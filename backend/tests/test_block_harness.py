"""The `/` block harness end to end, with the model and the tools stubbed.

What this file protects is the *seam*: the router no longer contains a loop,
so the only way a block still comes out is if Mode data, the shared loop, the
BlockHooks callbacks and the legacy event translation all line up. Each of
those moved in the refactor, and a mismatch between any two of them would
show up here rather than in a browser.
"""

from __future__ import annotations

import asyncio

import pytest
from app.scoring import DimensionScore, Evaluation

from app import agent_loop, blocks, llm
from app.agent_loop import ToolTrace
from app.harness import loop, modes
from app.harness.hooks.block import BlockHooks
from app.harness.state import State
from app.tools import ToolContext


def _passing(content, dimensions, **kw):
    return Evaluation(
        scores={d.name: DimensionScore(level=2, note="ok") for d in dimensions},
        status="complete", weakest=None)


@pytest.fixture
def stub(monkeypatch):
    """One tool call that really draws, one round of generation, a clean score."""
    chart = blocks.mermaid_xy("曝光", ["a", "b"], [1, 2])

    async def gather(messages, ctx, *, groups=None, max_iters=3, **kw):
        trace = ToolTrace(calls=[("render_chart", {"kind": "bar"}, chart)], iters=1)
        return [], trace

    async def stream(messages, **kw):
        yield "渠道对比如下。\n\n"
        yield chart

    async def score(st):
        return _passing(st.content, st.mode.dims)

    monkeypatch.setattr(agent_loop, "gather_context", gather)
    monkeypatch.setattr(llm, "stream", stream)
    monkeypatch.setattr(loop, "_score", score)
    return chart


def _run(mode, hooks=None, **state_kw):
    st = State(mode=mode,
               ctx=ToolContext(user="u", note_id="n", content="", cursor=0),
               **state_kw)
    async def go():
        return [e async for e in loop.run(st, hooks or BlockHooks())], st
    return asyncio.run(go())


def test_a_chart_block_comes_out_of_the_shared_loop(stub):
    events, st = _run(modes.CHART)
    assert stub in st.content
    kinds = [e.type.value for e in events]
    assert kinds[0] == "RUN_STARTED" and kinds[-1] == "RUN_FINISHED"
    assert events[-1].data["reason"] == "complete"


def test_the_frames_the_frontend_listens_for_still_arrive(stub):
    """The frontend was not touched by this refactor. If the translation drops
    a frame the editor shows nothing streaming, or never inserts the block."""
    from app.harness.events import legacy_frames

    events, _ = _run(modes.CHART)
    names = {line.split(": ", 1)[1]
             for e in events for frame in legacy_frames(e)
             for line in frame.splitlines() if line.startswith("event: ")}
    assert {"phase", "delta", "tool-calls", "evaluate", "round-end",
            "done"} <= names


def test_a_tool_chart_is_not_reported_as_hand_written(stub):
    """charts_from_tools compares byte-for-byte against what the tools
    returned. If Facts stopped collecting them, every real chart would be
    rejected as a forgery and the run would never finish."""
    from app.blockcheck import mermaid_blocks, unauthorized_charts

    _events, st = _run(modes.CHART)
    assert st.charts == mermaid_blocks(stub)          # fence stripped, body kept
    assert not unauthorized_charts(st.content, st.charts)


def test_each_round_replaces_the_block_rather_than_appending(monkeypatch, stub):
    """A block is rewritten every round. Appending would grow it without
    bound -- that is the long-form merge rule, and it lives in a different
    produce()."""
    async def failing(st):
        return Evaluation(scores={"fits_context": DimensionScore(level=0, note="no")},
                          status="continue", weakest="fits_context")

    monkeypatch.setattr(loop, "_score", failing)
    _events, st = _run(modes.CHART)
    assert st.content.count("渠道对比如下。") == 1


def test_the_users_selection_reaches_the_prompt(stub):
    hooks = BlockHooks(prompt="改得短一点", selection="要被替换掉的这一段",
                       title="标题")
    st = State(mode=modes.CUSTOM,
               ctx=ToolContext(user="u", note_id="n", content="", cursor=0))
    text = hooks._user(st, facts="")
    assert "要被替换掉的这一段" in text and "改得短一点" in text
    assert modes.CUSTOM.task in text
