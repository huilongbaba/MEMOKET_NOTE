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
from ..middleware import repeats
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


def table_columns_match(st: State) -> Verdict | None:
    """表头和数据行的列数对不对得上（计划 5.1 / [IND] §3）。

    `table_validity` 的达标线原话是「a complete markdown table whose header
    and rows have matching column counts」——**一句纯粹能用代码判准的话**，
    而在批 16 之前它整条交给了打分模型：`table_present` 只查"有没有表"、
    `blockcheck.has_table` 只查"表头下面有没有分隔行"，**两者都不数列**。

    实现（`blockcheck.table_column_mismatch`）是从
    `scripts/dimension_sensitivity_bench.py` 搬过来的——批 12 在 bench 侧写它，
    是为了自验「列数植入器真的把列数弄错了」。同一件事两边各写一份的话，
    "植入器植没植进去"和"生产判不判得出来"会各判各的。
    """
    if not blockcheck.table_column_mismatch(st.content):
        return None
    return Verdict(
        pick_dimension(st, "table_validity", "coherence"),
        "这张表的列数对不上：有的行比表头多一格或少一格，渲染出来会错位。"
        "**重新调用 render_table**（它按 columns / rows 拼，列数不会错），"
        "不要手动补竖线——空着的格子留空就行，别为了对齐去编一个值。",
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


def no_same_sources_twice(st: State) -> Verdict | None:
    """同一批事实被换个说法写了两遍。

    段落级查重（0.39）和清单级查重都看不见这一对，但**它们引的是同一组编号**
    ——而编号是我们自己发的，可以精确比对。判据细节和阈值来源见
    `citations.same_sources_twice`；它住在 citations.py 而不是 blockcheck.py，
    因为引用正则全仓只定义一处，而 blockcheck 是只许标准库的纯层。
    """
    from .citations import same_sources_twice

    dups = same_sources_twice(st.content, st.fresh or "")
    if not dups:
        return None
    a, b = dups[0]
    return Verdict(
        pick_dimension(st, "non_repetition", "coherence", "style_fit"),
        f"这两段引的是同一批事实，等于把同一件事说了两遍：「{a[:50]}…」和「{b[:50]}…」。"
        "留下更完整的那一段，另一段删掉或改成一句话接住上文——"
        "同一组依据支撑不出两段独立的结论。",
    )


# 段内重复到这个比例就是缺陷。**量出来的**：18 篇真产出里
# **15 篇精确等于 0.0%**，另外三篇是 5.7% / 27.4% / 42.9%——
# 中间没有连续带，所以门槛落在哪都一样安全，取 3% 是为了让
# 「一篇长文里偶然有一对近似句」不值得单独占一轮。
RESTATED_RATIO = 0.03


def no_restated_paragraph(st: State) -> Verdict | None:
    """同一段里把一件事逐句说了两遍。

    **这是这个系统里所有查重都看不见的那一类**：模型把整节重写了一遍，
    新旧并排落在同一段内部，连空行都没有。段落级的三条
    （`find_repeats` 按 `\n\n`、`drop_already_written` 按段、
    `repeated_lists` 按清单块）一条都够不到它。

    判的是**字数占比**而不是「有几对」：一篇 3000 字里有两句重复，
    跟一篇 1822 字里 782 字是重复，不是一回事。
    """
    ratio = repeats.restated_ratio(st.content)
    if ratio < RESTATED_RATIO:
        return None
    dups = repeats.find_restated(st.content)
    if not dups:
        return None
    a, b = dups[0].a, dups[0].b
    return Verdict(
        pick_dimension(st, "non_repetition", "coherence", "style_fit"),
        f"同一段里把一件事说了两遍（这一篇有 {ratio:.0%} 的正文是段内重复）："
        f"「{a[:40]}」和「{b[:40]}」。**删掉其中一句**，"
        "留信息更完整的那一句，不要两句都留着改写。",
    )


def no_repeated_lists(st: State) -> Verdict | None:
    """同一组清单换个说法列了两遍。

    段落级查重（`drop_already_written`）看不见它：两段各自还有别的内容，difflib 被稀释到 0.4。
    读产出才发现的（第 596 轮）——一篇复盘里「测试场景、时间、硬件版本、异常表现、负责人、最终结论」
    这组清单出现了两次，中间隔着几百字，读起来是同一件事说了两遍。
    """
    dups = blockcheck.repeated_lists(st.content, st.fresh or "")
    if not dups:
        return None
    a, b = dups[0]
    return Verdict(
        pick_dimension(st, "non_repetition", "coherence", "style_fit"),
        f"同一组清单列了两遍：「{a[:40]}」和「{b[:40]}」。留下更完整的那一处，"
        "另一处改成一句话带过（「按上面那几项回填」），不要把同一组要素换个说法再写一次。",
    )
