"""Structural checks: does the new text fit where it's being inserted.

Two of these carry a ``fix``. The boundary for that was established by
running both against real failing output rather than by reasoning:

* heading depth -- fixable. Sinking every heading one level is unambiguous
  and touches no words (verified: stripping ``#`` from before and after
  gives identical text).
* "too many subheadings" -- not fixable. Which one to drop is a judgement
  call, so it goes back to the model.
"""

from __future__ import annotations

import re

from ...editor import outline
from . import blockcheck
from ..state import State
from ..types import Verdict
from .pick import pick_dimension

_HEADING = re.compile(r"^(#{1,6})(\s)", re.M)

# Section titles that mean "wrapping up". A block that writes its own
# conclusion right before the note's existing conclusion is fighting the
# document's structure.
_TAIL_WORDS = ("next steps", "what to look at next", "summary", "conclusion",
               "接下来", "下一步", "总结", "小结")


def table_present(st: State) -> Verdict | None:
    """生成表格那条路的产出里得有一张表。

    实拍（第 152 轮）：第 1 轮调了 render_table 出了一张好表，第 2、3 轮模型写了句
    「[tool call needed]」就交卷——没表。之前这种轮次还要再花一次打分调用才发现 table_validity=0；
    表有没有是规则能判的，这里先判，判不过就不打分、下一轮的提示直接说清楚。"""
    if blockcheck.has_table(st.content):
        return None
    return Verdict(
        pick_dimension(st, "table_validity", "coherence"),
        "这一轮没有表格。必须**调用 render_table** 生成一张 markdown 表并把它原样贴进来——"
        "写「需要调用工具」不算，工具要真的调。",
    )


def heading_fits(st: State) -> Verdict | None:
    """Headings must sit *below* the surrounding section, not beside it."""
    gap = blockcheck.heading_gap(st.before, st.content)
    if not gap:
        return None
    return Verdict(pick_dimension(st, "fits_context", "coherence"), gap, fix=lambda text: _sink_headings(st.before, text))


def _sink_headings(before: str, block: str) -> str:
    """Push every heading down until the shallowest is one level below the
    nearest heading above the cursor. Only ``#`` counts change."""
    prev = re.findall(r"^(#{1,6})\s", before or "", re.M)
    needed = (len(prev[-1]) if prev else 1) + 1
    mine = re.findall(r"^(#{1,6})\s", block or "", re.M)
    if not mine:
        return block
    delta = needed - min(len(h) for h in mine)
    if delta <= 0:
        return block
    return _HEADING.sub(
        lambda m: "#" * min(6, len(m.group(1)) + delta) + m.group(2), block)


def tail_clashes(st: State) -> Verdict | None:
    """A self-written closing section colliding with one the note already has.

    Observed: a data-visualisation block ending in "What to look at next",
    inserted directly above the note's own "Next steps" section.
    """
    if not st.after:
        return None
    existing = re.findall(r"^#{1,6}\s+(\S.*)$", st.after, re.M)
    if not any(any(w in h.lower() for w in _TAIL_WORDS) for h in existing):
        return None
    mine = re.findall(r"^#{1,6}\s+(\S.*)$", st.content, re.M)
    clashing = [h for h in mine if any(w in h.lower() for w in _TAIL_WORDS)]
    if not clashing:
        return None
    return Verdict(
        pick_dimension(st, "fits_context", "coherence"),
        f"这一段自己写了一个收尾小节（{clashing[0]!r}），而下面的正文已经有收尾了。"
        "去掉——插进笔记里的是一段话，不是一篇独立的报告。",
        fix=lambda text: _drop_tail_sections(text),
    )


def _drop_tail_sections(block: str) -> str:
    parts = re.split(r"(?m)^(#{1,6}\s+.*)$", block)
    out, i = [parts[0]], 1
    while i < len(parts) - 1:
        title = re.sub(r"^#+\s+", "", parts[i]).strip().lower()
        if not any(w in title for w in _TAIL_WORDS):
            out += [parts[i], parts[i + 1]]
        i += 2
    return "".join(out).rstrip() + "\n"


def outline_intact(st: State) -> Verdict | None:
    """An outline note must keep its hierarchy.

    Flattening a three-level outline into a flat list was a 20-out-of-20
    reproducible failure once. Prose instructions never stopped it; this does.
    """
    if not outline.is_outline(st.before):
        return None
    if outline.structure_intact(st.before, st.content):
        return None
    return Verdict(
        pick_dimension(st, "fits_context", "coherence"),
        "这篇是一份大纲，它的标题层级被压平了。保留原来的层级：在标题下面写，"
        "不要重写标题。",
    )
