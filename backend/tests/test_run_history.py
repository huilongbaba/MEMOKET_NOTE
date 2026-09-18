"""批 22 / 计划 11.4：`middleware/history` 的两处「同一件事只挡住一半」。

① `st.ev is None` 在 `after_run` 有**两个**含义——「打分调用失败了」和
   「循环在每轮末尾把它清空了、这一轮没触发任何停机条件、`for` 正常跑完」。
   后者就是 `max_rounds`。原来那行 `if not st.ev: return` 把两者一起挡了，
   于是**跑满轮数的跑一行历史都不记**。实测：`harness_rounds` 158 次跑里
   17 次跑满（10.8%），`harness_runs` 里 `stopped='max_rounds'` 是 **0 行**；
   `analysis` 6 次跑全跑满、历史里 1 行，`eda` 6 次跑全跑满、历史里 0 行。
② 判据短路那一轮的伪造分数（一个维度、分数 0）被当成这次跑的终评记下来。
   实测 103 行里 14 行（13.6%）是这样。

下游读者是 `policy.from_history`：它拿最近 3 次的 `weak_dimensions` 给下一次
跑的第一轮定初始参数。
"""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from app.harness import modes
from app.harness.middleware.history import History
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import DimensionScore, Evaluation

DIMS = ("beat_coverage", "non_repetition", "factual_grounding")


@pytest.fixture()
def recorded(monkeypatch):
    out: list = []
    monkeypatch.setattr(
        "app.harness.adapter.SqliteRunHistoryStore",
        lambda: type("S", (), {"record": lambda self, r: out.append(r)})())
    return out


def _st(round_=3, stopped="max_rounds"):
    st = State(mode=dataclasses.replace(modes.NOTE, dims=DIMS),
               ctx=ToolContext(user="u", note_id="n", note_title="t"))
    st.round, st.stopped = round_, stopped
    return st


def _ev(**levels):
    return Evaluation(scores={k: DimensionScore(level=v, note="") for k, v in levels.items()},
                      status="continue", weakest=min(levels, key=levels.get))


def test_跑满轮数的跑也要记进历史(recorded):
    """循环跑到 `else` 分支时 `st.ev` 已经被清成 None——那不是「没发生过」。"""
    st = _st()
    st.bag["score_vectors"] = [
        {"beat_coverage": 2, "non_repetition": 1, "factual_grounding": 0},
        {"beat_coverage": 2, "non_repetition": 1, "factual_grounding": 1},
    ]
    asyncio.run(History().after_run(st))
    assert len(recorded) == 1
    rec = recorded[0]
    assert rec.stopped == "max_rounds", "0.3 加这一列就是为了记住这个值"
    assert rec.rounds == 3
    assert rec.final_scores == st.bag["score_vectors"][-1], "用最后一份真打出来的向量"
    assert sorted(rec.weak_dimensions) == ["factual_grounding", "non_repetition"]


def test_判据短路那一轮的伪造分数不当终评(recorded):
    """伪造的那份只有一个维度、分数 0，跟真分数向量不可比——`Ledger` /
    `Repair` / `loop._regressed` 三处都排除它，只有这里原来照单全收。"""
    st = _st(stopped="material_used_up")
    st.bag["score_vectors"] = [{"beat_coverage": 2, "non_repetition": 2,
                                "factual_grounding": 1}]
    st.ev = Evaluation(scores={"factual_grounding": DimensionScore(level=0, note="有占位符")},
                       status="continue", weakest="factual_grounding")
    st.skip_judge = True
    asyncio.run(History().after_run(st))
    rec = recorded[0]
    assert rec.final_scores == {"beat_coverage": 2, "non_repetition": 2,
                                "factual_grounding": 1}
    assert rec.weak_dimensions == ["factual_grounding"], \
        "只该有真判出来的那一维，不是判据打翻的那一维"
    assert len(rec.final_scores) == 3, "伪造的那份只有一维，混进来就看得出来"


def test_真打过分的收尾照旧用这一轮的分数(recorded):
    """**反向闸**：把上面两条改成「一律读 score_vectors」也能绿。"""
    st = _st(stopped="complete")
    st.bag["score_vectors"] = [{"beat_coverage": 0, "non_repetition": 0,
                                "factual_grounding": 0}]
    st.ev = dataclasses.replace(
        _ev(beat_coverage=2, non_repetition=2, factual_grounding=2), status="complete")
    asyncio.run(History().after_run(st))
    assert recorded[0].final_scores == {"beat_coverage": 2, "non_repetition": 2,
                                        "factual_grounding": 2}
    assert recorded[0].status == "complete"


def test_一轮都没真打上分就不编一个出来(recorded):
    """判据从头短路到尾（第 601 轮那次死锁的形状）：没判过就是没判过。
    空的 `weak_dimensions` 在 `from_history` 里什么都不推，这是对的。"""
    st = _st(stopped="max_rounds")
    asyncio.run(History().after_run(st))
    assert recorded[0].final_scores == {}
    assert recorded[0].weak_dimensions == []
    assert recorded[0].stopped == "max_rounds"


def test_一轮都没跑过的不记(recorded):
    """`precheck` 挡下来那一档（`reason=blocked`，循环体一次都没进）没有任何
    关于写作的信息，记下来只会在 `from_history` 的分母里加噪声。"""
    st = _st(round_=0, stopped="blocked")
    asyncio.run(History().after_run(st))
    assert recorded == []


def test_暂停等用户处置的照旧不记(recorded):
    st = _st(round_=2, stopped="awaiting_review")
    st.ev = _ev(beat_coverage=2, non_repetition=2, factual_grounding=2)
    asyncio.run(History().after_run(st))
    assert recorded == []


def test_跑满轮数记下来之后策略器真的学得到(monkeypatch, recorded):
    """端到端那一半：`from_history` 只读 `weak_dimensions`，所以①要是没修，
    最该学的那一类（从头到尾没达标）恰好是唯一学不到的。"""
    from app.harness import policy

    st = _st(stopped="max_rounds")
    st.bag["score_vectors"] = [{"beat_coverage": 2, "non_repetition": 2,
                                "factual_grounding": 0}]
    asyncio.run(History().after_run(st))
    asyncio.run(History().after_run(st))

    tuned, reasons = policy.from_history(recorded)
    assert reasons, "两次跑满、同一维不达标 —— 第一轮就该带上对应策略"
    assert tuned.require_verification is True
    assert tuned.tool_iters > policy.RuntimePolicy().tool_iters
