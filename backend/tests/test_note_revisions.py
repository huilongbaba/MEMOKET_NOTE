"""笔记历史版本（Trilium 的 note revisions）：保存时按间隔留旧版、手动存版、恢复可逆。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app

    with TestClient(app, headers={"X-User-Id": "t-rev"}) as c:
        yield c


def _put(client, nid, content, title="甲"):
    return client.put(f"/api/notes/{nid}", json={"title": title, "content": content}).json()


def test_保存时留旧版且受间隔限制(client, monkeypatch):
    n = client.post("/api/notes", json={"title": "甲", "content": "v1"}).json()
    _put(client, n["id"], "v2")                       # 第一次改：留 v1
    _put(client, n["id"], "v3")                       # 十分钟内：不再留
    revs = client.get(f"/api/notes/{n['id']}/revisions").json()
    assert [r["chars"] for r in revs] == [2]
    assert revs[0]["reason"] == "auto"
    monkeypatch.setattr(store, "REVISION_INTERVAL_S", 0)
    _put(client, n["id"], "v4")                       # 间隔归零：留 v3
    revs = client.get(f"/api/notes/{n['id']}/revisions").json()
    assert len(revs) == 2 and revs[0]["chars"] == 2
    # 只改标题不留版本
    _put(client, n["id"], "v4", title="乙")
    assert len(client.get(f"/api/notes/{n['id']}/revisions").json()) == 2


def test_手动存版与恢复可逆(client):
    n = client.post("/api/notes", json={"title": "甲", "content": "第一版正文"}).json()
    r = client.post(f"/api/notes/{n['id']}/revisions").json()
    assert r["reason"] == "manual" and r["chars"] == 5
    _put(client, n["id"], "第二版正文更长一点")
    restored = client.post(f"/api/notes/{n['id']}/revisions/{r['id']}/restore").json()
    assert restored["content"] == "第一版正文"
    revs = client.get(f"/api/notes/{n['id']}/revisions").json()
    # 恢复前把「第二版」强制存了一份，所以能再恢复回去
    assert revs[0]["reason"] == "before_restore"
    full = client.get(f"/api/notes/{n['id']}/revisions/{revs[0]['id']}").json()
    assert full["content"] == "第二版正文更长一点"


def test_空正文不存版本_越权404(client):
    n = client.post("/api/notes", json={"title": "甲", "content": ""}).json()
    assert client.post(f"/api/notes/{n['id']}/revisions").status_code == 409
    assert client.get(f"/api/notes/{n['id']}/revisions", headers={"X-User-Id": "other"}).status_code == 404
