"""Mechanical near-duplicate detection, fed to scoring as evidence.

Asking the model to re-read the whole piece each round looking for repetition
doesn't work -- it stalls on that dimension for rounds at a time. Handing it
concrete candidate pairs does. The pairs are cheap (difflib, no model call)
and capped, so this is close to free.
"""

from __future__ import annotations

from ..dedup import find_repeats

from ..state import State


class Repeats:
    """Put candidate duplicate pairs in the bag for the scoring call.

    Writes to ``bag`` rather than calling anything: two different consumers
    want this (the revision prompt and the scoring call), and a middleware
    that reached into either would be coupling itself to both.
    """

    name = "repeats"
    # Twice per round, not once. Revise reads it before producing; the
    # scoring call reads it after. Between those two points ``st.content``
    # changes, and handing the scorer the pairs found in last round's text
    # would be reporting duplicates that may already be gone.
    hooks = ("before_produce", "before_judge")
    after: tuple[str, ...] = ()

    async def before_produce(self, st: State) -> None:
        st.bag["dup_hints"] = find_repeats(st.content)

    async def before_judge(self, st: State) -> None:
        st.bag["dup_hints"] = find_repeats(st.content)
