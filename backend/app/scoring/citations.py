"""Deterministic, non-LLM citation verification.

The gap this closes: a model can be asked to self-report which source
material a claim rests on (the same "cite your sources" instruction already
used elsewhere in this package's host application), but that self-report is
itself just more model output -- nothing stops it from citing something
that sounds like a real source but was never actually shown to it. That
failure mode is different from "ungrounded" (no citation at all): it's a
*fabricated* citation, which reads as more trustworthy than no citation,
not less.

check_citations() answers a narrower, mechanically-verifiable question:
does each claimed source string actually match something in the pool of
material the model was given? A low match means the citation doesn't
correspond to real input -- evidence to feed into evaluate() (see
CitationCheck usage in rubric.py's citation_hints parameter), not a
verdict on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

DEFAULT_MATCH_THRESHOLD = 0.7


@dataclass(frozen=True)
class CitationCheck:
    """One claimed source's best match against the available material.
    ``best_match`` is already None whenever the best similarity found fell
    below whatever threshold check_citations() was called with -- ``verified``
    just reflects that, it does not re-derive against a fixed constant (an
    earlier version did, and disagreed with the threshold actually used)."""

    claimed: str
    best_match: str | None
    similarity: float

    @property
    def verified(self) -> bool:
        return self.best_match is not None


def check_citations(
    claimed_sources: list[str],
    available_facts: list[str],
    *,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> list[CitationCheck]:
    """For each string in ``claimed_sources``, find its best fuzzy match in
    ``available_facts`` and report the similarity. A claimed source with no
    match above ``threshold`` was not actually among the material the model
    was shown -- it's citing something that doesn't exist in its own input,
    not just paraphrasing loosely."""
    checks: list[CitationCheck] = []
    for claimed in claimed_sources:
        if not claimed.strip():
            continue
        best_match, best_ratio = None, 0.0
        for fact in available_facts:
            ratio = SequenceMatcher(None, claimed, fact).ratio()
            if ratio > best_ratio:
                best_match, best_ratio = fact, ratio
        checks.append(CitationCheck(
            claimed=claimed,
            best_match=best_match if best_ratio >= threshold else None,
            similarity=round(best_ratio, 3),
        ))
    return checks
