"""Remember the best round, so running out of rounds doesn't ship the worst.

"Kept going" means "never met the bar", which makes the final round the least
likely to be the good one -- yet it's what every harness here shipped. Real
example: round 2 produced two clean charts, round 3 added a single-value bar
to satisfy the scorer, round 3 was delivered.

DSPy's ``Refine`` tracks ``best_reward`` for the same reason. Ours differs in
that the score is multi-dimensional, so ranking needs a deterministic way to
collapse it -- see ``State.rank``.

**折叠成一个标量要不要改成保留 Pareto 前沿（[IND] §6⑤ / GEPA）：量完不做。**
批 22 在 `harness_rounds` 的 447 轮 / 158 次跑上逐跑重放了一遍
（`scripts/best_of_pareto_probe.py`，只读）：

* 51 次跑有 ≥2 个**真打过分**且维度集合相同的轮次，可以做支配比较；
* **`rank()` 挑出来的那一轮被别的轮次 Pareto 支配的次数：0。**
  折叠从来没有挑中一个「每一维都不更好」的轮次；
* 前沿有多个成员的 20 次里，**16 次 `rank()` 挑的正是最靠后的那个前沿成员**，
  只有 4 次不是——而那 4 次里 3 次是同一个形状（后一轮把某个**覆盖**维度
  写达标了，代价是别的维度掉一档），那件事由 `loop._regressed` 的
  `best_coverage_unmet` 治，不需要换排序。

还有一条**结构性**的理由：GEPA 的前沿回答的是「下一步该变异哪个候选」，
可以同时留着好几个；我们要回答的是「这一次交哪一份正文给用户」，**只能交
一份**——任何一条「交哪个」的规则都会把前沿重新折回一个标量。换成前沿只是
把这个折叠挪个地方写，还多出一份状态要进快照。
"""

from __future__ import annotations

from ..state import State

# 「有缺口」≠「作废」（P18 #1）。代码判据命中的轮 `rank()` 是 (0, 0.0)，永远输给任何真打过分的轮——
# 对 `no_placeholder` / `no_same_sources_twice` 这类「这一轮有个确定的毛病」这是对的（人读 p5–p15
# 21 次多轮真跑：7 次交的是更早那轮，后面的命中轮 14 次是重复段、3 次一个出处都没有、1 次占位句，
# 那些确实不该交）。**只有 `done_criteria` 不是这个形状**：它说的是「用户自己写的完成标准还没全满足」
# ——新写的 6 段里 2 段没日期——而不是这一轮坏了。P15 真跑 `da080ca847cf`：第 1 轮判过分 (5, 1.83)、
# 2 段；第 2、3 轮各写了 4 段 / 补了一句弃答，都只被 `done_criteria` 短路；第 4 轮 `no_placeholder`。
# 交出去的是第 1 轮的 2 段，用户读过之后会留的是第 3 轮（同一轮的 4 段实质内容 + 弃答句）。
# 所以：被 `done_criteria` 短路的轮**沿用上一轮的排名**（不升不降），平手归后来者 → 交更长的那份；
# 别的判据照旧打到底。「打上限 1 分」那个候选量过不成立：单维 1 分的 `rank()` 是 (0, 1.0)，仍然输给
# (5, 1.83)，用户拿到的还是第 1 轮。
#
# ## P55 #3：`citations_present` 是第二个不是这个形状的（P53 问题 #4）
#
# 实拍 `603dca25403a`（P53 D3）：r1 五维真打分 (4, 1.8)；r2/r3/r5 各写 340 字左右，
# 每一轮都被 `citations_present` 短路成单维 0 分、`rank()` = (0, 0.0)，`best` 五轮钉在 r1；
# `check_stuck` 一停就交 `best`——**25 次调用 / 154k prompt token / 131 秒，用户拿到的是
# 第 1 轮那 421 字，后 4 轮 1,469 字全扔。** P22 问题 #7 只记了这条短路让 `complete`
# 触发不了，没记它还会让**响过判据的轮永远进不了候选**。
#
# **先量再改**（`<scratch>/p55_shortcircuit.py` / `p55_sc_bycheck.py`，12 批 47 份跑）：
#   · 短路轮 136 个，其中写了字的 131 个；
#   · **14 / 47 份跑（30%）交的是更早那一轮，合计扔掉 15,031 字**；
#   · 短路轮按判据分：`citations_present` **72 轮 / 32,700 字**（占一半以上，
#     且那 14 份跑里的 27 轮是它），第二名 `no_same_sources_twice` 28 轮。
#
# 为什么只放 `citations_present` 进来、别的一条都不动：
#   · 它说的是「这一轮写了 N 字，**一个编号都没有**」——**缺**了一样东西，
#     不是「这一轮坏了」。文件顶上那条人读（p5–p15 21 次真跑）说得很清楚，
#     真该作废的是重复段 / 占位句 / 一个出处都没有那几种，`no_same_sources_twice`
#     和 `no_placeholder` 照旧是一票否决。
#   · 它要的那件事**这条路上办不到**：P30 量过可引率只有 7.7–9.1%（623 句里 52 句
#     在材料里有逐字出处），P53 D4 逐条回查的结论是**终稿里的编号全部是修订那一步
#     补进去的**，续写这一步四批（P5/P6/P8/P22）连响都没写过一个。
#   · 正文是**累积**的：沿用上一轮排名 + 平手归后来者 = 交更长的那一份，而更长的
#     那份**包含**前一轮写的字和它已经贴上的编号——不是拿没编号的换有编号的。
#
# 反事实（同一份实拍逐轮推）：r2 沿用 r1 的 (4,1.8) 平手 → best 走到 r2；r3 同理走到 r3；
# r4 真打分 (3,1.75) 更低，best 留在 r3；r5 沿用 r4 的 (3,1.75)，低于 best，不动。
# 最后交 r3 的 2,127 字而不是 r1 的 1,158 字。**排名的数一格没变，变的只是交哪一份正文。**
#
# ## `JUDGE_FLOOR`（P26 #2）为什么没接住这一跑——逐轮数过
#
# 这一跑 r1 就有真分，所以门槛走的是 `JUDGE_FLOOR_AFTER_FIRST = 3`（连着 3 轮一份真分
# 都没有才放行）。逐轮：r1 真打分 → `short_circuit_streak` 归 0；r2 短路（streak 0→1）；
# r3 短路（1→2）；**r4 一条判据都没命中、真打了分 → streak 归 0**；r5 短路（0→1）→
# `check_stuck` 停。**最长只攒到 2，永远够不着 3。**
#
# 更要紧的是：`JUDGE_FLOOR` 治的是「不同判据轮流把打分饿死」（P22 那个 6 轮一份分都没有的
# `e78306202d78`），而这一跑的真打分率是 **11/20 = 55%**——它压根不饿。
# **两条病不是一条**：一条是「没人给这一轮打分」，另一条是「打了分的轮也选不上它」。
# 所以不动 `JUDGE_FLOOR` 的两段门槛（那是量过的），只在这里补第二条。
NOT_A_VETO = ("done_criteria", "citations_present")


class BestOf:
    name = "best_of"
    hooks = ("after_judge",)
    after: tuple[str, ...] = ()

    async def after_judge(self, st: State) -> None:
        # **平手归后来者。** `>` 会让并列时最早的那一轮赢，而这是反的：每一轮
        # 的正文都是在上一轮的正文上改出来的，分数一样就说明后一轮白多做了
        # 那些修订——分不出高下时该交做得多的那份。
        #
        # 第 602 轮真跑实拍：4 轮全被代码判据打回，`rank()` 一律 (0, 0.0)，
        # 于是 best 从头到尾钉在第 1 轮。后三轮 8 条修订（删掉两整段重复、
        # 修好一张手写 mermaid）全被扔掉，用户等 90 秒拿到的是第 1 轮的正文。
        # 进来之前 `best` 排在哪一格——`best_stalled`（`modes.BEST_STALL_ROUNDS`，P55 #4）
        # 数的就是它连着几轮没往上走。**记在这儿而不是在停机规则里现算**：`st.best`
        # 只有这一处在写，历史攒在别处一定会飘（同 `check_stuck_detail` 两处各算一份的教训）。
        was = st.best[0] if st.best is not None else None
        rank = st.rank()
        unmet = st.coverage_unmet()
        if st.skip_judge and st.bag.get("short_circuit") in NOT_A_VETO and st.bag.get("prev_rank") is not None:
            # 用户标准有缺口的轮沿用上一轮的排名（见文件顶上）。快照进出会把元组变成列表，收回来。
            rank = tuple(st.bag["prev_rank"])
            unmet = bool(st.bag.get("prev_coverage_unmet"))
        if st.best is None or rank >= st.best[0]:
            st.best = (rank, st.content)
            # 顺手记下**这一轮当时写够了没有**。唯一的读者是 `_regressed`：
            # 它已经会放过「这一轮还没写够」的波动，但「最好那轮之所以排名高
            # 正因为它没写够」是同一件事的另一半，而那一半原来没人挡
            #（批 22，实拍见 `loop._regressed` 那段注释）。
            # 记在 bag 里而不是塞进 `st.best` 的元组：`_regressed` 拿
            # `best_rank[0]` 当「差几个维度」在用，元组一变形那行就得跟着改，
            # 而它跟这件事没关系。
            st.bag["best_coverage_unmet"] = unmet
        # **「涨」= 排名的数变大，不是「best 换了一份正文」。** 平手归后来者那一支
        # 会把 `st.best` 换成更长的一份而排名一格没动——P53 实拍 `3a3a96354546`
        # 正是这个形状（`best` 从 r3 的 [4, 1.667] 起 r4–r8 五轮一格没涨，
        # 跑满 8 轮 224k prompt token 换来五篇里最差的一篇）。
        now = st.best[0] if st.best is not None else None
        st.bag["best_stall"] = (int(st.bag.get("best_stall", 0)) + 1
                                if was is not None and now is not None and now == was else 0)
        st.bag["prev_rank"] = rank
        st.bag["prev_coverage_unmet"] = unmet
