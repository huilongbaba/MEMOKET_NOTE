"""批 23 / 计划 9.3：跨「跑」的护栏——比上次差就提示，**不自动回滚**。

[EFF] P2：`best_of` / `loop._regressed` 只管一次跑内部，用户第二次点「跑」时
**没有任何东西比较「这次跑完是不是比上次差」**。实测三篇笔记反复跑同一篇：
9→6→4、9→7→4→3。

计划第 4 节「不做」里写死了不做跨跑自动回滚，所以这里盯的既有「差了要报」，
也有「报了不许动正文」。
"""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from app.harness import modes
from app.harness.events import CUSTOM_CROSS_RUN
from app.harness.middleware import BASE, OrderError, verify
from app.harness.middleware.cross_run import CrossRun, compare
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import DimensionScore, Evaluation, RunRecord

DIMS = ("beat_coverage", "non_repetition", "factual_grounding")


@pytest.fixture()
def history(monkeypatch):
    """上一次跑的记录。往 `history` 里塞 RunRecord 就是「历史」；
    `history.asked` 记下 `recent()` 被问过几次——「有没有去查历史」本身
    也是一条要钉的性质（不该比的时候连库都不该读）。"""

    class _Past(list):
        asked: list[str] = []

    past = _Past()
    past.asked = []

    class _Store:
        def record(self, run):                      # pragma: no cover - 不该被调
            raise AssertionError("CrossRun 不许写历史")

        def recent(self, key, limit=3):
            past.asked.append(key)
            return list(past)[:limit]

    monkeypatch.setattr("app.harness.adapter.SqliteRunHistoryStore", lambda: _Store())
    return past


def _st(scores: dict[str, int], *, round_=3, stopped="complete"):
    st = State(mode=dataclasses.replace(modes.NOTE, dims=DIMS),
               ctx=ToolContext(user="u", note_id="n", note_title="t"))
    st.round, st.stopped, st.content = round_, stopped, "这次跑出来的正文"
    st.ev = Evaluation(scores={k: DimensionScore(level=v, note="") for k, v in scores.items()},
                       status="continue", weakest=min(scores, key=scores.get))
    return st


def _fire(st) -> list:
    async def go():
        return [e async for e in CrossRun().after_run(st)]
    return asyncio.run(go())


def _past(scores: dict[str, int]) -> RunRecord:
    return RunRecord(key="note:n", status="continue", rounds=3, final_scores=scores,
                     weak_dimensions=[k for k, v in scores.items() if v < 2])


# ------------------------------------------------------------ 折叠怎么比

def test_比上次差就报一句(history):
    history.append(_past({"beat_coverage": 2, "non_repetition": 2, "factual_grounding": 2}))
    events = _fire(_st({"beat_coverage": 2, "non_repetition": 1, "factual_grounding": 2}))
    assert len(events) == 1
    v = events[0].data["value"]
    assert events[0].data["name"] == CUSTOM_CROSS_RUN
    assert (v["last_met"], v["met"]) == (3, 2)
    assert v["dimensions"] == ["non_repetition"]
    assert "历史版本" in v["detail"], "只报不回滚，那就得告诉用户上一版在哪"


@pytest.mark.parametrize("now,last", [
    # 一样
    ({"beat_coverage": 2, "non_repetition": 1, "factual_grounding": 2},
     {"beat_coverage": 2, "non_repetition": 1, "factual_grounding": 2}),
    # 这次更好
    ({"beat_coverage": 2, "non_repetition": 2, "factual_grounding": 2},
     {"beat_coverage": 2, "non_repetition": 1, "factual_grounding": 1}),
    # 达标数一样、这次均分更高
    ({"beat_coverage": 2, "non_repetition": 1, "factual_grounding": 1},
     {"beat_coverage": 2, "non_repetition": 0, "factual_grounding": 1}),
])
def test_没变差就不报(history, now, last):
    history.append(_past(last))
    assert _fire(_st(now)) == []


def test_平手不报():
    """达标维度一样多、均分一样——那不是变差。"""
    assert compare({"a": 2, "b": 1}, {"a": 2, "b": 1}) is None


def test_达标数一样但均分掉了也算差():
    assert compare({"a": 2, "b": 1}, {"a": 2, "b": 2}) is not None


def test_维度集合不同不比(history):
    """维度集合会随「有没有风格档案」「是不是打磨模式」变（`modes.for_run`）。
    拿不同的维度集合折叠出来的两个标量比大小，比出来的是**配置差异**。"""
    history.append(_past({"beat_coverage": 2, "non_repetition": 2,
                          "factual_grounding": 2, "style_fit": 2}))
    assert _fire(_st({"beat_coverage": 2, "non_repetition": 1, "factual_grounding": 1})) == []


def test_没有历史就不比(history):
    assert _fire(_st({"beat_coverage": 1, "non_repetition": 1, "factual_grounding": 1})) == []


def test_这次一分没打上也不比(history):
    """判据从头短路到尾 / 打分一直失败：没判过就是没判过，不是「变差了」
    （批 3 的 `_regressed` 栽的正是这个）。"""
    history.append(_past({"beat_coverage": 2, "non_repetition": 2, "factual_grounding": 2}))
    st = _st({"beat_coverage": 1, "non_repetition": 1, "factual_grounding": 1})
    st.ev, st.bag["score_vectors"] = None, []
    assert _fire(st) == []
    # **连历史都不该去读。** 只断言「没发事件」的话这条测试是永远绿的：
    # 空分数向量走到 `compare()` 那儿也会被维度集合那一条挡掉，于是把守卫
    # 删掉它照样绿——一条抓不住任何突变的断言没有在断言任何东西（§21）。
    assert history.asked == []


@pytest.mark.parametrize("round_,stopped", [(0, "blocked"), (3, "awaiting_review")])
def test_不进历史的跑也不比(history, round_, stopped):
    history.append(_past({"beat_coverage": 2, "non_repetition": 2, "factual_grounding": 2}))
    assert _fire(_st({"beat_coverage": 1, "non_repetition": 1, "factual_grounding": 1},
                     round_=round_, stopped=stopped)) == []


# ------------------------------------------------------------ 只报，不替用户决定

def test_报完一个字都不许改(history):
    """计划第 4 节「不做」：不做跨跑自动回滚。"""
    history.append(_past({"beat_coverage": 2, "non_repetition": 2, "factual_grounding": 2}))
    st = _st({"beat_coverage": 2, "non_repetition": 1, "factual_grounding": 1})
    before, best_before = st.content, st.best
    assert _fire(st)
    assert st.content == before and st.best == best_before
    assert st.stopped == "complete", "这条规则不参与停机"


# ------------------------------------------------------------ 顺序

def test_必须排在History前面():
    """`History` 这一步就把这次跑写进 `harness_runs` 了，之后再读「最近一次」
    读到的是自己。这条依赖由 `_order.verify` 验，不靠注释——**而且它真的
    会红**：把两个换个位置试试。"""
    names = [getattr(m, "name", "") for m in BASE]
    assert names.index("cross_run") < names.index("history")
    verify(BASE)                                    # 现在这个顺序是合法的

    swapped = list(BASE)
    i, j = names.index("cross_run"), names.index("history")
    swapped[i], swapped[j] = swapped[j], swapped[i]
    with pytest.raises(OrderError):
        verify(swapped)
