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

import os
import re
import time
from pathlib import Path

from memoket_kite import Memory
from memoket_kite.core.algebra import CONF_ORDER, Store, execute_plan

from .config import get_settings
from .kite_writer import write_lock

EMPTY_CODEBOOK = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<codebook id="{uid}" speakers="user">\n'
    "  <vocab/>\n"
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
    """
    s = get_settings()
    os.environ["OPENAI_API_KEY"] = s.llm_api_key
    os.environ["OPENAI_BASE_URL"] = s.llm_base_url


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
        """符号检索。返回 (fact 行, 命中的表层词, 耗时毫秒)。"""
        t0 = time.perf_counter()
        store, vocab = self._index()
        topics, entities, surfaces = self._match_vocab(query, vocab)

        queries = []
        if topics or entities:
            queries.append({
                "select": "facts",
                "where": {"topics": topics, "entities": entities},
                "pipe": [{"op": "sort", "key": "t", "desc": True},
                         {"op": "head", "n": limit}],
            })
        # 词表没命中时退回词法检索，否则新用户永远召回为空
        for term in self._candidate_terms(query)[:3]:
            queries.append({
                "select": "facts",
                "where": {"grep": term},
                "pipe": [{"op": "sort", "key": "t", "desc": True},
                         {"op": "head", "n": limit}],
            })

        facts: list[dict] = []
        if queries:
            rows, _trace = execute_plan(store, vocab, {"queries": queries[:3]},
                                        budget=limit)
            facts = [r for r in rows if r.get("type") == "fact"]

        if not facts:
            facts = self._recall_via_lines(store, vocab, query, limit)
            surfaces = surfaces + self._cjk_terms(query)[:3]

        return facts[:limit], surfaces, (time.perf_counter() - t0) * 1000

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
        """topic 树。parents 字段构成层级——前端自己拼树，不在这里嵌套。"""
        _store, vocab = self._index()
        return [
            {"code": t.code, "parents": sorted(t.parents), "status": t.status,
             "aliases": sorted(t.aliases)}
            for t in sorted(vocab.topics.values(), key=lambda t: t.code)
        ]

    def entities(self) -> list[dict]:
        _store, vocab = self._index()
        return [
            {"code": e.code, "name": e.name, "type": e.etype,
             "aliases": sorted(e.aliases), "relations": sorted(e.rels)}
            for e in sorted(vocab.entities.values(), key=lambda e: e.code)
        ]

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

    # ------------------------------------------------------------ 入库（走 LLM，慢）

    def remember(self, messages: list[dict], *, session_id: str,
                 date: str | None = None, title: str = "") -> int:
        """把一段内容抽成 fact 存进 codebook。调用方负责放到后台执行。

        写入全程持有该 codebook 的独占锁 —— KITE 的 ``remember()`` 全量重写
        XML 且不加锁，并发写会互相覆盖造成静默的数据丢失（见 kite_writer）。

        ``Memory.load()`` 必须放在锁**内**：它把整个 XML 读进内存，
        ``remember()`` 再基于这份快照重写全文。在锁外加载等于拿到一份可能
        过期的快照，写回时会抹掉别人刚提交的 session。
        """
        s = get_settings()
        _export_provider_env()
        self.ensure()
        with write_lock(self.path):
            memory = Memory.load(self.path, model=s.kite_extract_model)
            facts = memory.remember(messages, session_id=session_id,
                                    date=date, title=title or None)
        self.invalidate()
        return len(facts)

    def ask(self, question: str, limit: int = 10) -> tuple[str, list[dict]]:
        """显式提问：走 KITE 原生 planning。

        与 recall() 的取舍：原生 planning 会用 LLM 把问题编译成查询计划，
        能处理 recall() 做不到的意图理解和时序推理（"现在谁负责" 这类需要
        按时间取最新的问题）。代价是本地模型上约 40-50s、3-4 次 LLM 调用。
        所以只用在用户主动提问的路径，写作路径一律走 recall()。
        """
        s = get_settings()
        _export_provider_env()
        self.ensure()
        memory = Memory.load(self.path, model=s.kite_extract_model)
        result = memory.answer_with_evidence(question, limit=limit)
        facts = [{"id": f.id, "text": f.content,
                  "date": getattr(f, "when", ""), "kind": getattr(f, "kind", ""),
                  "sources": [str(x.get("content", "")) for x in (f.sources or [])]}
                 for f in (result.facts or [])]
        return result.text, facts

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
