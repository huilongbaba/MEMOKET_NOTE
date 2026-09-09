"""Put "what skills exist" into context.

Two paths, and the default is the second one:

* **scope match** -- the user has said "this skill always applies when doing
  X". Inject the body directly; no point making the model decide something
  the user already decided.
* **everything else** -- only name + description go in, and the model calls
  ``load_skill`` if it judges one relevant. This is how the mechanism is
  meant to work: progressive disclosure means the model reads the table of
  contents and picks the chapter.

The two sets are disjoint. A skill that was injected must not also appear in
the menu, or the model will spend a tool call re-loading what it already has.
"""

from __future__ import annotations

from ... import skills as skills_store
from ..state import State


class Skills:
    name = "skills"
    hooks = ("before_produce",)
    after: tuple[str, ...] = ()

    async def before_produce(self, st: State) -> None:
        # First round only. ``skill_bodies`` also holds whatever the model
        # loaded via ``load_skill``, and recomputing every round would wipe
        # those out -- forcing it to re-load the same skill up to 8 times.
        if st.round > 1:
            return
        injected, listed = skills_store.for_scope(st.ctx.user, st.mode.skill_scope)
        st.skill_bodies = [s.body for s in injected]
        st.skill_menu = [(s.name, s.description) for s in listed]
        # Hand the tool layer the *same list object*, so a load_skill call
        # appends straight into the run's state. The tool pool stays unaware
        # that a harness exists -- it only sees a dict someone left for it.
        st.ctx.scratch["skill_bodies"] = st.skill_bodies
