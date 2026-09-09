"""Run the Mode's deterministic checks, before paying for a scoring call.

Ordering matters here and it used to be backwards: scoring ran first, then
the checks, so whenever a check fired the scoring call had been wasted. A
scoring call is tens of seconds against a local model.

(PydanticAI does the same thing for the same reason: schema validation is
free and runs first, semantic validation costs I/O and runs second.)
"""

from __future__ import annotations

from typing import AsyncIterator

import dataclasses

from ..types import DimensionScore, Evaluation

from ..events import CUSTOM_CHECK_HIT, Event
from ..state import State


class Checks:
    """First failing check wins; the rest don't run.

    Why stop at the first: the model gets one clear instruction for the next
    round. Handing it five complaints at once produces a round that addresses
    none of them properly.
    """

    name = "checks"
    hooks = ("before_judge",)
    # Repeats fills dup_hints for the scoring call. Checks may
    # short-circuit scoring entirely, so it has to run second --
    # otherwise a fired check means dup_hints never gets computed,
    # and the next round wants it.
    after: tuple[str, ...] = ("repeats",)

    async def before_judge(self, st: State) -> AsyncIterator[Event]:
        for check in st.mode.checks:
            verdict = check(st)
            if not verdict:
                continue

            if verdict.fix:
                # **Fixes are atomic**: apply to a copy, keep it only if the
                # check now passes. Without the copy, a fix that doesn't
                # actually fix anything still mutates the content -- and the
                # next round then builds on something that was edited and is
                # still wrong. (Found by running the prototype; three passes
                # of reading the design on paper had missed it.)
                probe = dataclasses.replace(st, content=verdict.fix(st.content))
                if not check(probe):
                    st.content = probe.content
                    continue

            st.ev = Evaluation(
                scores={verdict.dimension: DimensionScore(level=0, note=verdict.message)},
                status="continue",
                weakest=verdict.dimension,
            )
            st.skip_judge = True        # explicit, not "ev happens to be set"
            yield Event.custom(CUSTOM_CHECK_HIT, {
                "dimension": verdict.dimension,
                "note": verdict.message,
            })
            return
