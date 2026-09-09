"""The judgement extraction can't make with a rule.

``extract_check`` covers what code decides: does a number in the fact appear
in the conversation. What it cannot decide is whether a fact reads on its own
months later, or whether it was filed under the right subject -- and those are
the two things that decide whether the writing side can use it at all.

**This is the same mechanism as the writing harness, with different
dimensions.** ``writer_harness.evaluate`` was built as a package precisely so
that swapping the dimensions swaps the domain; extraction is the second
domain, and it needed no new machinery.

**The cost, measured, is not what the design assumed.** The plan said model
judgement would double the price of ingestion, on the assumption of judging
every chunk. Judging a *meeting's facts* instead costs 6-9s against 2-6k
characters of extracted text -- the whole 193-meeting library is about 25
minutes -- because it reads the facts, not the 30-57k characters of
transcript that extraction reads. It is a fraction of extraction, not a
doubling.

**And what it found was a prompt bug, not per-item noise.** Five meetings,
five ``self_contained = 1``, every one naming the same defect: relative time
and bare pronouns ("今年开始", "当前", "该项目", "后来"). A per-meeting retry
would have fixed none of it. The extraction rules now say so explicitly --
which is the point of judging a batch rather than each item: a defect that
shows up everywhere is a defect in the instructions.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass

from writer_harness import Dimension, Evaluation, evaluate

from .. import harness_adapter
from ..kite_memory import UserMemory

# How much of the original conversation the judge sees. It has to see some --
# "is this self-contained" can be answered from the fact alone, but "is this
# the right topic" cannot -- and a whole transcript would cost more than the
# extraction it is checking.
SOURCE_CHARS = 6000

DIMENSIONS = (
    Dimension(
        "self_contained",
        "达标：每条事实脱离上下文单独读也成立——人物、时间、对象都写清楚了，"
        "时间是具体日期或月份而不是「今年」「后来」「目前」，对象是具体名字"
        "而不是「该项目」「这个方案」。\n"
        "不足：出现依赖上下文才读得懂的指代或相对时间。"),
    Dimension(
        "topic_fit",
        "达标：每条事实挂的主题是这批已知主题里最贴切的那个。\n"
        "不足：挂到了明显不相关的主题上（比如把读 MBA 挂到「低龄留学」），"
        "或者一条事实一个主题都没挂。"),
)


@dataclass(frozen=True)
class MeetingJudgement:
    meeting: str
    facts: int
    evaluation: Evaluation | None


async def judge_meeting(user: str, meeting_id: str) -> MeetingJudgement:
    """Judge one meeting's extraction. ``evaluation`` is None if it failed.

    Failure is not an error here: this runs after a successful extraction,
    and losing the judgement must not lose the facts.
    """
    store, _vocab = UserMemory(user)._index()
    facts = [f for f in store.facts.values() if getattr(f, "unit", "") == meeting_id]
    if not facts:
        return MeetingJudgement(meeting_id, 0, None)

    body = "\n".join(f"- [{','.join(f.topics)}] {f.text}" for f in facts)
    source = "".join(line.text or "" for line in store.lines.values()
                     if line.unit == meeting_id)
    try:
        evaluation = await evaluate(
            harness_adapter.AppLLMClient(), content=body,
            dimensions=list(DIMENSIONS),
            context={"原始对话": source[:SOURCE_CHARS]})
    except Exception:                                  # noqa: BLE001
        return MeetingJudgement(meeting_id, len(facts), None)
    return MeetingJudgement(meeting_id, len(facts), evaluation)


async def judge_sample(user: str, limit: int = 5) -> dict:
    """Judge the biggest few extractions and aggregate.

    Biggest first because a meeting that produced three facts says little
    about the prompt either way -- what is being measured is the extraction
    rules, and they show themselves on the meetings that had material.
    """
    store, _vocab = UserMemory(user)._index()
    per_unit: dict[str, int] = collections.Counter(
        getattr(f, "unit", "") for f in store.facts.values())
    meetings = [m for m, _n in per_unit.most_common(max(1, min(limit, 50))) if m]

    results = [await judge_meeting(user, m) for m in meetings]
    scored = [r for r in results if r.evaluation]
    per_dim: dict[str, list[int]] = collections.defaultdict(list)
    for r in scored:
        for name, score in r.evaluation.scores.items():
            per_dim[name].append(score.level)

    return {
        "meetings": len(results),
        "judged": len(scored),
        "dimensions": {
            name: {"mean": round(sum(v) / len(v), 2),
                   "below_bar": sum(1 for x in v if x < 2)}
            for name, v in per_dim.items()
        },
        "details": [
            {"meeting": r.meeting, "facts": r.facts,
             "scores": {n: {"level": s.level, "note": s.note[:300]}
                        for n, s in r.evaluation.scores.items()}}
            for r in scored
        ],
    }
