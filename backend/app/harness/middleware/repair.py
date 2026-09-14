"""Turn this round's reading into next round's plan.

There are two kinds of weak score and they call for opposite responses:

  * a *coverage* dimension is weak -> not enough has been written -> write more
  * an *inner quality* dimension is weak (repetition, incoherence) -> what is
    already written has a defect -> fix it, and add nothing

Continuing when the problem is repetition cannot work: text that already
repeats does not stop repeating by growing. The earlier version of this rule
keyed on a single dimension name (``non_repetition``) and oscillated
visibly in real runs -- the cleanup round fixed it, the weakest dimension
became something else, the next round wrote more and broke it again, back and
forth until the round cap. Both long-form harnesses now read the whole score
vector instead of the weakest name, and read it the same way.
"""

from __future__ import annotations

from typing import AsyncIterator

from ..events import CUSTOM_POLICY, Event
from ..state import State

# Dimensions that describe a defect in the existing text rather than an
# absence of text.
INNER_QUALITY = ("non_repetition", "coherence")


class Repair:
    name = "repair"
    hooks = ("after_judge",)
    after: tuple[str, ...] = ()

    async def after_judge(self, st: State) -> AsyncIterator[Event]:
        # **代码判据打回的那一轮不算数。** 这个模块的整个设计前提是「读完整的
        # 分数向量」（见模块头：只看最弱那个维度名会来回震荡），而判据命中时
        # `st.ev` 是伪造的——只有一个维度、分数 0，根本没有向量可读。
        #
        # 代价是实拍出来的（第 606 轮，文件夹跑的第三节）：手写 mermaid 的判据
        # 落在 `coherence` 上（`pick_dimension` 的兜底，分段模式没有 has_charts
        # 这个维度），`coherence` 又在 INNER_QUALITY 里 → 下一轮 cleanup_only
        # → `produce()` 直接返回 → **模型根本没机会去调画图工具**，而那正是这条
        # 判据要求的修法。判据说「调工具画出来」，修复策略说「这一轮不许写」，
        # 于是两轮原地打转、一次分都没打上，最后 `no_progress` 收场。
        weak = [d for d in INNER_QUALITY
                if st.ev and not st.skip_judge
                and (s := st.ev.scores.get(d)) and s.level < 2]
        st.bag["cleanup_only"] = bool(weak)
        if weak:
            yield Event.custom(CUSTOM_POLICY, {
                "round": st.round,
                "note": "next round repairs what is written instead of "
                        "adding to it",
                "dimensions": weak,
            })
