"""The harness runtime: one loop, shared by every writing feature.

A harness = one ``Mode`` (configuration) + one ``Hooks`` (three callbacks).
Everything else -- the round loop, the event contract, the middleware chain,
the two kinds of judgement -- is shared and lives here.

See ``docs/harness-framework.md`` for the reasoning behind every decision in
this package. The short version:

* The loop is hardcoded. All 12 frameworks surveyed do it this way; we had
  three hand-copied loops (555 + 245 + 156 lines) and paid for it four times
  over with "one harness has it, the other doesn't" bugs.
* Judgement splits in two: ``Check`` (code decides) and ``Dimension`` (model
  decides). Anything code can decide reliably must not be left to the model,
  because the scorer and the thing being scored are the same local model --
  its blind spots overlap exactly with the writer's.
* Capabilities are middleware, on by default. Opt-out is explicit; opt-in
  is how things get forgotten.
"""

from .events import Event, EventType
from .state import State
from .types import Check, Hooks, Middleware, Mode, StopCondition, Verdict

__all__ = [
    "Check",
    "Event",
    "EventType",
    "Hooks",
    "Middleware",
    "Mode",
    "State",
    "StopCondition",
    "Verdict",
]
