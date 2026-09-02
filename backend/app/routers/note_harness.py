"""单篇笔记内的智能续写 harness：自动修订 + 自动续写交替进行，直到内容
按打分闭环判定完整才停——跟无限续写（writing_plan.py）是同一个"harness"
精神，范围收在一篇笔记内部，不创建新笔记/文件夹。

"完不完整"不再靠续写模型自己在正文末尾主观吐一个标记，也不是单独一次
二元 beats 核对——两者都吸收进 writer_harness.evaluate() 这一次打分调用：
给一组原则（spine 贴合度/beats 覆盖/有没有重复/知识库事实是否一致/风格
贴合度），返回 continue/complete/blocked 三态，continue 时附带当前最弱
的维度，驱动下一轮修订该优先改哪。原理见 writer_harness/README.md——
coding harness 能靠执行/测试当客观 oracle，写作没有，所以要有一套显式
打分的原则代替。

跟右键的"重写/校验"不一样：那两个是用户手动选中一段文本触发的一次性
建议，这里是自动跑、自动应用修订（不等人工点接受），一轮修订一轮续写
反复进行到完成。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from writer_harness import Evaluation, RunRecord, evaluate, find_repeats, compact_context

from .. import harness_adapter, llm, prompts, store
from ..schemas import NoteHarnessRunIn
from .compose import _profile, _retrieve
from .deps import current_user

router = APIRouter(prefix="/api/note-harness", tags=["note-harness"])

# 单次跑最多这么多轮（修订+续写算一轮）——真正的停止条件是 evaluate() 判定
# complete/blocked，这个只是防失控的安全网，跟 openJiuwen Goal Mode 里
# "语义完成"和"硬限制"分开判断是同一个道理。
MAX_ROUNDS_CAP = 30

# 连续这么多轮"修订没改动任何内容 + 续写没写出新文字"，即使 evaluate()
# 还没判定完成也强制停——防止卡在同一个状态里反复打分却什么都不变。
STALL_ROUNDS_CAP = 2

# 续写 prompt 用的上下文预算：超过这个长度，更早的内容压缩成摘要，只保留
# 最近这么多字符全量——只影响续写这一步，修订/打分两步继续吃全量正文（见
# writer_harness/context.py 的取舍说明：这两步的工作就是抓跨文档的偏题/
# 重复，压缩了反而漏掉要抓的东西）。
CONTEXT_KEEP_LAST_CHARS = 6000


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _run_edit_pass(user: str, content: str, spine: str, beats: list[str],
                         note_title: str, note_id: str, focus: str, result: dict):
    """一次修订：查知识库 + 跑 EDIT_SYSTEM + 把返回的修订自动应用到 content。
    yield revision SSE 事件；跑完把最终 content 和应用了几条写进 result
    （可变容器，配合 async generator 不能直接 return 值的限制）。

    ``focus`` 是上一轮 evaluate() 给出的最弱维度（第一轮是空字符串，逐条
    原则都检查）——传给 edit_user() 让这一轮优先看这个问题。"""
    facts, _ids, _took = _retrieve(user, content, spine, beats)
    edit_system = prompts.compose_system(prompts.EDIT_SYSTEM, store.enabled_skills_for_scope(user, "edit"))
    edit_text = await llm.complete(
        [{"role": "system", "content": edit_system},
         {"role": "user", "content": prompts.edit_user(spine, beats, content, facts, _profile(user), focus)}],
        max_tokens=1500, temperature=0.1)
    parsed_revisions = llm.extract_json(edit_text)
    applied = 0
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
            new_content = _apply_revision(content, op, anchor, text)
            if new_content == content:
                continue
            content = new_content
            applied += 1
            yield _sse("revision", {
                "op": op, "anchor": anchor[:120], "text": text[:300],
                "reason": str(item.get("reason") or ""),
                # EDIT_SYSTEM 的 JSON 约定本来就要求模型自报 sources（依据的
                # 事实原文），/api/edit 那条路径一直有正确读出来，这条
                # harness 专用路径漏了——之前用户读了一次真实笔记，问起
                # "溯源"才发现：不是没有这个信号，是模型给了、这里没读。
                "sources": [str(s) for s in (item.get("sources") or [])][:3],
            })
    if applied:
        store.update_note(user, note_id, note_title, content)
    result["content"] = content
    result["applied"] = applied


async def _evaluate_round(user: str, content: str, spine: str, beats: list[str]) -> Evaluation:
    """跑一次原则打分：机械查重先做（不用 LLM），结果作为 non_repetition
    维度的辅助证据喂给 evaluate()。"""
    facts, _ids, _took = _retrieve(user, content, spine, beats)
    dup_hints = find_repeats(content)
    context = {}
    if spine:
        context["核心张力"] = spine
    if beats:
        context["结构节拍"] = "\n".join(f"- {b}" for b in beats)
    if facts:
        context["知识库事实"] = "\n".join(f"- {f}" for f in facts)
    profile = _profile(user)
    return await evaluate(
        harness_adapter.AppLLMClient(),
        content=content,
        dimensions=harness_adapter.note_dimensions(has_profile=bool(profile)),
        context=context or None,
        dup_hints=dup_hints,
    )


def _apply_revision(content: str, op: str, anchor: str, text: str) -> str:
    """前端 RevisionPanel.tsx 的 applyRevision() 用的是同一套锚点语义，这里
    是要在没有人工审核的情况下自动应用，所以后端自己实现一份——不能指望
    前端那份，那是给用户点"接受"用的，只在浏览器里跑。"""
    i = content.find(anchor)
    if i < 0:
        return content  # 锚点在当前正文里找不到了（可能已经被上一条修订动过），跳过这条
    end = i + len(anchor)
    if op == "insert":
        return content[:end] + text + content[end:]
    if op == "insert_before":
        return content[:i] + text + content[i:]
    if op == "delete":
        return content[:i] + content[end:]
    return content[:i] + text + content[end:]  # replace


@router.post("/run")
async def run(body: NoteHarnessRunIn, request: Request, user: str = Depends(current_user)):
    """SSE 流式跑。事件：
        skeleton    —— 自动生成的 spine/beats（调用方没给的话）
        round-start  —— 新一轮开始，带这一轮续写检索到的事实数
        revision    —— 一条修订被自动应用（op/anchor/text/reason）
        delta       —— 续写正文增量
        evaluate    —— 这一轮打分结果（scores/status/weakest）
        round-end   —— 这一轮结束
        done        —— 真正停了（reason: complete | blocked | max_rounds | stalled，
                       blocked 时附带 blocked_reason）
        error
    """
    note = store.get_note(user, body.note_id)
    if not note:
        raise HTTPException(404, "note not found")

    async def gen():
        content = body.content
        spine, beats = body.spine, body.beats

        if not spine and not beats:
            skeleton_system = prompts.compose_system(
                prompts.SKELETON_SYSTEM, store.enabled_skills_for_scope(user, "skeleton"))
            text = await llm.complete(
                [{"role": "system", "content": skeleton_system},
                 {"role": "user", "content": prompts.skeleton_user(note["title"], content, _profile(user))}],
                max_tokens=800, temperature=0.4)
            parsed = llm.extract_json(text)
            if isinstance(parsed, dict):
                spine = str(parsed.get("spine") or "").strip()
                raw_beats = parsed.get("beats")
                if isinstance(raw_beats, list):
                    beats = [str(b).strip() for b in raw_beats if str(b).strip()][:6]
            yield _sse("skeleton", {"spine": spine, "beats": beats})

        max_rounds = max(1, min(body.max_rounds, MAX_ROUNDS_CAP))
        stall_rounds = 0
        focus = ""

        def _finish(reason: str, round_idx: int, evaluation: Evaluation | None):
            status = evaluation.status if evaluation else reason
            scores = {name: s.level for name, s in evaluation.scores.items()} if evaluation else {}
            weak = [name for name, level in scores.items() if level < 2]
            harness_adapter.SqliteRunHistoryStore().record(RunRecord(
                key=body.note_id, status=status, rounds=round_idx,
                final_scores=scores, weak_dimensions=weak))

        for round_idx in range(1, max_rounds + 1):
            if await request.is_disconnected():
                break

            # --- 自动修订：直接应用，不等人工接受 ---
            edit_result: dict = {}
            async for ev in _run_edit_pass(user, content, spine, beats, note["title"], body.note_id, focus, edit_result):
                yield ev
            content = edit_result["content"]
            revisions_applied = edit_result["applied"]

            # --- 自动续写 ---
            # 上一轮评分如果说最弱的是 non_repetition，这一轮跳过续写：真实
            # 测试跑出来的结果——terrence 一篇真实笔记连续跑 6 轮，
            # non_repetition 从没改善过，反而从 1 掉到 0。续写每轮都在加新
            # 内容，而且完全不知道"重复"是当前最该注意的问题（只有修订
            # 那一步拿到了 focus），新内容持续在给"已经在重复"的问题上再
            # 添一层，修订跟不上续写产出的速度。已经在重复的问题，靠"接着
            # 写"没有道理能自己变好——这一轮改成再跑一次聚焦修订（两次独立
            # 机会清理同一个问题），不叠加新内容。
            skip_continue = focus == "non_repetition"
            if skip_continue:
                cleanup_result: dict = {}
                async for ev in _run_edit_pass(user, content, spine, beats, note["title"], body.note_id, focus, cleanup_result):
                    yield ev
                content = cleanup_result["content"]
                revisions_applied += cleanup_result["applied"]
                yield _sse("round-start", {
                    "round": round_idx, "max_rounds": max_rounds, "revisions_applied": revisions_applied,
                    "facts": 0, "sources": [], "fact_ids": [], "skipped_continue": True,
                })
                round_text = ""
            else:
                # TRACELOG [14]：这里本来接了 _plan_retrieve()（用 KITE 的
                # compile_plan() 编译一次查询计划，指望比死板拼正文尾部更懂
                # 语义）——真实对比测试发现在 terrence 这个 codebook 上反而更差：
                # 两次真实查询，plan_recall() 返回的全是不相关事实（其中一次
                # 甚至扯到了完全不同领域的"港中择校"内容），recall() 老办法
                # 两次都准确命中；而且慢 15-30 倍（10+ 秒 vs 亚毫秒）。既慢又
                # 不准，退回原来的 _retrieve()。
                facts2, ids2, took2 = _retrieve(user, content, spine, beats, limit=6)
                magic_system = prompts.compose_system(
                    prompts.MAGIC_TAP_SYSTEM, store.enabled_skills_for_scope(user, "magic_tap"))
                continue_content = compact_context(content, keep_last_chars=CONTEXT_KEEP_LAST_CHARS)
                messages = [
                    {"role": "system", "content": magic_system},
                    {"role": "user", "content": prompts.note_harness_continue_user(
                        spine, beats, continue_content, facts2, _profile(user))},
                ]
                yield _sse("round-start", {
                    "round": round_idx, "max_rounds": max_rounds, "revisions_applied": revisions_applied,
                    "facts": len(facts2), "sources": facts2[:6], "fact_ids": ids2[:6],
                })

                round_text = ""
                try:
                    async for piece in llm.stream(messages, max_tokens=900):
                        round_text += piece
                        yield _sse("delta", {"text": piece})
                except Exception as exc:
                    yield _sse("error", {"detail": str(exc)})
                    break

            if round_text:
                content = prompts.join_round_text(content, round_text)
                store.update_note(user, body.note_id, note["title"], content)
            yield _sse("round-end", {"round": round_idx})

            no_change = revisions_applied == 0 and not round_text.strip()
            stall_rounds = stall_rounds + 1 if no_change else 0

            evaluation = await _evaluate_round(user, content, spine, beats)
            yield _sse("evaluate", {
                "scores": {name: {"level": s.level, "note": s.note} for name, s in evaluation.scores.items()},
                "status": evaluation.status,
                "weakest": evaluation.weakest,
            })

            if evaluation.status == "complete":
                _finish("complete", round_idx, evaluation)
                yield _sse("done", {"reason": "complete"})
                return
            if evaluation.status == "blocked":
                _finish("blocked", round_idx, evaluation)
                yield _sse("done", {"reason": "blocked", "blocked_reason": evaluation.blocked_reason})
                return
            if stall_rounds >= STALL_ROUNDS_CAP:
                _finish("stalled", round_idx, evaluation)
                yield _sse("done", {"reason": "stalled"})
                return
            focus = evaluation.weakest or ""

        _finish("max_rounds", max_rounds, None)
        yield _sse("done", {"reason": "max_rounds"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
