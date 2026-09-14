"""Run the Mode's deterministic checks, before paying for a scoring call.

Ordering matters here and it used to be backwards: scoring ran first, then
the checks, so whenever a check fired the scoring call had been wasted. A
scoring call is tens of seconds against a local model.

(PydanticAI does the same thing for the same reason: schema validation is
free and runs first, semantic validation costs I/O and runs second.)
"""

from __future__ import annotations

from typing import AsyncIterator

import dataclasses

from ..types import DimensionScore, Evaluation

from ..events import CUSTOM_CHECK_HIT, Event
from ..state import State


# 同一条判据原样卡住几轮之后就不再拦路。第 601 轮真跑读出来的死锁：
# `no_placeholder` 每一轮都拿正文**第一段**（这次续写根本没碰的旧文字）
# 打回，4 轮全打回，`scores` 里从头到尾只有 `factual_grounding` 一项——
# 打分器一次都没跑起来，`complete` 结构上就到不了，只能空转到轮数用尽。
# 而修订那一步是试过的：`dropped` 事件显示模型第 2/3/4 轮都提了针对那一段
# 的修订，每次都被「只是换了措辞」的空改守卫丢掉。判据说改、模型改、守卫
# 丢，三方各自都对，合起来是个谁也出不去的环。
#
# 拦两轮是给修订的机会；第三轮还一字不差，就说明这一轮的写作动不了它，
# 再拦下去只是把剩下的轮数烧掉。事件照发（用户仍然看得见这条没解决），
# 但不再短路——让打分器跑起来，其余维度有机会被看见，这一轮也能结束。
STUCK_ROUNDS = 2


class Checks:
    """First failing check wins; the rest don't run.

    Why stop at the first: the model gets one clear instruction for the next
    round. Handing it five complaints at once produces a round that addresses
    none of them properly.
    """

    name = "checks"
    hooks = ("before_judge",)
    # Repeats fills dup_hints for the scoring call. Checks may
    # short-circuit scoring entirely, so it has to run second --
    # otherwise a fired check means dup_hints never gets computed,
    # and the next round wants it.
    after: tuple[str, ...] = ("repeats",)

    async def before_judge(self, st: State) -> AsyncIterator[Event]:
        # 上一轮报过什么 → 这一轮报了什么。**先攒后落**：一轮里可能有两条
        # 判据先后触发（前一条卡死了放行、后一条才短路），边算边写会把前一条
        # 的计数擦掉。轮末整只换掉，这一轮没报的键自然断掉。
        prev: dict[str, int] = st.bag.get("check_streak") or {}
        cur: dict[str, int] = {}
        st.bag["check_streak"] = cur

        for check in st.mode.checks:
            verdict = check(st)
            if not verdict:
                continue

            if verdict.fix:
                # **Fixes are atomic**: apply to a copy, keep it only if the
                # check now passes. Without the copy, a fix that doesn't
                # actually fix anything still mutates the content -- and the
                # next round then builds on something that was edited and is
                # still wrong. (Found by running the prototype; three passes
                # of reading the design on paper had missed it.)
                probe = dataclasses.replace(st, content=verdict.fix(st.content))
                if not check(probe):
                    st.content = probe.content
                    continue

            key = f"{verdict.dimension}\u0000{verdict.message}"
            streak = cur[key] = prev.get(key, 0) + 1
            if streak > STUCK_ROUNDS:
                # 卡死了，不短路。**继续往下看别的判据**：这一条动不了，不等于
                # 后面那条也动不了，短路本来就是为了「一次只给一个清楚的指令」。
                yield Event.custom(CUSTOM_CHECK_HIT, {
                    "dimension": verdict.dimension,
                    "note": verdict.message,
                    "stuck_rounds": streak,
                })
                continue

            st.ev = Evaluation(
                scores={verdict.dimension: DimensionScore(level=0, note=verdict.message)},
                status="continue",
                weakest=verdict.dimension,
            )
            st.skip_judge = True        # explicit, not "ev happens to be set"
            yield Event.custom(CUSTOM_CHECK_HIT, {
                "dimension": verdict.dimension,
                "note": verdict.message,
            })
            return
