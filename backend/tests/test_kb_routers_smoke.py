"""知识库 / 记忆那一组只读接口的路由层冒烟：页面逻辑在 test_kb_pages 里测过，但路由 + 响应模型
这一层之前一条测试都没有（第 454 轮按 openapi 反查：35 个路径没有任何测试碰过）。
夹具跟 test_note_graph 一样：类级别 monkeypatch UserMemory._index，喂一个手搭的 Store / Vocab。"""

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


def _fact(id, text, when, *, topics=(), entities=(), unit="s1"):
    return FactRecord(id=id, unit=unit, unit_date=when, t=when, kind="plan", who="user",
                      conf="high", topics=tuple(topics), entities=tuple(entities), src=(), text=text)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    st, vocab = Store(), Vocab()
    vocab.topics["work"] = Topic("work", parents=set(), status="canonical")
    vocab.topics["work_hw"] = Topic("work_hw", parents={"work"}, status="canonical")
    vocab.entities["acme"] = Entity("acme", etype="org", name="Acme")
    st.units["s1"] = Unit(id="s1", date="2026-01-05", t="", title="周会", dur_min=0, n_lines=1)
    st.facts["u-1-A"] = _fact("u-1-A", "交付截止周五", "2026-01-05", topics=["work"], entities=["acme"])
    st.facts["u-2-B"] = _fact("u-2-B", "样机三台", "2026-01-05", topics=["work_hw"], entities=["acme"])
    monkeypatch.setattr(UserMemory, "_index", lambda self: (st, vocab))
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "t-kbr"}) as c:
        yield c


@pytest.mark.parametrize("path", [
    "/api/kb/tree",
    "/api/kb/tree/children?node=kb:topic:work",
    "/api/kb/topic/work",
    "/api/kb/entity/acme",
    "/api/kb/timeline",
    "/api/kb/timeline/2026-01-05",
    "/api/kb/unit/s1",
    "/api/memory/topics",
    "/api/memory/entities",
    "/api/memory/topic-entity-links",
    "/api/memory/timeline",
    "/api/kb/clusters",
    "/api/kb/quality",
    "/api/kb/rebuild/pending",
    "/api/skills/scopes",
    "/api/import/apple/available",
])
def test_只读接口都_200_且是_JSON(client, path):
    r = client.get(path)
    assert r.status_code == 200, (path, r.text[:200])
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body not in (None, "")


def test_树里有两个主题_一个实体_展开主题给事实(client):
    rows = client.get("/api/kb/tree").json()
    ids = {r["note_id"] for r in rows}
    assert {"kb:topic:work", "kb:topic:work_hw", "kb:entity:acme"} <= ids
    kids = client.get("/api/kb/tree/children", params={"node": "kb:topic:work"}).json()
    assert {r["note_id"] for r in kids} >= {"kb:fact:u-1-A", "kb:fact:u-2-B"}   # 闭包含子主题


def test_不存在的主题_实体_会议是_404(client):
    for path in ("/api/kb/topic/nope", "/api/kb/entity/nope", "/api/kb/unit/nope"):
        assert client.get(path).status_code == 404, path


def test_树的展开与重排接口(client):
    a = client.post("/api/notes", json={"title": "甲", "content": "x"}).json()
    b = client.post("/api/notes", json={"title": "乙", "content": "y"}).json()
    r = client.patch("/api/tree/branches/expanded", json={"note_id": a["id"], "parent_note_id": "root", "expanded": True})
    assert r.status_code == 200 and r.json() == {"note_id": a["id"], "expanded": True}
    assert next(x for x in client.get("/api/tree").json() if x["note_id"] == a["id"])["is_expanded"] is True
    r = client.patch("/api/tree/branches/reorder", json={"parent_note_id": "root", "order": [b["id"], a["id"]]})
    assert r.status_code == 200, r.text[:200]
    rows = client.get("/api/tree").json()
    pos = {x["note_id"]: x["position"] for x in rows if x["parent_note_id"] == "root"}
    assert pos[b["id"]] < pos[a["id"]]                       # 乙排到甲前面


def test_技能重排是配置不是展示(client):
    """两个 skill 互相矛盾时以模型最后读到的为准，所以顺序要落库、要按 reorder 给的顺序回来。"""
    a = client.post("/api/skills", json={"name": "alpha-rule", "content": "先写结论", "scopes": []})
    b = client.post("/api/skills", json={"name": "beta-rule", "content": "多给例子", "scopes": []})
    assert a.status_code == 200 and b.status_code == 200, (a.text[:120], b.text[:120])
    sa, sb = a.json()["slug"], b.json()["slug"]
    before = [s["slug"] for s in client.get("/api/skills").json() if s["slug"] in (sa, sb)]
    assert before == [sa, sb]
    r = client.post("/api/skills/reorder", json={"ordered_ids": [sb, sa]})
    assert r.status_code == 200 and r.json() == {"ok": True}
    after = [s["slug"] for s in client.get("/api/skills").json() if s["slug"] in (sa, sb)]
    assert after == [sb, sa]
