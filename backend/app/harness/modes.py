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

from .checks import grounding_rules as grounding_check
from .checks import (charts_from_tools, citations_exist, citations_hold, heading_fits,
                     material_used, no_audit_voice, no_fake_charts,
                     no_placeholder, outline_intact, table_present, tail_clashes)
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
#
# 长循环那两条 harness 的维度以前在 adapter.py 里——那是「app 和 harness
# 的接缝」，装的却是**领域配置**。八组维度现在都在这一个文件。

# 这一维的判据改过一次，原因值得记下来。
#
# 原来写的是「同一个结论被换一种说法讲了不止一次 = 不足」，结果它把**结尾
# 重申核心结论**这种正常写法也当缺陷扣分。九批 2160 次实测，这一维稳在 1.3
# 左右下不来，判词永远是同一句「X 的结论在多个段落中反复出现」；而同一批
# 产出里段落两两最高相似度只有 **0.29**——一处字面重复都没有，通读下来结构
# 是完整的（引子→原因→方法→操作→价值）。**是判据在罚正常写法，不是文章差。**
#
# 所以把两件事分开：小节之间主题撞车（真缺陷，机械查重看不见，危害最大）
# 保留；开头点题、结尾收束时重申一次核心结论，明确算达标。
#
# 放宽判据有"为了刷分而降标准"的风险，这里的兜底是：真正的字面重复由确定性
# 手段拦（find_repeats 的 dup_hints、插入前的 drop_already_written），不依赖
# 这一维；这一维只负责它们看不见的语义撞车。
_NON_REPETITION = Dimension(
    "non_repetition",
    "**重点看小节之间有没有主题撞车**：两节标题不同、措辞也完全不同，但讲的"
    "是同一个主题（《订阅制的具体设计》与《订阅分层与用量计费的落地细节》），"
    "后一节只是把前一节展开重说——这算不足，而且是最难发现、危害最大的一种"
    "重复，机械查重查不出来，只能靠通读小节标题和各节实际覆盖的内容来判断。"
    "同一组事实、同一组边界条件在正文里被重复论证两遍，也算不足。"
    "\n**但下面这些是正常写法，不要扣分**：开头点题、结尾收束时重申一次核心"
    "结论（只要没有借机重新论证一遍）；同一个概念在不同小节里被当作前提引用；"
    "总述之后分述展开。判断标准是「这一段有没有推进」，不是「这个说法出现过"
    "几次」——一篇有引子、主体、收尾的文章，核心结论本来就会出现在两三处。"
    "\n达标：每一节都在推进，没有哪一节只是把另一节重说一遍。",
)

_FACTUAL_GROUNDING = Dimension(
    "factual_grounding",
    "只看「用到的地方对不对」，不看「用了多少」——"
    "达标：正文里凡是依赖知识库事实的陈述都跟事实一致，没有跟事实矛盾的"
    "说法，也没有编造知识库里根本没有的具体人名、日期、数字；"
    "不足：正文里有跟知识库事实明显矛盾的陈述，或者写了具体的人名/日期/"
    "数字但知识库里查无此事。"
    "**明确不算不足的情况**：检索到的事实没有被全部用上。检索是按关键词"
    "近似匹配的，命中的事实里经常有跟当前这段内容根本不相关的（真实例子："
    "写「硬件续航」命中了「Speaker E 问3月31号能否有APP可以对外」），"
    "不用它们是对的，不是缺口。续写那一步的指令本来就是「不相关的事实"
    "可以不用，不要为了显得有依据硬编牵强的类比」，这里不能反过来因为"
    "「没用完」而扣分——那会逼着往正文里塞不相关的内容，或者干脆编出"
    "知识库里没有的细节来凑数（真实踩过：因为这条扣分，下一轮正文里"
    "「引入了大量未在知识库中出现的具体日期与人物」）。",
)

_STYLE_FIT = Dimension(
    "style_fit",
    "达标：语气、结构、用词贴合用户的个人偏好；不足：明显违背个人偏好"
    "（比如偏好简洁但正文冗长啰嗦）。",
)

# 这一条是人工读真实产出读出来的缺口，不是照着别处抄的：真实质量采样里
# 有两篇被四个维度全打 2 分、判定 complete，但人一眼就能看出问题——
# 一篇正文中间夹了一个完整的结尾（读者以为文章结束了，下面又开始展开），
# 一篇小节编号是 1、2、4、3，还有二级标题夹在一堆三级标题中间。原来的
# 四个维度没有任何一条在管"这篇东西作为一个整体是不是自洽"，所以这些
# 一眼可见的硬伤全部被判满分。guidance 写成明确的检查清单，泛泛说
# "检查结构"实测没用。
_MATERIAL_USE = Dimension(
    "material_use",
    "只在【知识库事实】块里**确实给了材料**时才判这一项，没给材料就算达标。"
    "达标：正文里能看出用了这些材料——具体的项目、数字、人、决定被写进了"
    "正文，而不只是抽象地提了一下这个话题；"
    "不足：给了材料却写成了任何人都能写的通用内容（成本要考虑哪些项、"
    "远程协作要注意什么这类教科书分类），一条具体材料都没落到正文里。"
    "**这一条比其他所有维度都重要**：这是用户自己的笔记，通用常识写得"
    "再干净、再不重复、再自洽，价值也是零。",
)

_COHERENCE = Dimension(
    "coherence",
    "整篇作为一个成品是否自洽，逐条对着查，任意一条中招就是不足："
    "(1) 有没有出现不止一个结尾——某一段已经在做总结收束，后面却又接着"
    "展开新内容，读者会以为文章已经结束。"
    "**```mermaid 图不算新开的内容，接在收束附近不构成第二个结尾**——"
    "图是把正文已有关系换一种形式呈现，不是新展开一块内容，不要因为"
    "结尾附近有张图就判为二次收束（这是实测误判过的情况）；"
    "(2) 标题层级是否统一——有没有二级标题和三级标题混着乱用、同一层级"
    "的内容用了不同级别的标题；"
    "(3) 编号是否连贯——小节序号有没有跳号、错序（比如 1、2、4、3）；"
    "(4) 前后体例是否一致——有没有前半部分是纯段落、后半部分突然全是"
    "带标题的小节这种像两篇文章拼起来的痕迹；"
    "(5) 有没有自我拆台——正文某处的表述跟这篇东西自己主张的立场相互"
    "矛盾（比如通篇在批判某种说法，某一段自己又说了这种话）。",
)


def _note_dims(has_profile: bool, polish: bool = False) -> list[Dimension]:
    """note_harness.py：单篇笔记续写，有 spine（核心张力）/beats（结构
    节拍）可以对着打分。

    ``polish``：打磨模式**只修不写**，不许新增内容。这时候
    ``beat_coverage``（有没有把每条结构节拍都写出来）和 ``material_use``
    （有没有把检索到的材料写进正文）这两条都不适用——它们衡量的是"写了
    多少"，而打磨这一模式被明确禁止写。

    实测代价：一篇有重复标题的短笔记跑打磨，``beat_coverage`` 判 0（节拍
    确实没写），于是永远到不了 complete，跑满三轮撞 max_rounds，每轮还被
    "最弱是节拍覆盖"这条诊断推着去写它不许写的东西。**拿一个它无权改善的
    维度去打分，闭环就不可能收敛。**
    """
    dims = [
        Dimension(
            "spine_fidelity",
            "达标：正文紧扣核心张力（spine）展开；不足：正文偏离核心张力，"
            "散成流水账或者跟核心张力无关的罗列。",
        ),
        _NON_REPETITION,
        _FACTUAL_GROUNDING,
        _COHERENCE,
    ]
    if not polish:
        dims.insert(1, Dimension(
            "beat_coverage",
            "达标：每条结构节拍（beats）都有对应内容实质存在，不要求写到"
            "极致，只要求这个功能真的在正文里起作用；不足：有结构节拍完全"
            "没有对应内容。",
        ))
        dims.append(_MATERIAL_USE)
    if has_profile:
        dims.append(_STYLE_FIT)
    return dims


def _section_dims(has_profile: bool) -> list[Dimension]:
    """writing_plan.py：文件夹级分段续写，没有 spine/beats，只有这个
    分段自己的主题——对应的贴合度维度换成"是否紧扣分段主题、没有跑去写
    该由别的分段写的内容"。"""
    dims = [
        Dimension(
            "topic_fidelity",
            "达标：正文紧扣这个分段自己的主题展开，没有写到该由计划里其他"
            "分段覆盖的内容；不足：正文偏题，或者跟其他分段的主题明显"
            "重叠。",
        ),
        _NON_REPETITION,
        _FACTUAL_GROUNDING,
        _MATERIAL_USE,
        _COHERENCE,
    ]
    if has_profile:
        dims.append(_STYLE_FIT)
    return dims


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
    label="续写整篇",
    groups=("memory", "skill"),
    skill_scope="magic_tap",
    dims=(),                      # runtime-shaped; see for_run()
    checks=(no_placeholder, no_audit_voice, outline_intact, citations_hold,
            citations_exist, material_used, no_fake_charts, charts_from_tools),
    stop_when=(material_used_up, stalled, nothing_left_to_fix,
               pause_for_review),
    extra_mw=(Revise(), Repair(), Runtime(), Replan(), Compact(), Save()),
    max_rounds=8,
    context_keep_last=4000,
)

SECTION = Mode(
    key="section",
    label="分段写作",
    groups=("memory", "skill"),
    skill_scope="section_write",
    dims=(),                      # runtime-shaped; see for_run()
    checks=(no_placeholder, no_audit_voice, citations_hold, citations_exist, material_used,
            no_fake_charts, charts_from_tools),
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
    label="数据可视化",
    verb="在画",
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
    label="智能插图",
    verb="在画",
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
    label="生成表格",
    verb="在拼表",
    groups=("data", "table", "memory", "skill"),
    skill_scope="block_write",
    dims=TABLE_DIMS,
    checks=(table_present, heading_fits),
    max_rounds=3,
)

ANALYSIS = Mode(
    task=(
        '回答用户在提示词里问的那个数据问题。用 data 组的工具把数字算出来，**不要自己心算**。结论先给，再给支撑它的数字，最后说这个结论在什么条件下不成立。有对比价值时用 render_chart 配一张图。\n'),
    key="analysis",
    label="数据分析",
    verb="在算",
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
    label="按指令生成",
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
    label="改写选区",
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
        dims = _note_dims(has_profile, polish)
    elif mode.key == "section":
        dims = _section_dims(has_profile)
    else:
        return mode
    return dataclasses.replace(mode, dims=tuple(dims))
