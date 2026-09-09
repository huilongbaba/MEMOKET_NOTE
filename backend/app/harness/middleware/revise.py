"""Fix what's already written, before writing more.

Continuation only ever appends. By round three, what round one wrote may
already repeat, contradict or drift from the rest -- and nothing looks back
at it. Without this pass the text can only grow, and grows more crooked.

Not in BASE: block generation has no "already written" to fix. It rewrites
the whole block each round, which is a different operation.

The user-facing half of this is the coloured diff with per-hunk accept /
reject. That makes one property non-negotiable: **every revision must be
attributable**. A rejected suggestion is reported (a ``dropped`` event with
the reason), never silently discarded -- if the model proposed eight edits
and three were unusable, the user should be able to see which and why.
"""

from __future__ import annotations

from typing import AsyncIterator

from ... import grounding_check, llm, outline, prompts, store
from ..events import (CUSTOM_DROPPED, CUSTOM_PHASE_DELTA,
                      CUSTOM_REVISION, Event)
from ..revision import (_apply_revision, _breakage, _expand_sources,
                        _tidy_blank_lines, reject_revision)
from ..state import State

# One pass proposes at most this many edits. Beyond it the model stops
# finding real problems and starts rephrasing for its own sake -- and each
# one still costs an anchor resolution that can go wrong.
DEFAULT_MAX_REVISIONS = 6

VALID_OPS = ("insert", "delete", "replace")


class Revise:
    name = "revise"
    hooks = ("before_produce",)
    after: tuple[str, ...] = ("repeats",)   # the pass wants this round's pairs

    async def before_produce(self, st: State) -> AsyncIterator[Event]:
        # Reset first: the loop's no-progress check reads this, and a stale
        # count from an earlier round would keep a dead run alive.
        st.bag["revisions_applied"] = 0
        if st.round < 2 or not st.content.strip():
            return          # nothing written yet; nothing to fix

        policy = st.bag.get("policy")
        max_revisions = getattr(policy, "max_revisions", DEFAULT_MAX_REVISIONS)
        # Anchors already touched **in this run**, not this pass. Two rounds
        # rewriting the same passage with nothing but wording changes is the
        # revision pass arguing with itself.
        edited: set[str] = st.bag.setdefault("edited_spans", set())
        focus = st.bag.get("focus", "")

        system = prompts.compose_system(prompts.EDIT_SYSTEM, "edit", st.ctx.user,
                                        st.skill_menu, None)
        user = prompts.edit_user(
            st.bag.get("spine", ""), st.bag.get("beats") or [], st.content,
            st.facts, st.bag.get("profile") or [], focus,
            st.bag.get("dup_hints") or [],
            # Deterministic defects go in as concrete lines. Asking the model
            # to find placeholders and audit voice by reading is strictly
            # worse than telling it which lines they are.
            defect_lines=(grounding_check.placeholder_lines(st.content)
                          + grounding_check.audit_voice_lines(st.content)),
            focus_note=st.bag.get("focus_note", ""))

        try:
            # Streamed so the user can watch: this step took tens of seconds
            # with a frozen interface, and the model's reasoning -- the most
            # interesting part of it -- was being discarded. The JSON is still
            # accumulated in full before parsing.
            text = ""
            async for kind, piece in llm.stream_events(
                    [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
                    max_tokens=1500, temperature=0.1):
                if kind == "output":
                    text += piece
                yield Event.custom(CUSTOM_PHASE_DELTA, {
                    "round": st.round, "phase": "edit", "kind": kind,
                    "text": piece})
        except Exception as exc:                       # noqa: BLE001
            # A failed revision pass costs this round's fixes, not the round.
            # Measured: under sustained load a single call passed the 300s
            # timeout, and with no guard here the exception escaped the SSE
            # generator -- the client saw the connection cut, not an error.
            yield Event.custom(CUSTOM_DROPPED,
                               {"reason": f"修订调用失败，跳过这一轮修订: {exc}"[:200]})
            return

        parsed = llm.extract_json(text)
        if not isinstance(parsed, list):
            return

        applied = 0
        # How much has already been inserted at each anchor. Two inserts at
        # the same anchor both mean "immediately after it", so the second one
        # lands in front of the first: the model handed over 「### 3. …」 then
        # 「### 4. …」 in the right order and the note ended up with 4 before
        # 3. Any "add two paragraphs in the same place" hits this.
        insert_offsets: dict[str, int] = {}
        outline_mode = bool(st.bag.get("outline_mode"))

        for item in parsed[:max_revisions]:
            if not isinstance(item, dict):
                continue
            op = str(item.get("op") or "").lower()
            if op not in VALID_OPS:
                continue
            anchor = str(item.get("anchor") or "")
            if not anchor or anchor not in st.content:
                continue
            body = str(item.get("text") or "")
            anchor_end = str(item.get("anchor_end") or "")
            reason = str(item.get("reason") or "")
            key = " ".join(anchor.split())[:40]

            why_not = reject_revision(st.content, op, anchor, body, anchor_end,
                                      edited)
            if why_not:
                # Dropping a revision is **the guards working**, not an error.
                # Reported as an error it renders as a wall of red, and
                # several get dropped every round.
                yield Event.custom(CUSTOM_DROPPED,
                                   {"round": st.round, "detail": why_not})
                continue

            updated = _apply_revision(
                st.content, op, anchor, body,
                insert_offset=insert_offsets.get(anchor, 0), anchor_end=anchor_end)
            if updated == st.content:
                continue
            broke = _breakage(st.content, updated)
            if broke:
                yield Event.custom(CUSTOM_DROPPED, {
                    "round": st.round,
                    "detail": f"这条会把正文切出破字「{broke}」，已丢弃：{key[:24]}…"})
                continue
            if outline_mode and not outline.structure_intact(st.content, updated):
                # When the user supplied the outline, anything that alters or
                # deletes one of their headings is dropped. The prompt already
                # says not to touch them; the model does anyway. This is the
                # hard guard behind the request.
                yield Event.custom(CUSTOM_DROPPED, {
                    "round": st.round,
                    "detail": f"这条修订会动到你写的标题，已丢弃：{(reason or op)[:60]}"})
                continue

            if op == "insert":
                insert_offsets[anchor] = insert_offsets.get(anchor, 0) + len(body)
            st.content = _tidy_blank_lines(updated)
            if op in ("replace", "delete"):
                edited.add(key)
            applied += 1
            yield Event.custom(CUSTOM_REVISION, {
                "op": op,
                "anchor": anchor[:120],
                "anchor_end": anchor_end[:120],
                "text": body[:300],
                "reason": reason,
                # EDIT_SYSTEM already asks the model to report which facts a
                # revision rests on. The one-shot endpoint read them and this
                # path didn't: the signal existed and was being dropped.
                "sources": _expand_sources(item.get("sources") or [], st.facts)[:3],
            })

        # **Clean up after revising too.** This used to run only where
        # continuation was saved, and a single replace can put audit voice
        # straight back into the text -- measured on the folder path after
        # the continuation-side scrub was already in place.
        st.content, meta_gone = grounding_check.scrub_meta_sentences_v(st.content)
        for sentence in meta_gone[:3]:
            yield Event.custom(CUSTOM_DROPPED, {
                "round": st.round,
                "detail": f"删掉一句元话语（不该出现在你的笔记里）：{sentence[:60]}"})

        if applied or meta_gone:
            store.update_note(st.ctx.user, st.ctx.note_id, st.ctx.note_title,
                              st.content)
        st.bag["revisions_applied"] = applied
        st.bag["no_change_rounds"] = 0 if applied else st.bag.get("no_change_rounds", 0) + 1
