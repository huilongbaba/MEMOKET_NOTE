"""Interfaces the host application implements. This package never does
network I/O or persistence itself -- see README "Design notes"."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import RunRecord


@runtime_checkable
class LLMClient(Protocol):
    """Anything that can turn a chat-style message list into text. Matches
    the common OpenAI-compatible `complete(messages, **kw) -> str` shape
    closely enough that most existing app-side LLM wrappers satisfy this
    with a one-line adapter, without this package caring which provider,
    auth scheme, or model is behind it."""

    async def complete(self, messages: list[dict], **kwargs) -> str: ...


@runtime_checkable
class RunHistoryStore(Protocol):
    """Persists completed runs and retrieves recent ones for a given key
    (whatever the host app's model of "same recurring task" is -- a note
    id, a user id, a task type -- this package doesn't prescribe it).
    Optional: callers that don't care about cross-run history simply never
    construct one."""

    def record(self, run: RunRecord) -> None: ...

    def recent(self, key: str, limit: int = 3) -> list[RunRecord]: ...
