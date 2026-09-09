"""把别家笔记应用的内容洗成 memoket-note 能吃的干净 markdown。

四个来源（Apple Notes / Notion / Evernote / Obsidian）拿内容的方式差别很大，
但**洗内容这一步是共用的**，所以放在这里做成纯函数：不碰网络、不碰文件系统、
不依赖 app 的其他模块，可以单独测。取内容和 POST 的活在
``scripts/import_notes.py``。

调研与各来源的坑见 ``docs/import-from-other-note-apps.md``。
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass
from datetime import date as _date

# ---------------------------------------------------------------- 统一的产物


@dataclass(frozen=True)
class ImportedNote:
    """洗干净之后交给导入器的一条笔记。

    ``source_id`` 必须在源侧稳定（Notion page_id、Obsidian 相对路径的哈希、
    ENEX 的 guid…）——它会被拼进 KITE 的 session_id，重跑导入时靠它跳过已导
    入的内容，不花 LLM 调用。给个随机值等于每次导入都翻倍。
    """

    title: str
    content: str
    date: str = ""            # YYYY-MM-DD，拿不到就留空（由调用方决定退回什么）
    source: str = "import"    # obsidian / notion / apple / evernote
    source_id: str = ""
    folder: str = ""          # 源侧的文件夹/笔记本名，用于在这边归类


# ---------------------------------------------------------------- 日期

_DATE_PATTERNS = (
    re.compile(r"^(\d{4})-(\d{2})-(\d{2})"),                    # 2026-03-15…
    re.compile(r"^(\d{4})(\d{2})(\d{2})T"),                     # 20260315T091500Z（ENEX）
    re.compile(r"^\w+,\s+(\d{1,2})\s+(\w+)\s+(\d{4})"),         # AppleScript 的英文日期
)
_MONTHS = {m: f"{i:02d}" for i, m in enumerate(
    "January February March April May June July August September "
    "October November December".split(), 1)}


def normalize_date(raw: str | None) -> str:
    """把各家五花八门的日期格式统一成 YYYY-MM-DD；认不出来返回空串。

    认不出来**不要瞎猜**：调用方拿到空串会退回文件 mtime 或今天，而一个猜错
    的日期比没有日期更糟——它会以"看起来可信"的样子进知识库。
    """
    s = (raw or "").strip()
    if not s:
        return ""
    m = _DATE_PATTERNS[0].match(s) or _DATE_PATTERNS[1].match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _DATE_PATTERNS[2].match(s)
    if m and m.group(2) in _MONTHS:
        return f"{m.group(3)}-{_MONTHS[m.group(2)]}-{int(m.group(1)):02d}"
    return ""


def today() -> str:
    return _date.today().isoformat()


# ---------------------------------------------------------------- Obsidian

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?", re.S)
_WIKI = re.compile(r"\[\[([^\]|#]+?)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")
# 只吃行内的空白，**不要吃换行**：吃掉换行会让紧跟其后的代码块不在行首，
# 后面按行首匹配的 dataview 清理就整个失效（自测当场抓到）。
_EMBED = re.compile(r"!\[\[[^\]]+\]\][ \t]*")
_CODE_FENCE = re.compile(r"^```(\w*)\n.*?^```\s*$", re.M | re.S)
# Obsidian 生态里这几种代码块是"模板/查询"，不是内容，抽取时纯噪声
_TEMPLATE_LANGS = {"dataview", "dataviewjs", "templater", "tasks", "query", "meta-bind"}


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """拆出 YAML frontmatter。只做扁平的 ``key: value``——嵌套结构对导入没用，
    不值得为它引一个 YAML 依赖。"""
    m = _FRONTMATTER.match(text or "")
    if not m:
        return {}, text or ""
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.lstrip().startswith("-"):
            k, _, v = line.partition(":")
            meta[k.strip().lower()] = v.strip().strip("'\"")
    return meta, text[m.end():]


def clean_obsidian(text: str) -> str:
    """把 Obsidian 特有语法洗成普通 markdown。

    - ``[[A|B]]`` → ``B``、``[[A#锚点]]`` → ``A``：抽取时链接语法是噪声，
      而链接**文字**往往是实体名，要留下
    - ``![[附件.png]]``：整条删掉，KITE 只吃文本
    - dataview/templater 代码块：删掉，那是模板不是内容
    """
    body = _EMBED.sub("", text or "")
    body = _WIKI.sub(lambda m: (m.group(2) or m.group(1)).strip(), body)
    body = _CODE_FENCE.sub(
        lambda m: "" if m.group(1).lower() in _TEMPLATE_LANGS else m.group(0), body)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


# ---------------------------------------------------------------- HTML / ENML

_BLOCK_TAGS = ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
               "blockquote", "pre")


def html_to_markdown(source: str) -> str:
    """把 Apple Notes 的 HTML / Evernote 的 ENML 转成朴素 markdown。

    刻意只做**结构**（标题、列表、粗体、链接、换行），不追求还原排版：进知识库
    的是文字和其中的事实，样式一点用没有，而每多一条转换规则就多一处会出错的
    地方。

    没有引 markdownify/html2text 是因为这两家的标记都是受限子集：Apple Notes
    的 body 是 Notes.app 自己生成的简单 HTML，ENML 是 XHTML 的子集且有自己的
    DTD（``<en-note>``/``<en-media>``）——通用转换器在 ``<en-media>`` 上会留下
    垃圾，还是得自己处理。
    """
    if not source or not source.strip():
        return ""
    try:
        from lxml import etree, html as lhtml
    except ImportError:                       # pragma: no cover - lxml 是既有依赖
        return re.sub(r"<[^>]+>", "", source)

    # ENML 的 <en-media>（附件）和 <en-crypt>（加密块）先整个去掉：前者是
    # base64 附件的占位，后者根本解不开，留着只会变成正文里的乱码。
    cleaned = re.sub(r"<en-(media|crypt)\b[^>]*?(/>|>.*?</en-\1>)", "", source, flags=re.S)
    try:
        root = lhtml.fromstring(cleaned)
    except (etree.ParserError, ValueError):
        return re.sub(r"<[^>]+>", "", cleaned).strip()

    out: list[str] = []

    def walk(el, depth: int = 0) -> None:
        tag = (el.tag if isinstance(el.tag, str) else "").lower()
        if tag in ("script", "style", "en-media", "en-crypt"):
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            out.append(f"\n\n{'#' * int(tag[1])} {el.text_content().strip()}\n\n")
            return
        if tag == "li":
            # 只取这一项**自己**的文字，不要把嵌套子列表的内容一起吞进来
            # （用 text_content() 会把「乙」和它下面的「丙」压成「乙丙」）。
            own = [el.text or ""]
            nested = []
            for child in el:
                if (child.tag if isinstance(child.tag, str) else "").lower() in ("ul", "ol"):
                    nested.append(child)
                else:
                    own.append(child.text_content())
                own.append(child.tail or "")
            # depth 是「外面套了几层 ul/ol」，最外层的列表项不该有缩进
            out.append(f"\n{'  ' * max(0, depth - 1)}- {''.join(own).strip()}")
            for sub in nested:
                walk(sub, depth)
            return
        if tag == "a":
            href = (el.get("href") or "").strip()
            txt = el.text_content().strip()
            out.append(f"[{txt}]({href})" if href and txt else txt)
            return
        if tag in ("b", "strong"):
            txt = el.text_content().strip()
            out.append(f"**{txt}**" if txt else "")
            return
        if tag == "br":
            out.append("\n")
            return
        if el.text:
            out.append(el.text)
        for child in el:
            walk(child, depth + 1 if tag in ("ul", "ol") else depth)
            if child.tail:
                out.append(child.tail)
        if tag in _BLOCK_TAGS:
            out.append("\n")

    walk(root)
    text = _html.unescape("".join(out))
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------- Evernote ENEX


def parse_enex(xml_bytes: bytes, *, limit: int = 0) -> list[ImportedNote]:
    """解析一个 ``.enex``。

    用 ``iterparse`` 流式解析而不是一次读进内存：大笔记本的 ENEX 能到几百 MB，
    而其中绝大部分体积是 ``<resource>`` 里的 base64 附件——那些正是我们要丢掉的。
    """
    from lxml import etree

    notes: list[ImportedNote] = []
    ctx = etree.iterparse(_BytesReader(xml_bytes), events=("end",), tag="note",
                          recover=True, huge_tree=True)
    for _ev, el in ctx:
        title = (el.findtext("title") or "").strip() or "无标题"
        content = el.findtext("content") or ""
        created = normalize_date(el.findtext("created"))
        guid = (el.findtext("guid") or "").strip()
        body = html_to_markdown(content)
        if body:
            notes.append(ImportedNote(
                title=title, content=body, date=created, source="evernote",
                # 没有 guid 就退回标题+日期：ENEX 导出不一定带 guid，而完全
                # 没有稳定标识会让重跑导入把内容翻倍。
                source_id=guid or f"{title}-{created}"))
        el.clear()
        while el.getprevious() is not None:
            del el.getparent()[0]
        if limit and len(notes) >= limit:
            break
    return notes


class _BytesReader:
    """给 lxml.iterparse 用的最小 file-like，免得把大 ENEX 落成临时文件。"""

    def __init__(self, data: bytes) -> None:
        self._data, self._pos = data, 0

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = len(self._data) - self._pos
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk
