"""写作三件套：骨架（线1）、修订建议（线2）、magic tap 续写。

检索一律先走 UserMemory.recall()（零 LLM、亚毫秒），把命中的事实塞进提示词，
再调模型。magic tap 用 SSE 流式返回，首 token 就能上屏。
"""

from __future__ import annotations

import time
import uuid
from datetime import date as _date
from datetime import timedelta

from fastapi import APIRouter, Depends

from ..harness import prompts
from ..harness.events import sse
from ..harness.params import CONTINUE_TAIL_TOKENS
from ..database import retrieval
from ..editor import profile
from ..util import llm
from ..harness.checks import grounding_rules as grounding_check
from ..database.kite.kite_memory import UserMemory
from .schemas import DigestIn, DigestOut, EditOut, ExpandIn, MagicTapIn, Revision, RewriteIn, SkeletonIn, SkeletonOut, VerifyFinding, VerifyIn, VerifyOut
from .deps import current_user, sse_response

router = APIRouter(prefix="/api", tags=["compose"])

# 拿正文的尾部做检索 —— 用户当前在写的地方才是相关的
TAIL_CHARS = 600

# 个人偏好条数上限：跟知识库事实不一样，这份是用户自己攒的，量级通常不大，
# 但防着万一积累很多年后把 prompt 撑爆——只取最新的一批
PROFILE_LIMIT = 20


def _profile(user: str) -> list[str]:
    """Kept as a thin alias while the routers migrate; the implementation
    moved to ``app/profile.py`` so routers stop importing each other."""
    return profile.entries(user)


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
    """Thin alias while the routers migrate; implementation moved to
    ``app/retrieval.py`` so routers stop importing each other."""
    return retrieval.retrieve(user, content, spine, beats, limit=limit,
                              title=title, anchor_first=anchor_first)


@router.post("/skeleton", response_model=SkeletonOut)
async def skeleton(body: SkeletonIn, user: str = Depends(current_user)):
    """线 1：生成核心张力（spine）+ 结构节拍（beats）。"""
    t0 = time.perf_counter()
    system = prompts.compose_system(prompts.SKELETON_SYSTEM, "skeleton", user)
    parsed, text = await llm.complete_json_raw(
        [{"role": "system", "content": system},
         {"role": "user", "content": prompts.skeleton_user(
             body.title, body.content, _profile(user))}],
        max_tokens=800, temperature=0.4)
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


@router.post("/magic-tap")
async def magic_tap(body: MagicTapIn, user: str = Depends(current_user)):
    """续写。先查知识库，命中就据此写；没命中退回模型自由发挥。

    SSE 流式返回：
        event: meta   —— 检索到的事实数与耗时，前端可以先显示「引用了 N 条记录」
        event: delta  —— 正文增量
        event: done
    """
    facts, ids, took = _retrieve(user, body.content, body.spine, body.beats, limit=6)

    system = prompts.compose_system(prompts.MAGIC_TAP_SYSTEM, "magic_tap", user)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompts.magic_tap_user(
            body.spine, body.beats, body.content, facts, _profile(user),
            following=body.following, title=body.title)},
    ]

    async def gen():
        meta = {"facts": len(facts), "recall_ms": round(took, 3),
                "grounded": bool(facts), "sources": facts[:6], "fact_ids": ids[:6]}
        yield sse("meta", meta)
        written = ""
        stats: dict = {}
        try:
            async for piece in llm.stream(messages, max_tokens=body.max_tokens,
                                          temperature=0.7, stats=stats):
                written += piece
                yield sse("delta", {"text": piece})
        except Exception as exc:
            yield sse("error", {"detail": str(exc)})
        # 撞上限停在半句：跟单篇 / 分段 harness 一样，让模型把那半句收尾（已写的一字不删），
        # 收尾还撞上限才把 truncated 报给前端。
        if stats.get("finish_reason") == "length" and written:
            tail_stats: dict = {}
            tail = messages + [{"role": "assistant", "content": written},
                               {"role": "user", "content": prompts.FINISH_THE_SENTENCE}]
            try:
                async for piece in llm.stream(tail, max_tokens=CONTINUE_TAIL_TOKENS,
                                              temperature=0.7, stats=tail_stats):
                    written += piece
                    yield sse("delta", {"text": piece})
            except Exception as exc:
                yield sse("error", {"detail": str(exc)})
            stats = tail_stats

        # 写完之后确定性地看一眼：检索到了材料，这段有没有真的用上。
        #
        # magic tap 刻意不套完整闭环——它的定位是"点一下几秒出一段"，加上
        # 检索规划和打分就变成智能续写了，两个功能没区别。但这一项是纯计算、
        # 零 LLM、毫秒级，而它对应的正是整晚测出来最深的缺口：评分体系里没有
        # 任何一条在衡量"有没有用上你自己的材料"，通用常识既不矛盾也不编造，
        # 在别的维度上都是满分。这里不打断、不重写，只回一个信号让用户自己
        # 决定要不要重来。
        used, _u = grounding_check.fact_usage(written, facts)
        yield sse("grounding", {
            "facts": len(facts), "used": used,
            "hint": ("" if used or not facts else
                     "这段没用上检索到的记录，写的是通用内容——"
                     "重新点一次，或者先补一句具体的再续写")})
        # 撞 token 上限被切断（实拍一段停在「…写成事项已经完成」没句号）要说出来：
        # 已写的不删（删是拿丢内容掩盖截断），只告诉用户再点一次接着写。
        yield sse("done", {"truncated": stats.get("finish_reason") == "length"})

    return sse_response(gen())


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
    system = prompts.compose_system(prompts.DIGEST_SYSTEM, "digest", user)
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
    system = prompts.compose_system(base, scope, user)
    stats: dict = {}
    text = await llm.complete(
        [{"role": "system", "content": system},
         {"role": "user", "content": prompts.rewrite_user(
             body.content, body.selection, body.spine, body.beats)}],
        max_tokens=600, temperature=0.4, stats=stats)
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
    note = _truncated_note(stats, revisions)   # 撞上限会把 revisions 清空
    return EditOut(revisions=revisions, note=note, took_ms=round((time.perf_counter() - t0) * 1000, 1))


def _truncated_note(stats: dict, revisions: list) -> str:
    """JSON 撞上限切了半截：extract_json 很宽容，`{"text": "改到一半就` 会被修成一条
    只有半句的 replace 修订（测试里实测）——用户一点接受，整段被换成半句。所以撞了
    上限就**清掉建议**、只留一句原因；之前用户看到的是「模型没有给出修改建议」。"""
    if stats.get("finish_reason") != "length":
        return ""
    revisions.clear()
    return "选中的段落太长，模型改到一半撞了长度上限——选短一点再试"


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
    system = prompts.compose_system(prompts.EXPAND_SYSTEM, "expand", user)
    stats: dict = {}
    text = await llm.complete(
        [{"role": "system", "content": system},
         {"role": "user", "content": prompts.expand_user(body.content, body.selection, facts)}],
        max_tokens=500, temperature=0.5, stats=stats)
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
    note = _truncated_note(stats, revisions)   # 撞上限会把 revisions 清空
    return EditOut(revisions=revisions, note=note, took_ms=round((time.perf_counter() - t0) * 1000, 1))


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

    system = prompts.compose_system(prompts.VERIFY_SYSTEM, "verify", user)
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
