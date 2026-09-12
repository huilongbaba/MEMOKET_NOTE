"""Hooks for one section of a folder-level writing plan.

The plan loop -- pick the next section, decide whether the plan needs more
sections, keep the tracking note in sync -- stays in the router. What runs
here is one section: gather, continue (or repair), judge, repeat.

Long-form's merge rule is the opposite of the block harness's: each round
*appends* to what is already there, so ``produce`` joins rather than
replaces, and everything written in earlier rounds stays under judgement.
"""

from __future__ import annotations

from typing import AsyncIterator

from .. import prompts
from .. import agent_loop
from .. import tools
from ...editor import outline
from ..checks import grounding_rules as grounding_check
from ...util import llm
from ..agent_loop import ToolTrace
from ..params import AGENT_TOOLS, CONTINUE_MAX_TOKENS, CONTINUE_TAIL_TOKENS
from ...database.retrieval import retrieve as _retrieve
from ..state import State

class SectionHooks:
    """One section of a plan. ``st.ctx.note_id`` is the note it writes into."""

    def __init__(self, *, goal: str, other_summaries: list[str],
                 folder_ctx: str = "", profile: list[str] | None = None):
        self.goal = goal
        self.other_summaries = list(other_summaries)
        self.folder_ctx = folder_ctx
        self.profile = list(profile or [])

    # ------------------------------------------------------------ gather --
    async def prepare(self, st: State) -> tuple[list[str], ToolTrace]:
        title = st.ctx.note_title
        trace = ToolTrace()
        if not AGENT_TOOLS:
            facts, _ids, _took = _retrieve(
                st.ctx.user, st.content, title, [], limit=6,
                title=title, anchor_first=True)
            return facts, trace

        msgs = [
            {"role": "system", "content": prompts.compose_system(
                prompts.RETRIEVAL_PLAN_SYSTEM, st.mode.skill_scope, st.ctx.user,
                st.skill_menu, [])},
            {"role": "user", "content": prompts.retrieval_plan_user(
                title, self.goal, self.other_summaries, st.content,
                topics_overview=tools.dispatch(
                    "list_topics", {"limit": 40}, st.ctx))},
        ]
        _extra, trace = await agent_loop.gather_context(
            msgs, st.ctx, groups=list(st.mode.groups))
        facts = list(trace.as_facts())

        # A failed tool loop must not mean writing empty-handed: fall back to
        # the pre-agent keyword retrieval rather than producing a round with
        # no material behind it.
        if trace.error and not facts:
            facts, _ids, _took = _retrieve(
                st.ctx.user, st.content, title, [], limit=6,
                title=title, anchor_first=True)

        # A section title often anchors to a specific occasion ("that time",
        # "last week"). Those need the multi-hop lookup, which the plain tool
        # loop does not reach on its own.
        probe = f"{title}\n{st.content[-400:]}"
        if agent_loop.is_scoped_question(probe):
            hop = tools.dispatch(
                "search_session_context",
                {"question": f"{title}——{self.goal[:100]}", "limit": 10},
                st.ctx)
            hop_facts = [line.strip() for line in hop.splitlines()
                         if line.strip() and not line.strip().startswith("（")]
            facts = hop_facts + facts

        return facts, trace

    # ----------------------------------------------------------- produce --
    async def produce(self, st: State) -> AsyncIterator[str]:
        if st.bag.get("cleanup_only"):
            # The repair already happened in Revise's before_produce. Writing
            # more now is precisely what this round exists to avoid.
            return

        system = prompts.compose_system(prompts.MAGIC_TAP_SYSTEM, st.mode.skill_scope,
                                        st.ctx.user, st.skill_menu,
                                        st.skill_bodies)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompts.section_write_user(
                st.ctx.note_title, self.goal, self.other_summaries,
                st.content_for_continue(), st.facts, self.folder_ctx,
                self.profile, focus=st.bag.get("focus", ""))},
        ]

        text = ""
        stats: dict = {}
        async for piece in llm.stream(messages, max_tokens=CONTINUE_MAX_TOKENS,
                                      stats=stats):
            text += piece
            yield piece
        # Hitting the token ceiling truncates mid-sentence. Finish the
        # sentence rather than dropping it -- deleting what was written is
        # the one response that loses work.
        if stats.get("finish_reason") == "length" and text:
            tail = messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": prompts.FINISH_THE_SENTENCE},
            ]
            async for piece in llm.stream(tail, max_tokens=CONTINUE_TAIL_TOKENS):
                text += piece
                yield piece

        # Drop paragraphs the note already contains before joining. This
        # guard lived only on the single-note harness once, and the first
        # benchmark of the folder path caught verbatim repetition inside a
        # single sentence.
        text = outline.drop_already_written(st.content, text) or text
        st.content = grounding_check.scrub_meta_sentences(
            prompts.join_round_text(st.content, text))

    # ------------------------------------------------------------ commit --
    async def commit(self, st: State) -> None:
        """The Save middleware persists every round. Marking the section done
        and re-syncing the tracking note are plan-level decisions and stay
        with the plan loop, which is the only place that can see the other
        sections."""
