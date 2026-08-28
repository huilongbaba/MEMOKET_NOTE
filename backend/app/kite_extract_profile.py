"""Patches KITE's extraction prompt: forces source-language fact content, and
strengthens the topic-proposal instruction.

KITE hardcodes the extraction profile inside Memory.remember() -- there is no
parameter to override it (same root cause as the English-only keywords()
regex documented in docs/kite-constraints.md constraint 5). The only
integration point that accepts a custom profile is the internal
pipeline.extract.extract_facts(vocabulary, profile, ...), and
memoket_kite.remember.extract_facts() -- what Memory.remember() actually
calls -- reads its profile from the module-level DEFAULT_MEMORY_PROFILE name
at call time. Reassigning that name is the narrowest way to swap the profile
without reimplementing remember()'s persistence/locking/dedup logic ourselves.

Two problems fixed here, both because the stock prompt never states a rule
and our local model (temperature is hardcoded to 0, see constraint 7) falls
back to whatever is "safe" by default when a rule is unstated:

1. Fact language. The prompt never says what language "content" should be
   written in. Verified directly against the raw LLM endpoint (bypassing
   KITE): the same Chinese input produces English content in one call and
   Chinese content in the next -- it is not driven by anything in the text,
   just call-to-call drift. For a Chinese-language note app this means the
   knowledge base ends up an unpredictable mix of the two, which breaks the
   "search in the language you wrote in" expectation. Fixed by requiring
   content to mirror the source utterance's language, untranslated.

2. Topic specificity. With the stock wording, the model almost never
   exercises "propose one specific child under a known root". Verified
   directly against the raw LLM endpoint with clearly specializable content
   -- a hiring thread naming three candidates and a budget deadline -- and
   got back "proposals": [] every time; it just reused whichever known root
   loosely fit. Fixed by making the instruction directive and adding a
   worked example.

Strengthening the instructions is the only lever available for either since
temperature is not configurable from here. See docs/kite-constraints.md
constraints 10 and 11.
"""

from __future__ import annotations

import warnings

import memoket_kite.remember as _kite_remember
from memoket_kite.defaults import DefaultMemoryProfile
from memoket_kite.prompts.extract import (
    DEFAULT_EXTRACT_PROMPT,
    DEFAULT_EXTRACT_PROMPT_NO_FACETS,
)

_ORIGINAL_CAPTURE_RULE = (
    '- Capture durable information that may matter in a later conversation. Write\n'
    '  one self-contained claim per fact; do not infer information not stated.'
)

_STRONGER_CAPTURE_RULE = (
    '- Capture durable information that may matter in a later conversation. Write\n'
    '  one self-contained claim per fact; do not infer information not stated.\n'
    '- Write "content" in the SAME language as the utterance(s) it is drawn\n'
    '  from. Never translate. If the conversation mixes languages, each fact\n'
    '  follows the language of its own supporting text, not the session as a\n'
    '  whole.'
)

_ORIGINAL_TOPICS_RULE = (
    '- "topics": reuse the most specific known codes. If none fits, propose one\n'
    '  specific child under a known root. "entities": named people, places,\n'
    '  organizations, products, works, or other concrete named things.'
)

_STRONGER_TOPICS_RULE = (
    '- "topics": do not settle for a broad root when a more specific label\n'
    '  fits. A root code (e.g. "work") is a category, not a proper topic -- it\n'
    '  is only correct when the fact is genuinely too general to specialize.\n'
    '  If the fact concerns a specific recurring subject (a named activity, a\n'
    '  project, a hiring round, a medical condition, a course, a budget line),\n'
    '  propose ONE new specific child topic under the closest known root and\n'
    '  use that child code instead of the root. Example: a fact about job\n'
    '  candidates and a hiring budget should propose a child like "hiring"\n'
    '  under "work", giving topics ["hiring"], not just ["work"]. "entities":\n'
    '  named people, places, organizations, products, works, or other\n'
    '  concrete named things.'
)


_PATCHES = (
    ("capture/language rule", _ORIGINAL_CAPTURE_RULE, _STRONGER_CAPTURE_RULE),
    ("topics rule", _ORIGINAL_TOPICS_RULE, _STRONGER_TOPICS_RULE),
)


def _patch(prompt: str) -> str:
    for name, anchor, replacement in _PATCHES:
        if anchor not in prompt:
            # KITE's prompt wording moved upstream -- fall back to the stock
            # text for this rule instead of silently shipping a patch that no
            # longer applies.
            warnings.warn(
                f"kite_extract_profile: anchor text for the {name} not found "
                "in KITE's extraction prompt; that patch is a no-op until "
                "this is updated for the new wording.",
                stacklevel=2,
            )
            continue
        prompt = prompt.replace(anchor, replacement)
    return prompt


class _PatchedProfile(DefaultMemoryProfile):
    EXTRACT_PROMPT = _patch(DEFAULT_EXTRACT_PROMPT)
    EXTRACT_PROMPT_NO_FACETS = _patch(DEFAULT_EXTRACT_PROMPT_NO_FACETS)


def install() -> None:
    """Point Memory.remember()'s extraction at the strengthened profile.

    Idempotent -- safe to call more than once / from more than one import path.
    """
    _kite_remember.DEFAULT_MEMORY_PROFILE = _PatchedProfile
