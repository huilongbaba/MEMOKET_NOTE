"""Plain dataclasses shared across the package. No behavior lives here."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Status = Literal["continue", "complete", "blocked"]


@dataclass(frozen=True)
class Dimension:
    """One scored axis of "what good means here", supplied by the caller.

    ``guidance`` is rendered directly into the scoring prompt -- write it as
    a sentence describing what a low vs. high score looks like for this
    dimension, not as a bare label. The model scores against this text, not
    against any assumption baked into this package.
    """

    name: str
    guidance: str


@dataclass(frozen=True)
class DimensionScore:
    """One dimension's result for one evaluate() call.

    ``level`` is 0 (insufficient) / 1 (partial) / 2 (meets the bar) -- coarse
    on purpose. A finer scale invites false precision from a single LLM call;
    three levels is enough to drive "what's weakest" without pretending the
    judgment is more exact than it is.
    """

    level: int
    note: str


@dataclass(frozen=True)
class Evaluation:
    """Result of one evaluate() call."""

    scores: dict[str, DimensionScore]
    status: Status
    weakest: str | None = None
    blocked_reason: str | None = None


@dataclass(frozen=True)
class DupHint:
    """One candidate near-duplicate pair found by find_repeats()."""

    a: str
    b: str
    similarity: float


@dataclass(frozen=True)
class RunRecord:
    """One completed (or abandoned) harness run, for RunHistoryStore."""

    key: str
    status: Status
    rounds: int
    final_scores: dict[str, int]
    weak_dimensions: list[str] = field(default_factory=list)
    timestamp: str = ""
