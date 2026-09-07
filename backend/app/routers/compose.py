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

from writer_harness import evaluate, find_repeats

from .. import grounding_check, harness_adapter, llm, prompts, store
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
    # 事实带上日期再进 prompt。之前只返回裸文本，导致**整条写作链路里事实的
    # 时间信息从来没进过任何一个 prompt**：修订看不到这条是什么时候说的，
    # 打分判 factual_grounding 时也没法核对正文写的日期跟事实对不对得上——
    # 而这个应用大量在写「硬件 4 月 10 号出来」这类带时间的内容。
    # 日期键在这条路径上是 ``date``（execute_plan 的行），不是 ``when``。
    texts = []
    for r in hits:
        d = (r.get("date") or r.get("when") or "").strip()
        texts.append(f"[{d}] {r['text']}" if d else r["text"])
    return texts, [r.get("id", "") for r in hits], took


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


def _expand_sources_for_edit(raw: list, facts: list[str]) -> list[str]:
    """把模型给的简短来源标记还原成完整事实。跟 note_harness._expand_sources
    同一套语义——模型只回显方括号标记，全文由后端补回来。"""
    out: list[str] = []
    for item in raw[:3]:
        key = str(item).strip().strip("[]")
        if not key:
            continue
        hit = next((f for f in facts if key in f[:60]), None)
        out.append(hit or str(item))
    return out


@router.post("/edit", response_model=EditOut)
async def edit(body: EditIn, user: str = Depends(current_user)):
    """线 2：结合 spine/beats 与知识库，产出 track-changes 修订建议。"""
    t0 = time.perf_counter()
    facts, _ids, _took = _retrieve(user, body.content, body.spine, body.beats)
    dup_hints = find_repeats(body.content)

    # 先诊断：跑一次跟 harness 同一套的七维打分，拿到"这篇现在最弱的是什么"。
    #
    # 之前这个功能是无立场的建议机——跑一遍 EDIT_SYSTEM，把最先注意到的六条
    # 丢给用户，既不知道文章当前哪里弱，也不告诉用户什么时候可以不用再改了。
    # 多花一次打分调用（600 token）换来两件事：建议有针对性，以及**有终点**。
    profile = _profile(user)
    ev_context = {}
    if body.spine:
        ev_context["核心张力"] = body.spine
    if body.beats:
        ev_context["结构节拍"] = "\n".join(f"- {b}" for b in body.beats)
    if facts:
        ev_context["知识库事实"] = "\n".join(f"- {f}" for f in facts)
    try:
        ev = await evaluate(
            harness_adapter.AppLLMClient(), content=body.content,
            dimensions=harness_adapter.note_dimensions(has_profile=bool(profile)),
            context=ev_context or None, dup_hints=dup_hints)
    except Exception:
        ev = None

    scores = ({n: {"level": sc.level, "note": sc.note} for n, sc in ev.scores.items()}
              if ev else {})
    weakest = (ev.weakest or "") if ev else ""

    # 全部达标就直说没什么要改的了，不硬凑建议——一次性工具的终点不是
    # "跑完了"，是"它告诉你不用再改了"。
    if ev and ev.status == "complete":
        return EditOut(revisions=[], took_ms=round((time.perf_counter() - t0) * 1000, 1),
                       scores=scores, weakest="",
                       verdict="七项都达标了，这篇暂时没什么要改的。继续写、或者点打磨再跑一轮都行。")

    system = prompts.compose_system(prompts.EDIT_SYSTEM, store.enabled_skills_for_scope(user, "edit"))
    user_prompt = prompts.edit_user(
        body.spine, body.beats, body.content, facts, profile,
        focus=weakest, dup_hints=dup_hints)
    if body.rejected_anchors:
        # 用户拒绝过的地方别再提——这个信号之前是纯浪费掉的
        user_prompt += ("\n\n【用户看过但不想改的地方，不要再提这几处】\n"
                        + "\n".join(f"- {a[:80]}" for a in body.rejected_anchors[:8]))
    text = await llm.complete(
        [{"role": "system", "content": system},
         {"role": "user", "content": user_prompt}],
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
            # anchor_end 必须一起传给前端：EDIT_SYSTEM 是这条路径和 harness
            # 共用的，模型现在只回显首尾两个短标记而不是整段原文。这里漏掉
            # anchor_end 的话，前端会把 12 个字的起始标记当成整段去 replace，
            # 改错范围——契约改了就得两条路径一起改。
            anchor_end = str(item.get("anchor_end") or "")
            if anchor_end and anchor_end not in body.content:
                anchor_end = ""          # 定位不到就退回只用 anchor
            revisions.append(Revision(
                id=uuid.uuid4().hex[:8],
                op=op,
                anchor=anchor,
                anchor_end=anchor_end,
                text=str(item.get("text") or ""),
                reason=str(item.get("reason") or ""),
                sources=_expand_sources_for_edit(item.get("sources") or [], facts),
            ))
    label = prompts.DIM_SHORT.get(weakest, weakest)
    verdict = (f"现在最弱的是「{label}」，下面 {len(revisions)} 条建议都针对它。"
               if weakest and revisions else
               "没能给出可用的修订建议，换个说法或者补一点内容再试。" if not revisions else "")
    return EditOut(revisions=revisions,
                   took_ms=round((time.perf_counter() - t0) * 1000, 1),
                   scores=scores, weakest=weakest, verdict=verdict)


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
        written = ""
        try:
            async for piece in llm.stream(messages, max_tokens=body.max_tokens,
                                          temperature=0.7):
                written += piece
                yield f"event: delta\ndata: {json.dumps({'text': piece}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'detail': str(exc)}, ensure_ascii=False)}\n\n"

        # 写完之后确定性地看一眼：检索到了材料，这段有没有真的用上。
        #
        # magic tap 刻意不套完整闭环——它的定位是"点一下几秒出一段"，加上
        # 检索规划和打分就变成智能续写了，两个功能没区别。但这一项是纯计算、
        # 零 LLM、毫秒级，而它对应的正是整晚测出来最深的缺口：评分体系里没有
        # 任何一条在衡量"有没有用上你自己的材料"，通用常识既不矛盾也不编造，
        # 在别的维度上都是满分。这里不打断、不重写，只回一个信号让用户自己
        # 决定要不要重来。
        used, _u = grounding_check.fact_usage(written, facts)
        yield ("event: grounding\ndata: "
               + json.dumps({"facts": len(facts), "used": used,
                             "hint": ("" if used or not facts else
                                      "这段没用上检索到的记录，写的是通用内容——"
                                      "重新点一次，或者先补一句具体的再续写")},
                            ensure_ascii=False) + "\n\n")
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
