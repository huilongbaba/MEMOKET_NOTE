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
NOT_A_VETO = ("done_criteria",)


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
        st.bag["prev_rank"] = rank
        st.bag["prev_coverage_unmet"] = unmet
