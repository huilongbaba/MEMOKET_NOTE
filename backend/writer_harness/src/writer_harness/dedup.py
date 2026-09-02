"""Deterministic, non-LLM near-duplicate detection.

The mechanical-signal counterpart to evaluate(): cheap enough to run every
round, and gives the model concrete candidate pairs to judge instead of
asking it to re-read the whole document looking for repeats on its own --
the same "rank, dedup, limit before injection" shape as a static analyzer's
diagnostics, applied to prose instead of code.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from .types import DupHint

DEFAULT_THRESHOLD = 0.6
DEFAULT_MAX_HINTS = 5
MIN_PARAGRAPH_LEN = 20  # shorter paragraphs (a lone heading, a short list
                        # item) produce noisy high-similarity matches that
                        # aren't meaningful repeats


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if len(p.strip()) >= MIN_PARAGRAPH_LEN]


def find_repeats(
    content: str,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    max_hints: int = DEFAULT_MAX_HINTS,
) -> list[DupHint]:
    """Pairwise-compare paragraphs in ``content``, return the highest-
    similarity pairs above ``threshold``, ranked descending and capped at
    ``max_hints``. A paragraph appears in at most one returned pair (the
    one it matched best) so the same repeated passage doesn't crowd out
    every other hint."""
    paragraphs = _paragraphs(content)
    scored: list[DupHint] = []
    for i, a in enumerate(paragraphs):
        for b in paragraphs[i + 1 :]:
            ratio = SequenceMatcher(None, a, b).ratio()
            if ratio >= threshold:
                scored.append(DupHint(a=a, b=b, similarity=ratio))
    scored.sort(key=lambda hint: hint.similarity, reverse=True)

    seen: set[str] = set()
    deduped: list[DupHint] = []
    for hint in scored:
        if hint.a in seen or hint.b in seen:
            continue
        deduped.append(hint)
        seen.add(hint.a)
        seen.add(hint.b)
        if len(deduped) >= max_hints:
            break
    return deduped
