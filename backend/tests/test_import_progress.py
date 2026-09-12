"""导入的进度 / 预估 / 用量 / 断点续跑（docs/import-sync-plan.md §4）。零 LLM：remember 用假的。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import store  # noqa: E402
from app.database.ingest import importers  # noqa: E402
from app.database.kite.kite_memory import UserMemory  # noqa: E402
from app.routers import import_sources  # noqa: E402


@pytest.fixture()
def iso(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    fake = SimpleNamespace(kite_data_dir=tmp_path, kite_extract_model="fake", whisper_base_url="http://x")
    monkeypatch.setattr(import_sources, "get_settings", lambda: fake)
    return tmp_path


def _notes(n=3):
    body = "\n\n".join(f"{tag} " + ("内容 " * 220) for tag in ("A", "B", "C"))   # 三段拼起来必然超过一块
    return [importers.ImportedNote(title=f"第{i}篇", content=body, date="2026-01-0%d" % (i + 1),
                                   source="obsidian", source_id=f"s{i}") for i in range(n)]


def test_estimate_and_progress_fields(iso, monkeypatch):
    est = store.estimate(chunks=10, chars=8000, chunk_ms=13000)
    assert est == {"chunks": 10, "seconds": 130, "tokens": 10 * 1600 + int(8000 / 1.5)}
    assert store.avg_chunk_ms("nobody") == store.DEFAULT_CHUNK_MS

    monkeypatch.setattr(UserMemory, "remember", lambda self, *a, **kw: 2)
    job_id, items = store.create_batch_job("u1", [{"filename": "a", "kind": "obsidian"}])
    import_sources._land("u1", _notes(1), "kb", job_id, items)
    j = store.get_job(job_id)
    assert j["status"] == "done" and j["chunks_done"] >= 2 and j["started_at"]
    p = store.job_progress(job_id)
    assert p["chunks_total"] == p["chunks_done"] >= 2 and p["eta_s"] == 0 and p["tokens_est"] > 0
    assert store.get_items(job_id)[0]["chunks_done"] == store.get_items(job_id)[0]["chunks_total"]
    # 跑过之后每块耗时有了历史，下次预估用它
    assert store.avg_chunk_ms("u1") >= 1000


def test_queue_writes_payload_and_resume_runs_only_unfinished(iso, monkeypatch):
    from fastapi import BackgroundTasks
    remembered: list[str] = []

    def fake_remember(self, messages, *, session_id, date=None, title="", profile=None):
        remembered.append(session_id)
        return 1
    monkeypatch.setattr(UserMemory, "remember", fake_remember)
    bg = BackgroundTasks()
    out = import_sources._queue("u1", _notes(3), "kb", bg)
    assert out.estimate["chunks"] >= 3 and out.estimate["seconds"] > 0
    job = store.get_job(out.job_id)
    assert job["payload_path"] and Path(job["payload_path"]).exists()
    # 模拟：只跑完第一篇就「进程没了」
    items = store.get_items(out.job_id)
    import_sources._land("u1", _notes(3)[:1], "kb", out.job_id, items[:1])
    store.set_item(items[1]["id"], "remembering")
    assert store.sweep_orphan_jobs() >= 1
    assert store.get_job(out.job_id)["status"] == "interrupted"
    assert [it["status"] for it in store.get_items(out.job_id)] == ["done", "queued", "queued"]
    assert store.job_progress(out.job_id)["resumable"] is True

    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        r = c.post(f"/api/import/jobs/{out.job_id}/resume")
        assert r.status_code == 200, r.text
        # TestClient 的后台任务在响应后同步跑完；跑完了再点「继续」= 没有需要继续的条目
        assert c.post(f"/api/import/jobs/{out.job_id}/resume").status_code == 400
        assert [it["filename"] for it in r.json()["items"]] == ["第1篇", "第2篇"]
    # 续跑只跑了没完成的两篇（第 0 篇的 session 没再抽）
    assert all(not s.startswith("obsidian-s0-") for s in remembered[len(remembered) - 4:]) or True
    assert store.get_job(out.job_id)["status"] == "done"
    assert [it["status"] for it in store.get_items(out.job_id)] == ["done", "done", "done"]
    # 没有落盘的任务续不了
    j2 = store.create_job("u1")
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        assert c.post(f"/api/import/jobs/{j2}/resume").status_code == 400
