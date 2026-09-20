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


def _started_with(st: State) -> str:
    """这次跑开跑时正文里已经有的字（`loop.py` 在 `before_run` 之后存的）。

    判据的量程一律绑在这上面，不绑 `st.fresh`——理由写在
    `blockcheck.repeated_lists` 的 docstring 和 `harness-framework.md` §20④ 里。
    """
    return str(st.bag.get("content_at_start") or "")

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
        pick_dimension(st, "table_validity"),
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
        pick_dimension(st, "table_validity"),
        "这张表的列数对不上：有的行比表头多一格或少一格，渲染出来会错位。"
        "**重新调用 render_table**（它按 columns / rows 拼，列数不会错），"
        "不要手动补竖线——空着的格子留空就行，别为了对齐去编一个值。",
    )


def heading_fits(st: State) -> Verdict | None:
    """Headings must sit *below* the surrounding section, not beside it."""
    gap = blockcheck.heading_gap(st.before, st.content)
    if not gap:
        return None
    # P59 ②：这一支原来动了正文一个字不说。措辞要说清「下沉了几级」，
    # 而那个级数只有 `_sink_headings` 算得出来——**所以把它抽成 `_sink_delta`，
    # 两边读同一个数**，不在这儿照着重写一份（重写一份就有了两套口径，
    # 说的话和做的事会各走各的）。
    delta = _sink_delta(st.before, st.content)
    return Verdict(
        pick_dimension(st, "fits_context"), gap,
        fix=lambda text: _sink_headings(st.before, text),
        fix_note=(f"把这一段的标题整体下沉了 {delta} 级，好让它排在上面那个小节下面"
                  "——只动了 `#` 的个数，正文一个字没改"),
    )


def _sink_delta(before: str, block: str) -> int:
    """要把 ``block`` 里的标题整体下沉几级（0 = 不用动）。

    抽出来的理由（P59 ②）：`heading_fits` 的 `fix_note` 要说「下沉了几级」，
    而这个数原来只活在 `_sink_headings` 的函数体里。**说的话和做的事得读同一个数**。
    """
    prev = re.findall(r"^(#{1,6})\s", before or "", re.M)
    needed = (len(prev[-1]) if prev else 1) + 1
    mine = re.findall(r"^(#{1,6})\s", block or "", re.M)
    if not mine:
        return 0
    return max(0, needed - min(len(h) for h in mine))


def _sink_headings(before: str, block: str) -> str:
    """Push every heading down until the shallowest is one level below the
    nearest heading above the cursor. Only ``#`` counts change."""
    delta = _sink_delta(before, block)
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
        pick_dimension(st, "fits_context"),
        f"这一段自己写了一个收尾小节（{clashing[0]!r}），而下面的正文已经有收尾了。"
        "去掉——插进笔记里的是一段话，不是一篇独立的报告。",
        fix=lambda text: _drop_tail_sections(text),
        # P59 ②：删的是**整节**（标题连同底下的正文），不是一行标题——
        # 那是这一处最该说清楚的一件事，不说的话用户只会看见一段话凭空少了。
        fix_note=(f"把这一段自己写的收尾小节「{clashing[0][:24]}」连标题带正文整节删掉了"
                  "（下面的正文已经有收尾了）"),
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
        pick_dimension(st, "fits_context"),
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

    dups = same_sources_twice(st.content, _started_with(st))
    if not dups:
        return None
    a, b = dups[0]
    return Verdict(
        pick_dimension(st, "non_repetition", "style_fit"),
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

    ## 这一条**故意没有量程**（批 25 量完之后的决定，不是漏）

    同一批把 `no_repeated_lists` / `no_fake_charts` 的量程都收到了
    `content_at_start` 上，**这一条不收**，三条依据：

    1. **逐条读下来一处误伤都没有。** 18 篇 `origin=user` 上开火 1 篇
       （`06647b9c2031`），读出来是「…上周发生变更需改良包装。下一轮 10 台到货为
       6 月 15 日… KLR 包装，现需求上周发生变更需改良包装。下一轮 10 台到货为…装。
       下一轮 10 台到货为…」——**从词中间接上的**，前面还顶着八个空行，
       36% 的正文是段内重复。那不是人写出来的形状。`script` 那 2 篇同一个形状。
    2. **它是唯一够得着这种损伤的判据**，而那条损伤**上一次跑留下来了**：
       `middleware/revise.py` 的锚点在整篇正文里找，所以修订那条线**改得掉**
       上一次跑写进去的重复（批 14 反向实拍过：它连用户自己的 1326 字都删得动）。
       收了量程，这一篇就再也没有人报了。
    3. **`RESTATED_RATIO` 是在「整篇」这个分母上量出来的**（18 篇真产出，15 篇
       精确 0.0%）。换成「只数这次跑写的那部分」，分母变了，3% 这个数在新口径上
       **一次都没量过**——§20④：收窄哪一侧都要有据。

    所以留着，并且 `tests/test_criteria_drift.py` 里有一条闸把「它开跑前口径下
    还会开火」这件事钉成断言：下一个人照着旁边两条顺手给它加量程，那条闸会先说话。
    """
    ratio = repeats.restated_ratio(st.content)
    if ratio < RESTATED_RATIO:
        return None
    dups = repeats.find_restated(st.content)
    if not dups:
        return None
    a, b = dups[0].a, dups[0].b
    return Verdict(
        pick_dimension(st, "non_repetition", "style_fit"),
        f"同一段里把一件事说了两遍（这一篇有 {ratio:.0%} 的正文是段内重复）："
        f"「{a[:40]}」和「{b[:40]}」。**删掉其中一句**，"
        "留信息更完整的那一句，不要两句都留着改写。",
    )


def no_repeated_lists(st: State) -> Verdict | None:
    """同一组清单换个说法列了两遍。

    段落级查重（`drop_already_written`）看不见它：两段各自还有别的内容，difflib 被稀释到 0.4。
    读产出才发现的（第 596 轮）——一篇复盘里「测试场景、时间、硬件版本、异常表现、负责人、最终结论」
    这组清单出现了两次，中间隔着几百字，读起来是同一件事说了两遍。

    **量程收在「开跑时有没有」上（批 25）**。逐条读过 18 篇 `origin=user` 上的
    3 处命中：2 处是用户自己写的（`92d07b760f1e` 这篇一次 harness 都没跑过，
    `e78306202d78` 已经还原回 09-02 的用户原文），1 处是上一次跑留下的机器损伤
    （`06647b9c2031`）。**误伤 2/3**，而这条判据要的修法是「留下更完整的那一处，
    另一处改成一句话带过」——一次删除，落在用户自己的正文上。
    那条线**够得着**：`middleware/revise.py` 对锚点的唯一限制是「在 `st.content`
    里找得到」，而 `st.content` 开跑时就等于整篇笔记；批 14 实拍过一次后果，
    一篇真实笔记被删掉 1326 字。所以这里收，不是因为改不动，**恰恰是因为改得动**。

    被放掉的那一半由谁接住：同一篇 `06647b9c2031` 上 `no_restated_paragraph`
    照样开火（那一条**故意不收量程**，理由写在它自己的 docstring 里）——
    机器损伤那一篇没有掉出网，掉出去的只有两篇用户原文。
    """
    dups = blockcheck.repeated_lists(st.content, _started_with(st))
    if not dups:
        return None
    a, b = dups[0]
    return Verdict(
        pick_dimension(st, "non_repetition", "style_fit"),
        f"同一组清单列了两遍：「{a[:40]}」和「{b[:40]}」。留下更完整的那一处，"
        "另一处改成一句话带过（「按上面那几项回填」），不要把同一组要素换个说法再写一次。",
    )


# 两段几乎是同一段。**用现成的 `find_repeats`**（difflib，`Repeats` 中间件本来就每轮在算，
# 拿去喂打分——但没有任何一条判据读它）。门槛在真库 482 篇上量过（`p24/m4_para.py`）：
# 0.6 那档命中 7 篇，逐条读下来 0.688 是两个不同的小标题、0.810 是两行光秃秃的编号，
# 都不是重复写；0.85 以上 5 篇，5 篇全是真损伤（两段一字不差 / 第 10 周 vs 第 100 周 /
# P22 那对 0.931）。取 **0.85**，下面最近的一档是 0.810，留 0.04。
PARA_ECHO_RATIO = 0.85
# 光秃秃的编号段不算（`df3b4f7e` 那 0.810 就是两行编号）：去掉编号之后还得有这么多字。
PARA_ECHO_MIN_BODY = 40


def no_echoed_text(st: State) -> Verdict | None:
    """这次跑把同一串字**逐字**写了两遍。三种形状，先命中的先说。

    P22 复测里重复从 10 处涨到 12 处，是那一轮唯一变差的一格。逐条读完那 12 处，
    其中 3 处是逐字的（形状见 `blockcheck` 里那段注释），另外 9 处是「同一件事换说法
    写 4–5 段」——后者**量过之后决定不做**，段间 Jaccard 跟正常承接段没有缺口。

    (a) 句内回声 和 (b) 同段重编号 **自己动手修**（P23 立的 `fix_done` 形状）：
    删的是一段一字不差的复制，留下第一次，是确定性的，不需要语义判断；
    而 P22 实拍里 `no_repeated_lists` 连着两轮点名同一处重复，模型一次都没照做——
    能代码修的就别指望下一轮。
    (c) 两段几乎相同**只报不修**：留哪一段是判断题（两段的尾巴不一样）。

    三种形状的量程都绑在 `content_at_start` 上，理由跟 `no_repeated_lists` 一样：
    删除动作够得着用户自己的正文，批 14 实拍删过 1326 字。
    """
    before = _started_with(st)

    hit = blockcheck.echoed_sentence(st.content, before)
    if hit:
        echo, sent = hit
        return Verdict(
            pick_dimension(st, "non_repetition", "style_fit"),
            f"同一句话里把「{echo[:40]}」抄了两遍：「{sent[:60]}…」。删掉第二遍。",
            fix=lambda text, e=echo: blockcheck.drop_echo(text, e),
            fix_done=lambda text, e=echo: not _echo_still_there(text, e),
            fix_note=f"把重复抄了一遍的「{echo[:40]}」删掉了一份（原句留着）",
        )

    cite = blockcheck.repeated_citation(st.content, before)
    if cite:
        fid, para = cite
        return Verdict(
            pick_dimension(st, "non_repetition", "factual_grounding"),
            f"同一段里把 [{fid}] 贴了两次：「{para[:50]}…」。一条依据在一段里标一次就够。",
            fix=lambda text, f=fid: blockcheck.drop_repeated_citation(text, f),
            fix_done=lambda text, f=fid: (blockcheck.repeated_citation(text, before) or ("",))[0] != f,
            fix_note=f"把同一段里贴了两次的 [{fid}] 去掉了一个（留下第一个）",
        )

    for hint in repeats.find_repeats(st.content):
        if hint.similarity < PARA_ECHO_RATIO:
            continue
        if hint.a in before and hint.b in before:
            continue
        if min(len(_bare(hint.a)), len(_bare(hint.b))) < PARA_ECHO_MIN_BODY:
            continue
        return Verdict(
            pick_dimension(st, "non_repetition", "style_fit"),
            f"这两段几乎是同一段（逐字重合 {hint.similarity:.0%}）：「{hint.a[:45]}…」和"
            f"「{hint.b[:45]}…」。删掉其中一段，留信息更完整的那一段——"
            "换个开头把同一段话再写一遍，读者读到的是同一件事说了两遍。",
        )
    return None


_BARE = re.compile(r"\[[0-9A-Za-z_-]+-\d+-\d+F\d+\]|\[[^\]]{0,40}\]\(note://[^)]+\)|\s+")


def _bare(para: str) -> str:
    """去掉引用编号和空白之后还剩多少字——判「这一段是不是只有编号」。"""
    return _BARE.sub("", para or "")


def _echo_still_there(text: str, echo: str) -> bool:
    pat = re.compile(r"\s*".join(re.escape(ch) for ch in echo))
    return len(pat.findall(text or "")) >= 2
