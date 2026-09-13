"""最近删除：删掉的笔记 30 天内能找回，id 不变、位置不变、历史版本一起回来。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "t-trash"}) as c:
        yield c


def test_删了能在最近删除里找回_位置和历史版本都在(client):
    p = client.post("/api/notes", json={"title": "项目", "content": "# 项目"}).json()
    a = client.post("/api/notes", json={"title": "会议 A", "content": "v1", "parent_note_id": p["id"]}).json()
    client.put(f"/api/notes/{a['id']}", json={"title": "会议 A", "content": "v2 改过"})
    assert client.delete(f"/api/notes/{a['id']}").json()["deleted"] == [a["id"]]
    assert client.get(f"/api/notes/{a['id']}").status_code == 404
    t = client.get("/api/notes/trash").json()
    assert [x["note_id"] for x in t] == [a["id"]] and t[0]["title"] == "会议 A" and t[0]["chars"] == len("v2 改过")
    r = client.post(f"/api/notes/trash/{a['id']}/restore").json()
    assert r["id"] == a["id"] and r["content"] == "v2 改过"
    tree = client.get("/api/tree").json()
    assert any(row["note_id"] == a["id"] and row["parent_note_id"] == p["id"] for row in tree)
    assert client.get("/api/notes/trash").json() == []
    assert client.get(f"/api/notes/{a['id']}/revisions").status_code == 200


def test_父节点也删了_恢复到树根_子树逐篇可恢复(client):
    p = client.post("/api/notes", json={"title": "项目", "content": "x"}).json()
    a = client.post("/api/notes", json={"title": "子", "content": "y", "parent_note_id": p["id"]}).json()
    deleted = client.delete(f"/api/notes/{p['id']}").json()["deleted"]
    assert set(deleted) == {p["id"], a["id"]}
    assert {x["note_id"] for x in client.get("/api/notes/trash").json()} == {p["id"], a["id"]}
    client.post(f"/api/notes/trash/{a['id']}/restore")
    tree = client.get("/api/tree").json()
    assert any(row["note_id"] == a["id"] and row["parent_note_id"] == "root" for row in tree)
    assert client.delete(f"/api/notes/trash/{p['id']}").json() == {"ok": True}
    assert client.get("/api/notes/trash").json() == []
    assert client.post(f"/api/notes/trash/{p['id']}/restore").status_code == 404


def test_超过_30_天的自动清掉(client, monkeypatch):
    n = client.post("/api/notes", json={"title": "旧", "content": "x"}).json()
    client.delete(f"/api/notes/{n['id']}")
    with store.connect() as c:
        c.execute("UPDATE note_trash SET deleted_at='2020-01-01T00:00:00+00:00'")
    assert client.get("/api/notes/trash").json() == []


def test_删子树时挂在上面的写作计划作废_孤儿计划启动时扫掉(client):
    p = client.post("/api/notes", json={"title": "项目", "content": "x"}).json()
    plan = store.create_plan("t-trash", p["id"], "写三篇")
    assert store.get_active_plan("t-trash", p["id"])["id"] == plan["id"]
    client.delete(f"/api/notes/{p['id']}")
    assert store.get_active_plan("t-trash", p["id"]) is None
    # 老库里父节点已经没了却还 active 的：启动扫一遍
    with store.connect() as c:
        c.execute("UPDATE writing_plans SET status='active' WHERE id=?", (plan["id"],))
    assert store.sweep_orphan_plans() == 1 and store.get_active_plan("t-trash", p["id"]) is None
    # 作废计划下指着已删笔记的 section、既不在笔记也不在回收站的导回记录，一起扫掉
    with store.connect() as c:
        c.execute("INSERT INTO writing_sections (id,plan_id,idx,title,status,note_id,created_at) VALUES ('s1',?,0,'x','done','gone-note','2026-01-01')", (plan["id"],))
        c.execute("INSERT INTO note_remotes (user_id,note_id,platform,remote_id,remote_path,exported_at) VALUES ('t-trash','gone-note','obsidian','','a.md','2026-01-01')")
    assert store.sweep_orphan_plans() == 2
