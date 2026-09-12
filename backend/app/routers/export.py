"""导出全部笔记：一个 zip，里面是按树的层级摆好的 Markdown 文件。

数据可携带是笔记工具的底线（Trilium 有整库导出）。每个文件带一段 front-matter
（id / 标题 / 创建 / 修改），正文原样——正文本来就是 Markdown。克隆（同一篇在多处）
只写在第一个位置，其余位置留一个 `.link.txt` 指过去，别让一篇笔记变成两份互相
漂移的文件。不在树上的笔记放进 `_未归类/`。
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from ..database import exporters, store
from ..database import assets as _assets_store
from .deps import current_user

router = APIRouter(prefix="/api/export", tags=["export"])

def build_export(user: str) -> bytes:
    files = exporters.render_tree(user)
    buf = io.BytesIO()
    assets_needed: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.writestr(f.path, f.content)
            assets_needed |= f.assets
        for name in sorted(assets_needed):
            path = _assets_store.assets_dir() / name   # 运行时取：测试会替换目录
            if path.is_file():
                z.write(path, f"_assets/{name}")
        z.writestr("README.txt",
                   f"MEMOKET NOTE 导出 · {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
                   f"用户：{user}\n笔记：{sum(1 for f in files if f.note_id)} 篇\n\n"
                   "每个 .md 开头的 front-matter 是这篇笔记的 id / 标题 / 时间；正文是原样的 Markdown。\n"
                   "有子笔记的笔记是一个文件夹，它自己的正文是文件夹里同名的 .md。\n"
                   "*.link.txt 表示这里原本是一篇克隆，正文在它指向的那个文件。\n"
                   "正文里引用的图片 / 录音在 _assets/ 里，链接已改成相对路径。\n")
    return buf.getvalue()


# ---------------------------------------------------------------- 导回
#
# 导回是「视图」：这里是真相，按 memoket_id 覆盖远端副本；远端改过先提示不覆盖
# （docs/import-sync-plan.md §2）。三条路都记 note_remotes。

class ObsidianOut(BaseModel):
    vault_dir: str
    note_ids: list[str] = []
    force: bool = False


class NotionOut(BaseModel):
    token: str
    parent_page_id: str
    note_ids: list[str] = []


class FeishuOut(BaseModel):
    app_id: str
    app_secret: str
    folder_token: str = ""
    note_ids: list[str] = []


@router.post("/obsidian")
def export_obsidian(body: ObsidianOut, user: str = Depends(current_user)) -> dict:
    """写进 vault 目录：`<树路径>/<标题>.md`，front-matter 带 memoket_id。文件被对方改过
    （内容不是我们上次写出去的那份）就跳过报冲突，除非 force。资产复制进 _assets/。"""
    vault = Path(body.vault_dir).expanduser()
    if not vault.is_dir():
        raise HTTPException(400, f"目录不存在：{vault}")
    only = set(body.note_ids) or None
    files = exporters.render_tree(user, only)
    written, skipped, conflicts = [], [], []
    assets: set[str] = set()
    for f in files:
        target = vault / f.path
        if f.note_id:
            prev = store.get_remote(user, f.note_id, "obsidian")
            current = target.read_text(encoding="utf-8", errors="replace") if target.exists() else None
            if current == f.content:
                skipped.append(f.path)
                store.record_remote(user, f.note_id, "obsidian", remote_id=store.content_sha(f.content), remote_path=f.path)
                continue
            # 对方改过 = 文件内容不是我们上次写出去的那份（remote_id 记的是写出内容的 sha）
            if current is not None and prev and prev.get("remote_id") and store.content_sha(current) != prev["remote_id"] and not body.force:
                conflicts.append(f.path)
                continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.content, encoding="utf-8")
        written.append(f.path)
        assets |= f.assets
        if f.note_id:
            store.record_remote(user, f.note_id, "obsidian", remote_id=store.content_sha(f.content), remote_path=f.path)
    for name in sorted(assets):
        src = _assets_store.assets_dir() / name
        if src.is_file():
            dst = vault / "_assets" / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                dst.write_bytes(src.read_bytes())
    return {"written": len(written), "skipped": len(skipped), "conflicts": conflicts, "files": written[:50]}


def _pick(user: str, note_ids: list[str]) -> list[exporters.ExportFile]:
    only = set(note_ids) or None
    return [f for f in exporters.render_tree(user, only) if f.note_id]


@router.post("/notion")
def export_notion(body: NotionOut, user: str = Depends(current_user)) -> dict:
    w = exporters.NotionWriter(body.token)
    created, updated, failed = [], [], []
    for f in _pick(user, body.note_ids):
        blocks = exporters.md_to_notion_blocks(f.content)
        try:
            prev = store.get_remote(user, f.note_id, "notion")
            if prev and prev.get("remote_id"):
                w.replace_children(prev["remote_id"], f.title, blocks)
                updated.append(f.title)
                store.record_remote(user, f.note_id, "notion", remote_id=prev["remote_id"])
            else:
                pid = w.create_page(body.parent_page_id, f.title, blocks)
                created.append(f.title)
                store.record_remote(user, f.note_id, "notion", remote_id=pid)
        except (httpx.HTTPError, KeyError, RuntimeError) as exc:
            failed.append(f"{f.title}: {exc}")
    if not created and not updated and failed:
        raise HTTPException(400, "一篇都没导出去：" + failed[0])
    return {"created": len(created), "updated": len(updated), "failed": failed}


@router.post("/feishu")
def export_feishu(body: FeishuOut, user: str = Depends(current_user)) -> dict:
    w = exporters.FeishuWriter(body.app_id, body.app_secret)
    created, updated, failed = [], [], []
    for f in _pick(user, body.note_ids):
        children = exporters.md_to_feishu_children(f.content)
        try:
            prev = store.get_remote(user, f.note_id, "feishu")
            if prev and prev.get("remote_id"):
                w.replace_children(prev["remote_id"], children)
                updated.append(f.title)
                store.record_remote(user, f.note_id, "feishu", remote_id=prev["remote_id"])
            else:
                did = w.create_document(body.folder_token, f.title)
                w.replace_children(did, children)
                created.append(f.title)
                store.record_remote(user, f.note_id, "feishu", remote_id=did)
        except (httpx.HTTPError, KeyError, RuntimeError) as exc:
            failed.append(f"{f.title}: {exc}")
    if not created and not updated and failed:
        raise HTTPException(400, "一篇都没导出去：" + failed[0])
    return {"created": len(created), "updated": len(updated), "failed": failed}


@router.get("/remotes/{note_id}")
def note_remotes(note_id: str, user: str = Depends(current_user)) -> list[dict]:
    return store.list_remotes(user, note_id)


@router.get("/markdown")
def export_markdown(user: str = Depends(current_user),
                    user_q: str | None = Query(None, alias="user")):
    """整库导出成 zip。浏览器直接导航到这个地址下载，带不上请求头，所以也认
    `?user=`——桌面版是单用户，这里不构成越权面。"""
    who = user_q or user
    data = build_export(who)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="memoket-note-{stamp}.zip"'})
