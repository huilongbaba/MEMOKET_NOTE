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

CITE = _re.compile(r"\[([A-Za-z][A-Za-z0-9_-]*-\d+-[0-9A-Fa-f]+)\]")
_HEAD_ID = _re.compile(r"^\[([A-Za-z][A-Za-z0-9_-]*-\d+-[0-9A-Fa-f]+)\]")


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


def strip_citations(text: str, ids: list[str]) -> str:
    """把指定的 ``[id]`` 从正文里摘掉（连同它前面的空格）。给 Verdict.fix 用：
    去掉一个编造的引用不需要任何语义判断。"""
    for fid in ids:
        text = _re.sub(r"\s*\[" + _re.escape(fid) + r"\]", "", text)
    return text
