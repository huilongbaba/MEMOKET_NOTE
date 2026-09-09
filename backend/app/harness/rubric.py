"""The scoring engine: one LLM call, a fixed JSON contract, a small amount
of programmatic post-processing. This is the package's answer to "there's
no execution oracle for writing" -- see README."""

from __future__ import annotations

import json

from .types import (Dimension, DimensionScore, DupHint, Evaluation, LLMClient)

DEFAULT_SYSTEM_PROMPT = """You are a rigorous editor. You will be given a \
piece of writing and a fixed set of dimensions to score it against. Score \
each dimension independently:

0 = insufficient: this dimension's bar is clearly not met
1 = partial: some progress, but not there yet
2 = meets the bar: no further work needed on this dimension

Then decide, across all dimensions together, whether the piece is:
- "blocked": stuck for a reason that another round of writing or editing \
cannot fix on its own (for example, the content written so far \
structurally contradicts the stated goal, or two required things are \
mutually exclusive as currently written) -- this is different from "not \
finished yet", and should be rare; only use it when more rounds genuinely \
would not help
- otherwise: not blocked

Do not soften a low score because the piece is long or because a lot of \
effort clearly went into it -- score strictly against each dimension's own \
description of what "meets the bar" means.

Return JSON only, no other text:
{
  "scores": {"<dimension name>": {"level": 0|1|2, "note": "one sentence"}, ...},
  "blocked": true|false,
  "blocked_reason": "one sentence, only if blocked is true, else empty string"
}"""


def _extract_json(text: str) -> dict | None:
    """Minimal JSON-object extraction: strips ``` fences, then finds the
    first balanced {...}. Kept deliberately small and dependency-free --
    this package doesn't try to recover from every malformed-output shape a
    model might produce, callers needing that should validate/retry around
    evaluate() themselves."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _render_dup_hints(dup_hints: tuple[DupHint, ...]) -> str:
    if not dup_hints:
        return ""
    lines = [
        f"- ({hint.similarity:.0%} similar) “{hint.a[:80]}…” vs “{hint.b[:80]}…”"
        for hint in dup_hints
    ]
    return "Mechanically detected candidate near-duplicate passages (verify, don't assume):\n" + "\n".join(lines)


def _build_prompt(
    content: str,
    dimensions: list[Dimension],
    context: dict[str, str] | None,
    dup_hints: tuple[DupHint, ...],
) -> str:
    parts = []
    if context:
        for title, text in context.items():
            if text:
                parts.append(f"[{title}]\n{text}")
    dim_lines = "\n".join(f"- {d.name}: {d.guidance}" for d in dimensions)
    parts.append(f"[Dimensions to score]\n{dim_lines}")
    dup_block = _render_dup_hints(dup_hints)
    if dup_block:
        parts.append(dup_block)
    parts.append(f"[Content]\n{content}")
    return "\n\n".join(parts)


async def evaluate(
    llm: LLMClient,
    *,
    content: str,
    dimensions: list[Dimension],
    context: dict[str, str] | None = None,
    dup_hints: list[DupHint] = (),
    system_prompt: str | None = None,
    max_tokens: int = 600,
    temperature: float = 0.1,
) -> Evaluation:
    """Score ``content`` against ``dimensions`` in one LLM call, return the
    per-dimension scores plus an overall continue/complete/blocked verdict.

    ``complete`` is decided programmatically (every dimension at level 2) --
    the model can't be trusted to reliably self-report "I'm done" (that's
    the whole reason this package exists), so it only has to make the
    narrower, harder-to-fake judgment of "is this specific dimension at
    level 2", not "is everything finished". ``blocked`` is the one signal
    that genuinely needs the model's own judgment (a low score alone can't
    tell you whether another round would help), so it's asked for directly
    and trusted as reported.
    """
    if not dimensions:
        raise ValueError("evaluate() needs at least one dimension")

    prompt = _build_prompt(content, dimensions, context, tuple(dup_hints))
    raw = await llm.complete(
        [
            {"role": "system", "content": system_prompt or DEFAULT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    parsed = _extract_json(raw) or {}
    raw_scores = parsed.get("scores") if isinstance(parsed.get("scores"), dict) else {}

    scores: dict[str, DimensionScore] = {}
    for dim in dimensions:
        entry = raw_scores.get(dim.name)
        level, note = 0, ""
        if isinstance(entry, dict):
            level_raw = entry.get("level")
            if isinstance(level_raw, (int, float)) and int(level_raw) in (0, 1, 2):
                level = int(level_raw)
            note = str(entry.get("note") or "")
        scores[dim.name] = DimensionScore(level=level, note=note)

    blocked = bool(parsed.get("blocked"))
    blocked_reason = str(parsed.get("blocked_reason") or "") or None

    if blocked:
        return Evaluation(scores=scores, status="blocked", blocked_reason=blocked_reason)

    weakest_name, weakest_level = None, 3
    for dim in dimensions:
        level = scores[dim.name].level
        if level < weakest_level:
            weakest_name, weakest_level = dim.name, level

    if weakest_level >= 2:
        return Evaluation(scores=scores, status="complete")
    return Evaluation(scores=scores, status="continue", weakest=weakest_name)
