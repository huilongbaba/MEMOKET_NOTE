"""飞书云文档 → Markdown（docs/import-sync-plan.md §1）。

两部分：``blocks_to_markdown`` 是纯函数（docx v1 的块结构 → markdown，可离线测试）；
``FeishuClient`` 包一层 open-apis（tenant_access_token → 列知识库 / 云空间里的文档 →
取块）。自建应用要有 docx:document:readonly、wiki:wiki:readonly、drive:drive:readonly，
而且文档 / 知识库要把应用加为协作者——跟 Notion 的 connect integration 是同一个模型。
"""

from __future__ import annotations

import time
from typing import Callable

import httpx

BASE = "https://open.feishu.cn/open-apis"

# docx v1 的 block_type（官方文档「块类型」表）
_HEADINGS = {3: 1, 4: 2, 5: 3, 6: 4, 7: 5, 8: 6, 9: 6, 10: 6, 11: 6}
_TYPE_KEY = {1: "page", 2: "text", 12: "bullet", 13: "ordered", 14: "code", 15: "quote",
             17: "todo", 19: "callout", 22: "divider", 27: "image", 31: "table", 32: "table_cell"}
for _t, _lvl in _HEADINGS.items():
    _TYPE_KEY[_t] = f"heading{_t - 2}"


# 飞书 docx 的代码块语言枚举 → markdown 的语言名（官方「代码块语言」表里的常用几十种；
# 认不出来就不写语言，不猜）。写出去那一侧在 `exporters._FEISHU_LANG`，两张表要对得上。
_CODE_LANG = {
    1: "", 8: "c", 9: "cpp", 10: "csharp", 12: "css", 17: "go", 22: "html",
    24: "java", 25: "javascript", 26: "json", 28: "kotlin", 29: "latex", 30: "lua",
    31: "makefile", 32: "markdown", 36: "objectivec", 40: "php", 43: "python",
    45: "r", 49: "ruby", 50: "rust", 51: "scala", 52: "scheme", 53: "shell",
    54: "sql", 55: "swift", 58: "typescript", 60: "xml", 61: "yaml", 63: "bash",
}


def _inline(elements: list[dict] | None) -> str:
    out = []
    for el in elements or []:
        tr = el.get("text_run")
        if tr:
            s = tr.get("content") or ""
            st = tr.get("text_element_style") or {}
            if st.get("inline_code"):
                s = f"`{s}`"
            if st.get("bold"):
                s = f"**{s}**"
            if st.get("italic"):
                s = f"*{s}*"
            if st.get("strikethrough"):
                s = f"~~{s}~~"
            link = (st.get("link") or {}).get("url")
            if link:
                s = f"[{s}]({link})"
            out.append(s)
        elif el.get("mention_doc"):
            out.append(el["mention_doc"].get("title") or "")
        elif el.get("mention_user"):
            out.append("@" + (el["mention_user"].get("name") or el["mention_user"].get("user_id") or ""))
        elif el.get("equation"):
            out.append(f"${el['equation'].get('content', '')}$")
    return "".join(out)


def blocks_to_markdown(blocks: list[dict]) -> str:
    """一篇文档的全部块（flat 列表，带 parent_id / children）→ markdown。标题块（page）本身不进正文。"""
    by_id = {b.get("block_id"): b for b in blocks if b.get("block_id")}
    root = next((b for b in blocks if b.get("block_type") == 1), None)
    order = root.get("children") or [] if root else [b["block_id"] for b in blocks if b.get("parent_id") in ("", None)]
    lines: list[str] = []
    counters: dict[str, int] = {}

    def gap() -> None:
        """块级元素之前留一个空行。
        
        **列表项后面紧跟的任何东西都会被 markdown 吃成那一项的续行**——往返实测
        （第 649 轮真账号）里连着中过两次：`> 引用` 紧跟 `- 列表第二条`、
        普通段落紧跟 `2. 有序第二条`。列表项之间不留（那本来就该是紧的）。
        """
        if lines and lines[-1].strip():
            lines.append("")

    def render(bid: str, depth: int = 0) -> None:
        b = by_id.get(bid)
        if not b:
            return
        t = b.get("block_type")
        key = _TYPE_KEY.get(t, "")
        body = b.get(key) or {}
        indent = "  " * depth
        if t in _HEADINGS:
            gap()
            lines.append(f"{'#' * _HEADINGS[t]} {_inline(body.get('elements'))}")
            lines.append("")
        elif t == 2:
            gap()
            lines.append(indent + _inline(body.get("elements")))
            lines.append("")
        elif t == 12:
            lines.append(f"{indent}- {_inline(body.get('elements'))}")
        elif t == 13:
            n = counters.get(b.get("parent_id", ""), 0) + 1
            counters[b.get("parent_id", "")] = n
            lines.append(f"{indent}{n}. {_inline(body.get('elements'))}")
        elif t == 17:
            done = (body.get("style") or {}).get("done")
            lines.append(f"{indent}- [{'x' if done else ' '}] {_inline(body.get('elements'))}")
        elif t == 14:
            # **语言标注要带回来**：往返实测（第 649 轮，真账号）`​```python` 导出去
            # 再导回来变成了裸 `​``` `——代码块没了高亮，重导一次就丢一次。
            gap()
            lang = _CODE_LANG.get((body.get("style") or {}).get("language"), "")
            lines.append("```" + lang)
            lines.append(_inline(body.get("elements")))
            lines.append("```")
            lines.append("")
        elif t == 15:
            gap()
            lines.append(f"> {_inline(body.get('elements'))}")
            lines.append("")
        elif t == 19:
            for cid in b.get("children") or []:
                render(cid, depth)
            return
        elif t == 22:
            gap()
            lines.append("---")
            lines.append("")
        elif t == 27:
            gap()
            lines.append(f"![图片]({body.get('token', '')})")
            lines.append("")
        elif t == 31:
            prop = body.get("property") or {}
            cols = int(prop.get("column_size") or 0)
            cells = body.get("cells") or []
            if cols and cells:
                rows = [cells[i:i + cols] for i in range(0, len(cells), cols)]
                def cell_text(cid: str) -> str:
                    c = by_id.get(cid) or {}
                    parts = []
                    for kid in c.get("children") or []:
                        kb = by_id.get(kid) or {}
                        kk = _TYPE_KEY.get(kb.get("block_type"), "")
                        parts.append(_inline((kb.get(kk) or {}).get("elements")))
                    return " ".join(p for p in parts if p).replace("|", "\\|")
                for ri, row in enumerate(rows):
                    lines.append("| " + " | ".join(cell_text(c) for c in row) + " |")
                    if ri == 0:
                        lines.append("|" + "---|" * cols)
                lines.append("")
            return
        elif t == 32:
            return
        # 子块（列表嵌套等）
        for cid in b.get("children") or []:
            if t in (12, 13, 17):
                render(cid, depth + 1)
            elif t not in (31,):
                render(cid, depth)
        if t in (12, 13, 17) and depth == 0:
            # 顶层列表项之间不空行；列表结束后由下一个段落带空行
            pass

    for bid in order:
        render(bid)
    text = "\n".join(lines)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip() + "\n"


def page_title(blocks: list[dict]) -> str:
    root = next((b for b in blocks if b.get("block_type") == 1), None)
    return _inline((root or {}).get("page", {}).get("elements")).strip() if root else ""


class FeishuClient:
    """最小客户端。``get`` 可注入（测试用假的），默认 httpx。"""

    def __init__(self, app_id: str, app_secret: str, *, base: str = BASE,
                 get: Callable[..., dict] | None = None, post: Callable[..., dict] | None = None):
        self.app_id, self.app_secret, self.base = app_id.strip(), app_secret.strip(), base
        self._get, self._post = get, post
        self._token = ""

    # -- HTTP --
    def _do_post(self, path: str, json: dict) -> dict:
        if self._post:
            return self._post(path, json)
        r = httpx.post(self.base + path, json=json, timeout=30)
        r.raise_for_status()
        return r.json()

    def _do_get(self, path: str, params: dict | None = None) -> dict:
        if self._get:
            return self._get(path, params or {})
        r = httpx.get(self.base + path, params=params, timeout=60,
                      headers={"Authorization": f"Bearer {self.token()}"})
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _ok(d: dict, what: str) -> dict:
        if d.get("code", 0) != 0:
            raise RuntimeError(f"飞书 {what} 失败：{d.get('code')} {d.get('msg', '')}")
        return d.get("data") or {}

    def token(self) -> str:
        if not self._token:
            d = self._do_post("/auth/v3/tenant_access_token/internal", {"app_id": self.app_id, "app_secret": self.app_secret})
            if d.get("code", 0) != 0 or not d.get("tenant_access_token"):
                raise RuntimeError(f"飞书拒绝了这个应用：{d.get('code')} {d.get('msg', '')}")
            self._token = d["tenant_access_token"]
        return self._token

    # -- 列文档 --
    def list_wiki_docs(self, limit: int = 0) -> list[dict]:
        """所有知识库空间里的 docx 节点：{document_id, title, created, edited}。"""
        out: list[dict] = []
        spaces = self._ok(self._do_get("/wiki/v2/spaces", {"page_size": 50}), "列知识库").get("items") or []
        for sp in spaces:
            stack = [""]
            while stack and (not limit or len(out) < limit):
                parent = stack.pop()
                page_token = ""
                while True:
                    params = {"page_size": 50}
                    if parent:
                        params["parent_node_token"] = parent
                    if page_token:
                        params["page_token"] = page_token
                    d = self._ok(self._do_get(f"/wiki/v2/spaces/{sp['space_id']}/nodes", params), "列节点")
                    for n in d.get("items") or []:
                        if n.get("has_child"):
                            stack.append(n["node_token"])
                        if n.get("obj_type") == "docx":
                            out.append({"document_id": n["obj_token"], "title": n.get("title") or "",
                                        "created": n.get("obj_create_time") or "", "edited": n.get("obj_edit_time") or ""})
                    if not d.get("has_more"):
                        break
                    page_token = d.get("page_token") or ""
                    time.sleep(0.2)
        return out[:limit] if limit else out

    def list_drive_docs(self, limit: int = 0, folder: str = "") -> list[dict]:
        """云空间（我的空间）里的 docx，递归进子文件夹。"""
        out: list[dict] = []
        stack = [folder]
        while stack and (not limit or len(out) < limit):
            cur = stack.pop()
            page_token = ""
            while True:
                params = {"page_size": 50}
                if cur:
                    params["folder_token"] = cur
                if page_token:
                    params["page_token"] = page_token
                d = self._ok(self._do_get("/drive/v1/files", params), "列文件")
                for f in d.get("files") or []:
                    if f.get("type") == "folder":
                        stack.append(f["token"])
                    elif f.get("type") == "docx":
                        out.append({"document_id": f["token"], "title": f.get("name") or "",
                                    "created": f.get("created_time") or "", "edited": f.get("modified_time") or ""})
                if not d.get("has_more"):
                    break
                page_token = d.get("next_page_token") or ""
                time.sleep(0.2)
        return out[:limit] if limit else out

    # 链接里那一段 token：`https://xxx.feishu.cn/docx/<token>` / `/wiki/<token>`，
    # 后面可能跟 `?from=...` 或 `#锚点`。裸 token 也认。
    _REF = __import__("re").compile(r"(?:/(docx|wiki|docs)/)?([A-Za-z0-9]{16,32})(?:[?#].*)?$")

    def resolve_doc(self, ref: str) -> dict:
        """一个链接 / token → `{document_id, title}`。

        **这条路存在的理由**：飞书是按文档授权的，而「列出来」那条路要求应用是
        知识库空间的成员。实测（第 649 轮真账号）：一篇按文档加了协作者的 wiki
        文档，`get_node` 读得到、`/wiki/v2/spaces` 里却一个空间都没有——
        **读得到却列不出来**。能粘链接，这个功能才对「不是管理员的人」也成立。
        """
        m = self._REF.search((ref or "").strip())
        if not m:
            raise RuntimeError(f"认不出这是哪一篇：{ref[:40]}")
        kind, token = m.group(1), m.group(2)
        if kind == "wiki":
            node = self._ok(self._do_get("/wiki/v2/spaces/get_node", {"token": token}), "查节点").get("node") or {}
            if node.get("obj_type") != "docx":
                raise RuntimeError(f"这是一篇「{node.get('obj_type') or '未知类型'}」，只能导入文档（docx）")
            return {"document_id": node.get("obj_token") or "", "title": node.get("title") or ""}
        return {"document_id": token, "title": ""}

    def document_blocks(self, document_id: str) -> list[dict]:
        blocks: list[dict] = []
        page_token = ""
        while True:
            params = {"page_size": 500, "document_revision_id": -1}
            if page_token:
                params["page_token"] = page_token
            d = self._ok(self._do_get(f"/docx/v1/documents/{document_id}/blocks", params), "取文档内容")
            blocks += d.get("items") or []
            if not d.get("has_more"):
                break
            page_token = d.get("page_token") or ""
        return blocks


def epoch_to_date(v: str | int | None) -> str:
    """飞书给的是秒级 unix 时间戳字符串；认不出来给空串（由 _land 退回今天，不猜）。"""
    try:
        n = int(str(v or "").strip())
    except ValueError:
        return ""
    if n <= 0:
        return ""
    if n > 10**11:          # 毫秒
        n //= 1000
    return time.strftime("%Y-%m-%d", time.localtime(n))
