"""重写 / 扩展：JSON 撞长度上限切了半截时，要说「选短一点」，不是「模型没给建议」。"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import store  # noqa: E402
from app.routers import compose  # noqa: E402


def _client(monkeypatch, tmp_path, text: str, finish_reason: str):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")

    async def fake_complete(messages, *, max_tokens=0, temperature=0.0, effort="low", stats=None):
        if stats is not None:
            stats["finish_reason"] = finish_reason
        return text

    monkeypatch.setattr(compose.llm, "complete", fake_complete)
    monkeypatch.setattr(compose, "_retrieve", lambda *a, **k: ([], [], 0.0))
    from app.main import app
    return TestClient(app, headers={"X-User-Id": "u1"})


def test_rewrite_truncated_json_gives_note(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path, '{"text": "改到一半就', "length") as c:
        r = c.post("/api/rewrite", json={"content": "a 选中 b", "selection": "选中"}).json()
    assert r["revisions"] == []
    assert "选短一点" in r["note"]


def test_rewrite_ok_has_empty_note(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path, '{"text": "改好了", "reason": "更顺"}', "stop") as c:
        r = c.post("/api/rewrite", json={"content": "a 选中 b", "selection": "选中"}).json()
    assert len(r["revisions"]) == 1 and r["note"] == ""


def test_expand_truncated_json_gives_note(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path, '{"before": "补到一半', "length") as c:
        r = c.post("/api/expand", json={"content": "a 选中 b", "selection": "选中"}).json()
    assert r["revisions"] == [] and "选短一点" in r["note"]
