"""Chart checks.

The design line these enforce: **the model decides what to draw, code
produces the numbers and the mermaid**. Left to itself the model invents
averages and writes mermaid that doesn't render -- both observed.

**这四条的兜底落点是这个仓最贵的一次错配**（计划 4.4 / [MECH] §3）：两条长文
模式挂着它们，而长文的维度里没有 `has_charts` / `chart_validity`，于是
`pick_dimension` 的兜底原来落在 `coherence` 上——`coherence` 在
`repair.INNER_QUALITY` 里，下一轮排 `cleanup_only`，`produce()` 直接返回，
**模型根本没机会去调这几条判据要求它调的画图工具**（第 606 轮真跑，两轮原地
打转、`no_progress` 收场）。现在兜底落到 `checks.pick.MECHANICS`，那个桶
**排不了修复轮**，理由写在 `pick.py` 里。
"""

from __future__ import annotations

import re

from . import blockcheck
from ..state import State
from ..types import Verdict
from .pick import pick_dimension


# 找「开跑时就有的那些」时不设上限：默认的 limit 是给诊断用的（一条诊断里
# 列三条假图就够人看了），拿它去当豁免名单会漏——开跑前正好有 3 张假图的话，
# 这一轮新写的第 4 张会挤不进名单，然后被当成「开跑前就有的」放过去。
_ALL = 99


def no_fake_charts(st: State) -> Verdict | None:
    """Charts described in prose instead of drawn.

    Real output: ``[bar chart: clicks by channel  Kickstarter: 12700 ...]``
    and ``[scatter: impressions vs orders, n=6, r=0.9902]``. The second is
    worse -- mermaid has no scatter plot, so that chart could never exist.
    The scorer gave this ``has_charts = 2``.

    ## 量程：开跑时就有的那几处不报（批 25）

    **它此前一处量程都没有**，而它的判词第一句是「**这一轮**没有真的画图」——
    对着一段开跑前就躺在笔记里的箭头链说这句话，是在报一件没发生的事。
    实测：18 篇 `origin=user` 上开火 1 篇（`3a3a96354546`），命中的是正文里
    一句「用户在页面停留的路径已经测出来了：先看硬件参数 → 跳到软件功能列表 →
    回到定价 → 退出。」——一句正常的叙述，而判词要求把它换成一张图，
    **每一次跑都要求一遍**。

    收它的硬依据是**它的孪生兄弟早就收了**：`charts_from_tools` 判的是同一件事
    的另一面（图是不是工具画的），量程写的正是
    `blockcheck.mermaid_blocks(st.bag["content_at_start"])`，理由是第 604 轮那次
    真跑——用户自己画的两张合法流程图被修订整个删掉，删完这一条又报「这条流程是
    用箭头串在正文里的」，**删图和要图来回打架**。两条判据打同一维、一条收了
    一条没收，那正是「同一件事挡住一半」。

    另一条依据是**这一维根本排不出修复轮**：长文两个模式的 `dims` 里既没有
    `has_charts` 也没有 `chart_validity`，`pick_dimension` 于是落到
    `checks.pick.MECHANICS` 兜底桶——那个桶按设计**不在 `repair.INNER_QUALITY`
    里，排不了「只修不写」的修复轮**。开跑前就有的那一处，在长文模式里既修不掉
    也停不下来，只会每一轮都短路一次打分。
    """
    before = str(st.bag.get("content_at_start") or "")
    was_there = set(blockcheck.fake_charts(before, limit=_ALL))
    hits = [h for h in blockcheck.fake_charts(st.content, limit=_ALL)
            if h not in was_there][:3]
    if not hits:
        # 另一种"用文字画图"：把一条流程写成箭头链（第 592 轮，用户实拍的那段里就有）
        # **两边都过一遍 `text_flow` 再比**，不是拿结果去 `before` 里搜：它返回的是
        # 空白规范化 + 截断到 80 字之后的串，直接拿去原文里找必然找不着。
        was_flow = set(blockcheck.text_flow(before, limit=_ALL))
        flows = [f for f in blockcheck.text_flow(st.content, limit=_ALL)
                 if f not in was_flow][:2]
        if flows:
            return Verdict(
                pick_dimension(st, "has_charts", "chart_validity"),
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
        pick_dimension(st, "has_charts", "chart_validity"),
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
    if "chart" not in st.mode.groups:
        # 这个模式手上没有画图工具（P8 问题 7：`note` 摘掉了 chart 组）。让它「下一轮再调
        # render_chart」是在要求一件做不到的事（第 606 轮那种死锁）；这里直接把手写的
        # 摘掉——最简流程图（`is_plain_flowchart`）不在 `bad` 里，照旧放行。
        return Verdict(
            pick_dimension(st, "has_charts", "chart_validity"),
            f"这里有 {len(bad)} 张手写的 mermaid 图（{'; '.join(bad)}）。续写整篇不画图——"
            "要图请用「/ 智能插图」，那条路的图是工具画的、验证过能渲染。已摘掉。",
            fix=lambda text: _drop_unauthorized(text, allowed),
        )
    return Verdict(
        pick_dimension(st, "has_charts", "chart_validity"),
        f"这里有 {len(bad)} 张 mermaid 图不是工具画的（{'; '.join(bad)}），是手写的、模仿工具"
        "输出。手写的 mermaid 没验证过，一处语法不对（比如 y 轴范围）整张图就变成一段"
        "报错。画什么由你定，**代码必须是工具原样返回的**；工具没画出你要的，"
        "就在下一轮取材料那一步再调一次 render_chart（写正文这一步没有工具可用）。"
        "——只有最简流程图例外：`graph TD` / `flowchart LR` 加几行 `A[甲] --> B[乙]`，"
        "那一种自己写没问题，上面这几张不是那一种。",
    )


def _drop_blocks(text: str, should_drop) -> str:
    """把 ``should_drop(规范化后的块内容)`` 为真的 ```mermaid 块整块摘掉（连同它后面的空行）。"""
    def _sub(m):
        body = "\n".join(ln.rstrip() for ln in m.group(1).strip().split("\n"))
        return "" if should_drop(body) else m.group(0)
    out = re.sub(r"```mermaid\n(.*?)```[ \t]*\n?", _sub, text or "", flags=re.S)
    return re.sub(r"\n{3,}", "\n\n", out)


def _drop_unauthorized(text: str, allowed: list[str]) -> str:
    ok = set(allowed)
    return _drop_blocks(text, lambda b: b not in ok and not blockcheck.is_plain_flowchart(b))


# ------------------------------------------------- 图只是把清单 / 段落再画一遍（P8 问题 7）---
#
# P5 / P6 十跑最终正文里 5 张 mermaid，人读只有 1 张用户会留（P6 `603dca` 那张核实
# 流程：节点「纳入横向比较」「标记为待核实判断」「继续补问」正文里都没有，图在说新东西）。
# 另外 4 张全是**把紧挨着的清单 / 段落逐节点重画一遍**：P6 `e783` 那张 `graph LR`
# 七个节点「教师现场录制 → 自动提交素材 → 转码与摘要 → …」，上面就是同样的四步有序
# 清单 + 一段「教师开始录制，素材自动进入处理流程…」；P5 `da080` 两张的节点
# 「7月29日老MP最终确认 → 预留5天buffer → 8月5日完成生产」逐字来自前一段。
# `_MERMAID_HINT` 明写「图跟正文讲同一件事是正常的」——对依赖 / 分支成立，对一条
# 顺序清单不成立：读者刚读完四步，再看一张四个框的图，没有一点新信息。
#
# 判法零模型：图里每个节点标签的特征词（`relevance.terms`），在图前后各 4 段正文里
# 找得到 ≥ `RESTATE_NODE_COVER` 的，算「正文已经说过」；≥ 3 个节点、其中
# ≥ `RESTATE_CHART_COVER` 的节点都说过 → 这张图是复述。`603dca` 那张 7 个节点里
# 只有 1 个盖住（14%），`e783` 那张 7/7，`da080` 两张 4/4、6/6——分界很宽。
# 开跑前就有的图不判（用户自己画的）。可自动修：整块摘掉，正文一个字不动。

RESTATE_NODE_COVER = 0.5
RESTATE_CHART_COVER = 0.8
RESTATE_WINDOW = 4          # 图前后各看几段
RESTATE_MIN_NODES = 3

_NODE_LABEL = re.compile(
    r"\[\[([^\]]+)\]\]|\(\(([^)]+)\)\)|\[([^\]]+)\]|\(([^)]+)\)|\{([^}]+)\}|\|([^|]+)\|")


def chart_node_labels(block: str) -> list[str]:
    """一块 mermaid 里的节点 / 边标签（去重保序）。"""
    out: list[str] = []
    for m in _NODE_LABEL.finditer(block or ""):
        label = next((g for g in m.groups() if g), "").strip().strip('"')
        if label and label not in out:
            out.append(label)
    return out


def chart_restates(block: str, around: str) -> tuple[int, int]:
    """``(说过的节点数, 节点总数)``——每个节点标签的特征词在 `around` 里盖住了多少。"""
    from .relevance import terms
    ctx = terms(around)
    # 没有特征词的标签（边上的「是」「否」、单个字母）判不了，不进分母
    labels = [(label, terms(label)) for label in chart_node_labels(block)]
    labels = [(label, lt) for label, lt in labels if lt]
    said = sum(1 for _label, lt in labels if len(lt & ctx) / len(lt) >= RESTATE_NODE_COVER)
    return said, len(labels)


def restating_charts(content: str, before: str = "") -> list[tuple[str, int, int]]:
    """正文里那些只是把周围文字再画一遍的图：``[(块内容, 说过的节点, 节点总数)]``。
    `before` 里就有的块不算。"""
    was = set(blockcheck.mermaid_blocks(before))
    paras = re.split(r"\n\s*\n", content or "")
    out: list[tuple[str, int, int]] = []
    for i, para in enumerate(paras):
        if not para.strip().startswith("```mermaid"):
            continue
        blocks = blockcheck.mermaid_blocks(para)
        if not blocks or blocks[0] in was:
            continue
        window = [p for p in paras[max(0, i - RESTATE_WINDOW):i] + paras[i + 1:i + 1 + RESTATE_WINDOW]
                  if not p.strip().startswith("```")]
        said, total = chart_restates(blocks[0], "\n\n".join(window))
        if total >= RESTATE_MIN_NODES and said / total >= RESTATE_CHART_COVER:
            out.append((blocks[0], said, total))
    return out


def chart_restates_list(st: State) -> Verdict | None:
    """这次跑画的图只是把紧挨着的清单 / 段落逐节点重画了一遍。可自动修：整块摘掉。"""
    before = str(st.bag.get("content_at_start") or "")
    hits = restating_charts(st.content, before)
    if not hits:
        return None
    block, said, total = hits[0]
    gone = {b for b, _s, _t in hits}
    head = chart_node_labels(block)[:3]
    return Verdict(
        pick_dimension(st, "has_charts", "non_repetition"),
        f"这张图的 {total} 个节点里 {said} 个（{'、'.join(head)}…）正文紧挨着的清单 / 段落已经逐条说过了，"
        "图没有带来新信息，已摘掉。图只在正文没法一眼看清的关系上画（分支 / 依赖 / 多方牵扯），"
        "顺序清单本身就是图。",
        fix=lambda text: _drop_blocks(text, lambda b: b in gone),
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
        pick_dimension(st, "has_charts", "chart_validity"),
        "图画出来读不出来：" + "；".join(problems[:2]) + "。"
        "**重画的时候仍然要用工具**（chart_from_text / render_chart / chart_column），"
        "不要自己去改 mermaid 里的字。",
    )
