"""Chart checks.

The design line these enforce: **the model decides what to draw, code
produces the numbers and the mermaid**. Left to itself the model invents
averages and writes mermaid that doesn't render -- both observed.
"""

from __future__ import annotations

from . import blockcheck
from ..state import State
from ..types import Verdict
from .pick import pick_dimension


def no_fake_charts(st: State) -> Verdict | None:
    """Charts described in prose instead of drawn.

    Real output: ``[bar chart: clicks by channel  Kickstarter: 12700 ...]``
    and ``[scatter: impressions vs orders, n=6, r=0.9902]``. The second is
    worse -- mermaid has no scatter plot, so that chart could never exist.
    The scorer gave this ``has_charts = 2``.
    """
    hits = blockcheck.fake_charts(st.content)
    if not hits:
        # 另一种"用文字画图"：把一条流程写成箭头链（第 592 轮，用户实拍的那段里就有）
        flows = blockcheck.text_flow(st.content)
        if flows:
            return Verdict(
                pick_dimension(st, "has_charts", "chart_validity", "coherence"),
                f"这条流程是用箭头串在正文里的，不是一张图：{'; '.join(flows)}。"
                # 点名的工具要真能画流程图。`chart_from_text` 只会饼 / 柱 / 折线，
                # 画不了 flowchart——指着一个做不到的工具，模型只能手写 mermaid，
                # 然后被下一条判据拦掉（第 606 轮真跑里来回了三轮）。
                "调 render_chart（kind=flow，labels 就是这几步，不用给 values），"
                "把返回的代码块原样贴进来；"
                "正文里留一句话说明这张图在讲什么就够，不用再把每一步重列一遍。",
            )
        return None
    return Verdict(
        pick_dimension(st, "has_charts", "chart_validity", "coherence"),
        f"这一轮没有真的画图，只是用文字描述了图：{'; '.join(hits)}。"
        "要画就调 chart_column / render_chart / chart_from_text，把它们返回的 ```mermaid 块"
        "原样贴进来——那段代码是验证过能渲染的。另外 mermaid 没有散点图：两列的关系"
        "写成相关系数，或者画成柱/折线图的两个系列。",
    )


def charts_from_tools(st: State) -> Verdict | None:
    """Mermaid that a tool did not produce.

    The model learned to route around ``no_fake_charts`` by hand-writing
    mermaid that mimics tool output -- the numbers were even correct, but the
    syntax was its own invention (``y-axis "impressions" 0 --> 260000``,
    a range ``render_chart`` never emits because getting it wrong turns the
    whole chart into an error message).

    So the test is not "does it look right" but **"is it byte-for-byte what a
    tool returned"**. Correct numbers don't make a chart render, and don't
    guarantee the next one won't quietly change a digit.
    """
    # 笔记原来就有的图不算这一轮手写的。`st.charts` 只记**这一次跑**里工具
    # 画过的，于是用户自己画的、或上一次跑留下的 mermaid 每一轮都会被判成
    # 「模型手写的」——第 604 轮真跑实拍：两张语法完全正确的流程图就是这么
    # 被修订那一步整个删掉的，删完下一轮又报「这条流程是用箭头串在正文里的，
    # 不是一张图」，删图和要图来回打架。判据只该管这次跑写出来的东西。
    allowed = st.charts + blockcheck.mermaid_blocks(st.bag.get("content_at_start") or "")
    bad = blockcheck.unauthorized_charts(st.content, allowed)
    if not bad:
        return None
    return Verdict(
        pick_dimension(st, "has_charts", "chart_validity", "coherence"),
        f"这里有 {len(bad)} 张 mermaid 图不是工具画的（{'; '.join(bad)}），是手写的、模仿工具"
        "输出。手写的 mermaid 没验证过，一处语法不对（比如 y 轴范围）整张图就变成一段"
        "报错。画什么由你定，**代码必须是工具原样返回的**；工具没画出你要的，"
        "就在下一轮取材料那一步再调一次 render_chart（写正文这一步没有工具可用）。"
        "——只有最简流程图例外：`graph TD` / `flowchart LR` 加几行 `A[甲] --> B[乙]`，"
        "那一种自己写没问题，上面这几张不是那一种。",
    )


# ------------------------------------------------------- readability 档 ---
#
# VisEval（IEEE VIS 2024）把图表评测分三档：validity / legality / **readability**。
# 上面两条 check 是 validity 档（图是不是真的、是不是工具产出的），
# `check-mermaid-grammar.mts` 那个门禁是 legality 档的一部分——
# **readability 档在批 16 之前一条都没有**（计划 5.3 / [IND] §2）。
#
# 挑的是「能算的」那几条，而且每一条都对应一个**我们自己的工具真的会吐出来**
# 的形状——不是假想的坏图：
#
# · 标签被截断：`blocks.safe_label` 超长就加「…」。blocks.py 里那段注释记着
#   实拍：「三月Kickstarter」被截成「三月Kickstarte…」，读者认不出是哪个渠道。
# · 图例数不上：`mermaid_xy` 多系列时把系列名拼成「甲 / 乙」写进 y 轴，
#   **而那一整串还要过一次 `safe_label(30)`**——名字一长就被切掉，
#   于是图上有两条柱、读者只看得到一个名字。
# · 类目太多：`mermaid_pie` 自己在 8 项以上就并「其他」（"十几个扇区谁也看不出
#   比例"是它的原话）；`mermaid_xy` 上限 24，而 8 类以上它就把标签宽度从
#   16 字压到 10 字——**我们自己的代码两处独立地把线画在 8**。
#
# 阈值**没有在真实产出上量过**，而且这一批量不了：批 11/13 记着图表那一组
# 只有 1 篇真实用户语料带图。所以 xy 那一档取的是 12（8 和 24 中间），
# **有意取宽**——这一条报错的代价小（"合并几项或拆成两张"不删内容），
# 但宁可漏也不要每张十格的图都拦一次。
MAX_PIE_SLICES = 8
MAX_XY_CATEGORIES = 12
MAX_FLOW_NODES = 14


def chart_readable(st: State) -> Verdict | None:
    """图画出来读不读得出来（计划 5.3 / VisEval 的 readability 档）。

    只看**这一轮正文里的** mermaid。判据一条都不涉及数值对错（那是
    `numbers.chart_numbers_grounded` 的事），也不涉及语法（`charts_from_tools`）。
    """
    start = blockcheck.mermaid_blocks(st.bag.get("content_at_start") or "")
    problems: list[str] = []
    for block in blockcheck.mermaid_blocks(st.content):
        if block in start:
            continue          # 笔记原来就有的图不是这一轮画的（见 charts_from_tools 那段注释）
        shape = blockcheck.chart_shape(block)
        title = shape["title"] or "（没有标题）"
        cats = shape["categories"]
        if shape["kind"] == "xy":
            if not shape["axis"]:
                problems.append(f"「{title}」没有 y 轴名字，读者不知道这根柱子量的是什么")
            elif shape["series"] > 1 and len(
                    [n for n in shape["axis"].split("/") if n.strip()]) < shape["series"]:
                problems.append(
                    f"「{title}」有 {shape['series']} 条系列，y 轴上却只写得下 "
                    f"{len([n for n in shape['axis'].split('/') if n.strip()])} 个名字"
                    f"（{shape['axis']}）——哪条是哪条读者分不出来，系列名要短")
            if len(cats) > MAX_XY_CATEGORIES:
                problems.append(
                    f"「{title}」x 轴上有 {len(cats)} 个类目，多到读不出形状——"
                    f"挑出最值得比的几项，或者按维度拆成两张图")
            truncated = [c for c in cats if c.endswith("…")]
            if truncated:
                problems.append(
                    f"「{title}」的 x 轴标签被截断了（{'、'.join(truncated[:2])}），"
                    f"读者认不出是哪一项——把 labels 换成更短的写法再画一次")
        elif shape["kind"] == "pie" and len(cats) > MAX_PIE_SLICES:
            problems.append(
                f"「{title}」有 {len(cats)} 个扇区，比例看不出来——"
                f"只留前几项、其余并成「其他」")
        elif shape["kind"] == "flow" and shape["nodes"] > MAX_FLOW_NODES:
            problems.append(
                f"这张流程图有 {shape['nodes']} 个节点，一屏读不完——"
                f"拆成两张，或者只画主干")
    if not problems:
        return None
    return Verdict(
        pick_dimension(st, "has_charts", "chart_validity", "coherence"),
        "图画出来读不出来：" + "；".join(problems[:2]) + "。"
        "**重画的时候仍然要用工具**（chart_from_text / render_chart / chart_column），"
        "不要自己去改 mermaid 里的字。",
    )
