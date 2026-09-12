"""从别家笔记应用导入：Obsidian / Notion / Evernote / Apple Notes。

跟已有的「批量导入」（``/api/ingest/batch``）分开是有原因的——那条路是
「把手边几个文件拖进来」，它**拿不到原始日期，也不认识各家的私有语法**：

- 一整个 Obsidian vault 走那条路，几年的笔记全被记成导入当天，时间线失真
  （而事实的日期正是写作时判断 factual_grounding 的依据）
- ``[[wiki 链接]]``、``![[附件]]``、dataview 代码块会原样进知识库变成噪声
- ``.enex`` 根本不在支持的类型里

这条路负责：按来源洗内容 → 带上原始日期和源侧稳定 id → 同时落到笔记和知识库。
稳定 id 让**重跑导入自动变成增量同步**（KITE 拒绝重复 session_id 且不花 LLM 调用）。

洗内容的纯函数在 ``app/importers.py``，各来源的调研在
``docs/import-from-other-note-apps.md``，命令行版本是 ``scripts/import_notes.py``。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time

import httpx
from dataclasses import asdict
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from ..database import store
from ..util.config import get_settings
from ..database.ingest import importers
from memoket_kite import StorageError

from ..database.kite.kite_memory import UserMemory
from .schemas import IngestItemOut, IngestOut
from .deps import current_user
from ..database.ingest.chunking import chunks as _chunks

router = APIRouter(prefix="/api/import", tags=["import"])

_TERMINAL = {"done", "failed", "cancelled"}

MAX_FILES = 2000          # 一个 vault 几千篇很常见，比 batch 的 50 放宽很多
NOTION_VERSION = "2026-03-11"


def _land(user: str, notes: list[importers.ImportedNote], to: str,
          job_id: str, items: list[dict]) -> None:
    """把洗好的笔记落到笔记列表 / 知识库。每条一个 item，互不拖累。"""
    # 目录结构：a/b/c 逐层建成嵌套的笔记（有子节点的笔记就是文件夹）。
    # **文件夹笔记**：`项目/项目.md` 这种「文件名 = 所在目录名」的文件（我们自己的整库
    # 导出、Obsidian 的 folder notes 都这么摆）是那个文件夹的正文，不另建一篇同名子笔记。
    # 第一版这里调的 store.create_folder 根本不存在——带目录的导入每条都静默失败。
    folders: dict[str, str] = {}
    folder_body: dict[str, importers.ImportedNote] = {}
    for note in notes:
        if note.folder and note.title == note.folder.rsplit("/", 1)[-1]:
            folder_body.setdefault(note.folder, note)

    def folder_id(path: str) -> str | None:
        if not path:
            return None
        if path not in folders:
            parent = folder_id(path.rsplit("/", 1)[0]) if "/" in path else None
            name = path.rsplit("/", 1)[-1]
            body = folder_body.get(path)
            folders[path] = store.create_note(user, name, body.content if body else "",
                                              parent or store.ROOT_ID)["id"]
        return folders[path]

    for note, item in zip(notes, items):
        item_id = item["id"]
        try:
            if store.is_cancel_requested(job_id):
                store.set_item(item_id, "cancelled")
                continue
            store.set_item(item_id, "chunking")
            store.update_job_from_items(job_id)   # 不然 job 一直停在 queued
            store.mark_job_started(job_id)
            sha = store.content_sha(note.content)
            existing = store.find_note_by_source(user, note.source, note.source_id)
            note_state = "new"        # new / same / updated / local-modified
            if to in ("both", "notes"):
                fid = folder_id(note.folder)
                if folder_body.get(note.folder) is note:
                    pass                                   # 已经是那个文件夹的正文
                elif existing is None:
                    n = store.create_note(user, note.title, note.content, fid or store.ROOT_ID)
                    store.set_note_source(user, n["id"], note.source, note.source_id, sha)
                elif existing.get("source_sha") == sha:
                    note_state = "same"                    # 同一份导第二次：不再建一篇
                elif (existing.get("updated_at") or "") > (existing.get("imported_at") or ""):
                    note_state = "local-modified"          # 本地改过：不动，说清楚
                else:
                    store.update_note_from_source(user, existing["id"], note.title, note.content, sha)
                    note_state = "updated"
            facts, skipped = 0, 0
            if to in ("both", "kb"):
                mem = UserMemory(user)
                # 源侧改过：先删这份上次抽的 session 再重抽，不然稳定 id 会让改过的内容被当「已导入」跳过。
                # 本地改过的那种也按源侧重抽（知识库跟源走，正文留给用户），并把 sha 记成源侧的。
                if note_state in ("updated", "local-modified"):
                    mem.remove_sessions(f"{note.source}-{note.source_id}-")
                    if note_state == "local-modified" and existing:
                        store.set_note_source(user, existing["id"], note.source, note.source_id, sha)
                # source_id 是源侧稳定的，所以 session_id 也稳定 —— 重跑导入时
                # KITE 直接跳过已有的，不花 LLM 调用，等于自动增量。
                stem = f"{note.source}-{note.source_id}"
                when = note.date or importers.today()
                chunks = _chunks(note.content)
                store.set_item(item_id, "remembering", chunks_total=len(chunks), chunks_done=0)
                for i, chunk in enumerate(chunks):
                    if store.is_cancel_requested(job_id):
                        break
                    try:
                        t_chunk = time.perf_counter()
                        facts += mem.remember([{"role": "user", "content": chunk}],
                                              session_id=f"{stem}-{i}", date=when,
                                              title=note.title)
                        store.bump_job_chunk(job_id, int((time.perf_counter() - t_chunk) * 1000), len(chunk))
                    except StorageError as exc:
                        # **"已存在" 是成功信号，不是失败。** 稳定 session_id 的
                        # 全部意义就是重跑时让 KITE 认出已导入的内容并跳过（不花
                        # LLM 调用）——第一版把它当异常抛出去，于是"第二次导入同一个
                        # vault"整批报错，恰好把增量同步这个卖点变成了故障。
                        if "already exists" not in str(exc):
                            raise
                        skipped += 1
                        store.set_item(item_id, "remembering", facts=facts, chunks_done=i + 1)
                        continue
                    store.set_item(item_id, "remembering", facts=facts, chunks_done=i + 1)
                    store.update_job_from_items(job_id)
            state_note = {"same": "这篇之前导过、内容没变", "updated": "源侧改过，正文已更新",
                          "local-modified": "源侧改过，但本地也改过——正文没动，知识库按源侧重抽"}.get(note_state, "")
            kb_note = (f"已导入过，跳过 {skipped} 块" if skipped and not facts
                       else (f"新增 {facts} 条，另有 {skipped} 块此前已导入" if skipped else ""))
            store.set_item(item_id, "done", facts=facts,
                           detail="；".join(x for x in (state_note, kb_note) if x))
        except Exception as exc:              # noqa: BLE001 — 单条失败不能拖垮整批
            store.set_item(item_id, "failed", detail=f"{type(exc).__name__}: {exc}")
        store.update_job_from_items(job_id)
    store.update_job_from_items(job_id)


def _reject_if_busy(user: str, except_job: str = "") -> None:
    """同一个用户同时只跑一个导入任务。

    KITE 的写入是串行的，第二个任务会**阻塞在写锁里**——它连自己的取消检查点
    都执行不到，于是界面上点取消完全没反应（实测：第二个任务卡了两分钟，
    items 全程 queued、facts 一直是 0）。与其让用户对着一个假死的进度条，
    不如直接说清楚上一个还没跑完。
    """
    for j in store.list_jobs(user, 10):
        if j["id"] == except_job:
            continue
        # **看 item 而不是 job 状态。** update_job_from_items 只要有一条 item
        # 失败就把 job 标成 error，无论其余的跑没跑完——用 job 状态判断会
        # 把"带着一条失败跑完了"和"出错了还在跑"混为一谈。真正的判据是
        # 「还有没有 item 处在非终态」。
        if any(it["status"] not in _TERMINAL for it in store.get_items(j["id"])):
            raise HTTPException(
                409, "上一个导入任务还没结束（导入是串行的）。等它跑完，"
                     "或者先点取消。")


def _payload_dir() -> Path:
    d = Path(get_settings().kite_data_dir) / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _queue(user: str, notes: list[importers.ImportedNote], to: str,
           bg: BackgroundTasks) -> IngestOut:
    if not notes:
        raise HTTPException(400, "没有可导入的内容（文件为空、或者全被最小长度过滤掉了）")
    job_id, items = store.create_batch_job(
        user, [{"filename": n.title[:80], "kind": n.source} for n in notes])
    # 清洗好的笔记落盘：进程重启后 job 还在，能从没跑完的 item 继续（docs/import-sync-plan.md §4.1）
    payload = _payload_dir() / f"{job_id}.json"
    payload.write_text(json.dumps({"user": user, "to": to, "notes": [asdict(n) for n in notes],
                                   "items": [it["id"] for it in items]}, ensure_ascii=False),
                       encoding="utf-8")
    store.set_job_payload(job_id, str(payload))
    # 开始前就说清这一批要跑多久、大概多少 token：412 篇的用户点下去之前应该知道这是一小时的事
    n_chunks = sum(len(_chunks(n.content)) for n in notes)
    est = store.estimate(n_chunks, sum(len(n.content) for n in notes), store.avg_chunk_ms(user))
    bg.add_task(_land, user, notes, to, job_id, items)
    return IngestOut(job_id=job_id, status="queued",
                     items=[IngestItemOut(**it) for it in items], estimate=est)


@router.post("/jobs/{job_id}/resume", response_model=IngestOut)
def resume_job(job_id: str, bg: BackgroundTasks, user: str = Depends(current_user)):
    """断点续跑：只跑还没到终态的 item。已经 done 的 item 的 session 本来就在，KITE 会拒重复
    ——所以块级也是天然断点，一篇导到第 3 块崩了，前 2 块被跳过、不花钱。"""
    job = store.get_job(job_id)
    if not job or job["user_id"] != user:
        raise HTTPException(404, "job not found")
    if not job.get("payload_path") or not Path(job["payload_path"]).exists():
        raise HTTPException(400, "这个任务没有落盘的内容，续不了（批量上传的文件不落盘）")
    if job["status"] in ("queued", "running", "cancelling"):
        raise HTTPException(409, "这个任务正在跑")          # 连点两次「继续」不能起两个后台任务
    _reject_if_busy(user, except_job=job_id)
    data = json.loads(Path(job["payload_path"]).read_text(encoding="utf-8"))
    notes = [importers.ImportedNote(**n) for n in data["notes"]]
    by_id = {it["id"]: it for it in store.get_items(job_id)}
    todo_notes, todo_items = [], []
    for n, item_id in zip(notes, data["items"]):
        it = by_id.get(item_id)
        if it and it["status"] not in ("done", "cancelled"):
            store.set_item(item_id, "queued", detail="")
            todo_notes.append(n)
            todo_items.append(it)
    if not todo_notes:
        store.update_job_from_items(job_id)
        raise HTTPException(400, "没有需要继续的条目")
    store.set_job(job_id, "running", facts=job["facts"])
    bg.add_task(_land, user, todo_notes, data["to"], job_id, todo_items)
    return IngestOut(job_id=job_id, status="running", items=[IngestItemOut(**it) for it in todo_items])


@router.post("/files", response_model=IngestOut)
async def import_files(bg: BackgroundTasks,
                       files: list[UploadFile] = File(...),
                       source: str = Form("obsidian"),
                       to: str = Form("both"),
                       min_chars: int = Form(10),
                       user: str = Depends(current_user)):
    """Obsidian vault（一堆 .md）或 Evernote 的 .enex。

    前端用 ``<input webkitdirectory>`` 选整个 vault 时，浏览器会把相对路径放在
    ``webkitRelativePath`` 里并作为文件名传上来——**那正是我们要的文件夹结构和
    稳定 id**，所以这里按文件名里的 ``/`` 还原目录层级。
    """
    _reject_if_busy(user)
    if source not in ("obsidian", "evernote"):
        raise HTTPException(400, f"这个接口只收 obsidian / evernote，收到 {source!r}")
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"一次最多 {MAX_FILES} 个文件")

    notes: list[importers.ImportedNote] = []
    for f in files:
        name = f.filename or "note"
        data = await f.read()
        if not data:
            continue
        if source == "evernote":
            if not name.lower().endswith(".enex"):
                continue
            notes += importers.parse_enex(data)
            continue
        if not name.lower().endswith((".md", ".markdown", ".txt")):
            continue
        # .obsidian/（配置）、.trash/（回收站）不是内容
        rel = name.replace("\\", "/")
        if any(p.startswith(".") for p in rel.split("/")):
            continue
        try:
            raw = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        meta, body = importers.parse_frontmatter(raw)
        body = importers.clean_obsidian(body)
        if not body.strip():
            continue
        stem = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        # 上传上来的文件拿不到 mtime（浏览器不传），日期只能靠 frontmatter；
        # 拿不到就留空，由 _land 退回今天——**不猜**。
        notes.append(importers.ImportedNote(
            title=meta.get("title") or stem, content=body,
            date=importers.normalize_date(meta.get("created") or meta.get("date")),
            source="obsidian",
            source_id=hashlib.sha1(rel.encode()).hexdigest()[:16],
            folder=parent))

    if min_chars:
        notes = [n for n in notes if len(n.content.strip()) >= min_chars]
    return _queue(user, notes, to, bg)


@router.post("/notion", response_model=IngestOut)
def import_notion(bg: BackgroundTasks, token: str = Form(...), to: str = Form("both"),
                  limit: int = Form(0), user: str = Depends(current_user)):
    """Notion 官方 Markdown API（2026-02 上线），一次调用拿一页完整 markdown。

    取内容是同步做的（要先知道有多少页才能建任务项），落库在后台。
    """
    _reject_if_busy(user)
    nh = {"Authorization": f"Bearer {token.strip()}",
          "Notion-Version": NOTION_VERSION, "Content-Type": "application/json"}
    pages, cursor = [], None
    try:
        while True:
            body = {"filter": {"property": "object", "value": "page"}, "page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            r = httpx.post("https://api.notion.com/v1/search", headers=nh,
                           json=body, timeout=60)
            r.raise_for_status()
            data = r.json()
            pages += data.get("results", [])
            if not data.get("has_more") or (limit and len(pages) >= limit):
                break
            cursor = data["next_cursor"]
            time.sleep(0.34)                  # 限流 3 请求/秒
    except httpx.HTTPStatusError as exc:
        raise HTTPException(400, f"Notion 拒绝了这个 token：{exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"连不上 Notion：{exc}") from exc

    if limit:
        pages = pages[:limit]
    notes: list[importers.ImportedNote] = []
    skipped = 0
    for i, page in enumerate(pages):
        pid = page["id"]
        try:
            m = httpx.get(f"https://api.notion.com/v1/pages/{pid}/markdown",
                          headers=nh, timeout=120)
            m.raise_for_status()
            md = (m.json().get("markdown") or "").strip()
        except httpx.HTTPError:
            # 最常见的原因是这一页没有 Connect 给这个 integration
            skipped += 1
            continue
        if md:
            notes.append(importers.ImportedNote(
                title=_notion_title(page) or "无标题", content=md,
                date=importers.normalize_date(page.get("created_time")),
                source="notion", source_id=pid.replace("-", "")))
        if i % 3 == 2:
            time.sleep(0.34)
    if not notes and skipped:
        raise HTTPException(400, f"{skipped} 个页面都取不到内容——通常是没有在 Notion 里"
                                 "把它们 Connect 给这个 integration")
    return _queue(user, notes, to, bg)


def _notion_title(page: dict) -> str:
    for prop in (page.get("properties") or {}).values():
        if prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title", [])).strip()
    return ""


# ---------------------------------------------------------------- Apple Notes

# AppleScript 是 Apple 认可的唯一自动化路径：不需要开发者模式、不碰 TCC、
# 不会破坏 iCloud 同步。**不走 NoteStore.sqlite** —— 那里正文是 gzip 过的
# protobuf、schema 随系统版本变，而且写它会破坏 iCloud 同步。
#
# **必须遍历 folders 再取 notes of f**，不能直接 ``repeat with n in notes`` 再
# 问 ``container of n``——后者在实机上每一条都抛异常（"不能获得 name of
# container of..."），而外面套着 try，结果是**静默返回零条**：接口不报错、
# 就是导不出东西。遍历文件夹顺带把文件夹名也拿到了。
#
# 之所以能在服务端跑，是因为 memoket-note 的后端就跑在用户自己的 Mac 上
# （localhost）。部署到远端服务器时这条路自然不可用，所以有 /apple/available
# 让前端先问一句，而不是给用户一个点了必然失败的按钮。
_APPLESCRIPT = r"""
set out to {}
tell application "Notes"
    repeat with f in folders
        set fname to name of f
        repeat with n in notes of f
            try
                set end of out to ((id of n) & "\t" & (name of n) & "\t" & ((modification date of n) as string) & "\t" & fname & "\t" & (body of n))
            end try
        end repeat
    end repeat
end tell
set AppleScript's text item delimiters to "\n<<<REC>>>\n"
return out as string
"""


def _apple_available() -> tuple[bool, str]:
    if sys.platform != "darwin":
        return False, "后端不在 macOS 上运行（Apple Notes 没有公开 API，只能在本机导出）"
    if not shutil.which("osascript"):
        return False, "找不到 osascript"
    return True, ""


@router.get("/apple/available")
def apple_available(user: str = Depends(current_user)) -> dict:
    """前端先问一句能不能导，别给一个点了必然失败的按钮。"""
    ok, why = _apple_available()
    return {"available": ok, "reason": why}


@router.post("/apple", response_model=IngestOut)
def import_apple(bg: BackgroundTasks, to: str = Form("both"), limit: int = Form(0),
                 user: str = Depends(current_user)):
    _reject_if_busy(user)
    ok, why = _apple_available()
    if not ok:
        raise HTTPException(400, why)
    try:
        r = subprocess.run(["osascript", "-e", _APPLESCRIPT],
                           capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, "导出超时（笔记太多？先用 --limit 试小批）") from exc
    if r.returncode != 0:
        # 第一次跑一定会弹「允许控制 Notes.app」的授权框，用户没点就是这个错。
        # 说清楚是授权问题，不要只把 osascript 的原文抛出去。
        raise HTTPException(
            400, "读不到 Apple Notes。第一次导入时 macOS 会弹一个「允许控制"
                 "「备忘录」」的授权框，需要你点允许（系统设置 → 隐私与安全性 →"
                 f"自动化）。原始错误：{r.stderr.strip()[:200]}")

    notes: list[importers.ImportedNote] = []
    for rec in r.stdout.split("\n<<<REC>>>\n"):
        parts = rec.split("\t", 4)
        if len(parts) < 5:
            continue
        nid, title, mdate, folder, body_html = parts
        body = importers.html_to_markdown(body_html)
        if not body.strip():
            continue
        notes.append(importers.ImportedNote(
            title=title.strip() or "无标题", content=body,
            date=importers.normalize_date(mdate), source="apple",
            source_id=hashlib.sha1(nid.encode()).hexdigest()[:16],
            folder=folder.strip()))
        if limit and len(notes) >= limit:
            break
    return _queue(user, notes, to, bg)
