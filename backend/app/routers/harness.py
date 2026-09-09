"""Resume a run the user paused to review.

The loop stops at the end of a round when the Mode asks it to, writes a
snapshot, and hands the client a ``run_id``. The user then accepts or rejects
what that round wrote -- in the editor, per hunk -- and posts the text they
kept back here. The run continues from the round after, with the user's
version as the content.

**Why the content comes from the client.** The editor is where the user's
decisions live; asking the backend to reconstruct them from a list of hunk
ids would mean two implementations of the same merge, and the one that ran
in the browser is the one the user actually saw. What arrives here is
therefore treated as the truth about the note and saved as-is.

This is one endpoint and one stop condition. Nothing in the loop knows that
pausing exists -- which is what the composable stop conditions were for.
"""

from __future__ import annotations

import dataclasses

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..database import store
from ..harness import loop, modes, snapshot
from ..harness.events import to_sse
from ..harness.hooks.block import BlockHooks
from ..harness.hooks.note import NoteHooks
from ..harness.hooks.section import SectionHooks
from ..editor.profile import entries as _profile
from .schemas import HarnessResumeIn
from .deps import current_user

router = APIRouter(prefix="/api/harness", tags=["harness"])


@router.get("/paused")
def list_paused(user: str = Depends(current_user), limit: int = 20) -> list[dict]:
    """Runs waiting for this user. A paused run is invisible otherwise -- the
    SSE stream that produced it is long gone."""
    return store.list_snapshots(user, limit=limit)


@router.post("/{run_id}/resume")
async def resume(run_id: str, body: HarnessResumeIn, request: Request,
                 user: str = Depends(current_user)):
    """Continue from the snapshot. SSE, same event contract as the first run."""
    row = store.get_snapshot(user, run_id)
    if not row:
        raise HTTPException(404, "这次暂停的运行已经不在了（可能已经恢复过，或者太旧被清理了）")

    mode = _mode_for(row["mode"])
    st = snapshot.loads(row["state"], mode)
    if body.content:
        # What the user kept. Overwrites the round's output rather than
        # merging with it: the merge already happened in the editor.
        st.content = body.content
    if body.stop:
        store.delete_snapshot(user, run_id)
        if st.content and st.ctx.note_id:
            store.update_note(user, st.ctx.note_id, st.ctx.note_title, st.content)
        return {"stopped": run_id, "rounds": st.round}

    hooks = _hooks_for(row["mode"], st)
    # Consumed on resume: a snapshot that could be resumed twice would fork
    # the run, and both forks would write to the same note.
    store.delete_snapshot(user, run_id)

    async def gen():
        st.request = request
        async for event in loop.run(st, hooks):
            yield to_sse(event)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def _mode_for(key: str):
    """The current Mode for that key, with review still on and the rounds
    already spent taken off the budget.

    Mode comes from code, not from the snapshot: a run resumed after a deploy
    should get today's checks and dimensions. Review stays on -- the user
    asked for it once and pausing again is what they expect.

    ``max_rounds`` is *not* adjusted: the loop counts on from the rounds
    already spent, so the budget is still the whole budget.
    """
    mode = modes.BLOCK.get(key) or next((m for m in modes.ALL if m.key == key), None)
    if mode is None:
        raise HTTPException(400, f"不认识的模式 {key!r}")
    return dataclasses.replace(mode, review_each_round=True)


def _hooks_for(key: str, st):
    """Rebuild the harness's callbacks from what the snapshot kept.

    Hooks hold the request's own parameters -- the prompt a user typed, the
    plan's goal. Those are in ``bag`` precisely so a resumed run is not a
    weaker version of the original.
    """
    bag = st.bag
    if key == "note":
        return NoteHooks(polish=bool(bag.get("polish")),
                         spine=bag.get("spine", ""),
                         beats=list(bag.get("beats") or []),
                         profile=list(bag.get("profile") or _profile(st.ctx.user)))
    if key == "section":
        return SectionHooks(goal=bag.get("goal", ""),
                            other_summaries=list(bag.get("other_summaries") or []),
                            folder_ctx=bag.get("folder_ctx", ""),
                            profile=list(bag.get("profile") or _profile(st.ctx.user)))
    return BlockHooks(prompt=bag.get("prompt", ""),
                      selection=bag.get("selection", ""),
                      profile=list(bag.get("profile") or _profile(st.ctx.user)),
                      title=st.ctx.note_title)
