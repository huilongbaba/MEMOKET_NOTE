"""Shrink the continuation prompt when the piece gets long.

**Only the continuation prompt.** Revision and scoring keep reading the full
text: both are hunting for drift and repetition *across* the whole piece, and
compacting hides exactly what they're looking for. That's why this writes to
``bag`` instead of touching ``st.content``.

Not in BASE -- only long-form runs into the limit. Block generation produces
a few hundred characters.
"""

from __future__ import annotations

from ...scoring import compact_context

from ..state import State


class Compact:
    name = "compact"
    hooks = ("before_produce",)
    # Revise rewrites st.content in the same hook; compacting
    # before it runs would shrink the *pre-revision* text and
    # hand the continuation prompt something already stale.
    after: tuple[str, ...] = ("revise",)

    async def before_produce(self, st: State) -> None:
        st.bag["content_for_continue"] = compact_context(
            st.content, keep_last_chars=st.mode.context_keep_last)
