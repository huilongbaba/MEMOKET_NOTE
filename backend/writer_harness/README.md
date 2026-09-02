# writer-harness

A closed loop for LLM writing agents, for the case coding agent harnesses
don't cover: **there is no execution oracle for prose.** A coding harness
can decide "continue vs. done" by running tests. A writing harness can't --
"is this note finished, is this section good" has no pass/fail command to
run. writer-harness's answer is to make that judgment call explicit and
scored instead of leaving it to an unreliable self-reported marker in the
model's own output.

You bring:
- a small set of **dimensions** -- what "good" means for your domain,
  each with one line of guidance for what a low/medium/high score looks
  like (nothing here is prescribed; a coding-adjacent tool might score
  "argument rigor", a marketing tool might score "keyword coverage")
- an **LLMClient** -- any async callable matching `complete(messages, **kw)
  -> str`, so any provider works
- optionally, a **RunHistoryStore** -- if you want completed runs to
  inform future ones

writer-harness gives back:
- `evaluate()` -- one LLM call that scores your dimensions and returns
  `continue` / `complete` / `blocked` plus which dimension is weakest,
  so the caller knows what to fix next round instead of guessing
- `find_repeats()` -- a free, deterministic (no LLM) near-duplicate-
  paragraph detector, for the extremely common case of an agent
  re-stating something it already wrote a few rounds ago
- `compact_context()` -- a free, deterministic progressive-compression
  helper for long-running sessions, so token cost doesn't grow unbounded
  with round count

## Design notes

- **No FastAPI, no HTTP client, no storage backend.** This package does
  one thing (score content against a rubric and mechanically flag
  repeats) and gets out of the way. The round loop, streaming, and
  persistence are the host application's job.
- **`blocked` is a real, distinct outcome**, not a subtype of `continue`.
  Sometimes what's been written so far structurally can't satisfy the
  rubric no matter how many more rounds run (the content contradicts the
  stated intent, say) -- that's a signal to surface to a human, not a
  reason to keep spinning against a round cap.
- **Dimensions are data, not code.** Nothing in this package knows what
  "good writing" means for any specific domain.

## Install

Editable local install (works from a monorepo checkout):

```
pip install -e ./writer_harness
```

## Quick example

```python
from writer_harness import Dimension, evaluate

dimensions = [
    Dimension("coherence", "high: every paragraph serves the stated goal; "
                            "low: content has drifted into unrelated listing"),
    Dimension("non_repetition", "high: no restated claims; "
                                 "low: the same conclusion appears more than once"),
]

result = await evaluate(
    my_llm_client,
    content=current_draft,
    dimensions=dimensions,
    context={"goal": "explain why the migration was necessary"},
)
if result.status == "complete":
    ...
elif result.status == "blocked":
    print(result.blocked_reason)
else:
    print("focus next round on:", result.weakest)
```
