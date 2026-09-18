from __future__ import annotations

import dataclasses

from fastapi import APIRouter, Depends, HTTPException, Request

from ..database import store
from ..editor import intent as doc_intent
from ..harness import tools
from ..harness import loop, modes
from ..harness.events import to_sse
from ..harness.hooks.note import NoteHooks
from ..harness.state import State
from ..editor.profile import entries as _profile
from .schemas import NoteHarnessRunIn
from .deps import current_user, sse_response

router = APIRouter(prefix="/api/note-harness", tags=["note-harness"])

# The request may ask for more rounds than this; it does not get them. Every
# other limit -- how many rounds a mode wants, when to stall, when the
# material runs out -- is Mode data or a stop condition, and lives with the
# rest of the configuration in harness/modes.py.
MAX_ROUNDS_CAP = 30


def rounds_for(requested: int | None, mode) -> int:
    """这次跑几轮：没传就用模式默认，传了也封在 `MAX_ROUNDS_CAP` 以内（P6 问题 4）。

    P5 实拍：schema 默认 20 + 前端硬传 20，`modes.NOTE.max_rounds = 8` 从来没生效过
    ——`e78306202d78` 跑了 15 轮。轮数是模式的属性；请求只在脚本 / 测试里显式给。
    """
    return max(1, min(requested or mode.max_rounds, MAX_ROUNDS_CAP))


def _score_context(st: State) -> dict[str, str]:
    """What the scorer needs beyond the text itself.

    材料不在这里，它每一轮都在长：`loop._evaluate` 把这次跑累积的那一份
    （`st.facts`）现拼进 context。**必须是累积的那一份，不能在打分前重新检索
    一遍**——那是量出来的真 bug：修订、写作、打分三步各自独立检索，打分器
    拿着第三批事实去判正文，报「知识库里查无此事」，而那一句正是写作那一步
    刚用过的材料。

    **这段话在批 8 之前是假的**（仓里第二处「文档与实现不符」，第一处是批 3
    查出的 `_score()`）：它写着「the loop hands evaluate the run's accumulated
    material directly」，而 `_evaluate` 当时只传 content / dimensions /
    dup_hints / context，**一条事实都没传**。后果是 `material_use` 在生产里
    恒判 2 分——判词写着「没给材料就算达标」，那个满分是判词规定的正确行为，
    跟这一维灵不灵一点关系都没有（台账批 6 ② / 批 7 下一步①）。
    批 8 把实现补上，这段话才成立。
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
                max_rounds=rounds_for(body.max_rounds, modes.NOTE),
                review_each_round=body.review_each_round),
            ctx=tools.ToolContext(user=user, note_id=body.note_id, scope=body.scope,
                                  note_title=note["title"],
                                  # 文档意图（P11）：请求带的优先（标题下那一行此刻的值），没带用库里那份
                                  intent=body.intent or doc_intent.as_text(note.get("intent") or {}),
                                  # 勾过的「完成标准」条目（P13 #1）：勾选是即时 PUT 落库的，库里那份就是此刻的
                                  intent_checked=tuple(doc_intent.normalize(note.get("intent") or {})["checked"]),
                                  # 材料托盘（P14）：跟 intent 同一条路进 harness——库里那份（前端加 / 删 / 拖序都是当场落库）
                                  tray=store.list_tray(user, body.note_id)),
            request=request,
            content=body.content,
        )
        hooks = NoteHooks(polish=polish, spine=body.spine, beats=body.beats,
                          profile=_profile(user))
        # 这次请求的参数。恢复时要靠它重建 hooks——放 bag 里，快照跟着走
        # （见 routers/harness.py 的 _hooks_for）。
        st.bag["polish"] = polish

        # The skeleton is established before the loop starts: a failure here
        # has to be reportable without a round having begun, and every round
        # after it reads spine/beats out of the bag.
        async for event in hooks.skeleton(st):
            yield to_sse(event)

        st.bag["score_context"] = _score_context(st)

        async for event in loop.run(st, hooks):
            yield to_sse(event)

    return sse_response(gen())
