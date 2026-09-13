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
    # 显示名 / 大小写 / 空格写法都能落到同一个实体
    assert pages.entity_page(mem, "Acme")["code"] == "acme"
    facts = pages.entity_page(mem, "acme")["facts"]          # 按时间倒序：f2（只有 acme）在前
    assert [f["entity_names"] for f in facts] == [["Acme"], ["Acme", "Bob"]]
    assert pages.entity_page(mem, "ACME")["code"] == "acme"
    vocab_e = mem._index()[1].entities
    vocab_e["speaker_a"] = type(vocab_e["bob"])("speaker_a", etype="person", name="Speaker A")
    assert pages.entity_page(mem, "Speaker A")["code"] == "speaker_a"


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


def test_各页都带取代与合并标注(mem, monkeypatch):
    monkeypatch.setattr(mem, "fact_attrs", lambda name: {"superseded_by": {"f1": "f2"}, "merged": {"f1": "1"}}.get(name, {}))
    for rows in (pages.topic_page(mem, "work")["facts"], pages.unit_page(mem, "s1")["facts"],
                 pages.day_facts(mem, "2026-01-05"), pages.entity_page(mem, "acme")["facts"]):
        f1 = next(r for r in rows if r["id"] == "f1")
        assert f1["superseded_by"] == "f2" and f1["merged"] is True
        f2 = next((r for r in rows if r["id"] == "f2"), None)   # 某一天那页没有 f2
        assert f2 is None or "superseded_by" not in f2


def test_按月是连续的日历月_错抽的远古日期不拉长横轴(mem):
    store, _ = mem._index()
    store.facts["old"] = _fact("old", "错抽", "2005-11-03", topics=["work"])
    store.facts["mid"] = _fact("mid", "x", "2025-10-01", topics=["work"])
    rows = pages.topic_page(mem, "work")["months"]
    assert [r["month"] for r in rows] == ["2025-10", "2025-11", "2025-12", "2026-01"]   # 开头空月砍掉，2005 不进来
    assert [r["facts"] for r in rows] == [1, 0, 0, 2]                                   # 中间空月补 0


def test_同一份材料切成几段_标题带段号(mem):
    from memoket_kite.core.algebra import Unit
    from app.database.kb.units import part_labels
    store, _ = mem._index()
    for i in range(3):
        store.units[f"obsidian-doc1-{i}"] = Unit(id=f"obsidian-doc1-{i}", date="2026-09-12", t="", title="战略讨论", dur_min=0, n_lines=1)
    labels = part_labels(list(store.units.values()))
    assert labels["obsidian-doc1-0"] == "战略讨论（1/3）" and labels["obsidian-doc1-2"] == "战略讨论（3/3）"
    assert labels["s1"] == "周会"                      # 单段的照原样
    d = pages.dashboard(mem)
    assert any(r["title"] == "战略讨论（3 段）" for r in d["recent_units"])   # 首页按材料列（第 267 轮）
    up = pages.unit_page(mem, "obsidian-doc1-1")
    assert up["part_index"] == 2 and up["part_total"] == 3 and [x["id"] for x in up["parts"]] == ["obsidian-doc1-0", "obsidian-doc1-1", "obsidian-doc1-2"]
    assert pages.unit_page(mem, "obsidian-doc1-1")["title"] == "战略讨论（2/3）"


def test_首页主题计数是不同事实的条数(mem):
    """第 207 轮：一条事实同时挂父主题和子主题，首页闭包计数把它加了两次，跟主题页对不上。"""
    store, vocab = mem._index()
    root = next(t.code for t in vocab.topics.values() if not any(p in vocab.topics for p in t.parents))
    kids = [t.code for t in vocab.topics.values() if root in t.parents]
    if not kids:
        import pytest; pytest.skip("夹具里没有子主题")
    store.facts["dup1"] = _fact("dup1", "两个主题都挂", "2026-01-05", topics=[root, kids[0]])
    d = pages.dashboard(mem)
    n_dash = next(t["facts"] for t in d["top_topics"] if t["code"] == root)
    assert n_dash == pages.topic_page(mem, root, limit=1, offset=0)["facts_total"]


def test_树上的主题计数也是不同事实的条数(mem):
    from app.database.kb import virtual_tree
    store, vocab = mem._index()
    root = next(t.code for t in vocab.topics.values() if not any(p in vocab.topics for p in t.parents))
    kids = [t.code for t in vocab.topics.values() if root in t.parents]
    if not kids:
        import pytest; pytest.skip("夹具里没有子主题")
    store.facts["dup2"] = _fact("dup2", "两个主题都挂", "2026-01-05", topics=[root, kids[0]])
    row = next(r for r in virtual_tree.build(mem) if r["note_id"] == f"kb:topic:{root}")
    assert row["fact_count"] == pages.topic_page(mem, root, limit=1, offset=0)["facts_total"]


def test_说话人不同写法算同一个人(mem):
    """第 217 轮：首页 speaker a 6185 和 speaker_a 1106 并排；事实表按说话人筛只能筛到一种写法。"""
    store, _ = mem._index()
    store.facts["w1"] = _fact("w1", "甲说的", "2026-01-05", who="speaker_a")
    store.facts["w2"] = _fact("w2", "甲又说", "2026-01-06", who="speaker a")
    store.facts["w3"] = _fact("w3", "甲再说", "2026-01-07", who="Speaker A")
    sp = {s["who"]: s["facts"] for s in pages.dashboard(mem)["speakers"]}
    assert sum(1 for k in sp if k.lower().replace("_", " ") == "speaker a") == 1
    assert [v for k, v in sp.items() if k.lower().replace("_", " ") == "speaker a"] == [3]
    rows, total = mem.facts_page(who="speaker a", limit=50, offset=0)[:2]
    assert {r["id"] for r in rows} >= {"w1", "w2", "w3"}


def test_事实表和单条事实都带实体显示名(mem, monkeypatch, tmp_path):
    """第 275 轮实拍：事实表卡片的实体 chip 显示代码 facebook，首页 / 筛选框显示 Facebook。"""
    from fastapi.testclient import TestClient
    from app.database import store
    from app.database.kite import kite_memory
    from app.main import app
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    monkeypatch.setattr(kite_memory, "UserMemory", lambda user: mem)
    from app.routers import memory as memory_router
    monkeypatch.setattr(memory_router, "UserMemory", lambda user: mem)
    with TestClient(app, headers={"X-User-Id": "u"}) as c:
        rows = c.get("/api/memory/facts", params={"entity": "acme", "limit": 5}).json()["facts"]
        assert rows and rows[0]["entity_names"] and rows[0]["entity_names"][rows[0]["entities"].index("acme")] == "Acme"
        one = c.get(f"/api/memory/facts/{rows[0]['id']}").json()
        assert one["entity_names"] == rows[0]["entity_names"]


def test_没抽出事实的会议页带原话(mem):
    """第 287 轮：零事实的段页面只有一句「没有事实」。"""
    from memoket_kite.core.algebra import Line, Unit
    store, _ = mem._index()
    store.units["s-empty"] = Unit(id="s-empty", date="2026-03-12", t="", title="短录音", dur_min=0, n_lines=1)
    store.lines["ln-empty"] = Line(id="ln-empty", unit="s-empty", unit_date="2026-03-12", who="A", text="就说了一句")
    page = pages.unit_page(mem, "s-empty")
    assert page["facts_total"] == 0 and page["lines"] == [{"who": "A", "text": "就说了一句"}]
    assert pages.unit_page(mem, "s1")["lines"] == []


def test_实体页_树_事实表都按组合并(mem):
    from app.database.kb import pages, virtual_tree
    store, vocab = mem._index()
    acme = vocab.entities["acme"]
    vocab.entities["acme_inc"] = type(acme)(code="acme_inc", name="ACME", etype=acme.etype, aliases=set(), rels=set()) if hasattr(acme, "rels") else acme
    f = next(iter(store.facts.values()))
    store.facts["f-dup"] = type(f)(**{**f.__dict__, "id": "f-dup", "entities": ["acme_inc"], "text": "另一种写法"})
    store.facts["f-both"] = type(f)(**{**f.__dict__, "id": "f-both", "entities": ["acme", "acme_inc"], "text": "两种写法都挂"})
    page = pages.entity_page(mem, "acme_inc")
    assert page["code"] == "acme" and "另一种写法" in [x["text"] for x in page["facts"]] and page["variants"] == ["ACME"]
    rows = [r for r in virtual_tree.build(mem) if r["note_id"].startswith("kb:entity:acme")]
    assert [r["note_id"] for r in rows] == ["kb:entity:acme"] and rows[0]["fact_count"] == page["facts_total"]
    assert "ACME" in rows[0]["preview"]
    got, total = mem.facts_page(entity="acme_inc", limit=50)
    assert total == page["facts_total"] and any(r["id"] == "f-dup" for r in got)
    kids = virtual_tree.children(mem, "kb:entity:acme")
    assert any(k["note_id"] == "kb:fact:f-dup" for k in kids)
