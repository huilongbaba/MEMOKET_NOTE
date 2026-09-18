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
import os
from pathlib import Path
from urllib.parse import quote

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
#
# P2-fix（docs/_research/export-verification-P2.md §4）：
#   · 开跑前先探一次凭证（token 错整库不再转圈 24 秒才报）；循环里同一类错误连着来就停
#   · 失败信息是对面平台自己的 code/msg 翻成的中文（exporters.explain_*），不是 httpx 的英文 + MDN 链接
#   · 成功带 `url`（toast 的「打开」、信息面板的链接）；note_ids 里对不上的 id 带回 `missing`
#   · Notion / 飞书也有「对方改过就跳过」（remote_rev），跟 Obsidian 一样走 force

class ObsidianOut(BaseModel):
    vault_dir: str
    note_ids: list[str] = []
    force: bool = False


class NotionOut(BaseModel):
    token: str
    parent_page_id: str
    note_ids: list[str] = []
    force: bool = False


class FeishuOut(BaseModel):
    app_id: str
    app_secret: str
    folder_token: str = ""
    note_ids: list[str] = []
    force: bool = False


def obsidian_url(vault: Path, rel_path: str) -> str:
    """Obsidian 自己的 URI：`obsidian://open?path=<绝对路径>`——装了 Obsidian 的机器上点一下就打开那篇。"""
    return "obsidian://open?path=" + quote(str(vault / rel_path), safe="/")


def _missing(user: str, note_ids: list[str], files: list[exporters.ExportFile]) -> list[str]:
    """note_ids 里指了、库里却没有的（删掉了 / id 贴错了）。**不带回去前端就会把 0 篇解释成「没改过」**（§4.6）。"""
    have = {f.note_id for f in files}
    return [i for i in note_ids if i not in have]


@router.post("/obsidian")
def export_obsidian(body: ObsidianOut, user: str = Depends(current_user)) -> dict:
    """写进 vault 目录：`<树路径>/<标题>.md`，front-matter 带 memoket_id。文件被对方改过
    （内容不是我们上次写出去的那份）就跳过报冲突，除非 force。资产复制进 _assets/。"""
    if not body.vault_dir.strip():
        # `Path("").expanduser()` 是 `.`，is_dir() 为真——P2 实测把文件写进了后端进程的 cwd（§4.11）
        raise HTTPException(400, "vault 目录没填")
    vault = Path(body.vault_dir.strip()).expanduser()
    if not vault.is_absolute():
        raise HTTPException(400, f"vault 目录要是绝对路径：{vault}")
    if vault.is_file():
        raise HTTPException(400, f"这是一个文件，不是目录：{vault}")
    if not vault.is_dir():
        raise HTTPException(400, f"目录不存在：{vault}")
    if not os.access(vault, os.W_OK):
        raise HTTPException(400, f"这个目录写不进去：{vault}")   # 选到 /etc 这种目录之前是 500（第 248 轮实测）
    only = set(body.note_ids) or None
    files = exporters.render_tree(user, only)
    written, skipped, conflicts, urls = [], [], [], []
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
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f.content, encoding="utf-8")
        except OSError as exc:
            raise HTTPException(400, f"写不进 {f.path}：{exc.strerror or exc}")
        written.append(f.path)
        assets |= f.assets
        if f.note_id:
            store.record_remote(user, f.note_id, "obsidian", remote_id=store.content_sha(f.content), remote_path=f.path)
            urls.append({"note_id": f.note_id, "title": f.title, "url": obsidian_url(vault, f.path)})
    for name in sorted(assets):
        src = _assets_store.assets_dir() / name
        if src.is_file():
            dst = vault / "_assets" / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                dst.write_bytes(src.read_bytes())
    return {"written": len(written), "skipped": len(skipped), "conflicts": conflicts, "files": written[:50],
            "missing": _missing(user, body.note_ids, [f for f in files if f.note_id]),
            "urls": urls[:50], "url": urls[0]["url"] if len(urls) == 1 else ""}


def _pick(user: str, note_ids: list[str]) -> list[exporters.ExportFile]:
    only = set(note_ids) or None
    return [f for f in exporters.render_tree(user, only) if f.note_id]



def _need(value: str, msg: str) -> None:
    """凭证没填就当场说清楚，别让它一路跑到 HTTP 库里。

    第 612 轮实测：Notion 的 token 留空点「写入」，用户拿到的是
    `一篇都没导出去：plaud的优势分析: Illegal header value b'Bearer '`
    ——httpx 拼请求头时的内部报错，而他的真实错误是「token 没填」。飞书那边
    是 `飞书返回 10003：invalid param`，同样看不出要去填哪个框。而且不拦的话
    每一篇都会发一次注定失败的请求（这个库 23 篇，别人的库可能是几百篇）。

    Obsidian 那条早就在开跑前查目录了（第 248 轮），另外两条一直没补上。
    """
    if not (value or "").strip():
        raise HTTPException(400, msg)


def _needs_create(user: str, files: list, kind: str) -> bool:
    """这次有没有要**新建**的——父页面 / 文件夹 token 只有新建时才用得上，
    全是更新的那一次不该因为它空着就被拦下。"""
    return any(not (store.get_remote(user, f.note_id, kind) or {}).get("remote_id")
               for f in files)


def _probe(fn, what: str) -> None:
    """开跑前探一次凭证。**填错了在这儿就停**：P2 实测 token 错 + 整库 28 篇 = 转圈 23.7 秒后只报第一篇（§4.3）。"""
    try:
        fn()
    except exporters.RemoteError as exc:
        raise HTTPException(400, str(exc))
    except (httpx.HTTPError, KeyError) as exc:
        raise HTTPException(400, f"连不上{what}：{exc}")


class _Breaker:
    """循环里同一类错误连着来第二次就停：一篇 404 可能是那一篇的事，两篇同样的 404 就是凭证 / 父页面的事。"""

    def __init__(self) -> None:
        self.last = ""
        self.tripped = False

    def hit(self, exc: BaseException) -> None:
        key = f"{getattr(exc, 'status', 0)}:{getattr(exc, 'code', '')}" if isinstance(exc, exporters.RemoteError) else exc.__class__.__name__
        if key == self.last:
            self.tripped = True
        self.last = key

    def ok(self) -> None:
        self.last = ""


def _finish(created: list, updated: list, failed: list, conflicts: list, urls: list, missing: list, untried: int) -> dict:
    if not created and not updated and failed:
        raise HTTPException(400, "一篇都没导出去：" + failed[0] + (f"（还有 {untried} 篇没再试）" if untried else ""))
    return {"created": len(created), "updated": len(updated), "failed": failed, "conflicts": conflicts,
            "missing": missing, "untried": untried,
            "urls": urls[:50], "url": urls[0]["url"] if len(urls) == 1 else ""}


@router.post("/notion")
def export_notion(body: NotionOut, user: str = Depends(current_user)) -> dict:
    _need(body.token, "Notion 的 Integration token 没填")
    files = _pick(user, body.note_ids)
    missing = _missing(user, body.note_ids, files)
    w = exporters.NotionWriter(body.token)
    _probe(w.probe, " Notion")
    if _needs_create(user, files, "notion"):
        _need(body.parent_page_id, "父页面 id 没填——每篇会建成它下面的子页面")
        _probe(lambda: w.check_parent(body.parent_page_id), " Notion")
    created, updated, failed, conflicts, urls = [], [], [], [], []
    br = _Breaker()
    untried = 0
    for k, f in enumerate(files):
        if br.tripped:
            untried = len(files) - k
            break
        blocks = exporters.md_to_notion_blocks(f.content)
        try:
            prev = store.get_remote(user, f.note_id, "notion")
            if prev and prev.get("remote_id"):
                pid = prev["remote_id"]
                if prev.get("remote_rev") and not body.force and w.last_edited(pid) != prev["remote_rev"]:
                    conflicts.append(f.title)
                    continue
                r = w.replace_children(pid, f.title, blocks)
                updated.append(f.title)
            else:
                r = w.create_page(body.parent_page_id, f.title, blocks)
                created.append(f.title)
            store.record_remote(user, f.note_id, "notion", remote_id=r["id"], remote_path=r["url"], remote_rev=r["rev"])
            urls.append({"note_id": f.note_id, "title": f.title, "url": r["url"]})
            br.ok()
        except (httpx.HTTPError, KeyError, RuntimeError) as exc:
            failed.append(f"{f.title}: {exc}")
            br.hit(exc)
    return _finish(created, updated, failed, conflicts, urls, missing, untried)


@router.post("/feishu")
def export_feishu(body: FeishuOut, user: str = Depends(current_user)) -> dict:
    _need(body.app_id, "飞书的 App ID 没填")
    _need(body.app_secret, "飞书的 App Secret 没填")
    files = _pick(user, body.note_ids)
    missing = _missing(user, body.note_ids, files)
    if _needs_create(user, files, "feishu"):
        _need(body.folder_token, "文件夹 token 没填——新文档会建在它下面")
    w = exporters.FeishuWriter(body.app_id, body.app_secret)
    _probe(w.probe, "飞书")
    created, updated, failed, conflicts, urls = [], [], [], [], []
    br = _Breaker()
    untried = 0
    for k, f in enumerate(files):
        if br.tripped:
            untried = len(files) - k
            break
        children = exporters.md_to_feishu_children(f.content)
        try:
            prev = store.get_remote(user, f.note_id, "feishu")
            if prev and prev.get("remote_id"):
                did = prev["remote_id"]
                if prev.get("remote_rev") and not body.force and w.edited_time(did) != prev["remote_rev"]:
                    conflicts.append(f.title)
                    continue
                w.replace_children(did, children)
                updated.append(f.title)
                url = prev.get("remote_path") or w.doc_url(did)
            else:
                did = w.create_document(body.folder_token, f.title)
                w.replace_children(did, children)
                created.append(f.title)
                url = w.doc_url(did)
            store.record_remote(user, f.note_id, "feishu", remote_id=did, remote_path=url, remote_rev=w.edited_time(did))
            urls.append({"note_id": f.note_id, "title": f.title, "url": url})
            br.ok()
        except (httpx.HTTPError, KeyError, RuntimeError) as exc:
            failed.append(f"{f.title}: {exc}")
            br.hit(exc)
    return _finish(created, updated, failed, conflicts, urls, missing, untried)


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
