"""数字比对：图 / 表 / 正文里的数，跟工具真的返回过的那些逐个 diff。

**这一条是「能用代码判准的，不交给模型」的正面实践**（计划 5.1 / 5.2，
依据 [IND] §2–3）。三条判词原话摆在那里：

* `data_grounding`（chart）：「every number in the chart traces to a table in
  the note or to a tool result」
* `data_grounding`（table）：「every cell traces to the note, a table in it, or
  a retrieved fact」
* `numbers_from_tools`（eda / analysis）：「every statistic in the text can be
  traced to a tool result」

**这三句都是「一次精确比对」，不是「一次判断」**，而在批 16 之前它们整条交给了
一个跟写作那一步同一个模型的打分器——实测 `data_grounding` 2/2 满分。
VisEval（IEEE VIS 2024）整套方法就是一组异构 checker，几乎不用打分模型。

---

## 判据窄在哪（这一条最容易误伤，所以规矩写在最前面）

铁律：**误伤比漏报贵。** 报一个「查无出处」的数字，下一轮的诊断会逼着模型去
动那句话——而那句话很可能是对的。所以窄了四道：

1. **位置即判据（图和表）。** 只取**数值位**上的数：mermaid 的 `bar [...]` /
   pie 的 `"标签" : 值`、markdown 表里**整格就是一个数**的格子。
   图标题里的「2026 年复盘」、x 轴标签、表头一律不取。
2. **形状即判据（正文）。** 正文里先把 `tabular._NOT_A_QUANTITY` 那一组
   （引用 id / 链接 / 日期 / 第 N / 型号）挖掉，再补五条这一侧才会撞上的
   （「2026 年」、`## 2.1` 这样的章节编号、有序列表编号、`0.5.10` 版本号、
   `3:2` 比例），**然后只留下"统计量形状"的**：带百分号、带小数点、或者
   数值 ≥ 100。「三个渠道」「补 2 条」这类小整数在正文里遍地都是，
   编错了也不构成「数字无据」。
3. **源头给得宽。** 比对的一侧是「整篇笔记 + 用户那条指令 + 选区 + 这次跑
   累积的全部工具返回 + 工具画过的每一张图」。宁可多给源头，也不要把一个
   真有出处的数报成编造。数值比对带 0.5% 相对容差（`tabular.unsupported_numbers`
   的老规矩：正文写「4.2 万」、图里给 42000 是对的），外加百分数两个方向
   （源表写 0.38、图里写 38 算对上）。
4. **没有工具输出就不判。** 这一轮一次工具都没调的话，我们手上根本没有
   oracle，「查无出处」和「无从判断」分不开——那一档交给 `charts_from_tools`
   / `table_present` 去说，它们说的是「你没调工具」，那才是真正的诊断。

## 为什么不复用 `tools/tabular.unsupported_numbers` 那一个

复用了它的**源头抽取**（`numbers_in_text`，认「4.2 万」「1.5 亿」这些写法）
和它的**非数量名单**（`_NOT_A_QUANTITY`，那份名单是实拍出来的：数据可视化
把「第 5、10、15 位用户」画成过柱子）。没复用的是它的比对：那一个只试
`v` 本身，这里还要试 `v/100` 和 `v*100`（份额这一类两种写法都合法）。
**名单没有原地改**——`has_quantity` 是 EDA 取材那一步在用的，改它会顺带改
「哪几句话被拿去画图」，那是另一件事。
"""

from __future__ import annotations

import re

from ..state import State
from ..tools import tabular
from ..types import Verdict
from . import blockcheck
from .pick import pick_dimension

# 相对容差，跟 `tabular.unsupported_numbers` 同一个数：正文写「4.2 万」，
# 图里给 42000 是对的；写「约 4 万」给 42000 就不该放行。
REL = 0.005

# 正文里"算得上一个统计量"的下限。**小整数一律不算**：
# 「三个渠道」「补 2 条」「4 轮」在正文里遍地都是，而它们对不上源头
# 不构成「数字无据」，报上去只会逼模型去改对的句子。
MIN_MAGNITUDE = 100

# `tabular._NOT_A_QUANTITY` 之外，正文这一侧才会撞上的五种。
# 每一条都对应一种"看起来是数据、其实是结构"的写法：
_NOT_DATA = (
    re.compile(r"(?:1[6-9]|20|21)\d{2}\s*(?:年|财年|Q[1-4])"),   # 2026 年（tabular 那条要求后面跟月份）
    re.compile(r"^#{1,6}\s*\d+(?:\.\d+)*", re.M),               # ## 2.1 背景
    re.compile(r"^[ \t]*\d+(?:\.\d+)*\s*[、.)）]", re.M),        # 有序列表 / 章节编号
    re.compile(r"\d+(?:\.\d+){2,}"),                            # 0.5.10 版本号
    re.compile(r"\d+\s*[:：]\s*\d+"),                           # 3:2 比例 / 14:30
)

# 正文里的一个数：数字 + 可选**中文**数量词 + 可选百分号。
#
# 两处跟 `tabular._TEXT_NUM` 有意不一样，都是在 24 篇真实用户笔记上跑出来的：
#
# · **负号前面不许是数字**：「跨柜 IB 带宽摔到 100-200GB」「单基站覆盖
#   500-600 米」——那是区间，不是 −200 和 −600。老正则在这两句上各造了
#   一个负数出来。
# · **不认 `k/K/m/M/w/W` 这几个倍数后缀**。在中文笔记里它们绝大多数是
#   **单位**不是倍数：「40m 的距离」「20kmh」「100kW」「12MW」「3km」实测
#   全中招（「40m」被读成四千万）。源头那一侧（`tabular.numbers_in_text`）
#   照旧两种都收，于是这里少认一种只会**漏**、不会**误伤**——
#   而漏报比误伤便宜，这是这一条的全部纪律。
_PROSE_NUM = re.compile(r"(?<![\d.-])(-?\d[\d,]*(?:\.\d+)?)\s*([万萬亿億千百])?\s*([%％])?")

_FENCE = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_LINK = re.compile(r"!?\[[^\]]*\]\([^)]*\)")


# ------------------------------------------------------------ 源头那一侧 ---

def sources(st: State) -> str:
    """这一轮"数字可以从哪儿来"的全部文字。

    **宁可多给**：整篇笔记（表和原文里写着的数都在里面）、用户那条指令、
    被替换掉的选区、这次跑累积的全部工具返回（`facts_all` 是只追加的那一份，
    批 15 的 3.2 之后它一条不丢）、工具画过的每一张图、以及这一轮的 trace。
    """
    st_facts = list(st.bag.get("facts_all") or []) or list(st.facts)
    parts = [st.ctx.content or "", st.before or "", st.after or "",
             str(st.bag.get("prompt") or ""), str(st.bag.get("selection") or ""),
             str(st.bag.get("content_at_start") or "")]
    parts += st_facts + list(st.facts) + list(st.charts)
    if st.trace is not None:
        parts += [r for _n, _a, r in st.trace.calls if r]
    return "\n".join(p for p in parts if p)


def has_tool_output(st: State) -> bool:
    """这一轮手上到底有没有 oracle。

    没有就**不判**——见模块文档第 4 条。「一次工具都没调」这件事本身有别的
    判据在说（`charts_from_tools` / `table_present`），那几条给的是能照办的
    诊断；这一条要是在没有工具输出时开火，说的会是「你这些数查无出处」，
    而正确的话是「你还没查」。
    """
    if st.charts or st.facts or st.bag.get("facts_all"):
        return True
    return st.trace is not None and bool(st.trace.calls)


def unsupported(values: list[float], known: set[float]) -> list[float]:
    """这些数里，哪些在源头里一个都对不上。

    三种写法都算对上：`v` 本身、`v/100`（源表写 0.38、图里写 38%）、
    `v*100`（源表写 38、正文写 0.38）。**份额这一类两个方向都合法**，
    定死一个方向就会把另一半真有出处的判成编造。
    """
    bad: list[float] = []
    for v in values:
        if any(any(abs(c - h) <= max(REL * abs(c), 1e-9) for h in known)
               for c in (v, v / 100.0, v * 100.0)):
            continue
        bad.append(v)
    return bad


def _fmt(values: list[float], limit: int = 5) -> str:
    return "、".join(f"{v:g}" for v in values[:limit]) + (
        f"（还有 {len(values) - limit} 个）" if len(values) > limit else "")


# ------------------------------------------------------- 5.1 图 / 表里的数 ---

def chart_numbers_grounded(st: State) -> Verdict | None:
    """图里画的数、表里填的数，跟工具返回的逐个 diff（计划 5.1）。

    取的是**数值位**：mermaid 的 `bar [...]` / pie 的 `"标签" : 值`，
    以及 markdown 表里整格就是一个数的格子。标题、轴名、x 轴标签、表头
    一个都不取——那些位置上的数字（「2026 年复盘」）不是数据。
    """
    if not has_tool_output(st):
        return None
    values: list[float] = []
    for block in blockcheck.mermaid_blocks(st.content):
        values += blockcheck.chart_numbers(block)
    values += blockcheck.table_numbers(st.content)
    if not values:
        return None
    bad = unsupported(values, tabular.numbers_in_text(sources(st)))
    if not bad:
        return None
    return Verdict(
        pick_dimension(st, "data_grounding", "numbers_from_tools"),
        f"图 / 表里这几个数在工具返回的结果和笔记原文里都找不到出处："
        f"{_fmt(bad)}。这几个位置上的数**必须是工具算出来的**——"
        "下一轮取材料那一步再调一次（describe_table / aggregate_table / "
        "correlate_columns），拿真的数重画；工具算不出来就把这一项从图/表里去掉。"
        "**别去改正文里别的句子**，这条判的只是图和表里的数值格。",
    )


# ------------------------------------------------------ 5.2 正文里的统计量 ---

def prose_statistics(text: str) -> list[float]:
    """正文里"算得上统计量"的那些数。判据窄在哪见模块文档第 2 条。"""
    body = _FENCE.sub(" ", text or "")
    body = _INLINE_CODE.sub(" ", body)
    body = _LINK.sub(" ", body)
    for block in blockcheck.table_blocks(body):
        body = body.replace(block, " ")
    for pat in tabular._NOT_A_QUANTITY:          # noqa: SLF001 —— 见模块文档
        body = pat.sub(" ", body)
    for pat in _NOT_DATA:
        body = pat.sub(" ", body)
    out: list[float] = []
    for m in _PROSE_NUM.finditer(body):
        raw, unit, pct = m.group(1), m.group(2), m.group(3)
        try:
            v = float(raw.replace(",", ""))
        except ValueError:
            continue
        if unit:
            v *= tabular._UNITS[unit]            # noqa: SLF001
        if not (pct or "." in raw or abs(v) >= MIN_MAGNITUDE):
            continue
        # 光秃秃一个四位年份（「2026上半年实现…」）不是数据。跟表格那一侧
        # 用同一个判据——`_NOT_DATA` 那条要求后面紧跟「年 / 财年 / Q1」，
        # 真实笔记里「2026上半年」这种写法从它底下穿过去了。
        if not pct and not unit and blockcheck._looks_like_a_year(raw, v):   # noqa: SLF001
            continue
        out.append(v)
    return out


def numbers_from_tools(st: State) -> Verdict | None:
    """正文里的统计量追不追得到工具结果（计划 5.2，eda / analysis）。

    这两个模式的 task 都明写着「**所有数字都来自工具返回，不要自己算**」——
    所以「模型自己心算出来的合计」被报上来是**对的**，不是误伤。
    """
    if not has_tool_output(st):
        return None
    values = prose_statistics(st.content)
    if not values:
        return None
    bad = unsupported(values, tabular.numbers_in_text(sources(st)))
    if not bad:
        return None
    return Verdict(
        pick_dimension(st, "numbers_from_tools", "data_grounding"),
        f"正文里这几个数既不在工具返回的结果里、也不在笔记原文里：{_fmt(bad)}。"
        "这个模式的规矩是**所有数字都来自工具返回，不要自己算**——"
        "合计、均值、占比这类都要用 aggregate_table / describe_table / "
        "correlate_columns 算出来再写。下一轮取材料那一步补上这次调用；"
        "**算不出来就把这句话改成不带数字的说法，不要去动别的句子。**",
    )
