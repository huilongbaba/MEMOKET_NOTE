"""Deterministic, non-LLM citation verification.

The gap this closes: a model can be asked to self-report which source
material a claim rests on (the same "cite your sources" instruction already
used elsewhere in this package's host application), but that self-report is
itself just more model output -- nothing stops it from citing something
that sounds like a real source but was never actually shown to it. That
failure mode is different from "ungrounded" (no citation at all): it's a
*fabricated* citation, which reads as more trustworthy than no citation,
not less.

check_citations() answers a narrower, mechanically-verifiable question:
does each claimed source string actually match something in the pool of
material the model was given? A low match means the citation doesn't
correspond to real input -- evidence to feed into evaluate() (see
CitationCheck usage in rubric.py's citation_hints parameter), not a
verdict on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

DEFAULT_MATCH_THRESHOLD = 0.7


@dataclass(frozen=True)
class CitationCheck:
    """One claimed source's best match against the available material.
    ``best_match`` is already None whenever the best similarity found fell
    below whatever threshold check_citations() was called with -- ``verified``
    just reflects that, it does not re-derive against a fixed constant (an
    earlier version did, and disagreed with the threshold actually used)."""

    claimed: str
    best_match: str | None
    similarity: float

    @property
    def verified(self) -> bool:
        return self.best_match is not None


def check_citations(
    claimed_sources: list[str],
    available_facts: list[str],
    *,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> list[CitationCheck]:
    """For each string in ``claimed_sources``, find its best fuzzy match in
    ``available_facts`` and report the similarity. A claimed source with no
    match above ``threshold`` was not actually among the material the model
    was shown -- it's citing something that doesn't exist in its own input,
    not just paraphrasing loosely."""
    checks: list[CitationCheck] = []
    for claimed in claimed_sources:
        if not claimed.strip():
            continue
        best_match, best_ratio = None, 0.0
        for fact in available_facts:
            ratio = SequenceMatcher(None, claimed, fact).ratio()
            if ratio > best_ratio:
                best_match, best_ratio = fact, ratio
        checks.append(CitationCheck(
            claimed=claimed,
            best_match=best_match if best_ratio >= threshold else None,
            similarity=round(best_ratio, 3),
        ))
    return checks


# ---------------------------------------------------------------- 按 id 的引用
#
# 上面那套是**模糊文本**匹配（模型自报"我引用了哪句"）。有了事实 id 之后引用
# 是确定性的：正文里的 ``[terrence-1872-5F8]`` 要么在这轮给它的材料里、要么
# 在知识库里，否则就是编的——而"编一个像真的一样的引用"比"不引用"更糟：
# 它读起来更可信。
#
# 跟 store._CITE / 前端 editor/factCite.ts 用同一条正则。三处认的不是同一批，
# 树上的角标、行内浮层、这条判据就会互相打架。

import re as _re

CITE = _re.compile(r"\[([A-Za-z][A-Za-z0-9_-]*-(?:\d+|[0-9a-f]{12})-[0-9A-Fa-f]+)\]")
_HEAD_ID = _re.compile(r"^\[([A-Za-z][A-Za-z0-9_-]*-(?:\d+|[0-9a-f]{12})-[0-9A-Fa-f]+)\]")


def cited_ids(text: str) -> list[str]:
    """正文里引用了哪些事实 id。去重，保持出现顺序。"""
    seen: dict[str, None] = {}
    for m in CITE.finditer(text or ""):
        seen.setdefault(m.group(1), None)
    return list(seen)


def supplied_ids(facts: list[str]) -> set[str]:
    """这轮喂给模型的材料里带了哪些 id（``[id] …`` 开头的那些）。"""
    out = set()
    for f in facts:
        m = _HEAD_ID.match(f or "")
        if m:
            out.add(m.group(1))
    return out


def dangling_citations(text: str, facts: list[str], exists) -> list[str]:
    """正文里引用了、但既不在材料里也查不到的 id。

    ``exists(id) -> bool`` 由调用方注入（生产是 UserMemory.fact_by_id，测试是
    一个集合）——这个模块保持纯函数、不碰 I/O，跟 checks 包的其他判据一个纪律。
    只对不在材料里的 id 才去查库：材料里有的一定存在，省一次查询。
    """
    have = supplied_ids(facts)
    return [fid for fid in cited_ids(text) if fid not in have and not exists(fid)]


# 「长得像引用」：`[前缀-xxx-yyy]` 至少两段短横，不跟着 `(`（那是 markdown 链接）、前面不是 `[`
# （那是 [[wiki 链接]]）。模型偶尔编出 `[terrence-23F3-4F3]` 这种段落顺序不对的 id——它不匹配
# CITE，于是既不被当引用检查、也不画成引用，就那么留在正文里（第 139 轮实拍 magic tap）。
_LOOSE = _re.compile(r"(?<!\[)\[([A-Za-z][A-Za-z0-9_]*(?:-[0-9A-Za-z]+){2,})\](?!\()")


def malformed_citations(text: str) -> list[str]:
    """正文里长得像引用、但不是合法 id 的方括号。"""
    valid = set(cited_ids(text))
    out: dict[str, None] = {}
    for m in _LOOSE.finditer(text or ""):
        if m.group(1) not in valid:
            out.setdefault(m.group(1), None)
    return list(out)


def fake_citations(text: str, facts: list[str], exists) -> list[str]:
    """编造的引用 = 合法格式但查不到的（dangling）+ 格式就不对的（malformed）。"""
    return dangling_citations(text, facts, exists) + malformed_citations(text)


# ---------------------------------------------------------------- 引笔记（P15 #2）
#
# 托盘里的**笔记**被用上时，正文里的出处不是 `[事实编号]`，是 `[标题](note://id)`（`harness/tray.py`
# 定的：笔记项照抄它开头的 `[标题](note://id)` 链回去）。P14 真跑：最终正文引了托盘那两篇 5 次、
# 事实编号 1 次，第 1、2 轮却被 `citations_present` 短路——它只数 `[事实编号]`，把「引了两篇笔记」
# 判成「一个编号都没有」。
#
# 跟 `store._NOTE_LINK` / 前端 `util/wordCount.NOTE_LINK_RE` 同一条正则（`check-regex-parity` 对拍的
# 是行为）：12 位十六进制的笔记 id，标题里不许有换行 / 右方括号。
NOTE_LINK = _re.compile(r"\[([^\]\n]*)\]\(note://([0-9a-f]{12})\)")


def note_link_ids(text: str) -> list[str]:
    """正文里链到（= 引用了）哪些笔记 id。去重，保持出现顺序。"""
    seen: dict[str, None] = {}
    for m in NOTE_LINK.finditer(text or ""):
        seen.setdefault(m.group(2), None)
    return list(seen)


def has_citation(text: str) -> bool:
    """这段字里有没有任何一种出处：`[事实编号]` 或 `[标题](note://id)`。

    「这一轮一个引用都没有」这个谓词有两个读者（`citations_present` / `material_thin` 的 (b) 档），
    两处都读这一个——判据认两种、材料薄那条只认一种，就是「同一件事挡住一半」。"""
    return bool(cited_ids(text) or note_link_ids(text))


# 被引的那句话：从上一个句读（。！？；换行）到链接为止。太短（链接顶在行首、列表项开头）就退回整行。
_SENT_BREAK = _re.compile(r"[。！？；\n]")
MIN_NOTE_SENTENCE = 6
# 那句话跟那篇笔记至少共用几个特征词（英文词 / 数字 / 中文 2-gram，`grounding_rules._terms`）才算「在那篇里找得到依据」。
# 跟 `fact_usage` 的 `min_overlap=3` 同一个数：三个以上才像是真的从那篇来的；P14 真跑里 5 处引笔记的句子
# 跟被引那篇共用 30–51 个（台账 P15 #2），编的「那篇里说过 2027 年要上市，融资五千万」是 0 个、
# 「团队决定把总部搬到杭州」是 2 个。
MIN_NOTE_SHARED = 3


def _sentence_before(text: str, at: int) -> str:
    head = text[:at]
    m = None
    for m in _SENT_BREAK.finditer(head):
        pass
    sent = head[m.end():] if m else head
    sent = CITE.sub("", NOTE_LINK.sub("", sent)).strip(" \t-*•>0123456789.、")
    if len(sent) < MIN_NOTE_SENTENCE:
        line_start = head.rfind("\n") + 1
        line_end = text.find("\n", at)
        line = text[line_start:line_end if line_end >= 0 else len(text)]
        sent = CITE.sub("", NOTE_LINK.sub("", line)).strip(" \t-*•>0123456789.、")
    return sent


def note_citations_unsupported(text: str, get_note, *, min_shared: int = MIN_NOTE_SHARED) -> list[dict]:
    """正文里每一处 `[标题](note://id)`：那篇得存在，而且引它的那句话在那篇里得找得到依据（词法）。

    `get_note(id) -> 正文 | None` 由调用方注入（生产是 `store.get_note`，测试是一个字典）——跟
    `dangling_citations` 的 `exists` 一个纪律：这个模块不碰 I/O。
    返回没通过的那几处：`{"id", "title", "sentence", "why": "missing" | "unsupported", "shared": n}`。
    同一篇同一句只报一次。
    """
    from .grounding_rules import _terms
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    body_terms: dict[str, set[str] | None] = {}
    for m in NOTE_LINK.finditer(text or ""):
        title, nid = m.group(1), m.group(2)
        sent = _sentence_before(text, m.start())
        if (nid, sent) in seen:
            continue
        seen.add((nid, sent))
        if nid not in body_terms:
            body = get_note(nid)
            body_terms[nid] = _terms(body) if isinstance(body, str) else None
        terms = body_terms[nid]
        if terms is None:
            out.append({"id": nid, "title": title, "sentence": sent, "why": "missing", "shared": 0})
            continue
        shared = len(_terms(sent) & terms)
        if shared < min_shared:
            out.append({"id": nid, "title": title, "sentence": sent, "why": "unsupported", "shared": shared})
    return out


def strip_citations(text: str, ids: list[str]) -> str:
    """把指定的 ``[id]`` 从正文里摘掉（连同它前面的空格）。给 Verdict.fix 用：
    去掉一个编造的引用不需要任何语义判断。"""
    for fid in ids:
        text = _re.sub(r"\s*\[" + _re.escape(fid) + r"\]", "", text)
    return text


# 同一组事实被写了两遍。段落级查重看不见它（整段两两相似度只有 0.39——
# 两段各自还有别的话，被稀释掉了），清单级查重也看不见（没有顿号清单）。
# 但**它们引的是同一组编号**，而编号是我们自己发的、可以精确比对的。
#
# 第 608 轮读产出抓到的那一对：
#   「付款安排本身也要保留触发条件。已有讨论中，供应商流程是先完成货物，再由我们
#     验货；验货通过后开票，付清尾款，之后才发货 [1459-8F1] [1459-8F2]。」
#   「商业动作还要按"付款、验货、发货、使用"拆开…供应商完成生产后，需要先由我方
#     验货，验货确认无误后再开票、支付尾款，之后才发货 [1459-8F1] [1459-8F2]。」
# 同一件事、同一组依据，换了个说法又说了一遍。
#
# 共享 2 个以上编号才报：共一个太常见（一条事实被两段从不同角度用上是正常的），
# 共两个以上就说明两段站在同一批依据上。阈值是量出来的——这几轮攒下的 30 份
# harness 产出、548 段（其中 95 段带 ≥2 个引用）里只命中这一对，没有误报。
MIN_SHARED_CITES = 2


def same_sources_twice(text: str, before: str = "", limit: int = 2) -> list[tuple[str, str]]:
    """两段正文站在同一批事实编号上，把同一件事说了两遍。

    `before` = 开跑时正文里已经有的字；两段**都**在里面就不报。

    **量程口径跟 `blockcheck.repeated_lists` 一起换的（批 25）**，而且是**同一处
    机制的第二个调用点**——原来两条都写着 `if fresh and a not in fresh and …`。
    这条判据在批 24 那份语料上一次都没开过火（`alive=False`），所以**分母是 0，
    这一改量不出任何东西**；跟着改的理由不是数据，是 §21 那条「同一件事挡住一半
    等于没挡」：一个会消失的量程修了一处、留了一处，下一次踩的就是留下的那处。
    """
    paras = [p.strip() for p in (text or "").split("\n\n") if len(p.strip()) >= 60]
    sets = [(p, set(cited_ids(p))) for p in paras]
    out: list[tuple[str, str]] = []
    for i, (pa, sa) in enumerate(sets):
        if len(sa) < MIN_SHARED_CITES:
            continue
        for pb, sb in sets[i + 1:]:
            if pa in before and pb in before:
                continue
            if len(sa & sb) >= MIN_SHARED_CITES:
                out.append((pa, pb))
                if len(out) >= limit:
                    return out
    return out
