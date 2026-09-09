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
        rank = st.rank()
        if st.best is None or rank > st.best[0]:
            st.best = (rank, st.content)
