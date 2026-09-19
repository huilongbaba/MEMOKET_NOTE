"""导回（docs/import-sync-plan.md §2）：把笔记按目标平台的规则渲染出去。

原则：导回是「视图」，不是双向同步的另一半——这里的笔记是真相，导回带上 `memoket_id`，
下次再导回按 id 覆盖而不是新建；对方改过就先提示，不自动拉回来。

三部分：``render_tree`` 把整棵树渲染成 (路径, 正文) 列表（zip 导出和 Obsidian 目录写入共用）；
``md_to_notion_blocks`` / ``md_to_feishu_children`` 是 markdown → 各家块结构的纯函数；
``NotionWriter`` / ``FeishuWriter`` 是最小客户端（HTTP 可注入，测试不打网络）。

P2-fix（产品就绪计划 A3）：P2 验证报告（docs/_research/export-verification-P2.md）实测导出去的
内容只到「纯文本级」——表格塌成一段、图片是一行 `![…]` 字面量、粗体带星号、引用 id 裸露。
这一版把 markdown 切成带行内样式的块树（表格 / 图片 / 任务 / 分隔线 / 嵌套列表 / 多行引用），
两家各自渲染；失败时先读对面的 `code/msg`，拼成用户能行动的中文。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import httpx

from . import store

_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
ASSET_REF = re.compile(r"/api/assets/([a-f0-9]{24}\.[a-z0-9]+)")
NOTE_LINK = re.compile(r"\]\(note://([a-f0-9]{12})\)")

# ---------------------------------------------------------------- mermaid → 图（P18 #4）
#
# 飞书 docx 没有 mermaid 这个语言枚举（P2-fix 只能落成纯文本代码块）。图不是后端画的：**没有外部服务**
# （不许 kroki 之类），后端是 PyInstaller 打的包、塞不进一个 Chromium；而前端本来就在用 mermaid 渲染
# 编辑器里的图——导回之前前端把每张图渲成 PNG（`util/mermaidPng.ts`），按**源码的哈希**交上来
# （`POST /api/export/renders`），这里按同一个哈希对上号、走 P2-fix 已做的图片三步上传。
# 哈希两边各算一份、同一个口径（strip 之后的源码 sha256 前 24 位）：`test_p18` 里钉着一对 fixture。
MERMAID_KEY_LEN = 24
MERMAID_RENDER_MAX = 4 * 1024 * 1024        # 一张图的 PNG 上限；2× 缩放的流程图几十 KB，4 MB 够十倍余量
MERMAID_RENDERS_MAX = 64                    # 一次导回最多带几张


def mermaid_key(code: str) -> str:
    import hashlib
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()[:MERMAID_KEY_LEN]


def mermaid_blocks(md: str) -> dict[str, str]:
    """正文里每一段 ```mermaid 的源码，按哈希：前端拿去渲、渲完按同一个哈希交回来。"""
    out: dict[str, str] = {}
    for b in md_to_blocks(md):
        if b.kind == "code" and b.lang == "mermaid" and b.text.strip():
            out[mermaid_key(b.text)] = b.text
    return out


_SENTENCE_END = "。！？"
_PAUSE = "；，,：:"


def clip_title(line: str, max_len: int = 60) -> str:
    """正文首行当名字时截到第一个够格的句读——跟前端 `displayTitle.clipTitle` 同一条规则：
    句号（。！？）不在开头一两个字就截；逗号 / 分号 / 冒号要 ≥ 8 字（「APP定义：先锚定范围」的冒号太靠前，
    截出来不成标题）；都没有才硬截。导出的文件名之前是 80 字硬截，一行「我们产品当前遇到的挑战：四项核心
    挑战归纳为验证框架：录制信任、关联即时反馈…」整句进文件名。"""
    for i, ch in enumerate(line):
        if ch in _SENTENCE_END and i >= 2:
            return line[:min(i, max_len)]
        if ch in _PAUSE and i >= 8:
            return line[:min(i, max_len)]
    return line[:max_len]


def display_title(title: str, content: str) -> str:
    t = (title or "").strip()
    if t and t not in ("未命名", "Untitled", "note"):
        return t
    for line in (content or "").split("\n"):
        # 先 strip 再剥 #：整篇缩进的「    # 标题」不然会变成「# 标题」（跟前端 displayTitle 一致）
        line = re.sub(r"^#+\s*", "", line.strip()).strip()
        if line:
            return clip_title(line)
    return "未命名"


def safe_name(name: str) -> str:
    name = _BAD.sub(" ", name).strip(" .")   # 「../../evil」之前变成「 .. evil」——先去点再去空格得循环，一次去掉两种
    return (name or "未命名")[:80]


@dataclass
class ExportFile:
    path: str
    content: str
    note_id: str = ""          # 空 = 克隆说明文件这类不对应笔记的东西
    title: str = ""
    assets: set[str] = field(default_factory=set)


_YAML_PLAIN = re.compile(r"^[^\[\]{}\"'*&!|>%@`#,\-?:][^#]*$")


def yaml_scalar(value: str) -> str:
    """front-matter 的值：能裸写就裸写，会被 YAML 误读的（含 `: `、` #`、开头是 `[ { \" ' * & !` 等）
    用双引号包起来（P2 报告 §1.5：`title: 会议: 周会 #1` 在 Obsidian 属性面板是 Invalid YAML）。
    对面的 `parse_frontmatter` 只 `strip('\\'\"')`，所以普通标题带不带引号读回来一样。"""
    v = value or ""
    if v and _YAML_PLAIN.match(v) and ": " not in v and not v.endswith(":") and "\n" not in v and v == v.strip():
        return v
    return json.dumps(v, ensure_ascii=False)


def note_body(n: dict, paths: dict[str, str] | None = None, depth: int = 0) -> tuple[str, set[str]]:
    """一篇笔记的导出正文：front-matter（memoket_id 是导回时按 id 覆盖的依据）+ 正文，
    资产链接改成相对路径（按这篇所在的目录深度补 `../`，P2 报告 §4.17），
    `[标题](note://id)` 改成指向对方 .md 的相对链接（§4.13；`paths` 是整棵树的 id → 路径）。"""
    front = (f"---\nid: {n['id']}\nmemoket_id: {n['id']}\ntitle: {yaml_scalar(n['title'] or '')}\n"
             + (f"icon: {yaml_scalar(n['icon'])}\n" if n.get("icon") else "")          # 笔记图标随身带，导回 / 再导入认得
             + f"created: {n['created_at']}\nupdated: {n['updated_at']}\n---\n\n")
    body = n["content"] or ""
    assets = set(ASSET_REF.findall(body))
    up = "../" * depth
    body = ASSET_REF.sub(lambda m: f"{up}_assets/{m.group(1)}", body)
    if paths:
        def _link(m: re.Match) -> str:
            target = paths.get(m.group(1))
            if not target:
                return m.group(0)
            return "](<" + up + target + ">)"      # 尖括号形式：路径里有空格 / 中文也不用百分号编码
        body = NOTE_LINK.sub(_link, body)
    return front + body, assets


def render_tree(user: str, only: set[str] | None = None) -> list[ExportFile]:
    """整棵树 → 文件列表。有子笔记的笔记是一个文件夹，它自己的正文是文件夹里同名的 .md；
    克隆写成 .link.txt；不在树上的进 _未归类/。``only`` 给了就只出这几篇（路径照树算）。

    两遍：先把每篇的路径定下来（笔记间链接要知道对方在哪），再渲染正文。"""
    notes = {n["id"]: n for n in store.list_notes(user)}
    rows = store.tree(user)
    children: dict[str, list[dict]] = {}
    for r in rows:
        children.setdefault(r["parent_note_id"], []).append(r)
    for lst in children.values():
        lst.sort(key=lambda r: (r.get("position") or 0, r["note_id"]))
    plan: list[tuple[dict | None, str]] = []     # (笔记, 路径)；笔记为 None = 克隆说明
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
                    link = unique(f"{prefix}{name}.link.txt")
                    plan.append((None, link)); clone_of[link] = (name, written[nid])
                continue
            if has_kids:
                written[nid] = unique(f"{prefix}{name}/{name}.md"); plan.append((n, written[nid]))
                walk(nid, f"{prefix}{name}/")
            else:
                written[nid] = unique(f"{prefix}{name}.md"); plan.append((n, written[nid]))

    clone_of: dict[str, tuple[str, str]] = {}
    walk(store.ROOT_ID, "")
    for nid, n in notes.items():
        if nid not in written:
            written[nid] = unique(f"_未归类/{safe_name(display_title(n['title'], n['content']))}.md")
            plan.append((n, written[nid]))

    out: list[ExportFile] = []
    for n, path in plan:
        if n is None:
            name, target = clone_of[path]
            out.append(ExportFile(path=path, content=f"这是「{name}」的克隆，正文在：{target}\n"))
            continue
        if only is not None and n["id"] not in only:
            continue
        body, assets = note_body(n, written, depth=path.count("/"))
        out.append(ExportFile(path=path, content=body, note_id=n["id"],
                              title=display_title(n["title"], n["content"]), assets=assets))
    return out


# markdown 的语言名 → 飞书 docx 的代码块语言枚举。读回来那一侧在
# `ingest/feishu._CODE_LANG`，**两张表要对得上**——`scripts/check-...` 管不到这儿，
# 靠的是这条注释和往返测试。认不出来就不设语言，不猜。
_FEISHU_LANG = {
    "c": 8, "cpp": 9, "c++": 9, "csharp": 10, "css": 12, "go": 17, "html": 22,
    "java": 24, "javascript": 25, "js": 25, "json": 26, "kotlin": 28, "latex": 29,
    "lua": 30, "makefile": 31, "markdown": 32, "md": 32, "objectivec": 36, "php": 40,
    "python": 43, "py": 43, "r": 45, "ruby": 49, "rust": 50, "scala": 51, "scheme": 52,
    "shell": 53, "sh": 53, "sql": 54, "swift": 55, "typescript": 58, "ts": 58,
    "xml": 60, "yaml": 61, "yml": 61, "bash": 63,
}
# Notion 的 language 是字符串枚举，名字基本就是通用写法。
# `mermaid` 是 Notion 原生支持并渲染成图的（P2 报告 §2.5：之前查不到就落成 plain text，白白丢了）。
_NOTION_LANG = {k: k for k in ("c", "css", "go", "html", "java", "javascript", "json",
                               "kotlin", "latex", "lua", "makefile", "markdown", "php",
                               "python", "r", "ruby", "rust", "scala", "scheme", "shell",
                               "sql", "swift", "typescript", "xml", "yaml", "bash", "mermaid")}
_NOTION_LANG.update({"cpp": "c++", "js": "javascript", "ts": "typescript",
                     "py": "python", "sh": "shell", "yml": "yaml", "md": "markdown"})


# ---------------------------------------------------------------- markdown → 块树

@dataclass
class Block:
    """markdown 的一个块。`text` 是**还没解析的行内 markdown**（渲染时再切成带样式的 run）；
    `children` 只有列表项用（嵌套列表）；`rows` 只有表格用；`alt`/`src` 只有图片用。"""
    kind: str                       # heading / bullet / ordered / todo / code / quote / para / table / divider / image
    text: str = ""
    level: int = 0                  # heading 1–6；列表项 = 嵌套深度
    lang: str = ""
    checked: bool = False
    rows: list[list[str]] = field(default_factory=list)
    children: list["Block"] = field(default_factory=list)
    alt: str = ""
    src: str = ""


_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_TASK = re.compile(r"^\[( |x|X)\]\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")
_DIVIDER = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_IMAGE_LINE = re.compile(r"^\s*!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")


def _split_cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells, buf, i = [], [], 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            buf.append("|"); i += 2; continue
        if ch == "|":
            cells.append("".join(buf).strip()); buf = []
        else:
            buf.append(ch)
        i += 1
    cells.append("".join(buf).strip())
    return cells


def _strip_frontmatter(md: str) -> str:
    text = md
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end > 0:
            text = text[end + 5:]
    return text


def md_to_blocks(md: str) -> list[Block]:
    """把 markdown 切成块树。front-matter 去掉（那是给 Obsidian 的）。

    `lang` 只有代码块用得上。**它是往返里唯一会丢的东西**（第 649 轮真账号实测：
    ```python 导出去再导回来变成裸 ```），所以宁可多带一个字段，也不要在这里把它扔了。

    段内硬换行用 `\\n` 连（不是英文空格——中文正文里凭空多空格，P2 报告 §4.14）；
    连续的 `>` 行合成一个引用块；表格是「连续 `|` 行 + 第二行是分隔行」。
    """
    lines = _strip_frontmatter(md).split("\n")
    out: list[Block] = []
    para: list[str] = []
    stack: list[tuple[int, Block]] = []      # 嵌套列表：(缩进宽度, 项)

    def flush_para() -> None:
        if para:
            out.append(Block("para", "\n".join(s.strip() for s in para)))
            para.clear()

    def close_lists() -> None:
        stack.clear()

    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```") or ln.startswith("~~~"):
            fence = ln[:3]
            flush_para(); close_lists()
            lang = ln[3:].strip().split()[0] if ln[3:].strip() else ""
            j = i + 1
            buf = []
            while j < len(lines) and not lines[j].startswith(fence):
                buf.append(lines[j]); j += 1
            out.append(Block("code", "\n".join(buf), lang=lang.lower()))
            i = j + 1
            continue
        m = _HEADING.match(ln)
        if m:
            flush_para(); close_lists()
            out.append(Block("heading", m.group(2).strip(), level=len(m.group(1)))); i += 1; continue
        if _DIVIDER.match(ln):       # `* * *` 也是分隔线：CommonMark 里分隔线优先于列表项
            flush_para(); close_lists()
            out.append(Block("divider")); i += 1; continue
        m = _IMAGE_LINE.match(ln)
        if m:
            flush_para(); close_lists()
            out.append(Block("image", alt=m.group(1).strip(), src=m.group(2).strip())); i += 1; continue
        if ln.lstrip().startswith("|") and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]) and "|" in lines[i + 1]:
            flush_para(); close_lists()
            rows = [_split_cells(ln)]
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append(_split_cells(lines[j])); j += 1
            width = max(len(r) for r in rows)
            out.append(Block("table", rows=[r + [""] * (width - len(r)) for r in rows]))
            i = j
            continue
        m = _LIST.match(ln)
        if m:
            flush_para()
            indent = len(m.group(1).expandtabs(4))
            body = m.group(3).strip()
            kind = "ordered" if m.group(2)[0].isdigit() else "bullet"
            b = Block(kind, body)
            t = _TASK.match(body)
            if t and kind == "bullet":
                b = Block("todo", t.group(2).strip(), checked=t.group(1) != " ")
            while stack and stack[-1][0] >= indent:
                stack.pop()
            if stack:
                parent = stack[-1][1]
                b.level = parent.level + 1
                parent.children.append(b)
            else:
                out.append(b)
            stack.append((indent, b))
            i += 1
            continue
        m = _QUOTE.match(ln)
        if m:
            flush_para(); close_lists()
            buf = [m.group(1).strip()]
            j = i + 1
            while j < len(lines) and (q := _QUOTE.match(lines[j])):
                buf.append(q.group(1).strip()); j += 1
            out.append(Block("quote", "\n".join(buf).strip()))
            i = j
            continue
        if not ln.strip():
            flush_para(); close_lists(); i += 1; continue
        # 列表项下面缩进的续行归到那一项（「- 甲\n  继续说甲」）
        if stack and ln.startswith((" ", "\t")) and not para:
            stack[-1][1].text += "\n" + ln.strip()
            i += 1
            continue
        close_lists()
        para.append(ln)
        i += 1
    flush_para()
    return out


# ---------------------------------------------------------------- 行内：markdown → run

@dataclass
class Run:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    strike: bool = False
    link: str = ""


# 跟 `store._CITE` 同一个形状：`[terrence-1346-1F3]` / `[note-5f65df10cad6-0A1]`。
# 导出去**剥掉**（连同前面那个空格）——对面没有知识库能解析它，留着就是一串乱码；
# 变脚注得把事实原文一起带过去，而那是会议记录（用户可能不想让它出现在飞书文档里）。
_CITE = re.compile(r" ?\[[A-Za-z][A-Za-z0-9_-]*-(?:\d+|[0-9a-f]{12})-[0-9A-Fa-f]+\]")
_INLINE = re.compile(
    r"(?P<fence>`+)(?P<code>.+?)(?P=fence)"
    r"|!\[(?P<imgalt>[^\]]*)\]\((?P<imgsrc>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
    r"|\[\[(?P<wiki>[^\]|]+)(?:\|(?P<wikilabel>[^\]]+))?\]\]"
    r"|\[(?P<ltxt>[^\]]+)\]\((?P<lurl>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
    r"|\*\*(?P<bold>.+?)\*\*"
    r"|__(?P<bold2>.+?)__"
    r"|~~(?P<strike>.+?)~~"
    r"|(?<![\w*])\*(?P<em>[^*\n]+?)\*(?![\w*])"
    r"|(?<![\w_])_(?P<em2>[^_\n]+?)_(?![\w_])",
    re.S,
)


def strip_citations(text: str) -> str:
    return _CITE.sub("", text or "")


def inline_runs(text: str, **style) -> list[Run]:
    """行内 markdown → 带样式的 run 列表。粗体 / 斜体 / 行内代码 / 删除线 / 链接 / 图片 / wiki 链接；
    `[terrence-xxx]` 引用先剥掉。嵌套（`**粗 `code`**`）递归解析，代码段内部不再解析。"""
    s = strip_citations(text)
    runs: list[Run] = []
    pos = 0

    def plain(t: str) -> None:
        if t:
            runs.append(Run(t, **style))

    for m in _INLINE.finditer(s):
        plain(s[pos:m.start()])
        pos = m.end()
        g = m.groupdict()
        if g["code"] is not None:
            runs.append(Run(g["code"], **{**style, "code": True}))
        elif g["imgalt"] is not None:
            plain(f"[图：{g['imgalt'] or '图片'}]")
        elif g["wiki"] is not None:
            plain((g["wikilabel"] or g["wiki"]).strip())
        elif g["ltxt"] is not None:
            url = g["lurl"]
            sub = {**style, "link": url} if re.match(r"^https?://", url) else style   # note:// 在对面点不开，只留文字
            runs.extend(inline_runs(g["ltxt"], **sub))
        elif g["bold"] is not None or g["bold2"] is not None:
            runs.extend(inline_runs(g["bold"] if g["bold"] is not None else g["bold2"], **{**style, "bold": True}))
        elif g["strike"] is not None:
            runs.extend(inline_runs(g["strike"], **{**style, "strike": True}))
        else:
            runs.extend(inline_runs(g["em"] if g["em"] is not None else g["em2"], **{**style, "italic": True}))
    plain(s[pos:])
    return runs or [Run("", **style)]


def _chunks(s: str, n: int = 2000) -> list[str]:
    return [s[i:i + n] for i in range(0, max(1, len(s)), n)] or [""]


# ---------------------------------------------------------------- Notion

def _notion_rich(runs: list[Run]) -> list[dict]:
    """rich_text 数组；每个 run 切 2000 字（Notion 单个 text.content 上限）。"""
    out = []
    for r in runs:
        for c in _chunks(r.text):
            t: dict = {"type": "text", "text": {"content": c}}
            if r.link:
                t["text"]["link"] = {"url": r.link}
            if r.bold or r.italic or r.code or r.strike:
                t["annotations"] = {"bold": r.bold, "italic": r.italic, "strikethrough": r.strike,
                                    "underline": False, "code": r.code, "color": "default"}
            out.append(t)
    return out


def _notion_items(b: Block, depth: int = 0) -> list[dict]:
    """一个列表项（带子项）→ Notion 块。Notion 一次请求最多嵌两层：更深的项拍平成第二层的兄弟（比整个丢掉强）。"""
    t = {"bullet": "bulleted_list_item", "ordered": "numbered_list_item", "todo": "to_do"}[b.kind]
    body: dict = {"rich_text": _notion_rich(inline_runs(b.text))}
    if b.kind == "todo":
        body["checked"] = b.checked
    blk = {"object": "block", "type": t, t: body}
    overflow: list[dict] = []
    for kid in b.children:
        sub = _notion_items(kid, depth + 1)
        if depth < 2:
            body.setdefault("children", []).extend(sub)
        else:
            overflow.extend(sub)
    return [blk] + overflow


def _notion_note(text: str) -> dict:
    """一行斜体说明（图传不上去 / 文件不在本机时替图的那一行）。"""
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": _notion_rich(inline_runs(text, italic=True))}}


def md_to_notion_blocks(md: str) -> list[dict]:
    blocks: list[dict] = []
    for b in md_to_blocks(md):
        if b.kind == "heading":
            if b.level <= 3:
                t = f"heading_{b.level}"
                blocks.append({"object": "block", "type": t, t: {"rich_text": _notion_rich(inline_runs(b.text))}})
            else:
                # Notion 只有三级标题：h4–h6 做成粗体段落，别再压成 heading_3（那会把层级抹平）
                blocks.append({"object": "block", "type": "paragraph",
                               "paragraph": {"rich_text": _notion_rich(inline_runs(b.text, bold=True))}})
        elif b.kind in ("bullet", "ordered", "todo"):
            blocks.extend(_notion_items(b))
        elif b.kind == "code":
            blocks.append({"object": "block", "type": "code",
                           "code": {"rich_text": [{"type": "text", "text": {"content": c}} for c in _chunks(b.text)],
                                    "language": _NOTION_LANG.get(b.lang, "plain text")}})
        elif b.kind == "quote":
            blocks.append({"object": "block", "type": "quote", "quote": {"rich_text": _notion_rich(inline_runs(b.text))}})
        elif b.kind == "divider":
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        elif b.kind == "table":
            width = len(b.rows[0])
            blocks.append({"object": "block", "type": "table",
                           "table": {"table_width": width, "has_column_header": True, "has_row_header": False,
                                     "children": [{"object": "block", "type": "table_row",
                                                   "table_row": {"cells": [_notion_rich(inline_runs(c)) for c in row]}}
                                                  for row in b.rows]}})
        elif b.kind == "image":
            m = ASSET_REF.search(b.src) or re.search(r"_assets/([a-f0-9]{24}\.[a-z0-9]+)", b.src)
            if re.match(r"^https?://", b.src):
                blocks.append({"object": "block", "type": "image", "image": {"type": "external", "external": {"url": b.src}}})
            elif m:
                # 本地图片走 Notion 的 File Upload API（P18 #5；P2-fix 时写成一行说明）：这里只留一个
                # `_asset` 标记，`NotionWriter.prepare` 写之前上传、换成 `file_upload` 块；文件不在本机
                # 才退回一行说明
                blocks.append({"object": "block", "type": "image", "image": {}, "_asset": m.group(1), "_alt": b.alt})
            else:
                blocks.append(_notion_note(f"[图：{b.alt or '图片'}]（{b.src}）"))
        else:
            blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": _notion_rich(inline_runs(b.text))}})
    return blocks


# ---------------------------------------------------------------- 飞书

def _feishu_elements(runs: list[Run]) -> list[dict]:
    out = []
    for r in runs:
        for c in _chunks(r.text):
            el: dict = {"text_run": {"content": c}}
            st: dict = {}
            if r.bold: st["bold"] = True
            if r.italic: st["italic"] = True
            if r.strike: st["strikethrough"] = True
            if r.code: st["inline_code"] = True
            if r.link: st["link"] = {"url": quote(r.link, safe="")}      # 飞书要求 url 编码过
            if st:
                el["text_run"]["text_element_style"] = st
            out.append(el)
    return out


def _feishu_text(text: str, **style) -> dict:
    return {"elements": _feishu_elements(inline_runs(text, **style))}


def _feishu_item(b: Block) -> dict:
    if b.kind == "todo":
        blk = {"block_type": 17, "todo": {**_feishu_text(b.text), "style": {"done": b.checked}}}
    elif b.kind == "ordered":
        blk = {"block_type": 13, "ordered": _feishu_text(b.text)}
    else:
        blk = {"block_type": 12, "bullet": _feishu_text(b.text)}
    if b.children:
        blk["children"] = [_feishu_item(k) for k in b.children]
    return blk


def md_to_feishu_children(md: str, renders: dict[str, bytes] | None = None) -> list[dict]:
    """飞书 docx 的块树。嵌套的 `children` 是**块本身**（不是 id）——`FeishuWriter` 送出去之前
    会拍平成 descendant 接口要的形状。图片块带一个 `_asset`（本地文件名）或 `_asset_bytes`（前端渲好的
    mermaid PNG，按 `mermaid_key` 从 `renders` 里对上号），写的时候上传再回填。"""
    out: list[dict] = []
    for b in md_to_blocks(md):
        if b.kind == "heading":
            lvl = min(b.level, 9)
            out.append({"block_type": 2 + lvl, f"heading{lvl}": _feishu_text(b.text)})
        elif b.kind in ("bullet", "ordered", "todo"):
            out.append(_feishu_item(b))
        elif b.kind == "code":
            # 语言标注带过去：往返实测（第 649 轮真账号）这是唯一会丢的东西。
            # mermaid：飞书 docx 没有这个语言枚举。前端渲好的 PNG 交上来了就先放一张图（P18 #4），
            # 源码照旧跟在后面（导回来还能改）；没渲（老客户端 / 语法错渲不出）就代码块 + 一行说明。
            png = (renders or {}).get(mermaid_key(b.text)) if b.lang == "mermaid" else None
            if png:
                key = mermaid_key(b.text)
                out.append({"block_type": 27, "image": {}, "_asset_bytes": png,
                            "_asset_name": f"mermaid-{key}.png", "_alt": "mermaid 图"})
            code: dict = {"elements": [{"text_run": {"content": c}} for c in _chunks(b.text)]}
            if b.lang and (n := _FEISHU_LANG.get(b.lang)):
                code["style"] = {"language": n}
            out.append({"block_type": 14, "code": code})
            if b.lang == "mermaid" and not png:
                out.append({"block_type": 2, "text": _feishu_text("（上面是一张 mermaid 图的源码：飞书不渲染它；从 MEMOKET NOTE 里再导一次会带上渲好的图）", italic=True)})
        elif b.kind == "quote":
            out.append({"block_type": 15, "quote": _feishu_text(b.text)})
        elif b.kind == "divider":
            out.append({"block_type": 22, "divider": {}})
        elif b.kind == "table":
            cols = len(b.rows[0])
            cells = [{"block_type": 32, "table_cell": {}, "children": [{"block_type": 2, "text": _feishu_text(c)}]}
                     for row in b.rows for c in row]
            out.append({"block_type": 31, "table": {"property": {"row_size": len(b.rows), "column_size": cols, "header_row": True}},
                        "children": cells})
        elif b.kind == "image":
            m = ASSET_REF.search(b.src) or re.search(r"_assets/([a-f0-9]{24}\.[a-z0-9]+)", b.src)
            if m:
                out.append({"block_type": 27, "image": {}, "_asset": m.group(1), "_alt": b.alt})
            else:
                out.append({"block_type": 2, "text": _feishu_text(f"[图：{b.alt or '图片'}]（{b.src}）")})
        else:
            out.append({"block_type": 2, "text": _feishu_text(b.text)})
    return out


# ---------------------------------------------------------------- 客户端

Call = Callable[..., dict]


class RemoteError(RuntimeError):
    """对面平台拒绝了：`str()` 是一句用户能行动的中文；`status` / `code` 给路由层判「同一类错误连着来」。"""

    def __init__(self, message: str, *, status: int = 0, code: str = ""):
        super().__init__(message)
        self.status, self.code = status, code


def explain_notion(status: int, message: str) -> str:
    """Notion 的 HTTP 状态 + 它自己的 message → 用户下一步该做什么（P2 报告 §4.2）。"""
    msg = (message or "").strip()
    if status == 401:
        return f"Notion 拒绝了这个 token（{msg or 'unauthorized'}）——去 notion.so/profile/integrations 重新复制 Internal Integration Secret"
    if status == 404:
        return (f"Notion 找不到这个页面（{msg}）——父页面 id 不对，或者这个页面还没连接给这个 integration："
                "页面右上「⋯」→「Connections」加上它")
    if status == 403:
        return f"Notion 说没权限（{msg}）——integration 的 Capabilities 要勾上「Insert content」和「Update content」"
    if status == 429:
        return f"Notion 限流了（{msg}）——等一会儿再试"
    if status == 400:
        return f"Notion 不接受这份内容（{msg}）"
    return f"Notion 返回 {status}：{msg}"


def explain_feishu(code: int | str, msg: str, helps: str = "") -> str:
    """飞书的 code / msg → 用户下一步该做什么（P2 报告 §4.2 / §4.15；code 来自真实响应）。"""
    c = str(code)
    hint = f"（{helps}）" if helps else ""
    if c == "10003":
        return "飞书说 App ID 不对（10003 invalid param）——开放平台 → 应用 → 凭证与基础信息，复制 App ID"
    if c == "10014":
        return "飞书说 App Secret 不对（10014 app secret invalid）——开放平台 → 应用 → 凭证与基础信息，重新复制 App Secret"
    if c == "1770039":
        return "飞书找不到这个文件夹（1770039）——文件夹 token 是文件夹链接 /drive/folder/ 后面那串，检查有没有贴错"
    if c in ("99991663", "99991664", "99991672", "99991679"):
        return f"应用没有开通这个权限范围（{c} {msg}）——开放平台 → 权限管理，加上 docx:document 和 drive:drive 并发布"
    if c in ("1770032", "1770033", "1770034", "1770035", "1770002") or "permission" in (msg or "").lower() or "forbidden" in (msg or "").lower():
        return f"飞书说应用没权限（{c} {msg}）——把应用加为目标文件夹的协作者（可编辑），并确认应用有 docx:document、drive:drive 权限"
    return f"飞书返回 {c}：{msg}{hint}"


def _local_asset(name: str, asset_dir: Path | None, max_size: int) -> Path | None:
    """本机上的那张图：在、是文件、不超上限才给路径。`asset_dir` 是测试注入的目录，生产读 assets 目录。"""
    if asset_dir is not None:
        p = asset_dir / name
    else:
        from . import assets as _assets_store
        p = _assets_store.assets_dir() / name
    return p if p.is_file() and p.stat().st_size <= max_size else None


_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}


class NotionWriter:
    # File Upload API 单次直传上限 20 MB（developers.notion.com/docs/uploading-small-files；更大要 multi_part）
    MAX_IMAGE = 20 * 1024 * 1024

    def __init__(self, token: str, *, call: Call | None = None, version: str = "2026-03-11", asset_dir: Path | None = None):
        self.h = {"Authorization": f"Bearer {token.strip()}", "Notion-Version": version, "Content-Type": "application/json"}
        self._call = call
        self._asset_dir = asset_dir

    def _req(self, method: str, path: str, json: dict | None = None) -> dict:
        if self._call:
            return self._call(method, path, json)
        try:
            if method == "UPLOAD":
                # File Upload 第二步是 multipart（字段名 `file`），不是 JSON；走同一个口子是为了测试能把它
                # 跟别的请求一起拦下来（跟 `FeishuWriter._req` 的 UPLOAD 同一个做法）
                j = dict(json or {})
                data, mime, name = j.pop("_data"), j.pop("_mime"), j.pop("_name")
                h = {k: v for k, v in self.h.items() if k != "Content-Type"}
                r = httpx.post("https://api.notion.com/v1" + path, headers=h, timeout=120,
                               files={"file": (name, data, mime)})
            else:
                r = httpx.request(method, "https://api.notion.com/v1" + path, headers=self.h, json=json, timeout=30)
        except httpx.RequestError as exc:
            raise RemoteError(f"连不上 Notion（{exc.__class__.__name__}: {exc}）——检查网络或代理", status=0, code="network")
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = {}
            # 先读 Notion 自己的 message，再翻成中文——之前 raise_for_status() 把它吞了，
            # 用户拿到的是 httpx 的英文 + MDN 链接（P2 报告 §2.4）
            raise RemoteError(explain_notion(r.status_code, str(body.get("message") or r.text[:200])),
                              status=r.status_code, code=str(body.get("code") or r.status_code))
        return r.json()

    def probe(self) -> None:
        """开跑前探一次：token 错就在这儿停，别让每一篇都发一次注定失败的请求。"""
        self._req("GET", "/users/me")

    def check_parent(self, page_id: str) -> None:
        self._req("GET", f"/pages/{page_id}")

    def upload_file(self, name: str, data: bytes, mime: str) -> str:
        """Notion File Upload API 两步（P18 #5，按 developers.notion.com/reference/create-a-file-upload 与
        send-a-file-upload 核过）：`POST /file_uploads` {filename, content_type} → id；
        `POST /file_uploads/{id}/send` multipart `file`。回 `file_upload` 的 id，之后一小时内要挂到块上。
        无凭据只能验到文档级：真账号第一次跑要核一下响应形状。"""
        d = self._req("POST", "/file_uploads", {"filename": name[:200], "content_type": mime})
        fid = str(d.get("id") or "")
        if not fid:
            raise RemoteError("Notion 没给这次上传分配 id", status=0, code="file_upload")
        self._req("UPLOAD", f"/file_uploads/{fid}/send", {"_data": data, "_mime": mime, "_name": name})
        return fid

    def prepare(self, blocks: list[dict]) -> list[dict]:
        """写之前把 `_asset` 标记的图片块换成真块：本机有文件 → 先传再挂 `file_upload`；
        没文件 / 传不上 → 一行说明（别留一个空图片块让整篇 400）。"""
        out: list[dict] = []
        for b in blocks:
            if not b.get("_asset"):
                out.append(b)
                continue
            alt = b.get("_alt") or "图片"
            p = _local_asset(b["_asset"], self._asset_dir, self.MAX_IMAGE)
            if not p:
                out.append(_notion_note(f"[图：{alt}]（文件不在本机）"))
                continue
            try:
                fid = self.upload_file(p.name, p.read_bytes(), _MIME.get(p.suffix.lower(), "application/octet-stream"))
            except (RemoteError, httpx.HTTPError, KeyError) as exc:
                out.append(_notion_note(f"[图：{alt}]（传不上 Notion：{exc}）"))
                continue
            out.append({"object": "block", "type": "image",
                        "image": {"type": "file_upload", "file_upload": {"id": fid}}})
        return out

    def create_page(self, parent_page_id: str, title: str, blocks: list[dict]) -> dict:
        blocks = self.prepare(blocks)
        d = self._req("POST", "/pages", {"parent": {"page_id": parent_page_id},
                                          "properties": {"title": {"title": [{"text": {"content": title[:200]}}]}},
                                          "children": blocks[:100]})
        pid = d["id"]
        for i in range(100, len(blocks), 100):
            self._req("PATCH", f"/blocks/{pid}/children", {"children": blocks[i:i + 100]})
            time.sleep(0.34)
        url = str(d.get("url") or "")
        rev = str(d.get("last_edited_time") or "")
        if len(blocks) > 100:
            page = self._req("GET", f"/pages/{pid}")
            rev = str(page.get("last_edited_time") or rev)
        return {"id": pid, "url": url or f"https://www.notion.so/{pid.replace('-', '')}", "rev": rev}

    def replace_children(self, page_id: str, title: str, blocks: list[dict]) -> dict:
        blocks = self.prepare(blocks)
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
        page = self._req("GET", f"/pages/{page_id}")
        return {"id": page_id, "url": str(page.get("url") or f"https://www.notion.so/{page_id.replace('-', '')}"),
                "rev": str(page.get("last_edited_time") or "")}

    def last_edited(self, page_id: str) -> str:
        return str(self._req("GET", f"/pages/{page_id}").get("last_edited_time") or "")


class FeishuWriter:
    # 一次 descendant 请求最多带多少个块：实测 1000 个段落 / 20×5 表格（201 块）都过；留余量按 300 切
    BATCH = 300
    MAX_IMAGE = 20 * 1024 * 1024

    def __init__(self, app_id: str, app_secret: str, *, call: Call | None = None, base: str = "https://open.feishu.cn/open-apis",
                 asset_dir: Path | None = None):
        self.app_id, self.app_secret, self.base = app_id.strip(), app_secret.strip(), base
        self._call = call
        self._token = ""
        self._asset_dir = asset_dir

    def _req(self, method: str, path: str, json: dict | None = None, auth: bool = True) -> dict:
        if self._call:
            return self._call(method, path, json)
        headers = {"Authorization": f"Bearer {self.token()}"} if auth else {}
        try:
            if method == "UPLOAD":
                # 素材上传是 multipart，不是 JSON；走同一个口子是为了测试能把它跟别的请求一起拦下来
                j = dict(json or {})
                data, mime = j.pop("_data"), j.pop("_mime")
                r = httpx.post(self.base + path, headers=headers, timeout=120, data={k: str(v) for k, v in j.items()},
                               files={"file": (j["file_name"], data, mime)})
            else:
                r = httpx.request(method, self.base + path, headers=headers, json=json, timeout=30)
        except httpx.RequestError as exc:
            raise RemoteError(f"连不上飞书（{exc.__class__.__name__}: {exc}）——检查网络或代理", status=0, code="network")
        return self._check(r)

    def _check(self, r: httpx.Response) -> dict:
        # 飞书 4xx 的响应体里就有 code / msg / error.helps（中文排查建议）——先读它，别先 raise_for_status
        try:
            d = r.json()
        except ValueError:
            raise RemoteError(f"飞书返回 {r.status_code}：{r.text[:200]}", status=r.status_code, code=str(r.status_code))
        code = d.get("code", 0 if r.status_code < 400 else r.status_code)
        if code != 0:
            helps = ((d.get("error") or {}).get("helps") or [{}])[0].get("description", "")
            raise RemoteError(explain_feishu(code, d.get("msg", ""), helps), status=r.status_code, code=str(code))
        return d

    def token(self) -> str:
        if not self._token:
            d = self._req("POST", "/auth/v3/tenant_access_token/internal",
                          {"app_id": self.app_id, "app_secret": self.app_secret}, auth=False)
            self._token = d.get("tenant_access_token") or ""
            if not self._token:
                raise RemoteError("飞书拒绝了这个应用", status=401, code="no-token")
        return self._token

    def probe(self) -> None:
        self.token()

    def create_document(self, folder_token: str, title: str) -> str:
        d = self._req("POST", "/docx/v1/documents", {"folder_token": folder_token, "title": title[:200]})
        return d["data"]["document"]["document_id"]

    def doc_url(self, doc_id: str) -> str:
        try:
            d = self._req("POST", "/drive/v1/metas/batch_query",
                          {"request_docs": [{"doc_token": doc_id, "doc_type": "docx"}], "with_url": True})
            return str(((d.get("data") or {}).get("metas") or [{}])[0].get("url") or "")
        except (RemoteError, KeyError, IndexError):
            return ""

    def _count_children(self, doc_id: str) -> int:
        n, token = 0, ""
        while True:
            d = self._req("GET", f"/docx/v1/documents/{doc_id}/blocks/{doc_id}/children?page_size=500"
                          + (f"&page_token={token}" if token else ""))
            data = d.get("data") or {}
            n += len(data.get("items") or [])
            if not data.get("has_more"):
                return n
            token = data.get("page_token") or ""
            if not token:
                return n

    @staticmethod
    def flatten(children: list[dict]) -> tuple[list[str], list[dict], list[tuple[str, dict]]]:
        """块树 → descendant 接口的 (children_id, descendants)；顺便把带 `_asset` 的图片块挑出来
        （(临时 id, 块)），写完拿真 id 去上传。"""
        ids: list[str] = []
        flat: list[dict] = []
        images: list[tuple[str, dict]] = []
        seq = 0

        def walk(b: dict) -> str:
            nonlocal seq
            seq += 1
            bid = f"b{seq}"
            node = {k: v for k, v in b.items() if not k.startswith("_") and k != "children"}
            node["block_id"] = bid
            kids = b.get("children") or []
            if kids:
                node["children"] = [walk(k) for k in kids]
            flat.append(node)
            if b.get("_asset") or b.get("_asset_bytes"):
                images.append((bid, b))
            return bid

        for b in children:
            ids.append(walk(b))
        return ids, flat, images

    def _asset_path(self, name: str) -> Path | None:
        return _local_asset(name, self._asset_dir, self.MAX_IMAGE)

    def upload_image(self, doc_id: str, block_id: str, path: Path | None, *,
                     data: bytes | None = None, name: str = "", mime: str = "") -> None:
        """飞书图片三步：空图片块（已建）→ `upload_all`（parent_type=docx_image, parent_node=块 id）→ `replace_image`。
        给 `path` 是本机文件；给 `data`+`name` 是内存里的字节（前端渲好的 mermaid PNG，P18 #4）——同一条路。"""
        if path is not None:
            data, name = path.read_bytes(), path.name
            mime = _MIME.get(path.suffix.lower(), "application/octet-stream")
        assert data is not None and name
        d = self._req("UPLOAD", "/drive/v1/medias/upload_all",
                      {"file_name": name, "parent_type": "docx_image", "parent_node": block_id, "size": len(data), "_data": data, "_mime": mime or "image/png"})
        token = (d.get("data") or {}).get("file_token") or ""
        if token:
            self._req("PATCH", f"/docx/v1/documents/{doc_id}/blocks/{block_id}", {"replace_image": {"token": token}})

    def replace_children(self, doc_id: str, children: list[dict]) -> None:
        # 删光：按页数到底（之前 page_size=500 不翻页，>500 块的文档只删前 500 块——P2 报告 §4.10）
        while (n := self._count_children(doc_id)):
            self._req("DELETE", f"/docx/v1/documents/{doc_id}/blocks/{doc_id}/children/batch_delete",
                      {"start_index": 0, "end_index": n})
        # 本地不存在的图片先换成一行说明，别留一个空图片块
        prepared = []
        for b in children:
            if b.get("_asset") and not self._asset_path(b["_asset"]):
                prepared.append({"block_type": 2, "text": _feishu_text(f"[图：{b.get('_alt') or '图片'}]（文件不在本机）")})
            else:
                prepared.append(b)
        def size(b: dict) -> int:
            return 1 + sum(size(k) for k in b.get("children") or [])

        index = 0
        i = 0
        while i < len(prepared):
            j, total = i, 0
            while j < len(prepared) and (j == i or total + size(prepared[j]) <= self.BATCH):
                total += size(prepared[j]); j += 1
            ids, flat, images = self.flatten(prepared[i:j])
            i = j
            d = self._req("POST", f"/docx/v1/documents/{doc_id}/blocks/{doc_id}/descendant",
                          {"children_id": ids, "index": index, "descendants": flat})
            created = (d.get("data") or {}).get("children") or []
            real = {tmp: (created[k] or {}).get("block_id", "") for k, tmp in enumerate(ids) if k < len(created)}
            for tmp, blk in images:
                rid = real.get(tmp)
                if not rid:
                    continue
                if blk.get("_asset_bytes"):
                    self.upload_image(doc_id, rid, None, data=blk["_asset_bytes"],
                                      name=blk.get("_asset_name") or "mermaid.png", mime="image/png")
                    continue
                p = self._asset_path(blk["_asset"])
                if p:
                    self.upload_image(doc_id, rid, p)
            index += len(ids)

    def edited_time(self, doc_id: str) -> str:
        d = self._req("GET", f"/docx/v1/documents/{doc_id}")
        return str((d.get("data") or {}).get("document", {}).get("revision_id") or "")
