"""Deterministic checks on what an extraction produced.

The writing harness learned this the expensive way: a judgement a rule can
make should never be handed to a model. Extraction is in the same position --
its output is a batch of facts, and some things about a fact are decidable.

**Only one check is here, and the reason is measured.** The design listed
three code-judged criteria: duplicates, granularity, and numbers having a
source. Run against the real writing codebook (2922 facts):

| 判据 | 真实占比 | 结论 |
|---|---|---|
| 同场会议内高度相似的事实对 | 1 / 26258 | 不存在，不做 |
| 一条事实塞了三件以上 | 6 / 2922 (0.2%) | 不存在，不做 |
| 数字在原文里找不到 | **~10%** | 做 |

Building all three would have been copying the design instead of reading the
data -- the same mistake as porting a threshold that never fires.

**And the one check needed its own measurement before it was worth anything.**
The naive version -- "every number in the fact must appear in the source" --
flags 31%, and most of those are correct extractions: the year comes from the
session's own date, ``10,000`` is one number that a digit regex reads as two,
and a date inside the sentence brings its own month and day. Filtering those
leaves ~10%, and what is left is the interesting kind: arithmetic the model
did itself (``112 / 1.5 = 74.6``) and years it inferred rather than read.

**It reports; it does not reject.** A derived number can be right, and a
correct extraction that computes a ratio is more useful than one that
doesn't. What matters is that the rate is visible.

The second group of checks here is about **shape**: a fact too short to carry
anything, a transcription stutter, a bare question, a lone speaker label.
These are what justified re-extracting the whole library in the first place --
15.6% of the source codebook's 20406 facts are unusable by these rules
against 1.2% of the writing one. They are kept because one of them is still
being violated: **9.5% of writing facts still carry a "Speaker A/B/C" label**
even though the extraction rules say in as many words never to write one, and
those labels are per-session tags that mean a different person in the next
conversation.
"""

from __future__ import annotations

import re

# Digit runs, keeping decimals and comma grouping together. Splitting
# ``10,000`` into ``10`` and ``000`` was a measured false positive.
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Anything date-shaped, so a date written inside the sentence does not
# contribute its parts as free-floating numbers to check.
_DATE = re.compile(r"\d{4}\s*[-年/]\s*\d{1,2}(?:\s*[-月/]\s*\d{1,2})?\s*日?")

# One-digit numbers are noise: "1" appears in almost any long source text by
# accident, so its presence proves nothing either way.
MIN_DIGITS = 2

# Chinese numerals, for sources that spell figures out. Deliberately only the
# small ones -- a general converter would be a project, and the measured
# misses are things like 三米 / 二十, not 三千二百四十七.
_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_RUN = re.compile(r"[零〇一二两三四五六七八九十]{1,3}")


def numbers_without_source(fact_text: str, source_text: str,
                           when: str = "") -> list[str]:
    """Numbers in the fact that the source does not contain.

    ``when`` is the conversation's date. Its parts are excluded: an extractor
    writing "2026 年 3 月" for a meeting held in March 2026 is completing the
    record, not inventing one, and that single case accounts for two thirds of
    what the naive check flags.
    """
    if not fact_text or not source_text:
        return []

    known = set(_NUMBER.findall(source_text))
    known |= {n.replace(",", "") for n in known}
    known |= _chinese_numbers(source_text)
    known |= set(re.findall(r"\d+", when or ""))

    # A date inside the fact is one token, not three numbers.
    body = _DATE.sub(" ", fact_text)

    missing = []
    for raw in _NUMBER.findall(body):
        plain = raw.replace(",", "")
        if len(plain.replace(".", "")) < MIN_DIGITS:
            continue
        if raw in known or plain in known:
            continue
        if plain not in missing:
            missing.append(plain)
    return missing


def rate(facts, lines_by_unit: dict[str, str]) -> dict:
    """The unsupported-number rate over a batch of facts.

    Reported as a fraction of the facts that *could* be checked -- ones that
    contain a number and whose source text is available. Reporting it over
    every fact would hide a bad batch inside a pile of facts with no numbers
    in them.
    """
    checked = flagged = 0
    examples: list[dict] = []
    for fact in facts:
        source = lines_by_unit.get(getattr(fact, "unit", ""), "")
        text = getattr(fact, "text", "") or ""
        if not source or not _NUMBER.search(text):
            continue
        checked += 1
        missing = numbers_without_source(text, source, getattr(fact, "when", ""))
        if missing:
            flagged += 1
            if len(examples) < 10:
                examples.append({"id": getattr(fact, "id", ""),
                                 "numbers": missing, "text": text[:200]})
    return {"checked": checked, "flagged": flagged,
            "rate": round(flagged / checked, 3) if checked else 0.0,
            "examples": examples}


def _chinese_numbers(text: str) -> set[str]:
    """Small Chinese numerals as their digit form."""
    out: set[str] = set()
    for match in _CN_RUN.finditer(text):
        value = _value_of(match.group(0))
        if value is not None:
            out.add(str(value))
    return out


def _value_of(run: str) -> int | None:
    if run in _CN_DIGIT:
        return _CN_DIGIT[run]
    if run == "十":
        return 10
    if len(run) == 2 and run[0] == "十":
        return 10 + _CN_DIGIT.get(run[1], 0)
    if len(run) == 2 and run[1] == "十":
        return _CN_DIGIT.get(run[0], 0) * 10
    if len(run) == 3 and run[1] == "十":
        return _CN_DIGIT.get(run[0], 0) * 10 + _CN_DIGIT.get(run[2], 0)
    return None


# ---------------------------------------------------------------- shape ---

# Below this a fact cannot carry what it needs to (what happened, to what,
# with which constraint). Measured against real output: the source codebook
# has 1699 facts shorter than this, most of them noun phrases.
MIN_USEFUL_CHARS = 16

_FILLER = re.compile(r"(那个那个|就是就是|他他他|要要|嗯嗯|呃呃|我说那个|这个这个)")

# A fact whose whole content is "Speaker B said <a few words>". The label is
# useless (it names a different person next session) and what remains is too
# little to write from.
_SPEAKER_ONLY = re.compile(r"^Speaker [A-Z] ?(说|表示|认为|提到)?\s*[「\"\']?.{0,12}[」\"\']?$")

# The label anywhere in the content, which the extraction rules forbid
# outright: attribution belongs in the ``who`` field.
_SPEAKER_LABEL = re.compile(r"Speaker [A-Z]")


def unusable_shape(text: str) -> str | None:
    """Why this fact can't be written from, or None if it can."""
    if len(text) < MIN_USEFUL_CHARS:
        return "太短"
    if _FILLER.search(text):
        return "口语填充/ASR 噪声"
    if text.rstrip().endswith(("？", "?")):
        return "是提问不是事实"
    if _SPEAKER_ONLY.match(text):
        return "只有说话人+短语"
    return None


def shapes(facts) -> dict:
    """How many facts are the wrong shape to write from, and which way.

    Separate from ``rate`` because it needs no source text: shape is decidable
    from the fact alone, so this runs over a whole codebook in milliseconds.
    """
    reasons: dict[str, int] = {}
    labelled = 0
    total = 0
    for fact in facts:
        text = (getattr(fact, "text", "") or "").strip()
        if not text:
            continue
        total += 1
        why = unusable_shape(text)
        if why:
            reasons[why] = reasons.get(why, 0) + 1
        if _SPEAKER_LABEL.search(text):
            labelled += 1
    unusable = sum(reasons.values())
    return {
        "facts": total,
        "unusable": unusable,
        "unusable_rate": round(unusable / total, 3) if total else 0.0,
        "reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        # 抽取规则明说了不许把 Speaker A/B/C 写进正文——归属放 who 字段。
        # 实测写作库还有 9.5%，所以这条单独报，不混进 unusable。
        "speaker_labels": labelled,
        "speaker_label_rate": round(labelled / total, 3) if total else 0.0,
    }
