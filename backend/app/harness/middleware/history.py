"""Record how the run went, for cross-run learning.

Deliberately in BASE even though nothing reads it yet: it was missing from
compose_block entirely, which is exactly the class of omission that made
"capabilities are middleware, on by default" a rule.
"""

from __future__ import annotations

from ..types import RunRecord

from ... import harness_adapter
from ..state import State


class History:
    name = "history"
    hooks = ("after_run",)
    after: tuple[str, ...] = ()

    async def after_run(self, st: State) -> None:
        if not st.ev:
            return
        if st.stopped == "awaiting_review":
            # A paused run has not finished. Recording it would tell the next
            # run "this note reached round 2 and stopped", which is a lesson
            # about the user stepping away, not about the writing.
            return
        scores = {name: s.level for name, s in st.ev.scores.items()}
        harness_adapter.SqliteRunHistoryStore().record(RunRecord(
            key=f"{st.mode.key}:{st.ctx.note_id}",
            status=st.ev.status,
            rounds=st.round,
            final_scores=scores,
            weak_dimensions=[n for n, lv in scores.items() if lv < 2],
        ))
