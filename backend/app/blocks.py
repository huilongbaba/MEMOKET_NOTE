"""把结构化数据拼成可以直接插进笔记的 markdown / mermaid 块。

**这里是「智能插图/智能表格」不出语法错误的原因**：图表语法由代码拼，模型
只负责决定画什么、用哪些数据。反过来让模型自己写 mermaid，用户已经碰到过
「mermaid 语法错误，自动修复也没成功」——而那种错一旦出现，笔记里就留下一块
渲染不出来的死代码。

规则来自 mermaid 的实际解析器行为，踩过的坑写在各函数里。
"""

from __future__ import annotations

import re

# mermaid 的标签里这些字符会把解析器搞崩：引号截断字符串、方括号和圆括号
# 被当成节点形状、分号和换行截断语句。统一换成安全字符，不做转义——转义
# 在不同 mermaid 版本里行为不一致，换掉最稳。
_LABEL_BAD = re.compile(r'["\'\[\]{}()<>;|\n\r]')


def safe_label(s: str, limit: int = 28) -> str:
    out = _LABEL_BAD.sub(" ", str(s)).strip()
    out = re.sub(r"\s+", " ", out)
    return (out[:limit] + "…") if len(out) > limit else (out or "未命名")


def markdown_table(columns: list[str], rows: list[list[str]], limit: int = 50) -> str:
    """行数超过 limit 就截断并注明——把两千行贴进笔记没人会读，而且会把
    后续每一轮 harness 的上下文撑爆。"""
    cols = [safe_label(c, 40).replace("|", "/") for c in columns] or ["列"]
    body = rows[:limit]
    lines = ["| " + " | ".join(cols) + " |",
             "|" + "---|" * len(cols)]
    for r in body:
        cells = [str(x).replace("|", "/").replace("\n", " ") for x in r[:len(cols)]]
        cells += [""] * (len(cols) - len(cells))
        lines.append("| " + " | ".join(cells) + " |")
    if len(rows) > limit:
        lines.append(f"\n> 共 {len(rows)} 行，这里只列出前 {limit} 行。")
    return "\n".join(lines)


def _fmt(v: float) -> str:
    """mermaid 的数值不能带千分位逗号，整数也不要拖一个 .0。"""
    return str(int(v)) if float(v).is_integer() else f"{float(v):.4g}"


def mermaid_pie(title: str, data: list[tuple[str, float]], limit: int = 8) -> str:
    """饼图。超过 limit 项就把剩下的并成「其他」——十几个扇区谁也看不出比例。"""
    items = [(safe_label(k), float(v)) for k, v in data if float(v) > 0]
    items.sort(key=lambda kv: -kv[1])
    if len(items) > limit:
        rest = sum(v for _k, v in items[limit:])
        items = items[:limit] + [("其他", rest)]
    lines = [f'pie title {safe_label(title, 40)}']
    lines += [f'    "{k}" : {_fmt(v)}' for k, v in items]
    return "```mermaid\n" + "\n".join(lines) + "\n```"


def mermaid_xy(title: str, labels: list[str], values: list[float],
               series: str = "数值", kind: str = "bar", limit: int = 24,
               extra: list[tuple[str, list[float], str]] | None = None) -> str:
    """柱状/折线图（xychart-beta），**支持多条系列**。

    ``extra`` 是额外的系列，每项是 ``(名字, 数值, kind)``。多系列是分组对比的
    正确画法：「三月 vs 四月各渠道曝光」应该是 x 轴三个渠道 + 两条柱，而不是
    把「月份×渠道」压成一维的六根柱子——后者读者得自己在脑子里再分一次组。
    （实测 mermaid 支持同一张图里多条 bar、以及 bar 和 line 混排。）

    坑：x 轴的分类标签必须整体写成 ``[a, b, c]``，**每一项都要带引号**，
    中文和空格不带引号会解析失败；y 轴不写范围时 mermaid 自己算，写错反而
    出不来，所以这里不写。
    """
    n = min(len(labels), len(values), limit)
    # x 轴标签的长度按**项数**给：3 个类目时每个能写得下二十来字，
    # 十几个类目就得短。写死 12 的后果实测到了：「三月Kickstarter」被截成
    # 「三月Kickstarte…」——省略号本身还占位置，读者反而认不出是哪个渠道。
    cap = 24 if n <= 4 else (16 if n <= 8 else 10)
    xs = [safe_label(x, cap) for x in labels[:n]] or ["无数据"]
    ys = [float(v) for v in values[:n]] or [0.0]
    kind = "line" if kind == "line" else "bar"
    names = [series] + [nm for nm, _v, _k in (extra or [])]
    lines = [
        "xychart-beta",
        f'    title "{safe_label(title, 40)}"',
        "    x-axis [" + ", ".join(f'"{x}"' for x in xs) + "]",
        # 多系列时 y 轴写成「甲 / 乙」，不然读者不知道哪条是哪条
        f'    y-axis "{safe_label(" / ".join(names), 30)}"',
        f"    {kind} [" + ", ".join(_fmt(v) for v in ys) + "]",
    ]
    for _nm, vs, k in (extra or []):
        vv = [float(v) for v in vs[:n]]
        vv += [0.0] * (n - len(vv))
        lines.append(f"    {'line' if k == 'line' else 'bar'} ["
                     + ", ".join(_fmt(v) for v in vv) + "]")
    return "```mermaid\n" + "\n".join(lines) + "\n```"


def mermaid_flow(title: str, steps: list[str], kind: str = "LR") -> str:
    """流程图。节点 id 用 N0/N1… 自己生成，**不要拿标签当 id**——中文和标点
    当 id 会直接解析失败。"""
    ids = [f"N{i}" for i in range(len(steps))]
    lines = [f"flowchart {'TD' if kind == 'TD' else 'LR'}"]
    if title:
        lines.insert(0, f"---\ntitle: {safe_label(title, 40)}\n---")
    for i, (nid, label) in enumerate(zip(ids, steps)):
        lines.append(f'    {nid}["{safe_label(label)}"]')
        if i:
            lines.append(f"    {ids[i - 1]} --> {nid}")
    return "```mermaid\n" + "\n".join(lines) + "\n```"
