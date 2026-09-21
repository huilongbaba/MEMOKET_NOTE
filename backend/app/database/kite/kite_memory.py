"""KITE 长期记忆封装。

分两条路径，这是整个后端最关键的设计决策：

**入库（慢，异步）** —— 走 KITE 原生 ``Memory.remember()``，用 LLM 把对话/文档
抽成结构化 fact。实测本地 30B 上约 13s/session，放后台跑，不挡交互。

**检索（快，同步）** —— 绕开 KITE 的 ``recall()``。原生 recall 会用 LLM 把问题
编译成查询计划（compile_plan.py），实测要 3 次 LLM 调用、38-190 秒，而其中本地
符号检索本身只花 0.0s。所以这里自己做：把查询里的表层词用 ``Vocab`` 确定性地
解析成符号码，手工拼出 plan dict，交给 ``execute_plan()`` 执行 —— 零 LLM 调用，
亚毫秒返回。
"""

from __future__ import annotations

import copy
import functools
import os
from contextlib import contextmanager
from types import SimpleNamespace
import re

from ..kb.who import norm_who
import shutil
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

# 下面两个 import 伸进了 memoket_kite 的私有名（前面带下划线的那两个）。
# 这是有意的、也是有代价的：
#   * ``_consolidation_round_votes`` 是投票解析，重写一份就等于让两边的
#     解析规则各自漂移，比借用更糟；
#   * ``_verify_loadable`` 是写回前的可读性校验，没有公开等价物。
# 代价是 memoket-kite 在 requirements 里是 ``git+…`` 不带 ref 的，跟着上游
# HEAD 走：上游把这两个名字一改，这里是**import 期**炸，整个 app 起不来。
# 所以 tests/test_kite_private_api.py 盯着这两个名字——把「某天服务起不来」
# 提前成一条说得清哪个名字没了的红测试。降级没有意义：这两件事做不了，
# 整合本身就做不了。
from memoket_kite import Memory
from memoket_kite.core.algebra import CONF_ORDER, Store, execute_plan
from memoket_kite.core.vocab import Topic, norm_code
from memoket_kite.pipeline.extract import _consolidation_round_votes
from memoket_kite.providers.llm import llm_json
from memoket_kite.storage import _verify_loadable

from .. import store
from . import kite_entity_candidates, kite_extract_profile, kite_tokens
from ..kb import search
from ..kb.who import is_speaker_tag
from ...util.config import get_settings
from .kite_writer import write_lock

kite_extract_profile.install()
kite_entity_candidates.install()
# 词元共用同一批字符串对象：真库实测峰值 RSS 308 → 242MB（省 21%），
# 检索结果一个字都不变。装不上就当没有（见 kite_tokens 的模块注释）。
kite_tokens.install()

# Root topics seeded into every new codebook. KITE's extraction prompt only
# lets the model propose a topic as a child of an already-known root
# (prompts/extract.py: "propose one specific child under a known root"), and
# core/vocab.py's propose_topic() rejects any proposal whose parent doesn't
# already resolve ("orphan proposals are rejected"). A brand-new vocab has no
# roots at all, so topics can never bootstrap themselves from zero — this
# fixes that from the very first ingest.
#
# Aliases are extra surface forms recall()/ask() can match against non-English
# input; the app already treats English + Chinese as first-class elsewhere
# (see STOPWORDS / _cjk_terms below), so both are seeded here too.
ROOT_TOPICS: dict[str, tuple[str, ...]] = {
    "work": ("工作",),
    "project": ("项目",),
    "personal": ("个人",),
    "learning": ("学习",),
    "health": ("健康",),
    "finance": ("财务", "理财"),
}


def _root_topics_xml() -> str:
    parts = []
    for code, aliases in ROOT_TOPICS.items():
        alias_xml = "".join(f"<alias>{a}</alias>" for a in aliases)
        parts.append(f'    <topic code="{code}" status="canonical" parents="" born="">{alias_xml}</topic>')
    return "\n".join(parts)


EMPTY_CODEBOOK = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<codebook id="{uid}" speakers="user">\n'
    "  <vocab>\n"
    f"{_root_topics_xml()}\n"
    "  </vocab>\n"
    "  <timeline/>\n"
    "</codebook>\n"
)

# 检索时忽略的高频词，避免把 grep 拉成全表扫描
STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are",
    "was", "were", "be", "what", "which", "who", "when", "where", "how", "why",
    "i", "my", "me", "we", "our", "you", "your", "it", "this", "that", "with",
    "about", "did", "do", "does", "有", "的", "了", "是", "在", "我", "你", "他",
    "什么", "怎么", "哪些", "这个", "那个",
}


def _export_provider_env() -> None:
    """KITE 的 provider 只认 os.environ，把配置桥接过去。

    它读 OPENAI_API_KEY / OPENAI_BASE_URL 两个变量（见 providers/llm.py），
    不走参数传递 —— 所以调用前必须先设好，否则报 "OPENAI_API_KEY is required"。

    从 store.get_active_llm_config() 取，不直接读 Settings——用户在设置页
    切了 GPT，KITE 这边（抽取/问答/实体去重）也要跟着切，不能只有
    llm.py 那条写作路径切了、KITE 这边还锁死在本地模型。"""
    cfg = store.get_active_llm_config()
    os.environ["OPENAI_API_KEY"] = cfg["api_key"]
    os.environ["OPENAI_BASE_URL"] = cfg["base_url"]


class ProviderFailed(RuntimeError):
    """KITE 内部有模型调用失败、且最终没拿到任何依据——答案是回退出来的，不能当「没记录」给用户。"""


@contextmanager
def _watch_provider():
    """给 `memoket_kite.providers.llm._http_llm` 装观察器（它在 `llm()` 里按模块全局名查，运行时可换）：
    记下第一次失败的那句；之后的调用直接抛（不再打模型），退避的 `time.sleep` 也跳过——
    模型 500 时 30 秒变 1 秒。用完原样装回去。"""
    from memoket_kite.providers import llm as kite_llm
    failures: list[str] = []
    real_http = kite_llm._http_llm
    real_time = kite_llm.time          # 那个模块只用 time.sleep；换成一个壳，别去改全局 time.sleep
    real_sleep = real_time.sleep

    def http(*a, **kw):
        if failures:
            raise RuntimeError(failures[0])
        try:
            return real_http(*a, **kw)
        except Exception as exc:      # noqa: BLE001 — 什么错都记，翻译交给路由
            failures.append(_describe(exc))
            raise

    def sleep(sec):
        if not failures:
            real_sleep(sec)

    kite_llm._http_llm = http
    kite_llm.time = SimpleNamespace(sleep=sleep)
    try:
        yield failures
    finally:
        kite_llm._http_llm = real_http
        kite_llm.time = real_time


def _describe(exc: BaseException) -> str:
    """urllib 的错翻成一句：HTTP 状态码 / 连不上 / 超时。"""
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return f"模型服务返回 {code}"
    reason = getattr(exc, "reason", None)
    if reason is not None:
        return f"模型连不上（{reason}）"
    return f"模型调用失败（{type(exc).__name__}: {exc})"


_CJK_RE = re.compile(r"[一-鿿]")


def _is_cjk_pair(a: str, b: str) -> bool:
    return bool(_CJK_RE.search(a) or _CJK_RE.search(b))


# TRACELOG [15] 续：一开始用 KITE 自带的 ENTITY_CONSOLIDATION_PROMPT（问
# "这两个是不是同一个真实世界的实体，参考给的例句"）——实测证明这个问法
# 从根上就问错了：真实数据里的重复实体，中文那批是 ASR 把同一个读音识别
# 成了不同的字（同音字混淆），英文那批更多是打字/拼写变体（漏字母、
# 单复数、缩写）——这是两种不同的产生机制，"语义上下文能不能证明"这个
# 问法对哪种都不对口：中文候选的"上下文"其实是抽取阶段基于错误转写独立
# 生成的，本身就是错误的下游产物，拿它反过来当"这两个不是同一个实体"的
# 证据是循环论证；英文候选的拼写变体压根不需要看语义，看拼写本身就够了。
# 换成针对性的两条问法之后，真实数据上从"该判重复的一个都没判出来"变成
# "该判重复的基本都判对了，该拒绝的也都正确拒绝了"（见 TRACELOG）。
_PHONETIC_MERGE_PROMPT = """For each pair of short Chinese text codes below
(extracted as named entities from noisy speech-to-text transcripts), judge
ONLY by how they would SOUND if spoken aloud in Mandarin — could a speech
recognizer plausibly have transcribed the same spoken word as these two
different strings, due to identical or very close pronunciation (同音字/
近音字)? This is purely about pronunciation, not meaning or spelling —
ignore what each string might refer to.

PAIRS:
{pairs}

Return JSON only:
{{"decisions": [{{"i": 0, "merge": true, "winner": str}}]}}"""

_SPELLING_VARIANT_MERGE_PROMPT = """For each pair of short text codes below
(extracted as named entities from hastily typed or transcribed notes), judge
whether they are plausibly the SAME underlying word/name, differing only
because of a typo, a missing/extra letter, a singular/plural form, an
abbreviation, or a near-miss spelling variant — the kind of accidental
duplication that happens when the same entity gets written slightly
differently on different occasions. Do NOT merge pairs that are simply two
different real words/names that happen to be similar length or share some
letters (e.g. "mba" and "nba" are two different real acronyms, not a typo
of each other).

PAIRS:
{pairs}

Return JSON only:
{{"decisions": [{{"i": 0, "merge": true, "winner": str}}]}}"""


def _vote_entity_merges(vocabulary, candidates: list[tuple[str, str]], model: str,
                        batch_size: int = 60) -> dict[str, str]:
    """实体去重投票——每批独立投 3 轮，2/3 一致才真的合并（复用 KITE 自带
    的投票解析函数 ``_consolidation_round_votes``），候选列表由调用方
    传入而不是内部写死（库自带版本内部固定 ``min_len=2``，实测在真实
    数据上这个阈值把大量像"ac"/"af"这种 2 字符噪声碎片互相撞出的候选也
    算了进去，见 TRACELOG）。

    候选按是否含 CJK 字符分成两组，分别用不同的问法投票——中文问"读音
    像不像"，英文/其他问"是不是同一个词的拼写变体"，理由见上面两个
    prompt 前的注释。``merged_codes`` 的"同一轮内不链式合并"这条防护
    是跨两组共享的，不是每组各自独立——两组候选理论上可能共享某个 code
    （虽然实践中因为分组本身按脚本类型分开，交叉概率很低，但共享防护
    集合成本几乎为零，没有理由不做）。

    直接 mutate 传入的 vocabulary（调用方决定传真身还是深拷贝——预览用
    深拷贝，真正执行时传真身）。返回 {loser_code: winner_code}。
    """
    cjk_candidates = [(a, b) for a, b in candidates if _is_cjk_pair(a, b)]
    latin_candidates = [(a, b) for a, b in candidates if not _is_cjk_pair(a, b)]

    entity_rewrites: dict[str, str] = {}
    merged_codes: set[str] = set()
    for candidate_group, prompt_template in (
        (cjk_candidates, _PHONETIC_MERGE_PROMPT),
        (latin_candidates, _SPELLING_VARIANT_MERGE_PROMPT),
    ):
        for start in range(0, len(candidate_group), batch_size):
            batch = candidate_group[start:start + batch_size]
            votes: dict[int, list] = {i: [] for i in range(len(batch))}
            prompt = prompt_template.format(
                pairs="\n".join(f"{i}: {a!r} | {b!r}" for i, (a, b) in enumerate(batch)))
            for _ in range(3):
                try:
                    data = llm_json(prompt, model=model)
                    round_votes = _consolidation_round_votes(data, batch)
                    for i in votes:
                        votes[i].append(round_votes.get(i))
                except RuntimeError:
                    continue
            for i, (first_code, second_code) in enumerate(batch):
                winners = [w for w in votes[i] if w]
                if len(winners) >= 2 and len(set(winners)) == 1:
                    winner = winners[0]
                    loser = second_code if winner == first_code else first_code
                    if loser in merged_codes or winner in merged_codes:
                        continue
                    if loser in vocabulary.entities and winner in vocabulary.entities:
                        entity_rewrites.update(vocabulary.merge_entities([loser], winner))
                        merged_codes.add(loser)
                        merged_codes.add(winner)
    return entity_rewrites


def _fact_seq(fact_id: str) -> int:
    """`…-0F12` → 12：同一个 session 里按抽取顺序排。"""
    m = re.search(r"F(\d+)$", fact_id)
    return int(m.group(1)) if m else 0


def _surface_in(sl: str, lowered: str) -> bool:
    """词表里的表层词是否出现在查询里。中文没有空格只能子串匹配；拉丁字母的表层词要
    按整词匹配——「ev」「pc」「pcb」这些两三个字母的实体码之前靠子串命中「EVT」「PCBA」，
    把电动车 / 电脑的事实拉进候选池，回给用户看的「搜了什么」也跟着多出三个半截词
    （第 192 轮真库实测）。"""
    # **先做子串预检，再做整词正则**（P11 #3）。整词正则的字面量必须是查询的子串，所以
    # `sl not in lowered` 时答案已经是 False——而词表里几千个 ASCII 表层词里 99% 都不在这一段里。
    # 之前每个表层词都走 `re.search(动态拼的 pattern)`：`re` 的编译缓存只有 512 条，几千个
    # 不同 pattern 轮着来，**每一次都重新编译**。实测 `relations/batch` 一段 ~90 ms 里 2/3 是
    # 这里的正则编译（80 段 27.5 万次 compile）。预检之后编译的是真出现过的那几十个，再按
    # 表层词缓存住。判定语义一个字没变（`test_surface_in_预检不改判定`）。
    if sl.isascii():
        if sl not in lowered:
            return False
        return _word_pattern(sl).search(lowered) is not None
    return sl in lowered


@functools.lru_cache(maxsize=4096)
def _word_pattern(sl: str) -> "re.Pattern[str]":
    return re.compile(r"(?<![a-z0-9])" + re.escape(sl) + r"(?![a-z0-9])")


# ------------------------------------------------------------ 调用侧的词法预筛（P15 #4）
#
# 首次打开一篇 30k 字的笔记，页边圆点要把 143 段各自 recall 一遍；P11 把 12.8 s 压到 3.9 s 之后，
# 剩下的 70% 在 `memoket_kite.core.algebra.execute` 的 grep：每段 2–3 条 `{"grep": 词}` 子查询，
# 每条都拿正则把 2 万条事实扫一遍（80 段 174 次全表 grep = 1.2 s）。**量出来的形状**（143 段、
# 322 条 grep 子查询、249 个不同的词）：**162 个词在库里一个 unit 都不命中**（全表扫一遍换回一个空集），
# 54 个只落在 1–8 个 unit 里，真需要全表扫的只有 33 个。
#
# kite 不改（用户定死用 kite）。改的是**问法**：先在调用侧按字符 2-gram 倒排表算出「这个词落在哪几个
# unit」，再把 `units` 作为过滤条件一起交给 kite——kite 自己的 plan 语法就有 `where.units`（多跳绑定
# 用的），`_match_facts` 先按 unit 取候选、再在候选里 grep。语义一字不变：
#   · 落在 ≤ 8 个 unit（kite 的 `units` 上限）→ `{"grep": 词, "units": [那几个]}`：命中的事实全在这几个
#     unit 里，候选集跟全表 grep 一模一样；`_score` 不看 units；cand 非空不触发 relax；
#   · 一个都不落 → `{"grep": 词, "units": ["<没有这个 unit>"]}`：候选集空，kite 走 relax 也放不出东西
#     （units 永不 relax、别的 relax 步骤对它都是 no-op）——跟原来「全表 grep 之后空集 → relax 掉 grep →
#     没内容约束 → 停」同一个结果，只是不再扫那 2 万条。**不能直接删掉这条子查询**：kite 的 `parse_plan`
#     只取前 3 条，删一条会让第 4 条顶上来，那就是换了查询；
#   · > 8 个 unit 或词是复杂正则 → 原样交给 kite 全表扫。
# 行级回退（`_recall_via_lines`）同一套：每个词单独一次 `select lines`，零命中的词那一次本来就是空，跳过；
# ≤ 8 个 unit 的加 `units` 过滤（lines 的 `units` 就是纯过滤）。
# 倒排表按索引 mtime 缓存在 `_cache` 里（跟 `fact_attrs` 同一个位置、同一套闲置回收）。
# 判定对拍：同一篇 143 段 112 个点的 marks digest 修前修后 `bc385fd1fd9e445d` 一字不差（台账 P15 #4）。

# grep 词只认这种形状的：字母 / 数字 / 下划线 / 短横 / 撇号 / 汉字，没有正则元字符。别的（kite 自己拼的
# 多分支 `a|b`、带括号的）不预筛，原样全表扫。
_PLAIN_GREP = re.compile(r"^[\w'\-一-鿿]{2,}$")
# 纯 ASCII 的词（`ai` / `app` / `pr`）——`unit_df` 只给这一类补词边界，中文没有词边界
_ASCII_TERM = re.compile(r"^[0-9A-Za-z'\-]+$")
_MISSING = object()
# kite 的 `parse_plan` 最多收 8 个 unit id；多于这个数没法表达成过滤条件，只能全表扫
_UNITS_CAP = 8
# 「库里长出来的词」至少要出现在几条记录（unit）里才算数（P34 #1，`UserMemory.segment`）。
# 5 是量出来的：真库上 `众筹` 47 / `算力` 9 / `灵衢` 6 都过得去，而门槛调到 3
# 会放进 `品方` `户提` 这种跨词的两字串（全库多认 300 多个「词」，逐条读下来几乎全是撞的）。
WORD_DF_MIN = 5


def _corpus_word(idx):
    """「这个串在这个人的库里算不算一个词」——`kb/tokenize.Tokenizer(attest=…)` 那一档（P34 #1）。

    底表是通用汉语词，`众筹`（真库 df=107）/ `算力` / `灵衢` 它一个都没有；实体表也不一定收
    （`众筹` 在真库里就不是实体）。所以再开一条**按需**问库的路：切词时碰到底表不认识的
    2–3 字串，就问一句「它出现在几条记录的 unit 里」（走 `search.plan` 已经在用的那份
    2-gram 倒排表，memo 过，零额外 IO）。

    两道窄闸，**宁可不认识**：
    · **串里不许有口水字**——`的一` 在真库里 df=359，次数远远够，可它是跨词切出来的；
      按次数收词就一定会收到这种。这一条不看次数，先把它们整类挡掉。
    · **至少 `WORD_DF_MIN` 条记录里出现过**——`品方` 1 条、`户提` 2 条，那是撞出来的。
    """
    from ..kb.search import _FILLER_CHARS

    def is_word(w: str) -> bool:
        if any(c in _FILLER_CHARS for c in w):
            return False
        n = idx.unit_df(w, floor=WORD_DF_MIN)
        return n is not None and n >= WORD_DF_MIN

    return is_word
# 「一个 unit 都不命中」时给 kite 的占位 unit：库里永远没有这个 id，候选集就是空集
_NO_UNIT = "__memoket_no_unit__"


class _GrepIndex:
    """按 unit 建的字符 2-gram 倒排表：`units_for(词)` 回「哪几个 unit 里有这个词」。

    候选靠 casefold 后的 2-gram 交集拿，**最后一步拿原文再用 kite 同一个 `re.compile(词, re.I).search`
    核一遍**——所以「这个 unit 里有没有」跟 kite 逐条事实 grep 的判定是同一个谓词（词里没有换行，
    `\\n` 拼接不会跨事实撞出假命中）。2-gram 那一步只可能多给候选、不会少给：casefold 把 ſ / K 这类
    折成 s / k，跟 re.I 的等价类一致。
    """

    __slots__ = ("_blob", "_grams", "_line_blob", "_line_grams", "_memo", "_line_memo", "_df_memo")

    def __init__(self, store) -> None:
        self._blob, self._grams = self._build(
            (f.unit, f.text) for f in getattr(store, "facts", {}).values())
        self._line_blob, self._line_grams = self._build(
            (ln.unit, ln.text) for ln in getattr(store, "lines", {}).values())
        self._memo: dict[str, frozenset | None] = {}
        self._line_memo: dict[str, frozenset | None] = {}
        self._df_memo: dict[str, int | None] = {}

    @property
    def unit_count(self) -> int:
        """有事实的 unit 数——`unit_df` 的分母。"""
        return len(self._blob)

    def unit_df(self, term: str, *, floor: int = 0) -> int | None:
        """这个词出现在几个 unit 里（`kb/relations` 拿它判「一条共用的串算不算证据」）。

        **不能直接用 `units_for`**：那条是给预筛用的，判定是 `re.compile(词, re.I).search`，
        也就是**子串**——`pr` 会在 product / approve 里命中（真库上 692 个 unit，而它真正
        作为一个词只在 33 个里）、`mp` 在 example 里命中（402 vs 4）。拿子串数当「这个词
        有多常见」会把短英文词冤枉成「满库都是」，于是把真沾边的 `kol + pr` 砍掉。
        所以 ASCII 词要在候选 unit 上按**词边界**再核一遍；中文没有词边界，子串就是要的那个数。

        `floor`：调用方只关心「有没有到某个门槛」。子串数是词边界数的**上界**，
        上界都没到门槛就不必再扫一遍——这时回的是那个上界（也 < floor，判定一样）。
        `None` = 这个词预筛不了（形状里有正则元字符），调用方按「不知道」处理。
        """
        hit = self._df_memo.get(term, _MISSING)
        if hit is not _MISSING:
            return hit
        units = self.units_for(term)
        if units is None or len(units) < floor or not _ASCII_TERM.match(term):
            out = None if units is None else len(units)
        else:
            rx = re.compile(rf"(?<![0-9A-Za-z]){re.escape(term)}(?![0-9A-Za-z])", re.I)
            out = sum(1 for u in units if rx.search(self._blob[u]))
        if len(self._df_memo) >= 4096:
            self._df_memo.clear()
        self._df_memo[term] = out
        return out

    @staticmethod
    def _build(pairs) -> tuple[dict[str, str], dict[str, set[str]]]:
        per_unit: dict[str, list[str]] = {}
        for unit, text in pairs:
            if unit and text:
                per_unit.setdefault(unit, []).append(text)
        blob = {u: "\n".join(t) for u, t in per_unit.items()}
        grams: dict[str, set[str]] = {}
        for u, b in blob.items():
            f = b.casefold()
            for g in {f[i:i + 2] for i in range(len(f) - 1)}:
                grams.setdefault(g, set()).add(u)
        return blob, grams

    def units_for(self, term: str, *, lines: bool = False) -> frozenset | None:
        """含这个 grep 词的 unit 集合；None = 这个词预筛不了（交给 kite 全表扫）。"""
        memo = self._line_memo if lines else self._memo
        if term in memo:
            return memo[term]
        out = self._units_uncached(term, lines=lines)
        if len(memo) >= 4096:
            memo.clear()
        memo[term] = out
        return out

    def _units_uncached(self, term: str, *, lines: bool) -> frozenset | None:
        if not _PLAIN_GREP.match(term or ""):
            return None
        blob, grams = (self._line_blob, self._line_grams) if lines else (self._blob, self._grams)
        folded = term.casefold()
        if len(folded) < 2:
            return None
        cand: set[str] | None = None
        for i in range(len(folded) - 1):
            ids = grams.get(folded[i:i + 2])
            if not ids:
                return frozenset()
            cand = set(ids) if cand is None else cand & ids
            if not cand:
                return frozenset()
        try:
            rx = re.compile(term, re.I)
        except re.error:
            return None
        return frozenset(u for u in (cand or ()) if rx.search(blob[u]))


def _narrow_grep_query(q: dict, units: frozenset | None) -> dict:
    """一条 `{"grep": 词}` 子查询按预筛结果改写成带 `units` 的同义查询；预筛不了就原样。"""
    if units is None or len(units) > _UNITS_CAP:
        return q
    where = dict(q.get("where") or {})
    where["units"] = sorted(units) if units else [_NO_UNIT]
    return {**q, "where": where}


def _rotate(per_run: list[list[str]], out: list[str], cap: int) -> list[str]:
    """按片段轮转取样，取满 `cap` 个为止。**P4 立的那个循环，一个字没动**，
    只是搬出来好让 `_cjk_terms` 能对「实词」和「碎片」各转一遍（P65 ①）。

    `out` 是**接着往下填**的那一份（第二遍轮转要认得第一遍已经拿了哪些），
    原地改并返回同一个列表。
    """
    depth = 0
    while len(out) < cap and any(depth < len(g) for g in per_run):
        for grams in per_run:
            if depth < len(grams) and grams[depth] not in out:
                out.append(grams[depth])
                if len(out) >= cap:
                    break
        depth += 1
    return out


class UserMemory:
    """单个用户的 codebook。每人一个 XML 文件。"""

    _cache: dict[str, tuple[float, object, object]] = {}

    def __init__(self, user_id: str):
        self.user_id = re.sub(r"[^A-Za-z0-9_.-]", "_", user_id) or "default"
        s = get_settings()
        self.dir = Path(s.kite_data_dir) / self.user_id
        self.path = self.dir / "codebook.xml"

    # ------------------------------------------------------------ 存储

    def ensure(self) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(EMPTY_CODEBOOK.format(uid=self.user_id),
                                 encoding="utf-8")
        return self.path

    # 每个缓存项最后一次被用的时间：符号索引很占内存（20406 条事实的库 ≈ 200MB，大头是
    # 词元倒排表），桌面版常驻时不该一直抱着——闲置一段时间就放掉，下次用再花 1s 重建。
    _last_used: dict[str, float] = {}
    IDLE_TTL_S = 300

    def _grep_index(self, store) -> "_GrepIndex | None":
        """这份索引对应的 2-gram 倒排表（P15 #4）。按 mtime 缓存在 `_cache["…#grepidx"]`，
        跟 `fact_attrs` 同一个位置——索引换了它跟着重建，闲置回收也一起收。建不出来回 None（不预筛）。"""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return None
        key = f"{self.path}#grepidx"
        hit = self._cache.get(key)
        if hit and hit[0] == mtime and hit[2] is store:
            return hit[1]
        try:
            idx = _GrepIndex(store)
        except Exception:      # noqa: BLE001 —— 预筛只是快路，建不出来就走原来的全表扫
            return None
        self._cache[key] = (mtime, idx, store)
        return idx

    def _topic_face(self, store, idx):
        """这个库的「话题面」（P84）。按 mtime 缓存在 `_cache["…#topicface"]`，
        跟 `#grepidx` 同一个位置和同一条回收规则。

        **只有 `common_term()` 里真的要问「泛词还是主题词」时才建**——它要扫一遍
        `store.facts`，而 2362 unit 的真库上那条分支根本不会走到（见 `common_term`）。
        建不出来回 `None` = 这条判据不插手，**不插手就是原样**（同 `_grep_index`）。
        """
        from ..kb.topic_face import TopicFace

        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return None
        key = f"{self.path}#topicface"
        hit = self._cache.get(key)
        if hit and hit[0] == mtime and hit[2] is store:
            return hit[1]
        try:
            face = TopicFace(store.facts.values(),
                             units_for=(idx.units_for if idx is not None else None))
        except Exception:      # noqa: BLE001 —— 建不出来就是不启用这一档
            return None
        self._cache[key] = (mtime, face, store)
        return face

    def _who_face(self, store, idx):
        """这个库的「主语面」（P88 ①）。跟 `_topic_face` 逐字同一条缓存和回收规则，
        只是轴换成 `FactRecord.who`。

        **只有 `TopicFace` 已经判「不泛」之后才建**——它跟 `_topic_face` 一样要扫一遍
        `store.facts`，而走到这儿的串一个库里只有几十个（`terrence-rewrite` 实测 63 个）。
        建不出来回 `None` = 这条判据不插手，**不插手就是原样**。
        """
        from ..kb.topic_face import WhoFace

        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return None
        key = f"{self.path}#whoface"
        hit = self._cache.get(key)
        if hit and hit[0] == mtime and hit[2] is store:
            return hit[1]
        try:
            face = WhoFace(store.facts.values(),
                           units_for=(idx.units_for if idx is not None else None))
        except Exception:      # noqa: BLE001 —— 建不出来就是不启用这一档
            return None
        self._cache[key] = (mtime, face, store)
        return face

    def common_term(self):
        """回一个「这个词在**这个人的**库里到处都是」的判据，给 `kb/relations.detect(common=…)`。

        判据本身（为什么是文档频率、门槛怎么量的）写在 `kb/relations.COMMON_DF_RATIO`
        那段注释里；这里只负责把这个人的库接上去——`relations` 那个文件不依赖 app 的
        其它模块，拿不到 store，所以由调用方注入。

        零模型、零额外 IO：走的是 `search.plan` 已经在用的那份 2-gram 倒排表。
        建不出索引（或库是空的）就回 `None` = 不启用这条判据，**不启用就是原样**。

        ## P84：小库那一档再问一句「泛词还是主题词」

        P81 / P82 量清楚的根因：**单主题小库里主题词的 df 天然就高，df 高 ≠ 它不是证据**。
        P82 试过「按库大小把整条判据关掉」——变好 16 / 变差 23，**退回**，因为
        `common` 在那种库上还兼着口水词兜底（`因此` df 23.3%，`_is_cn_filler` 里一个都没有）。

        **这一批不关它，只在它已经判 True 之后加问一句**
        （`kb/topic_face.TopicFace.generic`，轴是 `FactRecord.topics` 的话题面，不是 df）：

        * **只在 `total * RATIO < MIN` 那一档问**（< 333 unit）。大库上 6% 自己就是有效门槛，
          这条判据一个字都不插手——`terrence`（2362 unit）逐格不动，**四栏对这一刀是瞎的**
          （P82 那一课），唯一看得见它的是 `recall_ruler --by-lib` 的小库那一行。
        * **只对汉字串问**。泛尺在英文那一半没有留出集（P77 ③ / P79 ④ 两批的账），
          而 P84 实测这一格是真的会出事——理由和两组数写在 `kb/topic_face` 文件头第 ① 格。
        * **只有明确判「不泛」才捞回来**。`None`（判不了）当 `False` 用不得。

        全库对拍（765 条，`recall_ruler --cf-spread`）：**变了 28 条，全部落在
        `terrence-rewrite`（193 unit）**；28 条逐条读完 **变好 14 / 变差 7 / 中性 7**
        （标注 `p84-spread-28`）。

        ## P88 ①：捞回来那一问**再串一条轴**（`WhoFace`）

        P86 判「那条轴分不开『指着一个具体东西的窄』和『整个库都在讲这件事的窄』」，
        并留下「缺的那一块叫**这个库是关于谁的**，库里没记这件事」。
        **后半句错了**：库里记了，记在**每条事实的 `who`** 上——
        P86 找的是**库级**那一个主语（`entities` 取最多的，拿了是循环），
        **而分开两种「窄」不需要库级那一个**。理由和五张表在 `kb/topic_face`
        文件头第 ⑥⑦ 格（含这一批新废掉的四条轴 `obj`/`kind`/`event`/`place`
        和两版自动取主语）。

        **这一刀只许做减法**：`WhoFace` 串在 `TopicFace` **后面**，
        `topics` 已经判「不泛」了才问，而且只有它也说「不泛」才真捞回来。
        所以它**只可能少捞回几个串，不可能多捞回**——
        英文那一半（汉字闸）和大库那一档（库大小闸）**逐字不动**。

        全库对拍（765 条，`recall_ruler --cf-whoaxis`）：**变了 2 条，都在
        `terrence-rewrite`，进 2 掉 0，「有→空」0 条**；两条逐条读完
        **变好 1 / 中性 1 / 变差 0**（标注 `p88-whoaxis-2`）：

        * **i=293 变好**：`0 → 1`，回来的正是 P82 / P84 / P86 三批一直丢的那条逐句出处
          （`terrence-1837F16`「她最终因大健康业务裁员而**离开安克**」）。
          链条是 `公司` 的主语面 .900 ≥ 0.85 → 不再被捞回来 → `大公司`/`公司病`/`公司运`
          退出实词档 → `开安克` 回到 `_cjk_terms` 那 16 个名额里 → `span` 回来 →
          `qualifies` 和 `_strong_enough` 两道闸一起放行。
          **这就是 `_cjk_terms` 那段注释里记的「不动那 16 也能治它」的那条路**
          （它跟 `test_p86::第三条` 的 A 刀是同一件事，区别是 A 刀靠手按、这一条是算出来的）。
        * **i=26 中性**：`3 → 4`，屏没满时多进来一条同领域的（`团队希望尽快将…APP
          提供给外部团队测试并收集反馈`），沾边但没正面答题，**没挤掉任何人**。

        ## P90：这三道闸今天各自还挡着什么（**量完了，一个字节没改**）

        ⚠️ **并排写**（更正 P88 ①）：P88 收尾写的是「**i=607（大库上同一张脸）没治好**
        ——这一刀够不着大库」。**那句话两半，一半对一半错**，实测在
        `kb/topic_face` 文件头第 ⑧ 格，这里只留三句：

        * **`i=607` 在 HEAD 上是好的（1 条），没有「治」这回事**。它跟 `i=293`
          确实是同一条链（`_cjk_terms` 那 16 个名额、同样三换三、`span` 断成 `pair`），
          但**方向相反**：`i=293` 是这条轴一开口就治好的，`i=607` 是这条轴一开口就打坏的。
        * **「够不着大库」说反了**。`WhoFace` 在大库上 `usable=False` → `generic()` 回
          `None` → 下面那句 `who.generic(term) is not False` 为 `True` → **判「是 common」**。
          所以主语面在大库上**把话题面那一问整个按住了**：全库实测，
          **拆掉 `ask_face` 那道库大小闸、主语面照问 → 765 条一条都不变**。
        * ⚠️ **但两道闸都得留着**。那个「0 条」是**冗余**不是「有一道没用」：
          把 `SPEAKER_TAG_MAX` 一摘，同一份语料上 **24 条变了、i=607 1 → 0**。
          大库上的安全来自「那个库的 `who` 恰好装的不是主语」这个**偶然**
          （`用户`.460 / `需要`.473 / `产品`.559 / `手机`.534 全都远低于 0.85），
          **不是来自这条轴判得准**。

        **拆汉字闸那条路也量完了：不通**（收 P88 ③）。全库对拍变了 6 条、
        逐条读完 **变好 0 / 中性 2 / 变差 4**（标注 `p90-engate-6`），
        卡在门槛（`ai` 主语面 .819 < 0.85）和轴（主语面在英文串上没有信号，
        `p90-holdout-en-60` 这份**英文那半的第一个留出集**量过）两格。
        量具进了仓库：`scripts/recall_ruler.py --cf-gates`（三档 + 接线自检，对不上 exit 9）。
        """
        from ..kb import relations as R
        from ..kb import topic_face as TF

        store, _vocab = self._index()
        idx = self._grep_index(store)
        if idx is None or not idx.unit_count:
            return None
        total = idx.unit_count
        # **大库那一档一个字都不动**：6% 本来就是有效门槛，`MIN` 绑不住它。
        # 这个判断只跟库大小有关，所以在这儿算一次，不进每个串的热路。
        ask_face = total * R.COMMON_DF_RATIO < R.COMMON_DF_MIN

        def is_common(term: str) -> bool:
            n = idx.unit_df(term, floor=R.COMMON_DF_MIN)
            if not (n is not None and n >= R.COMMON_DF_MIN
                    and n / total >= R.COMMON_DF_RATIO):
                return False
            if not (ask_face and TF.has_cjk(term)):
                return True
            face = self._topic_face(store, idx)
            if face is None:
                return True
            # **只有明确「不泛」才捞回来**；`None` = 判不了，照旧算 common。
            if face.generic(term) is not False:
                return True
            # **第二条轴**（P88 ①）：话题面说「不泛」了，再问一句主语面。
            # 串在后面而不是并排，是因为**这一刀只许做减法**——见下面那段。
            who = self._who_face(store, idx)
            if who is None:
                return False
            return who.generic(term) is not False

        return is_common

    def vocab_term(self):
        """回一个「这串**是这个人词表里的一个词**（实体 / 主题的表层词）」的判据，
        给 `kb/search.qualifies(attested=…)`（P32 #1）。

        判据为什么长这样、为什么只用在「只剩一条证据串」那一档，写在
        `kb/search.EVIDENCE_CJK_MIN` 上面那段注释里。这里只负责把这个人的词表接上去。

        **只当放行条件，从不用来否掉任何东西**——P29 #1 量过，拿「是不是实体」当唯一的闸
        会连 `cpu+npu` / `第二款产品` 这种真沾边一起砍（1239 个实体里混着 `app` / `device`，
        又漏着 `超节点`）。零模型、零额外 IO：词表本来就在索引里。
        """
        try:
            _store, vocab = self._index()
        except Exception:      # noqa: BLE001 —— 建不出索引就是不启用这一档
            return None
        # 一篇 30k 字的笔记首开要 recall 143 次，每次重扫 1404 个实体是白扫的——
        # 跟 `_grep_index` 一样按索引 mtime 缓存，索引换了它跟着重建、闲置一起回收
        key = f"{self.path}#vocabterm"
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            mtime = None
        hit = self._cache.get(key)
        if mtime is not None and hit and hit[0] == mtime and hit[2] is vocab:
            return hit[1]
        surfaces: set[str] = set()
        for code, topic in getattr(vocab, "topics", {}).items():
            if getattr(topic, "status", "") == "deprecated":
                continue
            for s in {code, *(getattr(topic, "aliases", set()) or set())}:
                sl = str(s).replace("_", " ").lower()
                if len(sl) >= 2:
                    surfaces.add(sl)
        for code, ent in getattr(vocab, "entities", {}).items():
            if is_speaker_tag(code) or is_speaker_tag(getattr(ent, "name", "")):
                continue
            for s in {code, getattr(ent, "name", ""), *(getattr(ent, "aliases", set()) or set())}:
                sl = str(s).replace("_", " ").lower()
                if len(sl) >= 2:
                    surfaces.add(sl)
        if not surfaces:
            return None

        def attested(term: str) -> bool:
            return term in surfaces

        if mtime is not None:
            self._cache[key] = (mtime, attested, vocab)
        return attested

    def segment(self):
        """回一个**中文切词函数**（`str -> list[str]`），给 `kb/search.qualifies(segment=…)`（P34 #1）。

        判据为什么要分词、底表为什么是自带的 1.5 MB 而不是 jieba 的 37 MB，
        写在 `kb/tokenize.py` 顶上那段里。这里只负责**把这个人的专名接上去**：
        底表是通用汉语词，`算力` / `灵衢` / `众筹后` 这种它没有，不补就会切成单字，
        「算力底座」的实词字数从 4 掉到 2——**把 P29 点名的一条真沾边砍掉**。
        补充词就是 `vocab_term` 用的那批表层词（实体 / 主题），零额外 IO。

        建不出索引 / 词典读不出来就回 `None` = **不启用这一层，不启用就是原样**
        （`_why` 退回 P32 的原始字数规则）。
        """
        from ..kb import tokenize as tok

        try:
            store, vocab = self._index()
        except Exception:      # noqa: BLE001 —— 建不出索引就是不启用这一档
            return None
        path = getattr(self, "path", None)
        key = f"{path}#segment"
        try:
            mtime = path.stat().st_mtime
        except (OSError, AttributeError):
            mtime = None
        hit = self._cache.get(key)
        if mtime is not None and hit and hit[0] == mtime and hit[2] is vocab:
            return hit[1]
        extra: set[str] = set()
        for code, topic in getattr(vocab, "topics", {}).items():
            for s in {code, *(getattr(topic, "aliases", set()) or set())}:
                extra.add(str(s).replace("_", " ").lower())
        for code, ent in getattr(vocab, "entities", {}).items():
            for s in {code, getattr(ent, "name", ""), *(getattr(ent, "aliases", set()) or set())}:
                extra.add(str(s).replace("_", " ").lower())
        # **第三份词典：这个库自己长出来的**。底表是通用汉语词，`众筹` / `算力` / `灵衢`
        # 它一个都没有；实体表也不一定收（`众筹` 在真库里就不是实体）。
        # 所以再加一条**按需**问库的路：切词时碰到底表不认识的 2–3 字串，就问一句
        # 「这个串在这个人的库里出现在几条记录里」（`unit_df`，走的是 `search.plan` 已经
        # 在用的那份 2-gram 倒排表，memo 过，零额外 IO）。
        # 两道窄闸，**宁可不认识**：
        # · 串里不许有口水字——不然 `的一` / `了这` 这种跨词的两字串也会攒够次数变成「词」；
        # · 至少 `WORD_DF_MIN` 条记录里出现过——只出现一两次的多半是撞出来的。
        try:
            idx = self._grep_index(store)
        except Exception:      # noqa: BLE001 —— 问不出 df 就只是少一档兜底，不是不启用
            idx = None
        attest = _corpus_word(idx) if (idx is not None and idx.unit_count) else None

        try:
            t = tok.Tokenizer(extra, attest=attest)
        except Exception:      # noqa: BLE001 —— 词典读不出来就是不启用
            return None
        if not t.enabled():
            return None
        if mtime is not None:
            self._cache[key] = (mtime, t.cut, vocab)
        return t.cut

    def _prescreen(self, store, queries: list[dict]) -> list[dict]:
        """`search.plan` 给的查询列表 → 同义但便宜的那份：每条 `{"grep": 词}` 按预筛结果带上 `units`。
        条数、顺序、别的查询都不动（kite 只取前 3 条，动了条数就是换查询）。"""
        idx = self._grep_index(store)
        if idx is None:
            return queries
        out: list[dict] = []
        for q in queries:
            where = q.get("where") or {}
            term = where.get("grep") if isinstance(where, dict) else None
            if not term or len(where) != 1 or q.get("select", "facts") != "facts":
                out.append(q)
                continue
            out.append(_narrow_grep_query(q, idx.units_for(str(term))))
        return out

    def _index(self):
        """加载符号索引，按 mtime 缓存 —— 每次请求重新解析 XML 是浪费。"""
        self.ensure()
        mtime = self.path.stat().st_mtime
        key = str(self.path)
        self._last_used[key] = time.time()
        hit = self._cache.get(key)
        if hit and hit[0] == mtime:
            return hit[1], hit[2]
        store, vocab = Store.load([key])
        # **把用户挂在 store 上**：下游（`kb/entities.for_store`）要按用户去取
        # 「人判过的实体合并」，而它手上只有 store。加一个属性比给五个调用点
        # 都加一个参数干净——那五处分散在 routers / search / pages 三层。
        try:
            store._memoket_user = self.user_id
        except Exception:      # noqa: BLE001
            pass
        self._cache[key] = (mtime, store, vocab)
        return store, vocab

    def is_empty(self) -> bool:
        """这个用户的知识库一条事实都没有。

        **「库是空的」跟「这一次没查到」是两件事**：后者该劝人换个说法再试，
        前者该劝人去导入。分不开的时候，写作闭环会对着空库反复换检索路径
        （第 676 轮实跑量到白烧一轮），`@` 引用会说「没找到跟 X 相关的记录」
        （第 677 轮实拍）——两句话对一个还没导过任何东西的人都是误导。

        索引按 mtime 缓存，检索本身刚加载过，所以这是一次字典取长度；读不出来
        一律当「不是空的」，宁可少说一句也不要对着读失败告诉用户「你没有材料」。
        """
        try:
            store, _vocab = self._index()
            return not getattr(store, "facts", None)
        except Exception:      # noqa: BLE001
            return False

    def invalidate(self) -> None:
        self._cache.pop(str(self.path), None)

    @classmethod
    def evict_idle(cls, ttl_s: float | None = None, now: float | None = None) -> int:
        """放掉闲置超过 ttl 的索引（含 fact_attrs 那类派生缓存）。main.py 每分钟调一次。
        返回放掉了几项。"""
        ttl = cls.IDLE_TTL_S if ttl_s is None else ttl_s
        now = time.time() if now is None else now
        gone = 0
        for key in list(cls._cache):
            base = key.split("#", 1)[0]
            last = cls._last_used.get(base, 0.0)
            if now - last > ttl:
                cls._cache.pop(key, None)
                gone += 1
        if gone:
            import gc
            gc.collect()
        return gone

    @classmethod
    def cache_info(cls) -> dict:
        return {"entries": len(cls._cache), "users": sorted({k.split("#", 1)[0].rsplit("/", 2)[-2] for k in cls._cache})}

    # ------------------------------------------------------------ 检索（零 LLM）

    @staticmethod
    def _candidate_terms(text: str) -> list[str]:
        """英文候选词。"""
        words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}", text.lower())
        return [w for w in words if w not in STOPWORDS][:12]

    @staticmethod
    def _cjk_terms(text: str, weigh=None) -> list[str]:
        """中文候选词：没有空格可切，用 2-3 字滑窗生成 n-gram。

        KITE 的抽取提示词是英文的，中文输入抽出的 fact 可能是英文，符号通道
        匹配不上。但原始 <line> 保留了中文原文，这些 n-gram 拿去 grep 原始行
        仍然能命中。

        两个要点：
        1. **从最靠近光标的片段开始** —— 续写时正文尾部才是相关的。
        2. **按片段轮转取样** —— 逐段生成会让第一个长片段吃光配额，
           后面真正有信息量的词（"后端准备用"）永远进不了候选。

        **`weigh`：先给实词，再给碎片（P65 ①）。** 名额还是 16，一个没动——
        动的是**谁先拿到这 16 个**。P60 / P61 / P63 三批在名额上来回量过
        （24 / 32 / 48 / 400 各一档全库对拍，P63 还把 cap 24 那 190 对一条不落读完了），
        结论都是「不改」，而 P63 收尾写下的是：**问题不在名额在排序**——
        `记忆` 这种真词排在第 17 位，而 `了智` / `的业务` / `另一方` 这些碎片占着前 16，
        抬名额只是把碎片和真词一起放进来。

        判据就是 `_strong_enough` 那一把尺（`kb/search._weigher` → `tokenize.content_chars`，
        **同一个函数、同一份口径，不另起一把**）：这一串在查询的分词里整词覆盖了
        几个字的实词，`>= STRONG_CJK_MIN` 就算实词。调用方把 `_weigher(...)` 的返回值
        原样递进来，**不给就是原样**——`weigh is None` 这一支跟 P63 的 HEAD 逐字相同，
        `_cjk_greps` 的退路、行级回退、面板那几条路今天都还走它。

        **轮转在每一档里原样保留**：实词那一档自己轮转一遍（片段公平性是 P4 立的，
        这一批一个字没动），没填满再让碎片那一档接着轮转填。所以这一刀是
        **纯换序**，不放进任何今天进不来的词、也不少给任何一条查询词。

        `weigh` 回 `None`（定位不到）按「不知道」处理 = **不给它插队**，仍排在碎片那一档里。
        这跟 `content_chars` 顶上那句「不许当成 0」不冲突：那句说的是「当成 0 就把一条召回
        判死」，而这里最坏也只是**顺序没变**，一个词都不会因此被踢出去。

        ## ⚠️ **那 16 是「整屏变空」的真根因**（P86 ③，**更正 P84 ⑥**）

        P82 / P84 两批放宽 `common` 的刀都栽在**同一条查询**上（`recall_ruler` 的
        i=293，`terrence-rewrite`）：唯一那条逐句出处「Speaker A …最终因大健康业务裁员而
        **离开安克**」掉了，**整屏变空**。P84 ⑥ 把它记成
        「**排名挤压**（捞回来的串让更多事实够了 quorum，好的那条被挤出 top-8）」。
        **那句话是错的**，这一批查清了：

        * 它在基准上只有 **1 条**候选、变完 **0 条**——**只有一条的时候没有
          「被谁挤出 top-8」这回事**。`out[:8]` 和排序在这条上一次都没参与。
        * 真正的挤压就发生在**这里、这 16 个名额上**。那条轴在小库上把 `公司` 从
          `common` 手里捞回来，于是 `大公司` / `公司病` / `公司运` 进了实词那一档，
          **把 `开安克` 挤出了这 16 个**（`司运转`/`运转方`/`开安克`
          → `大公司`/`公司病`/`公司运`，三换三）。
        * `开安克` 一走，`离开安` + `开安克` 就合不成 `离开安克` 那一整段，
          `evidence()` 从 `('离开安克', 'span')` 退成 `('离开安', 'pair')`，于是
          `qualifies`（单条证据不许是 `pair`）和 `_strong_enough`（至少两个 cluster）
          **两道闸同时翻**，那条事实打 0 分 → 一条都不剩。
          **quorum 是最后那道说「不」的闸，但它说得没错——错在喂给它的词表被掏空了。**

        三个反事实钉着这条因果链（`tests/test_p86.py::第三条`，**一次只动一样**）：
        单独把 `公司` 按回 `common` → `开安克` 回来、`span` 回来、召回回来；
        只把这个 16 抬到 17 → 同样全部回来；HEAD 原样 → 照旧空屏。

        **这一批判「不改」**：能修它的旋钮就是这个 16，而它正是 P60 / P61 / P63
        三批来回量过、P63 还把 cap 24 那 190 对一条不落读完之后判「不改」的那一个
        （抬名额把碎片和真词一起放进来，user 侧误判率 43.0%）。
        **不重读那 190 对就动这个数，等于拿一条查询换一整张读过的表。**
        账记在 `docs/TRACELOG-product.md` 的 P86 ③。

        ## ⚠️ **上面那句「能修它的旋钮就是这个 16」是错的**（P88 ②，**更正 P86 ③**）

        ⚠️ **并排写**：错的那句留在原地，跟这一段对照着读。

        **① 「不重读那 190 对就不能动这个 16」这句话，前提就不成立**——
        P86 引的那 190 对**不是今天该重读的那一批**，这一批在夹具和库上重数过：

        | | 单位 | 查询 | (查询,事实) 对 | 基准 HEAD 的 `有召回 / 召回对` |
        |---|---|---:|---:|---|
        | `p63-cap24-190` | **对** | **86** | **190**（进 153 / 掉 37）| 337 / 1345 |
        | `p73-cap24-134` | **条（查询）** | **134** | 231（进 207 / 掉 24）| 341 / 1347 |
        | **今天（P88 重量）** | | **144** | 252（进 219 / 掉 33）| **345 / 1367** |

        **两把尺量的不是同一批**：按 `(user, i)` 比，P63 那 86 条跟 P73 那 134 条
        **只交 15 条**；按查询原文比也只交 59 条。而且 **P63 判「不改」的那条理由
        已经被 P73 证伪了**（P63 说「抬名额只是把碎片和真词一起放进来」，
        P73 实测多出来的 5898 串次里 **98.3% 是实词**、碎片只有 1.7%）。
        **P86 引的是一张两代之前的、理由已经作废的表。**
        （P73 那 134 条跟今天也差了 13 条新的 / 3 条没了——P84 那条轴落地之后 HEAD 动过。）

        **② 而且这一批找到了一条不动这个 16 也能治 i=293 的路**，所以这 16
        今天**不必**动：`common_term()` 里新串的那条主语面轴（`kb/topic_face.WhoFace`）
        让 `公司` 不再被捞回来（主语面 .900 ≥ `WHO_GENERIC`），
        于是 `大公司`/`公司病`/`公司运` 退出实词档，`开安克` **自己回到这 16 个名额里**，
        `span` 回来、两道闸一起放行、那条逐句出处回到屏幕上。
        **那条因果链一个字没改，改的是链条最前面那一环。**
        全库对拍见 `common_term()` 的 P88 ① 那段（变了 2 条 · 进 2 掉 0 · 变好 1 中性 1）。
        账记在 `docs/TRACELOG-product.md` 的 P88 ②。

        > **留给下一批**：真要动这 16，该重读的是**今天这 144 条**，
        > 不是 P63 那 190 对、也不是 P73 那 134 条。
        """
        runs = [r for r in re.findall(r"[一-鿿]{2,}", text)
                if r not in STOPWORDS]
        runs.reverse()

        per_run: list[list[str]] = []
        for run in runs:
            grams: list[str] = []
            for size in (3, 2):
                for i in range(len(run) - size + 1):
                    g = run[i:i + size]
                    if g not in STOPWORDS and g not in grams:
                        grams.append(g)
            if grams:
                per_run.append(grams)

        # 两档：**实词先转一遍，转不满再让碎片接着填**。
        # `weigh is None` 时第二档是空的，于是整个函数**逐字退回**只有一遍轮转的那一版
        # ——这一支跟 P63 的 HEAD 逐条相同，`test_p65` 拿抄过来的原算法钉着。
        first, second = per_run, []
        if weigh is not None:
            from ..kb.search import STRONG_CJK_MIN
            solid: dict[str, bool] = {}
            for grams in per_run:
                for g in grams:
                    if g not in solid:
                        n = weigh(g)
                        solid[g] = n is not None and n >= STRONG_CJK_MIN
            first = [[g for g in grams if solid[g]] for grams in per_run]
            second = [[g for g in grams if not solid[g]] for grams in per_run]

        return _rotate(second, _rotate(first, [], 16), 16)

    @staticmethod
    def _surface_in(sl: str, lowered: str) -> bool:
        return _surface_in(sl, lowered)

    # 同一次 recall 里 `_match_vocab(同一段, 同一份词表)` 要算三遍（recall 本身 / `search.plan` /
    # `search.rank`），`relations/batch` 一段一段来，每段都是三遍全表扫描（P11 #3 实测 80 段 277 次）。
    # 按 (文本, 词表对象) 记住结果；词表换了（`_index` 按 mtime 重建）自然失配。返回的是拷贝，
    # 调用方改自己那份不会污染缓存。
    _MV_MEMO_MAX = 256

    def _match_vocab(self, text: str, vocab) -> tuple[list[dict], list[str], list[str]]:
        memo = self.__dict__.setdefault("_mv_memo", {})
        hit = memo.get(text)
        if hit is not None and hit[0] is vocab:
            t, e, s = hit[1]
            return [dict(x) for x in t], list(e), list(s)
        out = self._match_vocab_uncached(text, vocab)
        if len(memo) >= self._MV_MEMO_MAX:
            memo.clear()
        memo[text] = (vocab, ([dict(x) for x in out[0]], list(out[1]), list(out[2])))
        return out

    def _match_vocab_uncached(self, text: str, vocab) -> tuple[list[dict], list[str], list[str]]:
        """把查询映射到符号码。

        两条通路：
        1. 英文按词切开后 resolve —— 精确命中 code 或 alias。
        2. 反向扫描：拿词表里已知的表层词去查询串里做子串匹配。中文没有空格，
           只能靠这条；顺带也能匹配到多词短语。
        """
        topics: list[dict] = []
        entities: list[str] = []
        hit_surfaces: list[str] = []
        lowered = text.lower()

        for term in self._candidate_terms(text):
            code = vocab.resolve_topic(term)
            if code and not any(t["code"] == code for t in topics):
                topics.append({"code": code, "closure": True})
                hit_surfaces.append(term)
            code = vocab.resolve_entity(term)
            # 「speaker b」在词表里是个实体：让它进符号通道会把那个说话人的几百条事实整个拉进候选池，
            # 还占掉 4 个实体槽里的一个（第 531 轮）。说话人标签不是查询的对象
            if code and code not in entities and not is_speaker_tag(term) and not is_speaker_tag(code):
                entities.append(code)
                hit_surfaces.append(term)

        for code, topic in vocab.topics.items():
            if getattr(topic, "status", "") == "deprecated":
                continue
            for surface in {code, *getattr(topic, "aliases", set())}:
                sl = str(surface).replace("_", " ").lower()
                if len(sl) >= 2 and _surface_in(sl, lowered):
                    if not any(t["code"] == code for t in topics):
                        topics.append({"code": code, "closure": True})
                        hit_surfaces.append(sl)
                    break

        for code, ent in vocab.entities.items():
            if is_speaker_tag(code) or is_speaker_tag(getattr(ent, "name", "")):
                continue
            surfaces = {code, getattr(ent, "name", ""), *getattr(ent, "aliases", set())}
            for surface in surfaces:
                sl = str(surface).replace("_", " ").lower()
                if len(sl) >= 2 and _surface_in(sl, lowered):
                    if code not in entities:
                        entities.append(code)
                        hit_surfaces.append(sl)
                    break

        return topics[:4], entities[:4], hit_surfaces

    def recall(self, query: str, limit: int = 8, scope: str = "all", *,
               evidence: bool = False) -> tuple[list[dict], list[str], float]:
        """符号检索。返回 (fact 行, 命中的表层词, 耗时毫秒)。

        `evidence=True` 才过 P32 #1 那道**证据闸**（`kb/search.qualifies`）。
        **默认关着，是量出来的，不是偷懒**：这个函数有两种用途，收紧只对其中一种成立。
        · **拿给用户看的那一列**（`/memory/recall` → 右栏「记忆」/ ⌘K / 知识库搜索框）——
          每一条都得说得出「为什么给我看这条」，说不出就别送上去。这一档 `evidence=True`。
        · **给判据当候选池的那一次**（`/memory/relations`、`relations/batch`、摄入冲突扫描、
          写作取材料）——下游 `kb/relations.detect` 自己有一套**更全**的判据：同值同单位、
          同一天、共用编号，**词面证据不够不等于关系判不出来**。
          实测：把闸开在这条路上，N4 `e78306202d78` L27 那个从 P22 就在的**绿点**
          （印证 `1439-0F4`）当场掉了——`detect` 是靠「同值同单位」判出来的，
          而那条候选的词面证据只有一条站不住的串。**「留下率不许跌」说的就是这种。**

        **P38 #5：`search.plan` 的中文 grep 通道跟着 `evidence` 一起开关，理由是同一条。**
        那一处从「2–3 字滑窗」换成「分词出来的实词」之后，全库 37/765 条查询的 top-8 变了
        （掉 33 对 / 进 43 对）。**37 条逐条读过**：18 条明确变好（`自动化测试` 一条捞回 7 条真沾边、
        `80%以上` 砍掉 5 条撞词、「好几回」那段砍掉 7 条撞 `好几` 的、`3月10日众筹版本` /
        `算力底座…行业知识` / `相关功能7月前后` 几条逐句对应的进来了）、9 条明确变差
        （`成功经验`、`希望通过`、「这篇用来看链接面板」这种虚词撞的，和 `投资人` 那 5 条
        股权架构合规的）、8 条平手。自召回那一栏跌的 2 条**逐条找出来读过**：
        `terrence-596-6F3`「嗯,那我们这个键就不要了」（拿口水句自己召回自己）和
        `terrence-2029-8F9` 的 40 字截断档——**两条都是退化用例，不是真相关性掉了**。
        **但候选池那条路不能开**：开了之后 N4 那个绿点又掉了一次（`corroborated → no_record`），
        跟 P32 那一刀是同一个根因——**候选池宁可宽，一个闸别管所有调用方**。

        **先撒网再排序**，不是「命中主题后按时间取前 8」。原来那个写法等于
        「这个主题下最近的 8 条」，跟查询内容无关——实测拿一条事实自己的原文
        去查，只有 22% 能召回它自己、38% 能召回同主题的东西。撒网 + 按词面
        重排之后是 90% / 97%，仍然零 LLM 调用、仍然几毫秒。判据和量出来的
        数字见 ``kb/search.py``。
        """
        t0 = time.perf_counter()
        # 正文当查询时先剥掉引用标记 / 图片 / 链接地址（search.clean_query）——后端自己拿正文查的
        # 那几条路（选中校验、摄入冲突扫描、写作取材料）原来是带着标记去查的（第 566 轮）
        query = search.clean_query(query)
        store, vocab = self._index()
        _topics, _entities, surfaces = self._match_vocab(query, vocab)
        # 报给右栏的「命中词」里别列 speaker b 这种说话人标签（它在词表里是个实体，所以会被认出来）：
        # 第 530 轮正式版冒烟 recall terms=['speaker b', 'ideas']——用户看着像是拿说话人在搜
        surfaces = [x for x in surfaces if not is_speaker_tag(x)]

        # 证据资格那两档由调用方注入（P32 #1，同 P29 给 `relations.detect` 注 `common` 的做法）：
        # `kb/search` 不依赖 app 的其它模块，拿不到这个人的 df 索引和词表。
        common, attested = ((self.common_term(), self.vocab_term()) if evidence
                            else (None, None))
        # 中文切词只在**开着证据闸**的那条路上要（P34 #1 / P38 #5）：`qualifies` 和
        # `search.plan` 的中文 grep 通道都只在那条路上问它，闸不开就没人问，白建一份词典。
        segment = self.segment() if evidence else None
        # `common` 跟着 `segment` 一起进 `plan`（P42 A2）：取 grep 词那一处原来只剔
        # 口水词那张固定表，不剔「这个人库里满库都是」的那一档。全库量过：4 条查询的
        # top-8 变了、掉 2 进 2、四条逐条读过全是好的方向，47 条抽样一条没动。
        # **闸是同一个**（`evidence=True`）——候选池那条路不给，理由同 P38 #5。
        queries = search.plan(self, query, vocab, segment=segment, common=common)
        facts: list[dict] = []
        if queries:
            rows, _trace = execute_plan(store, vocab, {"queries": self._prescreen(store, queries)},
                                        budget=search.POOL * 2)
            facts = [r for r in rows if r.get("type") == "fact"]
        # 多留一些候选再筛：无论哪个范围，筛完都可能不够 `limit` 条
        # （「全部」也会筛掉屏幕活动，见 kb/scope.filter_rows）
        facts = search.rank(facts, query, self, store, limit=limit * 4,
                            evidence=evidence, common=common, attested=attested,
                            segment=segment)

        if not facts:
            # 行级回退拉出来的是整场会的事实，同样要过一遍「至少命中一个查询词」——
            # 不然「这篇是从系统拖进来的」这种没信息量的句子照样召回一屏不相干的（第 225 轮）
            facts = search.rank(self._recall_via_lines(store, vocab, query, limit * 2),
                                query, self, store, limit=limit,
                                evidence=evidence, common=common, attested=attested,
                                segment=segment)
            # **这一处是 fallback，逐字保持原样**（P61 立的那条，P67 ② 复核过）：
            # 行级回退是「上面那条路一条都没排出来」才走的，它自己没有 `segment`
            # 那一档（`evidence=False` 时 `segment` 本来就是 `None`）。
            surfaces = surfaces + self._cjk_terms(query)[:3]
        else:
            # **这两个实参是 P67 ② 接上的**：面板那行「命中：」得跟 `rank` 真用的
            # 那一份是同一份（P65「留给下一批」②）。`evidence=False` 时 `segment`
            # 就是 `None`，`_weigher` 回 `None`，这一支**逐字退回**改之前那一版。
            surfaces = surfaces + [t for t in search.matched_terms(
                facts, query, self, store, common=common, segment=segment)
                if t not in surfaces]

        from ..kb.scope import filter_rows
        facts = filter_rows(facts, scope)     # 「全部」也要筛：它不含屏幕活动
        return facts[:limit], surfaces, (time.perf_counter() - t0) * 1000

    def recall_evidence(self, query: str, rows: list[dict]) -> list[dict]:
        """这几条召回各自**凭什么**进来——右栏那句「为什么给我看这条」的原料（计划 §2 A5）。

        面板原来只写「命中：再决定」。P31 实拍证明**光说命中了哪个词不够**：它说对了自己在
        干什么，干的这件事本身是错的。所以这里把**那个词凭什么算证据**也一起给出去：
        · `vocab` —— 它是你知识库里的一个词条（实体 / 主题）；
        · `span`  —— 这么长的一整段原话逐字对上（≥4 个汉字 / ≥4 个字母，不可能是一个滑窗撞的）；
        · `pair`  —— 它自己不够硬，是跟别的词**一起**命中才算数的。
        `units` 是这个词在你库里出现在几条记录的 unit 里（P29 的 df），让「为什么」有个量。

        **两条显示过滤（P44，账在 P41 #2 里量完了）**：P40 实拍「3月12号上线」被摆成
        「命中：众筹页面、**号上**、页面」——「号上」横跨 `号` 和 `上线` 的词边界，
        而且每一个字都在 `_EDGE_STOP` 里，原来那行 `label = … or term` 把剥空的原串退了回来。
        · `aligned is False` —— 跨词边界的碎片，不摆（`kb/search._aligned`）；
        · 剥完合不出 ≥2 个字的，不摆（跟 `search.display_terms` 同一条规矩）。

        **P46 松了一格：它自己就是一个词的，剥之前先放过**（`search.is_whole_token`）。
        `华为` / `阿里` / `不变` / `上线` 都是这个形状——真词，只是末字碰巧在 `_EDGE_STOP`
        那张表里，剥完剩一个字就被第二条砍了。全库代价逐条读过：9 条查询的行变了。

        **过滤必须留底**：这两条砍的只是「这一串摆不摆出来」，**召回那几条一条都不少**
        （`rows` 是调用方传进来的，`qualifies` 这一批一个字没动）。全被砍光时这里回空列表——
        **一条证据都摆不出来 ≠ 这条召回不成立**。全库量过：765 条查询里有 9 条落到这一档。
        **空列表是一个判断，不是「没判成」**（P46 #1）：前端据此如实说一句
        「这一段没有可摆出来的证据」，**不再退回 `display_terms`**——后端已经判出
        「这些串都不合格」，前端拿一份没判过的去顶，摆出来的是「希望通过智能化能」
        这种更碎的。「没判成」走的是另一条路：`/recall` 那里 `evidence=None`。

        **去重按摆出来的那一串**（不是按原始的 run）：`众筹后` 和 `众筹的` 剥完都是「众筹」，
        按 run 去重会把同一个词摆两遍（全库量过真的有，见 P44 台账）。
        """
        store, _vocab = self._index()
        q = search.clean_query(query)
        common, attested, segment = self.common_term(), self.vocab_term(), self.segment()
        # **`_weigher(...)` 是 P67 ② 接上的**，跟 `matched_terms` 同一个理由：
        # 右栏摆出来的证据 chip 得是**真干了活的那几个词**。这条路原来走 `weigh is None`，
        # 于是它按碎片优先取前 16 个，而 `rank` 按实词优先——两份词。
        # **一条召回都不动**：`rows` 是 `/recall` 排好递进来的（上面文档串第一段就是这句），
        # 这里只决定摆哪几个 chip。
        terms = search._terms(self, q, search._weigher(q, segment, common))
        squeezed = search.squeeze(q)
        idx = self._grep_index(store)
        seen: set[str] = set()
        out: list[dict] = []
        for r in rows:
            f = store.facts.get(r.get("id"))
            text = (f.text if f else "") or ""
            for e in search.evidence(search._hits(terms, text), q,
                                     common=common, attested=attested, segment=segment):
                term = e["term"]
                if e.get("aligned") is False:
                    continue
                # **这两个实参不能省**（P46）：省了就退回「一律剥」，而上面那格 `aligned`
                # 是按**带着它们**算出来的 label 判的——两把尺子，`华为` 会判成对齐、
                # 摆出来却是被剥成单字的「华」。接线洞，`test_p46` 专门钉了一条。
                label = search.evidence_label(term, squeezed, segment)
                if not term.isascii() and len(label) < 2:
                    continue
                if label in seen:
                    continue
                seen.add(label)
                out.append({"term": label, "why": e["why"],
                            "units": (idx.unit_df(term) if idx else None) or 0})
        return out[:6]

    def recall_multihop(self, question: str, limit: int = 8) -> tuple[list[dict], bool, float]:
        """多跳检索：先按内容定位到某次会话，再在那个范围里展开。

        上面的 ``recall()`` 是零 LLM 的词法检索，快、直接命中好，但它**不会
        多跳**：「在讨论 X 的那次会里还提到了什么」这种意图，一个词袋根本
        表达不了——第一跳要按内容定位 session，第二跳要在那个 session 里展开。

        KITE 的 plan 代数支持这个（``stages`` + ``$anchor.units`` 绑定，引用
        解析是确定性的，LLM 只写模板），代价是一次 compile 的 LLM 调用
        （本地模型约 10 秒）。所以它不替代 recall()，是并列的另一条通道，
        由写作 agent 按问题类型自己选——实测两者的失败场景互不重叠，代码里
        替用户选反而更差。

        返回 ``(fact 行, 是否真的编出了多跳计划, 耗时毫秒)``。第二个值让调用方
        能如实说明「这次是不是真走了多跳」：模型判断问题不需要多跳时会编出
        单跳计划，那种情况这条路径不比 recall() 好，只是更慢。
        """
        from memoket_kite.core.algebra import execute_plan
        from memoket_kite.pipeline.compile_plan import compile_plan

        from .kite_profile import WritingProfile

        t0 = time.perf_counter()
        _export_provider_env()
        kb, vocab = self._index()
        profile = WritingProfile(
            Memory.load([str(self.path)])._reasoner()._profile, kb, vocab)
        # 必须取**当前生效**的模型，不能读 Settings.llm_model——后者是 .env
        # 里的本地模型默认值，进程启动时定死。用户在设置页切到 GPT 之后，
        # 这里还拿 muse-glimmer-30b 去问 OpenAI，直接 404。
        model = os.environ.get("KITE_MODEL") or store.get_active_llm_config()["model"]
        # n_candidates=1 / scorer=None：只 compile 一次。库默认采样 3 个候选再
        # 用确定性 scorer 选优，实测把耗时推到 110 秒——而那个 scorer 打的是
        # plan 的形状（行数、有没有用结构过滤），不是结果跟问题的相关性。
        plan = compile_plan(question, vocab, kb, profile, model,
                            scorer=None, n_candidates=1)
        rows, _trace = execute_plan(kb, vocab, plan, speakers=kb.speakers,
                                    budget=limit)
        facts = [r for r in rows if r.get("type") == "fact"]
        return facts[:limit], bool(plan.get("stages")), (time.perf_counter() - t0) * 1000


    def _recall_via_lines(self, store, vocab, query: str, limit: int) -> list[dict]:
        """跨语言回退：在原始对话行里 grep，命中后取所属 session 的 facts。"""
        terms = self._cjk_terms(query) + self._candidate_terms(query)
        if not terms:
            return []

        # 同一行原话里要同时出现至少两个查询词才算命中：「这篇是」「系统」这种词几乎哪场会都
        # 各有一行，分散命中就把整场会的事实都拉出来，右栏全是不相干的（第 224 轮实拍拖一篇
        # .md 进来）。两个词挤在一句话里才像是在说同一件事。
        probe = [t for t in terms[:12]]
        hits: dict[str, int] = {}
        idx = self._grep_index(store)
        for term in probe:
            # 预筛（P15 #4）：库里的原话一行都没有这个词 → 这一次 grep 本来就是空的，不发；
            # 落在 ≤ 8 个 unit 里 → 带 `units` 过滤（lines 的 units 是纯过滤，结果一样）
            units = idx.units_for(term, lines=True) if idx is not None else None
            if units is not None and not units:
                continue
            rows, _t = execute_plan(
                store, vocab,
                {"queries": [_narrow_grep_query(
                    {"select": "lines", "where": {"grep": term},
                     "pipe": [{"op": "head", "n": limit}]}, units)]},
                budget=limit)
            for r in rows:
                unit = r.get("unit")
                text = (r.get("text") or "").lower()
                n = sum(1 for t in probe if t.lower() in text)
                if unit and n >= 2:
                    hits[unit] = max(hits.get(unit, 0), n)
        units = [u for u, n in sorted(hits.items(), key=lambda kv: -kv[1])][:4]

        if not units:
            return []

        rows, _t = execute_plan(
            store, vocab,
            {"queries": [{"select": "facts", "where": {"units": units[:8]},
                          "pipe": [{"op": "sort", "key": "t", "desc": True},
                                   {"op": "head", "n": limit}]}]},
            budget=limit)
        return [r for r in rows if r.get("type") == "fact"]

    def source_lines(self, fact_row: dict) -> list[str]:
        """取一条 fact 的原始出处（receipts）。"""
        store, _vocab = self._index()
        out = []
        for line_id in (fact_row.get("src") or "").split():
            line = getattr(store, "lines", {}).get(line_id)
            if line is not None:
                out.append(getattr(line, "text", ""))
        return [t for t in out if t]

    # ------------------------------------------------------------ 结构化浏览（可视化用，零 LLM）
    #
    # 故意不用 memoket_kite.research.CodebookInspector —— 那是上游明说的非稳定
    # API（见 docs/kite-constraints.md 约束 8）。这里全走 core.Store / core.Vocab，
    # 跟 recall() 用的是同一层，字段含义和边界情况都已经在检索路径上踩过坑了。

    def topics(self) -> list[dict]:
        """topic 树。parents 字段构成层级——前端自己拼树，不在这里嵌套。

        fact_count 是精确匹配该 code 的 fact 数（不含子主题闭包），给force
        图当节点大小用；跟 facts_page(topic=...) 的闭包过滤是两回事。
        """
        store, vocab = self._index()
        counts: dict[str, int] = {}
        for f in store.facts.values():
            for code in f.topics:
                counts[code] = counts.get(code, 0) + 1
        return [
            {"code": t.code, "parents": sorted(t.parents), "status": t.status,
             "aliases": sorted(t.aliases), "fact_count": counts.get(t.code, 0)}
            for t in sorted(vocab.topics.values(), key=lambda t: t.code)
        ]

    def entities(self) -> list[dict]:
        store, vocab = self._index()
        counts: dict[str, int] = {}
        for f in store.facts.values():
            for code in f.entities:
                counts[code] = counts.get(code, 0) + 1
        return [
            {"code": e.code, "name": e.name, "type": e.etype,
             "aliases": sorted(e.aliases), "relations": sorted(e.rels),
             "fact_count": counts.get(e.code, 0)}
            for e in sorted(vocab.entities.values(), key=lambda e: e.code)
            if not is_speaker_tag(e.code) and not is_speaker_tag(e.name or "")   # 说话人标签不是实体（第 554 轮，跟树 / 首页 / stats 一致）
        ]

    def topic_entity_links(self) -> list[dict]:
        """topic 和 entity 在 KITE 的数据模型里没有直接的 schema 关联——两个都
        是挂在 fact 上的独立分类维度，只在同一条 fact 上"共现"。这里把共现
        次数按 (topic, entity) 聚合成边，主题地图拿这个把两类节点连起来，
        不然图上主题和实体各画各的，看不出关系（用户反馈原话："这样展示
        两个，很迷糊"）。
        """
        store, _vocab = self._index()
        counts: dict[tuple[str, str], int] = {}
        spk = {c for c, e in _vocab.entities.items() if is_speaker_tag(c) or is_speaker_tag(getattr(e, "name", "") or "")}
        for f in store.facts.values():
            for t in f.topics:
                for e in f.entities:
                    if e in spk:          # 说话人标签不是实体，图上不该有它的边（第 554 轮）
                        continue
                    key = (t, e)
                    counts[key] = counts.get(key, 0) + 1
        return [{"topic": t, "entity": e, "weight": w}
                for (t, e), w in sorted(counts.items())]

    def _fact_dict(self, f) -> dict:
        return {"id": f.id, "text": f.text, "when": f.when, "kind": f.kind,
                "who": f.who, "conf": f.conf, "topics": list(f.topics),
                "entities": list(f.entities), "unit": f.unit}

    def facts_page(self, *, kind: str = "", who: str = "", topic: str = "",
                   entity: str = "", conf_min: str = "", limit: int = 20,
                   offset: int = 0) -> tuple[list[dict], int]:
        """分页 + 过滤。topic 过滤走闭包（含子主题），跟 recall() 的语义一致。"""
        store, vocab = self._index()

        topic_closure: set[str] | None = None
        if topic:
            code = vocab.resolve_topic(topic) or topic
            topic_closure = vocab.downset(code, include_candidates=True) or {code}
        entity_code = vocab.resolve_entity(entity) if entity else ""
        if entity and not entity_code:
            entity_code = entity
        entity_codes: set[str] = set()
        if entity_code:
            from ..kb import entities as entities_mod     # 同一实体的几种写法都算（kb/entities.py）
            entity_codes = set(entities_mod.for_store(store, vocab).members(entity_code))
        conf_floor = CONF_ORDER.get(conf_min, 0) if conf_min else 0

        def match(f) -> bool:
            if kind and f.kind != kind:
                return False
            if who and norm_who(f.who) != norm_who(who):    # speaker a / speaker_a 是同一个人
                return False
            if conf_floor and CONF_ORDER.get(f.conf, 1) < conf_floor:
                return False
            if topic_closure is not None and not (set(f.topics) & topic_closure):
                return False
            if entity_codes and not (entity_codes & set(f.entities)):
                return False
            return True

        rows = sorted((f for f in store.facts.values() if match(f)),
                      key=lambda f: f.when, reverse=True)
        total = len(rows)
        page = rows[offset:offset + limit]
        return [self._fact_dict(f) for f in page], total

    def facts_between(self, date_from: str, date_to: str, limit: int = 400) -> list[dict]:
        """按日期范围取全部 facts（不分页，按时间正序）——摘要生成用。`when` 是
        ISO 日期字符串，字典序比较就是时间序，不用另外解析。"""
        store, _vocab = self._index()
        rows = sorted(
            (f for f in store.facts.values() if date_from <= f.when <= date_to),
            key=lambda f: f.when,
        )
        return [self._fact_dict(f) for f in rows[:limit]]

    def fact_by_id(self, fact_id: str) -> dict | None:
        """按 id 取一条事实。行内出处浮层用。

        找不到返回 None——调用方要据此回 404。**不能返回空壳**：一条指向
        不存在事实的引用是个真问题（模型编的、或者知识库重建过 id 变了），
        静默当成没事等于把它藏起来。
        """
        store, _vocab = self._index()
        fact = store.facts.get(fact_id)
        return self._fact_dict(fact) if fact is not None else None

    def fact_sources(self, fact_id: str) -> list[dict]:
        """一条 fact 的原始出处，带 unit/日期/说话人——跟 source_lines() 的区别是
        这里给结构化字段，不是纯文本，方便前端做「fact -> 原始行」的证据回溯。"""
        store, _vocab = self._index()
        fact = store.facts.get(fact_id)
        if not fact:
            return []
        out = []
        for line_id in fact.src:
            line = store.lines.get(line_id)
            if line is not None:
                out.append({"id": line.id, "unit": line.unit, "date": line.unit_date,
                           "who": line.who, "text": line.text})
        return out

    def timeline(self) -> list[dict]:
        """按日期聚合 session（unit）数与 fact 数，供时间线视图用。"""
        store, _vocab = self._index()
        buckets: dict[str, dict] = {}
        for u in store.units.values():
            if not u.date:
                continue
            buckets.setdefault(u.date, {"date": u.date, "units": 0, "facts": 0})["units"] += 1
        for f in store.facts.values():
            if not f.when:
                continue
            buckets.setdefault(f.when, {"date": f.when, "units": 0, "facts": 0})["facts"] += 1
        return sorted(buckets.values(), key=lambda b: b["date"])

    def add_topic(self, code: str, *, parent: str = "", aliases: list[str] | None = None) -> dict:
        """手动新建一个 topic——主题地图里"新建主题"用。

        跟模型的 propose_topic() 不一样：那条路径是给 LLM 抽取时用的，带
        admission budget 防模型瞎造（约束 10 那个坑），状态先落 candidate 等
        promote。这里是用户自己点的，直接给 canonical，不用等门槛。

        没走 Memory.remember()——那条路径必须绑一个 session，为了改 vocab
        硬造一条空会话既污染时间线又多余。改成直接操作 Vocab 再用
        Vocab.to_xml() 序列化写回，只换 <vocab> 子树，<timeline> 原样不动。
        写入仍然全程持锁（约束 1），落盘前 Store.load() 验证一遍能读回来，
        跟 KITE 自己 storage.append_session() 的做法一致（没直接复用它，因为
        它的签名绑死了 session/facts 参数）。
        """
        self.ensure()
        new_code = norm_code(code)
        if not new_code:
            raise ValueError("主题名不能为空")

        with write_lock(self.path):
            _store, vocab = Store.load([str(self.path)])
            if new_code in vocab.topics:
                raise ValueError(f"主题已存在：{new_code}")
            parent_code = ""
            if parent:
                parent_code = vocab.resolve_topic(parent) or ""
                if not parent_code:
                    raise ValueError(f"父主题不存在：{parent}")

            topic = Topic(new_code, parents={parent_code} if parent_code else set(),
                          status="canonical")
            for alias in (aliases or []):
                a = norm_code(alias)
                if a and a != new_code:
                    topic.aliases.add(a)
            vocab.topics[new_code] = topic
            for alias in topic.aliases:
                vocab._alias_t[alias] = new_code

            tree = ET.parse(self.path)
            root = tree.getroot()
            prior_vocab_el = root.find("vocab")
            new_vocab_el = vocab.to_xml()
            if prior_vocab_el is None:
                root.insert(0, new_vocab_el)
            else:
                root.insert(list(root).index(prior_vocab_el), new_vocab_el)
                root.remove(prior_vocab_el)
            ET.indent(tree, space="  ")

            fd, tmp_name = tempfile.mkstemp(
                suffix=".xml", prefix=f".{self.path.stem}-", dir=self.path.parent)
            os.close(fd)
            tmp_path = Path(tmp_name)
            try:
                tree.write(tmp_path, encoding="utf-8", xml_declaration=True)
                Store.load([str(tmp_path)])  # refuse to publish an unreadable file
                os.replace(tmp_path, self.path)
            finally:
                tmp_path.unlink(missing_ok=True)

        self.invalidate()
        return {"code": new_code, "parents": sorted(topic.parents), "status": "canonical",
                "aliases": sorted(topic.aliases), "fact_count": 0}

    # ------------------------------------------------------------ 入库（走 LLM，慢）

    def remember(self, messages: list[dict], *, session_id: str,
                 date: str | None = None, title: str = "",
                 profile=None) -> int:
        """把一段内容抽成 fact 存进 codebook。调用方负责放到后台执行。

        写入全程持有该 codebook 的独占锁 —— KITE 的 ``remember()`` 全量重写
        XML 且不加锁，并发写会互相覆盖造成静默的数据丢失（见 kite_writer）。

        ``Memory.load()`` 必须放在锁**内**：它把整个 XML 读进内存，
        ``remember()`` 再基于这份快照重写全文。在锁外加载等于拿到一份可能
        过期的快照，写回时会抹掉别人刚提交的 session。
        """
        cfg = store.get_active_llm_config()
        _export_provider_env()
        self.ensure()
        with write_lock(self.path):
            memory = Memory.load(self.path, model=cfg["model"])
            # 换抽取 prompt（面向写作而不是问答）时只能改
            # DEFAULT_MEMORY_PROFILE——``memoket_kite.remember.extract_facts``
            # 把它写死了，没有参数可传。所以在**持锁期间**临时替换、finally
            # 还原。它是进程级全局对象，这样做的前提是同一时刻只有一个
            # remember 在跑，而这正是上面那把独占锁保证的事。
            # 不传 profile 时完全不碰它，既有入库行为一个字节都不变。
            patched = []
            if profile is not None:
                from memoket_kite.defaults import DEFAULT_MEMORY_PROFILE as _P
                for attr in ("EXTRACT_PROMPT", "EXTRACT_PROMPT_NO_FACETS"):
                    patched.append((attr, getattr(_P, attr)))
                    setattr(_P, attr, getattr(profile, attr))
            try:
                facts = memory.remember(messages, session_id=session_id,
                                        date=date, title=title or None)
            finally:
                if patched:
                    from memoket_kite.defaults import DEFAULT_MEMORY_PROFILE as _P
                    for attr, val in patched:
                        setattr(_P, attr, val)
        self.invalidate()
        return len(facts)

    def ask(self, question: str, limit: int = 10) -> tuple[str, list[dict]]:
        """显式提问：走 KITE 原生 planning。

        与 recall() 的取舍：原生 planning 会用 LLM 把问题编译成查询计划，
        能处理 recall() 做不到的意图理解和时序推理（"现在谁负责" 这类需要
        按时间取最新的问题）。代价是本地模型上约 40-50s、3-4 次 LLM 调用。
        所以只用在用户主动提问的路径，写作路径一律走 recall()。

        **模型出错时要说出错，不能说「没记录」**（P9，edge-cases「来龙去脉 × 模型报错」实拍）：
        KITE 的 pipeline 把 provider 异常全吞了（`except Exception` → 词法回退 → 「No information」），
        模型 500 时用户等 3 次调用 × 3 次重试（退避 2s + 4s）≈ 30 秒，然后看到一句
        「知识库里没有跟这段沾边的记录」——那是假的。这里给 provider 装一个观察器：
        第一次失败之后后面的调用直接失败、不再睡退避，跑完若有失败且没有依据就抛
        `ProviderFailed`，路由翻成 502 + 一句人话。
        """
        cfg = store.get_active_llm_config()
        _export_provider_env()
        self.ensure()
        memory = Memory.load(self.path, model=cfg["model"])
        with _watch_provider() as failures:
            result = memory.answer_with_evidence(question, limit=limit)
        # KITE 的 Answer 把依据叫 ``evidence``（Fact 元组）；早期版本叫 ``facts``。
        # 实拍：「来龙去脉」直接 500——AttributeError: 'Answer' object has no attribute
        # 'facts'。两个名字都认，别再跟着上游改名炸一次。
        evidence = getattr(result, "evidence", None)
        if evidence is None:
            evidence = getattr(result, "facts", None) or []
        facts = [{"id": f.id, "text": f.content,
                  "date": getattr(f, "when", ""), "kind": getattr(f, "kind", ""),
                  "sources": [str(x.get("content", "")) if isinstance(x, dict) else str(x)
                              for x in (getattr(f, "sources", None) or [])]}
                 for f in evidence]
        if failures and not facts:
            raise ProviderFailed(failures[0])
        return result.text, facts

    # ------------------------------------------------------------ 实体去重（手动触发）

    def preview_entity_consolidation(self, min_len: int = 5, batch_size: int = 60) -> dict[str, str]:
        """只读预览：算候选、真的跑一遍投票，但改的是 vocab 的深拷贝——
        不碰真实数据、不写文件、不需要拿 write_lock。返回 {loser: winner}
        给调用方（前端/人工）审查用，确认要合并哪些之后再调
        apply_entity_consolidation()，不是自动生效。
        """
        cfg = store.get_active_llm_config()
        _export_provider_env()
        _store, vocab = self._index()
        candidates = vocab.entity_merge_candidates(min_len=min_len)
        staged = copy.deepcopy(vocab)
        return _vote_entity_merges(staged, candidates, cfg["model"], batch_size)

    # ------------------------------------------------------------ 笔记 ↔ 知识库链接层
    #
    # 一篇笔记摄入时的 session 叫 `note-<noteId>-<块号>`（routers/ingest.py），所以
    # 「这篇贡献了哪些事实」= unit 以 `note-<noteId>-` 开头的事实。用户手工加的事实
    # 放在 `note-<noteId>-manual` 这个 session 里：同步（删旧 session 重抽）时它被保留。

    @staticmethod
    def note_prefix(note_id: str) -> str:
        return f"note-{note_id}-"

    def facts_for_prefix(self, prefix: str) -> list[dict]:
        store_, _vocab = self._index()
        rows = [f for f in store_.facts.values() if f.unit.startswith(prefix)]
        rows.sort(key=lambda f: (f.unit, _fact_seq(f.id)))
        out = []
        for f in rows:
            d = self._fact_dict(f)
            d["manual"] = f.unit.endswith("-manual")
            out.append(d)
        return out

    def _rewrite_xml(self, mutate) -> None:
        """锁内改 XML 树、校验能读回来、原子替换。增删改事实都走这一条。"""
        self.ensure()
        with write_lock(self.path):
            tree = ET.parse(self.path)
            root = tree.getroot()
            mutate(root)
            ET.indent(tree, space="  ")
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".xml", prefix=f".{self.path.stem}-",
                dir=self.path.parent, delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                tree.write(handle, encoding="utf-8", xml_declaration=True)
            try:
                _verify_loadable(temp_path)
            except Exception:
                temp_path.unlink(missing_ok=True)
                raise
            os.replace(temp_path, self.path)
        self.invalidate()

    def delete_facts(self, ids: set[str]) -> int:
        removed = 0

        def mutate(root):
            nonlocal removed
            for sess in root.iter("session"):
                for fe in list(sess.findall("fact")):
                    if fe.get("id") in ids:
                        sess.remove(fe)
                        removed += 1
        if ids:
            self._rewrite_xml(mutate)
        return removed

    def set_fact_text(self, fact_id: str, text: str) -> bool:
        hit = False

        def mutate(root):
            nonlocal hit
            for fe in root.iter("fact"):
                if fe.get("id") == fact_id:
                    fe.text = text
                    hit = True
        self._rewrite_xml(mutate)
        return hit

    def set_fact_attr(self, fact_id: str, name: str, value: str) -> bool:
        """给一条事实加 / 改一个自定义属性（loader 忽略不认识的属性，所以安全）。
        用来记「被哪条取代」：superseded_by。"""
        hit = False

        def mutate(root):
            nonlocal hit
            for fe in root.iter("fact"):
                if fe.get("id") == fact_id:
                    if value:
                        fe.set(name, value)
                    elif name in fe.attrib:
                        del fe.attrib[name]
                    hit = True
        self._rewrite_xml(mutate)
        return hit

    def fact_attrs(self, name: str) -> dict[str, str]:
        """所有带这个自定义属性的事实：id → 值。按 mtime 缓存，跟索引一样。"""
        self.ensure()
        key = f"{self.path}#{name}"
        mtime = self.path.stat().st_mtime
        self._last_used[str(self.path)] = time.time()
        hit = self._cache.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
        out: dict[str, str] = {}
        try:
            for _ev, el in ET.iterparse(self.path):
                if el.tag == "fact" and el.get(name):
                    out[el.get("id") or ""] = el.get(name) or ""
        except ET.ParseError:
            out = {}
        self._cache[key] = (mtime, out, None)
        return out

    def add_manual_fact(self, session_id: str, text: str, *, date: str, title: str,
                        who: str = "") -> dict:
        """往 `<session_id>` 里手工加一条事实；session 不在就建（一条 line 当出处，
        loader 要求 fact.src 指向存在的 line）。返回新事实。"""
        new_id = ""

        def mutate(root):
            nonlocal new_id
            timeline = root.find("timeline")
            if timeline is None:
                timeline = ET.SubElement(root, "timeline")
            sess = next((s for s in timeline.findall("session") if s.get("id") == session_id), None)
            if sess is None:
                sess = ET.SubElement(timeline, "session", {"id": session_id, "t": "", "date": date,
                                                            "dur": "", "title": title})
            n = len(sess.findall("fact")) + 1
            line_id = f"{session_id}L{n}"
            fe = ET.SubElement(sess, "fact", {"id": f"{session_id}F{n}", "kind": "statement", "who": who,
                                              "t": "", "conf": "high", "topics": "", "entities": "",
                                              "src": line_id, "manual": "1"})
            fe.text = text
            le = ET.SubElement(sess, "line", {"id": line_id, "who": who or "user", "t": ""})
            le.text = text
            new_id = fe.get("id")
        self._rewrite_xml(mutate)
        return self.fact_by_id(new_id) or {"id": new_id, "text": text}

    def remove_sessions(self, prefix: str, keep_suffix: str = "-manual") -> int:
        """删掉 id 以 prefix 开头的 session（连同里面的事实和出处行）。手工加的那个
        session（`…-manual`）留着。同步 = 删旧的再重抽。"""
        removed = 0

        def mutate(root):
            nonlocal removed
            timeline = root.find("timeline")
            if timeline is None:
                return
            for sess in list(timeline.findall("session")):
                sid = sess.get("id") or ""
                if sid.startswith(prefix) and not (keep_suffix and sid.endswith(keep_suffix)):
                    timeline.remove(sess)
                    removed += 1
        self._rewrite_xml(mutate)
        return removed

    def apply_entity_consolidation(self, rewrites: dict[str, str]) -> Path:
        """真的执行：备份 codebook.xml，把 rewrites 应用到真实 vocab 和
        真实 fact 的 entities 属性上，原子写回。

        rewrites 必须是 preview_entity_consolidation() 刚返回的那份、经过
        人工确认的结果——不在这里重新跑一次投票，因为投票本身有概率性
        （见 TRACELOG），用户审查过的预览应该就是最终生效的那份，不是
        "大概"。真正写入前对每一条 rewrite 重新核实 loser/winner 是不是
        还存在于当前 vocab（防的是预览和执行之间又有新内容入库、把还没
        见过的实体编码合并没了）。

        写入流程仿照 KITE 自己 append_session() 的原子写模式（临时文件+
        校验能读回来+原子替换），但 append_session() 是给"追加新 session"
        设计的，没法直接复用——这条路径是这次专门为实体合并写的，全库
        没有任何先例可以照抄，所以先备份一份原文件，写完之后原文件不会
        被直接覆盖丢失，出问题能马上恢复。
        """
        self.ensure()
        with write_lock(self.path):
            backup_path = self.path.with_name(f"{self.path.stem}.bak-{int(time.time())}{self.path.suffix}")
            shutil.copy2(self.path, backup_path)

            tree = ET.parse(self.path)
            root = tree.getroot()
            _store, vocab = Store.load([str(self.path)])  # 锁内重新加载，保证不是过期快照

            applied: dict[str, str] = {}
            for loser, winner in rewrites.items():
                if loser in vocab.entities and winner in vocab.entities:
                    applied.update(vocab.merge_entities([loser], winner))

            for fact in root.iter("fact"):
                original_codes = (fact.get("entities") or "").split()
                rewritten_codes = []
                for code in original_codes:
                    new_code = applied.get(code, code)
                    if new_code not in rewritten_codes:
                        rewritten_codes.append(new_code)
                fact.set("entities", " ".join(rewritten_codes))

            new_vocab_el = vocab.to_xml()
            prior_vocab_el = root.find("vocab")
            if prior_vocab_el is not None:
                root.insert(list(root).index(prior_vocab_el), new_vocab_el)
                root.remove(prior_vocab_el)
            else:
                root.insert(0, new_vocab_el)

            ET.indent(tree, space="  ")
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".xml", prefix=f".{self.path.stem}-",
                dir=self.path.parent, delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                tree.write(handle, encoding="utf-8", xml_declaration=True)
            _verify_loadable(temp_path)  # 写完先校验能读回来，读不回来就不替换真文件
            os.replace(temp_path, self.path)

        self.invalidate()
        return backup_path

    def stats(self) -> dict:
        store, vocab = self._index()
        dates = sorted(u.date for u in store.units.values() if u.date)
        return {
            "facts": len(getattr(store, "facts", {}) or {}),
            "topics": len(vocab.topics),
            # 说话人标签（speaker b）在词表里也是实体，树 / 图 / 召回都不算它——这里数出来的「1223 个实体」也别算（第 552 轮）
            "entities": sum(1 for c, e in vocab.entities.items() if not is_speaker_tag(c) and not is_speaker_tag(getattr(e, "name", ""))),
            "units": len(getattr(store, "units", {}) or {}),
            "lines": len(getattr(store, "lines", {}) or {}),
            "speakers": sorted(getattr(store, "speakers", set()) or []),
            "start_date": dates[0] if dates else None,
            "end_date": dates[-1] if dates else None,
            "codebook": str(self.path),
        }

