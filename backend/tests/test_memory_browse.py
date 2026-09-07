"""知识库可视化端点背后的纯逻辑（PLAN.md 第 4 节）：topics/entities/facts 分页
过滤/timeline 聚合。

刻意不走真实 XML —— UserMemory._index() 之后的这些方法只消费 core.Store /
core.Vocab 的公开字段，用真实的 dataclass（FactRecord/Unit/Line/Topic/Entity）
手工搭一个 Store/Vocab 就够了，不用管 XML 解析和 provenance 校验那一层
（那一层已经在 KITE 自己的测试和 test_write_lock.py 里覆盖过）。

    cd backend && python -m pytest tests/test_memory_browse.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memoket_kite.core.algebra import FactRecord, Line, Store, Unit  # noqa: E402
from memoket_kite.core.vocab import Entity, Topic, Vocab  # noqa: E402

from app.kite_memory import UserMemory  # noqa: E402


def _fact(id, text, when, *, kind="pref", who="user", conf="high",
         topics=(), entities=(), unit="s1", src=()):
    return FactRecord(id=id, unit=unit, unit_date=when, t=when, kind=kind, who=who,
                      conf=conf, topics=tuple(topics), entities=tuple(entities),
                      src=tuple(src), text=text)


@pytest.fixture()
def mem(monkeypatch):
    store = Store()
    vocab = Vocab()

    vocab.topics["work"] = Topic("work", parents=set(), status="canonical", aliases={"job"})
    vocab.topics["work_deadline"] = Topic("work_deadline", parents={"work"}, status="canonical")
    vocab.topics["hobby"] = Topic("hobby", parents=set(), status="canonical")

    vocab.entities["acme"] = Entity("acme", etype="org", name="Acme Corp",
                                    aliases={"acme corp"}, rels={("employs", "alice")})

    store.units["s1"] = Unit(id="s1", date="2026-01-01", t="", title="", dur_min=0, n_lines=1)
    store.units["s2"] = Unit(id="s2", date="2026-01-02", t="", title="", dur_min=0, n_lines=1)

    store.lines["l1"] = Line(id="l1", unit="s1", unit_date="2026-01-01", who="user",
                             text="deadline is Friday for Acme")

    store.facts["f1"] = _fact("f1", "deadline Friday", "2026-01-01",
                              kind="pref", who="user", conf="high",
                              topics=["work_deadline"], entities=["acme"],
                              unit="s1", src=["l1"])
    store.facts["f2"] = _fact("f2", "likes hiking", "2026-01-02",
                              kind="pref", who="user", conf="low",
                              topics=["hobby"], entities=[], unit="s2")
    store.facts["f3"] = _fact("f3", "assistant noted context", "2026-01-02",
                              kind="context", who="assistant", conf="med",
                              topics=["work"], entities=["acme"], unit="s2")

    m = UserMemory("browse-test-user")
    monkeypatch.setattr(m, "_index", lambda: (store, vocab))
    return m


def test_topics_lists_all_with_parents_and_aliases(mem):
    out = {t["code"]: t for t in mem.topics()}
    assert out["work_deadline"]["parents"] == ["work"]
    assert out["work"]["aliases"] == ["job"]
    assert set(out) == {"work", "work_deadline", "hobby"}


def test_topics_fact_count_is_exact_match_not_closure(mem):
    # f1 is tagged "work_deadline" directly, f3 is tagged "work" directly --
    # "work" itself must NOT inherit f1's count just because work_deadline is
    # its child (that's facts_page()'s closure behaviour, not topics()'s).
    out = {t["code"]: t for t in mem.topics()}
    assert out["work_deadline"]["fact_count"] == 1
    assert out["work"]["fact_count"] == 1
    assert out["hobby"]["fact_count"] == 1


def test_entities_lists_type_and_relations(mem):
    out = mem.entities()
    assert out == [{
        "code": "acme", "name": "Acme Corp", "type": "org",
        "aliases": ["acme corp"], "relations": [("employs", "alice")],
        "fact_count": 2,  # f1 and f3 both tag entities=["acme"]
    }]


def test_topic_entity_links_aggregates_cooccurrence(mem):
    # f1: topics=["work_deadline"], entities=["acme"] -- f3: topics=["work"], entities=["acme"]
    # f2 has no entities, so it contributes no link.
    links = mem.topic_entity_links()
    assert links == [
        {"topic": "work", "entity": "acme", "weight": 1},
        {"topic": "work_deadline", "entity": "acme", "weight": 1},
    ]


def test_facts_page_sorted_by_when_desc_and_paginated(mem):
    rows, total = mem.facts_page(limit=2, offset=0)
    assert total == 3
    assert [r["id"] for r in rows] == ["f2", "f3"] or [r["id"] for r in rows] == ["f3", "f2"]
    # 都在同一天(2026-01-02)，f1 更早——分页第二页应该是 f1
    rows2, _total = mem.facts_page(limit=2, offset=2)
    assert [r["id"] for r in rows2] == ["f1"]


def test_facts_page_filters_by_kind_and_who(mem):
    rows, total = mem.facts_page(kind="context")
    assert total == 1 and rows[0]["id"] == "f3"

    rows, total = mem.facts_page(who="assistant")
    assert total == 1 and rows[0]["id"] == "f3"


def test_facts_page_filters_by_conf_min(mem):
    # conf_min="med" 应该排除 f2(low)，保留 f1(high)/f3(med)
    rows, total = mem.facts_page(conf_min="med")
    assert total == 2
    assert {r["id"] for r in rows} == {"f1", "f3"}


def test_facts_page_topic_filter_includes_descendants(mem):
    # 按父主题 "work" 过滤应该也命中挂在子主题 "work_deadline" 下的 f1
    rows, total = mem.facts_page(topic="work")
    assert total == 2
    assert {r["id"] for r in rows} == {"f1", "f3"}


def test_facts_page_entity_filter(mem):
    rows, total = mem.facts_page(entity="acme")
    assert total == 2
    assert {r["id"] for r in rows} == {"f1", "f3"}


def test_fact_sources_returns_structured_lines(mem):
    sources = mem.fact_sources("f1")
    assert sources == [{"id": "l1", "unit": "s1", "date": "2026-01-01",
                        "who": "user", "text": "deadline is Friday for Acme"}]


def test_fact_sources_unknown_id_returns_empty(mem):
    assert mem.fact_sources("nope") == []


def test_timeline_aggregates_units_and_facts_by_date(mem):
    buckets = {b["date"]: b for b in mem.timeline()}
    assert buckets["2026-01-01"] == {"date": "2026-01-01", "units": 1, "facts": 1}
    assert buckets["2026-01-02"] == {"date": "2026-01-02", "units": 1, "facts": 2}


# ---------------------------------------------------------------- facts_between (digest)

def test_facts_between_filters_by_inclusive_date_range(mem):
    rows = mem.facts_between("2026-01-01", "2026-01-01")
    assert [r["id"] for r in rows] == ["f1"]


def test_facts_between_sorts_ascending_by_date(mem):
    # facts_page/timeline sort newest-first; digest wants chronological
    # order since it reads like "what happened, in sequence" -- deliberately
    # the other direction.
    rows = mem.facts_between("2026-01-01", "2026-01-02")
    assert [r["id"] for r in rows] == ["f1", "f2", "f3"]
    assert rows[0]["when"] == "2026-01-01"


def test_facts_between_excludes_out_of_range(mem):
    rows = mem.facts_between("2025-01-01", "2025-12-31")
    assert rows == []


def test_facts_between_respects_limit(mem):
    rows = mem.facts_between("2026-01-01", "2026-01-02", limit=1)
    assert len(rows) == 1
