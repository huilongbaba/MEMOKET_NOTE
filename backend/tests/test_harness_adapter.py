"""harness_adapter.py：把 scoring 的 LLMClient/RunHistoryStore 接口
接到 app.llm / app.store 上的薄适配层。

    cd backend && python -m pytest tests/test_harness_adapter.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import harness_adapter, llm, store  # noqa: E402
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


def test_note_dimensions_includes_style_fit_only_with_profile():
    with_profile = harness_adapter.note_dimensions(has_profile=True)
    without_profile = harness_adapter.note_dimensions(has_profile=False)
    assert "style_fit" in {d.name for d in with_profile}
    assert "style_fit" not in {d.name for d in without_profile}


def test_beat_coverage_guidance_does_not_demand_more_elaboration():
    # TRACELOG [10]：实测 beats 早就被正文实质覆盖了，续写模型还是主观
    # 续续续，没有内在动力主动收敛——这条打分指令必须明确"覆盖了就是
    # 覆盖了"，不能被"还能写得更详细"这种理由带着继续判定"没覆盖"。
    # 之前是 BEATS_COVERAGE_SYSTEM 自己的规则，现在是 beat_coverage 这个
    # 维度的 guidance 文案。
    dims = {d.name: d for d in harness_adapter.note_dimensions(has_profile=False)}
    assert "写到极致" in dims["beat_coverage"].guidance


def test_section_dimensions_has_topic_fidelity_instead_of_spine_beats():
    dims = {d.name for d in harness_adapter.section_dimensions(has_profile=False)}
    assert "topic_fidelity" in dims
    assert "spine_fidelity" not in dims
    assert "beat_coverage" not in dims


def test_polish_mode_drops_dimensions_it_may_not_act_on():
    """打磨只修不写，就不能拿"写了多少"去打分——否则闭环不可能收敛。"""
    from app.harness_adapter import note_dimensions

    write = {d.name for d in note_dimensions(has_profile=False)}
    polish = {d.name for d in note_dimensions(has_profile=False, polish=True)}
    assert {"beat_coverage", "material_use"} <= write
    assert not ({"beat_coverage", "material_use"} & polish), \
        "打磨模式不许写，就不该被节拍覆盖/材料使用打分（实测：判 0 → 永远到不了 complete → 撞 max_rounds）"
    assert {"spine_fidelity", "non_repetition", "factual_grounding", "coherence"} <= polish
    assert "style_fit" in {d.name for d in note_dimensions(has_profile=True, polish=True)}
