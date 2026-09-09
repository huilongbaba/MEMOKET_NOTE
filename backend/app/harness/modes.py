"""Every feature's configuration, in one place.

Today these live in two: ``compose_block.MODES`` (six inline dicts) and
``harness_adapter.note_dimensions()`` / ``section_dimensions()``. Splitting
them meant "where do I add a dimension" had two answers depending on which
harness you were touching.

A Mode is pure data. Skills layer on top at runtime by producing a modified
copy, so nothing here may depend on anything only code can supply.
"""

from __future__ import annotations

import dataclasses

from .types import Dimension

from . import adapter as harness_adapter
from .checks import grounding_rules as grounding_check
from .checks import (charts_from_tools, citations_hold, heading_fits,
                     material_used, no_audit_voice, no_fake_charts,
                     no_placeholder, outline_intact, tail_clashes)
from .middleware import Compact, Repair, Replan, Runtime, Save
from .middleware.revise import Revise
from .state import State
from .types import Mode

# --------------------------------------------------------------- stops ---
# Beyond the three the loop always applies (complete / blocked / no
# progress), long-form runs need to notice they've run dry.


def material_used_up(st: State) -> str | None:
    """Stop when there is nothing new left to say.

    Without this, a run keeps going because a *coverage* dimension demands
    more sections while the material only supports one -- and the model
    obliges by restating the same facts from a new angle. Measured: the one
    harness lacking this check lost 0.278 per round on average, and what fell
    was ``non_repetition`` specifically, while ``factual_grounding`` held
    steady. That is the signature of "same material, said again".

    **The existing threshold barely ever fires** and this is knowingly kept
    as-is for now: "two consecutive rounds with zero new facts" almost never
    happens, because retrieval keeps returning fact rows that differ in
    wording while saying the same thing. Porting it unchanged would be
    cargo-culting; it needs a real criterion, and until then it is a
    formality. Written down here rather than quietly omitted, so nobody
    assumes there's a working guard.
    """
    if st.round < 2 or st.bag.get("polish"):
        # Polish adds nothing, so "the material ran out" is not a reason for
        # it to stop -- there was never any material being consumed.
        return None
    if st.bag.get("dry_rounds", 0) >= 2:
        return "material_used_up"
    if grounding_check.material_exhausted(st.content, st.facts):
        return "material_used_up"
    return None


# Two rounds that change nothing. The old harness used the same number as
# the fallback for "scoring failed": an occasional failure recovers next
# round, and repeated failure is indistinguishable from being stuck, so one
# safety net serves both rather than inventing a second policy for it.
STALL_ROUNDS = 2


def stalled(st: State) -> str | None:
    """Stop when rounds stop changing anything."""
    return "stalled" if st.bag.get("no_change_rounds", 0) >= STALL_ROUNDS else None


def pause_for_review(st: State) -> str | None:
    """Stop after each round and wait for the user.

    Without this the run keeps writing while the user is still reading, and
    every acceptance they make gets overwritten by the next round -- the
    editor's per-hunk accept/reject never reached the backend at all, so on
    an eight-round run "accept this one paragraph" was decided seven times
    and honoured zero.

    It is an ordinary stop condition, which is the point: the loop needs no
    concept of pausing. Resuming is loading the snapshot and running again
    with a higher round number.
    """
    return "awaiting_review" if st.mode.review_each_round else None


def nothing_left_to_fix(st: State) -> str | None:
    """Polish only repairs. When a round applies no revision, the next one
    would propose the same nothing -- there is no second mechanism that could
    change the outcome."""
    if not st.bag.get("polish"):
        return None
    if st.round >= 1 and not st.bag.get("revisions_applied"):
        return "no_more_changes"
    return None


# ---------------------------------------------------------- dimensions ---
# The wording is what the scorer reads, so these read as sentences about
# what good and bad look like, not as labels. Anything a rule can decide
# reliably is NOT here -- it belongs in checks/, because the scorer and the
# writer are the same local model and share the same blind spots.

_NUMBERS_FROM_TOOLS = Dimension(
    "numbers_from_tools",
    "Meets the bar: every statistic in the text (mean, median, extreme, "
    "correlation, share) can be traced to a tool result. Insufficient: a "
    "number appears that no tool computed.")

_HONEST_CAVEATS = Dimension(
    "honest_caveats",
    "Meets the bar: small samples, heavy gaps and unreliable correlations are "
    "stated plainly. Insufficient: a correlation over three rows is presented "
    "as a finding.")

_HAS_CHARTS = Dimension(
    "has_charts",
    "The body should be charts, but every chart must show something.\n"
    "Insufficient at both extremes: (a) prose and numbers only, no chart, or "
    "one token chart at the end; (b) a pile of charts that say nothing -- a "
    "3:3 share pie, a two-bar histogram over six points. Real output once had "
    "seven charts of which one was informative. More charts is not better.\n"
    "Meets the bar: each chart corresponds to a specific finding, and the "
    "sentence beside it says what the shape means rather than restating the "
    "numbers.")

_NO_DUP_CHARTS = Dimension(
    "no_duplicate_charts",
    "Meets the bar: each chart looks at something different. Insufficient: "
    "the same data drawn twice -- a different title or a different chart type "
    "both count. Real output drew one set of market shares as both bars and a "
    "pie while the text itself noted the numbers exceed 100% so a pie doesn't "
    "fit. Pick one form per dataset and stay with it.")

_COVERS_THE_DATA = Dimension(
    "covers_the_data",
    "Every comparable group in the sentence near the cursor should be drawn, "
    "and drawn whole.\n"
    "Insufficient (all observed): the sentence is about vendor A at 38% with "
    "B/C/D in parentheses, and the chart has only the parenthetical ones -- "
    "**the subject of the sentence is missing**; three groups mentioned, two "
    "drawn.\n"
    "This checks for **omissions, not exhaustiveness**: a table can be sliced "
    "by channel, by month, per capita; drawing every slicing is endless. As "
    "long as the slicings you chose are each complete, that meets the bar -- "
    "do not mark it down for a slicing nobody drew. (Being strict here fought "
    "directly with fits_context for three rounds in real runs.)")

_FITS_CONTEXT = Dimension(
    "fits_context",
    "It should read like a passage that was always in this note, not a report "
    "dropped into it.\n"
    "Meets the bar: headings one level below the nearest heading above; **few "
    "headings** (one or two, not one per chart); each chart gets a sentence or "
    "two; tone and conventions match the surrounding text.\n"
    "This dimension is about headings and register, **not chart count** -- the "
    "body of this mode is charts, two or three is normal. Whether a chart "
    "deserves to exist is has_charts' problem.")

_ACTIONABLE = Dimension(
    "actionable",
    "Meets the bar: it says what to look at next. Insufficient: statistics "
    "with no direction.")

EDA_DIMS = (_NUMBERS_FROM_TOOLS, _HONEST_CAVEATS, _HAS_CHARTS, _NO_DUP_CHARTS,
            _COVERS_THE_DATA, _FITS_CONTEXT, _ACTIONABLE)

CHART_DIMS = (
    Dimension("chart_validity",
              "Meets the bar: the chart came from render_chart (a complete "
              "```mermaid block) or render_image (a markdown image reference). "
              "Insufficient: hand-written mermaid, a truncated block, or a "
              "reference to an image that doesn't exist."),
    Dimension("data_grounding",
              "Meets the bar: every number in the chart traces to a table in "
              "the note or to a tool result. Insufficient: a number with no "
              "source. Not applicable when the image is illustrative."),
    Dimension("right_kind",
              "Meets the bar: numbers and processes go through render_chart; "
              "render_image is for abstract concepts. Insufficient: using "
              "text-to-image for what should be exact -- the numbers in it are "
              "invented and can't be edited."),
    _FITS_CONTEXT,
)

TABLE_DIMS = (
    Dimension("table_validity",
              "Meets the bar: a complete markdown table whose header and rows "
              "have matching column counts."),
    Dimension("data_grounding",
              "Meets the bar: every cell traces to the note, a table in it, or "
              "a retrieved fact. Insufficient: invented data. An unknown should "
              "say so, not be filled in."),
    _FITS_CONTEXT,
)

ANALYSIS_DIMS = (
    Dimension("answers_the_question",
              "Meets the bar: it answers the question that was asked. "
              "Insufficient: it talks around it."),
    _NUMBERS_FROM_TOOLS,
    Dimension("states_limits",
              "Meets the bar: it says what the conclusion depends on and when "
              "it stops holding. Insufficient: a small-sample result stated as "
              "settled."),
    # 这两条是被一条断言逼出来的：analysis 挂着图表检查和标题检查，dims 里
    # 却没有对应的轴，于是 check 命中时打翻的是一个这个模式根本没有的维度。
    # 它的 task 明说「有对比价值时用 render_chart 配一张图」，而且它是插进
    # 笔记里的一块——两条本来就该有。
    Dimension("chart_validity",
              "Meets the bar: any chart here came from render_chart (a "
              "complete ```mermaid block). Insufficient: a chart described in "
              "prose, or hand-written mermaid imitating tool output. Drawing "
              "nothing is fine -- this mode's body is an answer, not charts."),
    _FITS_CONTEXT,
)

_REPLACES_CLEANLY = Dimension(
    "replaces_cleanly",
    "Meets the bar: the output can be dropped in over the selected passage "
    "and still read continuously, in the same conventions. Insufficient: it "
    "carries a lead-in like \"here is the revision\", or it copies back text "
    "from outside the selection.")

_FOLLOWS_PROMPT = Dimension(
    "follows_prompt",
    "Meets the bar: it does what the instruction asked. Insufficient: it did "
    "something else, or only half.")

_NO_FABRICATION = Dimension(
    "no_fabrication",
    "Meets the bar: anything about the user's own projects, numbers or "
    "decisions comes from retrieved facts or from the note. Insufficient: "
    "invented names, dates or figures.")

# The two prompt-driven modes differ in one dimension, and the difference is
# the whole point: PROMPT writes at a cursor, so it is judged on fitting the
# surrounding text; CUSTOM overwrites a selection, so it is judged on dropping
# in cleanly over it.
PROMPT_DIMS = (_FOLLOWS_PROMPT, _FITS_CONTEXT, _NO_FABRICATION)
CUSTOM_DIMS = (_FOLLOWS_PROMPT, _REPLACES_CLEANLY, _NO_FABRICATION)



# --------------------------------------------------------------- modes ---
# Eight features. Everything that makes them different is here; the loop,
# the middleware chain and the event contract are identical for all of them.
#
# ``task`` is elided in this file for readability -- the real prompts move
# over from compose_block.MODES during migration. What matters here is the
# shape: which tools, which dimensions, which checks, how many rounds.

NOTE = Mode(
    key="note",
    label="Continue a whole note",
    groups=("memory", "skill"),
    skill_scope="magic_tap",
    dims=(),                      # runtime-shaped; see for_run()
    checks=(no_placeholder, no_audit_voice, outline_intact, citations_hold,
            material_used),
    stop_when=(material_used_up, stalled, nothing_left_to_fix,
               pause_for_review),
    extra_mw=(Revise(), Repair(), Runtime(), Replan(), Compact(), Save()),
    max_rounds=8,
    context_keep_last=4000,
)

SECTION = Mode(
    key="section",
    label="Folder-level section",
    groups=("memory", "skill"),
    skill_scope="section_write",
    dims=(),                      # runtime-shaped; see for_run()
    checks=(no_placeholder, no_audit_voice, citations_hold, material_used),
    stop_when=(material_used_up, pause_for_review),
    extra_mw=(Revise(), Repair(), Compact(), Save()),
    # Measured cap, not a completion criterion: a section that keeps
    # scoring 'continue' must not hold the whole plan hostage.
    max_rounds=4,
)

# The six block modes. They share one set of Hooks -- only the fields below
# differ. Note the tool groups: render_table moves out of ``chart`` into its
# own group, so drawing modes stop being handed a table builder and the table
# mode stops being handed three chart builders.

EDA = Mode(
    task=(
        '对笔记里的数据做一次探索性分析。\n'
        '**EDA 的主体是图，不是文字。** 光给一串统计量等于没做——分布长什么样、哪个类目占多少、谁跟谁一起变，这些是看出来的不是读出来的。\n'
        '怎么做：\n'
        '1. **先 numbers_near_cursor 看光标跟前那段话里写着什么数**——用户在哪儿\n'
        '   触发的，想可视化的就是他跟前那段。再 list_tables 看有没有表：\n'
        '   **表标了离光标多远，写着「不在光标附近」的就别用**——那多半是笔记\n'
        '   别处的东西，跟用户现在看的没关系。实测出现过分析一万字外的项目进度表。\n'
        '   两边都有内容时以近的为准；用户点名了某张表就用那张。\n'
        '   光标附近的文字里往往写着数字\n'
        '   （「昇腾 38%，浪潮 22.4%、中科光 14.1%、寒武纪 43%、沐曦 1.79」），\n'
        '   把**整组**读出来用 chart_from_text 画——**包括句子的主角**：\n'
        '   上面那句讲的是昇腾，昇腾的 38% 必须在图里，不能只画括号里那几家。\n'
        '   一段话里有几组数就画几张（份额一张、规模一张…），不要只挑一组\n'
        '   数值会拿去跟原文核对，抄错会被拒绝——只用原文里真的写着的数\n'
        '2. 有表格时 describe_table 拿每列的画像\n'
        '3. **每张图都要能看出点什么，不是每列都画一张。** chart_column 会\n'
        '   直接拒绝没信息量的图（数据点太少的直方图、每个取值出现次数都一样\n'
        '   的占比图），被拒了就按它的提示换个画法，不要硬凑\n'
        '4. 有分组关系的用 aggregate_table 算完，再 render_chart 画对比（bar）；有时间顺序的画 line\n'
        '5. 怀疑两列相关就 correlate_columns，**同时把 n 说出来**\n'
        '每张图配一到两句话，说这张图看出了什么——不是复述图里的数字，是说这个形状意味着什么。最后给「接下来值得看什么」。\n'
        '**所有数字都来自工具返回，不要自己算，也不要自己写 mermaid 语法。**\n'),
    key="eda",
    label="Data visualisation",
    groups=("data", "chart", "memory", "skill"),
    focus_groups=("chart",),
    skill_scope="block_write",
    dims=EDA_DIMS,
    checks=(no_fake_charts, charts_from_tools, heading_fits, tail_clashes),
    max_rounds=3,
)

CHART = Mode(
    task=(
        '为这篇笔记的当前位置配一张图。**先判断该画哪一类**：\n'
        '· 有具体数字或步骤依赖 → 用 render_chart（占比用 pie、分类对比用 bar、随时间变化用 line、步骤依赖用 flow）。画出来精确、可编辑、跟着主题变色，**不要自己写 mermaid 语法**。\n'
        '· 是抽象概念、场景示意、需要视觉表现力的配图 → 用 render_image 文生图。这一次调用要几十秒，只在确实需要「画面」而不是「数据」的时候用。\n'
        '图前面用一句话说明它在讲什么。\n'),
    key="chart",
    label="Illustrate",
    groups=("data", "chart", "image", "memory", "skill"),
    skill_scope="block_write",
    dims=CHART_DIMS,
    checks=(no_fake_charts, charts_from_tools, heading_fits),
    max_rounds=3,
)

TABLE = Mode(
    task=(
        '为当前位置整理一张表格。**必须调用 render_table 生成表格**。先想清楚这张表的每一行代表什么、每一列是什么，再填数据。表前面用一句话说明它整理的是什么。\n'),
    key="table",
    label="Build a table",
    groups=("data", "table", "memory", "skill"),
    skill_scope="block_write",
    dims=TABLE_DIMS,
    checks=(heading_fits,),
    max_rounds=3,
)

ANALYSIS = Mode(
    task=(
        '回答用户在提示词里问的那个数据问题。用 data 组的工具把数字算出来，**不要自己心算**。结论先给，再给支撑它的数字，最后说这个结论在什么条件下不成立。有对比价值时用 render_chart 配一张图。\n'),
    key="analysis",
    label="Analyse the data",
    groups=("data", "chart", "memory", "skill"),
    focus_groups=("chart",),
    skill_scope="block_write",
    dims=ANALYSIS_DIMS,
    checks=(no_fake_charts, charts_from_tools, heading_fits),
    max_rounds=3,
)

PROMPT = Mode(
    task=(
        '按用户的提示词，在当前位置写一段内容。需要用户自己的事实时，用 memory 组的工具去查知识库。\n'),
    key="prompt",
    label="Write from an instruction",
    groups=("memory", "skill"),
    skill_scope="block_prompt",
    dims=PROMPT_DIMS,
    checks=(no_placeholder, heading_fits),
    max_rounds=3,
)

# CUSTOM replaces a selection; PROMPT inserts at a cursor. That is why they
# do not share a dimension list: only one of them can be judged on whether the
# output drops in cleanly over what it replaces.
CUSTOM = Mode(
    task=(
        '用户选中了一段文字，按他的提示词处理这一段。**输出的是用来替换这一段的新内容**——不要重复选中之外的正文，不要写「好的」「修改后：」这类话。需要用户自己的事实时，用 memory 组的工具去查知识库。\n'),
    key="custom",
    label="Rework the selection",
    groups=("memory", "skill"),
    skill_scope="block_prompt",
    dims=CUSTOM_DIMS,
    checks=(no_placeholder,),
    max_rounds=3,
)

BLOCK: dict[str, Mode] = {m.key: m for m in (EDA, CHART, TABLE, ANALYSIS,
                                             PROMPT, CUSTOM)}
ALL: tuple[Mode, ...] = (NOTE, SECTION, *BLOCK.values())


# ------------------------------------------------------------ runtime ---


def for_run(mode: Mode, *, has_profile: bool = False,
            polish: bool = False) -> Mode:
    """Return ``mode`` with the dimensions this particular run can act on.

    Most of a Mode is decided when the feature is written. Two of the
    long-form dimensions are not, because they depend on facts only known at
    call time, and getting this wrong does not merely score badly -- it stops
    the loop converging at all:

      * ``style_fit`` needs a style profile to compare against. With no
        profile there is nothing to be faithful *to*, so the dimension can
        never be satisfied and the run burns every round chasing it.
      * ``beat_coverage`` and ``material_use`` both measure *how much got
        written*. Polish mode is forbidden to write. Measured on a short note
        with a duplicated heading: beat_coverage scored 0 every round (the
        beats genuinely were not written), the run never reached complete,
        hit max_rounds, and each round's steer pushed it towards writing the
        very thing the mode prohibits.

    The rule both cases share: **never score a run on a dimension it has no
    power to improve.** Modes with fixed dimensions pass through untouched.
    """
    if mode.key == "note":
        dims = harness_adapter.note_dimensions(has_profile, polish)
    elif mode.key == "section":
        dims = harness_adapter.section_dimensions(has_profile)
    else:
        return mode
    return dataclasses.replace(mode, dims=tuple(dims))
