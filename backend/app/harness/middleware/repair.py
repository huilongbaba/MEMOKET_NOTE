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
        # **修复对某一档分数试过一次没用，就不再为它花轮次。**
        #
        # 实拍（第 647 轮，真跑 4 轮）：`non_repetition` 每一轮都判 0，第 2 轮
        # 排修复、第 3 轮修完还是 0、第 4 轮**又排一次修复**——二十轮上限下这
        # 就是十轮空转。而那一轮判的是「同一个论点换个说法又说了一遍」，正文里
        # 一对逐字重复都没有（段落两两相似度最高不到 0.5），修订那一步手上全是
        # 词面手段，改不动它。
        #
        # 分数一动（哪怕只从 0 到 1）就重新给一次机会：那说明上一次修复是有效的，
        # 只是还没到位。记的是「在哪一档上失败过」而不是「失败过」，就是为了这个。
        pending: dict[str, int] = st.bag.setdefault("repair_pending", {})
        failed: dict[str, int] = st.bag.setdefault("repair_failed", {})

        weak: list[str] = []
        gave_up: list[str] = []
        for d in INNER_QUALITY:
            if not st.ev or st.skip_judge:
                break
            s = st.ev.scores.get(d)
            if not s:
                continue
            if s.level >= 2:                       # 达标了：账一笔勾销
                pending.pop(d, None)
                failed.pop(d, None)
                continue
            if d in pending and s.level <= pending.pop(d):
                failed[d] = s.level                # 上一轮修完没动分
            if d in failed and s.level <= failed[d]:
                gave_up.append(d)
                continue
            weak.append(d)

        st.bag["cleanup_only"] = bool(weak)
        for d in weak:
            pending[d] = st.ev.scores[d].level     # type: ignore[union-attr]
        if weak or gave_up:
            yield Event.custom(CUSTOM_POLICY, {
                "round": st.round,
                "note": "next round repairs what is written instead of "
                        "adding to it" if weak else
                        "repairing these did not move the score; writing instead",
                "dimensions": weak,
                **({"gave_up": gave_up} if gave_up else {}),
            })
