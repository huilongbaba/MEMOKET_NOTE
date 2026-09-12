"""笔记附件：图片、音频。

**为什么不内联成 data URI**：笔记正文存在 sqlite 里，一张手机拍的图 base64
之后两三兆，会跟着每一次自动保存、每一轮 harness 的上下文、每一次检索一起
搬来搬去——正文很快就没法读也没法编辑了。存成文件、正文里只留一个短链接。

按内容哈希命名：同一张图插两次只占一份，也不用担心重名。
"""

from __future__ import annotations

import hashlib
import mimetypes
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


def _dir() -> Path:
    return assets_store.assets_dir()


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
    if not path.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(path)
