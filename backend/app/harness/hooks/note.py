"""Hooks for the single-note harness: continue writing one note to completion.

Two things live here that no other harness has:

* **The skeleton.** ``spine`` (the note's central tension) and ``beats`` (its
  structural steps) are produced once in ``before_run`` and then belong to
  the run. They sit in ``st.bag`` rather than on ``State`` because only this
  harness has them -- putting them on State would be putting one feature's
  vocabulary into the shared type.
* **Outline mode.** When the user has already written the headings, those
  headings *are* the goal: continuation fills one named section at a time and
  writes no headings of its own. The whole harness changes shape around this,
  and every mechanism that touches structure has to know about it.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

from .. import prompts
from .. import agent_loop
from .. import tools
from ...util import llm
from ...editor import outline
from ..checks import grounding_rules as grounding_check
from ..agent_loop import ToolTrace
from ...database.retrieval import retrieve as _retrieve
from ..params import AGENT_TOOLS, CONTINUE_MAX_TOKENS, CONTINUE_TAIL_TOKENS
from ..events import CUSTOM_SKELETON, Event
from ..state import State

# How many of the user's own headings become beats. Past this the skeleton
# stops being a plan and becomes a copy of the table of contents.
MAX_OUTLINE_BEATS = 12


class NoteHooks:
    """``polish`` only repairs; it never continues."""

    def __init__(self, *, polish: bool = False, spine: str = "",
                 beats: list[str] | None = None, profile: list[str] | None = None):
        self.polish = polish
        self.spine = spine
        self.beats = list(beats or [])
        self.profile = list(profile or [])

    # -------------------------------------------------------- before_run --
    async def skeleton(self, st: State) -> AsyncIterator[Event]:
        """Establish spine/beats and whether this note is an outline.

        Called by the router before the loop starts, because a failure here
        has to be reportable without a round having begun. Yields ordinary
        ``Event``s -- **one event vocabulary, no exceptions**: this used to
        yield ``(name, payload)`` tuples that the router serialised with the
        old custom names, and when the frontend switched to the AG-UI names
        the skeleton silently stopped arriving.
        """
        content = st.content
        # **Outline protection is off in polish mode.** The two are directly
        # opposed: polishing exists to fix structural defects (duplicated
        # headings, scaffolding headings, broken numbering) and outline
        # protection exists to freeze structure. Measured: polish seeds are
        # short notes with one sentence per section, which is exactly what
        # is_outline() detects, so structure froze and every revision that
        # tried to delete a duplicated heading was rejected -- non_repetition
        # scored 0 twenty times in a row.
        is_outline = (not self.polish) and outline.is_outline(content)
        st.bag["outline_mode"] = is_outline

        if is_outline and not self.beats:
            # The user built the table of contents. **Do not generate another
            # one.** This cost a user their structure once: they wrote a
            # nine-section outline for the AI to fill in, the skeleton step
            # ignored it and invented its own beats, and by the end 「硬件」
            # had moved to the bottom, three sub-headings were gone and
            # 「反思与展望」 had vanished.
            self.beats = [txt for _lv, txt in outline.headings(content)][:MAX_OUTLINE_BEATS]
            self.spine = self.spine or f"按用户已有的目录逐节填充：{'、'.join(self.beats[:4])}…"
        elif not self.spine and not self.beats:
            system = prompts.compose_system(prompts.SKELETON_SYSTEM, "skeleton",
                                            st.ctx.user)
            try:
                text = await llm.complete(
                    [{"role": "system", "content": system},
                     {"role": "user", "content": prompts.skeleton_user(
                         st.ctx.note_title, content, self.profile)}],
                    max_tokens=800, temperature=0.4)
                parsed = llm.extract_json(text)
                if isinstance(parsed, dict):
                    self.spine = str(parsed.get("spine") or "").strip()
                    raw = parsed.get("beats")
                    if isinstance(raw, list):
                        self.beats = [str(b).strip() for b in raw if str(b).strip()][:6]
            except Exception as exc:                   # noqa: BLE001
                # Scoring still works without a skeleton -- spine_fidelity and
                # beat_coverage judge on weaker evidence, not on none. Losing
                # the whole session over it would be the worse trade.
                yield Event.run_error(f"骨架生成失败，退回空骨架继续: {exc}")

        st.bag["spine"], st.bag["beats"] = self.spine, self.beats
        st.bag["profile"] = self.profile
        yield Event.custom(CUSTOM_SKELETON, {"spine": self.spine, "beats": self.beats})

    # ------------------------------------------------------------ gather --
    async def prepare(self, st: State) -> tuple[list[str], ToolTrace]:
        trace = ToolTrace()
        if self.polish or st.bag.get("cleanup_only"):
            # Repair rounds write nothing, so new material has nowhere to go.
            return [], trace

        spine = st.bag.get("spine", "")
        beats = st.bag.get("beats") or []
        title = st.ctx.note_title
        policy = st.bag.get("policy")

        # **Decide which section this round writes before retrieving.** The
        # order used to be reversed, so retrieval never knew the target and
        # every round came back with the same facts -- the model, holding
        # material about crowdfunding and told to write the "team" section,
        # could only say the same things again under a new heading.
        target = outline.next_gap(st.content) if st.bag.get("outline_mode") else None
        st.bag["outline_target"] = target

        if not AGENT_TOOLS:
            facts, _ids, _took = _retrieve(
                st.ctx.user, st.content, spine, beats, limit=6,
                title=title, anchor_first=True)
            return facts, trace

        # Two stages: ask the model whether and what to retrieve, then write.
        #
        # The first version hung the tools off the continuation call itself
        # and **the model never once retrieved anything**: 4300 characters of
        # "keep writing" with the tool description tacked on the end reads as
        # "you decide", and it decided no. Making the retrieval decision its
        # own call makes *that question* the task. The model can still answer
        # "nothing needed" -- what changed is the context it is asked in.
        msgs = [
            {"role": "system", "content": self._plan_system(st)},
            {"role": "user", "content": prompts.retrieval_plan_user(
                title, spine, beats, st.content_for_continue(),
                steer=getattr(policy, "steer", ""),
                require_verification=getattr(policy, "require_verification", False),
                topics_overview=tools.dispatch("list_topics", {"limit": 40}, st.ctx),
                section=target[0] if target else "")},
        ]
        # Mode decides which groups exist; the policy may add to them for a
        # round (escalating to verification tools, say). It may not replace
        # them -- doing so is how the skill tools became unreachable.
        groups = list(st.mode.groups)
        for extra in getattr(policy, "extra_tool_groups", ()) or ():
            if extra not in groups:
                groups.append(extra)
        _extra, trace = await agent_loop.gather_context(
            msgs, st.ctx, groups=groups,
            max_iters=getattr(policy, "tool_iters", 2))
        facts = list(trace.as_facts())

        if trace.error and not facts:
            # Fall back to the zero-LLM keyword retrieval rather than writing
            # empty-handed. One transient 500 used to push the round into the
            # known-worst state -- no material, so invent some -- while a
            # two-millisecond fallback sat unused.
            facts, _ids, _took = _retrieve(
                st.ctx.user, st.content, spine, beats, limit=6,
                title=title, anchor_first=True)

        # When last round's facts were judged unsupported, trace the top few
        # back to the original conversation lines and put them in front of the
        # model. ``fact_sources`` is a two-step tool and the model has never
        # been observed reaching the second step on its own -- the budget goes
        # on breadth in the first round.
        if getattr(policy, "require_verification", False) and trace.used:
            for fid in agent_loop.fact_ids_in(trace)[:3]:
                src = tools.dispatch("fact_sources", {"fact_id": fid}, st.ctx)
                if src and not src.startswith("（"):
                    facts.append(f"[{fid} 的原话] " + src.replace("\n", " ")[:300])

        # A question anchored to a specific occasion ("that time", "besides X")
        # needs the multi-hop lookup. Prompt-level instructions to choose that
        # tool were measured to have no effect on this model, so it is run
        # directly instead of hoped for.
        probe = f"{title}\n{st.content_for_continue()[-400:]}"
        if agent_loop.is_scoped_question(probe):
            hop = tools.dispatch(
                "search_session_context",
                {"question": f"{title}——{spine or st.content[:120]}", "limit": 10},
                st.ctx)
            hop_facts = [line.strip() for line in hop.splitlines()
                         if line.strip() and not line.strip().startswith("（")]
            if hop_facts:
                facts = hop_facts + facts

        return facts, trace

    def _plan_system(self, st: State) -> str:
        """The retrieval-planning prompt, carrying the skill menu.

        **The menu has to be here, not only in the writing prompt.** Tools
        exist on this call and nowhere else, so a model that first reads
        "these skills are available" while writing has already lost its
        chance to load one. Measured: with the menu only in the writing
        prompt, ``load_skill`` was never called once.

        Bodies are deliberately empty here -- what to retrieve is not what a
        writing skill has an opinion about, and they land in the writing
        prompt where they belong.
        """
        return prompts.compose_system(
            prompts.RETRIEVAL_PLAN_SYSTEM, st.mode.skill_scope, st.ctx.user,
            st.skill_menu, [])

    # ----------------------------------------------------------- produce --
    async def produce(self, st: State) -> AsyncIterator[str]:
        if self.polish or st.bag.get("cleanup_only"):
            return

        policy = st.bag.get("policy")
        base = (prompts.MAGIC_TAP_SYSTEM_LEAN
                if os.getenv("MEMOKET_LEAN_PROMPT") == "1"
                else prompts.MAGIC_TAP_SYSTEM)
        system = prompts.compose_system(base, st.mode.skill_scope, st.ctx.user,
                                    st.skill_menu, st.skill_bodies)

        note_block = ""
        target = st.bag.get("outline_target")
        if st.bag.get("outline_mode"):
            note_block = outline.outline_block(st.content)
            if target:
                note_block += (f"\n\n**这一轮只写「{target[0]}」这一节的正文**，"
                               "不要写标题、不要碰别的小节。")
        # 定向续写：正文已有目录、没有待填的空节时，让模型先说这段放哪一节。
        # 大纲模式下已有 outline_target 的轮次不用——那一轮本来就是定向的。
        sections = ([t for _lv, t in outline.headings(st.content)]
                    if (not target and len(outline.headings(st.content)) >= 2) else [])
        st.bag["insert_at"] = None
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompts.note_harness_continue_user(
                st.bag.get("spine", ""), st.bag.get("beats") or [],
                st.content_for_continue(), st.facts, self.profile,
                outline_note=note_block, sections=sections)},
        ]

        text = ""
        stats: dict = {}
        temp = getattr(policy, "continue_temperature", 0.7)
        # 有放置指令时先攒到第一个换行再往外吐：指令行不进正文，位置要在第一个
        # delta 之前就定下来（loop 据 bag["insert_at"] 先发一个 insert_at 事件）。
        head = ""
        directive_done = not sections
        place: str | None = None
        async for piece in llm.stream(messages, max_tokens=CONTINUE_MAX_TOKENS,
                                      temperature=temp, stats=stats):
            if not directive_done:
                head += piece
                if "\n" not in head and len(head) < 120:
                    continue
                directive_done = True
                first, _nl, rest = head.partition("\n")
                place = outline.parse_place_directive(first)
                if place is None and not outline.PLACE_DIRECTIVE.match(first):
                    rest = head                          # 没写指令行：整段都是正文
                pos = outline.section_end(st.content, place) if place else None
                st.bag["insert_at"] = ({"section": place, "pos": pos} if pos is not None else None)
                piece = rest.lstrip("\n")
                if not piece:
                    continue
            text += piece
            yield piece
        if not directive_done and head:                  # 整段没换行的短输出
            text += head
            yield head

        # Hitting the ceiling truncates mid-sentence -- real output ended on
        # 「这意味着」. **Do not delete the half sentence**: that hides a
        # truncation by throwing away work the model already did. Ask it to
        # finish, once.
        if stats.get("finish_reason") == "length" and text:
            unclosed = ("\n**上面有一个 ``` 代码块还没闭合，必须先把它补完整"
                        "再收尾**——没闭合的代码块会让整段渲染失败。"
                        if text.count("```") % 2 == 1 else "")
            tail = messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content":
                    "上面这段在句子中间被长度限制切断了。接着最后那半句往下写完，"
                    "**不要重复已经写过的内容**，把当前这个自然段收尾即可，"
                    "不用另起新话题。" + unclosed},
            ]
            async for piece in llm.stream(tail, max_tokens=CONTINUE_TAIL_TOKENS,
                                          temperature=temp):
                text += piece
                yield piece

        if not text.strip():
            return

        if st.bag.get("outline_mode") and target:
            # Insert **at the target heading**, not at the end. Appending makes
            # the model create a second heading with the same name further
            # down, and the table of contents then shows 「市场」 twice. Its
            # own headings are stripped: the prompt says not to write any and
            # it writes them anyway, flattening the user's ### into ##.
            body = outline.drop_already_written(
                st.content, outline.strip_headings(text))
            if body:
                st.content = grounding_check.scrub_meta_sentences(
                    outline.insert_into(st.content, target[1], body))
            return

        # Appending repeats too -- just less visibly than in outline mode,
        # where the duplicated sections sit side by side.
        text = outline.drop_already_written(st.content, text) or text
        placed = st.bag.get("insert_at")
        if placed and placed.get("pos") is not None:
            # 定向插进那一节的末尾。模型偶尔还是会把目标标题再写一遍——剥掉。
            body = text
            for line in body.split("\n", 1)[:1]:
                if line.lstrip("# ").strip() == (placed.get("section") or "").strip():
                    body = body.split("\n", 1)[1] if "\n" in body else ""
            st.content = grounding_check.scrub_meta_sentences(
                outline.insert_into(st.content, placed["pos"], body))
            return
        st.content = grounding_check.scrub_meta_sentences(
            prompts.join_round_text(st.content, text))

    # ------------------------------------------------------------ commit --
    async def commit(self, st: State) -> None:
        """Save handles per-round persistence; History records the run. What
        is left is nothing -- kept as an explicit no-op so the contract is
        visibly satisfied rather than accidentally absent."""
