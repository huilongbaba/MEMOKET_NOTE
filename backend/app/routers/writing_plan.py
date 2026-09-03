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

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from writer_harness import Evaluation, RunRecord, evaluate, find_repeats

from .. import harness_adapter, llm, prompts, store
from ..schemas import WritingPlanOut, WritingPlanRunIn, WritingPlanStartIn
from .compose import _profile, _retrieve
from .deps import current_user
from .note_harness import _apply_revision  # 纯字符串函数，两条 harness 共用

router = APIRouter(prefix="/api/writing-plan", tags=["writing-plan"])

TRACKING_NOTE_TITLE = "📋 写作追踪"

# 单个 section 最多写这么多轮还没被 evaluate() 判定 complete/blocked 就
# 强制结束——防止某个 section 卡住整个 plan 永远走不下去，是安全网，不是
# "完成"的判定依据（判定依据见 _evaluate_section）。
SECTION_ROUND_CAP = 4

# 整个 plan 单次 /run 调用最多处理这么多"步"（写一轮 = 一步，问一次"还有
# 更多吗" = 一步）——真正的终止条件是 more-sections 判定为空，这个只是
# 防失控的安全网，不是"完成"的判定依据。
PLAN_SAFETY_CAP = 300

def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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


async def _evaluate_section(user: str, content: str, section_title: str,
                            goal: str, other_summaries: list[str]) -> Evaluation | None:
    """一个 section 是不是写完了：跟 note_harness 同一套机制，见
    writer_harness/README.md——机械查重先做，结果作为 non_repetition 维度
    的辅助证据，跟其他维度一起打分，返回 continue/complete/blocked。

    调用失败返回 None（不抛出）——真实压测撞过：本地模型持续高负载下
    单次调用超过 300s 超时，异常从 SSE generator 里冒出去，客户端看到的
    是连接被硬中断，不是正常的错误事件（note_harness.py 那边先修的，
    这里是同一个模式）。"""
    facts, _ids, _took = _retrieve(user, content, section_title, [], limit=6,
                                   title=section_title, anchor_first=True)
    dup_hints = find_repeats(content)
    context = {"这个分段的主题": section_title}
    if goal:
        context["整个写作计划的总体目标"] = goal
    if other_summaries:
        context["计划里已完成的其他分段小结"] = "\n".join(f"- {s}" for s in other_summaries)
    if facts:
        context["知识库中的相关事实"] = "\n".join(f"- {f}" for f in facts)
    profile = _profile(user)
    try:
        return await evaluate(
            harness_adapter.AppLLMClient(),
            content=content,
            dimensions=harness_adapter.section_dimensions(has_profile=bool(profile)),
            context=context,
            dup_hints=dup_hints,
        )
    except Exception:
        return None


async def _run_section_edit_pass(user: str, content: str, section_title: str, goal: str,
                                 other_summaries: list[str], note_title: str, note_id: str,
                                 focus: str, result: dict):
    """分段专用的修订/清理步骤——之前 writing_plan.py 完全没有这一步，只有
    续写；真实压测数据（TRACELOG [28]）发现分段的收敛率明显低于笔记
    （20% vs 50%+），根因是 non_repetition 被打低分之后除了"接着写"没有
    别的手段，这跟 note_harness.py 改之前撞过的同一个坑——已经在重复的
    问题，靠"接着写"没道理能自己变好。这里照 note_harness._run_edit_pass
    的模式给分段也配一份，用 section_edit_user()（跟 edit_user() 共用同
    一份 EDIT_SYSTEM，只是上下文块换成分段自己的）。"""
    facts, _ids, _took = _retrieve(user, content, section_title, [], limit=6,
                                   title=section_title, anchor_first=True)
    # 机械查重是纯 difflib、不花 LLM 调用，没有理由只在"最弱项恰好叫
    # non_repetition"时才算——coherence 的多结尾问题往往也伴随重复内容，
    # 而且候选对最多 5 条、prompt 成本可忽略。一律算好传进去，让模型
    # 自己判断这些候选是不是真的重复、要不要动。
    dup_hints = find_repeats(content)
    edit_system = prompts.compose_system(prompts.EDIT_SYSTEM, store.enabled_skills_for_scope(user, "edit"))
    try:
        edit_text = await llm.complete(
            [{"role": "system", "content": edit_system},
             {"role": "user", "content": prompts.section_edit_user(
                 section_title, goal, other_summaries, content, facts, _profile(user), focus, dup_hints)}],
            max_tokens=1500, temperature=0.1)
    except Exception as exc:
        yield _sse("error", {"detail": f"分段修订调用失败，跳过这一轮修订: {exc}"})
        result["content"] = content
        result["applied"] = 0
        return
    parsed_revisions = llm.extract_json(edit_text)
    applied = 0
    # 跟 note_harness._run_edit_pass 同样的 insert 顺序保护：同一锚点上的
    # 第二条 insert 必须插在第一条插入的内容之后，否则会紧贴锚点把先插的
    # 顶到后面、顺序颠倒（真实质量采样里抓到过「### 3.」「### 4.」被写成
    # 4 在 3 前面）。两条 harness 共用 _apply_revision，这个保护也必须
    # 两边都传，只修一边等于这条路径上的 bug 还活着。
    insert_offsets: dict[str, int] = {}
    if isinstance(parsed_revisions, list):
        for item in parsed_revisions[:6]:
            if not isinstance(item, dict):
                continue
            op = str(item.get("op", "")).lower()
            if op not in ("insert", "delete", "replace"):
                continue
            anchor = str(item.get("anchor") or "")
            if not anchor or anchor not in content:
                continue
            text = str(item.get("text") or "")
            new_content = _apply_revision(
                content, op, anchor, text, insert_offset=insert_offsets.get(anchor, 0))
            if new_content == content:
                continue
            if op == "insert":
                insert_offsets[anchor] = insert_offsets.get(anchor, 0) + len(text)
            content = new_content
            applied += 1
            yield _sse("revision", {
                "section_id": None, "op": op, "anchor": anchor[:120], "text": text[:300],
                "reason": str(item.get("reason") or ""),
                "sources": [str(s) for s in (item.get("sources") or [])][:3],
            })
    if applied:
        store.update_note(user, note_id, note_title, content)
    result["content"] = content
    result["applied"] = applied


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

    plan_system = prompts.compose_system(prompts.PLAN_SYSTEM, store.enabled_skills_for_scope(user, "plan_generate"))
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

        section_rounds: dict[str, int] = {}
        section_focus: dict[str, str] = {}
        # 每个分段上一轮的完整分数——决定该不该续写要看"内在质量维度
        # 有没有没达标的"，只留最弱项的名字信息不够（见 skip_continue）。
        section_scores: dict[str, dict[str, int]] = {}
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
                    prompts.MORE_SECTIONS_SYSTEM, store.enabled_skills_for_scope(user, "more_sections"))
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

            other_summaries = [s["summary"] for s in sections if s["id"] != target["id"] and s["summary"]]
            focus = section_focus.get(target["id"], "")

            # 这一轮该续写还是该只理顺，看的是"上一轮最弱那项到底是内容
            # 不够、还是已写内容有毛病"——两类问题处理方式相反：
            #   topic_fidelity 低 = 该覆盖的内容没写 → 续写
            #   non_repetition/coherence 低 = 已写的内容自身有毛病
            #                                 （重复、多结尾、层级乱）
            #                                 → 只理顺，不再加新内容
            # 之前这里跟 note_harness.py 一样只判断
            # `focus == "non_repetition"`，那个版本在真实质量采样里跑出了
            # 清晰的震荡：清理轮修好 non_repetition 后最弱项变成别的维度，
            # 下一轮又去续写、又把它弄坏，来回拉锯到轮数上限收场。这里跟
            # note_harness.py 用同一套判断口径，不各修一半。
            _INNER_QUALITY_DIMS = ("non_repetition", "coherence")
            prev_scores = section_scores.get(target["id"], {})
            skip_continue = any(prev_scores.get(d, 2) < 2 for d in _INNER_QUALITY_DIMS)
            cleanup_applied = 0
            if skip_continue:
                cleanup_result: dict = {}
                # _run_section_edit_pass 自己会在 applied>0 时调用
                # store.update_note()，这里不用再存一次。
                async for ev in _run_section_edit_pass(
                        user, note["content"], target["title"], plan["goal"],
                        other_summaries, target["title"], note["id"], focus, cleanup_result):
                    yield ev
                new_content = cleanup_result["content"]
                cleanup_applied = cleanup_result["applied"]
                round_text = ""
                yield _sse("section-start", {
                    "section_id": target["id"], "title": target["title"], "note_id": note["id"],
                    "is_new_note": is_new_note, "facts": 0, "recall_ms": 0,
                    "sources": [], "fact_ids": [], "skipped_continue": True,
                })
            else:
                facts, ids, took = _retrieve(user, note["content"], target["title"], [], limit=6,
                                        title=target["title"], anchor_first=True)
                folder_notes = store.notes_in_folder(user, body.folder_id, exclude_id=note["id"], limit=6)
                folder_ctx = prompts.folder_context_block(folder_notes)
                section_system = prompts.compose_system(
                    prompts.MAGIC_TAP_SYSTEM, store.enabled_skills_for_scope(user, "section_write"))

                messages = [
                    {"role": "system", "content": section_system},
                    {"role": "user", "content": prompts.section_write_user(
                        target["title"], plan["goal"], other_summaries,
                        note["content"], facts, folder_ctx, _profile(user), focus=focus)},
                ]

                yield _sse("section-start", {
                    "section_id": target["id"], "title": target["title"], "note_id": note["id"],
                    "is_new_note": is_new_note, "facts": len(facts),
                    "recall_ms": round(took, 3), "sources": facts[:6], "fact_ids": ids[:6],
                })

                round_text = ""
                try:
                    async for piece in llm.stream(messages, max_tokens=900):
                        round_text += piece
                        yield _sse("delta", {"note_id": note["id"], "text": piece})
                except Exception as exc:
                    yield _sse("error", {"detail": str(exc)})
                    break

                new_content = prompts.join_round_text(note["content"], round_text)
                store.update_note(user, note["id"], target["title"], new_content)

            section_rounds[target["id"]] = section_rounds.get(target["id"], 0) + 1
            # 普通续写轮：round_text 空就是没进展。跳过续写的清理轮：看
            # 有没有真的应用修订——两次独立尝试都没改动，才算没进展，跟
            # note_harness.py 的 no_change 判断是同一个道理。
            no_progress = (not skip_continue and not round_text.strip()) or (skip_continue and not cleanup_applied)

            evaluation = None if no_progress else await _evaluate_section(
                user, new_content, target["title"], plan["goal"], other_summaries)
            forced = section_rounds[target["id"]] >= SECTION_ROUND_CAP and (
                evaluation is None or evaluation.status == "continue")
            finished = no_progress or forced or (evaluation and evaluation.status in ("complete", "blocked"))

            if evaluation:
                yield _sse("evaluate", {
                    "section_id": target["id"],
                    "scores": {name: {"level": s.level, "note": s.note} for name, s in evaluation.scores.items()},
                    "status": evaluation.status,
                    "weakest": evaluation.weakest,
                })
                scores = {name: s.level for name, s in evaluation.scores.items()}
                harness_adapter.SqliteRunHistoryStore().record(RunRecord(
                    key=note["id"], status=evaluation.status, rounds=section_rounds[target["id"]],
                    final_scores=scores, weak_dimensions=[n for n, lv in scores.items() if lv < 2]))

            if finished:
                summary = _make_summary(target["title"], new_content)
                store.update_section(plan["id"], target["id"], status="done", summary=summary)
                blocked = bool(evaluation and evaluation.status == "blocked")
                yield _sse("section-done", {
                    "section_id": target["id"], "summary": summary, "forced": forced,
                    "blocked": blocked,
                    "blocked_reason": evaluation.blocked_reason if blocked else None,
                })
                sections = store.list_sections(plan["id"])
                _sync_tracking_note(user, plan, sections)
            else:
                section_focus[target["id"]] = evaluation.weakest or "" if evaluation else ""
                if evaluation:
                    section_scores[target["id"]] = {
                        name: sc.level for name, sc in evaluation.scores.items()}
                yield _sse("round-end", {"section_id": target["id"]})

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
