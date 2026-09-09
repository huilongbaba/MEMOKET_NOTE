"""app 和 harness 之间的接缝：两个 Protocol 的落地实现。

``checks/rubric.py`` 只认识 ``LLMClient`` 和 ``RunHistoryStore`` 两个协议，
不认识这个产品的任何东西——那是它能换个领域复用的前提。这个文件就是把
那两个协议接到 ``util/llm.py`` 和 ``database/store.py`` 上。

**领域词汇不在这儿。** 八组评分维度一度也放在这个文件里，理由是「它们
也是 app 侧的东西」——但接缝和配置是两回事，维度现在都在 ``modes.py``，
跟它们所属的 Mode 放在一起。

原文（英文）：Wires the domain-agnostic scoring engine into this app: an
LLMClient adapter over app.llm, a RunHistoryStore backed by the
harness_runs sqlite table, and memoket-note's own rubric (spine/beats
vocabulary lives here, not in harness/rubric.py -- see harness/rubric.py 的 docstring
"Design notes").
"""

from __future__ import annotations

from .types import RunRecord

from ..util import llm as _llm
from ..database import store


class AppLLMClient:
    """Implements harness.types.LLMClient by forwarding to app.llm.complete()."""

    async def complete(self, messages: list[dict], **kwargs) -> str:
        return await _llm.complete(messages, **kwargs)


class SqliteRunHistoryStore:
    """Implements harness.types.RunHistoryStore over app/store.py's
    harness_runs table."""

    def record(self, run: RunRecord) -> None:
        store.record_harness_run(
            run.key, run.status, run.rounds, run.final_scores, run.weak_dimensions)

    def recent(self, key: str, limit: int = 3) -> list[RunRecord]:
        return [
            RunRecord(
                key=row["key"], status=row["status"], rounds=row["rounds"],
                final_scores=row["final_scores"], weak_dimensions=row["weak_dimensions"],
                timestamp=row["timestamp"],
            )
            for row in store.recent_harness_runs(key, limit)
        ]
