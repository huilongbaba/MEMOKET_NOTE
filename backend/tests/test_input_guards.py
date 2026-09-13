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
