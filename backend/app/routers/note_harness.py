from __future__ import annotations

import dataclasses

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from .. import store, tools
from ..harness import loop, modes
from ..harness.events import legacy_frames, sse as _sse
from ..harness.hooks.note import NoteHooks
from ..harness.state import State
from ..profile import entries as _profile
from ..schemas import NoteHarnessRunIn
from .deps import current_user

router = APIRouter(prefix="/api/note-harness", tags=["note-harness"])

# The request may ask for more rounds than this; it does not get them. Every
# other limit -- how many rounds a mode wants, when to stall, when the
# material runs out -- is Mode data or a stop condition, and lives with the
# rest of the configuration in harness/modes.py.
MAX_ROUNDS_CAP = 30


def _score_context(st: State) -> dict[str, str]:
    """What the scorer needs beyond the text itself.

    Facts are not in here: the loop hands ``evaluate`` the run's accumulated
    material directly. That is the fix for a measured bug -- the revise, write
    and score steps each retrieved independently, so the scorer judged the
    text against a third batch of facts and reported "not found in the
    knowledge base" about a line the writer had just used.
    """
    ctx: dict[str, str] = {}
    spine, beats = st.bag.get("spine", ""), st.bag.get("beats") or []
    if spine:
        ctx["核心张力"] = spine
    if beats:
        ctx["结构节拍"] = "\n".join(f"- {b}" for b in beats)
    if st.bag.get("outline_mode"):
        # In outline mode the headings are the **user's**, not part of the
        # output. Without saying so the scorer marks them down: three rounds
        # running, coherence read 「产品和众筹使用三级标题而时间线、团队、
        # 反思使用二级标题，造成标题层级不统一」 -- that is the structure the
        # user supplied, and a hard guard elsewhere guarantees it cannot be
        # changed. Penalised and unfixable is a loop that can only spin.
        ctx["标题结构"] = ("正文里的所有标题都是用户自己写好的大纲，写作这一步"
                           "只负责往标题下面填正文。**不要评价标题的层级、措辞或"
                           "顺序**，那是用户的写作意图，不是这次产出的一部分；"
                           "只看每一节的正文写得怎么样。")
    return ctx


@router.post("/run")
async def run(body: NoteHarnessRunIn, request: Request,
              user: str = Depends(current_user)):
    """SSE 流式跑单篇 harness。事件契约见 harness/events.py。

    循环本身在 ``harness.loop``，三条 harness 共用一份。这里剩下的是这条
    harness 独有的东西：骨架（spine/beats）怎么来、打磨模式怎么配、以及把
    AG-UI 事件翻成前端现在听的那套名字。
    """
    note = store.get_note(user, body.note_id)
    if not note:
        raise HTTPException(404, "note not found")

    async def gen():
        polish = body.mode == "polish"
        st = State(
            mode=dataclasses.replace(
                modes.for_run(modes.NOTE, has_profile=bool(_profile(user)),
                              polish=polish),
                max_rounds=max(1, min(body.max_rounds, MAX_ROUNDS_CAP))),
            ctx=tools.ToolContext(user=user, note_id=body.note_id,
                                  note_title=note["title"]),
            request=request,
            content=body.content,
        )
        st.bag["polish"] = polish
        hooks = NoteHooks(polish=polish, spine=body.spine, beats=body.beats,
                          profile=_profile(user))

        # The skeleton is established before the loop starts: a failure here
        # has to be reportable without a round having begun, and every round
        # after it reads spine/beats out of the bag.
        async for name, payload in hooks.skeleton(st):
            yield _sse(name, payload)

        st.bag["score_context"] = _score_context(st)

        async for event in loop.run(st, hooks):
            for frame in legacy_frames(event):
                yield frame

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
