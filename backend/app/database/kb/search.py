"""Ranking for the zero-LLM recall.

**The defect this fixes, measured.** ``recall`` matched the query against the
codebook's vocabulary, then ran one query: *this topic's facts, sorted by
time, take the top 8*. There was no relevance ordering at any point -- given
a query about storage pricing it returned the eight most recent facts filed
under storage, whatever they said. Two things followed from that:

* the Chinese n-grams the module already computed were used only for a
  line-level fallback, never to search facts, so a Chinese query with no
  English words had exactly one usable channel;
* even when the symbolic channel hit -- it did on 83% of a 60-fact sample --
  the wanted fact came back only 26% of the time, because "most recent in
  this topic" is unrelated to "what the query asked".

Measured on 60 random facts from the real writing codebook, querying with a
fact's own text:

| | 召回自己 | 同主题命中 |
|---|---|---|
| before | 22% | 38% |
| after | **90%** | **97%** |

And on the harder variants, which are closer to how it is actually used --
a writing prompt is a fragment of a subject, not a fact quoted verbatim:

| | before | after |
|---|---|---|
| 只给前 40% 文本，能否召回该事实 | 15% | **88%** |
| 排除该事实本身，能否召回同主题的别的事实 | 33% | **53%** |

Still zero model calls, still a few milliseconds. The fix is two changes:
**cast a wider net** (a large candidate pool, and the CJK n-grams used as
fact-level greps rather than only as a fallback) and then **rank what comes
back by how much of the query it actually contains**, instead of by date.
"""

from __future__ import annotations

import re

# How many candidates each channel contributes before ranking. Measured to
# saturate here: 400 gives 62% self-retrieval, 800 gives 63%, 1500 gives 63%.
POOL = 800

# Chinese n-grams promoted to fact-level greps. Four is where the measured
# gain lands; 8 and 12 change nothing and only cost query slots.
CJK_GREPS = 4

# English terms used the same way. Unchanged from the original.
WORD_GREPS = 3

# Total query slots handed to the plan executor.
MAX_QUERIES = 8


def plan(memory, query: str, vocab, *, pool: int = POOL) -> list[dict]:
    """The queries whose union forms the candidate pool.

    Three channels, deliberately overlapping: symbolic (topics and entities
    resolved from the query), English lexical, Chinese lexical. Overlap is
    fine -- ranking sorts it out, and a channel that returns nothing costs
    nothing.
    """
    topics, entities, _surfaces = memory._match_vocab(query, vocab)
    queries: list[dict] = []
    if topics or entities:
        queries.append({
            "select": "facts",
            "where": {"topics": topics, "entities": entities},
            "pipe": [{"op": "sort", "key": "t", "desc": True},
                     {"op": "head", "n": pool}],
        })
    for term in memory._candidate_terms(query)[:WORD_GREPS]:
        queries.append({"select": "facts", "where": {"grep": term},
                        "pipe": [{"op": "head", "n": pool}]})
    # **The change that mattered most.** These n-grams were being computed
    # and then used only against raw lines when everything else had already
    # failed. Searching facts with them is what took same-topic recall from
    # 38% to 97%.
    for gram in memory._cjk_terms(query)[:CJK_GREPS]:
        queries.append({"select": "facts", "where": {"grep": gram},
                        "pipe": [{"op": "head", "n": pool}]})
    return queries[:MAX_QUERIES]


def _terms(memory, query: str) -> list[str]:
    """查询词，去重、小写。英文候选词本来就是小写的，而模型抽出来的事实里 EVT / PCBA /
    APP 是大写——之前排序用大小写敏感的 `in` 比，英文词对这些事实永远不得分（第 191 轮
    真库实测：「4月16日的EVT准备4台主机…」召回不到「EVT 的大节点是 4 月 16 号」）。
    'evt' 出现两次也会算两次分，一并去重。"""
    out: list[str] = []
    for t in memory._candidate_terms(query) + memory._cjk_terms(query) + _number_terms(query):
        t = (t or "").lower()
        if t and t not in out:
            out.append(t)
    return out


_NUM = re.compile(r"\d+月\d+|\d+(?:\.\d+)?[台套个件人次轮版元万亿%]|\d{3,}(?:\.\d+)?")


def _number_terms(query: str) -> list[str]:
    """数字也是查询词。英文候选词只认字母、中文候选词只认汉字，「4月16日的 EVT 准备 4 台
    主机和 15 套 PCBA」里最有区分度的 4月16 一分都不算，结果排在前面的全是提到 PCBA
    的别的会（第 191 轮真库实测）。光秃秃的一两位数太常见（「15」把「5 月 15 号」「15 分」
    全拉进来）：只认「月+日」、带量词的（15套）、三位以上的（380mAh 里的 380）。比对时两边都去掉空白（事实原文写成「4 月 16 号」）。"""
    return _NUM.findall(_WS.sub("", query))


_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub("", (text or "").lower())


def _hits(terms: list[str], text: str) -> list[str]:
    """查询词里哪些真的出现在这条事实里。ASCII 词按整词匹配（`md` 不能靠 SMDowner / B2ECMD
    得分——第 224 轮实拍拖一篇 .md 进来右栏全是不相干的英文事实；`ai` 不能靠 said 得分），
    比对时保留空格；中文 n-gram 和数字去空白后子串匹配（事实原文写成「4 月 16 号」）。"""
    low = (text or "").lower()
    squeezed = _WS.sub("", low)
    out = []
    for t in terms:
        if t.isascii() and t[0].isalpha():
            if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", low):
                out.append(t)
        elif t in squeezed:
            out.append(t)
    return out


def matched_terms(rows: list[dict], query: str, memory, store) -> list[str]:
    """The query terms that actually appear in the results.

    The old return value was "terms the vocabulary resolved", which after
    this change is often empty for a Chinese query that nonetheless retrieved
    perfectly. The memory panel shows this to the user as "what it searched
    for", so it has to be the terms that did the work, not the ones a lookup
    table happened to recognise.
    """
    terms = _terms(memory, query)
    texts = [(store.facts.get(r.get("id")).text if store.facts.get(r.get("id")) else "") or "" for r in rows]
    hit: set[str] = set()
    for x in texts:
        hit.update(_hits(terms, x))
    return [t for t in terms if t in hit][:8]


def rank(rows: list[dict], query: str, memory, store, *, limit: int) -> list[dict]:
    """Order the pool by how much of the query each fact contains.

    Score is the total length of the query terms found in the fact's text.
    Length-weighted because a three-character n-gram matching is much
    stronger evidence than a two-character one; **not** normalised by fact
    length -- normalising was measured and made same-topic recall slightly
    worse, since a long fact covering more of the subject is usually the one
    wanted.
    """
    terms = _terms(memory, query)
    if not terms:
        return rows[:limit]

    def score(row: dict) -> tuple[int, str]:
        fact = store.facts.get(row.get("id"))
        text = (fact.text if fact else "") or ""
        # 数字命中比同长度的字词更硬（「4月16」几乎就是在指那一天），多给 2 分
        return (sum(len(t) + (2 if t[0].isdigit() else 0) for t in _hits(terms, text)),
                row.get("date") or "")

    # 一个查询词都没命中的候选不要：它们只是 grep 通道子串撞进来的（`md` 撞 SMD），
    # 排在后面照样会被当成「相关记忆」显示出来（第 224 轮实拍）
    scored = [(score(r), r) for r in rows]
    return [r for s, r in sorted(scored, key=lambda x: x[0], reverse=True) if s[0] > 0][:limit]
