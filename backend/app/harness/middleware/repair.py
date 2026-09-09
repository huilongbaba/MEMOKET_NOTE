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
        weak = [d for d in INNER_QUALITY
                if st.ev and (s := st.ev.scores.get(d)) and s.level < 2]
        st.bag["cleanup_only"] = bool(weak)
        if weak:
            yield Event.custom(CUSTOM_POLICY, {
                "round": st.round,
                "note": "next round repairs what is written instead of "
                        "adding to it",
                "dimensions": weak,
            })
