"""知识库虚拟子树（docs/kb-fusion-design.md §3.2）：KITE 的数据呈现成跟
store.tree() 同一种行。夹具跟 test_memory_browse 一样手搭 Store/Vocab。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memoket_kite.core.algebra import FactRecord, Store, Unit  # noqa: E402
from memoket_kite.core.vocab import Entity, Topic, Vocab  # noqa: E402

from app.database.kb import virtual_tree as vt  # noqa: E402
from app.database.kite.kite_memory import UserMemory  # noqa: E402


def _fact(id, text, when, *, topics=(), entities=(), unit="s1"):
    return FactRecord(id=id, unit=unit, unit_date=when, t=when, kind="plan", who="user",
                      conf="high", topics=tuple(topics), entities=tuple(entities),
                      src=(), text=text)


@pytest.fixture()
def mem(monkeypatch):
    store, vocab = Store(), Vocab()
    vocab.topics["work"] = Topic("work", parents=set(), status="canonical")
    vocab.topics["life"] = Topic("life", parents=set(), status="canonical")
    # 两个父主题 = 树上两处 = 克隆
    vocab.topics["balance"] = Topic("balance", parents={"work", "life"}, status="canonical")
    vocab.entities["acme"] = Entity("acme", etype="org", name="Acme")
    vocab.entities["bob"] = Entity("bob", etype="person", name="Bob")
    store.units["s1"] = Unit(id="s1", date="2026-01-05", t="", title="周会", dur_min=0, n_lines=1)
    store.units["s2"] = Unit(id="s2", date="2026-02-10", t="", title="", dur_min=0, n_lines=1)
    store.facts["f1"] = _fact("f1", "交付截止周五", "2026-01-05", topics=["work"], entities=["acme"])
    store.facts["f2"] = _fact("f2", "每周留一天不开会", "2026-02-10", topics=["balance"],
                              entities=["bob"], unit="s2")
    store.facts["f3"] = _fact("f3", "x" * 200, "2026-02-11", topics=["life"], unit="s2")
    m = UserMemory("vt-test")
    monkeypatch.setattr(m, "_index", lambda: (store, vocab))
    return m


def _by_id(rows):
    return {r["note_id"]: r for r in rows}


def test_根和四个分类都在_挂在树根最后(mem):
    rows = vt.build(mem)
    ids = _by_id(rows)
    assert ids["kb"]["parent_note_id"] == "root"
    assert ids["kb"]["position"] == vt.ROOT_POSITION
    assert {r["note_id"] for r in rows if r["parent_note_id"] == "kb"} == {
        "kb:topics", "kb:entities", "kb:timeline", "kb:recent",
        "kb:facts", "kb:graph", "kb:digest"}
    assert ids["kb"]["child_count"] == 7
    # 工具节点没有子节点、排在分类后面
    assert ids["kb:graph"]["child_count"] == 0
    assert ids["kb:graph"]["position"] > ids["kb:recent"]["position"]


def test_行的字段跟真笔记的树行一致(mem):
    from app.routers.schemas import TreeRow
    for r in vt.build(mem):
        TreeRow(**r)   # 少字段/类型不对会抛


def test_多个父主题的主题是克隆(mem):
    rows = [r for r in vt.build(mem) if r["note_id"] == "kb:topic:balance"]
    assert {r["parent_note_id"] for r in rows} == {"kb:topic:work", "kb:topic:life"}
    assert all(r["branch_count"] == 2 for r in rows)
    assert len({r["id"] for r in rows}) == 2, "两条 branch 的 id 得不一样"


def test_主题的子节点数包含子主题和直接事实(mem):
    ids = _by_id(vt.build(mem))
    # work：一个子主题 balance + 一条直接事实 f1
    assert ids["kb:topic:work"]["child_count"] == 2
    assert ids["kb:topic:balance"]["child_count"] == 1


def test_实体按类型分组(mem):
    ids = _by_id(vt.build(mem))
    assert ids["kb:entity:acme"]["parent_note_id"] == "kb:etype:org"
    assert ids["kb:entity:bob"]["parent_note_id"] == "kb:etype:person"
    assert ids["kb:etype:org"]["title"] == "组织"
    assert ids["kb:entity:acme"]["title"] == "Acme"
    assert ids["kb:entity:acme"]["fact_count"] == 1


def test_实体只有一种类型时不分组(mem, monkeypatch):
    store, vocab = mem._index()
    vocab.entities["bob"] = Entity("bob", etype="org", name="Bob")
    ids = _by_id(vt.build(mem))
    assert ids["kb:entity:bob"]["parent_note_id"] == "kb:entities"
    assert not any(k.startswith("kb:etype:") for k in ids)
    assert ids["kb:entities"]["child_count"] == 2


def test_主题的事实数含子主题闭包(mem):
    ids = _by_id(vt.build(mem))
    assert ids["kb:topic:work"]["fact_count"] == 2     # f1 直接 + f2 在 balance
    assert ids["kb:topic:balance"]["fact_count"] == 1
    assert ids["kb"]["fact_count"] == 3


def test_时间线按月_新的在前(mem):
    months = sorted((r for r in vt.build(mem) if r["parent_note_id"] == "kb:timeline"),
                    key=lambda r: r["position"])
    assert [m["title"] for m in months] == ["2026-02", "2026-01"]
    assert months[0]["child_count"] == 2


def test_最近摄入是最近的会议(mem):
    units = sorted((r for r in vt.build(mem) if r["parent_note_id"] == "kb:recent"),
                   key=lambda r: r["position"])
    assert [u["note_id"] for u in units] == ["kb:unit:s2", "kb:unit:s1"]
    assert units[1]["title"] == "2026-01-05 · 周会"
    assert units[0]["title"] == "2026-02-10 · s2", "没标题的会议退回 id"


def test_事实不在分类层里(mem):
    assert not any(r["note_id"].startswith("kb:fact:") for r in vt.build(mem))


def test_展开主题取闭包内的事实(mem):
    rows = vt.children(mem, "kb:topic:work")
    assert [r["note_id"] for r in rows] == ["kb:fact:f2", "kb:fact:f1"], "含子主题，新的在前"
    assert all(r["parent_note_id"] == "kb:topic:work" for r in rows)


def test_展开实体和月份和会议(mem):
    assert [r["note_id"] for r in vt.children(mem, "kb:entity:bob")] == ["kb:fact:f2"]
    assert [r["note_id"] for r in vt.children(mem, "kb:month:2026-01")] == ["kb:fact:f1"]
    assert {r["note_id"] for r in vt.children(mem, "kb:unit:s2")} == {"kb:fact:f2", "kb:fact:f3"}


def test_事实行的标题截短_正文全放_preview(mem):
    row = next(r for r in vt.children(mem, "kb:unit:s2") if r["note_id"] == "kb:fact:f3")
    assert len(row["title"]) == vt.FACT_TITLE_CHARS and row["title"].endswith("…")
    assert row["preview"] == "x" * 200


def test_不认识的节点返回空(mem):
    assert vt.children(mem, "kb:whatever:x") == []
    assert vt.children(mem, "kb:topics") == []


def test_is_virtual():
    assert vt.is_virtual("kb") and vt.is_virtual("kb:fact:f1")
    assert not vt.is_virtual("kbabc") and not vt.is_virtual("13d06e717afa")
