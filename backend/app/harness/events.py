"""SSE event contract, following the AG-UI protocol.

We don't invent event names. AG-UI is an existing open protocol with a fixed
set of lifecycle / text / tool events plus a ``CUSTOM`` escape hatch for
domain-specific ones. Using it means the frontend can eventually plug into
off-the-shelf UI libraries, and -- more immediately -- that adding a fourth
harness needs zero new event names.

三条 router 一度各发一套自定义事件名，一共 23 个，映射到这 9 个标准事件
加一个 ``CUSTOM``。迁移期间有过一层把标准名翻回旧名的函数，好让前端不用
跟着一条条改；三条都切完之后前端换成标准名、那个函数删掉——**过渡层从
写下第一天就该标好死期**。

**Pairing matters.** ``TEXT_MESSAGE_START`` / ``CONTENT`` / ``END`` must
nest properly -- the protocol has a state machine that rejects two STARTs in
a row. One round emits exactly one message.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """AG-UI standard event names. Domain-specific things go through CUSTOM."""

    RUN_STARTED = "RUN_STARTED"
    RUN_FINISHED = "RUN_FINISHED"
    RUN_ERROR = "RUN_ERROR"

    STEP_STARTED = "STEP_STARTED"          # one round, or one section
    STEP_FINISHED = "STEP_FINISHED"

    TEXT_MESSAGE_START = "TEXT_MESSAGE_START"
    TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"
    TEXT_MESSAGE_END = "TEXT_MESSAGE_END"

    TOOL_CALL_RESULT = "TOOL_CALL_RESULT"
    ACTIVITY_SNAPSHOT = "ACTIVITY_SNAPSHOT"   # "looking things up...", "drawing..."

    CUSTOM = "CUSTOM"                          # {name, value}


# Domain events ride on CUSTOM's ``name`` field rather than becoming
# top-level types. The frontend then needs one branch for CUSTOM instead of
# one branch per domain concept, and adding a harness costs it nothing.
CUSTOM_EVALUATE = "evaluate"
CUSTOM_REVISION = "revision"
CUSTOM_DROPPED = "dropped"          # a revision the guards rejected
CUSTOM_CHECK_HIT = "check_hit"      # a deterministic Check fired
CUSTOM_POLICY = "policy"            # runtime policy / replan / plan extended
CUSTOM_WARNING = "warning"          # one middleware failed, run continues
CUSTOM_SKELETON = "skeleton"
CUSTOM_PHASE_DELTA = "phase_delta"   # live output from a sub-step
CUSTOM_ROUND = "round_summary"       # what this round gathered, before writing
CUSTOM_REPLAN = "replan"             # the skeleton changed mid-run


@dataclass(frozen=True)
class Event:
    """One SSE event. ``type`` is an AG-UI name; ``data`` is its payload."""

    type: EventType
    data: dict[str, Any] = field(default_factory=dict)

    # -- constructors -------------------------------------------------
    # The loop and middleware use these instead of hand-building dicts, so
    # payload shapes stay consistent and the frontend can generate types
    # from one place.

    @staticmethod
    def run_started(mode_key: str, label: str) -> "Event":
        return Event(EventType.RUN_STARTED, {"mode": mode_key, "label": label})

    @staticmethod
    def run_finished(content: str, reason: str, blocked_reason: str = "",
                     run_id: str = "") -> "Event":
        data = {"content": content, "reason": reason}
        if run_id:
            # A paused run. The client sends this back to /resume together
            # with what the user kept.
            data["run_id"] = run_id
        if blocked_reason:
            # "blocked" on its own tells the user nothing. The scorer wrote a
            # sentence about what the structural conflict is; carry it.
            data["blocked_reason"] = blocked_reason
        return Event(EventType.RUN_FINISHED, data)

    @staticmethod
    def run_error(message: str) -> "Event":
        return Event(EventType.RUN_ERROR, {"message": message[:500]})

    @staticmethod
    def step_started(step: int, label: str = "") -> "Event":
        return Event(EventType.STEP_STARTED, {"step": step, "label": label})

    @staticmethod
    def step_finished(step: int) -> "Event":
        return Event(EventType.STEP_FINISHED, {"step": step})

    @staticmethod
    def text_start(message_id: str) -> "Event":
        return Event(EventType.TEXT_MESSAGE_START, {"messageId": message_id})

    @staticmethod
    def text_content(message_id: str, delta: str) -> "Event":
        return Event(EventType.TEXT_MESSAGE_CONTENT,
                     {"messageId": message_id, "delta": delta})

    @staticmethod
    def text_end(message_id: str) -> "Event":
        return Event(EventType.TEXT_MESSAGE_END, {"messageId": message_id})

    @staticmethod
    def tool_result(name: str, args: dict, result: str) -> "Event":
        return Event(EventType.TOOL_CALL_RESULT,
                     {"toolName": name, "args": args, "content": result[:400]})

    @staticmethod
    def activity(label: str) -> "Event":
        return Event(EventType.ACTIVITY_SNAPSHOT, {"content": label})

    @staticmethod
    def custom(name: str, value: dict) -> "Event":
        return Event(EventType.CUSTOM, {"name": name, "value": value})


def sse(event: str, data: dict) -> str:
    """序列化一帧 SSE。

    住在这儿是因为它是事件契约的线上格式——三条 router 都要用，而它们之间
    不该互相 import（这个函数就是因为那条规则从 note_harness 搬出来的）。
    """
    import json

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def to_sse(event: Event) -> str:
    """把一个 ``Event`` 序列化成一帧 SSE。

    事件名直接用 AG-UI 的标准名字上线。这里曾经有一层把它们翻回旧自定义名字的翻译函数，因为三条 router 是逐条迁移的、期间前端要同时
    认两套。三条都切完之后前端换成标准名、这个函数换回来，是一个 commit
    的事——**过渡层从写下第一天就标好了死期，到期就删**。
    """
    return sse(event.type.value, event.data)
