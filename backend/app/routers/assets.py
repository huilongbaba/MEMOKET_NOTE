"""笔记附件：图片、音频。

**为什么不内联成 data URI**：笔记正文存在 sqlite 里，一张手机拍的图 base64
之后两三兆，会跟着每一次自动保存、每一轮 harness 的上下文、每一次检索一起
搬来搬去——正文很快就没法读也没法编辑了。存成文件、正文里只留一个短链接。

按内容哈希命名：同一张图插两次只占一份，也不用担心重名。
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..database import assets as assets_store
from .deps import current_user

router = APIRouter(prefix="/api/assets", tags=["assets"])

MAX_BYTES = 32 * 1024 * 1024
# 只收这几类。**不做通用文件托管**：任意类型意味着这个目录随时可能被当成
# 分发任意内容的地方，而它是直接对外可读的。
ALLOWED = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
    "image/webp": ".webp", "image/svg+xml": ".svg",
    "audio/webm": ".webm", "audio/mpeg": ".mp3", "audio/wav": ".wav",
    "audio/x-wav": ".wav", "audio/mp4": ".m4a", "audio/ogg": ".ogg",
}
_INLINE_EXTENSIONS = frozenset((*ALLOWED.values(), ".avif"))
_SAFE_EXTENSION = re.compile(r"\.[a-z0-9]{1,12}$")


def _dir() -> Path:
    return assets_store.assets_dir()


def _attachment_name(filename: str | None) -> str:
    # Browsers normally send a basename; also handle Windows paths and remove
    # control characters before retaining a name for Content-Disposition.
    name = (filename or "附件").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(char for char in name if ord(char) >= 32 and ord(char) != 127)
    name = name.strip().strip(".")
    return name[:180] or "附件"


def _raster_type(data: bytes) -> tuple[str, str] | None:
    """Only inert raster formats may render inline; never trust the upload MIME."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", ".gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    if data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis"):
        return "image/avif", ".avif"
    return None


@router.post("/attachments")
async def upload_attachment(file: UploadFile = File(...), user: str = Depends(current_user)) -> dict:
    """An independent copy for a note; never a reference to a shelf/source path.

    Keep the existing hash.ext URL shape so Markdown/Obsidian exports include
    these files. Ownership/download metadata lives in a private subdirectory;
    it also retains uploads whose only reference is a durable desktop draft.
    """
    try:
        data = await file.read(MAX_BYTES + 1)
    finally:
        await file.close()
    if not data:
        raise HTTPException(400, "空文件")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "附件太大，单个文件上限 32MB")

    display_name = _attachment_name(file.filename)
    raster = _raster_type(data)
    if raster:
        ctype, ext = raster
        name = hashlib.sha256(data).hexdigest()[:24] + ext
        kind = "image"
    else:
        ext = Path(display_name).suffix.lower()
        # An SVG, or a file merely named .png/.mp3, must not inherit the legacy
        # inline-media route if its metadata is ever lost.
        if not _SAFE_EXTENSION.fullmatch(ext) or ext in _INLINE_EXTENSIONS:
            ext = ".bin"
        ctype = mimetypes.guess_type(display_name)[0] or "application/octet-stream"
        name = hashlib.sha256(display_name.encode("utf-8") + b"\0" + data).hexdigest()[:24] + ext
        kind = "file"

    # Mark both raster and generic assets, even when a raster already exists
    # from a legacy upload. Exclusive creation preserves metadata during dedup.
    metadata = _dir() / assets_store.ATTACHMENT_METADATA_DIR
    metadata.mkdir(exist_ok=True)
    try:
        with (metadata / f"{name}.json").open("x", encoding="utf-8") as record:
            json.dump({"name": display_name, "kind": kind, "retained_for_note": True}, record, ensure_ascii=False)
    except FileExistsError:
        pass

    path = _dir() / name
    if not path.exists():
        path.write_bytes(data)
    return {"url": f"/api/assets/{name}", "name": display_name, "kind": kind,
            "bytes": len(data), "content_type": ctype}


@router.post("")
async def upload(file: UploadFile = File(...), user: str = Depends(current_user)) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(400, "空文件")
    if len(data) > MAX_BYTES:
        raise HTTPException(400, f"文件太大（{len(data) // 1024 // 1024}MB），上限 32MB")
    ctype = (file.content_type or "").split(";")[0].strip().lower()
    ext = ALLOWED.get(ctype)
    if not ext:
        # 有些浏览器不给 content_type，退回按扩展名猜——猜不出来才拒
        guess = mimetypes.guess_type(file.filename or "")[0] or ""
        ext = ALLOWED.get(guess)
        ctype = guess
    if not ext:
        raise HTTPException(400, f"不支持的类型 {file.content_type or '未知'}，只收图片和音频")
    name = hashlib.sha256(data).hexdigest()[:24] + ext
    path = _dir() / name
    if not path.exists():                       # 同样的内容不重复存
        path.write_bytes(data)
    return {"url": f"/api/assets/{name}", "name": file.filename or name,
            "content_type": ctype, "bytes": len(data),
            "kind": "image" if ctype.startswith("image/") else "audio"}


@router.get("/{name}")
def fetch(name: str):
    # 只按文件名取，且文件名是我们自己生成的哈希——不接受路径分隔符，
    # 免得变成任意文件读取
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "非法文件名")
    path = _dir() / name
    if not path.is_file() or path.is_symlink():
        raise HTTPException(404, "not found")
    metadata = _dir() / assets_store.ATTACHMENT_METADATA_DIR / f"{name}.json"
    if path.suffix not in _INLINE_EXTENSIONS:
        display_name = name
        try:
            saved = json.loads(metadata.read_text(encoding="utf-8"))
            if isinstance(saved, dict) and isinstance(saved.get("name"), str):
                display_name = _attachment_name(saved["name"])
        except (OSError, ValueError):
            pass
        return FileResponse(path, filename=display_name, media_type="application/octet-stream",
                            headers={"X-Content-Type-Options": "nosniff",
                                     "Content-Security-Policy": "default-src 'none'; sandbox"})
    if path.suffix == ".avif":
        return FileResponse(path, media_type="image/avif", headers={"X-Content-Type-Options": "nosniff"})
    return FileResponse(path)
