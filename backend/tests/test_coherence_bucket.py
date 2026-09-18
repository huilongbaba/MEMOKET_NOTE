"""`coherence` 不再当兜底桶，而且它只能停机（计划 4.4 + 4.5 / [MECH] §3、第 2 层 5）。

两件事是同一件事的两半：

* **4.4**：6 条判据把 `coherence` 写在候选的第二 / 第三位，于是
  `coherence = 0` 可能意味着审计腔、手写 mermaid、标题位置不对、表格列数
  对不上……**也可能真的是文章不连贯**。分数没有可操作的含义。
  现在兜底落到 `checks.pick.MECHANICS`——一个**不是评分维度**的桶。
* **4.5**：`coherence` 没有位置级探测器（量过，见
  `scripts/coherence_denominator.py`：148 个相邻标题对跳级 0 个、42 个兄弟组
  只有 1 组全带编号）。所以 `Repair` 不再为它排「只修不写」的修复轮——
  它的分数只能让回路停下来。

**这两条都必须是闸，不能是注释。** 4.4 那一半尤其：漏了不会报错，只会让
一个维度重新变成垃圾桶，而垃圾桶是安静地长回来的。
"""

from __future__ import annotations

import asyncio
import pathlib
import re

from app.harness import loop, modes
from app.harness.agent_loop import ToolTrace
from app.harness.checks.pick import MECHANICS, pick_dimension
from app.harness.middleware.repair import (INNER_QUALITY, STOP_ONLY, Repair,
                                           _REPAIRABLE)
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import DimensionScore, Evaluation

CHECKS_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "harness" / "checks"

# 一段会被 `no_fake_charts` 当场抓住的正文：用文字描述了一张图。
FAKE_CHART = "## 渠道\n[柱状图：各渠道点击量 Kickstarter：12700]\n"
# P8 起 `note` 不挂 `no_fake_charts`（不带 chart 组，续写整篇不画图），拿审计腔那条当
# 「落兜底桶的判据」的样本：note 没有 profile 时没有 `style_fit`，`no_audit_voice` 落桶。
AUDIT_VOICE = "## 渠道\n现有材料不足以说明这一点。\n"


def _note_state(content: str = AUDIT_VOICE) -> State:
    st = State(mode=modes.for_run(modes.NOTE), ctx=ToolContext(user="u", note_id="n"))
    st.content = st.fresh = content
    st.trace = ToolTrace()
    return st


# ------------------------------------------------------------- 4.4 ---


def test_没有任何判据再拿coherence当兜底():
    """**词法闸。** 盯的性质是「`coherence` 不再出现在候选名单里」——

    行为闸挡不住这一档：一条新判据把 `coherence` 写回候选第二位，在长文模式下
    它会被选中（长文真的有这一维），于是 `verdict.dimension in mode.dims` 成立、
    `test_每条check打翻的维度这个mode真的有` 照样绿，而垃圾桶原样长回来了。
    """
    offenders = []
    for path in sorted(CHECKS_DIR.glob("*.py")):
        for call in re.findall(r"pick_dimension\(\s*st\s*,([^)]*)\)", path.read_text()):
            if '"coherence"' in call or "'coherence'" in call:
                offenders.append(f"{path.name}: pick_dimension(st,{call.strip()})")
    assert not offenders, (
        "这几处又把 coherence 当兜底了——它是一个评分维度，不是垃圾桶。"
        "没有对应轴的判据该落到 checks.pick.MECHANICS：\n  " + "\n  ".join(offenders))


def test_一个候选都对不上时落进兜底桶而不是第一个候选():
    """退回第一个候选 = Evaluation 里冒出一个这个模式根本没有的维度名，
    而那正是 `pick_dimension` 存在的理由。"""
    st = _note_state()
    assert pick_dimension(st, "has_charts", "chart_validity") == MECHANICS
    # 对得上的时候照旧
    assert pick_dimension(st, "has_charts", "coherence") == "coherence"


def test_兜底桶不是任何一个mode的评分维度():
    """打分器永远不该看见它，也永远不会打它。"""
    for mode in modes.ALL:
        shaped = modes.for_run(mode, has_profile=True)
        assert MECHANICS not in {d.name for d in shaped.dims}, shaped.key


def test_兜底桶既不排修复轮也不算写得不够():
    """它落在两条执行器选择规则之外，这是它跟 `coherence` 最要紧的区别：
    第 606 轮那次死锁就是「判据说去调工具画图、修复策略说这一轮不许写」。"""
    assert MECHANICS not in INNER_QUALITY
    assert MECHANICS not in loop.COVERAGE_DIMS


def test_判据命中时不再往coherence头上记一笔0分():
    """**端到端**：长文模式下图表判据命中，`Evaluation` 里不许出现 coherence。

    实测的污染面：`harness_rounds` 的 354 轮里 222 轮是判据短路的（62.7%），
    落点里有 1 轮是 `coherence`——那一轮 `coherence` 被记了 0 分，而正文连贯
    与否根本没人看过。它会进分数统计、进 `weakest`、进下一轮的诊断标签。
    """
    from app.harness.middleware.checks import Checks

    st = _note_state()
    events = asyncio.run(_drain(Checks().before_judge(st)))
    assert st.skip_judge and st.ev is not None
    assert "coherence" not in st.ev.scores
    assert set(st.ev.scores) == {MECHANICS}
    assert any((e.data or {}).get("value", {}).get("dimension") == MECHANICS
               for e in events)


async def _drain(gen):
    return [e async for e in gen]


# ------------------------------------------------------------- 4.5 ---


def test_两个集合加起来正好是内在质量且不重叠():
    """拆成两半之后最容易出的错：改了一边忘了另一边，于是某一维两边都不在，
    既排不了修复轮，也不算"只能停机"——它会安静地什么都不做。"""
    assert set(_REPAIRABLE) | set(STOP_ONLY) == set(INNER_QUALITY)
    assert not (set(_REPAIRABLE) & set(STOP_ONLY))
    assert STOP_ONLY == ("coherence",)


def test_只有coherence不达标时不排修复轮():
    """没有位置级探测器的维度排出来的修复轮，修订那一步手上一个候选都没有
    ——[MECH] 第二节那条链的终点。实测支持：347 个 note 轮次里「只剩
    coherence 不达标」只有 2 轮，连着两轮的 0 轮。"""
    st = _note_state()
    st.ev = Evaluation(
        scores={"coherence": DimensionScore(level=0, note="读着有两个结尾"),
                "non_repetition": DimensionScore(level=2, note=""),
                "factual_grounding": DimensionScore(level=2, note="")},
        status="continue", weakest="coherence")
    events = asyncio.run(_drain(Repair().after_judge(st)))
    assert st.bag["cleanup_only"] is False
    # 但它必须**看得见**：驱动不了任何东西的维度，更不能连报都不报。
    payload = next((e.data or {})["value"] for e in events)
    assert payload.get("stop_only") == ["coherence"]
    assert payload["dimensions"] == []


def test_有探测器的那几维照旧排修复轮():
    """4.5 只摘掉 coherence 这一条路，不许顺手把 `non_repetition` /
    `topic_fidelity` 一起摘了——那两条是批 2 / 批 3 花了两批才接上的。"""
    st = _note_state()
    st.ev = Evaluation(
        scores={"coherence": DimensionScore(level=0, note=""),
                "non_repetition": DimensionScore(level=0, note="说了两遍"),
                "factual_grounding": DimensionScore(level=2, note="")},
        status="continue", weakest="non_repetition")
    asyncio.run(_drain(Repair().after_judge(st)))
    assert st.bag["cleanup_only"] is True


def test_coherence达标时不报stop_only():
    """报出来的必须是「这一维这一轮真的没达标」，不是「这一维存在」。"""
    st = _note_state()
    st.ev = Evaluation(
        scores={"coherence": DimensionScore(level=2, note=""),
                "non_repetition": DimensionScore(level=2, note="")},
        status="complete")
    events = asyncio.run(_drain(Repair().after_judge(st)))
    assert not events
