"""Persist after every round, not just at the end.

A run takes minutes. If the user closes the tab at round 6, the five rounds
already written have to survive. ``commit`` in the loop's ``finally`` is a
second line of defence for that, but per-round saving is what makes a
half-finished run useful rather than merely recoverable.

Not in BASE: block generation has nothing to persist -- the block goes
straight to the editor.
"""

from __future__ import annotations

from ...database import store
from ..state import State


class Save:
    name = "save"
    hooks = ("after_produce",)
    after: tuple[str, ...] = ()

    async def after_produce(self, st: State) -> None:
        if not st.content.strip():
            return
        store.update_note(st.ctx.user, st.ctx.note_id, st.ctx.note_title, st.content)
