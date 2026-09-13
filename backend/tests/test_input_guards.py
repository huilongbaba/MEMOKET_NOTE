"""空输入不花模型调用：空正文生成骨架、空选区重写 / 扩写 / 校验都直接 400。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import store
from app.routers import compose


def test_空输入直接_400_不打模型(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    calls = []

    async def boom(*a, **k):
        calls.append(1)
        return "{}"
    monkeypatch.setattr(compose.llm, "complete", boom)
    monkeypatch.setattr(compose.llm, "complete_json", boom)
    monkeypatch.setattr(compose.llm, "complete_json_raw", boom, raising=False)
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        assert c.post("/api/skeleton", json={"content": "  ", "title": ""}).status_code == 400
        assert c.post("/api/rewrite", json={"content": "一段话。", "selection": " ", "intent": "rewrite"}).status_code == 400
        assert c.post("/api/expand", json={"content": "一段话。", "selection": ""}).status_code == 400
        assert c.post("/api/verify", json={"content": "一段话。", "selection": ""}).status_code == 400
    assert calls == []


def test_标题一行_父节点要存在(tmp_path, monkeypatch):
    """第 244 轮实测：带换行的一万字标题照收；parent_note_id 给个不存在的 id 也 200（树上看不见）。"""
    from fastapi.testclient import TestClient
    from app.database import store
    from app.main import app
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        n = c.post("/api/notes", json={"title": "  a\nb\t c  " + "x" * 500, "content": ""}).json()
        assert n["title"].startswith("a b c x") and "\n" not in n["title"] and len(n["title"]) == 200
        assert c.post("/api/notes", json={"title": "p", "content": "", "parent_note_id": "nope"}).status_code == 404
        m = c.put(f"/api/notes/{n['id']}", json={"title": "改\n名", "content": "x"}).json()
        assert m["title"] == "改 名"


def test_移动到不存在的父节点404_克隆成环400(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.database import store
    from app.main import app
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        a = c.post("/api/notes", json={"title": "A", "content": ""}).json()
        b = c.post("/api/notes", json={"title": "B", "content": "", "parent_note_id": a["id"]}).json()
        assert c.patch("/api/tree/branches/move", json={"note_id": b["id"], "from_parent_id": a["id"], "to_parent_id": "nope"}).status_code == 404
        assert c.post("/api/tree/branches", json={"note_id": a["id"], "parent_note_id": b["id"]}).status_code == 400
        assert [t["parent_note_id"] for t in c.get("/api/tree").json() if t["note_id"] == b["id"]] == [a["id"]]
