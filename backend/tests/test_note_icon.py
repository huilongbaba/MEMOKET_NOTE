"""笔记图标（Trilium 的 NoteIcon）：一列 icon，POST /icon 设 / 清，树行和笔记都带。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "t-icon"}) as c:
        yield c


def test_设图标_树行和笔记都带_清掉回空(client):
    n = client.post("/api/notes", json={"title": "火箭", "content": "x"}).json()
    assert n["icon"] == ""
    r = client.post(f"/api/notes/{n['id']}/icon", json={"icon": "bx-rocket"})
    assert r.status_code == 200 and r.json()["icon"] == "bx-rocket"
    row = next(x for x in client.get("/api/tree").json() if x["note_id"] == n["id"])
    assert row["icon"] == "bx-rocket"
    assert client.get(f"/api/notes/{n['id']}").json()["icon"] == "bx-rocket"
    assert client.get("/api/notes/brief", params={"q": "火箭"}).json()["notes"][0]["icon"] == "bx-rocket"   # ⌘K 行也带
    assert client.post(f"/api/notes/{n['id']}/icon", json={"icon": ""}).json()["icon"] == ""


def test_图标名只认_boxicons_类名(client):
    n = client.post("/api/notes", json={"title": "x", "content": "x"}).json()
    for bad in ["rocket", "bx-<script>", "bx-" + "a" * 50, "fa fa-rocket"]:
        assert client.post(f"/api/notes/{n['id']}/icon", json={"icon": bad}).status_code == 422, bad
    assert client.post(f"/api/notes/{n['id']}/icon", json={"icon": "bxs-star"}).status_code == 200
    assert client.post("/api/notes/nope/icon", json={"icon": "bx-rocket"}).status_code == 404
