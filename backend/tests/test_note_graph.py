"""这篇笔记周围有什么（`GET /api/notes/{id}/graph`）：引用的 + 贡献的事实挂在哪些主题 / 实体上。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memoket_kite.core.algebra import FactRecord, Store, Unit  # noqa: E402
from memoket_kite.core.vocab import Entity, Topic, Vocab  # noqa: E402

from app.database import store  # noqa: E402
from app.database.kite.kite_memory import UserMemory  # noqa: E402


def _fact(id, text, *, topics=(), entities=()):
    return FactRecord(id=id, unit="s1", unit_date="2026-01-05", t="2026-01-05", kind="plan", who="user",
                      conf="high", topics=tuple(topics), entities=tuple(entities), src=(), text=text)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    st, vocab = Store(), Vocab()
    vocab.topics["work"] = Topic("work", parents=set(), status="canonical")
    vocab.topics["work_hw"] = Topic("work_hw", parents={"work"}, status="canonical")
    vocab.entities["acme"] = Entity("acme", etype="org", name="Acme")
    vocab.entities["speaker_a"] = Entity("speaker_a", etype="", name="speaker a")
    st.units["s1"] = Unit(id="s1", date="2026-01-05", t="", title="周会", dur_min=0, n_lines=1)
    st.facts["u-1-A"] = _fact("u-1-A", "交付截止周五", topics=["work"], entities=["acme", "speaker_a"])
    st.facts["u-2-B"] = _fact("u-2-B", "样机三台", topics=["work_hw"], entities=["acme"])
    st.facts["u-3-C"] = _fact("u-3-C", "无关", topics=["work"], entities=[])
    monkeypatch.setattr(UserMemory, "_index", lambda self: (st, vocab))
    monkeypatch.setattr(UserMemory, "fact_by_id", lambda self, fid: (
        {"id": fid, "text": st.facts[fid].text, "topics": list(st.facts[fid].topics), "entities": list(st.facts[fid].entities)}
        if fid in st.facts else None))
    monkeypatch.setattr(UserMemory, "facts_for_prefix", lambda self, prefix: [])
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "t-graph"}) as c:
        yield c


def test_引用的事实牵出主题和实体_说话人不进图(client):
    n = client.post("/api/notes", json={"title": "x", "content": "据 [u-1-A] 和 [u-2-B] 所述，再引 [u-1-A] 一次；[u-9-Z] 不存在。"}).json()
    g = client.get(f"/api/notes/{n['id']}/graph").json()
    assert g["facts"] == 2
    assert {t["code"]: t["fact_count"] for t in g["topics"]} == {"work": 1, "work_hw": 1}
    assert [e["code"] for e in g["entities"]] == ["acme"]          # speaker a 是伪实体
    assert g["entities"][0]["name"] == "Acme" and g["entities"][0]["fact_count"] == 2
    assert {(l["topic"], l["entity"], l["weight"]) for l in g["links"]} == {("work", "acme", 1), ("work_hw", "acme", 1)}
    # 子主题的父链只留图里有的
    assert next(t for t in g["topics"] if t["code"] == "work_hw")["parents"] == ["work"]


def test_没有引用也没摄入_空图(client):
    n = client.post("/api/notes", json={"title": "y", "content": "什么都没引"}).json()
    g = client.get(f"/api/notes/{n['id']}/graph").json()
    assert g == {"facts": 0, "topics": [], "entities": [], "links": []}
    assert client.get("/api/notes/nope/graph").status_code == 404
