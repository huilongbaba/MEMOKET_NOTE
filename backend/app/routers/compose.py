"""写作三件套：骨架（线1）、修订建议（线2）、magic tap 续写。

检索一律先走 UserMemory.recall()（零 LLM、亚毫秒），把命中的事实塞进提示词，
再调模型。magic tap 用 SSE 流式返回，首 token 就能上屏。
"""

from __future__ import annotations

import time
import uuid
from datetime import date as _date
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException

from ..harness import prompts
from ..harness.events import sse
from ..harness.params import CONTINUE_TAIL_TOKENS
from ..harness.middleware.compact import compact_context

# magic tap 的「已写正文」块最多原样给的字数；再往前的各节折成一行梗概
TAP_KEEP_LAST = 6000
TAP_SUMMARY_MAX = 2000
from ..database import retrieval
from ..editor import profile
from ..editor.preconditions import note_precondition
from ..editor import intent as doc_intent
from ..harness import tray as tray_mod
from ..util import llm
from ..harness.checks import grounding_rules as grounding_check
from ..harness.checks import citations as citation_check
from ..harness.checks.skeleton import beats_budget, check_skeleton, skeleton_length_rule, verify_beats
from ..harness.checks.tap import check_tap
from ..harness.checks.slides import check_slides
from ..database import store
from ..database.kite.kite_memory import UserMemory
from .schemas import DigestIn, DigestOut, SlidesIn, EditOut, ExpandIn, MagicTapIn, Revision, RewriteIn, SkeletonIn, SkeletonOut, VerifyFinding, VerifyIn, VerifyOut
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


def _fact_exists(user: str):
    """给 fake_citations 用的 exists(id)：查一次知识库。测试里替换成集合。"""
    mem = UserMemory(user)

    def exists(fid: str) -> bool:
        try:
            return mem.fact_by_id(fid) is not None
        except Exception:      # noqa: BLE001 — 索引读不出来就当不存在，宁可多摘一个
            return False
    return exists


def why_no_facts(user: str, content: str, scope: str) -> str:
    """续写一条材料都没取到时，给用户一句**能照着做**的原因。纯代码、零 LLM。

    三种情况，按"用户能改什么"排：库是空的（去导入）；范围筛掉了（换档）；
    正文尾巴没命中（换个地方续写 / 先写一句具体的）。
    """
    from ..database.kb.scope import SCOPE_LABEL
    try:
        mem = UserMemory(user)
        if mem.is_empty():
            return "知识库是空的——先导入会议记录或笔记，续写才有材料可引。"
        if scope not in ("", "all"):
            texts, _ids, _took = _retrieve(user, content, "", [], limit=6, scope="all")
            label = SCOPE_LABEL.get(scope, scope)
            if texts:
                return (f"记忆范围现在是「{label}」，这一档里没有能用的记录；"
                        f"「全部」里能取到 {len(texts)} 条。右栏「记忆」顶部可以换档。")
            return f"记忆范围现在是「{label}」，这一档和「全部」都没查到沾边的记录。"
        return "拿光标前面这段正文去查，知识库里没有沾边的记录——先写一句具体的（人名、日期、数字）再续写。"
    except Exception:      # noqa: BLE001 — 解释是附赠的，解释不出来不能影响续写本身
        return ""


def _retrieve(user: str, content: str, spine: str, beats: list[str], limit: int = 8,
              title: str = "", anchor_first: bool = False, scope: str = "all"):
    """Thin alias while the routers migrate; implementation moved to
    ``app/retrieval.py`` so routers stop importing each other."""
    return retrieval.retrieve(user, content, spine, beats, limit=limit,
                              title=title, anchor_first=anchor_first, scope=scope)


@router.post("/skeleton", response_model=SkeletonOut)
async def skeleton(body: SkeletonIn, user: str = Depends(current_user)):
    """线 1：生成核心张力（spine）+ 结构节拍（beats）。"""
    if why := note_precondition("skeleton", body.content, body.title):
        raise HTTPException(400, why)   # 空正文也会花一次模型调用，答一句「内容尚未提供」；前端同一句话先拦
    t0 = time.perf_counter()
    # P7（P4 #1/#3）：条数按正文长度定（每 2k 字一条、6–12）、每条 ≤120 字、开头标「已写：/待补：」——
    # 作为附加段拼进 system，提示词本身（`prompts/writing.py`）不动。
    budget = beats_budget(len(body.content))
    # 文档意图是 system 的第一段（P9，§3.1）：骨架按「这篇要干什么」定，不是按正文猜
    system = doc_intent.block(body.intent) + prompts.compose_system(prompts.SKELETON_SYSTEM, "skeleton", user) + skeleton_length_rule(len(body.content))
    parsed, text = await llm.complete_json_raw(
        [{"role": "system", "content": system},
         {"role": "user", "content": prompts.skeleton_user(
             body.title, body.content, _profile(user))}],
        max_tokens=1600, temperature=0.4)
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
            beats = lines[1:budget + 1]
    beats = beats[:budget]
    # 所见即所存（P4 #1）：返回前就按落库同一条规则收（按句 / 顿号，不按字硬切）
    spine, beats = store.clamp_skeleton(spine, beats)
    # 「待补」的正文里有没有——代码核对（P4 #2），标签统一成「已写：」「待补：」，翻过来的带正文行号
    beats = verify_beats(beats, body.content)
    # 骨架的确定性体检（计划 4.3）。**判了不拦着返回**——照 `slides` 那一档：
    # 骨架是一次成型的产物，不进多轮闭环，判据的结果跟产物一起显示，用户自己
    # 决定要不要重新生成。零模型调用。
    return SkeletonOut(spine=spine, beats=beats,
                       notes=check_skeleton(spine, beats).notes(),
                       took_ms=round((time.perf_counter() - t0) * 1000, 1))


@router.post("/magic-tap")
async def magic_tap(body: MagicTapIn, user: str = Depends(current_user)):
    """续写。先查知识库，命中就据此写；没命中退回模型自由发挥。

    SSE 流式返回：
        event: meta   —— 检索到的事实数与耗时，前端可以先显示「引用了 N 条记录」
        event: delta  —— 正文增量
        event: done
    """
    if why := note_precondition("tap", body.content, body.title):
        raise HTTPException(400, why)   # 空正文空标题照样开流、白花一次模型调用（第 265 轮实测）
    facts, ids, took = _retrieve(user, body.content, body.spine, body.beats, limit=6, scope=body.scope)
    # 材料托盘（P14）：这篇摊在桌上的先摆——排最前、不占检索那 6 条的名额；meta 里也报给前端（TapProvenance）
    tray_items = store.list_tray(user, body.note_id) if body.note_id else []
    tray = tray_mod.lines_of(tray_items)
    tray_ids = [it["ref_id"] for it in tray_items if it.get("kind") == "fact" and it.get("ref_id")]
    facts = tray + [f for f in facts if f not in tray]
    ids = tray_ids + [i for i in ids if i not in tray_ids]

    system = doc_intent.block(body.intent) + prompts.compose_system(prompts.MAGIC_TAP_SYSTEM, "magic_tap", user)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompts.magic_tap_user(
            # 长文只给最近一截 + 前面各节的一行梗概（跟智能续写的 Compact 同一个函数）：
            # 实拍 47k 字的笔记上点续写，整篇 3 万 token 进提示词，慢且没必要。
            body.spine, body.beats, compact_context(body.content, keep_last_chars=TAP_KEEP_LAST, max_summary_chars=TAP_SUMMARY_MAX),
            facts, _profile(user), following=body.following, title=body.title, tray=tray)},
    ]

    async def gen():
        meta = {"facts": len(facts), "recall_ms": round(took, 3),
                "grounded": bool(facts), "sources": facts[:6], "fact_ids": ids[:6],
                "scope": body.scope,
                # 一条没取到时说清楚**为什么**（P1-1a）。用户第 768 轮：「有时有引用，
                # 有时无引用」——零调用量下来，terrence 的 19 篇笔记在「全部」档
                # 篇篇取满 6 条、在「只看笔记」档篇篇 0 条（他的库里没有笔记来源的
                # 事实）。那个下拉存在 localStorage 里，换过一次就一直是那一档，
                # 而续写这边只显示「自由续写 · 知识库中没有相关记录」——
                # **一个用户看不见的条件，在他眼里就是随机**。
                "why_empty": "" if facts else why_no_facts(user, body.content, body.scope)}
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
        # 另外四条确定性体检（计划 8.1，`harness/checks/tap.py`）：停在半句上、
        # 复述了光标前已有的段落、脚手架标题、提示词里的例子被抄进正文。
        # **判了不拦**，跟 `slides` / `skeleton` 同一档——流已经送出去了，这里
        # 只把结果跟产物一起给用户，重不重来由他定。零模型调用。
        yield sse("grounding", {
            "facts": len(facts), "used": used,
            "notes": check_tap(written, body.content).notes(),
            "hint": ("" if used or not facts else
                     "这段没用上检索到的记录，写的是通用内容——"
                     "重新点一次，或者先补一句具体的再续写")})
        # 编造的引用（查不到的 id、或者 `[terrence-23F3-4F3]` 这种格式就不对的）：流已经送出去了，
        # 这里只报 id，前端从刚插入的那段里摘掉——跟单篇 harness 的 grounding 判据同一个口径。
        fake = citation_check.fake_citations(written, facts, _fact_exists(user)) if written else []
        # 撞 token 上限被切断（实拍一段停在「…写成事项已经完成」没句号）要说出来：
        # 已写的不删（删是拿丢内容掩盖截断），只告诉用户再点一次接着写。
        yield sse("done", {"truncated": stats.get("finish_reason") == "length", "fake_citations": fake})

    return sse_response(gen())


@router.post("/slides")
async def slides(body: SlidesIn, user: str = Depends(current_user)):
    """这篇 → 一份幻灯片笔记（痛点 6，docs/slides-plan.md）。

    痛点原话是「想做成 PPT，又要上传给另一个 agent 工具，**两个工具之间没有
    链接**」。所以产物是**一篇笔记**而不是一个文件：落成原笔记的子笔记，于是它
    天然继承这个产品已有的一切——能用 ⌘K 找到、能挂引用、能被智能续写继续改、
    能进知识库、能导出。导出成 .pptx / PDF 是第二步，不是主路径。

    一次模型调用，不进多轮闭环：幻灯片是一次成型的重构，多轮只会把页越改越碎。

    SSE：
        event: delta   —— markdown 增量
        event: slides  —— 页数 + 判据结果 + 落库之后的 note_id
        event: done
    """
    if not body.content.strip():
        raise HTTPException(400, note_precondition("slides", ""))
    note = store.get_note(user, body.note_id) if body.note_id else None

    base = prompts.SLIDES_SYSTEM + (prompts.SLIDES_TALK_EXTRA if body.style == "talk" else "")
    messages = [
        {"role": "system", "content": prompts.compose_system(base, "slides", user)},
        {"role": "user", "content": prompts.slides_user(
            body.title or (note or {}).get("title", ""), body.content, body.style)},
    ]

    async def gen():
        md = ""
        stats: dict = {}
        try:
            async for piece in llm.stream(messages, max_tokens=body.max_tokens,
                                          temperature=0.4, stats=stats):
                md += piece
                yield sse("delta", {"text": piece})
        except Exception as exc:                       # noqa: BLE001
            yield sse("error", {"detail": str(exc)})
            yield sse("done", {})
            return

        md = md.strip()
        check = check_slides(md, body.content)
        note_id = ""
        if note and md:
            # **落成原笔记的子笔记**，同名覆盖：重做一次就该换掉上一份，
            # 而不是在树上留一串「… · 幻灯片」。
            made = store.upsert_child(user, body.note_id, f"{note['title']} · 幻灯片", md,
                                      source="slides", icon="bx-slideshow")
            note_id = made["id"]
        yield sse("slides", {"pages": check.pages, "cite_coverage": check.cite_coverage,
                             "notes": check.notes(), "note_id": note_id,
                             "truncated": stats.get("finish_reason") == "length"})
        yield sse("done", {})

    return sse_response(gen())


@router.post("/digest", response_model=DigestOut)
async def digest(body: DigestIn, user: str = Depends(current_user)):
    """阶段回顾：把某段时间的 facts 喂给模型，按「核心结论/关键决定/待跟进/
    值得注意的变化」总结——不用手动翻记录就能找回一段时间发生了什么。"""
    t0 = time.perf_counter()
    date_to = body.date_to or _date.today().isoformat()
    date_from = body.date_from or (_date.today() - timedelta(days=body.days)).isoformat()

    rows = UserMemory(user).facts_between(date_from, date_to)
    # 「全部」也要走一遍：它不含屏幕活动（kb/scope.filter_rows）。阶段回顾里
    # 混进几百条「你在看某个网页」，这份回顾就没法读了。
    from ..database.kb.scope import filter_rows
    rows = filter_rows(rows, body.scope)
    if not rows:
        from ..database.kb.scope import SCOPE_LABEL
        empty = ("这段时间没有记录。" if body.scope in ("", "all")
                 else f"这段时间「{SCOPE_LABEL.get(body.scope, body.scope)}」范围内没有记录，换成「全部记忆」再试。")
        return DigestOut(summary=empty, fact_count=0,
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
    if not body.selection.strip():
        raise HTTPException(400, "没有选中内容")   # 空选区一样会花一次模型调用然后回空（第 168 轮实测）
    t0 = time.perf_counter()
    if body.selection not in body.content:
        return EditOut(revisions=[], took_ms=round((time.perf_counter() - t0) * 1000, 1))
    base = prompts.POLISH_SYSTEM if body.intent == "polish" else prompts.REWRITE_SYSTEM
    scope = "polish" if body.intent == "polish" else "rewrite"
    system = doc_intent.block(body.doc_intent) + prompts.compose_system(base, scope, user)
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
    if not body.selection.strip():
        raise HTTPException(400, "没有选中内容")   # 空选区一样会花一次模型调用然后回空（第 168 轮实测）
    t0 = time.perf_counter()
    if body.selection not in body.content:
        return EditOut(revisions=[], took_ms=round((time.perf_counter() - t0) * 1000, 1))
    # 之前这里没查知识库——"补充缺失的上下文"这个任务本来就该优先从用户
    # 真实的知识库事实里来，不查的话模型只能自己编一个听起来合理但查无
    # 实据的背景（审查中实测到："团队把电池容量、功耗优化和充电策略一起
    # 纳入关键路径评审"这类具体但没有任何依据的细节）。查询用选中片段本身
    # 当线索，跟校验（verify）用同一个思路。
    facts, _ids, _took = _retrieve(user, body.selection, "", [], limit=6, scope=body.scope)
    # 托盘先摆（P14）：补上下文优先从用户摊在桌上的材料里补
    tray = tray_mod.lines_of(store.list_tray(user, body.note_id)) if body.note_id else []
    facts = tray + [f for f in facts if f not in tray]
    system = doc_intent.block(body.intent) + prompts.compose_system(prompts.EXPAND_SYSTEM, "expand", user)
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


def _cited_near(content: str, selection: str) -> list[str]:
    """选区所在段落（找不到选区就整篇）里引用的事实 id，保持出现顺序。"""
    i = content.find(selection) if selection else -1
    if i < 0:
        scope = selection
    else:
        start = content.rfind("\n\n", 0, i) + 2 if content.rfind("\n\n", 0, i) >= 0 else 0
        end = content.find("\n\n", i + len(selection))
        scope = content[start:end if end >= 0 else len(content)]
    return citation_check.cited_ids(scope)[:6]


@router.post("/verify", response_model=VerifyOut)
async def verify(body: VerifyIn, user: str = Depends(current_user)):
    """选中文本 -> 核对笔记内部一致性 + 知识库事实，返回带证据引用的判断。
    检索走 recall()（零 LLM），只有判断这一步调模型——跟线2/续写同一个
    "快检索 + 一次 LLM 调用"节奏，不是 KITE 的 ask()/planning 那条慢路径。"""
    if not body.selection.strip():
        raise HTTPException(400, "没有选中内容")   # 空选区一样会花一次模型调用然后回空（第 168 轮实测）
    t0 = time.perf_counter()
    mem = UserMemory(user)
    # 用户已经在这段旁边引了的事实，是最直接的证据：先按 id 取，再补词法召回。
    # 实拍：选中「4 月 16 日的 EVT 准备 4 台主机 15 套 PCBA」，同一段紧跟着 [terrence-2046-12F1]
    # 这些引用，词法召回却没把它们捞回来，模型只能答「知识库没有记录」。
    hits: list[dict] = []
    for fid in _cited_near(body.content, body.selection):
        f = mem.fact_by_id(fid)
        if f and f.get("text"):
            f = dict(f, date=f.get("date") or f.get("when", ""))
            hits.append(f)
    rows, _terms, _took = mem.recall(body.selection, limit=6, scope=body.scope)
    seen = {h["id"] for h in hits}
    hits += [r for r in rows if r.get("text") and r["id"] not in seen]
    facts = [r["text"] for r in hits]
    # 托盘先摆（P14）：用户摊在桌上的材料是最直接的证据，排在引用过的和词法召回的前面
    tray = tray_mod.lines_of(store.list_tray(user, body.note_id)) if body.note_id else []
    facts = tray + [f for f in facts if f not in tray]

    system = doc_intent.block(body.intent) + prompts.compose_system(prompts.VERIFY_SYSTEM, "verify", user)
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
