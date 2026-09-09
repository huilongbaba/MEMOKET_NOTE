"""无限续写：文件夹级别的写作 harness。

不是"轮数封顶的自动续写"——是一个持久化的写作计划（plan + 有序 section
列表），每个 section 独立成一篇笔记，写完当前所有 section 后会主动问一次
"还有没有更多值得写的"，有就追加继续、没有才真正停。停止条件由内容是否
覆盖完整决定，不是轮数。

状态全在 writing_plans/writing_sections 两张表里，SSE 连接断开（用户点
停止）只是暂停——plan 留在 active，section 状态原样留着，下次 /run 直接
从断的地方接着写，不用重新规划。
"""

from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from .. import prompts
from ..database import store
from ..harness import tools
from ..util import llm
from ..harness import loop, modes
from ..harness.events import EventType, to_sse, sse as _sse
from ..harness.hooks.section import SectionHooks
from ..harness.state import State
from ..editor.profile import entries as _profile
from ..database.retrieval import retrieve as _retrieve
from .schemas import WritingPlanOut, WritingPlanRunIn, WritingPlanStartIn
from .deps import current_user

router = APIRouter(prefix="/api/writing-plan", tags=["writing-plan"])

TRACKING_NOTE_TITLE = "📋 写作追踪"

# 单个 section 的轮数上限现在是 ``modes.SECTION.max_rounds``，跟其余的
# 分段配置放在一起；「是否走 agent 自主检索」是 harness.params.AGENT_TOOLS，
# 两条 harness 共用同一个开关——不然用户在文件夹里写和在单篇里写会得到
# 两种质量的产出（实测差别很大：单篇接了工具之后写的是用户自己的材料，
# 分段这边还在编「T0 2026-05-15、DVT 2026-05-20」这种知识库里根本没有的
# 节点）。

# 整个 plan 单次 /run 调用最多处理这么多"步"（写一轮 = 一步，问一次"还有
# 更多吗" = 一步）——真正的终止条件是 more-sections 判定为空，这个只是
# 防失控的安全网，不是"完成"的判定依据。
PLAN_SAFETY_CAP = 300


def _make_summary(title: str, content: str) -> str:
    """便宜的启发式摘要，不额外打一次 LLM 调用。

    这段小结有三个下游：追踪笔记（给用户看）、后续分段的 other_summaries
    （分段之间靠它避免写重复内容）、以及「还有没有更多值得写的」判断
    （靠它决定要不要追加新分段）。

    真实质量采样里抓到的问题：旧版只取「最后一段的前 200 字」，对一篇
    800 字、含三个大节的分段来说完全不能代表它写了什么——一篇《决策、
    冲突与升级机制》的小结只剩下"升级触发条件……"那一段，决策原则和冲突
    处理两大块在小结里完全不存在。结果 more-sections 判断认为"决策与冲突
    处理"还没被覆盖，又追加了一个《决策与冲突处理规范》，两篇内容几乎
    一模一样（"先写后聊""范围分级""48 小时评论期"全都重复）；同一批还
    出现了《工时、在线状态与可预期性》vs《可预期工作时段与在线状态管理》
    这一对。

    改成"标题 + 各级小标题 + 结尾片段"：小标题是零成本就能拿到的结构化
    信息，最能说明这个分段到底覆盖了哪些方面，正是判重最需要的东西。"""
    text = content.strip()
    if not text:
        return f"{title}（空）"
    headings = [
        line.strip().lstrip("#").strip()
        for line in text.splitlines()
        if line.strip().startswith("#")
    ]
    parts = [f"《{title}》"]
    if headings:
        parts.append("覆盖：" + "、".join(headings[:8]))
    tail = [p for p in text.split("\n\n") if p.strip()]
    if tail:
        parts.append(tail[-1].strip()[:120])
    return " ｜ ".join(parts)


def _score_context(section_title: str, goal: str,
                   other_summaries: list[str]) -> dict[str, str]:
    """What the scorer needs to know beyond the text itself.

    Facts are *not* in here. The loop passes the run's accumulated material
    to ``evaluate`` directly, which is the fix for a bug both long-form
    harnesses had: retrieval ran separately in the write step, the revise
    step and the scoring step, so the scorer judged the text against a third
    batch of facts and reported "not found in the knowledge base" about
    material the writer had just used.
    """
    ctx = {"这个分段的主题": section_title}
    if goal:
        ctx["整个写作计划的总体目标"] = goal
    if other_summaries:
        ctx["计划里已完成的其他分段小结"] = "\n".join(f"- {s}" for s in other_summaries)
    return ctx


def _sync_tracking_note(user: str, plan: dict, sections: list[dict]) -> None:
    doc = prompts.render_tracking_doc(plan["goal"], plan["status"], sections)
    if plan.get("doc_note_id"):
        existing = store.get_note(user, plan["doc_note_id"])
        if existing:
            store.update_note(user, plan["doc_note_id"], TRACKING_NOTE_TITLE, doc)
            return
    note = store.create_note(user, TRACKING_NOTE_TITLE, doc, plan["folder_id"])
    store.set_plan_doc_note(user, plan["id"], note["id"])
    plan["doc_note_id"] = note["id"]


@router.get("", response_model=WritingPlanOut)
def get_plan(folder_id: str, user: str = Depends(current_user)):
    plan = store.get_active_plan(user, folder_id)
    if not plan:
        return WritingPlanOut()
    return WritingPlanOut(plan=plan, sections=store.list_sections(plan["id"]))


@router.post("/start", response_model=WritingPlanOut)
async def start_plan(body: WritingPlanStartIn, user: str = Depends(current_user)):
    goal = body.goal.strip()
    if not goal:
        raise HTTPException(400, "goal required")

    facts, _ids, _took = _retrieve(user, goal, "", [], limit=8)
    folder_notes = store.notes_in_folder(user, body.folder_id, limit=8)
    folder_ctx = prompts.folder_context_block(folder_notes)

    plan_system = prompts.compose_system(prompts.PLAN_SYSTEM, "plan_generate", user)
    text = await llm.complete(
        [{"role": "system", "content": plan_system},
         {"role": "user", "content": prompts.plan_user(goal, facts, folder_ctx)}],
        max_tokens=600, temperature=0.4)
    parsed = llm.extract_json(text)
    titles = [str(t).strip() for t in parsed if str(t).strip()] if isinstance(parsed, list) else []
    if not titles:
        raise HTTPException(502, "模型没能生成有效的分段列表，换个目标描述再试试")

    plan = store.create_plan(user, body.folder_id, goal)
    sections = store.add_sections(plan["id"], titles)
    _sync_tracking_note(user, plan, sections)
    return WritingPlanOut(plan=plan, sections=sections)


@router.post("/run")
async def run_plan(body: WritingPlanRunIn, request: Request, user: str = Depends(current_user)):
    """SSE 流式跑 harness 主循环。事件：
        plan-loaded   —— 连接建立时的当前状态
        section-start —— 开始/继续写某个 section，带它落在哪篇笔记
        delta         —— 正文增量
        evaluate      —— 这一轮打分结果（scores/status/weakest）
        section-done  —— 这个 section 结束了（complete/blocked/forced 任一），带小结
        plan-extended —— 「还有更多吗」判定为是，追加了新 section
        plan-done     —— 「还有更多吗」判定为否，整个计划真正完成
        error / done
    """
    plan = store.get_active_plan(user, body.folder_id)
    if not plan:
        raise HTTPException(404, "no active plan for this folder")

    async def gen():
        sections = store.list_sections(plan["id"])
        yield _sse("plan-loaded", {"plan": plan, "sections": sections})

        steps = 0
        while steps < PLAN_SAFETY_CAP:
            steps += 1
            if await request.is_disconnected():
                break

            sections = store.list_sections(plan["id"])
            target = next((s for s in sections if s["status"] in ("pending", "in_progress")), None)

            if target is None:
                done_summaries = [s["summary"] for s in sections if s["summary"]]
                facts, _ids, _took = _retrieve(user, plan["goal"], "", [], limit=8)
                folder_notes = store.notes_in_folder(user, body.folder_id, limit=8)
                folder_ctx = prompts.folder_context_block(folder_notes)
                more_system = prompts.compose_system(
                    prompts.MORE_SECTIONS_SYSTEM, "more_sections", user)
                try:
                    text = await llm.complete(
                        [{"role": "system", "content": more_system},
                         {"role": "user", "content": prompts.more_sections_user(
                             plan["goal"], done_summaries, facts, folder_ctx)}],
                        max_tokens=400, temperature=0.4)
                    parsed = llm.extract_json(text)
                    more = [str(t).strip() for t in parsed if str(t).strip()] if isinstance(parsed, list) else []
                except Exception as exc:
                    # 调用失败不能当成"没有更多分段了"处理——那会把一次
                    # 网络/超时问题误判成计划真的完成了。当成这一步没判成，
                    # 重试，由外层 PLAN_SAFETY_CAP 兜底防止真的卡死。
                    yield _sse("error", {"detail": f"判断是否还有更多分段失败，重试: {exc}"})
                    continue

                if not more:
                    store.set_plan_status(user, plan["id"], "done")
                    plan["status"] = "done"
                    _sync_tracking_note(user, plan, sections)
                    yield _sse("plan-done", {"plan": plan})
                    break

                new_sections = store.add_sections(plan["id"], more)
                _sync_tracking_note(user, plan, sections + new_sections)
                yield _sse("plan-extended", {"sections": new_sections})
                continue

            note = store.get_note(user, target["note_id"]) if target["note_id"] else None
            is_new_note = note is None
            if is_new_note:
                note = store.create_note(user, target["title"], "", body.folder_id)
            if target["status"] != "in_progress" or is_new_note:
                store.update_section(plan["id"], target["id"], status="in_progress", note_id=note["id"])
            target = {**target, "status": "in_progress", "note_id": note["id"]}

            other_summaries = [s["summary"] for s in sections
                               if s["id"] != target["id"] and s["summary"]]
            folder_notes = store.notes_in_folder(
                user, body.folder_id, exclude_id=note["id"], limit=6)

            # One section = one harness run. Rounds, material accumulation,
            # dedup, the repair-vs-continue policy, scoring, best-of and the
            # stop conditions are all in the shared loop now; this function
            # only decides *which* section runs next and what happens to the
            # plan when one finishes.
            st = State(
                mode=modes.for_run(modes.SECTION, has_profile=bool(_profile(user))),
                ctx=tools.ToolContext(user=user, note_id=note["id"],
                                      note_title=target["title"]),
                request=request,
                content=note["content"],
            )
            st.bag["score_context"] = _score_context(
                target["title"], plan["goal"], other_summaries)
            folder_ctx = prompts.folder_context_block(folder_notes)
            hooks = SectionHooks(
                goal=plan["goal"], other_summaries=other_summaries,
                folder_ctx=folder_ctx, profile=_profile(user))
            # 恢复时靠这些重建 hooks（见 routers/harness.py 的 _hooks_for）
            st.bag.update(goal=plan["goal"], other_summaries=other_summaries,
                          folder_ctx=folder_ctx, profile=_profile(user))

            yield _sse("section-start", {
                "section_id": target["id"], "title": target["title"],
                "note_id": note["id"], "is_new_note": is_new_note,
            })

            reason = "max_rounds"
            async for event in loop.run(st, hooks):
                if event.type is EventType.RUN_FINISHED:
                    reason = event.data.get("reason", reason)
                yield to_sse(event)

            summary = _make_summary(target["title"], st.content)
            store.update_section(plan["id"], target["id"], status="done",
                                 summary=summary)
            yield _sse("section-done", {
                "section_id": target["id"], "summary": summary,
                "reason": reason,
                "forced": reason == "max_rounds",
                "material_used_up": reason == "material_used_up",
                "blocked": reason == "blocked",
                "blocked_reason": (st.ev.blocked_reason
                                   if reason == "blocked" and st.ev else None),
            })
            sections = store.list_sections(plan["id"])
            _sync_tracking_note(user, plan, sections)

        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.post("/{folder_id}/abandon")
def abandon_plan(folder_id: str, user: str = Depends(current_user)):
    plan = store.get_active_plan(user, folder_id)
    if not plan:
        raise HTTPException(404, "no active plan for this folder")
    store.set_plan_status(user, plan["id"], "abandoned")
    return {"abandoned": plan["id"]}
