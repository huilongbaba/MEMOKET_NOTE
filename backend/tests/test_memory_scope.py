"""记忆范围：按 session id 前缀分 笔记 / 会议记录 / 导入 三档，召回 / 关系 / 续写都能只看一档。"""

from __future__ import annotations

from types import SimpleNamespace

from app.database.kb import scope


def test_按前缀分档():
    assert scope.classify("note-5f65df10cad6-0") == "notes"
    assert scope.classify("terrence-2046-12") == "meetings"
    assert scope.classify("obsidian-doc1-0") == "imports" and scope.classify("feishu-x-1") == "imports"
    rows = [{"id": "a", "unit": "note-x-0"}, {"id": "b", "unit": "terrence-1-2"}, {"id": "c", "unit": "notion-p-0"}]
    assert [r["id"] for r in scope.filter_rows(rows, "meetings")] == ["b"]
    assert scope.filter_rows(rows, "all") == rows and scope.filter_rows(rows, "bogus") == rows


def test_recall_按范围过滤_多取再滤(tmp_path, monkeypatch):
    from app.database import store
    from app.database.kite import kite_memory
    from app.database.kite.kite_memory import UserMemory
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    fake = SimpleNamespace(kite_data_dir=tmp_path, kite_extract_model="fake", whisper_base_url="http://x")
    monkeypatch.setattr(kite_memory, "get_settings", lambda: fake)
    mem = UserMemory("u1")
    mem.add_manual_fact("note-n1-0", "电池容量定在 380mAh。", date="2026-05-08", title="笔记")
    mem.add_manual_fact("u1-7-1", "电池容量从 300mAh 改到 380mAh。", date="2026-05-09", title="会议")
    mem.add_manual_fact("obsidian-doc-0", "电池 380mAh 的结构评审。", date="2026-05-10", title="导入")
    ids = lambda rows: sorted(r["unit"].split("-")[0] for r in rows)   # noqa: E731
    assert ids(mem.recall("电池容量 380mAh", limit=8)[0]) == ["note", "obsidian", "u1"]
    assert ids(mem.recall("电池容量 380mAh", limit=8, scope="notes")[0]) == ["note"]
    assert ids(mem.recall("电池容量 380mAh", limit=8, scope="meetings")[0]) == ["u1"]
    assert ids(mem.recall("电池容量 380mAh", limit=8, scope="imports")[0]) == ["obsidian"]
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        r = c.post("/api/memory/recall", json={"query": "电池容量 380mAh", "limit": 8, "scope": "notes"}).json()
        assert [f["id"] for f in r["facts"]] and all(f["id"].startswith("note-") for f in r["facts"])
        r = c.post("/api/memory/relations", json={"passage": "电池容量定在 420mAh。", "confirm": False, "scope": "imports"}).json()
        assert all(i.startswith("obsidian-") for rel in r["relations"] for i in rel["fact_ids"])


def test_harness_取材料的工具也带范围(monkeypatch):
    from app.harness.tools import ToolContext, registry
    from app.harness.tools import memory_tools
    from app.database.kite.kite_memory import UserMemory
    seen = {}
    monkeypatch.setattr(UserMemory, "recall", lambda self, q, limit=8, scope="all": (seen.__setitem__("scope", scope) or [], [], 0.1))
    ctx = ToolContext(user="u", scope="meetings")
    assert registry.get("search_memory") is not None
    memory_tools.search_memory(ctx, "电池")
    assert seen["scope"] == "meetings"
    assert ToolContext(user="u").scope == "all"


def test_阶段回顾也只看一档(tmp_path, monkeypatch):
    """第 184 轮：召回 / 关系 / 续写都遵守范围了，回顾还把三档混在一起总结。"""
    from app.database import store
    from app.database.kite import kite_memory
    from app.database.kite.kite_memory import UserMemory
    from app.routers import compose
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    fake = SimpleNamespace(kite_data_dir=tmp_path, kite_extract_model="fake", whisper_base_url="http://x")
    monkeypatch.setattr(kite_memory, "get_settings", lambda: fake)
    mem = UserMemory("u1")
    mem.add_manual_fact("note-n1-0", "电池容量定在 380mAh。", date="2026-05-08", title="笔记")
    mem.add_manual_fact("u1-7-1", "电池容量从 300mAh 改到 380mAh。", date="2026-05-09", title="会议")
    seen: list[str] = []

    async def fake_complete(messages, **kw):
        seen.append(messages[-1]["content"])
        return "总结"
    monkeypatch.setattr(compose.llm, "complete", fake_complete)
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        body = {"date_from": "2026-05-01", "date_to": "2026-05-31"}
        assert c.post("/api/digest", json=body).json()["fact_count"] == 2
        assert c.post("/api/digest", json={**body, "scope": "notes"}).json()["fact_count"] == 1
        assert "300mAh 改到" not in seen[-1] and "定在 380mAh" in seen[-1]
        assert c.post("/api/digest", json={**body, "scope": "imports"}).json()["fact_count"] == 0


def test_回顾空结果提示带范围(tmp_path, monkeypatch):
    from app.database import store
    from app.database.kite import kite_memory
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    fake = SimpleNamespace(kite_data_dir=tmp_path, kite_extract_model="fake", whisper_base_url="http://x")
    monkeypatch.setattr(kite_memory, "get_settings", lambda: fake)
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        assert c.post("/api/digest", json={"days": 7}).json()["summary"] == "这段时间没有记录。"
        assert "只看笔记" in c.post("/api/digest", json={"days": 7, "scope": "notes"}).json()["summary"]
