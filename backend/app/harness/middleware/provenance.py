"""Show the user what the tools actually returned.

Grounding cannot be the model's own say-so. Every harness already had some
version of this -- each with its own event shape -- because the provenance
panel is what lets a user check a number instead of trusting it. One
implementation, one payload shape, every harness.
"""

from __future__ import annotations

from typing import AsyncIterator

from ..events import CUSTOM_ROUND, Event
from ..state import State


class Provenance:
    """Report what this round gathered: every tool call, then a summary.

    Named for what it is rather than for the object it reads. It was ``Trace``
    once, which collided with ``State.trace`` -- the tool trace itself -- and
    made "is this the middleware or the field" a question you had to answer by
    reading. Grounding that the user can check is the capability; ToolTrace is
    just where the data comes from.

    The summary is what the round counter and the sources panel read. It has
    to come *after* prepare rather than at the round's start, because before
    prepare there is nothing to report -- and a round header reading "0 facts"
    that never updates is worse than none.
    """

    name = "provenance"
    hooks = ("after_prepare",)
    after: tuple[str, ...] = ("facts",)   # Facts is what decides a call counted

    async def after_prepare(self, st: State) -> AsyncIterator[Event]:
        if st.trace is not None and st.trace.used:
            already = st.bag.setdefault("traced", 0)
            for name, args, result in st.trace.calls[already:]:
                yield Event.tool_result(name, args, result or "")
            st.bag["traced"] = len(st.trace.calls)

        yield Event.custom(CUSTOM_ROUND, {
            "round": st.round,
            "max_rounds": st.mode.max_rounds,
            "facts": len(st.facts_new),
            "sources": st.facts_new[:6],
            "revisions_applied": st.bag.get("revisions_applied", 0),
            "skipped_continue": bool(st.bag.get("cleanup_only")),
            # 「这一轮没查到」和「这个库压根是空的」在界面上原来长得一模一样：
            # 都只是 `facts: 0`，一个字的解释都没有。新用户点了续写，看到的是
            # 「第 1 轮：修订 0 处，续写中…」，完全不知道它手上没有任何材料
            # （第 676 轮）。
            "kb_empty": _kb_empty(st),
        })


def _kb_empty(st) -> bool:
    """这个用户的知识库一条事实都没有。读不出来就说「不是空的」——
    宁可少说一句，也不要对着一个读失败的索引告诉用户「你没有材料」。"""
    try:
        from ..tools.memory_tools import kb_is_empty
        return kb_is_empty(st.ctx.user)
    except Exception:      # noqa: BLE001
        return False
