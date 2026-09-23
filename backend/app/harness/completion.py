"""Deterministic last gate before a long-form run may say "complete".

The LLM judge evaluates prose quality, but it has repeatedly returned all
twos for drafts that still end in an empty heading or literally say that a
piece of evidence must be added. Those are not subtle quality judgements:
the document itself declares that work remains. Keep that truth outside the
model so a polished-looking score cannot turn an unfinished draft into a
successful delivery.
"""

from __future__ import annotations

import re


_PENDING = re.compile(
    r"(?:这里|此处|这一节|本节)?(?:仍|还|尚)?(?<!不)(?<!无需)(?<!不再)需要补上|"
    r"[（(]\s*(?:日期待补|date pending)\s*[）)]|"
    r"^\s*(?:[-*+]\s*)?(?:待补|尚缺|未写|待写)(?:充)?\s*[：:]|"
    r"^\s*(?:[-*+]\s*)?(?:TODO|TBD|FIXME|TO ADD|MISSING|PLACEHOLDER)\b\s*[:：-]?",
    re.M | re.I,
)
_PENDING_BEAT = re.compile(
    r"^\s*(?:待补|尚缺|未写|待写)(?:充)?\s*[：:]|"
    r"^\s*(?:TODO|TBD|FIXME|TO ADD|MISSING|PLACEHOLDER)\b\s*[:：-]?",
    re.I,
)
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(\S.*)$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def unfinished_reasons(content: str, beats: list[str] | None = None) -> list[str]:
    """Return short user-facing reasons why a long-form draft is unfinished."""
    reasons: list[str] = []
    text = content or ""
    if _PENDING.search(text):
        reasons.append("正文明确标了待补材料")

    empty = _empty_headings(text)
    if empty:
        examples = "、".join(empty[:2])
        reasons.append(f"有 {len(empty)} 个空章节（{examples}）")

    pending_beats = [b for b in (beats or []) if _PENDING_BEAT.match(b)]
    if pending_beats:
        reasons.append(f"写作计划还有 {len(pending_beats)} 项未覆盖")
    return reasons


def _empty_headings(content: str) -> list[str]:
    """Markdown headings with no prose/list/code content before the next one."""
    lines = content.splitlines()
    headings: list[tuple[int, int, str]] = []
    fenced = False
    fence_mark = ""
    for i, line in enumerate(lines):
        mark = _FENCE.match(line)
        if mark:
            token = mark.group(1)
            if not fenced:
                fenced, fence_mark = True, token[0]
            elif token.startswith(fence_mark):
                fenced, fence_mark = False, ""
            continue
        heading = _HEADING.match(line) if not fenced else None
        if heading:
            headings.append((i, len(heading.group(1)), heading.group(2).strip()))

    out: list[str] = []
    for n, (start, level, title) in enumerate(headings):
        # A document title followed by a populated H2 is not empty. A heading
        # ends only at the next heading of the same or a higher level; nested
        # subheadings belong to its section.
        end = len(lines)
        for next_start, next_level, _next_title in headings[n + 1:]:
            if next_level <= level:
                end = next_start
                break
        body = [line.strip() for line in lines[start + 1:end]
                if line.strip()
                and not line.lstrip().startswith("<!--")
                and not _HEADING.match(line)]
        if not body:
            out.append(title)
    return out
