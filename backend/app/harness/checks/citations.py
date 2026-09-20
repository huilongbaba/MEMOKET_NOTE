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


# ---------------------------------------------------- 被吃掉中段的编号（P55 #2）
#
# P53 实拍：`3a3a96354546` 第 2 轮写进「…把用户推回了额外步骤。**[terrence-8F6]**」，
# 一路留到终稿；`fact_by_id` 查无此 id。形状是真编号 `terrence-1833-8F6` **被吃掉中段**
# 之后的残骸——而 `1833-8F6` 正是同一次跑批里另一篇（`a941efecd390`）引到的那一条。
#
# **判据侧不是「没查库」，是「压根没看见它」**（P55 #2 量的第一件事）：
#   · `CITE` 要**三段**（`前缀-数字或12位hex-hex`），`terrence-8F6` 只有两段 → `cited_ids` 不收；
#   · `_LOOSE`（`malformed_citations`）要**至少两条短横**（`{2,}`）→ 也不收。
# 于是 `citations_exist` 拿到一个空列表，第一行就 `return None`，`fact_by_id` 根本没被问到。
# P5 / P22 / P24 三批这一格都是 0，P53 是第一次破。
#
# **不放宽 `CITE`**：它跟 `store._CITE` / 前端 `editor/factCite.ts` 是对拍的三处之一，
# 放宽会把这种残骸画成正文里的引用角标——「一个像真的一样的引用比不引用更糟」。
# **也不放宽 `_LOOSE`**：`{2,}` 降成 `{1,}` 会把 `[Fig-1]` `[TODO-2]` 这种正常方括号一起收进来。
#
# 这里单开一条**窄得多**的：只认「长得像这篇笔记**自己那套编号**」的方括号——
# 前缀（第一段）必须是这轮材料里 / 正文里某个**合法** id 用过的前缀（实拍即 `terrence`）。
# 没有那个命名空间就一个都不报，所以 `[Fig-1]` / `[TODO-2]` / `[see-A]` 天然不在射程里。
_ID_LIKE = _re.compile(r"(?<!\[)\[([A-Za-z][A-Za-z0-9_]*(?:-[0-9A-Za-z]+)+)\](?!\()")


def id_prefixes(ids) -> set[str]:
    """一批合法 id 的前缀（第一段）。`terrence-1833-8F6` → `terrence`。"""
    return {str(i).split("-")[0] for i in ids if str(i).split("-")[0]}


def truncated_citations(text: str, facts: list[str], exists) -> list[str]:
    """正文里长得像**这篇笔记自己那套编号**、但既不是合法 id 也查不到的方括号。

    ``exists(id) -> bool`` 同 `dangling_citations`（生产是 `UserMemory.fact_by_id`）——
    这个模块保持纯函数、不碰 I/O。查得到就不报：编号的段数不是我们发的唯一形状，
    **能查到就是真的**，形状好不好看不归这条管。
    """
    valid = cited_ids(text)
    ns = id_prefixes(valid) | id_prefixes(supplied_ids(facts))
    if not ns:
        return []                                  # 这篇笔记没有自己的编号命名空间：一个都不报
    good = set(valid)
    out: dict[str, None] = {}
    for m in _ID_LIKE.finditer(text or ""):
        fid = m.group(1)
        if fid in good or fid.split("-")[0] not in ns:
            continue
        if exists(fid):
            continue
        out.setdefault(fid, None)
    return list(out)


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


# ------------------------------------- 这一句用的是哪条材料（P24 #2）---
#
# P22 #4：`citations_present` 在 `e78306` 响了 3 轮、`a941` 响了 3 轮，模型一轮都没照做；
# 最终正文里的编号**全部**是修订那一步带进来的。建议是「把这一句该配哪个编号直接算出来」。
#
# **先量了再说**（`p24/m2_locate.py`，P22 五跑每一轮流出的正文，共 89 句 ≥15 字的句子）：
#   已经带编号的 11 句；剩下 78 句里——
#   **唯一能逐字定位到一条材料的 1 句（1%）**、能定位但落在 ≥2 条材料上的 5 句（6%）、
#   **一条都定不到的 72 句（92%）**。
# 92% 定不到，不是因为定位写得松，是因为续写这一步写的**本来就是模型自己的组织语言**
# （「午餐会上需要把这条数据流拆成可确认的责任链」这种），材料里没有对应的逐字来源。
#
# 所以**不自动贴**：唯一能贴的只有 1/78，而贴错的代价是这个仓库自己写过的那句
# ——「一个像真的一样的引用比不引用更糟」（`citations_exist` 的原话）。
# 定位结果改成**写进判据的措辞里**：能定位的逐句点名 + 该贴的编号；
# 一句都定不到时就把这件事直说，并且换一条做得到的要求（见 `grounding.citations_present`）。

_ANCHOR = _re.compile(
    r"\d+\s*[年月日号点分]"
    r"|\d+(?:\.\d+)?\s*(?:%|％|台|套|个|人|天|周|小时|分钟|秒|元|万|亿|kw|kwh|gb|tb|pb)",
    _re.I)
_SENT = _re.compile(r"[^。！？!?\n]+")
_CJK_RUN = _re.compile(r"[一-鿿]+")
_EN_WORD = _re.compile(r"[A-Za-z][A-Za-z'-]*")
# 逐字定位要多硬：共享一个数字锚（日期 / 带单位的量），或者一段 ≥6 字的连续汉字一模一样。
MIN_VERBATIM_CJK = 6
# **英文那一侧**（P30 #1）。加它之前这里只认汉字（`_CJK_RUN` + `_ANCHOR` 里的中文量词），
# 于是**整篇英文的笔记上这个定位器结构性地永远返回空**——`citations_present` 连响到卡死，
# 每一轮都在说「这一轮写的 N 字里没有一句能在材料里找到逐字的出处」，而那句话在英文篇上
# 是**无条件成立**的、不是量出来的（§21：一个可能为空的量程，就不是量程）。
# P28 留的问题「`a941efecd390` 那篇催不动到底是什么形状」，答案的一半就在这儿。
#
# **门槛是量出来的，不是拍的**（`p30/m1b.py` / `m1c.py`，四批 20 跑终稿 623 句）：
#   · 4 个连续相同的词：全库只多出 **1 句**，而那一句是真的
#     （`Speaker B uses OneNote for personal notes…` ↔ `[terrence-380-40F1] Speaker B uses
#     OneNote for a lot of like notes…`），**而且模型已经把那个编号贴上去了**；
#     另外 4 篇中文笔记上一句都没多出来（0/547，加它不动任何既有结论）。
#   · 3 个：多出 7 句，**7 句全是 `speaker a says` / `speaker b says`** 这种转写模板的虚词串，
#     而且一句同时命中 3 条材料（`0F3` / `0F4` / `0F5`）——按唯一性规则本来就不该说。
MIN_VERBATIM_EN = 4


def _flat(text: str) -> str:
    return _re.sub(r"\s+", "", text or "")


def _anchors(text: str) -> set[str]:
    return {_flat(x).lower() for x in _ANCHOR.findall(text or "")}


def _shares_verbatim(sentence: str, fact: str, n: int = MIN_VERBATIM_CJK) -> bool:
    flat_fact = _flat(fact)
    for run in _CJK_RUN.findall(_flat(sentence)):
        for i in range(len(run) - n + 1):
            if run[i:i + n] in flat_fact:
                return True
    return _shares_verbatim_en(sentence, fact)


def _word_runs(text: str, n: int) -> set[str]:
    w = [x.lower() for x in _EN_WORD.findall(text or "")]
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def _shares_verbatim_en(sentence: str, fact: str, n: int = MIN_VERBATIM_EN) -> bool:
    """英文那一侧：≥`n` 个**连续相同**的词。门槛的依据见 `MIN_VERBATIM_EN`。"""
    runs = _word_runs(sentence, n)
    return bool(runs and (runs & _word_runs(fact, n)))


MIN_SENTENCE_CHARS = 15


def _indexed(facts: list[str]) -> list[tuple[str, str]]:
    """材料里 `[id] 正文…` 那些 → [(id, 正文)]。没带 id 的材料定位不到任何东西，丢掉。"""
    out: list[tuple[str, str]] = []
    for f in facts or []:
        m = _HEAD_ID.match((f or "").strip())
        if m:
            out.append((m.group(1), (f or "").strip()[m.end():]))
    return out


def _sentences(text: str) -> list[str]:
    """按句切，只留够长的那些。

    `locate_sources` 和 `citation_coverage` **共用这一个**——两者的分子和分母
    必须落在同一批句子上，各切各的就没法说「定位到的这些里贴了几个」
    （§21：一句诊断只许有一个载体）。
    """
    return [s.strip() for s in _SENT.findall(text or "")
            if len(_flat(s.strip())) >= MIN_SENTENCE_CHARS]


def _hits(sent: str, indexed: list[tuple[str, str]]) -> set[str]:
    """这一句能逐字定位到哪几条材料。"""
    sa = _anchors(sent)
    return {fid for fid, body in indexed
            if (sa & _anchors(body)) or _shares_verbatim(sent, body)}


def locate_sources(text: str, facts: list[str]) -> list[tuple[str, str]]:
    """这段文字里，哪几句能**逐字**定位到唯一一条材料。回 [(句子, 事实 id), …]。

    只回「唯一」的那些：命中两条以上说明贴哪个都可能错，宁可不说。
    已经带了编号的句子跳过。纯函数，零模型。
    """
    indexed = _indexed(facts)
    if not indexed:
        return []
    out: list[tuple[str, str]] = []
    for sent in _sentences(text):
        if has_citation(sent):
            continue
        hits = _hits(sent, indexed)
        if len(hits) == 1:
            out.append((sent, hits.pop()))
    return out


# ------------------------------- 引用覆盖率：换掉「引用处数」那一格（P30 #1）---
#
# **旧指标坏在哪**（P28 #4 量的）：「这次跑写进终稿的引用处数」四批是 17 / 16 / 10 / 8，
# 摆动很大，而它的方差**主要由「这一跑抽到哪几篇」决定**——四批 51 处新引用里
# `da080ca847cf` 一篇占 27 处（53%），`a941efecd390` 四批合计 **1 处**。
# 更糟的是它把三条不同的路混成一个数：模型自己敲的、修订带进去的、判据 fix 带进去的
# （P24 那批流式里只有 9 个新 id，终稿却有 16 处，7 处是后两者）。
# 拿它读「判据松没松」正好读反：`citations_present` 响得最凶的恰恰是引用最少的那两篇
# （`a941` + `e78306` 占 42 轮命中里的 31 轮），**判据在催，模型答的是「催不动」**。
#
# **换成一个有分母的**：`marked / located` ——「**能**逐字定位到材料的句子里，
# 真贴了编号的占多少」。分母是「这段字里有多少句本来就该贴」，它随抽到哪几篇变，
# 分子跟着同一个分母走，比值才可比。**分母为 0 时 `ratio` 是 `None` 不是 `0.0`**：
# 「没有一句该贴」和「该贴的一句都没贴」是两件事，混成同一个 0 就又是一次
# 「一个可能为空的量程不是量程」（§21 批 27 那条）。
#
# 定位的判法逐字沿用 `locate_sources`（共享数字锚 / ≥6 字连续汉字），只差一处：
# **这里不跳过已经带编号的句子**——那些正是分子。


@dataclass(frozen=True)
class CiteCoverage:
    """一段正文的引用覆盖。四个数一起给，因为单给比例读不出它站在多大的分母上。"""

    sentences: int          # 够长、算得上一句的总数
    located: int            # 其中能逐字定位到 ≥1 条材料的（**分母**）
    marked: int             # `located` 里带了出处的（`[编号]` 或 `[标题](note://id)`）
    matched: int            # `marked` 里贴的编号**正好是**定位到的那条之一

    @property
    def ratio(self) -> float | None:
        """`marked / located`。**分母 0 时是 `None`**，不是 0.0（见上面那段）。"""
        if not self.located:
            return None
        return round(self.marked / self.located, 3)


def citation_coverage(text: str, facts: list[str]) -> CiteCoverage:
    """有逐字出处的句子里，贴了编号的比例。纯函数、零模型。

    `matched` 单独数一份是因为「贴了编号」和「贴对了编号」不是一件事：
    修订那一步搬进来的编号常常落在**隔壁那句**上，只数 `marked` 会把它算成好。
    它是诊断用的第二个数，不参与 `ratio`——`ratio` 答的是 P28 留的那个问题
    （判据催得动催不动），把「贴对没贴对」混进去答的就是另一个问题了。
    """
    indexed = _indexed(facts)
    sents = _sentences(text)
    if not indexed:
        return CiteCoverage(len(sents), 0, 0, 0)
    located = marked = matched = 0
    for sent in sents:
        hits = _hits(sent, indexed)
        if not hits:
            continue
        located += 1
        cited = set(cited_ids(sent))
        if cited or note_link_ids(sent):
            marked += 1
            if cited & hits:
                matched += 1
    return CiteCoverage(len(sents), located, marked, matched)
