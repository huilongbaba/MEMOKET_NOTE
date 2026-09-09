"""数据与图表工具。分组 ``data`` / ``chart``。

跟 memory 那组一样是**零 LLM、确定性**的：模型决定算什么、画什么，数字由
这里算、图表语法由这里拼。这条分界线是「数据可视化 / 数据分析」能不能信的
关键——让模型自己算均值它会编，让它自己写 mermaid 会出语法错。

数据从**当前笔记**里认（markdown 表格 + ```csv/```tsv 代码块），所以用户
粘一段 CSV 进来就能直接分析，不需要另外上传。
"""

from __future__ import annotations

import json

from .. import blocks, tabular
from .registry import ToolContext, register

# 正文和光标位置从 ctx 上取（调用方构造 ToolContext 时带进来）。
#
# **光标位置是必要的**：用户在某个地方按 `/数据可视化`，要看的是他跟前那张表。
# 一篇有五张表的笔记，没有位置信息模型只能瞎猜一个编号。


# 「光标附近」的半径。定在两三段的长度：实测一篇连续叙述的汇报里，
# 光标在「油气勘探」段，1280 字外的那张表已经隔了榴莲分拣、城市燃气、
# 光谱感知三个话题——**距离近不等于相关**，半径宽一点就等于没有判据。
# 中间隔了标题的一律算远，那是明确的话题边界。
NEAR_CHARS = 600


def _tables(ctx: ToolContext) -> list[tabular.Table]:
    return tabular.find_tables(ctx.content or "")


def _cursor(ctx: ToolContext) -> int:
    return max(0, min(int(ctx.cursor or 0), len(ctx.content or "")))


def _default_index(ctx: ToolContext) -> int:
    """没指定表时用哪张：离光标最近的那张（就近原则）。"""
    n = tabular.nearest(_tables(ctx), _cursor(ctx))
    return n.index if n else 0


def _pick(ctx: ToolContext, index: int | None) -> tabular.Table | str:
    ts = _tables(ctx)
    if not ts:
        return "（这篇笔记里没有找到表格数据。支持 markdown 表格和 ```csv / ```tsv 代码块。）"
    if index is None:                    # 没给编号就用离光标最近的
        index = _default_index(ctx)
    if index < 0 or index >= len(ts):
        return f"（没有第 {index} 张表，当前一共 {len(ts)} 张，编号 0 到 {len(ts) - 1}）"
    return ts[index]


@register(
    name="list_tables", group="data",
    description="列出当前笔记里的表格数据：编号、来源、列名、行数。做任何数据分析之前先调它。",
    params={},
)
def list_tables(ctx: ToolContext) -> str:
    ts = _tables(ctx)
    if not ts:
        return "（这篇笔记里没有表格数据。支持 markdown 表格和 ```csv / ```tsv 代码块。）"
    cur = _cursor(ctx)
    lines = []
    # **按离光标的远近排**，最近的排最前面——用户在哪儿触发的，就先看哪张表。
    # 距离要**如实报出来**：nearest 只会返回"相对最近"的那张，一篇笔记里
    # 唯一的一张表哪怕在一万字外也是"最近"的。实测吃过这个亏——光标在讲
    # AI FWI 的段落，工具却说"光标就在这张表旁边"，指的是一万字外的项目
    # 进度表，于是整段分析画的是跟用户完全无关的东西。
    for t in sorted(ts, key=lambda x: tabular.distance(x, cur)):
        rows, cols = t.shape
        kinds = ["数值" if tabular.is_numeric_column(t.column(c)) else "文本" for c in t.columns]
        d = tabular.distance(t, cur)
        crossed = tabular.headings_between(ctx.content or "", cur, t.start, t.end)
        if crossed:
            tag = f"  ← 中间隔着 {crossed} 个标题，**是另一个话题**"
            lines.append(f"表 {t.index}（{t.source}，{rows} 行 {cols} 列）："
                         + "、".join(f"{c}[{k}]" for c, k in zip(t.columns, kinds)) + tag)
            continue
        if d <= NEAR_CHARS:
            tag = "  ← **光标就在这张表旁边，没有特别指定就用它**"
        else:
            tag = f"  ← 离光标 {d} 字，**不在光标附近**"
        lines.append(f"表 {t.index}（{t.source}，{rows} 行 {cols} 列）："
                     + "、".join(f"{c}[{k}]" for c, k in zip(t.columns, kinds)) + tag)
    if all(tabular.distance(t, cur) > NEAR_CHARS
           or tabular.headings_between(ctx.content or "", cur, t.start, t.end)
           for t in ts):
        lines.insert(0, "（**光标附近没有表格**——下面这些表都离得很远，多半跟用户"
                        "现在看的内容无关。先用 numbers_near_cursor 看看光标跟前的"
                        "正文里有没有数字，那才是他想可视化的东西。）")
    return "\n".join(lines)


@register(
    name="numbers_near_cursor", group="data",
    description="看光标跟前的正文里写着哪些数字，返回含数字的原句（离光标最近的排最前）。"
                "**做数据可视化第一步就调它**——用户在哪儿触发的，想看的多半是他跟前那段话里的数，"
                "而不是笔记别处的某张表。",
    params={"radius": {"type": "integer",
                       "description": "往前后各看多少字，默认 1200。不用改"}},
)
def numbers_near_cursor(ctx: ToolContext, radius: int | None = None) -> str:
    text = ctx.content or ""
    r = int(radius) if radius else 1200
    hits = tabular.sentences_with_numbers(text, _cursor(ctx), radius=r)
    if not hits:
        return f"（光标前后 {r} 字里没有写着数字的句子。）"
    head = ("光标附近写着数字的句子（最近的排最前）。**单位在句子里，"
            "画图时一张图只放同一个单位的数**：\n")
    return head + "\n".join(f"{i}. {s}" for i, s in enumerate(hits[:12], 1))


@register(
    name="describe_table", group="data",
    description="对一张表做统计画像：每列的类型、缺失数，数值列给最小/最大/均值/中位数/P25/P75/标准差/求和，"
                "文本列给不同取值数和最常见的几个。数字全部由代码算出，不要自己估。",
    params={"index": {"type": "integer",
                      "description": "表编号，先用 list_tables 查。不给就用离光标最近的那张"}},
)
def describe_table(ctx: ToolContext, index: int | None = None) -> str:
    t = _pick(ctx, None if index is None else int(index))
    if isinstance(t, str):
        return t
    out = [tabular.describe_column(c, t.column(c)) for c in t.columns]
    return json.dumps(out, ensure_ascii=False, indent=1)


@register(
    name="aggregate_table", group="data",
    description="按一列分组、对另一列聚合。agg 取 sum/mean/count/max/min/median。结果按值从大到小排。",
    params={
        "index": {"type": "integer", "description": "表编号，不给就用离光标最近的那张"},
        "group_by": {"type": "string", "description": "分组用的列名"},
        "value": {"type": "string", "description": "被聚合的列名；agg=count 时随便给一列"},
        "agg": {"type": "string", "description": "sum / mean / count / max / min / median"},
    },
    required=["group_by", "value", "agg"],
)
def aggregate_table(ctx: ToolContext, group_by: str, value: str, agg: str,
                    index: int | None = None) -> str:
    t = _pick(ctx, None if index is None else int(index))
    if isinstance(t, str):
        return t
    try:
        rows = tabular.aggregate(t, group_by, value, str(agg).lower())
    except (KeyError, ValueError) as exc:
        return f"（{exc}。这张表的列是：{'、'.join(t.columns)}）"
    if not rows:
        return f"（按 {group_by} 分组后没有可聚合的数值——{value} 这一列可能不是数字）"
    return json.dumps([{"分组": k, "值": v} for k, v in rows], ensure_ascii=False)


@register(
    name="correlate_columns", group="data",
    description="算两个数值列的皮尔逊相关系数。会同时给出实际参与计算的行数 n——n 很小时相关系数不可信。",
    params={
        "index": {"type": "integer", "description": "表编号，不给就用离光标最近的那张"},
        "x": {"type": "string", "description": "第一列列名"},
        "y": {"type": "string", "description": "第二列列名"},
    },
    required=["x", "y"],
)
def correlate_columns(ctx: ToolContext, x: str, y: str, index: int | None = None) -> str:
    t = _pick(ctx, None if index is None else int(index))
    if isinstance(t, str):
        return t
    try:
        return json.dumps(tabular.correlate(t, x, y), ensure_ascii=False)
    except KeyError as exc:
        return f"（没有这一列 {exc}。这张表的列是：{'、'.join(t.columns)}）"


# 画一张分布图至少要这么多个点。少于这个数，直方图就是几根孤立的柱子，
# 看不出任何形状——**那不是可视化，是噪声**。
#
# 实测代价：6 行数据的表，「每列都画」画出 4 张两根柱的直方图 + 2 张
# 「3:3」「2:2:2」的饼图，7 张里只有 1 张有信息。图多不等于可视化好。
# 单位里出现分隔词，就说明调用方自己也知道这张图混了量纲。实测抓到过
# 模型传 series="百分比/倍数" 去画「效率提升 10 倍、成本降幅 75%、机房空间
# 降低 98%」——三根柱子量纲不同，高度之间不构成任何比较。
# 判据取"调用方自己写出来的混合"，不去猜每个数字的单位：猜会误伤
# （「万元」里有「元」），而这个信号是明确的。
_MIXED = ("/", "／", "、", "，", ",", " 和 ", " 与 ", " 或 ", "或")


def _mixed_unit(unit: str) -> str:
    u = (unit or "").strip()
    if not u or len(u) > 12:
        return ""
    return u if any(sep in u for sep in _MIXED) else ""


def _too_few(values: list[float], values2: list | None, kind: str) -> str:
    """一根柱子的柱状图、一个点的折线图：画出来什么也看不出。

    「10 倍」这种孤零零一个数，图上是一根柱子配一根坐标轴，读者得到的信息
    跟直接读那句话完全一样——图的作用是比较，没有比较对象就不该画。
    """
    if str(kind).lower() == "flow" or len(values) != 1 or values2:
        return ""
    return ("（只有一个数，画出来是一根孤零零的柱子，读者得到的信息跟直接读那句话"
            "一样——图的作用是比较，没有比较对象就不值得画。这个数写进正文的句子里，"
            "或者找到它的对照（前后期、竞品、目标值）再一起画。）")


def _unit_clash(ctx: ToolContext, values: list[float]) -> str:
    """这组数在光标附近带的单位对不对得上；混了就返回该说的话。

    比 `_mixed_unit` 硬：那个只抓"调用方自己写出混合单位"，模型声明
    unit="倍" 却把「576 台」画进来时，声明本身没撒谎，混的是数据。
    单位从**原文**里取才作数。
    """
    by = tabular.mixed_units(ctx.content or "", values, _cursor(ctx))
    if not by:
        return ""
    detail = "；".join(f"{u}：{'、'.join(f'{v:g}' for v in vs)}" for u, vs in by.items())
    return (f"（这几个数在原文里的单位不是一个——{detail}。画进同一张图，"
            "柱子高度之间不构成任何比较（「效率提升 10 倍」和「576 台服务器」"
            "谁比谁高没有意义）。**按单位拆成几张图**，一张一个单位。）")


MIN_POINTS_FOR_HISTOGRAM = 10


@register(
    name="chart_column", group="chart",
    description="给某一列直接出一张分布图，返回可直接插进笔记的 mermaid 代码块。"
                "**数据可视化的主力工具**：数值列出直方图（分箱由代码算），"
                "文本列出取值占比饼图。不用自己想画什么、也不用自己算分箱。",
    params={
        "index": {"type": "integer", "description": "表编号，不给就用离光标最近的那张"},
        "column": {"type": "string", "description": "列名"},
    },
    required=["column"],
)
def chart_column(ctx: ToolContext, column: str, index: int | None = None) -> str:
    t = _pick(ctx, None if index is None else int(index))
    if isinstance(t, str):
        return t
    try:
        vals = t.column(column)
    except KeyError:
        return f"（没有这一列 {column!r}。这张表的列是：{'、'.join(t.columns)}）"

    if tabular.is_numeric_column(vals):
        n = len(tabular.numeric([v for v in vals if (v or "").strip()]))
        if n < MIN_POINTS_FOR_HISTOGRAM:
            return (f"（{column} 只有 {n} 个数据点，画直方图看不出分布，不值得画。"
                    f"这么少的数据，直接把每一项列出来对比更有信息——"
                    f"用 aggregate_table 或 render_chart 画分组对比。）")
        labels, counts = tabular.histogram(vals)
        if not labels:
            return f"（{column} 的有效数值不足两个，画不出分布）"
        return blocks.mermaid_xy(f"{column} 分布", labels, counts, "条数", kind="bar")

    counts: dict[str, int] = {}
    for v in vals:
        v = (v or "").strip()
        if v:
            counts[v] = counts.get(v, 0) + 1
    if not counts:
        return f"（{column} 全是空值）"
    freqs = set(counts.values())
    if len(freqs) == 1:
        # 每个取值出现次数都一样：这张饼图除了"数据是均衡的"什么都说明不了
        only = next(iter(freqs))
        return (f"（{column} 的 {len(counts)} 个取值各出现 {only} 次，占比图没有信息量，"
                f"不值得画。这一列适合当**分组维度**：用 aggregate_table 按它分组，"
                f"再画各组的数值对比。）")
    return blocks.mermaid_pie(f"{column} 取值占比",
                              sorted(((k, float(n)) for k, n in counts.items()),
                                     key=lambda kv: -kv[1]))


@register(
    name="chart_from_text", group="chart",
    description="**正文里有数字但没有表格时用这个。** 你从光标附近的文字里读出"
                "一组「名称 + 数值」，这个工具负责画图。"
                "每个数值都会拿去跟原文核对——抄错或编造会被拒绝并告诉你哪个不对。"
                "kind：pie 占比 / bar 对比 / line 趋势。",
    params={
        "kind": {"type": "string", "description": "pie / bar / line"},
        "title": {"type": "string", "description": "图表标题"},
        "labels": {"type": "array", "items": {"type": "string"},
                   "description": "每个数值对应的名称，按顺序"},
        "values": {"type": "array", "items": {"type": "number"},
                   "description": "从正文里读出来的数值。**必须是原文里真的写着的数**，"
                                  "「4.2 万」写成 42000 可以，但不能自己换算出原文没有的数"},
        "series": {"type": "string", "description": "第一条系列的名字，比如「三月」「曝光」"},
        "unit": {"type": "string",
                 "description": "**这张图的单位，只能有一个**：「%」「倍」「台」「亿参数」「公里」。"
                                "单位不同的数不能画进同一张图——「效率提升 10 倍」和「成本降幅 75%」"
                                "画在一根轴上是错的，要拆成两张。"},
        "values2": {"type": "array", "items": {"type": "number"},
                    "description": "**第二条系列**（可选）。分组对比就该这么画：x 轴是类目、"
                                   "两条柱分别是两个时期，而不是把「月份×渠道」压成一维"},
        "series2": {"type": "string", "description": "第二条系列的名字"},
        "kind2": {"type": "string", "description": "第二条画成 bar 还是 line。"
                                                   "量纲差很多时用 line（比如曝光配转化率）"},
    },
    required=["kind", "title", "labels", "values", "unit"],
)
def chart_from_text(ctx: ToolContext, kind: str, title: str, labels: list,
                    values: list, unit: str = "", series: str = "数值",
                    values2: list | None = None, series2: str = "系列2",
                    kind2: str = "bar") -> str:
    text = ctx.content or ""
    if not text.strip():
        return "（拿不到笔记正文）"
    mixed = _mixed_unit(unit) or _mixed_unit(series)
    if mixed:
        return (f"（{mixed} 不是一个单位，是几个混在一起。一张图只能放同一个单位的数——"
                "「效率提升 10 倍」和「成本降幅 75%」画在一根轴上，柱子高度之间没有意义。"
                "按单位拆成几张图，一张一个单位。）")
    clash = _unit_clash(ctx, [float(v) for v in (values or [])
                              if isinstance(v, (int, float))])
    if clash:
        return clash
    few = _too_few([float(v) for v in (values or []) if isinstance(v, (int, float))],
                   values2, kind)
    if few:
        return few
    labs = [str(x) for x in (labels or [])]
    vals: list[float] = []
    for v in (values or []):
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            return f"（values 里有不是数字的项：{v!r}）"
    if not labs or not vals or len(labs) != len(vals):
        return f"（labels 和 values 数量要一致，收到 {len(labs)} 个名称、{len(vals)} 个数值）"

    # **数值必须在正文里找得到出处。** 抽取是语义判断（知道「4.2 万」对应
    # 「官网曝光」），数值对不对由代码验证——模型抄错一位，图就是错的，
    # 而错的图比没有图更糟：它看起来同样可信。
    all_vals = list(vals) + [float(v) for v in (values2 or []) if isinstance(v, (int, float))]
    # **出处只在光标附近找**，不在全篇找。三万字的笔记里「1」出现 48 次，
    # 拿全文当出处等于没有校验——实测模型就是这么把「传统方案 = 1 倍」
    # 这个原文里根本没有的对照编进图里的（它想给单值图凑一个对照）。
    # 范围取 numbers_near_cursor 给模型看过的那些句子：工具给它看了什么，
    # 它就只能用什么。
    near_text = "\n".join(tabular.sentences_with_numbers(text, _cursor(ctx))) or text
    bad = tabular.unsupported_numbers(near_text, all_vals)
    if not bad:
        # 数出现过还不够，**得以这个单位出现过**：小整数在长文里必然有出处，
        # 「1」在这篇三万字的笔记里出现 48 次。实测模型就是这么给一张单值图
        # 凑出「传统方案 = 1 倍」这个原文没有的对照的。
        bad = tabular.without_unit(near_text, all_vals, unit)
    if bad:
        pairs = "、".join(f"{labs[vals.index(v)]}={v:g}" for v in bad if v in vals)
        return (f"（这些数在光标附近的正文里找不到出处：{pairs}。"
                "只能用 numbers_near_cursor 列出来的那些句子里真的写着的数字，"
                "不要自己换算、估计，也不要为了凑一张图编一个对照值。"
                "如果原文写的是「约」「左右」这类模糊说法，那就不该画成精确的图。）")

    k = str(kind).lower()
    if k == "pie":
        return blocks.mermaid_pie(title, list(zip(labs, vals)))
    # 单位写进 y 轴。读者看到的是「倍」还是「%」，决定了这张图怎么读——
    # 而 xychart-beta 除了 y 轴标题没有别的地方能放它。
    axis = f"{series}（{unit.strip()}）" if unit.strip() else series
    return blocks.mermaid_xy(title, labs, vals, axis, kind="line" if k == "line" else "bar")


@register(
    name="render_chart", group="chart",
    description="把数据画成图，返回可以直接插进笔记的 mermaid 代码块。"
                "**不要自己写 mermaid 语法**——语法由这个工具生成，保证能渲染。"
                "kind：pie 饼图 / bar 柱状 / line 折线 / flow 流程图（flow 用 labels 当步骤，不用 values）。",
    params={
        "kind": {"type": "string", "description": "pie / bar / line / flow"},
        "title": {"type": "string", "description": "图表标题"},
        "labels": {"type": "array", "items": {"type": "string"},
                   "description": "分类名 / 流程步骤，按顺序"},
        "values": {"type": "array", "items": {"type": "number"},
                   "description": "对应的数值；kind=flow 时不用给"},
        "series": {"type": "string", "description": "第一条系列的名字，比如「三月」「曝光」"},
        "values2": {"type": "array", "items": {"type": "number"},
                    "description": "**第二条系列**（可选）。分组对比就该这么画：x 轴是类目、"
                                   "两条柱分别是两个时期，而不是把「月份×渠道」压成一维"},
        "series2": {"type": "string", "description": "第二条系列的名字"},
        "kind2": {"type": "string", "description": "第二条画成 bar 还是 line。"
                                                   "量纲差很多时用 line（比如曝光配转化率）"},
    },
    required=["kind", "title", "labels"],
)
def render_chart(ctx: ToolContext, kind: str, title: str, labels: list,
                 values: list | None = None, series: str = "数值",
                 values2: list | None = None, series2: str = "系列2",
                 kind2: str = "bar") -> str:
    labs = [str(x) for x in (labels or [])]
    vals: list[float] = []
    for v in (values or []):
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            vals.append(0.0)
    k = str(kind).lower()
    if k == "flow":
        return blocks.mermaid_flow(title, labs)
    if not vals:
        return "（这种图需要 values：给每个 label 一个数值。流程图才用 kind=flow。）"
    # 这个工具的数一般来自表格聚合，正文里取不到单位就不判——但模型也会
    # 拿它画正文里的数（实测画出过 y 轴写「提升/降幅」的混量纲图），
    # 所以同样要过一遍。
    mixed = _mixed_unit(series)
    if mixed:
        return (f"（{mixed} 不是一个单位，是几个混在一起。一张图只放同一个单位的数，"
                "按单位拆成几张。）")
    clash = _unit_clash(ctx, vals)
    if clash:
        return clash
    few = _too_few(vals, values2, k)
    if few:
        return few
    if k == "pie":
        return blocks.mermaid_pie(title, list(zip(labs, vals)))
    return blocks.mermaid_xy(title, labs, vals, series,
                             kind="line" if k == "line" else "bar",
                             extra=_extra(values2, series2, kind2))


def _extra(values2, series2: str, kind2: str):
    """第二条系列。给了才画——多系列是分组对比的正确画法，但不是每张图都需要。"""
    if not values2:
        return None
    out = []
    for v in values2:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(0.0)
    return [(str(series2 or "系列2"), out, str(kind2 or "bar"))]


@register(
    # Its own group, not "chart": building a table is not drawing. While it
    # lived under chart, every drawing mode was handed a table builder and
    # the table mode was handed three chart builders -- each one costing
    # prompt space and one more thing for the model to pick wrongly.
    name="render_table", group="table",
    description="把数据拼成 markdown 表格，返回可以直接插进笔记的文本。行太多会自动截断并注明。",
    params={
        "columns": {"type": "array", "items": {"type": "string"}, "description": "表头"},
        "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}},
                 "description": "每一行的单元格，顺序跟表头对应"},
    },
    required=["columns", "rows"],
)
def render_table(ctx: ToolContext, columns: list, rows: list) -> str:
    cols = [str(c) for c in (columns or [])]
    body = [[str(c) for c in (r or [])] for r in (rows or []) if isinstance(r, (list, tuple))]
    if not cols:
        return "（columns 不能为空）"
    return blocks.markdown_table(cols, body)


# ---------------------------------------------------------------- 文生图
#
# 单独一个 group（``image``）而不是并进 chart：这一次调用要花钱、要等三四十秒，
# 而 chart 组那两个是零成本的本地拼装。分开之后 harness 可以只给某些模式开
# 文生图，不会在"画个柱状图"的场合被顺手调用。

@register(
    name="render_image", group="image", max_calls_per_round=1,
    description="用文生图模型画一张**示意/概念插图**，返回可直接插进笔记的 markdown 图片引用。"
                "适合：抽象概念、场景示意、封面配图。"
                "**不适合**：有具体数字的图表（那用 render_chart，画出来精确、可编辑、"
                "还能跟着主题变色）、以及流程图（同样用 render_chart 的 flow）。"
                "一次调用要几十秒，想清楚再用。",
    params={"prompt": {"type": "string",
                       "description": "画什么。写清楚风格、构图、要出现的元素；"
                                      "需要文字时把文字内容写进来"}},
    required=["prompt"],
)
async def render_image(ctx: ToolContext, prompt: str) -> str:
    from .. import imagegen
    try:
        png, model = await imagegen.generate(str(prompt))
    except imagegen.ImageGenError as exc:
        return f"（画不出来：{exc}）"
    url = imagegen.save(png)
    alt = str(prompt)[:60].replace("]", "").replace("\n", " ")
    return f"![{alt}]({url})\n\n> 由 {model} 生成"
