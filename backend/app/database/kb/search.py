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

from .who import is_speaker_tag

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
    # 查询里认出的实体扩到同一组的所有写法：问「MemoCat」也要拿到挂在 memo_cat 上的事实（kb/entities.py）
    if entities and hasattr(memory, "_index"):
        try:
            from . import entities as entities_mod
            store, _ = memory._index()
            g = entities_mod.for_store(store, vocab)
            entities = list(dict.fromkeys(m for e in entities for m in g.members(e)))
        except Exception:      # noqa: BLE001 — 假的 memory / 没索引就按原样
            pass
    queries: list[dict] = []
    if topics or entities:
        queries.append({
            "select": "facts",
            "where": {"topics": topics, "entities": entities},
            "pipe": [{"op": "sort", "key": "t", "desc": True},
                     {"op": "head", "n": pool}],
        })
    # grep 的英文词也先剔虚词 / 说话人标签：英文事实前三个候选词常常是 it / speaker a / says，
    # 三个 grep 槽全浪费在它们身上，事实根本进不了候选池（第 527 轮自召回三条 miss 都不在池里）
    words = [t for t in memory._candidate_terms(query) if t.lower() not in _EN_STOP and not _is_speaker_word(t.lower())]
    for term in (words or memory._candidate_terms(query))[:WORD_GREPS]:
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


# 拿正文当查询之前要剥掉的东西（跟前端 util/wordCount.stripForRecall 同一条规则，
# scripts/check-regex-parity 对拍）：引用标记里的 id、整条图片、链接地址（只留链接文字）。
# 实拍：拖一张图进空笔记，右栏立刻冒出 Bill Browder / Russia 的英文事实——查询词就是那行
# `![probe](/api/assets/…png)`，「assets」撞上了「assets of Russia frozen」。
# 前端在发请求前剥过一遍，但**后端自己也拿正文查**（选中校验 compose、摄入冲突扫描 inbox、
# 写作取材料），那几条路原来是带着标记去查的（第 566 轮）。剥两次幂等，两边都留着。
_IMG_MD = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_MD = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_CITE_MARK = re.compile(r"\[[A-Za-z][\w-]*-(?:\d+|[0-9a-f]{12})-[0-9A-Fa-f]+\]")
# `<|start|>` 这种转写残留的乱码（P4 表 A #3）：`start` 被当成英文查询词，8 条候选全是 start-up。
_GARBAGE = re.compile(r"<\|[^|>]*\|>")


def clean_query(text: str) -> str:
    s = _IMG_MD.sub("", text or "")
    s = _LINK_MD.sub(r"\1", s)
    s = _CITE_MARK.sub("", s)
    s = _GARBAGE.sub(" ", s)
    return re.sub(r"[ \t]{2,}", " ", s)


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
    # 英文虚词和「speaker a」这种说话人标签不当查询词：英文事实几乎每条都是「Speaker B says …」，
    # 这些词一人一分把真正的内容词稀释掉——第 527 轮自召回复测三条 miss 全是这个样子
    # （terms= ['it', 'speaker a', 'speaker', 'says', 'can', …]）。全是虚词时退回原样，别搜不出东西。
    kept = [t for t in out if t not in _EN_STOP and not _is_speaker_word(t)
            and not _is_cn_filler(t)]
    # 全被剔光时怎么办，**分两种情况**（第 747 轮真库量出来的）：
    # · 查询很短（用户主动在搜「总结」这种词）→ 退回原样，别搜不出东西（第 527 轮那条）；
    # · 查询是一长句（跟着正文自动召回、或者一句任务指令）→ **就该什么都不返回**。
    #   实测「帮我总结一下」在两万条的真库里得分 **20**，比真正相关的命中（8 分）还高——
    #   因为整句口水话在会议记录里原样出现，还被切成 8 个重叠片段叠加。
    #   这种时候捞回来的每一条都是噪声，**宁可空着**。
    if kept:
        return kept
    return out if len(query.strip()) <= _SHORT_QUERY else []


_EN_STOP = frozenset("""
a an the it its is are was were be been being can could will would shall should may might must
they them their he she his her we us our you your i me my this that these those there here
have has had having do does did done not no yes but and or so if then than too very really just
also about after before again against all any because both each few for from into of on off over
under to up down out with without at by as in what which who whom when where why how
say says said saying talk talks talking know knows knew think thinks like likes want wants
now later still already only ever never always some more most much many other another such
""".split())


# 查询里的**指令 / 口水词**。只放两类：中文虚词，和「帮我 / 写一个 / 总结一下」这种
# **任务脚手架**。**不放领域词**——「需求」「功能」「产品」「目标用户」在这个库里是真内容，
# 剔掉它们等于把用户真正想查的东西也剔了（第 747 轮定这条边界时先量后定）。
_CN_FILLER = frozenset("""
的 了 在 是 和 与 及 或 把 被 对 到 从 这 那 就 也 都 还 又 很 不 没 有 个 着 过 为 以 及
我 你 他 她 它 我们 你们 他们 咱们 自己 什么 怎么 怎样 如何 为什么 哪些 哪个 多少
帮我 帮忙 请 麻烦 一下 一个 一些 这个 那个 这些 那些 现在 然后 所以 因为 但是 而且
写 写一 写一个 生成 做一 做一个 整理 梳理 总结 概括 归纳 列出 给出 给我 看看 说说
一下子 一点 可以 能否 是否 需要注意
""".split())


_FILLER_CHARS = frozenset("".join(_CN_FILLER))


def _is_cn_filler(t: str) -> bool:
    """`t` 是不是纯指令 / 口水词。

    CJK 查询会被切成**重叠的 n-gram**（「帮我总结一下」→ 帮我总 / 我总结 / 总结一 /
    结一下 …），而这些片段**跨在两个口水词之间**，整词比对抓不住
    （第 747 轮第一版就是这么漏的：剔完还剩 6 个片段，分数照样 20）。
    改成**按字符**判：整个片段的字全来自口水词表才算口水。
    「需求文」不会被误伤——需 / 求 / 文 都不在那张表的字里。
    """
    if t in _CN_FILLER:
        return True
    return bool(t) and all("\u4e00" <= c <= "\u9fff" and c in _FILLER_CHARS for c in t)


# 字符数：比这短才当成「用户主动搜的词」，剔光了退回原样。
# 主动搜的词一般就 2–4 个字（众筹 / 订金 / DVT）；「帮我总结一下」是 6 个字的**句子**，
# 第一版门槛设成 8，它正好落进兜底里，剔了等于没剔（第 747 轮量出来的）。
_SHORT_QUERY = 4


def _is_speaker_word(t: str) -> bool:
    """「speaker a」「说话人 2」走 who.is_speaker_tag（跟前端 kbNoise.SPEAKER_TAG 同一条正则），光秃秃的「speaker」也算。"""
    return t in ("speaker", "说话人", "发言人") or is_speaker_tag(t)


_NUM = re.compile(r"\d+月\d+|\d+(?:\.\d+)?[台套个件人次轮版元万亿%]|\d{3,}(?:\.\d+)?")


def _number_terms(query: str) -> list[str]:
    """数字也是查询词。英文候选词只认字母、中文候选词只认汉字，「4月16日的 EVT 准备 4 台
    主机和 15 套 PCBA」里最有区分度的 4月16 一分都不算，结果排在前面的全是提到 PCBA
    的别的会（第 191 轮真库实测）。光秃秃的一两位数太常见（「15」把「5 月 15 号」「15 分」
    全拉进来）：只认「月+日」、带量词的（15套）、三位以上的（380mAh 里的 380）。比对时两边都去掉空白（事实原文写成「4 月 16 号」）。"""
    return _NUM.findall(_WS.sub("", query))


_WS = re.compile(r"\s+")


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
            elif len(t) >= 6 and t in squeezed:
                # 够长的词去掉空格再比一次：「memocat」要能命中写成「memo cat」的事实（第 293 轮）；
                # 六个字母以下不这么比，免得 md / api 这种撞回来
                out.append(t)
        elif t in squeezed:
            out.append(t)
    return out


def _clusters(hits: list[str]) -> list[str]:
    """命中的词里**互不包含**的那些：「华为」「华为的」是同一个词，「ui」「uiux」也是。
    P4 #6：查询退化到一个泛词（`记录`）时，5 条候选各自只靠这一个词得分——
    「至少命中 2 个不同内容词」要按这个数，不按 n-gram 片段数。"""
    hs = sorted(set(hits), key=lambda h: (-len(h), h))
    out: list[str] = []
    for h in hs:
        if not any(h in o for o in out):
            out.append(h)
    return out


# 自动召回（拿一段正文当查询）跟用户主动搜一个词不是一回事：查询 ≥ 这么多字就按「长查询」对待——
# 每条候选至少命中 2 个不同的内容词、且不能全靠 ≤2 字的碎片，不够就宁可空着（P4 #6：N5 末段只剩
# `记录` 一个词，凑出 Vlog / 日志 5 条不相干的；N3 末段讲学位，5 条全是 `ui`）。
LONG_QUERY = 100
LONG_QUERY_MIN_WORDS = 2


def _strong_enough(hits: list[str]) -> bool:
    cl = _clusters(hits)
    return len(cl) >= LONG_QUERY_MIN_WORDS and any(len(h) >= 3 for h in cl)


def display_terms(terms: list[str], query: str) -> list[str]:
    """给右栏看的查询词：英文词 / 数字原样；中文 n-gram 片段（「小时预」「号上众」「并以」）合成它们在
    查询里连成的整段、再剥掉两端的虚词——用户看到的是「众筹」「学位」这种词，不是切碎的三个字（P4 #6）。
    没有分词器，这是最接近「整词」的做法；合不出 ≥2 字的就不显示。"""
    squeezed = _WS.sub("", (query or "").lower())
    plain: list[str] = []
    spans: list[tuple[int, int]] = []
    for t in terms:
        if not t or (t.isascii() and t[0].isalpha()) or t[0].isdigit():
            if t and t not in plain:
                plain.append(t)
            continue
        start = 0
        while True:
            i = squeezed.find(t, start)
            if i < 0:
                break
            spans.append((i, i + len(t)))
            start = i + 1
    spans.sort()
    merged: list[list[int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out = list(plain)
    for a, b in merged:
        # 片段常常在词中间断掉（「号上众」← 号上众筹）：往后接到这一串汉字的尽头（最多 3 个字、遇虚词停）
        while b < len(squeezed) and b - a < 8 and _IS_CJK(squeezed[b]) and squeezed[b] not in _EDGE_STOP:
            b += 1
        w = squeezed[a:b].strip(_EDGE_STOP)
        # 「众筹」已经在了就不再列「众筹里面会」；反过来「众筹里面会」在了也不列「众筹」
        if len(w) >= 2 and not any((w in o or o in w) for o in out if not o.isascii()):
            out.append(w)
    return out[:8]


def _IS_CJK(ch: str) -> bool:
    return "一" <= ch <= "鿿"


# 显示时从整段词两端剥掉的字：虚词、方位、「号 / 日」这种日期后缀（「3月10号上众筹」切出的「号上众」剥完就是「众筹」）
_EDGE_STOP = "的了在是和与及或把被对到从这那我们你他她它就也都还又很不没有个一着过为以上里并且而但号日上下前后中"


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
        # **一个内容词都没有 = 这段话跟知识库没关系，就该什么都不返回。**
        # 原来这里是 `return rows[:limit]`——把整池原样交回去。
        # 在「查询词不可能为空」的年代那是无害的兜底；第 747 轮给查询加了中文
        # 口水词过滤之后，「帮我总结一下」这种**整句都是指令**的查询会被剔成空，
        # 而这一行照旧把 8 条不相干的事实端上来（用户原话：「我让你写一个需求文档，
        # 你给我搞了一堆没用的记忆」）。
        # 两个调用点都是召回（正文召回 + 行级回退），返回空正是它们要的语义。
        return []
    # 查询里认出的实体（含同一组的其它写法）：事实挂着它就加分——不然「MemoCat」只召回文本里写成
    # MemoCat 的，写成 memo cat 的那一半排不上来（第 293 轮真库实测 7:1）
    group_codes: set[str] = set()
    if hasattr(memory, "_match_vocab") and hasattr(memory, "_index"):
        try:
            from . import entities as entities_mod
            _t, ents, _s = memory._match_vocab(query, getattr(memory, "_index")()[1])
            g = entities_mod.for_store(store, getattr(memory, "_index")()[1])
            group_codes = {m for e in ents for m in g.members(e)}
        except Exception:      # noqa: BLE001 — 假的 memory 没这些，按纯词面
            group_codes = set()
    ENTITY_BONUS = 4
    long_query = len((query or "").strip()) >= LONG_QUERY

    def score(row: dict) -> tuple[int, str]:
        fact = store.facts.get(row.get("id"))
        text = (fact.text if fact else "") or ""
        # 数字命中比同长度的字词更硬（「4月16」几乎就是在指那一天），多给 2 分
        hits = _hits(terms, text)
        # 长查询（自动召回）：只靠一个泛词命中的候选不要——那不是相关，是凑数（P4 #6）
        if long_query and not _strong_enough(hits):
            return (0, row.get("date") or "")
        s = sum(len(t) + (2 if t[0].isdigit() else 0) for t in hits)
        # 同一个词出现不止一次再加一点（每多一次 +1，最多 +2）：查询只剩一个内容词时（「…no ideas now but
        # will have ideas later」剔掉虚词只剩 ideas），几十条都提到 ideas 的事实靠日期断结，
        # 说了两遍的那条反而排不进前五（第 531 轮 seed 7 那条 miss）
        low = text.lower()
        s += sum(min(2, max(0, low.count(t) - 1)) for t in hits)
        if group_codes and fact is not None and group_codes & set(getattr(fact, "entities", ()) or ()):
            s += ENTITY_BONUS
        return (s, row.get("date") or "")

    # 一个查询词都没命中的候选不要：它们只是 grep 通道子串撞进来的（`md` 撞 SMD），
    # 排在后面照样会被当成「相关记忆」显示出来（第 224 轮实拍）
    scored = [(score(r), r) for r in rows if score(r)[0] > 0]
    scored.sort(key=lambda x: x[0], reverse=True)
    # 伪相关反馈（第 533 轮实验）：词面排前两名的事实挂着什么主题，其余候选挂同一主题的 +1 再排一次——
    # 「给一个片段找同主题的别的事实」这条口径靠它；查询片段本身很少能直接认出主题（TOPIC_BONUS 试过零效果）
    if len(scored) > 2:
        lead: set[str] = set()
        for (_s, r) in scored[:2]:
            f = store.facts.get(r.get("id"))
            lead |= set(getattr(f, "topics", ()) or ()) if f is not None else set()
        if lead:
            def bump(item):
                (sc, d), r = item
                f = store.facts.get(r.get("id"))
                return ((sc + (1 if f is not None and lead & set(getattr(f, "topics", ()) or ()) else 0), d), r)
            scored = sorted((bump(x) for x in scored), key=lambda x: x[0], reverse=True)
    return [r for _s, r in scored][:limit]
