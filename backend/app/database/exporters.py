"""导回（docs/import-sync-plan.md §2）：把笔记按目标平台的规则渲染出去。

原则：导回是「视图」，不是双向同步的另一半——这里的笔记是真相，导回带上 `memoket_id`，
下次再导回按 id 覆盖而不是新建；对方改过就先提示，不自动拉回来。

三部分：``render_tree`` 把整棵树渲染成 (路径, 正文) 列表（zip 导出和 Obsidian 目录写入共用）；
``md_to_notion_blocks`` / ``md_to_feishu_children`` 是 markdown → 各家块结构的纯函数；
``NotionWriter`` / ``FeishuWriter`` 是最小客户端（HTTP 可注入，测试不打网络）。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx

from . import store

_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
ASSET_REF = re.compile(r"/api/assets/([a-f0-9]{24}\.[a-z0-9]+)")


def display_title(title: str, content: str) -> str:
    t = (title or "").strip()
    if t and t not in ("未命名", "Untitled", "note"):
        return t
    for line in (content or "").split("\n"):
        line = re.sub(r"^#+\s*", "", line).strip()
        if line:
            return line[:60]
    return "未命名"


def safe_name(name: str) -> str:
    name = _BAD.sub(" ", name).strip().strip(".")
    return (name or "未命名")[:80]


@dataclass
class ExportFile:
    path: str
    content: str
    note_id: str = ""          # 空 = 克隆说明文件这类不对应笔记的东西
    title: str = ""
    assets: set[str] = field(default_factory=set)


def note_body(n: dict) -> tuple[str, set[str]]:
    """一篇笔记的导出正文：front-matter（memoket_id 是导回时按 id 覆盖的依据）+ 正文，
    资产链接改成相对路径。"""
    front = (f"---\nid: {n['id']}\nmemoket_id: {n['id']}\ntitle: {n['title'] or ''}\n"
             f"created: {n['created_at']}\nupdated: {n['updated_at']}\n---\n\n")
    body = n["content"] or ""
    assets = set(ASSET_REF.findall(body))
    return front + ASSET_REF.sub(r"_assets/\1", body), assets


def render_tree(user: str, only: set[str] | None = None) -> list[ExportFile]:
    """整棵树 → 文件列表。有子笔记的笔记是一个文件夹，它自己的正文是文件夹里同名的 .md；
    克隆写成 .link.txt；不在树上的进 _未归类/。``only`` 给了就只出这几篇（路径照树算）。"""
    notes = {n["id"]: n for n in store.list_notes(user)}
    rows = store.tree(user)
    children: dict[str, list[dict]] = {}
    for r in rows:
        children.setdefault(r["parent_note_id"], []).append(r)
    for lst in children.values():
        lst.sort(key=lambda r: (r.get("position") or 0, r["note_id"]))
    out: list[ExportFile] = []
    written: dict[str, str] = {}
    used: set[str] = set()

    def unique(path: str) -> str:
        base, i = path, 2
        while path in used:
            root, ext = base.rsplit(".", 1) if "." in base.rsplit("/", 1)[-1] else (base, "")
            path = f"{root} ({i})" + (f".{ext}" if ext else "")
            i += 1
        used.add(path)
        return path

    def emit(n: dict, path: str) -> None:
        body, assets = note_body(n)
        written[n["id"]] = path
        if only is None or n["id"] in only:
            out.append(ExportFile(path=path, content=body, note_id=n["id"],
                                  title=display_title(n["title"], n["content"]), assets=assets))

    def walk(parent: str, prefix: str) -> None:
        for r in children.get(parent, []):
            nid = r["note_id"]
            n = notes.get(nid)
            if not n:
                continue
            name = safe_name(display_title(n["title"], n["content"]))
            has_kids = bool(children.get(nid))
            if nid in written:
                if only is None:
                    out.append(ExportFile(path=unique(f"{prefix}{name}.link.txt"),
                                          content=f"这是「{name}」的克隆，正文在：{written[nid]}\n"))
                continue
            if has_kids:
                emit(n, unique(f"{prefix}{name}/{name}.md"))
                walk(nid, f"{prefix}{name}/")
            else:
                emit(n, unique(f"{prefix}{name}.md"))

    walk(store.ROOT_ID, "")
    for nid, n in notes.items():
        if nid not in written:
            emit(n, unique(f"_未归类/{safe_name(display_title(n['title'], n['content']))}.md"))
    return out


# ---------------------------------------------------------------- markdown → 块

def _md_lines(md: str) -> list[tuple[str, str, int]]:
    """把 markdown 粗粒度切成 (kind, text, level)：heading / bullet / ordered / code / quote / para。
    front-matter 去掉（那是给 Obsidian 的）。"""
    text = md
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end > 0:
            text = text[end + 5:]
    out: list[tuple[str, str, int]] = []
    lines = text.split("\n")
    i = 0
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append(("para", " ".join(s.strip() for s in para), 0))
            para.clear()
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            flush()
            j = i + 1
            buf = []
            while j < len(lines) and not lines[j].startswith("```"):
                buf.append(lines[j]); j += 1
            out.append(("code", "\n".join(buf), 0))
            i = j + 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            flush(); out.append(("heading", m.group(2).strip(), min(len(m.group(1)), 3))); i += 1; continue
        m = re.match(r"^\s*[-*+]\s+(.*)$", ln)
        if m:
            flush(); out.append(("bullet", m.group(1).strip(), 0)); i += 1; continue
        m = re.match(r"^\s*\d+[.)]\s+(.*)$", ln)
        if m:
            flush(); out.append(("ordered", m.group(1).strip(), 0)); i += 1; continue
        m = re.match(r"^>\s?(.*)$", ln)
        if m:
            flush(); out.append(("quote", m.group(1).strip(), 0)); i += 1; continue
        if not ln.strip():
            flush(); i += 1; continue
        para.append(ln)
        i += 1
    flush()
    return out


def _chunks2000(s: str) -> list[str]:
    return [s[i:i + 2000] for i in range(0, max(1, len(s)), 2000)] or [""]


def md_to_notion_blocks(md: str) -> list[dict]:
    blocks = []
    for kind, text, level in _md_lines(md):
        rt = [{"type": "text", "text": {"content": c}} for c in _chunks2000(text)]
        if kind == "heading":
            t = f"heading_{level}"
            blocks.append({"object": "block", "type": t, t: {"rich_text": rt}})
        elif kind == "bullet":
            blocks.append({"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rt}})
        elif kind == "ordered":
            blocks.append({"object": "block", "type": "numbered_list_item", "numbered_list_item": {"rich_text": rt}})
        elif kind == "code":
            blocks.append({"object": "block", "type": "code", "code": {"rich_text": rt, "language": "plain text"}})
        elif kind == "quote":
            blocks.append({"object": "block", "type": "quote", "quote": {"rich_text": rt}})
        else:
            blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt}})
    return blocks


def md_to_feishu_children(md: str) -> list[dict]:
    out = []
    for kind, text, level in _md_lines(md):
        el = {"elements": [{"text_run": {"content": text}}]}
        if kind == "heading":
            out.append({"block_type": 2 + level, f"heading{level}": el})
        elif kind == "bullet":
            out.append({"block_type": 12, "bullet": el})
        elif kind == "ordered":
            out.append({"block_type": 13, "ordered": el})
        elif kind == "code":
            out.append({"block_type": 14, "code": el})
        elif kind == "quote":
            out.append({"block_type": 15, "quote": el})
        else:
            out.append({"block_type": 2, "text": el})
    return out


# ---------------------------------------------------------------- 客户端

Call = Callable[..., dict]


class NotionWriter:
    def __init__(self, token: str, *, call: Call | None = None, version: str = "2026-03-11"):
        self.h = {"Authorization": f"Bearer {token.strip()}", "Notion-Version": version, "Content-Type": "application/json"}
        self._call = call

    def _req(self, method: str, path: str, json: dict | None = None) -> dict:
        if self._call:
            return self._call(method, path, json)
        r = httpx.request(method, "https://api.notion.com/v1" + path, headers=self.h, json=json, timeout=60)
        r.raise_for_status()
        return r.json()

    def create_page(self, parent_page_id: str, title: str, blocks: list[dict]) -> str:
        d = self._req("POST", "/pages", {"parent": {"page_id": parent_page_id},
                                          "properties": {"title": {"title": [{"text": {"content": title[:200]}}]}},
                                          "children": blocks[:100]})
        pid = d["id"]
        for i in range(100, len(blocks), 100):
            self._req("PATCH", f"/blocks/{pid}/children", {"children": blocks[i:i + 100]})
            time.sleep(0.34)
        return pid

    def replace_children(self, page_id: str, title: str, blocks: list[dict]) -> None:
        self._req("PATCH", f"/pages/{page_id}", {"properties": {"title": {"title": [{"text": {"content": title[:200]}}]}}})
        cursor = None
        while True:
            d = self._req("GET", f"/blocks/{page_id}/children?page_size=100" + (f"&start_cursor={cursor}" if cursor else ""))
            for b in d.get("results", []):
                self._req("DELETE", f"/blocks/{b['id']}")
            if not d.get("has_more"):
                break
            cursor = d.get("next_cursor")
        for i in range(0, len(blocks), 100):
            self._req("PATCH", f"/blocks/{page_id}/children", {"children": blocks[i:i + 100]})

    def last_edited(self, page_id: str) -> str:
        return str(self._req("GET", f"/pages/{page_id}").get("last_edited_time") or "")


class FeishuWriter:
    def __init__(self, app_id: str, app_secret: str, *, call: Call | None = None, base: str = "https://open.feishu.cn/open-apis"):
        self.app_id, self.app_secret, self.base = app_id.strip(), app_secret.strip(), base
        self._call = call
        self._token = ""

    def _req(self, method: str, path: str, json: dict | None = None, auth: bool = True) -> dict:
        if self._call:
            return self._call(method, path, json)
        headers = {"Authorization": f"Bearer {self.token()}"} if auth else {}
        r = httpx.request(method, self.base + path, headers=headers, json=json, timeout=60)
        r.raise_for_status()
        d = r.json()
        if d.get("code", 0) != 0:
            raise RuntimeError(f"飞书返回 {d.get('code')}：{d.get('msg', '')}")
        return d

    def token(self) -> str:
        if not self._token:
            d = self._req("POST", "/auth/v3/tenant_access_token/internal",
                          {"app_id": self.app_id, "app_secret": self.app_secret}, auth=False)
            self._token = d.get("tenant_access_token") or ""
            if not self._token:
                raise RuntimeError("飞书拒绝了这个应用")
        return self._token

    def create_document(self, folder_token: str, title: str) -> str:
        d = self._req("POST", "/docx/v1/documents", {"folder_token": folder_token, "title": title[:200]})
        return d["data"]["document"]["document_id"]

    def replace_children(self, doc_id: str, children: list[dict]) -> None:
        d = self._req("GET", f"/docx/v1/documents/{doc_id}/blocks/{doc_id}/children?page_size=500")
        n = len(d.get("data", {}).get("items") or [])
        if n:
            self._req("DELETE", f"/docx/v1/documents/{doc_id}/blocks/{doc_id}/children/batch_delete",
                      {"start_index": 0, "end_index": n})
        for i in range(0, len(children), 50):
            self._req("POST", f"/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                      {"children": children[i:i + 50], "index": i})

    def edited_time(self, doc_id: str) -> str:
        d = self._req("GET", f"/docx/v1/documents/{doc_id}")
        return str((d.get("data") or {}).get("document", {}).get("revision_id") or "")
