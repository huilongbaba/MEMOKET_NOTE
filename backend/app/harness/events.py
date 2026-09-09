"""SSE event contract, following the AG-UI protocol.

We don't invent event names. AG-UI is an existing open protocol with a fixed
set of lifecycle / text / tool events plus a ``CUSTOM`` escape hatch for
domain-specific ones. Using it means the frontend can eventually plug into
off-the-shelf UI libraries, and -- more immediately -- that adding a fourth
harness needs zero new event names.

The 23 hand-rolled names the three routers currently emit map onto 9 standard
events plus ``CUSTOM``; see ``ALIASES`` for the migration mapping.

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


# Legacy names the three routers emit today. Kept as an explicit map so the
# migration can emit both for one release and the frontend needs no change.
ALIASES: dict[str, EventType] = {
    "skeleton": EventType.RUN_STARTED,
    "plan-loaded": EventType.RUN_STARTED,
    "done": EventType.RUN_FINISHED,
    "plan-done": EventType.RUN_FINISHED,
    "error": EventType.RUN_ERROR,
    "round-start": EventType.STEP_STARTED,
    "section-start": EventType.STEP_STARTED,
    "round-end": EventType.STEP_FINISHED,
    "delta": EventType.TEXT_MESSAGE_CONTENT,
    "tool-calls": EventType.TOOL_CALL_RESULT,
    "phase": EventType.ACTIVITY_SNAPSHOT,
    "phase-delta": EventType.ACTIVITY_SNAPSHOT,
    # everything below became CUSTOM with a name
    "evaluate": EventType.CUSTOM,
    "revision": EventType.CUSTOM,
    "dropped": EventType.CUSTOM,
    "policy": EventType.CUSTOM,
    "replan": EventType.CUSTOM,
    "plan-extended": EventType.CUSTOM,
    "section-done": EventType.CUSTOM,
}


def sse(event: str, data: dict) -> str:
    """Serialise one SSE frame.

    Lived in ``routers/note_harness`` and was imported by two other routers.
    It is the wire format for the event contract, so it belongs next to the
    contract.
    """
    import json

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def to_sse(event: Event) -> str:
    """Serialise an ``Event``. ``type`` goes on the wire as the AG-UI name."""
    return sse(event.type.value, event.data)


def legacy_frames(event: Event) -> list[str]:
    """Serialise one ``Event`` into the frames today's frontend listens for.

    A translation shim with a known end date. The three routers are migrating
    to the loop one at a time; if each migration also changed the wire format,
    the frontend would have to support two contracts for as long as the
    migration runs. Instead the backend speaks AG-UI internally and this
    function speaks the old names outward. When the last router has moved,
    the frontend switches to the AG-UI names in one commit and this function
    is deleted -- ``ALIASES`` above is the map it will follow.

    Events with no legacy equivalent (TEXT_MESSAGE_START/END, warnings)
    serialise to nothing. The old frontend never saw them.
    """
    t, d = event.type, event.data
    if t is EventType.TEXT_MESSAGE_CONTENT:
        return [sse("delta", {"text": d.get("delta", "")})]
    if t is EventType.STEP_STARTED:
        return [sse("phase", {"round": d.get("step"), "label": d.get("label", "")})]
    if t is EventType.STEP_FINISHED:
        return [sse("round-end", {"round": d.get("step")})]
    if t is EventType.ACTIVITY_SNAPSHOT:
        return [sse("phase", {"label": d.get("content", "")})]
    if t is EventType.TOOL_CALL_RESULT:
        # The old frame carried a whole round's calls at once; one call per
        # frame is equivalent for a frontend that appends them.
        return [sse("tool-calls", {"calls": [{"tool": d.get("toolName"),
                                              "args": d.get("args"),
                                              "result": d.get("content")}]})]
    if t is EventType.RUN_FINISHED:
        return [sse("done", {"reason": d.get("reason"),
                             "run_id": d.get("run_id"),
                             "blocked_reason": d.get("blocked_reason"),
                             # ``block`` for the block harness, ``content``
                             # for the long-form ones -- one field under the
                             # two names the frontend already reads.
                             "block": d.get("content"),
                             "content": d.get("content")})]
    if t is EventType.RUN_ERROR:
        return [sse("error", {"detail": d.get("message", "")})]
    if t is EventType.CUSTOM:
        name, value = d.get("name", ""), d.get("value") or {}
        if name in ("evaluate", "policy", "revision", "dropped", "skeleton"):
            return [sse(name, value)]
        if name == "phase_delta":
            return [sse("phase-delta", value)]
        if name == "round_summary":
            return [sse("round-start", value)]
        if name == "replan":
            return [sse("replan", value)]
        return []
    return []
