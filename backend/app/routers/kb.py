"""Knowledge-base views that are not KITE's job.

KITE serves facts, topics and entities. What this router adds is the coarse
layer built on top of them -- the clusters writing retrieves at, and the
coverage figures that say whether the codebook is up to date.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends

from ..database import store
from ..database.kb import extract_check, extract_judge, reextract
from ..database.kb.recall import cached
from ..database.kite.kite_memory import UserMemory
from .schemas import IngestOut
from .deps import current_user

router = APIRouter(prefix="/api/kb", tags=["kb"])


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
