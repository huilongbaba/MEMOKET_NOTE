"""The loop, driven by fake hooks and a fake scorer.

The point of this file is that it needs no model. Verifying a loop change
used to mean running a real harness -- minutes, and non-deterministic. Here
the whole behavioural surface is exercised in milliseconds, deterministically.

Every scenario below is a property the architecture claims. If one of them
stops holding, the claim was wrong or the code drifted.
"""

from __future__ import annotations

import asyncio

import pytest
from app.harness.types import Dimension, DimensionScore, Evaluation

from app.harness import State
from app.harness.loop import run
from app.harness.middleware import BASE, OrderError, verify
from app.harness.types import Mode, Verdict
from app.harness.tools import ToolContext


class FakeHooks:
    """produce() owns updating st.content -- that's the contract."""

    def __init__(self, texts: list[str]):
        self.texts = texts
        self.saved: list[str] = []
        self.prepared = 0

    async def prepare(self, st):
        self.prepared += 1
        return [f"fact-{st.round}"], _FakeTrace()

    async def produce(self, st):
        text = self.texts[min(st.round, len(self.texts)) - 1]
        for ch in text:
            yield ch
        st.content = text

    async def commit(self, st):
        self.saved.append(st.content)


class _FakeTrace:
    calls: list = []
    used = False
    iters = 0


def _scorer(levels_per_round: list[list[int]]):
    async def score(st):
        levels = levels_per_round[min(st.round, len(levels_per_round)) - 1]
        scores = {f"d{i}": DimensionScore(level=v, note="") for i, v in enumerate(levels)}
        status = "complete" if all(v >= 2 for v in levels) else "continue"
        return Evaluation(scores=scores, status=status,
                          weakest=None if status == "complete" else "d0")
    return score


def _mode(**kw) -> Mode:
    kw.setdefault("dims", (Dimension("d0", "..."),))
    return Mode(key="t", label="test", skill_scope="test_scope", **kw)


async def _drive(st, hooks, scorer, mw=()):
    """Run to completion with scoring stubbed out."""
    import app.harness.loop as loop_mod
    original, loop_mod._score = loop_mod._score, scorer
    try:
        return [e async for e in run(st, hooks, mw=mw)]
    finally:
        loop_mod._score = original


def _state(mode: Mode) -> State:
    return State(mode=mode, ctx=ToolContext(user="u", note_id="n"), request=None)


def _finished(events):
    return next(e for e in events if e.type.value == "RUN_FINISHED")


# --------------------------------------------------------------- tests ---

def test_completes_early_when_every_dimension_meets_the_bar():
    hooks = FakeHooks(["a", "b", "c"])
    st = _state(_mode())
    events = asyncio.run(_drive(st, hooks, _scorer([[1, 2], [2, 2], [2, 2]])))
    done = _finished(events)
    assert done.data["reason"] == "complete"
    assert done.data["content"] == "b"
    assert st.round == 2


def test_out_of_rounds_ships_the_best_round_not_the_last():
    """Running out means never meeting the bar -- which is exactly when the
    final round is least likely to be the good one. Observed for real: round
    two produced two clean charts, round three added a pointless one to
    satisfy the scorer, round three shipped."""
    hooks = FakeHooks(["a", "bb", "c"])
    st = _state(_mode(max_rounds=3))
    events = asyncio.run(_drive(st, hooks, _scorer([[1, 1], [2, 1], [0, 1]]),
                                mw=BASE))
    done = _finished(events)
    assert done.data["reason"] == "max_rounds"
    assert done.data["content"] == "bb"


def test_a_failing_check_skips_the_scoring_call():
    """A scoring call costs tens of seconds. If a deterministic rule already
    knows the answer, paying for it is waste."""
    calls: list[int] = []

    async def counting(st):
        calls.append(st.round)
        return Evaluation({"d0": DimensionScore(2, "")}, "complete")

    def always_fails(st):
        return Verdict("d0", "no charts here")

    hooks = FakeHooks(["x"] * 3)
    st = _state(_mode(checks=(always_fails,), max_rounds=3))
    events = asyncio.run(_drive(st, hooks, counting, mw=BASE))
    assert calls == []
    assert sum(1 for e in events if e.data.get("name") == "check_hit") == 3


def test_a_fix_that_works_is_kept_and_does_not_fail_the_round():
    # NB the naive fix ``s.replace("## ", "### ")`` does *not* work here:
    # "## " is a substring of "### ", so the check still fires afterwards and
    # the rollback correctly undoes it. Sinking has to be done as a regex on
    # the heading prefix -- which is what checks/structure.py actually does.
    import re

    def needs_sinking(st):
        if re.search(r"^#{1,2}\s", st.content, re.M):
            return Verdict("fits", "heading too shallow",
                           fix=lambda s: re.sub(r"^(#{1,5})(\s)", r"#\1\2", s, flags=re.M))
        return None

    hooks = FakeHooks(["## Title"])
    st = _state(_mode(checks=(needs_sinking,), max_rounds=1))
    events = asyncio.run(_drive(st, hooks, _scorer([[2]]), mw=BASE))
    assert st.content == "### Title"
    assert not any(e.data.get("name") == "check_hit" for e in events)


def test_a_fix_that_does_not_work_is_rolled_back():
    """Found by running the prototype; three passes of reading the design on
    paper had missed it. A fix that leaves the check still failing must not
    leave its edit behind -- the next round would build on text that was
    modified and is still wrong."""
    def unfixable(st):
        if "bad" in st.content:
            return Verdict("d0", "cannot repair", fix=lambda s: s + " (mangled)")
        return None

    hooks = FakeHooks(["bad text"])
    st = _state(_mode(checks=(unfixable,), max_rounds=1))
    events = asyncio.run(_drive(st, hooks, _scorer([[2]]), mw=BASE))
    assert st.content == "bad text"
    assert any(e.data.get("name") == "check_hit" for e in events)


def test_one_middleware_blowing_up_does_not_kill_the_run():
    class Boom:
        name = "boom"
        hooks = ("after_round",)
        after: tuple = ()

        async def after_round(self, st):
            raise RuntimeError("I am broken")

    hooks = FakeHooks(["a"])
    st = _state(_mode(max_rounds=1))
    events = asyncio.run(_drive(st, hooks, _scorer([[2]]), mw=(Boom(),)))
    warnings = [e for e in events if e.data.get("name") == "warning"]
    assert len(warnings) == 1
    assert warnings[0].data["value"]["middleware"] == "boom"
    assert any(e.type.value == "RUN_FINISHED" for e in events)


def test_text_messages_are_paired_one_per_round():
    """AG-UI rejects two STARTs in a row, so a retry has to open a new message
    rather than continue the old one."""
    hooks = FakeHooks(["ab", "cd"])
    st = _state(_mode(max_rounds=2))
    events = asyncio.run(_drive(st, hooks, _scorer([[1], [2]]), mw=BASE))
    seq = [e.type.value for e in events
           if e.type.value.startswith("TEXT_MESSAGE")]
    assert seq.count("TEXT_MESSAGE_START") == 2
    assert seq.count("TEXT_MESSAGE_END") == 2
    depth = 0
    for name in seq:
        if name == "TEXT_MESSAGE_START":
            depth += 1
        elif name == "TEXT_MESSAGE_END":
            depth -= 1
        assert depth in (0, 1), "messages must not nest or close twice"


def test_facts_accumulate_and_stay_under_the_budget():
    hooks = FakeHooks(["a"] * 8)
    st = _state(_mode(max_rounds=8, fact_budget=3))
    asyncio.run(_drive(st, hooks, _scorer([[1]] * 8), mw=BASE))
    assert len(st.facts) == 3
    assert st.facts[-1] == "fact-8"


def test_a_stop_condition_from_the_mode_is_honoured():
    def stop_after_two(st):
        return "custom_stop" if st.round >= 2 else None

    hooks = FakeHooks(["a"] * 5)
    st = _state(_mode(max_rounds=5, stop_when=(stop_after_two,)))
    events = asyncio.run(_drive(st, hooks, _scorer([[1]] * 5), mw=BASE))
    assert _finished(events).data["reason"] == "custom_stop"


def test_rails_off_removes_a_base_capability():
    """Turning one off is allowed, but has to be written down -- see the
    parity test that asserts no Mode actually does it."""
    hooks = FakeHooks(["a", "b"])
    st = _state(_mode(max_rounds=2, rails_off=("best_of",)))
    events = asyncio.run(_drive(st, hooks, _scorer([[2, 1], [0, 0]]), mw=BASE))
    # Without BestOf there is nothing to fall back to, so the last round ships
    assert _finished(events).data["content"] == "b"
    assert st.best is None


def test_declared_ordering_is_enforced():
    class First:
        name = "first"
        hooks = ("before_produce",)
        after: tuple = ()

    class Second:
        name = "second"
        hooks = ("before_produce",)
        after = ("first",)

    verify((First(), Second()))                       # correct order: fine
    with pytest.raises(OrderError):
        verify((Second(), First()))                   # reversed: caught


def test_ordering_only_matters_within_a_shared_hook():
    class A:
        name = "a"
        hooks = ("before_produce",)
        after: tuple = ()

    class B:
        name = "b"
        hooks = ("after_judge",)      # different hook; the loop orders these
        after = ("a",)

    verify((B(), A()))                # no complaint


# ------------------------------------------------- 洋葱包装的两个扩展点 ---
#
# wrap_prepare / wrap_produce 在 Middleware 协议里声明、在 loop 里实现、
# 在 harness-framework.md 里当作设计过的扩展点写着（重试、短路、改写
# 进出），**但生产里一个使用者都没有，测试里一条覆盖都没有**——只在
# docs/_research 的原型里出现过。
#
# 一个从没被验证过的扩展点，第一次有人用的时候大概率是坏的。这两条测试
# 就是让它「有人用过」：文档承诺的三件事（多次调 handler、根本不调、
# 改写进出）在真实循环里各验一遍。


def test_wrap_prepare_能重试也能短路():
    class Retry:
        name = "retry"
        hooks: tuple = ()
        after: tuple = ()

        def __init__(self):
            self.calls = 0

        async def wrap_prepare(self, st, handler):
            self.calls += 1
            facts, trace = await handler(st)       # 第一次
            facts2, _ = await handler(st)          # 再来一次：多次调是允许的
            return facts + facts2, trace

    class Cached:
        name = "cached"
        hooks: tuple = ()
        after: tuple = ()

        async def wrap_prepare(self, st, handler):
            return ["缓存里的材料"], _FakeTrace()   # 根本不调 handler

    hooks = FakeHooks(["a"])
    st = _state(_mode(max_rounds=1))
    asyncio.run(_drive(st, hooks, _scorer([[2, 2]]), mw=(Retry(),)))
    assert hooks.prepared == 2, "wrap_prepare 调了两次 handler，取材料该跑两遍"
    assert st.facts_new == ["fact-1", "fact-1"]   # 累积到 st.facts 是 Facts 那条 middleware 的活，这里没挂它

    hooks = FakeHooks(["a"])
    st = _state(_mode(max_rounds=1))
    asyncio.run(_drive(st, hooks, _scorer([[2, 2]]), mw=(Cached(),)))
    assert hooks.prepared == 0, "短路了却还是调到了 handler"
    assert st.facts_new == ["缓存里的材料"]


def test_wrap_produce_能改写流出去的内容():
    class Upper:
        name = "upper"
        hooks: tuple = ()
        after: tuple = ()

        def wrap_produce(self, st, handler):
            async def gen():
                async for piece in handler(st):
                    yield piece.upper()
                st.content = st.content.upper()
            return gen()

    hooks = FakeHooks(["abc"])
    st = _state(_mode(max_rounds=1))
    events = asyncio.run(_drive(st, hooks, _scorer([[2, 2]]), mw=(Upper(),)))
    deltas = "".join(e.data["delta"] for e in events
                     if e.type.value == "TEXT_MESSAGE_CONTENT")
    assert deltas == "ABC", f"流出去的是 {deltas!r}"
    assert _finished(events).data["content"] == "ABC"


def test_regressed_stops_early_and_ships_the_best():
    """Round 1 nearly meets the bar (one dimension short), round 2 is worse:
    stop right there and ship round 1 -- don't burn round 3. Observed for
    real with 智能表格: round 1 had a good table, rounds 2 and 3 wrote
    "[tool call needed]" and no table."""
    hooks = FakeHooks(["good", "worse", "never"])
    st = _state(_mode(dims=(Dimension("d0", "."), Dimension("d1", "."), Dimension("d2", ".")), max_rounds=3))
    events = asyncio.run(_drive(st, hooks, _scorer([[2, 2, 1], [0, 2, 1], [2, 2, 2]]), mw=BASE))
    done = _finished(events)
    assert done.data["reason"] == "regressed"
    assert done.data["content"] == "good"
    assert st.round == 2 and hooks.prepared == 2


def test_regressed_does_not_fire_when_the_best_was_far_from_the_bar():
    """Two dimensions short is not "nearly there": a worse round is just noise, keep going."""
    hooks = FakeHooks(["a", "b", "c"])
    st = _state(_mode(dims=(Dimension("d0", "."), Dimension("d1", "."), Dimension("d2", ".")), max_rounds=3))
    events = asyncio.run(_drive(st, hooks, _scorer([[2, 1, 1], [0, 1, 1], [2, 2, 2]]), mw=BASE))
    assert _finished(events).data["reason"] == "complete" and st.round == 3
