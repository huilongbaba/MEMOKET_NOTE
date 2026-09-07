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

Four problems fixed here, all because the stock prompt never states a rule
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

3. Entity grounding against ASR mishearings. This is entity CODE resolution,
   not transcription correction -- "entities" is already a normalized
   reference assigned by register_entity() (core/vocab.py), not verbatim
   text, so recognizing that two different-looking mentions resolve to the
   same real thing doesn't change what was said, only which existing code a
   mention maps to; "content" is untouched by this rule. First attempt at
   this (below, still worth reading) was tested and abandoned as a false
   negative: KITE's own prompt builder capped KNOWN ENTITIES at
   `sorted(vocabulary.entities)[:80]`, and with ~2000 entities including ~105
   numeric-looking ones ("100美元", "10号", ...), digits sorting before
   letters meant the hint was 100% numeric noise -- the model's own product
   name never had a chance to be seen, let alone matched against. That root
   cause is now fixed separately (see kite_entity_candidates.py: KNOWN
   ENTITIES is now a session-relevant candidate list, not an alphabetical
   slice). Re-tested with the fix in place, same controlled case ("memokat"
   mishearing a real known entity "memoket", now actually visible in the
   hint): still 0/6 with no rule stated -- visibility alone isn't enough, the
   model doesn't spontaneously treat two different spellings as the same
   entity without being told to consider that possibility. This rule is that
   instruction. Wording matters: an earlier draft caused real
   over-suppression (already-known entities like "applewatch"/"woop"/"安克"
   vanished from output entirely instead of being substituted, fact counts
   dropped), root-caused to the model treating "prefer known code" as license
   to omit anything it wasn't confident about. Fixed by making addition-only
   explicit ("this only ever ADDS a substitution -- it never removes an
   entity you would otherwise write") and verified the fix holds (identical
   entity sets before/after on a real un-ingested meeting, no regression).

4. Confidence calibration under ASR uncertainty, for the residual case rule 3
   doesn't cover: an unusual-sounding term with no close match anywhere in
   KNOWN ENTITIES (a genuinely new mishearing, not yet reflected in any known
   code). Source data has no ASR confidence signal to inherit (checked:
   neither our own asr.py nor the raw terrence_records exports keep per-word
   probabilities), so "conf" is the only place left to record that kind of
   uncertainty. If a fact rests on a name, term, or number that sounds like
   it could be a mishearing, "conf" should reflect that even when the rest of
   the fact reads cleanly -- so retrieval's existing conf-based
   ranking/filtering (Where.conf_min, the 0.2 * conf ranking boost) naturally
   discounts it without any fact being dropped, rewritten, or guessed at.

   Verified with a controlled matched-pair trial (identical sentence, only the
   entity swapped between a real known brand and an invented, odd-sounding
   name; 6 runs per side against gpt-5.6-luna): unpatched, both sides came
   back "high" 6/6 -- no differentiation at all. This wording: the odd name
   came back "low" 6/6, a real, repeatable effect. It is not precise --
   the known-brand control also got knocked down to "low"/"med" in 3/6 runs,
   which a narrower rewrite (explicitly exempting known-vocab terms) fixed for
   the control case but also killed the effect on the odd name entirely (back
   to 6/6 "high", i.e. no signal). Kept this broader wording deliberately: the
   goal per the actual ask is reducing the IMPACT of ASR noise on the
   knowledge base, not precise per-fact calibration -- a noisy-but-directional
   signal (odd terms trend low, known terms mostly don't) is a real
   improvement over the unpatched baseline's zero differentiation, and the
   downstream cost of an occasional over-cautious "med"/"low" on a genuinely
   solid fact is a modest ranking nudge (Where.conf_min defaults to "low",
   i.e. inclusive), not exclusion.

Strengthening the instructions is the only lever available for any of these
since temperature is not configurable from here. See docs/kite-constraints.md
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


_ORIGINAL_ENTITY_RULE = (
    '"entities":\n'
    '  named people, places, organizations, products, works, or other\n'
    '  concrete named things.'
)

_STRONGER_ENTITY_RULE = (
    '"entities":\n'
    '  named people, places, organizations, products, works, or other\n'
    '  concrete named things. The conversation is machine-transcribed speech,\n'
    '  so an unusual-looking name or term is sometimes an ASR mishearing\n'
    '  rather than a new entity. This only ever ADDS a substitution -- it\n'
    '  never removes an entity you would otherwise write. Every entity you\n'
    '  would otherwise write still belongs in the output. Check each one\n'
    '  against KNOWN ENTITIES: only if it is a close phonetic or spelling\n'
    '  match AND nothing in the surrounding text marks it as a genuinely\n'
    '  different thing, write the known entity code in its place. In every\n'
    '  other case -- including when you are unsure, or it has no close match\n'
    '  in KNOWN ENTITIES -- write it as-is; a term with no close match is not\n'
    '  a reason to drop it. This is a code-resolution decision, not a\n'
    '  transcription correction -- it does not change what was said, only\n'
    '  which existing entity a mention refers to.'
)


_ORIGINAL_CONF_RULE = (
    '- "t": event time as YYYY-MM-DD or YYYY-MM when stated or safely resolvable;\n'
    '  otherwise null. "conf": high, med, or low.'
)

_STRONGER_CONF_RULE = (
    '- "t": event time as YYYY-MM-DD or YYYY-MM when stated or safely resolvable;\n'
    '  otherwise null. "conf": high, med, or low -- your confidence that this\n'
    '  fact is correct. This conversation is machine-transcribed speech, so the\n'
    '  text itself can be wrong independent of how clear the fact reads. If the\n'
    '  fact depends on a name, term, or number that sounds like it could be a\n'
    '  mishearing or a garbled fragment of the audio, mark "conf" as "low" even\n'
    '  when everything else about the fact is clear -- do not raise "conf" just\n'
    '  because the sentence around it is well-formed. Do not try to guess or\n'
    '  substitute what the "correct" word should be; write it exactly as\n'
    '  transcribed and let "conf" carry the uncertainty instead.'
)


_PATCHES = (
    ("capture/language rule", _ORIGINAL_CAPTURE_RULE, _STRONGER_CAPTURE_RULE),
    ("topics rule", _ORIGINAL_TOPICS_RULE, _STRONGER_TOPICS_RULE),
    # must run after the topics patch: this rule's anchor is the "entities"
    # tail left behind by _STRONGER_TOPICS_RULE's substitution, not the
    # original stock wording.
    ("entity grounding rule", _ORIGINAL_ENTITY_RULE, _STRONGER_ENTITY_RULE),
    ("ASR confidence rule", _ORIGINAL_CONF_RULE, _STRONGER_CONF_RULE),
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
