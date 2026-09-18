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
#
# **`topic_fidelity` 是第 765 轮补进来的，它之前是个孤儿。**
# 它既不在这个元组里，也不在 `loop.COVERAGE_DIMS` 里——于是分段模式实测
# 16 次里 7 次判它不达标，而两条执行器选择规则一条都不看它：既不会排
# 「只修不写」，也不算「还没写够」。它唯一的作用是把 `status` 钉在
# `continue` 上，然后看着回路把轮数跑满。
#
# 归内在质量的理由很硬：**已经跑题的那段文字，不会因为后面补了几段切题的
# 就不跑题了。** 跟重复是同一个形状——追加只会让它更差，只有修订能让它变对。
INNER_QUALITY = ("non_repetition", "coherence", "topic_fidelity")

# ------------------------------------------------- 只能停机的那一档 ---
#
# **[MECH] 第 2 层第 5 条**（计划 4.5）：
#
# > 内在质量维度必须有位置级探测器，否则不许进 `INNER_QUALITY`
# > ——没有探测器的维度，它的分数只能让回路**停下来**，不能让它**变好**。
#
# `coherence` 没有探测器。这一批去量了一次「那要不要补一个」，结论是**不补**，
# 依据有三条，全是数：
#
# 1. **分母接近零**（`scripts/coherence_denominator.py`，只读跑在 45 篇真实
#    语料上）。`_COHERENCE` 那条判词列了五款，只有第 (2)(3) 款是结构性的
#    ——标题层级、小节编号。实测：`user` + `script` 两类共 **148 个相邻标题对
#    里跳级 0 个**、**42 个兄弟组里只有 1 组是「每一条都带编号」的**（所以
#    「1、2、4、3」那种断号根本没有可比的对象）。一条在真实语料上**一次都
#    命中不了**的判据，跟一条全部命中的判据一样说明不了任何事。
# 2. **那一款在生产里已经被明确排除在 coherence 之外了。**
#    `routers/note_harness._score_context` 里记着一次实拍：大纲模式下连着三轮
#    `coherence` 判「产品和众筹用三级标题而时间线、团队、反思用二级标题，造成
#    标题层级不统一」——**那是用户自己写的大纲**，而且另有一道硬闸保证它改不了。
#    修法是告诉打分器「不要评价标题的层级」。再做一个机械版的标题判据，等于
#    把那次已经判过的事重新判一遍。
# 3. **它几乎从来不是唯一的阻塞项。** `harness_rounds` 的 347 个 note 轮次里，
#    `coherence` 出现 123 轮、判 0 的 46 轮（37.4%）、不达标 75 轮；但
#    **「只剩 coherence 一维不达标」只有 2 轮，连着两轮的 0 轮**。也就是说
#    它每次拖住回路，旁边都站着一个**有**探测器的维度（`factual_grounding`
#    249 次、`non_repetition` 136 次），修复轮本来就会被那一个排出来。
#
# 所以这一批选的是那句话的后半句：**承认它只能用来停机，并在代码里写明**。
# 写明的方式不是注释（「凡是只能靠自报来保证的性质，迟早会被报错一次」），
# 是下面那行 `_REPAIRABLE` —— `Repair` 只从它里面挑要修的维度，
# `STOP_ONLY` 里的维度**永远排不出 `cleanup_only`**，另有一条闸钉着这两个
# 集合加起来正好是 `INNER_QUALITY`、且交集为空。
#
# 它剩下的作用一点没少：`status` 到不了 `complete`、进 `rank()` 拉低这一轮的
# 排名、`weakest` 时它的诊断照样进 `focus_note` 交给修订那一步。
# **少的只有一件事：不再为它专门烧掉一整轮「只修不写」。**
#
# `topic_fidelity` 留在 `_REPAIRABLE` 里，**这是笔明账**：它同样没有位置级
# 探测器（[MECH] 第二节那张表里跟 `coherence` 并排），但第 765 轮把它归进
# 内在质量是为了让 7/16 的不达标**能触发一次只修不写**，而它的诊断（「这一节
# 写到了别的分段该写的内容」）本身就带位置。计划里「没有位置级探测器的内在
# 质量维度 2 → 0」这一条，这一批做掉的是其中一个。
STOP_ONLY = ("coherence",)
_REPAIRABLE = tuple(d for d in INNER_QUALITY if d not in STOP_ONLY)


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
        # **只从 `_REPAIRABLE` 里挑**，不是从 `INNER_QUALITY` 里挑：
        # `STOP_ONLY`（今天只有 `coherence`）没有位置级探测器，为它排一轮
        # 「只修不写」等于让修订那一步空手上场——[MECH] 第二节那条链的终点
        # 正是「修理工到了现场，但没人告诉他哪里坏了」。理由和实测见上面。
        for d in _REPAIRABLE:
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

        # 只能停机的那几维这一轮到底达没达标。**报出来，不是为了驱动什么**
        # ——恰恰因为它驱动不了任何东西，才必须在事件里看得见：
        # 用户那一侧（`AgentActivity`）不然会看到「这一轮什么策略都没排」，
        # 而实际上有一维一直判 0，只是这个回路对它无能为力。
        stop_only = [d for d in STOP_ONLY
                     if st.ev and not st.skip_judge
                     and (s := st.ev.scores.get(d)) and s.level < 2]

        st.bag["cleanup_only"] = bool(weak)
        for d in weak:
            pending[d] = st.ev.scores[d].level     # type: ignore[union-attr]
        if weak or gave_up or stop_only:
            yield Event.custom(CUSTOM_POLICY, {
                "round": st.round,
                "note": "next round repairs what is written instead of "
                        "adding to it" if weak else
                        "repairing these did not move the score; writing instead"
                        if gave_up else
                        "these have no position-level probe: the score can only "
                        "stop the loop, not drive a repair round",
                "dimensions": weak,
                **({"gave_up": gave_up} if gave_up else {}),
                **({"stop_only": stop_only} if stop_only else {}),
            })
