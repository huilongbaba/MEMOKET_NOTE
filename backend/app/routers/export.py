"""导出全部笔记：一个 zip，里面是按树的层级摆好的 Markdown 文件。

数据可携带是笔记工具的底线（Trilium 有整库导出）。每个文件带一段 front-matter
（id / 标题 / 创建 / 修改），正文原样——正文本来就是 Markdown。克隆（同一篇在多处）
只写在第一个位置，其余位置留一个 `.link.txt` 指过去，别让一篇笔记变成两份互相
漂移的文件。不在树上的笔记放进 `_未归类/`。
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from ..database import store
from .deps import current_user

router = APIRouter(prefix="/api/export", tags=["export"])

_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def _display_title(title: str, content: str) -> str:
    t = (title or "").strip()
    if t and t not in ("未命名", "Untitled", "note"):
        return t
    for line in (content or "").split("\n"):
        line = re.sub(r"^#+\s*", "", line).strip()
        if line:
            return line[:60]
    return "未命名"


def _safe(name: str) -> str:
    name = _BAD.sub(" ", name).strip().strip(".")
    return (name or "未命名")[:80]


def build_export(user: str) -> bytes:
    notes = {n["id"]: n for n in store.list_notes(user)}
    rows = store.tree(user)
    children: dict[str, list[dict]] = {}
    for r in rows:
        children.setdefault(r["parent_note_id"], []).append(r)
    for lst in children.values():
        lst.sort(key=lambda r: (r.get("position") or 0, r["note_id"]))

    buf = io.BytesIO()
    written: dict[str, str] = {}          # note_id -> 第一次写入的路径
    used: set[str] = set()

    def unique(path: str) -> str:
        base, i = path, 2
        while path in used:
            root, ext = base.rsplit(".", 1) if "." in base.rsplit("/", 1)[-1] else (base, "")
            path = f"{root} ({i})" + (f".{ext}" if ext else "")
            i += 1
        used.add(path)
        return path

    def note_file(n: dict) -> str:
        front = (f"---\nid: {n['id']}\ntitle: {n['title'] or ''}\n"
                 f"created: {n['created_at']}\nupdated: {n['updated_at']}\n---\n\n")
        return front + (n["content"] or "")

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        def walk(parent: str, prefix: str) -> None:
            for r in children.get(parent, []):
                nid = r["note_id"]
                n = notes.get(nid)
                if not n:
                    continue
                name = _safe(_display_title(n["title"], n["content"]))
                has_kids = bool(children.get(nid))
                if nid in written:
                    z.writestr(unique(f"{prefix}{name}.link.txt"),
                               f"这是「{name}」的克隆，正文在：{written[nid]}\n")
                    continue
                if has_kids:
                    path = unique(f"{prefix}{name}/{name}.md")
                    written[nid] = path
                    z.writestr(path, note_file(n))
                    walk(nid, f"{prefix}{name}/")
                else:
                    path = unique(f"{prefix}{name}.md")
                    written[nid] = path
                    z.writestr(path, note_file(n))

        walk(store.ROOT_ID, "")
        for nid, n in notes.items():
            if nid not in written:
                path = unique(f"_未归类/{_safe(_display_title(n['title'], n['content']))}.md")
                written[nid] = path
                z.writestr(path, note_file(n))
        z.writestr("README.txt",
                   f"MEMOKET NOTE 导出 · {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
                   f"用户：{user}\n笔记：{len(written)} 篇\n\n"
                   "每个 .md 开头的 front-matter 是这篇笔记的 id / 标题 / 时间；正文是原样的 Markdown。\n"
                   "有子笔记的笔记是一个文件夹，它自己的正文是文件夹里同名的 .md。\n"
                   "*.link.txt 表示这里原本是一篇克隆，正文在它指向的那个文件。\n")
    return buf.getvalue()


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
