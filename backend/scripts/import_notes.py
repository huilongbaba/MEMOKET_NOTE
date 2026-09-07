"""从别家笔记应用导入到 memoket-note。

    python scripts/import_notes.py obsidian ~/Documents/MyVault --user me
    python scripts/import_notes.py notion   --token secret_xxx --user me
    python scripts/import_notes.py evernote ~/Downloads/笔记本.enex --user me
    python scripts/import_notes.py apple    --user me          # 只能在 macOS 本机
    …任意一个加 --dry-run 先看会导入什么，不写任何东西

**两个落点**（默认两个都进，见 docs/import-from-other-note-apps.md §1）：

    知识库   POST /api/ingest/text  —— 抽成事实，以后写作时被检索到
    笔记     POST /api/notes        —— 一篇可编辑的文档，出现在列表里

    --to kb     只进知识库（导别人的资料、会议记录）
    --to notes  只进笔记列表（纯搬家，先不花抽取的钱）

**重跑是增量的**：每条笔记都带源侧稳定的 source_id，KITE 拒绝重复的 session_id
且不花 LLM 调用，所以同一个 vault 反复跑只会处理新增和改动的部分。

洗内容的纯函数在 app/importers.py，各来源的坑记在
docs/import-from-other-note-apps.md。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.importers import (ImportedNote, clean_obsidian, html_to_markdown,  # noqa: E402
                           normalize_date, parse_enex, parse_frontmatter, today)

BASE = os.environ.get("MEMOKET_NOTE_BASE", "http://localhost:8000")


# ---------------------------------------------------------------- 四个来源


def from_obsidian(vault: Path) -> list[ImportedNote]:
    """vault 就是一堆 .md，没有 API 也没有鉴权。"""
    out: list[ImportedNote] = []
    for md in sorted(vault.rglob("*.md")):
        rel = md.relative_to(vault)
        # .obsidian/（配置）、.trash/（回收站）里的不是内容
        if any(p.startswith(".") for p in rel.parts):
            continue
        try:
            raw = md.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            print(f"  跳过 {rel}: {exc}")
            continue
        meta, body = parse_frontmatter(raw)
        body = clean_obsidian(body)
        if not body.strip():
            continue
        # frontmatter 的 created/date 优先，没有就用文件的修改时间——**不要用
        # 今天**，那会把整个 vault 压成同一天
        when = (normalize_date(meta.get("created") or meta.get("date"))
                or time.strftime("%Y-%m-%d", time.localtime(md.stat().st_mtime)))
        out.append(ImportedNote(
            title=meta.get("title") or md.stem,
            content=body, date=when, source="obsidian",
            # 相对路径是 vault 内稳定的标识；哈希一下免得路径里的空格/中文
            # 进到 session_id 里
            source_id=hashlib.sha1(rel.as_posix().encode()).hexdigest()[:16],
            folder=rel.parent.as_posix() if rel.parent.as_posix() != "." else ""))
    return out


NOTION_VERSION = "2026-03-11"


def from_notion(token: str, *, limit: int = 0) -> list[ImportedNote]:
    """官方 Markdown API（2026-02 上线），一次调用拿一页的完整 markdown。"""
    nh = {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION,
          "Content-Type": "application/json"}
    pages, cursor = [], None
    while True:
        body = {"filter": {"property": "object", "value": "page"}, "page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        r = httpx.post("https://api.notion.com/v1/search", headers=nh, json=body, timeout=60)
        r.raise_for_status()
        data = r.json()
        pages += data.get("results", [])
        if not data.get("has_more") or (limit and len(pages) >= limit):
            break
        cursor = data["next_cursor"]
        time.sleep(0.34)                      # 限流 3 请求/秒
    if limit:
        pages = pages[:limit]

    out: list[ImportedNote] = []
    for i, page in enumerate(pages):
        pid = page["id"]
        try:
            m = httpx.get(f"https://api.notion.com/v1/pages/{pid}/markdown",
                          headers=nh, timeout=120)
            m.raise_for_status()
            md = m.json().get("markdown") or ""
        except httpx.HTTPError as exc:
            # 最常见的原因是这一页没有 Connect 给这个 integration —— 说清楚，
            # 别让用户以为是「导了但是空的」
            print(f"  取不到 {pid}: {exc}（这一页可能没共享给该 integration）")
            continue
        if md.strip():
            out.append(ImportedNote(
                title=_notion_title(page) or "无标题", content=md,
                date=normalize_date(page.get("created_time")), source="notion",
                source_id=pid.replace("-", "")))
        if i % 3 == 2:
            time.sleep(0.34)                  # 同样受 3 请求/秒 限制
    return out


def _notion_title(page: dict) -> str:
    for prop in (page.get("properties") or {}).values():
        if prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title", [])).strip()
    return ""


def from_evernote(enex: Path, *, limit: int = 0) -> list[ImportedNote]:
    return parse_enex(enex.read_bytes(), limit=limit)


_APPLESCRIPT = r'''
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
'''


def from_apple_notes(*, limit: int = 0) -> list[ImportedNote]:
    """AppleScript 是 Apple 认可的唯一自动化路径。

    不走 NoteStore.sqlite：正文是 gzip 过的 protobuf、schema 随系统版本变，
    而且写它会破坏 iCloud 同步。**首次运行会弹授权框，必须用户手动点** ——
    这也是它做不成无人值守服务的原因。
    """
    if sys.platform != "darwin":
        raise SystemExit("Apple Notes 只能在 macOS 上导出")
    r = subprocess.run(["osascript", "-e", _APPLESCRIPT],
                       capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise SystemExit(f"osascript 失败（第一次跑要在弹窗里授权）：{r.stderr.strip()[:300]}")
    out: list[ImportedNote] = []
    for rec in r.stdout.split("\n<<<REC>>>\n"):
        parts = rec.split("\t", 4)
        if len(parts) < 5:
            continue
        nid, title, mdate, folder, body_html = parts
        body = html_to_markdown(body_html)
        if not body.strip():
            continue
        out.append(ImportedNote(
            title=title.strip() or "无标题", content=body,
            date=normalize_date(mdate) or today(), source="apple",
            source_id=hashlib.sha1(nid.encode()).hexdigest()[:16], folder=folder.strip()))
        if limit and len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- 落库


def push(notes: list[ImportedNote], user: str, to: str, *, dry: bool) -> None:
    h = {"X-User-Id": user, "Content-Type": "application/json"}
    folders: dict[str, str] = {}
    ok_kb = ok_note = 0
    for i, n in enumerate(notes, 1):
        head = f"[{i}/{len(notes)}] {n.title[:32]} · {n.date or '无日期'} · {len(n.content)}字"
        if dry:
            print(f"  {head}")
            continue
        if to in ("both", "notes"):
            fid = None
            if n.folder:
                if n.folder not in folders:
                    folders[n.folder] = httpx.post(
                        f"{BASE}/api/folders", headers=h,
                        json={"name": n.folder}, timeout=30).json()["id"]
                fid = folders[n.folder]
            httpx.post(f"{BASE}/api/notes", headers=h, timeout=60,
                       json={"title": n.title, "content": n.content, "folder_id": fid})
            ok_note += 1
        if to in ("both", "kb"):
            httpx.post(f"{BASE}/api/ingest/text", headers=h, timeout=300,
                       json={"content": n.content, "title": n.title,
                             "source": n.source, "date": n.date or today(),
                             "source_id": n.source_id})
            ok_kb += 1
        print(f"  {head}")
    if not dry:
        print(f"\n笔记 {ok_note} 篇 · 知识库任务 {ok_kb} 个（抽取在后台跑，"
              f"进度看 GET /api/ingest/jobs）")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", choices=("obsidian", "notion", "evernote", "apple"))
    ap.add_argument("path", nargs="?", help="vault 目录 / .enex 文件")
    ap.add_argument("--user", default="default", help="X-User-Id（每个用户一个独立知识库）")
    ap.add_argument("--token", default=os.environ.get("NOTION_TOKEN", ""))
    ap.add_argument("--to", choices=("both", "kb", "notes"), default="both")
    ap.add_argument("--limit", type=int, default=0, help="只导前 N 条，先小范围验证")
    # 一条只有几个字的笔记进知识库要花一次 LLM 调用，抽出来的必然是垃圾。
    # 默认挡掉，但留出口——有人确实拿笔记记单词。
    ap.add_argument("--min-chars", type=int, default=10,
                    help="短于这个长度的笔记不导入（默认 10，设 0 全导）")
    ap.add_argument("--dry-run", action="store_true", help="只打印会导入什么，不写任何东西")
    a = ap.parse_args()

    if a.source == "obsidian":
        if not a.path:
            ap.error("obsidian 需要 vault 目录")
        notes = from_obsidian(Path(a.path).expanduser())
    elif a.source == "notion":
        if not a.token:
            ap.error("notion 需要 --token 或环境变量 NOTION_TOKEN")
        notes = from_notion(a.token, limit=a.limit)
    elif a.source == "evernote":
        if not a.path:
            ap.error("evernote 需要 .enex 文件")
        notes = from_evernote(Path(a.path).expanduser(), limit=a.limit)
    else:
        notes = from_apple_notes(limit=a.limit)

    if a.min_chars:
        before = len(notes)
        notes = [n for n in notes if len(n.content.strip()) >= a.min_chars]
        if before != len(notes):
            print(f"（跳过 {before - len(notes)} 条短于 {a.min_chars} 字的）")
    if a.limit:
        notes = notes[: a.limit]
    print(f"{a.source}: 找到 {len(notes)} 条"
          + ("（dry-run，不写任何东西）" if a.dry_run else f" → {a.user}"))
    if not notes:
        return
    push(notes, a.user, a.to, dry=a.dry_run)


if __name__ == "__main__":
    main()
