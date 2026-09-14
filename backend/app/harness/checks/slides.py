"""幻灯片的判据：全是确定性的，零模型调用（docs/slides-plan.md）。

这几条判的不是「好不好看」，是**这份幻灯片还是不是这篇笔记的幻灯片**：
每一页有没有依据、数字有没有在总结的路上被改掉、有没有整节漏掉。
通用 PPT 工具做不到这几件事，因为它手上没有原文和引用。

不合格**不拦着落库**——幻灯片是一次成型的重构，不是多轮闭环；判据的结果
跟着产物一起显示，用户自己决定要不要重跑。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .citations import cited_ids

# 一页正文超过这么多字就是在把 PPT 当文档写
MAX_CHARS = 200
# 一页超过这么多条要点，读的人已经记不住了
MAX_BULLETS = 6
# 名词短语标题**只可能是短的**。第一版反过来做——枚举谓词、没命中就判不合格
# ——拿真产出一对就露馅了：24 页里点了 6 页，其中 5 页是
# 「APP目前只能确认存在实际使用」「硬件节点必须同时记录计划与结果」这种
# 完完整整的判断句，只是「必须」「经历了」不在我列的那张表上。
# **枚举语言现象的表永远补不全**，换成量的判断：短到这个份上才可能是名词短语。
NOUN_PHRASE_MAX = 6
# 短标题的第二次机会：短但带着变化 / 数字（「延到 8 月」）照样是判断句
_CLAIM = re.compile(r"[0-9]|是|要|把|从|到|改|降|涨|延|停|不|没|仍|已|将|需|应")


@dataclass(frozen=True)
class SlideCheck:
    pages: int
    """有引用标记的页数 / 总页数。"""
    cited_pages: int
    over_dense: list[int]
    """标题只是个名词短语的页（页码，从 1 数起）。"""
    weak_titles: list[int]
    """幻灯片里出现、原文里找不到的数字。"""
    stray_numbers: list[str]
    """原文有、幻灯片里没有对应页的小节标题。"""
    missed_sections: list[str]

    @property
    def cite_coverage(self) -> float:
        return round(self.cited_pages / self.pages, 2) if self.pages else 0.0

    def notes(self) -> list[str]:
        """给界面显示的人话。全都合格就是空列表。"""
        out: list[str] = []
        if self.pages and self.cite_coverage < 0.5:
            out.append(f"{self.pages} 页里只有 {self.cited_pages} 页带着引用编号——"
                       "一页没有依据的幻灯片跟通用工具做出来的没区别")
        if self.over_dense:
            out.append(f"第 {'、'.join(str(i) for i in self.over_dense)} 页太挤了"
                       f"（正文超过 {MAX_CHARS} 字或超过 {MAX_BULLETS} 条）")
        if self.weak_titles:
            out.append(f"第 {'、'.join(str(i) for i in self.weak_titles)} 页的标题只是个名词短语，"
                       "读的人要自己猜结论")
        if self.stray_numbers:
            out.append(f"这些数字原文里找不到：{'、'.join(self.stray_numbers[:6])}")
        if self.missed_sections:
            out.append(f"原文这几节没有对应的页：{'、'.join(self.missed_sections[:4])}")
        return out


_FENCE = re.compile(r"^```")


def split_pages(md: str) -> list[str]:
    """按 `---` 分页。**代码块里的 `---` 不算**——跟 `editor/outline.section_end`
    同一个坑：mermaid / yaml 块里横线很常见，切错一次整份就乱了。

    开头的 front-matter（第一行就是 `---`）不算一页。
    """
    lines = (md or "").split("\n")
    start = 0
    if lines and lines[0].strip() == "---":                 # front-matter
        for i, ln in enumerate(lines[1:], 1):
            if ln.strip() == "---":
                start = i + 1
                break
    pages: list[list[str]] = [[]]
    fenced = False
    for ln in lines[start:]:
        if _FENCE.match(ln.strip()):
            fenced = not fenced
        if not fenced and ln.strip() == "---":
            pages.append([])
            continue
        pages[-1].append(ln)
    return [p for p in ("\n".join(x).strip() for x in pages) if p]


def _sections(src: str) -> list[tuple[str, str]]:
    """原文按 `##` 切成 (标题, 这一节的正文)。"""
    parts = re.split(r"(?m)^##\s+(\S.*)$", src)
    return [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


_NUM = re.compile(r"\d+(?:\.\d+)?")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.、])\s+", re.M)


def check_slides(md: str, source: str) -> SlideCheck:
    pages = split_pages(md)
    cited = sum(1 for p in pages if cited_ids(p))
    dense: list[int] = []
    weak: list[int] = []
    for i, p in enumerate(pages, 1):
        body = re.sub(r"^#+\s+.*$", "", p, flags=re.M)
        if len(re.sub(r"\s", "", body)) > MAX_CHARS or len(_BULLET.findall(p)) > MAX_BULLETS:
            dense.append(i)
        head = next((m.group(1).strip() for m in re.finditer(r"^#+\s+(.*)$", p, re.M)), "")
        # **首末两页不算**：首页是标题页（本来就该是笔记的名字），末页是提示词
        # 规定的「还缺什么」。要求它们是判断句等于要求它们改名。
        plain = re.sub(r"[\s\W_]", "", head)
        if 1 < i < len(pages) and 0 < len(plain) <= NOUN_PHRASE_MAX and not _CLAIM.search(head):
            weak.append(i)

    # 数字对账：幻灯片里出现、原文里一次都没出现的。**总结的时候把数字改掉**
    # 是这类产物最隐蔽的错（读者没法从幻灯片本身看出来）。
    src_nums = set(_NUM.findall(source or ""))
    stray: list[str] = []
    for n in _NUM.findall("\n".join(pages)):
        if n not in src_nums and n not in stray and len(n) >= 2:
            stray.append(n)

    # 整节漏掉。**不能只比标题**：原文的「时间线与里程碑」这种结构性标题，内容
    # 被拆进了好几页各自的判断句里，按标题比会报一个不存在的漏（真产出实拍，
    # 24 页那次误报了 3 节）。所以再看一眼**这一节的引用编号有没有进到幻灯片里**
    # ——依据进去了，这一节就是覆盖到了。
    flat = "\n".join(pages)
    shown = set(cited_ids(flat))
    missed = [t for t, body in _sections(source or "")
              if t not in flat and not (set(cited_ids(body)) & shown)]
    return SlideCheck(pages=len(pages), cited_pages=cited, over_dense=dense,
                      weak_titles=weak, stray_numbers=stray, missed_sections=missed)
