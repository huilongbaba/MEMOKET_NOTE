"""判据卡死之后要放行。

第 601 轮真跑读出来的死锁：`no_placeholder` 每轮都拿正文**第一段**（这次
续写根本没碰的旧文字）打回，四轮全打回，`scores` 里从头到尾只有一项——
打分器一次都没跑起来，`complete` 结构上就到不了。修订那一步是试过的：
模型第 2/3/4 轮都提了针对那段的修订，每次都被空改守卫丢掉。判据说改、
模型改、守卫丢，合起来是个谁也出不去的环。

所以测的是这条性质：**同一条判据原样卡满 STUCK_ROUNDS 轮之后，不再短路
打分**，但事件照发。
"""

from __future__ import annotations

import pytest

from app.harness.middleware.checks import STUCK_ROUNDS, Checks
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import Dimension, Mode, Verdict


def _st(checks) -> State:
    mode = Mode(key="t", label="t", skill_scope="test_scope",
                dims=(Dimension("factual_grounding", "..."),
                      Dimension("style_fit", "...")),
                checks=tuple(checks))
    return State(mode=mode, ctx=ToolContext(user="u", note_id="n"))


async def _round(st: State) -> list:
    st.ev, st.skip_judge = None, False
    return [e async for e in Checks().before_judge(st)]


def _always(dimension: str, message: str):
    return lambda st: Verdict(dimension, message)


@pytest.mark.anyio
async def test_同一条判据卡满之后不再短路打分():
    st = _st([_always("factual_grounding", "第一段有占位句")])

    for n in range(1, STUCK_ROUNDS + 1):
        evs = await _round(st)
        assert st.skip_judge, f"第 {n} 轮就该拦住——拦几轮是给修订的机会"
        assert len(evs) == 1

    evs = await _round(st)
    assert not st.skip_judge, "卡满了还拦，就是把剩下的轮数烧掉"
    assert st.ev is None, "不短路就不能自己写好 Evaluation，那是打分器的活"
    assert evs[0].data["value"]["stuck_rounds"] == STUCK_ROUNDS + 1, "事件要照发"


@pytest.mark.anyio
async def test_中间改好过一轮计数就断():
    """它是「连着卡了几轮」，不是「累计报过几次」。"""
    fires = iter([True, True, False, True, True])
    st = _st([lambda st: Verdict("factual_grounding", "同一句话")
              if next(fires) else None])

    await _round(st); await _round(st)
    await _round(st)                      # 这一轮没报 → 断
    for _ in range(2):
        assert (await _round(st)) and st.skip_judge, "断过之后要重新数满才放行"


@pytest.mark.anyio
async def test_原话变了就重新数():
    """判据原话里带着出问题的那一行；原话变了说明那一行动过了。"""
    msgs = iter(["占位句：A", "占位句：A", "占位句：B", "占位句：B"])
    st = _st([lambda st: Verdict("factual_grounding", next(msgs))])

    for _ in range(4):
        await _round(st)
        assert st.skip_judge, "每次都是新报的，不该被当成卡死"


@pytest.mark.anyio
async def test_卡死的那条放行之后后面的判据还能拦():
    """短路本来就是为了「一次只给一个清楚的指令」——这条动不了，
    不等于后面那条也动不了。"""
    st = _st([_always("factual_grounding", "改不动的老问题"),
              _always("style_fit", "这一轮新写出来的问题")])

    for _ in range(STUCK_ROUNDS):
        await _round(st)
    evs = await _round(st)

    assert st.skip_judge and st.ev is not None
    assert st.ev.weakest == "style_fit", "该轮到后面那条说话了"
    assert [e.data["value"]["dimension"] for e in evs] == \
        ["factual_grounding", "style_fit"], "两条都要让用户看见"


def test_笔记原来就有的图不算这一轮手写的():
    """第 604 轮真跑实拍的内容损毁。

    `st.charts` 只记**这一次跑**里工具画过的图，于是用户自己画的、或上一次
    跑留下的 mermaid 每一轮都被判成「模型手写的、模仿工具输出」——两张语法
    完全正确的流程图就这样被修订那一步整个删掉，删完下一轮又报「这条流程是
    用箭头串在正文里的，不是一张图」，删图和要图来回打架。

    判据只该管这次跑写出来的东西；对开跑时就在的图，那句指控本身是假的。
    """
    from app.harness.checks.charts import charts_from_tools

    old = "```mermaid\ngraph TD\nA[5G切换至2.4G] --> B[完成通信验证]\n```"
    mine = "```mermaid\ngraph TD\nX[我自己编的] --> Y[语法未验证]\n```"

    st = _st([])
    st.bag["content_at_start"] = "一段正文。\n\n" + old
    st.content = st.bag["content_at_start"]
    assert charts_from_tools(st) is None, "开跑时就在的图不是这一轮手写的"

    st.content += "\n\n" + mine
    v = charts_from_tools(st)
    assert v is not None and "我自己编的" in v.message, "这一轮新写的手写图照样要拦"

    # 没记开跑快照的老路径（别的 harness / 单测）不能因此崩掉
    st2 = _st([]); st2.content = old
    assert charts_from_tools(st2) is not None
