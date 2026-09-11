"""知识库各节点打开之后的页面数据（docs/kb-experience-plan.md §3）。夹具跟
test_kb_virtual_tree 一样手搭 Store/Vocab。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memoket_kite.core.algebra import FactRecord, Store, Unit  # noqa: E402
from memoket_kite.core.vocab import Entity, Topic, Vocab  # noqa: E402

from app.database.kb import pages  # noqa: E402
from app.database.kite.kite_memory import UserMemory  # noqa: E402


def _fact(id, text, when, *, topics=(), entities=(), unit="s1", who="user", kind="plan"):
    return FactRecord(id=id, unit=unit, unit_date=when, t=when, kind=kind, who=who,
                      conf="high", topics=tuple(topics), entities=tuple(entities), src=(), text=text)


@pytest.fixture()
def mem(monkeypatch):
    store, vocab = Store(), Vocab()
    vocab.topics["work"] = Topic("work", parents=set(), status="canonical", aliases={"工作"})
    vocab.topics["hiring"] = Topic("hiring", parents={"work"}, status="canonical")
    vocab.topics["life"] = Topic("life", parents=set(), status="canonical")
    vocab.entities["acme"] = Entity("acme", etype="org", name="Acme", rels={("employs", "bob")})
    vocab.entities["bob"] = Entity("bob", etype="person", name="Bob")
    store.units["s1"] = Unit(id="s1", date="2026-01-05", t="", title="周会", dur_min=0, n_lines=1)
    store.units["s2"] = Unit(id="s2", date="2026-02-10", t="", title="", dur_min=0, n_lines=1)
    store.facts["f1"] = _fact("f1", "招人", "2026-01-05", topics=["hiring"], entities=["acme", "bob"])
    store.facts["f2"] = _fact("f2", "交付", "2026-01-06", topics=["work"], entities=["acme"], who="alice", kind="decision")
    store.facts["f3"] = _fact("f3", "跑步", "2026-02-10", topics=["life"], unit="s2")
    for i in range(14):   # 14 个月，验证首页只给近 12 个
        store.facts[f"m{i}"] = _fact(f"m{i}", "x", f"2025-{(i % 12) + 1:02d}-01" if i < 12 else f"2024-0{i - 11}-01",
                                    topics=["life"], unit="s2")
    m = UserMemory("pages-test")
    monkeypatch.setattr(m, "_index", lambda: (store, vocab))
    return m


def test_首页数字和近12个月(mem):
    d = pages.dashboard(mem)
    assert d["stats"]["facts"] == 17 and d["stats"]["topics"] == 3 and d["stats"]["entities"] == 2
    assert d["stats"]["start_date"] == "2024-01-01" and d["stats"]["end_date"] == "2026-02-10"
    assert len(d["months"]) == 12 and d["months"][-1] == {"month": "2026-02", "facts": 1}


def test_首页主题Top只看一级且用闭包计数(mem):
    d = pages.dashboard(mem)
    codes = [t["code"] for t in d["top_topics"]]
    assert "hiring" not in codes
    work = next(t for t in d["top_topics"] if t["code"] == "work")
    assert work["facts"] == 2 and work["children"] == 1     # f1 在 hiring，算进 work


def test_首页实体Top和最近会议(mem):
    d = pages.dashboard(mem)
    assert d["top_entities"][0] == {"code": "acme", "name": "Acme", "facts": 2}
    assert d["recent_units"][0]["id"] == "s2" and d["recent_units"][1]["title"] == "周会"
    assert d["recent_units"][1]["facts"] == 2
    assert {k["kind"] for k in d["kinds"]} == {"plan", "decision"}


def test_主题页含子主题共现实体和月度(mem):
    p = pages.topic_page(mem, "work")
    assert p["aliases"] == ["工作"] and p["facts_total"] == 2
    assert p["children"] == [{"code": "hiring", "facts": 1}]
    assert p["entities"][0]["code"] == "acme" and p["entities"][0]["facts"] == 2
    assert p["months"] == [{"month": "2026-01", "facts": 2}]
    assert [f["id"] for f in p["facts"]] == ["f2", "f1"], "新的在前"


def test_主题页分页与不存在(mem):
    p = pages.topic_page(mem, "work", limit=1, offset=1)
    assert p["facts_total"] == 2 and [f["id"] for f in p["facts"]] == ["f1"]
    assert pages.topic_page(mem, "nope") is None


def test_实体页关系和相关主题(mem):
    p = pages.entity_page(mem, "acme")
    assert p["name"] == "Acme" and p["type"] == "org"
    assert p["relations"] == [{"rel": "employs", "target": "bob", "target_name": "Bob"}]
    assert p["facts_total"] == 2
    assert {t["code"] for t in p["topics"]} == {"hiring", "work"}
    assert pages.entity_page(mem, "nope") is None


def test_时间线月到日(mem):
    tl = pages.timeline(mem)
    jan = next(m for m in tl if m["month"] == "2026-01")
    assert jan["facts"] == 2 and jan["units"] == 1
    assert [d["date"] for d in jan["days"]] == ["2026-01-05", "2026-01-06"]
    assert jan["days"][0] == {"date": "2026-01-05", "facts": 1, "units": 1}
    assert tl[0]["month"] == "2024-01", "按时间正序"


def test_会议页和某一天(mem):
    u = pages.unit_page(mem, "s1")
    assert u["title"] == "周会" and u["facts_total"] == 2 and u["speakers"] == ["alice", "user"]
    assert u["entities"][0]["name"] == "Acme"
    assert pages.unit_page(mem, "nope") is None
    assert [f["id"] for f in pages.day_facts(mem, "2026-01-05")] == ["f1"]
