"""笔记之间的链接：`[标题](note://<id>)` 的解析与反查（Trilium 的 note links / referenced by）。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app

    with TestClient(app, headers={"X-User-Id": "t-links"}) as c:
        yield c


def test_note_links_in_解析并去重():
    ids = store.note_links_in("见 [甲](note://aaaaaaaaaaaa) 和 [乙](note://bbbbbbbbbbbb)，再 [甲](note://aaaaaaaaaaaa)")
    assert ids == ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]
    assert store.note_links_in("[外链](https://x.y) 与 [坏的](note://short)") == []


def test_链接接口_链出与反链(client):
    a = client.post("/api/notes", json={"title": "甲", "content": ""}).json()
    b = client.post("/api/notes", json={"title": "乙", "content": f"回看 [甲](note://{a['id']})。"}).json()
    client.put(f"/api/notes/{a['id']}", json={"title": "甲", "content": f"下一步见 [乙](note://{b['id']})"})
    r = client.get(f"/api/notes/{a['id']}/links").json()
    assert [x["id"] for x in r["outgoing"]] == [b["id"]]
    assert [x["id"] for x in r["backlinks"]] == [b["id"]]
    assert r["backlinks"][0]["preview"].startswith("回看")
    assert client.get("/api/notes/nonexist0000/links").status_code == 404


def test_反链不跨用户(client):
    a = client.post("/api/notes", json={"title": "甲", "content": ""}).json()
    client.post("/api/notes", json={"title": "别人的", "content": f"[甲](note://{a['id']})"},
                headers={"X-User-Id": "someone-else"})
    assert client.get(f"/api/notes/{a['id']}/links").json()["backlinks"] == []
