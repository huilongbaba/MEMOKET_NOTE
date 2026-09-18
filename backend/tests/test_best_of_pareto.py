"""批 22 / 计划 11.2：`best_of` 的标量折叠，以及它漏掉的那一半。

**折叠本身量完不做**（依据在 `middleware/best_of.py` 的模块注释里，数在
`scripts/best_of_pareto_probe.py` 跑得出来）：`harness_rounds` 447 轮 /
158 次跑里，`rank()` 挑的那一轮**一次都没有**被同跑里别的轮次 Pareto 支配。

**真被量出来的那一处**是 `loop._regressed` 的覆盖守卫只挡住一半：它会放过
「这一轮还没写够」的波动，却不会放过「最好那轮之所以排名高正因为它没写够」。
"""

from __future__ import annotations

import asyncio
import dataclasses

from app.harness import loop, modes
from app.harness.middleware.best_of import BestOf
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import DimensionScore, Evaluation

DIMS = ("spine_fidelity", "beat_coverage", "non_repetition",
        "factual_grounding", "coherence", "material_use")


def _st(round_=2, **kw):
    mode = dataclasses.replace(modes.NOTE, dims=DIMS, max_rounds=4, **kw)
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n", note_title="t"))
    st.round = round_
    return st


def _ev(**levels):
    return Evaluation(
        scores={d: DimensionScore(level=levels[d], note="") for d in DIMS},
        status="continue", weakest=min(levels, key=levels.get))


# 第 602/605 轮那次实拍的分数，逐字来自 `harness_rounds` 的 run `2d64b594db9b`
# （`note:309f19202309`）：第 1 轮 537 字、第 2 轮 1092 字。
ROUND1 = dict(spine_fidelity=2, beat_coverage=1, non_repetition=2,
              factual_grounding=2, coherence=2, material_use=2)
ROUND2 = dict(spine_fidelity=2, beat_coverage=2, non_repetition=1,
              factual_grounding=2, coherence=1, material_use=2)


def _replay(round1: dict, round2: dict) -> tuple[State, str | None]:
    """按真实顺序跑一遍：第 1 轮判分 → BestOf → 第 2 轮判分 → BestOf → 停机规则。"""
    st = _st(round_=1)
    st.ev, st.content = _ev(**round1), "第一轮写的"
    asyncio.run(BestOf().after_judge(st))
    st.round, st.ev, st.content = 2, _ev(**round2), "第一轮写的 第二轮又写的"
    asyncio.run(BestOf().after_judge(st))
    return st, loop._regressed(st)


def test_刚把覆盖写达标的那一轮不算退步():
    """实拍：第 1 轮 `beat_coverage=1` 拿 (5, 1.83)，第 2 轮把它写到 2、
    代价是 `non_repetition` / `coherence` 各掉一档拿 (4, 1.67)，
    `stopped=regressed` → 交出去的是第 1 轮的 537 字。"""
    st, hit = _replay(ROUND1, ROUND2)
    assert st.rank() < st.best[0], "前提：折叠之后这一轮的排名确实更低"
    assert hit is None, "最好那轮当时还没写够，不配当「退步」的基准"


def test_最好那轮已经写够了的退步照旧要拦():
    """**反向闸**：把守卫改成恒 True 也能让上面那条绿。这一条钉住「该停的
    还得停」——第 1 轮覆盖全达标、第 2 轮真的变差，那就是退步。"""
    good = dict(ROUND1, beat_coverage=2)                 # 覆盖全达标
    worse = dict(good, non_repetition=1, coherence=1)    # 纯变差，没换来任何东西
    st, hit = _replay(good, worse)
    assert st.rank() < st.best[0]
    assert hit == "regressed"


def test_BestOf记下最好那轮写够了没有():
    st = _st(round_=1)
    st.ev, st.content = _ev(**ROUND1), "残篇"
    asyncio.run(BestOf().after_judge(st))
    assert st.bag["best_coverage_unmet"] is True

    st.round, st.ev, st.content = 2, _ev(**dict(ROUND1, beat_coverage=2)), "写够了"
    asyncio.run(BestOf().after_judge(st))
    assert st.best[1] == "写够了", "前提：这一轮成了新的最好"
    assert st.bag["best_coverage_unmet"] is False, "换了 best 就要跟着换这个标记"


def test_覆盖标记进得了快照():
    """轮末暂停之后恢复的那次跑，`_regressed` 还得读得到它。"""
    from app.harness import snapshot

    st = _st(round_=1)
    st.ev, st.content = _ev(**ROUND1), "残篇"
    asyncio.run(BestOf().after_judge(st))
    back = snapshot.loads(snapshot.dumps(st), st.mode)
    assert back.bag["best_coverage_unmet"] is True


def test_探针脚本抄的覆盖维度名单跟实现一致():
    """`scripts/best_of_pareto_probe.py` 只连 sqlite、不 import app 包，
    所以那份名单是手抄的。抄错了整段④会安静地报 0。"""
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
    import best_of_pareto_probe as probe

    from app.harness.state import COVERAGE_DIMS
    assert tuple(probe.COVERAGE_DIMS) == tuple(COVERAGE_DIMS)


def test_探针复现的rank跟实现逐字一致():
    """③（602 那个形状还在不在）全靠「平手归后来者」复现得对。"""
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
    import best_of_pareto_probe as probe

    for levels in ({}, {"a": 0}, {"a": 2, "b": 1}, {"a": 2, "b": 2, "c": 0}):
        st = _st()
        st.ev = (Evaluation(scores={k: DimensionScore(level=v, note="")
                                    for k, v in levels.items()},
                            status="continue", weakest="a")
                 if levels else None)
        assert probe.rank(levels) == st.rank(), levels

    # 平手归后来者：三轮同分，best 必须是最后一轮
    rounds = [{"round": i, "sc": {"a": 0}, "content_len": i} for i in (1, 2, 3)]
    assert probe.best_of(rounds)["round"] == 3
