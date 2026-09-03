"""写作三件套：骨架（线1）、修订建议（线2）、magic tap 续写。

检索一律先走 UserMemory.recall()（零 LLM、亚毫秒），把命中的事实塞进提示词，
再调模型。magic tap 用 SSE 流式返回，首 token 就能上屏。
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import date as _date
from datetime import timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from .. import llm, prompts, store
from ..kite_memory import UserMemory
from ..schemas import (DigestIn, DigestOut, EditIn, EditOut, ExpandIn,
                       MagicTapIn, Revision, RewriteIn, SkeletonIn,
                       SkeletonOut, VerifyFinding, VerifyIn, VerifyOut)
from .deps import current_user

router = APIRouter(prefix="/api", tags=["compose"])

# 拿正文的尾部做检索 —— 用户当前在写的地方才是相关的
TAIL_CHARS = 600

# 个人偏好条数上限：跟知识库事实不一样，这份是用户自己攒的，量级通常不大，
# 但防着万一积累很多年后把 prompt 撑爆——只取最新的一批
PROFILE_LIMIT = 20


def _profile(user: str) -> list[str]:
    return [p["text"] for p in store.list_profile(user)[:PROFILE_LIMIT]]


# harness 自动多轮跑时，正文只取这么多字符——不是不要正文，是不能让它
# 主导查询。
#
# 真实质量采样撞到的问题：检索线索只用「正文最后 600 字」，harness 一轮轮
# 续写之后尾部全是新展开的细节，早就偏离这篇笔记的主题了——同一篇笔记
# 前两轮各命中 6 条真实知识库事实，第三轮命中 0 条。
#
# 第一版修复试过「再带上正文开头 300 字当主题锚点」，实测证明方向就是错的
# ——拿同一篇长正文对比五种查询构造，"只有尾部"和"开头+尾部"都命中一堆
# 完全无关的内容（写众筹的笔记命中了 Google 合作的对话），因为长正文里的
# 通用词汇会淹没主题词；而"标题+spine+少量尾部"和"只有标题"都稳定命中 6 条
# 全部相关的事实（Kickstarter $5 预留、5 月样机、Referral 测试）。
# 结论：稳定锚点（标题/spine/beats）才是主题信号，正文越长越是噪声源，
# 加更多正文治不好，得让锚点主导、正文让位。
TAIL_CHARS_FOR_HARNESS = 300


def _retrieve(user: str, content: str, spine: str, beats: list[str], limit: int = 8,
              title: str = "", anchor_first: bool = False):
    """用正文尾部 + spine/beats 作为检索线索。返回 (事实文本列表, 对应 fact id 列表, 耗时毫秒)。

    fact id 跟着文本一起传出去，是为了让前端能把「续写用了这条事实」精确
    链回 /api/memory/facts/{id}/sources 的原始对话行——不然 grounding 只是
    一句自称，用户没法验证。
    """
    mem = UserMemory(user)
    if anchor_first:
        # harness：稳定锚点（标题/spine/beats）主导，正文只留少量尾部说明
        # "当前写到哪了"。顺序也有意义——放前面的词在关键词匹配里权重更高。
        anchors = [a for a in (title, spine, " ".join(beats[-3:])) if a]
        query = "\n".join(anchors + [content[-TAIL_CHARS_FOR_HARNESS:]])
    else:
        # magic tap：用户在光标处续写，正文尾部就是"用户当前在写的地方"，
        # 是最相关的线索，保持原行为不动。
        query = content[-TAIL_CHARS:]
        hint = " ".join([spine] + beats[-3:]) if spine or beats else ""
        if hint:
            query = hint + "\n" + query
    rows, _terms, took = mem.recall(query, limit=limit)
    hits = [r for r in rows if r.get("text")]
    return [r["text"] for r in hits], [r.get("id", "") for r in hits], took


@router.post("/skeleton", response_model=SkeletonOut)
async def skeleton(body: SkeletonIn, user: str = Depends(current_user)):
    """线 1：生成核心张力（spine）+ 结构节拍（beats）。"""
    t0 = time.perf_counter()
    system = prompts.compose_system(prompts.SKELETON_SYSTEM, store.enabled_skills_for_scope(user, "skeleton"))
    text = await llm.complete(
        [{"role": "system", "content": system},
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
    facts, _ids, _took = _retrieve(user, body.content, body.spine, body.beats)

    system = prompts.compose_system(prompts.EDIT_SYSTEM, store.enabled_skills_for_scope(user, "edit"))
    text = await llm.complete(
        [{"role": "system", "content": system},
         {"role": "user", "content": prompts.edit_user(
             body.spine, body.beats, body.content, facts, _profile(user))}],
        max_tokens=1500, temperature=0.1)

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
    facts, ids, took = _retrieve(user, body.content, body.spine, body.beats, limit=6)

    system = prompts.compose_system(prompts.MAGIC_TAP_SYSTEM, store.enabled_skills_for_scope(user, "magic_tap"))
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompts.magic_tap_user(
            body.spine, body.beats, body.content, facts, _profile(user))},
    ]

    async def gen():
        meta = {"facts": len(facts), "recall_ms": round(took, 3),
                "grounded": bool(facts), "sources": facts[:6], "fact_ids": ids[:6]}
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


@router.post("/digest", response_model=DigestOut)
async def digest(body: DigestIn, user: str = Depends(current_user)):
    """阶段回顾：把某段时间的 facts 喂给模型，按「核心结论/关键决定/待跟进/
    值得注意的变化」总结——不用手动翻记录就能找回一段时间发生了什么。"""
    t0 = time.perf_counter()
    date_to = body.date_to or _date.today().isoformat()
    date_from = body.date_from or (_date.today() - timedelta(days=body.days)).isoformat()

    rows = UserMemory(user).facts_between(date_from, date_to)
    if not rows:
        return DigestOut(summary="这段时间没有记录。", fact_count=0,
                         date_from=date_from, date_to=date_to,
                         took_ms=round((time.perf_counter() - t0) * 1000, 1))

    facts = [f"[{r['when']}] {r['text']}" for r in rows]
    system = prompts.compose_system(prompts.DIGEST_SYSTEM, store.enabled_skills_for_scope(user, "digest"))
    text = await llm.complete(
        [{"role": "system", "content": system},
         {"role": "user", "content": prompts.digest_user(facts)}],
        max_tokens=1200, temperature=0.3)
    return DigestOut(summary=text.strip(), fact_count=len(rows),
                     date_from=date_from, date_to=date_to,
                     took_ms=round((time.perf_counter() - t0) * 1000, 1))


# ---------------------------------------------------------------- 选中文本操作
#
# 右键选中一段文本触发的三个动作。都产出跟线2同一个 Revision 模型的结果，
# 复用前端已有的接受/拒绝 UI，不用另起一套展示层。

@router.post("/rewrite", response_model=EditOut)
async def rewrite(body: RewriteIn, user: str = Depends(current_user)):
    """选中文本 -> 重写/润色，产出一条 replace 修订。"""
    t0 = time.perf_counter()
    if body.selection not in body.content:
        return EditOut(revisions=[], took_ms=round((time.perf_counter() - t0) * 1000, 1))
    base = prompts.POLISH_SYSTEM if body.intent == "polish" else prompts.REWRITE_SYSTEM
    scope = "polish" if body.intent == "polish" else "rewrite"
    system = prompts.compose_system(base, store.enabled_skills_for_scope(user, scope))
    text = await llm.complete(
        [{"role": "system", "content": system},
         {"role": "user", "content": prompts.rewrite_user(
             body.content, body.selection, body.spine, body.beats)}],
        max_tokens=600, temperature=0.4)
    parsed = llm.extract_json(text)
    revisions: list[Revision] = []
    if isinstance(parsed, dict):
        new_text = str(parsed.get("text") or "").strip()
        if new_text:
            default_reason = "润色" if body.intent == "polish" else "重写"
            revisions.append(Revision(
                id=uuid.uuid4().hex[:8], op="replace", anchor=body.selection,
                text=new_text, reason=str(parsed.get("reason") or default_reason),
            ))
    return EditOut(revisions=revisions, took_ms=round((time.perf_counter() - t0) * 1000, 1))


@router.post("/expand", response_model=EditOut)
async def expand(body: ExpandIn, user: str = Depends(current_user)):
    """选中文本 -> 往前/往后补上下文，最多产出两条修订
    （insert_before 补在前面、insert 补在后面），各自独立可接受。"""
    t0 = time.perf_counter()
    if body.selection not in body.content:
        return EditOut(revisions=[], took_ms=round((time.perf_counter() - t0) * 1000, 1))
    # 之前这里没查知识库——"补充缺失的上下文"这个任务本来就该优先从用户
    # 真实的知识库事实里来，不查的话模型只能自己编一个听起来合理但查无
    # 实据的背景（审查中实测到："团队把电池容量、功耗优化和充电策略一起
    # 纳入关键路径评审"这类具体但没有任何依据的细节）。查询用选中片段本身
    # 当线索，跟校验（verify）用同一个思路。
    facts, _ids, _took = _retrieve(user, body.selection, "", [], limit=6)
    system = prompts.compose_system(prompts.EXPAND_SYSTEM, store.enabled_skills_for_scope(user, "expand"))
    text = await llm.complete(
        [{"role": "system", "content": system},
         {"role": "user", "content": prompts.expand_user(body.content, body.selection, facts)}],
        max_tokens=500, temperature=0.5)
    parsed = llm.extract_json(text)
    revisions: list[Revision] = []
    if isinstance(parsed, dict):
        # before/after 共用同一份 sources：EXPAND_SYSTEM 只要求模型报一次
        # 依据，不区分是给 before 用的还是给 after 用的（多数情况只会写
        # 其中一个方向，分开要求没有实际意义，徒增模型输出复杂度）。
        sources = [str(s) for s in (parsed.get("sources") or [])][:3]
        before = str(parsed.get("before") or "").strip()
        after = str(parsed.get("after") or "").strip()
        if before:
            revisions.append(Revision(
                id=uuid.uuid4().hex[:8], op="insert_before", anchor=body.selection,
                text=before, reason="往前补充上下文", sources=sources,
            ))
        if after:
            revisions.append(Revision(
                id=uuid.uuid4().hex[:8], op="insert", anchor=body.selection,
                text=after, reason="往后补充上下文", sources=sources,
            ))
    return EditOut(revisions=revisions, took_ms=round((time.perf_counter() - t0) * 1000, 1))


@router.post("/verify", response_model=VerifyOut)
async def verify(body: VerifyIn, user: str = Depends(current_user)):
    """选中文本 -> 核对笔记内部一致性 + 知识库事实，返回带证据引用的判断。
    检索走 recall()（零 LLM），只有判断这一步调模型——跟线2/续写同一个
    "快检索 + 一次 LLM 调用"节奏，不是 KITE 的 ask()/planning 那条慢路径。"""
    t0 = time.perf_counter()
    mem = UserMemory(user)
    rows, _terms, _took = mem.recall(body.selection, limit=6)
    hits = [r for r in rows if r.get("text")]
    facts = [r["text"] for r in hits]

    system = prompts.compose_system(prompts.VERIFY_SYSTEM, store.enabled_skills_for_scope(user, "verify"))
    text = await llm.complete(
        [{"role": "system", "content": system},
         {"role": "user", "content": prompts.verify_user(body.content, body.selection, facts)}],
        max_tokens=800, temperature=0.1)
    parsed = llm.extract_json(text)
    findings: list[VerifyFinding] = []
    if isinstance(parsed, list):
        for item in parsed[:4]:
            if not isinstance(item, dict):
                continue
            verdict = str(item.get("verdict") or "")
            if verdict not in ("矛盾", "支持", "无法判断"):
                continue
            idx = item.get("fact_index")
            fact_id = fact_text = ""
            sources: list[str] = []
            if isinstance(idx, int) and 0 <= idx < len(hits):
                fact_id = hits[idx].get("id", "")
                fact_text = hits[idx].get("text", "")
                sources = mem.source_lines(hits[idx])
            findings.append(VerifyFinding(
                verdict=verdict, reason=str(item.get("reason") or ""),
                fact_id=fact_id, fact_text=fact_text, sources=sources,
            ))
    return VerifyOut(findings=findings, took_ms=round((time.perf_counter() - t0) * 1000, 1))
