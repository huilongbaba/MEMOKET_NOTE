"""笔记 ↔ 知识库链接层：这篇贡献了哪些事实、增删改、同步（删旧 session 重抽）、过期标识、
自动同步开关；以及一个真 bug——笔记摄入的事实 id（note-<id>-0F1）之前不匹配引用正则。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import store  # noqa: E402
from app.database.kite import kite_memory  # noqa: E402
from app.database.kite.kite_memory import UserMemory  # noqa: E402
from app.harness.checks import citations  # noqa: E402
from app.harness.prompts import fragments  # noqa: E402
from app.routers import ingest  # noqa: E402
from memoket_kite.errors import StorageError  # noqa: E402


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    fake = SimpleNamespace(kite_data_dir=tmp_path, kite_extract_model="fake", whisper_base_url="http://x")
    monkeypatch.setattr(kite_memory, "get_settings", lambda: fake)


def test_manual_facts_add_edit_delete_and_survive_resync(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    mem = UserMemory("u1")
    # 模拟一次摄入产生的 session + 手工加的一条
    mem.add_manual_fact("note-abc-0", "抽出来的第一条", date="2026-09-12", title="T")
    mem.add_manual_fact("note-abc-0", "抽出来的第二条", date="2026-09-12", title="T")
    f = mem.add_manual_fact("note-abc-manual", "我手工补的", date="2026-09-12", title="T")
    assert f["id"] == "note-abc-manualF1"

    facts = mem.facts_for_prefix(UserMemory.note_prefix("abc"))
    assert [x["text"] for x in facts] == ["抽出来的第一条", "抽出来的第二条", "我手工补的"]
    assert [x["manual"] for x in facts] == [False, False, True]

    assert mem.set_fact_text("note-abc-0F2", "改过的第二条")
    assert mem.fact_by_id("note-abc-0F2")["text"] == "改过的第二条"
    assert not mem.set_fact_text("note-abc-0F99", "x")

    assert mem.delete_facts({"note-abc-0F1"}) == 1
    assert mem.fact_by_id("note-abc-0F1") is None

    # 同步：删旧 session，手工的留着
    assert mem.remove_sessions(UserMemory.note_prefix("abc")) == 1
    left = mem.facts_for_prefix(UserMemory.note_prefix("abc"))
    assert [x["text"] for x in left] == ["我手工补的"]
    # 别人的 session 不受影响
    mem.add_manual_fact("note-zzz-0", "别篇的", date="2026-09-12", title="Z")
    assert mem.remove_sessions(UserMemory.note_prefix("abc")) == 0
    assert mem.fact_by_id("note-zzz-0F1") is not None


def test_note_fact_ids_are_citable():
    """`note-f5e34e385aac-0F1` 这种 id 之前三处正则都不认——摄入进去的事实没法被引用。"""
    for pat in (store._CITE, citations.CITE):
        assert pat.findall("据 [note-f5e34e385aac-0F1] 和 [terrence-1872-5F8] 所述") == \
            ["note-f5e34e385aac-0F1", "terrence-1872-5F8"]
        assert pat.findall("[a-b-c] [2026-01-01] [note-xyz-0F1]") == []   # 段数不对 / 不是 12 位 hex 的不算
    assert fragments._FACT_ID.match("[note-f5e34e385aac-0F1] x")
    assert citations._HEAD_ID.match("[note-f5e34e385aac-0F12]")


def test_ingest_job_replace_removes_old_sessions_and_tolerates_existing(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    calls: list[str] = []
    removed: list[str] = []

    def fake_remember(self, messages, *, session_id, date=None, title="", profile=None):
        calls.append(session_id)
        if session_id.endswith("-0") and not removed:
            raise StorageError("session_id already exists: " + session_id)
        return 3

    monkeypatch.setattr(UserMemory, "remember", fake_remember)
    monkeypatch.setattr(UserMemory, "remove_sessions", lambda self, prefix, keep_suffix="-manual": removed.append(prefix) or 1)
    n = store.create_note("u1", "T", "正文")
    # 不 replace：已存在 = 跳过，不报错
    job = store.create_job("u1")
    ingest._ingest_job(job, "u1", "正文", "T", "note", "", n["id"], False)
    j = store.get_job(job)
    assert j["status"] == "done" and j["facts"] == 0 and "此前已摄入" in j["detail"]
    assert removed == []
    # replace：先删旧 session 再抽
    job2 = store.create_job("u1")
    ingest._ingest_job(job2, "u1", "正文", "T", "note", "", n["id"], True)
    assert removed == [f"note-{n['id']}-"]
    assert store.get_job(job2)["status"] == "done" and store.get_job(job2)["facts"] == 3
    assert store.get_note("u1", n["id"])["ingested_at"]


def test_note_kb_endpoint_reports_stale_and_manual_add(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        n = c.post("/api/notes", json={"title": "例会", "content": "第一版"}).json()
        r = c.get(f"/api/notes/{n['id']}/kb").json()
        assert r["ingested_at"] == "" and r["stale"] is False and r["facts"] == []
        # 手工补一条 → 视为已摄入
        f = c.post("/api/kb/fact", json={"note_id": n["id"], "text": "手工的一条"}).json()
        assert f["id"] == f"note-{n['id']}-manualF1"
        r = c.get(f"/api/notes/{n['id']}/kb").json()
        assert r["ingested_at"] and r["stale"] is False
        assert [x["text"] for x in r["facts"]] == ["手工的一条"] and r["facts"][0]["manual"] is True
        # 改正文 → 过期（时间戳只到秒，把摄入时间往前拨一天再改）
        with store.connect() as conn:
            conn.execute("UPDATE notes SET ingested_at='2026-01-01T00:00:00+00:00' WHERE id=?", (n["id"],))
        c.put(f"/api/notes/{n['id']}", json={"title": "例会", "content": "第二版"})
        assert c.get(f"/api/notes/{n['id']}/kb").json()["stale"] is True
        # 改 / 删
        assert c.patch(f"/api/kb/fact/{f['id']}", json={"text": "改过"}).json()["text"] == "改过"
        assert c.delete(f"/api/kb/fact/{f['id']}").json()["removed"] == 1
        assert c.delete(f"/api/kb/fact/{f['id']}").status_code == 404
        # 知识库页面上的事实带 note_id 反链
        from app.database.kb import pages
        assert pages.note_id_of_unit("note-abc-0") == "abc"
        assert pages.note_id_of_unit("note-abc-manual") == "abc"
        assert pages.note_id_of_unit("terrence-268-0") == ""


def test_auto_sync_setting_round_trip(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from app.main import app
    with TestClient(app) as c:
        assert c.get("/api/settings/provider").json()["auto_sync_notes"] is False
        r = c.post("/api/settings/provider", json={"provider": "local", "auto_sync_notes": True}).json()
        assert r["auto_sync_notes"] is True
        # 只改别的不动它
        assert c.post("/api/settings/provider", json={"provider": "local"}).json()["auto_sync_notes"] is True
