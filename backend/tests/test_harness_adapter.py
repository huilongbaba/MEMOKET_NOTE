"""harness_adapter.py：把 scoring 的 LLMClient/RunHistoryStore 接口
接到 app.util.llm / app.database.store 上的薄适配层。

    cd backend && python -m pytest tests/test_harness_adapter.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import store
from app.harness import adapter as harness_adapter
from app.util import llm# noqa: E402
from app.harness.types import RunRecord  # noqa: E402


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    return store


@pytest.mark.anyio
async def test_app_llm_client_forwards_to_app_llm_complete(monkeypatch):
    captured = {}

    async def fake_complete(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return "the response"

    monkeypatch.setattr(llm, "complete", fake_complete)
    client = harness_adapter.AppLLMClient()
    result = await client.complete([{"role": "user", "content": "hi"}], max_tokens=42)
    assert result == "the response"
    assert captured["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["kwargs"] == {"max_tokens": 42}


def test_sqlite_run_history_store_round_trips(isolated_store):
    hist = harness_adapter.SqliteRunHistoryStore()
    hist.record(RunRecord(
        key="note-1", status="complete", rounds=3,
        final_scores={"spine_fidelity": 2, "non_repetition": 1},
        weak_dimensions=["non_repetition"],
    ))
    recent = hist.recent("note-1", limit=3)
    assert len(recent) == 1
    assert recent[0].status == "complete"
    assert recent[0].rounds == 3
    assert recent[0].final_scores == {"spine_fidelity": 2, "non_repetition": 1}
    assert recent[0].weak_dimensions == ["non_repetition"]


def test_sqlite_run_history_store_scoped_by_key(isolated_store):
    hist = harness_adapter.SqliteRunHistoryStore()
    hist.record(RunRecord(key="note-1", status="complete", rounds=1,
                          final_scores={}, weak_dimensions=[]))
    hist.record(RunRecord(key="note-2", status="complete", rounds=1,
                          final_scores={}, weak_dimensions=[]))
    assert len(hist.recent("note-1")) == 1
    assert len(hist.recent("note-3")) == 0


def test_sqlite_run_history_store_orders_most_recent_first(isolated_store):
    hist = harness_adapter.SqliteRunHistoryStore()
    for i in range(3):
        hist.record(RunRecord(key="note-1", status="complete", rounds=i,
                              final_scores={}, weak_dimensions=[]))
    recent = hist.recent("note-1", limit=2)
    assert len(recent) == 2
    assert recent[0].rounds == 2  # most recently inserted
