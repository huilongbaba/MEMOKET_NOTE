"""第 246 轮：手工事实的取代 / 合并不能成环，一条事实不能是一篇文章。"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_取代不能自指_合并不能互指_事实不能太长(tmp_path, monkeypatch):
    from app.database import store
    from app.main import app
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        n = c.post("/api/notes", json={"title": "N", "content": "x"}).json()
        a = c.post("/api/kb/fact", json={"note_id": n["id"], "text": "电池 380mAh", "when": "2026-05-01"}).json()["id"]
        b = c.post("/api/kb/fact", json={"note_id": n["id"], "text": "电池 420mAh", "when": "2026-06-01"}).json()["id"]
        assert c.post("/api/kb/fact", json={"note_id": n["id"], "text": "y" * 2001, "when": "2026-06-01"}).status_code == 400
        assert c.patch(f"/api/kb/fact/{a}", json={"text": "", "superseded_by": a}).status_code == 400
        assert c.post("/api/kb/fact/merge", json={"keep": b, "drop": a, "text": ""}).status_code == 200
        assert c.post("/api/kb/fact/merge", json={"keep": a, "drop": b, "text": ""}).status_code == 400
        assert c.patch(f"/api/kb/fact/{b}", json={"text": "", "superseded_by": a}).status_code == 400
        facts = {f["id"]: f for f in c.get("/api/memory/facts", params={"limit": 10}).json()["facts"]}
        assert facts[a].get("merged") and not facts[b].get("merged")
