"""Knowledge-base views that are not KITE's job.

KITE serves facts, topics and entities. What this router adds is the coarse
layer built on top of them -- the clusters writing retrieves at, and the
coverage figures that say whether the codebook is up to date.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from ..database import store
from ..database.kb import extract_check, extract_judge, pages, reextract, virtual_tree
from ..database.kb.recall import cached
from ..database.kite.kite_memory import UserMemory
from .schemas import IngestOut, TreeRow
from .deps import current_user

router = APIRouter(prefix="/api/kb", tags=["kb"])


@router.get("/tree", response_model=list[TreeRow])
def kb_tree(user: str = Depends(current_user)):
    """知识库的虚拟子树——分类层。跟 /api/tree 同一种行，前端同一个控件画。
    见 database/kb/virtual_tree.py 的模块注释。"""
    return virtual_tree.build(UserMemory(user))


@router.get("/tree/children", response_model=list[TreeRow])
def kb_tree_children(node: str, user: str = Depends(current_user)):
    """展开一个分类节点时才取的事实层。"""
    return virtual_tree.children(UserMemory(user), node)


# ---------------------------------------------------------------- 各节点的页面
# 打开树上一个知识库节点，里面是什么（docs/kb-experience-plan.md）。

@router.get("/dashboard")
def kb_dashboard(user: str = Depends(current_user)) -> dict:
    d = pages.dashboard(UserMemory(user))
    d["conflicts_open"] = store.count_open_conflicts(user)
    return d


@router.get("/topic/{code}")
def kb_topic(code: str, limit: int = 50, offset: int = 0, user: str = Depends(current_user)) -> dict:
    page = pages.topic_page(UserMemory(user), code, limit=max(1, min(limit, 200)), offset=max(0, offset))
    if page is None:
        raise HTTPException(404, f"没有这个主题：{code}")
    return page


@router.get("/entity/{code}")
def kb_entity(code: str, limit: int = 50, offset: int = 0, user: str = Depends(current_user)) -> dict:
    page = pages.entity_page(UserMemory(user), code, limit=max(1, min(limit, 200)), offset=max(0, offset))
    if page is None:
        raise HTTPException(404, f"没有这个实体：{code}")
    return page


@router.get("/timeline")
def kb_timeline(user: str = Depends(current_user)) -> list[dict]:
    return pages.timeline(UserMemory(user))


@router.get("/timeline/{date}")
def kb_day(date: str, user: str = Depends(current_user)) -> list[dict]:
    return pages.day_facts(UserMemory(user), date)


@router.get("/unit/{unit_id}")
def kb_unit(unit_id: str, limit: int = 50, offset: int = 0, user: str = Depends(current_user)) -> dict:
    page = pages.unit_page(UserMemory(user), unit_id, limit=max(1, min(limit, 200)), offset=max(0, offset))
    if page is None:
        raise HTTPException(404, f"没有这场会议：{unit_id}")
    return page


@router.get("/clusters")
def list_clusters(user: str = Depends(current_user), limit: int = 200) -> dict:
    """The coarse topic layer, biggest first.

    The graph view uses this as its default level: 196 topics is not a
    picture, and the measured cost of that was that nobody could see the
    shape of their own knowledge base. Clicking a cluster drills into the
    topics it holds, which are still exactly the topics KITE knows about --
    this layer is a view, not a second copy of the data.
    """
    memory = UserMemory(user)
    clusters = cached(memory)[:max(1, min(int(limit or 200), 500))]
    return {
        "clusters": [
            {"key": c.key, "label": c.label, "topics": list(c.topics),
             "facts": c.facts, "merged": c.merged}
            for c in clusters
        ],
        "topics": sum(len(c.topics) for c in clusters),
    }


@router.get("/coverage")
def coverage(user: str = Depends(current_user)) -> dict:
    """How much of the codebook exists, and how fragmented it is.

    Both numbers are here because they were confused for each other once:
    "the writing library only covers 8% of the material" and "its topics are
    fragmented" were treated as one problem, and the first turned out to have
    been fixed months earlier while the second had not moved.
    """
    memory = UserMemory(user)
    store, _vocab = memory._index()
    sizes = sorted(len(v) for v in store.by_topic.values())
    clusters = cached(memory)
    csizes = sorted(c.facts for c in clusters)
    return {
        "facts": len(store.facts),
        "units": len(store.units),
        "topics": len(sizes),
        "topic_median": _median(sizes),
        "topic_small_share": _share_small(sizes),
        "clusters": len(clusters),
        "cluster_median": _median(csizes),
        "cluster_small_share": _share_small(csizes),
    }


def _median(values: list[int]) -> float:
    if not values:
        return 0.0
    mid = len(values) // 2
    return float(values[mid] if len(values) % 2 else
                 (values[mid - 1] + values[mid]) / 2)


def _share_small(values: list[int], floor: int = 10) -> float:
    """The share at or below ``floor`` facts -- the fragmentation measure the
    findings document uses, kept identical so the numbers stay comparable."""
    if not values:
        return 0.0
    return round(sum(1 for v in values if v <= floor) / len(values), 3)


@router.get("/quality")
def quality(user: str = Depends(current_user), limit: int = 0) -> dict:
    """Deterministic quality of what extraction produced.

    One number, because one is what the data supports: the share of facts
    containing a figure that the conversation itself does not contain. The
    other two criteria the design proposed -- duplicate facts and facts
    holding three separate things -- were measured at 1 in 26258 and 0.2%,
    so there is nothing there to check.

    Reference points from the real codebooks: the source library sits at
    **0.3%**, the writing one at **9%**. That gap is the price of extracting a
    whole meeting at once and merging what it says -- consolidation infers,
    and inference sometimes supplies a figure nobody said. It is reported
    rather than blocked, because a number the model derived correctly is
    worth having.

    ``shape`` is the second half: facts too short to carry anything, ASR
    stutters, bare questions, lone speaker labels. That is the measure the
    whole re-extraction was justified by -- 16% of the source library against
    1.2% of the writing one -- and it still has something to say, because
    9.5% of writing facts carry a "Speaker A/B/C" label the extraction rules
    forbid outright.
    """
    memory = UserMemory(user)
    store, _vocab = memory._index()
    facts = list(store.facts.values())
    if limit > 0:
        facts = facts[:limit]
    return {"numbers": extract_check.rate(facts, _source_text(store)),
            "shape": extract_check.shapes(facts)}


def _source_text(store) -> dict[str, str]:
    """Conversation text per unit, which is what a fact is checked against."""
    out: dict[str, list[str]] = {}
    for line in store.lines.values():
        out.setdefault(line.unit, []).append(line.text or "")
    return {unit: "".join(parts) for unit, parts in out.items()}


@router.post("/quality/judged")
async def judged_quality(user: str = Depends(current_user), limit: int = 5) -> dict:
    """What a rule cannot decide: does a fact read on its own, is it filed right.

    Costs model calls, so it is a POST and it samples rather than sweeping --
    6-9 seconds per meeting, which is a fraction of what extracting that
    meeting cost but is still not free.

    Read the aggregate, not the individual scores: this exists to find defects
    in the extraction rules, and a defect in the rules shows up as the same
    complaint on every meeting. That is how the "relative time and bare
    pronouns" rule got written -- five meetings, five identical diagnoses.
    """
    return await extract_judge.judge_sample(user, limit=limit)


# ------------------------------------------------------- 摄入续跑（写作库）


@router.get("/rebuild/pending")
def rebuild_pending(user: str = Depends(current_user)) -> dict:
    """哪些会议还没进写作库。"""
    ids = reextract.pending(user)
    return {"pending": len(ids), "meetings": ids[:50],
            "source": reextract.source_user(user),
            "target": reextract.writing_user(user)}


@router.post("/rebuild", response_model=IngestOut)
def rebuild(bg: BackgroundTasks, limit: int = 0,
            user: str = Depends(current_user)) -> IngestOut:
    """Catch the writing codebook up with the source one.

    ``limit`` caps how many meetings this run takes -- the original script was
    deliberately incremental so a batch could be inspected before going
    further, and that is still the right default for a first run on a large
    corpus. ``0`` means everything outstanding.

    Safe to call at any time and safe to call twice: a meeting already in the
    writing codebook is skipped before the model is reached, so a second call
    costs a directory scan.
    """
    ids = reextract.pending(user)
    if limit > 0:
        ids = ids[:limit]
    if not ids:
        return IngestOut(job_id="", status="done", facts=0,
                         detail="写作库已经是最新的")

    job_id, items = store.create_batch_job(
        user, [{"filename": mid, "kind": "meeting"} for mid in ids])
    bg.add_task(_rebuild_job, job_id, user, ids, [i["id"] for i in items])
    return IngestOut(job_id=job_id, status="queued",
                     detail=f"{len(ids)} 场会议要补")


def _rebuild_job(job_id: str, user: str, ids: list[str],
                 item_ids: list[str]) -> None:
    """One meeting per item, so a long catch-up is watchable and cancellable.

    Extraction is minutes per meeting. A job that reports only at the end is
    indistinguishable from a hung one, and a cancel that only takes effect
    between jobs cannot stop a run of two hundred.
    """
    store.set_job(job_id, "running")
    meetings = {m.id: m for m in reextract.meetings(user, ids)}
    for mid, item_id in zip(ids, item_ids):
        if store.is_cancel_requested(job_id):
            store.set_item(item_id, "cancelled")
            store.update_job_from_items(job_id)
            continue
        meeting = meetings.get(mid)
        if meeting is None:
            store.set_item(item_id, "done", facts=0, detail="源库里没有内容")
            store.update_job_from_items(job_id)
            continue
        store.set_item(item_id, "remembering")
        store.update_job_from_items(job_id)
        try:
            facts = reextract.extract_one(user, meeting)
            # Report the unsupported-number rate for what this meeting just
            # produced. A batch that quietly got worse is otherwise invisible
            # until something downstream cites a figure nobody said.
            store.set_item(item_id, "done", facts=facts,
                           detail=f"{len(meeting.messages)} 段 / {meeting.chars:,} 字"
                                  f"{_quality_note(user, meeting.id)}")
        except Exception as exc:                       # noqa: BLE001
            # One meeting failing must not end the catch-up: the next call
            # picks it up again, because pending() is computed from what
            # actually landed rather than from what was attempted.
            store.set_item(item_id, "failed", detail=f"{type(exc).__name__}: {exc}")
        store.update_job_from_items(job_id)


def _quality_note(user: str, meeting_id: str) -> str:
    """``· 数字存疑 2/9`` for one meeting, or nothing if it can't be told."""
    try:
        memory = UserMemory(reextract.writing_user(user))
        memory.invalidate()
        store, _vocab = memory._index()
        facts = [f for f in store.facts.values()
                 if getattr(f, "unit", "") == meeting_id]
        if not facts:
            return ""
        result = extract_check.rate(facts, _source_text(store))
        if not result["checked"]:
            return ""
        return f" · 数字存疑 {result['flagged']}/{result['checked']}"
    except Exception:                                  # noqa: BLE001
        # A quality note is a nicety. It must never be able to turn a
        # successful extraction into a failed item.
        return ""


# ---------------------------------------------------------------- 事实增删改
#
# 笔记贡献的事实用户要能改：抽取器抽错了、想补一条没抽出来的。改的是 codebook.xml
# 里的那条（锁内改、校验能读回来、原子替换），改完 mtime 变了索引自动失效。

class FactTextIn(BaseModel):
    text: str = ""
    # 「新的取代旧的」：把这条标成被 superseded_by 那条取代（传空串 = 取消）。None = 不动
    superseded_by: str | None = None


class FactAddIn(BaseModel):
    note_id: str
    text: str
    when: str = ""


@router.patch("/fact/{fact_id}")
def kb_fact_edit(fact_id: str, body: FactTextIn, user: str = Depends(current_user)) -> dict:
    mem = UserMemory(user)
    text = body.text.strip()
    if body.superseded_by is None and not text:
        raise HTTPException(400, "text is empty")
    if text and not mem.set_fact_text(fact_id, text):
        raise HTTPException(404, f"没有这条事实：{fact_id}")
    if body.superseded_by is not None:
        if body.superseded_by and mem.fact_by_id(body.superseded_by) is None:
            raise HTTPException(404, f"没有这条事实：{body.superseded_by}")
        if not mem.set_fact_attr(fact_id, "superseded_by", body.superseded_by):
            raise HTTPException(404, f"没有这条事实：{fact_id}")
    out = mem.fact_by_id(fact_id) or {"id": fact_id, "text": text}
    out["superseded_by"] = mem.fact_attrs("superseded_by").get(fact_id, "")
    return out


@router.delete("/fact/{fact_id}")
def kb_fact_delete(fact_id: str, user: str = Depends(current_user)) -> dict:
    removed = UserMemory(user).delete_facts({fact_id})
    if not removed:
        raise HTTPException(404, f"没有这条事实：{fact_id}")
    return {"ok": True, "removed": removed}


@router.post("/fact")
def kb_fact_add(body: FactAddIn, user: str = Depends(current_user)) -> dict:
    """给一篇笔记手工补一条事实。落在 `note-<id>-manual` 这个 session 里，同步时不会被删。"""
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "text is empty")
    n = store.get_note(user, body.note_id)
    if not n:
        raise HTTPException(404, "note not found")
    from datetime import date as _date
    when = body.when or _date.today().isoformat()
    mem = UserMemory(user)
    fact = mem.add_manual_fact(f"note-{body.note_id}-manual", text, date=when,
                               title=n.get("title") or "未命名")
    if not n.get("ingested_at"):
        store.mark_ingested(user, body.note_id)
    return fact


# ---------------------------------------------------------------- 合并 / 冲突收件箱

class FactMergeIn(BaseModel):
    keep: str
    drop: str
    text: str = ""       # 合成后的正文（空 = 保留 keep 的原文）


@router.post("/fact/merge")
def kb_fact_merge(body: FactMergeIn, user: str = Depends(current_user)) -> dict:
    """「合成一条」：drop 标成被 keep 取代（merged=1），keep 的正文可以顺手改。合并结果记住了，
    页面默认不再显示 drop，关系检测也不再提这一对（docs/agent-native-editor.md §3.3.1）。"""
    if body.keep == body.drop:
        raise HTTPException(400, "同一条没法合并")
    mem = UserMemory(user)
    if mem.fact_by_id(body.keep) is None or mem.fact_by_id(body.drop) is None:
        raise HTTPException(404, "有一条不存在")
    text = body.text.strip()
    if text:
        mem.set_fact_text(body.keep, text)
    mem.set_fact_attr(body.drop, "superseded_by", body.keep)
    mem.set_fact_attr(body.drop, "merged", "1")
    store.drop_conflicts_for_facts(user, {body.drop})
    out = mem.fact_by_id(body.keep) or {"id": body.keep}
    out["merged_from"] = body.drop
    return out


@router.get("/conflicts")
def kb_conflicts(user: str = Depends(current_user), status: str = "open") -> dict:
    """待处理的冲突：摄入时检出的「新事实 vs 旧事实」，带两条的正文 / 日期 / 来源笔记。"""
    mem = UserMemory(user)
    out = []
    for c in store.list_conflicts(user, status=status):
        new, old = mem.fact_by_id(c["new_fact_id"]), mem.fact_by_id(c["old_fact_id"])
        if new is None or old is None:
            store.drop_conflicts_for_facts(user, {c["new_fact_id"], c["old_fact_id"]})
            continue
        out.append({**c, "new": _brief(new), "old": _brief(old)})
    return {"conflicts": out, "open": store.count_open_conflicts(user)}


def _brief(f: dict) -> dict:
    return {"id": f["id"], "text": f.get("text", ""), "when": f.get("when") or f.get("date", ""),
            "note_id": pages.note_id_of_unit(f.get("unit") or ""), "unit": f.get("unit") or ""}


class ConflictResolveIn(BaseModel):
    action: str        # new_wins | old_wins | keep_both


@router.post("/conflicts/{conflict_id}/resolve")
def kb_conflict_resolve(conflict_id: int, body: ConflictResolveIn, user: str = Depends(current_user)) -> dict:
    if body.action not in ("new_wins", "old_wins", "keep_both"):
        raise HTTPException(400, "action 只能是 new_wins / old_wins / keep_both")
    row = next((c for c in store.list_conflicts(user, status="open", limit=10000) if c["id"] == conflict_id), None)
    if row is None:
        raise HTTPException(404, "没有这条待办")
    mem = UserMemory(user)
    if body.action == "new_wins":
        mem.set_fact_attr(row["old_fact_id"], "superseded_by", row["new_fact_id"])
    elif body.action == "old_wins":
        mem.set_fact_attr(row["new_fact_id"], "superseded_by", row["old_fact_id"])
    return store.resolve_conflict(user, conflict_id, body.action) or {}
