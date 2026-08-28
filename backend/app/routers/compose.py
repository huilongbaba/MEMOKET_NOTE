"""写作三件套：骨架（线1）、修订建议（线2）、magic tap 续写。

检索一律先走 UserMemory.recall()（零 LLM、亚毫秒），把命中的事实塞进提示词，
再调模型。magic tap 用 SSE 流式返回，首 token 就能上屏。
"""

from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from .. import llm, prompts, store
from ..kite_memory import UserMemory
from ..schemas import (EditIn, EditOut, MagicTapIn, Revision, SkeletonIn,
                       SkeletonOut)
from .deps import current_user

router = APIRouter(prefix="/api", tags=["compose"])

# 拿正文的尾部做检索 —— 用户当前在写的地方才是相关的
TAIL_CHARS = 600

# 个人偏好条数上限：跟知识库事实不一样，这份是用户自己攒的，量级通常不大，
# 但防着万一积累很多年后把 prompt 撑爆——只取最新的一批
PROFILE_LIMIT = 20


def _profile(user: str) -> list[str]:
    return [p["text"] for p in store.list_profile(user)[:PROFILE_LIMIT]]


def _retrieve(user: str, content: str, spine: str, beats: list[str], limit: int = 8):
    """用正文尾部 + spine/beats 作为检索线索。返回 (事实文本列表, 耗时毫秒)。"""
    mem = UserMemory(user)
    query = content[-TAIL_CHARS:]
    hint = " ".join([spine] + beats[-3:]) if spine or beats else ""
    if hint:
        query = hint + "\n" + query
    rows, _terms, took = mem.recall(query, limit=limit)
    return [r.get("text", "") for r in rows if r.get("text")], took


@router.post("/skeleton", response_model=SkeletonOut)
async def skeleton(body: SkeletonIn, user: str = Depends(current_user)):
    """线 1：生成核心张力（spine）+ 结构节拍（beats）。"""
    t0 = time.perf_counter()
    text = await llm.complete(
        [{"role": "system", "content": prompts.SKELETON_SYSTEM},
         {"role": "user", "content": prompts.skeleton_user(
             body.title, body.content, _profile(user))}],
        max_tokens=800, temperature=0.4)
    parsed = llm.extract_json(text)
    spine = ""
    beats: list[str] = []
    if isinstance(parsed, dict):
        spine = str(parsed.get("spine") or "").strip()
        raw_beats = parsed.get("beats")
        if isinstance(raw_beats, list):
            beats = [str(x).strip() for x in raw_beats if str(x).strip()]
    if not spine and not beats and text:
        # 模型没给出合法 JSON 时退回按行解析：第一行当 spine，其余当 beats
        lines = [ln.lstrip("-*0123456789. ").strip()
                 for ln in text.splitlines() if ln.strip()]
        if lines:
            spine = lines[0]
            beats = lines[1:7]
    return SkeletonOut(spine=spine, beats=beats[:6],
                       took_ms=round((time.perf_counter() - t0) * 1000, 1))


@router.post("/edit", response_model=EditOut)
async def edit(body: EditIn, user: str = Depends(current_user)):
    """线 2：结合 spine/beats 与知识库，产出 track-changes 修订建议。"""
    t0 = time.perf_counter()
    facts, _took = _retrieve(user, body.content, body.spine, body.beats)

    text = await llm.complete(
        [{"role": "system", "content": prompts.EDIT_SYSTEM},
         {"role": "user", "content": prompts.edit_user(
             body.spine, body.beats, body.content, facts, _profile(user))}],
        max_tokens=1500, temperature=0.2)

    parsed = llm.extract_json(text)
    revisions: list[Revision] = []
    if isinstance(parsed, list):
        for item in parsed[:6]:
            if not isinstance(item, dict):
                continue
            op = str(item.get("op", "")).lower()
            if op not in ("insert", "delete", "replace"):
                continue
            anchor = str(item.get("anchor") or "")
            # anchor 必须真的在正文里，否则前端定位不到，直接丢弃这条
            if op in ("delete", "replace") and anchor not in body.content:
                continue
            if op == "insert" and anchor and anchor not in body.content:
                continue
            revisions.append(Revision(
                id=uuid.uuid4().hex[:8],
                op=op,
                anchor=anchor,
                text=str(item.get("text") or ""),
                reason=str(item.get("reason") or ""),
                sources=[str(s) for s in (item.get("sources") or [])][:3],
            ))
    return EditOut(revisions=revisions,
                   took_ms=round((time.perf_counter() - t0) * 1000, 1))


@router.post("/magic-tap")
async def magic_tap(body: MagicTapIn, user: str = Depends(current_user)):
    """续写。先查知识库，命中就据此写；没命中退回模型自由发挥。

    SSE 流式返回：
        event: meta   —— 检索到的事实数与耗时，前端可以先显示「引用了 N 条记录」
        event: delta  —— 正文增量
        event: done
    """
    facts, took = _retrieve(user, body.content, body.spine, body.beats, limit=6)

    messages = [
        {"role": "system", "content": prompts.MAGIC_TAP_SYSTEM},
        {"role": "user", "content": prompts.magic_tap_user(
            body.spine, body.beats, body.content, facts, _profile(user))},
    ]

    async def gen():
        meta = {"facts": len(facts), "recall_ms": round(took, 3),
                "grounded": bool(facts), "sources": facts[:6]}
        yield f"event: meta\ndata: {json.dumps(meta, ensure_ascii=False)}\n\n"
        try:
            async for piece in llm.stream(messages, max_tokens=body.max_tokens,
                                          temperature=0.7):
                yield f"event: delta\ndata: {json.dumps({'text': piece}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'detail': str(exc)}, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
