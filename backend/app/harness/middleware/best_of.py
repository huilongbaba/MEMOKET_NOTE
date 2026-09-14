"""Remember the best round, so running out of rounds doesn't ship the worst.

"Kept going" means "never met the bar", which makes the final round the least
likely to be the good one -- yet it's what every harness here shipped. Real
example: round 2 produced two clean charts, round 3 added a single-value bar
to satisfy the scorer, round 3 was delivered.

DSPy's ``Refine`` tracks ``best_reward`` for the same reason. Ours differs in
that the score is multi-dimensional, so ranking needs a deterministic way to
collapse it -- see ``State.rank``.
"""

from __future__ import annotations

from ..state import State


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
        if st.best is None or rank >= st.best[0]:
            st.best = (rank, st.content)
