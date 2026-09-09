"""策略这两条 middleware 的**接线**。

底下的纯逻辑（`harness/policy.py` 99%、`harness/replan_rules.py` 100%）
测得很满，可把它们接到 State 上的这一层几乎空白：runtime 50%、replan 34%。

接线层正是字段映射错误的藏身处——这个 run 里已经撞过一次同类的：打分
读的是第三批检索回来的事实，于是它对着写作者刚用过的一句话报「知识库里
没有」。这种错不会抛异常，只会让策略照着错的观测调参。
"""

from __future__ import annotations

import asyncio

import pytest

from app.harness.middleware.replan import MAX_REPLANS_PER_RUN, Replan
from app.harness.middleware.runtime import Runtime
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import Dimension, DimensionScore, Evaluation, Mode


def _st(**bag) -> State:
    mode = Mode(key="t", label="t", skill_scope="test_scope",
                dims=(Dimension("coherence", "..."),))
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n", note_title="标题"))
    st.round = 2
    st.bag.update(bag)
    return st


def _drive(coro_gen):
    async def go():
        return [e async for e in coro_gen]
    return asyncio.run(go())


class _Trace:
    def __init__(self, calls, truncated=False):
        self.calls = calls
        self.truncated = truncated


# ------------------------------------------------------------- runtime ---

def test_喂给策略的观测取自正确的字段(monkeypatch):
    """这条测试的全部意义是**字段对不对**：本轮新查到的事实要用
    ``facts_new``（不是累积的 ``facts``），工具次数取自 trace，改了几条取自
    ``revisions_applied``。取错一个，策略就按着一个不存在的局面调参。
    """
    from app.harness.middleware import runtime as mod

    seen = {}

    def fake_adjust(policy, feedback):
        seen["fb"] = feedback
        return policy, []

    monkeypatch.setattr(mod.runtime_policy, "adjust", fake_adjust)

    st = _st(revisions_applied=3, stall_rounds=1)
    st.ev = Evaluation(
        scores={"coherence": DimensionScore(level=1, note="有点散"),
                "non_repetition": DimensionScore(level=2, note="")},
        status="continue", weakest="coherence")
    st.facts = ["累积的一", "累积的二", "累积的三", "累积的四"]
    st.facts_new = ["这一轮新查到的"]
    st.trace = _Trace([("recall", {}, "x"), ("list_topics", {}, "y")], truncated=True)

    _drive(Runtime().after_judge(st))
    fb = seen["fb"]
    assert fb.scores == {"coherence": 1, "non_repetition": 2}
    assert fb.notes["coherence"] == "有点散"
    assert fb.weakest == "coherence" and fb.status == "continue"
    assert fb.tool_calls == 2 and fb.tool_truncated is True
    assert fb.tools_used == ("list_topics", "recall")
    assert fb.tool_facts == 1, "该数这一轮新查到的，不是累积的四条"
    assert fb.revisions_applied == 3 and fb.stall_rounds == 1


def test_没打分就不调参(monkeypatch):
    """打分失败的那一轮 ev 是 None。按一个不存在的观测调参比不调更糟。"""
    from app.harness.middleware import runtime as mod

    monkeypatch.setattr(mod.runtime_policy, "adjust",
                        lambda *a: pytest.fail("不该调到这儿"))
    assert _drive(Runtime().after_judge(_st())) == []


def test_开跑前按历史记录定初始策略(monkeypatch):
    """同一篇笔记连着三次以同样的方式失败，第四次不能还用那套设置开跑。"""
    from app.harness.middleware import runtime as mod

    class FakeStore:
        def recent(self, key, limit=3):
            assert key == "n" and limit == 3
            return ["历史记录"]

    monkeypatch.setattr(mod.harness_adapter, "SqliteRunHistoryStore", FakeStore)
    sentinel = object()
    monkeypatch.setattr(mod.runtime_policy, "from_history",
                        lambda runs: (type("P", (), {"snapshot": lambda self: {"tool_iters": 4}})(),
                                      ["上次卡在同一个地方"]))
    st = _st()
    events = _drive(Runtime().before_run(st))
    assert st.bag["policy"] is not None
    (payload,) = [e.data["value"] for e in events if e.data.get("name") == "policy"]
    assert payload["round"] == 0, "开跑前那次没有对应轮次，挂在第 0 轮"
    assert payload["reasons"] == ["上次卡在同一个地方"]
    _ = sentinel


# -------------------------------------------------------------- replan ---

def _replanning(monkeypatch, ops, *, should=True, why="卡住了"):
    from app.harness.middleware import replan as mod

    monkeypatch.setattr(mod.replan_rules, "should_replan",
                        lambda **kw: (should, why))

    async def fake_complete(messages, **kw):
        import json
        return json.dumps(ops, ensure_ascii=False)

    monkeypatch.setattr(mod.llm, "complete", fake_complete)


def test_改骨架之后骨架面板要跟着变(monkeypatch):
    """run 的目标刚刚被改了，用户必须看得见改成了什么——所以除了 replan
    事件还要再发一个 skeleton 事件。"""
    _replanning(monkeypatch, [{"op": "rewrite", "index": 1, "text": "换一个节拍"}])
    st = _st(beats=["起", "承", "转"], spine="核心张力")
    st.ev = Evaluation(scores={"coherence": DimensionScore(level=0, note="")},
                       status="continue", weakest="coherence")
    events = _drive(Replan().after_judge(st))
    names = [e.data.get("name") for e in events]
    assert names == ["replan", "skeleton"]
    assert st.bag["beats"] != ["起", "承", "转"]
    assert st.bag["replans_used"] == 1
    assert events[1].data["value"]["spine"] == "核心张力"


def test_大纲模式下不许改骨架(monkeypatch):
    """标题是用户自己写的，改骨架等于改用户的大纲。"""
    _replanning(monkeypatch, [{"op": "rewrite", "index": 1, "text": "换"}])
    st = _st(beats=["起", "承"], outline_mode=True)
    st.ev = Evaluation(scores={"coherence": DimensionScore(level=0, note="")},
                       status="continue", weakest="coherence")
    assert _drive(Replan().after_judge(st)) == []


def test_一次run最多改两次骨架(monkeypatch):
    _replanning(monkeypatch, [{"op": "rewrite", "index": 1, "text": "换"}])
    st = _st(beats=["起", "承"], replans_used=MAX_REPLANS_PER_RUN)
    st.ev = Evaluation(scores={"coherence": DimensionScore(level=0, note="")},
                       status="continue", weakest="coherence")
    assert _drive(Replan().after_judge(st)) == []


def test_没有节拍就没有骨架可改(monkeypatch):
    """空节拍表不是「改一改」，是让模型凭空造一份骨架——那是另一件事。"""
    _replanning(monkeypatch, [{"op": "rewrite", "index": 1, "text": "换"}])
    st = _st(beats=[])
    st.ev = Evaluation(scores={"coherence": DimensionScore(level=0, note="")},
                       status="continue", weakest="coherence")
    assert _drive(Replan().after_judge(st)) == []


def test_改骨架的调用挂了不影响这一轮(monkeypatch):
    from app.harness.middleware import replan as mod

    monkeypatch.setattr(mod.replan_rules, "should_replan", lambda **kw: (True, "卡住"))

    async def boom(messages, **kw):
        raise RuntimeError("超时")

    monkeypatch.setattr(mod.llm, "complete", boom)
    st = _st(beats=["起", "承"])
    st.ev = Evaluation(scores={"coherence": DimensionScore(level=0, note="")},
                       status="continue", weakest="coherence")
    events = _drive(Replan().after_judge(st))
    assert st.bag["beats"] == ["起", "承"], "骨架不该被动"
    assert any("replan failed" in r
               for e in events for r in e.data["value"].get("reasons", []))


def test_模型没提出有效改动就什么都不做(monkeypatch):
    _replanning(monkeypatch, [{"op": "不认识的操作", "index": 1}])
    st = _st(beats=["起", "承"])
    st.ev = Evaluation(scores={"coherence": DimensionScore(level=0, note="")},
                       status="continue", weakest="coherence")
    assert _drive(Replan().after_judge(st)) == []
    assert "replans_used" not in st.bag, "没改成就不该消耗次数"
