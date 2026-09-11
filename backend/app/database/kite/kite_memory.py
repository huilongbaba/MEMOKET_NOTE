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
import os
import re
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
from . import kite_entity_candidates, kite_extract_profile
from ..kb import search
from ...util.config import get_settings
from .kite_writer import write_lock

kite_extract_profile.install()
kite_entity_candidates.install()

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

    def _index(self):
        """加载符号索引，按 mtime 缓存 —— 每次请求重新解析 XML 是浪费。"""
        self.ensure()
        mtime = self.path.stat().st_mtime
        hit = self._cache.get(str(self.path))
        if hit and hit[0] == mtime:
            return hit[1], hit[2]
        store, vocab = Store.load([str(self.path)])
        self._cache[str(self.path)] = (mtime, store, vocab)
        return store, vocab

    def invalidate(self) -> None:
        self._cache.pop(str(self.path), None)

    # ------------------------------------------------------------ 检索（零 LLM）

    @staticmethod
    def _candidate_terms(text: str) -> list[str]:
        """英文候选词。"""
        words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}", text.lower())
        return [w for w in words if w not in STOPWORDS][:12]

    @staticmethod
    def _cjk_terms(text: str) -> list[str]:
        """中文候选词：没有空格可切，用 2-3 字滑窗生成 n-gram。

        KITE 的抽取提示词是英文的，中文输入抽出的 fact 可能是英文，符号通道
        匹配不上。但原始 <line> 保留了中文原文，这些 n-gram 拿去 grep 原始行
        仍然能命中。

        两个要点：
        1. **从最靠近光标的片段开始** —— 续写时正文尾部才是相关的。
        2. **按片段轮转取样** —— 逐段生成会让第一个长片段吃光配额，
           后面真正有信息量的词（"后端准备用"）永远进不了候选。
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

        out: list[str] = []
        depth = 0
        while len(out) < 16 and any(depth < len(g) for g in per_run):
            for grams in per_run:
                if depth < len(grams) and grams[depth] not in out:
                    out.append(grams[depth])
                    if len(out) >= 16:
                        break
            depth += 1
        return out

    def _match_vocab(self, text: str, vocab) -> tuple[list[dict], list[str], list[str]]:
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
            if code and code not in entities:
                entities.append(code)
                hit_surfaces.append(term)

        for code, topic in vocab.topics.items():
            if getattr(topic, "status", "") == "deprecated":
                continue
            for surface in {code, *getattr(topic, "aliases", set())}:
                sl = str(surface).replace("_", " ").lower()
                if len(sl) >= 2 and sl in lowered:
                    if not any(t["code"] == code for t in topics):
                        topics.append({"code": code, "closure": True})
                        hit_surfaces.append(sl)
                    break

        for code, ent in vocab.entities.items():
            surfaces = {code, getattr(ent, "name", ""), *getattr(ent, "aliases", set())}
            for surface in surfaces:
                sl = str(surface).replace("_", " ").lower()
                if len(sl) >= 2 and sl in lowered:
                    if code not in entities:
                        entities.append(code)
                        hit_surfaces.append(sl)
                    break

        return topics[:4], entities[:4], hit_surfaces

    def recall(self, query: str, limit: int = 8) -> tuple[list[dict], list[str], float]:
        """符号检索。返回 (fact 行, 命中的表层词, 耗时毫秒)。

        **先撒网再排序**，不是「命中主题后按时间取前 8」。原来那个写法等于
        「这个主题下最近的 8 条」，跟查询内容无关——实测拿一条事实自己的原文
        去查，只有 22% 能召回它自己、38% 能召回同主题的东西。撒网 + 按词面
        重排之后是 90% / 97%，仍然零 LLM 调用、仍然几毫秒。判据和量出来的
        数字见 ``kb/search.py``。
        """
        t0 = time.perf_counter()
        store, vocab = self._index()
        _topics, _entities, surfaces = self._match_vocab(query, vocab)

        queries = search.plan(self, query, vocab)
        facts: list[dict] = []
        if queries:
            rows, _trace = execute_plan(store, vocab, {"queries": queries},
                                        budget=search.POOL * 2)
            facts = [r for r in rows if r.get("type") == "fact"]
        facts = search.rank(facts, query, self, store, limit=limit)

        if not facts:
            facts = self._recall_via_lines(store, vocab, query, limit)
            surfaces = surfaces + self._cjk_terms(query)[:3]
        else:
            surfaces = surfaces + [t for t in search.matched_terms(
                facts, query, self, store) if t not in surfaces]

        return facts[:limit], surfaces, (time.perf_counter() - t0) * 1000

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

        units: list[str] = []
        for term in terms[:12]:
            rows, _t = execute_plan(
                store, vocab,
                {"queries": [{"select": "lines", "where": {"grep": term},
                              "pipe": [{"op": "head", "n": limit}]}]},
                budget=limit)
            for r in rows:
                unit = r.get("unit")
                if unit and unit not in units:
                    units.append(unit)
            if len(units) >= 4:
                break

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
        for f in store.facts.values():
            for t in f.topics:
                for e in f.entities:
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
        conf_floor = CONF_ORDER.get(conf_min, 0) if conf_min else 0

        def match(f) -> bool:
            if kind and f.kind != kind:
                return False
            if who and f.who != who:
                return False
            if conf_floor and CONF_ORDER.get(f.conf, 1) < conf_floor:
                return False
            if topic_closure is not None and not (set(f.topics) & topic_closure):
                return False
            if entity_code and entity_code not in f.entities:
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
        """
        cfg = store.get_active_llm_config()
        _export_provider_env()
        self.ensure()
        memory = Memory.load(self.path, model=cfg["model"])
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
            "entities": len(vocab.entities),
            "units": len(getattr(store, "units", {}) or {}),
            "lines": len(getattr(store, "lines", {}) or {}),
            "speakers": sorted(getattr(store, "speakers", set()) or []),
            "start_date": dates[0] if dates else None,
            "end_date": dates[-1] if dates else None,
            "codebook": str(self.path),
        }

