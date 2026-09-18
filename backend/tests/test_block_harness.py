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
from app.harness.types import DimensionScore, Evaluation

from app.harness import agent_loop
from app.util import llm
from app.harness.tools import blocks
from app.harness.agent_loop import ToolTrace
from app.harness import loop, modes
from app.harness.hooks.block import BlockHooks
from app.harness.state import State
from app.harness.tools import ToolContext


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
    """前端没被这次重构碰过。少发一种帧的症状不是报错，是编辑器里什么都
    不动——所以这里检查一轮跑完真的发出了它需要的那几种。"""
    from app.harness.events import to_sse

    events, _ = _run(modes.CHART)
    names = {frame.split(": ", 1)[1].split("\n")[0]
             for frame in (to_sse(e) for e in events)}
    assert {"ACTIVITY_SNAPSHOT", "TEXT_MESSAGE_CONTENT", "TOOL_CALL_RESULT",
            "STEP_STARTED", "STEP_FINISHED", "RUN_FINISHED", "CUSTOM"} <= names


def test_a_tool_chart_is_not_reported_as_hand_written(stub):
    """charts_from_tools compares byte-for-byte against what the tools
    returned. If Facts stopped collecting them, every real chart would be
    rejected as a forgery and the run would never finish."""
    from app.harness.checks.blockcheck import mermaid_blocks, unauthorized_charts

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


def test_补图那一轮的停机和报错要折回主trace(monkeypatch):
    """批 22 / 计划 11.5。

    `eda` / `analysis` 声明了 `focus_groups`，第一轮没画出图时会再跑一次工具
    循环。那一次的 `ToolTrace` 原来只被手抄了两个字段（`calls` / `iters`），
    **`stopped_barren` / `error` / `truncated` / `barren_calls` 四个全丢**。
    各自都有读者：`middleware/runtime` 把 `stopped_barren` 喂给
    `policy.adjust`，那是「工具预算 -1」唯一的判据；`error` 更直接——
    `hooks/block` 本来就没有 `note` / `section` 那种 `trace.error and not facts`
    的降级，第二次调用整个失败会一点痕迹都没有。

    **闸钉在调用点**，不是 `ToolTrace.merge` 自己：把那一行换回手抄两行，
    `merge` 的逐字段闸照样全绿（台账 §21「一个在别处顺手被满足的断言，
    没有在断言任何东西」）。
    """
    seen = []

    async def gather(messages, ctx, *, groups=None, max_iters=3, **kw):
        seen.append(tuple(groups or ()))
        if len(seen) == 1:
            # 第一轮：查到了东西，但一张图都没画出来 → 触发 focus 那一轮
            return [], ToolTrace(calls=[("search_memory", {}, "[f-1] 材料")], iters=1)
        t = ToolTrace(calls=[("render_chart", {}, "（渲染失败）")], iters=1)
        t.stopped_barren = True
        t.truncated = True
        t.barren_calls = 2
        t.error = "RuntimeError: 补图那一轮挂了"
        return [], t

    monkeypatch.setattr(agent_loop, "gather_context", gather)
    st = State(mode=modes.EDA, ctx=ToolContext(user="u", note_id="n", content="", cursor=0))
    _facts, trace = asyncio.run(BlockHooks().prepare(st))

    assert len(seen) == 2, "前提：focus 那一轮真的跑了"
    assert trace.stopped_barren, "查到头了，策略器得看得见（否则预算永远收不回来）"
    assert trace.error, "第二次调用挂了，不能一点痕迹都没有"
    assert trace.truncated
    assert trace.barren_calls == 2
    assert trace.iters == 2 and len(trace.calls) == 2


def test_补图那一轮的工具组里不许出现事实类或广度类工具():
    """批 24 的 R2——**把一个「分母为 0」的决定钉住**。

    `hooks/block.prepare` 的第二发 `gather_context` 进去那一侧既不喂
    `known_ids` 也不接着数迭代：`seen_ids` 从空集起步（`BARREN_STOP` 失效）、
    `trace2.iters` 从 0 起步（`_cap_calls` 的深度门整个放开）。
    `hooks/note.py` 恰恰是特意把账本喂进来的，两处做法相反——形状上这正是
    §21「同一件事挡住一半等于没挡」。

    **但分母是 0，而且是结构性的 0**：这一发的 groups 写死成
    `mode.focus_groups`，而 `seen_ids` 只在 `name in FACT_TOOLS` 里被读、
    深度门只丢 `name in BREADTH_TOOLS`——focus 那一轮一个这样的工具都够不着。
    所以批 24 决定**不改**（批 22 的规矩：分母为 0 就写「不改」并说清理由），
    改成把这个分母变成一条会说话的断言。

    哪天有人给某个模式的 `focus_groups` 加上 `memory`，这条当场变红，
    那时候要做的正是把 `known_ids` 和迭代序号接上去，而不是删掉这条闸。
    """
    from app.harness import agent_loop as al
    from app.harness.tools import registry

    interesting = al.FACT_TOOLS | al.BREADTH_TOOLS
    checked = 0
    for mode in modes.ALL:
        groups = tuple(getattr(mode, "focus_groups", ()) or ())
        if not groups:
            continue
        checked += 1
        names = set(registry.names(list(groups)))
        assert names, f"{mode.key} 的 focus_groups 一个工具都注册不到：{groups}"
        overlap = sorted(names & interesting)
        assert not overlap, (
            f"{mode.key} 的补图那一轮够得着 {overlap}——"
            "这时候 hooks/block 必须把 known_ids 和迭代序号一起传进第二发 "
            "gather_context，否则 BARREN_STOP 和深度门在那一轮都是失效的")
    assert checked == 2, "声明了 focus_groups 的模式变了（原来是 EDA / ANALYSIS）"
