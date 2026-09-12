"""插入块的确定性检查：图是不是真的、结构合不合上下文。

这两件事都能用规则判准，就不该交给打分器去"感觉"——实测打分器给一份
**通篇假图**的产出打了 has_charts=2，因为它看到「柱状图：…」就以为有图。
"""

from __future__ import annotations

import re

# 假图：用文字描述了一张图，而不是给出 ```mermaid 代码块。
# 真实产出里长这样：
#   [柱状图：各渠道点击量  Kickstarter：12700；小红书：6720；官网：2790]
#   [散点图：曝光与下单，n=6，相关系数 r=0.9902]
# 后者还更糟——mermaid 根本没有散点图，那张图无论如何都不可能存在。
_FAKE_CHART = re.compile(
    r"[\[［(（]\s*(?:柱状图|条形图|折线图|饼图|散点图|直方图|图表|示意图)\s*[:：]"
    r"|^\s*(?:柱状图|折线图|饼图|散点图|直方图)\s*[:：]", re.M)
_HEADING = re.compile(r"^(#{1,6})\s+(\S.*)$", re.M)
_MERMAID = re.compile(r"```mermaid\n(.*?)```", re.S)


def fake_charts(block: str, limit: int = 3) -> list[str]:
    """块里"用文字描述的图"。有这个就说明它没真的调工具画。"""
    out = []
    for m in _FAKE_CHART.finditer(block or ""):
        line = (block[m.start():].split("\n", 1)[0]).strip()
        out.append(line[:80])
        if len(out) >= limit:
            break
    return out


def mermaid_blocks(text: str) -> list[str]:
    """抽出所有 ```mermaid 代码块的**内容**，按行去掉首尾空白后规范化。

    规范化只做空白，不动语法——比对的目的是判断这段代码是不是工具原样给的，
    模型顺手改一个数字或加一句 y 轴范围都必须能被看出来。
    """
    out = []
    for m in _MERMAID.finditer(text or ""):
        body = "\n".join(ln.rstrip() for ln in m.group(1).strip().split("\n"))
        out.append(body)
    return out


def unauthorized_charts(block: str, allowed: list[str], limit: int = 3) -> list[str]:
    """块里那些**不是工具产出**的 mermaid 图。

    这条检查是整套设计的底线：数字和图表语法由代码产出，模型只决定画什么。
    实测里模型学会了绕过它——照着工具结果的样子自己手写 mermaid，数字甚至
    是对的，但语法是它自创的（``y-axis "曝光" 0 --> 260000`` 带范围，而
    render_chart 从不写范围，因为写错了图就出不来）。数字对不代表图能渲染，
    也不代表下次它不会顺手改一个数。

    所以判据不是"看起来像不像"，是**跟工具返回的字符串一模一样**。
    """
    ok = set(allowed)
    return [b.split("\n", 2)[1][:70] if "\n" in b else b[:70]
            for b in mermaid_blocks(block) if b not in ok][:limit]


def chart_gap(block: str, allowed: list[str] | None = None) -> str:
    """图相关的确定性诊断；没问题返回空串。"""
    fake = fake_charts(block)
    if fake:
        return ("这一轮**没有真的画图**，只是用文字描述了图："
                + "；".join(fake)
                + "。必须调用 chart_column / render_chart / chart_from_text，"
                  "把它们返回的 ```mermaid 代码块**原样**放进正文——"
                  "工具返回的代码是验证过能渲染的。另外 mermaid 没有散点图，"
                  "两列的关系用相关系数说明，或者画成两条系列的折线/柱状。")
    if allowed is not None:
        bad = unauthorized_charts(block, allowed)
        if bad:
            return (f"正文里有 {len(bad)} 张 mermaid 图**不是工具生成的**"
                    f"（{'；'.join(bad)}）——是照着工具结果自己手写的。"
                    "手写的 mermaid 没经过验证，渲染不出来的写法（比如给 y-axis "
                    "加 `0 --> 260000` 这种范围）会让整张图变成一段报错。"
                    "要画什么由你定，**代码必须原样用工具返回的那一段**："
                    "想要的图工具没画，就再调一次 render_chart / chart_from_text，"
                    "不要自己补。")
    return ""


def heading_gap(before: str, block: str, *, max_new: int = 3) -> str:
    """插入块的标题结构跟上下文合不合。

    两条判据，都是从真实产出量出来的：
      · **层级**：光标前最近的标题是 `##`，插入块就不该出现 `##` 或更浅的——
        那是在跟原文的章节平级，把一节内容变成了并列的新章节。
      · **数量**：一段插入内容里塞 8 个 `###`，读起来是一篇独立报告，
        不是笔记里的一段。
    """
    prev = _HEADING.findall(before or "")
    depth = len(prev[-1][0]) if prev else 1
    mine = _HEADING.findall(block or "")
    if not mine:
        return ""
    problems = []
    too_shallow = [t for lvl, t in mine if len(lvl) <= depth]
    if too_shallow:
        problems.append(
            f"上文最近的标题是 {depth} 级，插入的内容里却有 {len(too_shallow)} 个"
            f"{depth} 级或更浅的标题（{'、'.join(too_shallow[:2])}）——"
            f"那会跟原文的章节平级，把这一段变成并列的新章节。"
            f"这里的标题最浅只能是 {depth + 1} 级。")
    if len(mine) > max_new:
        problems.append(
            f"一共写了 {len(mine)} 个小标题，太碎了——插进笔记里的是**一段内容**，"
            f"不是一篇独立报告。最多 {max_new} 个，图配一两句话就够，"
            f"不用每张图都起一个标题。")
    return " ".join(problems)


_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$", re.M)


def has_table(block: str) -> bool:
    """有没有一张 markdown 表：一行表头 + 紧跟的分隔行（`|---|---|`）。"""
    for m in _TABLE_SEP.finditer(block or ""):
        head_end = m.start()
        prev = (block[:head_end].rstrip("\n").split("\n") or [""])[-1]
        if "|" in prev:
            return True
    return False
