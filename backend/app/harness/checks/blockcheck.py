"""插入块的确定性检查：图是不是真的、结构合不合上下文。

这两件事都能用规则判准，就不该交给打分器去"感觉"——实测打分器给一份
**通篇假图**的产出打了 has_charts=2，因为它看到「柱状图：…」就以为有图。
"""

from __future__ import annotations

import difflib
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


# 用箭头链在正文里"画"的流程。真实产出（用户第 570 轮报的那段里就有一条）：
#   验证链路应按以下顺序记录：KOL 触达 → 进入 APP → 完成设备连接 → 持续查看数据 → 提交购买意向 → 实际下单。
# mermaid 的 flowchart 正好画这个，而且 chart_from_text 能生成。两个节点的（5G → 2.4G）
# 是在说一次变化，不是流程，不算；围栏代码块里的箭头也不算（第 592 轮）。
# 节点里不许有分号 / 句号：那是"三组条件—动作对"（录制未启动 → 检查权限；文件缺失 → 检查存储）
# 而不是一条顺序流程，画成 flowchart 反而更绕（318 篇真实笔记上验出来的唯一一个误报）
_ARROW_CHAIN = re.compile(r"(?:[^\n→>—;；。.]{1,40}(?:→|->|—>)){3,}")


def text_flow(text: str, limit: int = 2) -> list[str]:
    """正文里用箭头串起来的流程（≥4 个节点）。整篇已经有 mermaid 图就不报——
    那说明这一轮它知道该画图，剩下的箭头多半是图里画不下的旁注。"""
    body = _MERMAID.sub("", text or "")
    if "```" in body:                       # 别的代码块里的箭头也不算
        body = re.sub(r"```.*?```", "", body, flags=re.S)
    if _MERMAID.search(text or ""):
        return []
    out = []
    for m in _ARROW_CHAIN.finditer(body):
        out.append(" ".join(m.group(0).split())[:80])
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


# 手写也放行的那一种图：最简单的流程图。
#
# 「必须跟工具返回的字节一模一样」这条原本是对的——模型学会了照着工具结果
# 手写 mermaid，而它自创的语法（`y-axis "曝光" 0 --> 260000` 带范围）会让
# 整张图变成一段报错。但第 607 轮把四次真跑里模型写出来的 mermaid 全收集起来
# 看了一遍：**9 块全是 `graph TD` / `flowchart LR` 加几行 `A[x] --> B[y]`，
# 9 块全合法**。判据把九张有用的流程图全拒了，换来一个模型多半完成不了的
# 工具往返（写正文那一步没有工具）。
#
# 所以判据从「跟工具字节一致」放宽一格：**这一种形状，自己写的也算数**。
# 它的语法面小到可以确定性地判全——节点名、形状、箭头、箭头上的标签，再无
# 别的。xychart / pie / gantt / sequence 一概照旧必须工具产出：那些才是真会
# 写坏的地方，而且工具本来就画得出来。
#
# 标签里不许出现 `[](){}"|`：这些在 mermaid 里有语法含义，嵌在标签中间是
# 最常见的渲染失败原因，而它又是纯字符判断。
_FLOW_HEAD = re.compile(r"^(?:graph|flowchart)\s+(?:TD|TB|BT|LR|RL)\s*$")
_FLOW_NODE = r"[A-Za-z_][A-Za-z0-9_]*(?:\[\[[^\[\]{}()\"|]*\]\]|\[[^\[\]{}()\"|]*\]|\(\([^\[\]{}()\"|]*\)\)|\([^\[\]{}()\"|]*\)|\{[^\[\]{}()\"|]*\})?"
_FLOW_ARROW = r"(?:-{2,3}>|-{3}|-\.->|={2,3}>)(?:\|[^|]*\|)?"
_FLOW_LINE = re.compile(
    rf"^{_FLOW_NODE}(?:\s*{_FLOW_ARROW}\s*{_FLOW_NODE})+$")


def is_plain_flowchart(block: str) -> bool:
    """这块 mermaid 是不是「最简单的流程图」——手写也认的那一种。

    整块每一行都得认得出来才算：一行看不懂就说明里面有这个语法之外的东西，
    那就走工具那条路。空行忽略。
    """
    lines = [ln.strip() for ln in (block or "").strip().splitlines()]
    lines = [ln for ln in lines if ln]
    if len(lines) < 2 or not _FLOW_HEAD.match(lines[0]):
        return False
    return all(_FLOW_LINE.match(ln) for ln in lines[1:])


def unauthorized_charts(block: str, allowed: list[str], limit: int = 3) -> list[str]:
    """块里那些**不是工具产出**的 mermaid 图。

    这条检查是整套设计的底线：数字和图表语法由代码产出，模型只决定画什么。
    实测里模型学会了绕过它——照着工具结果的样子自己手写 mermaid，数字甚至
    是对的，但语法是它自创的（``y-axis "曝光" 0 --> 260000`` 带范围，而
    render_chart 从不写范围，因为写错了图就出不来）。数字对不代表图能渲染，
    也不代表下次它不会顺手改一个数。

    所以判据不是"看起来像不像"，是**跟工具返回的字符串一模一样**——
    只放一格：最简流程图（`is_plain_flowchart`）手写也算数，那一种的语法面
    小到可以确定性判全，而且真跑里模型想画的全是它。
    """
    ok = set(allowed)
    return [b.split("\n", 2)[1][:70] if "\n" in b else b[:70]
            for b in mermaid_blocks(block)
            if b not in ok and not is_plain_flowchart(b)][:limit]


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


# 顿号串起来的清单（≥3 项，每项 2–12 字）。整段查重（`drop_already_written`，difflib 0.62）
# 抓不到"同一组清单换个说法再列一遍"：两段各自还有别的内容，相似度被稀释到 0.4 左右。
# 把清单单独抽出来两两比，第 596 轮读产出时发现的：
#   「至少要补齐测试场景、测试时间、使用的硬件版本、异常表现、负责人和最终结论」
#   「这里需要补上测试场景、时间、硬件版本、异常表现、负责人、最终结论和接收记录」
_ITEM_LIST = re.compile(r"(?:[^、，。；：\n]{2,12}、){2,}[^、，。；：\n]{2,12}")
_IMG_ALT = re.compile(r"!\[[^\]]*\]\([^)]*\)")
LIST_DUP_RATIO = 0.7


def repeated_lists(text: str, fresh: str = "", limit: int = 2) -> list[tuple[str, str]]:
    """同一组清单被换个说法列了两遍。

    `fresh` 给了的话，只报**这一轮碰过**的那些——用户原来正文里就有的重复不该每轮都报一次。
    图片的 alt 文字跳过：两张图的提示词长得像是正常的（167 篇真实笔记上唯一的假阳性）。
    """
    body = _IMG_ALT.sub("", text or "")
    lists = [m.group(0) for m in _ITEM_LIST.finditer(body)]
    out: list[tuple[str, str]] = []
    for i, a in enumerate(lists):
        for b in lists[i + 1:]:
            if fresh and a not in fresh and b not in fresh:
                continue
            if difflib.SequenceMatcher(None, a, b).ratio() >= LIST_DUP_RATIO:
                out.append((a, b))
                if len(out) >= limit:
                    return out
    return out


# ---------------------------------------------------------------- 表格 ---
#
# 整块表：连着两行以上以 `|` 开头结尾的行。**末尾那一行后面可能没有换行**
# （表格就在正文结尾）——这条正则写死 `\n` 的那一版让 `603dca25403a` 那张
# 真实的表最后一整行落在匹配之外（台账批 7）。
_TABLE_BLOCK = re.compile(r"(?m)^(\|.*\|[ \t]*(?:\n|$)){2,}")
# 一个格子算不算「一个数」：整格就是数字（可带千分位、小数、百分号），
# **不做任何抽取**。「2026-09-18」「第 3 版」「约 40 台」一律不算——
# 判据宁可窄，一个格子里混着文字就说明它不是一个纯粹的数据格。
_NUM_CELL = re.compile(r"^-?[\d,]+(?:\.\d+)?\s*[%％]?$")


def table_blocks(text: str) -> list[str]:
    return [m.group(0) for m in _TABLE_BLOCK.finditer(text or "")]


def table_column_mismatch(text: str) -> bool:
    """markdown 表的表头 / 分隔行 / 数据行列数对不对得上。

    `table_validity` 的达标线原话就是「header and rows have matching column
    counts」——**那是一句纯粹能用代码判准的话**，而在批 16 之前仓里没有任何
    一处在判它：`structure.table_present` 只查"有没有表"，`has_table` 只查
    "表头下面有没有分隔行"，**两者都不数列**。

    这份实现原来住在 `scripts/dimension_sensitivity_bench.py` 里（批 12 写的，
    用途是自验植入器真的把列数弄错了）。搬进来之后 bench 反过来 import 它，
    **一份实现两个用途**——bench 那边留一份副本的话，"植入器植没植进去"和
    "生产判不判得出来"就会各判各的。
    """
    for block in table_blocks(text):
        rows = [r for r in block.strip().split("\n") if r.strip()]
        widths = {len(r.strip().strip("|").split("|")) for r in rows}
        if len(widths) > 1:
            return True
    return False


def table_numbers(text: str) -> list[float]:
    """表里那些**整格就是一个数**的格子。表头行和分隔行不算。

    百分号原样剥掉（`38%` → 38.0），换算留给调用方——比对那一侧要同时试
    `v` 和 `v/100`，在这里定死会把「源表里写 0.38」那一档判成无据。
    """
    out: list[float] = []
    for block in table_blocks(text):
        rows = [r for r in block.strip().split("\n") if r.strip()]
        for row in rows[1:]:                     # 第一行是表头
            if set(row.replace("|", "").strip()) <= set("-: \t"):
                continue                          # 分隔行
            for cell in row.strip().strip("|").split("|"):
                cell = cell.strip()
                if not _NUM_CELL.match(cell):
                    continue
                try:
                    v = float(cell.rstrip("%％").replace(",", ""))
                except ValueError:
                    continue
                if _looks_like_a_year(cell, v):
                    continue
                out.append(v)
    return out


def _looks_like_a_year(raw: str, value: float) -> bool:
    """光秃秃一个四位整数，落在 1900–2100：当年份看，不当数据。

    **这是"判据宁可窄"的那一刀**：表格里真有一列是年份时，它每一格都会被
    当成"查无出处的数字"报上去，而报错的代价是模型去删一整列真内容。
    带小数点、带百分号、带千分位的一律不算年份——那些形状不会是年份。
    """
    return (value.is_integer() and 1900 <= value <= 2100
            and raw.strip().isdigit() and len(raw.strip()) == 4)


# ------------------------------------------------------------ mermaid ---
#
# 工具拼出来的三种形状（`tools/blocks.py`）：
#   pie        `pie title X` + `    "标签" : 数值`
#   xychart    `xychart-beta` + title / x-axis [..] / y-axis ".." + `bar [..]`
#   flowchart  `flowchart LR` + 节点和箭头（没有数值）
# 这里只认**数值位**：x 轴标签、标题、轴名一律不取。
# 理由是"位置即判据"——一个数出现在 `bar [...]` 里，它就是数据；
# 出现在标题里（「2026 年复盘」）它不是。
_PIE_SLICE = re.compile(r'^\s*"[^"]*"\s*:\s*(-?[\d.]+)\s*$')
_XY_SERIES = re.compile(r"^\s*(?:bar|line)\s*\[([^\]]*)\]\s*$")
_XY_XAXIS = re.compile(r"^\s*x-axis\s*\[([^\]]*)\]\s*$")
_XY_YAXIS = re.compile(r'^\s*y-axis\s+"([^"]*)"\s*$')
_XY_TITLE = re.compile(r'^\s*title\s+"([^"]*)"\s*$')


def chart_numbers(block: str) -> list[float]:
    """一块 mermaid 里的**数值位**上的数。"""
    out: list[float] = []
    for line in (block or "").splitlines():
        m = _PIE_SLICE.match(line)
        if m:
            out += _floats([m.group(1)])
            continue
        m = _XY_SERIES.match(line)
        if m:
            out += _floats(m.group(1).split(","))
    return out


def _floats(raw: list[str]) -> list[float]:
    out = []
    for piece in raw:
        piece = piece.strip().strip('"')
        try:
            v = float(piece.replace(",", ""))
        except ValueError:
            continue
        if _looks_like_a_year(piece, v):
            continue
        out.append(v)
    return out


def chart_shape(block: str) -> dict:
    """一块 mermaid 的可读性画像：类型、标题、类目、系列条数、轴名。

    只描述，不判断——判断在 `checks/charts.chart_readable` 里，
    那样阈值改动跟解析改动能分开测。
    """
    lines = [ln for ln in (block or "").strip().splitlines() if ln.strip()]
    head = lines[0].strip() if lines else ""
    shape: dict = {"kind": "", "title": "", "categories": [], "series": 0,
                   "axis": "", "nodes": 0}
    if head.startswith("pie"):
        shape["kind"] = "pie"
        shape["title"] = head[3:].replace("title", "", 1).strip()
        shape["categories"] = [ln.split('"')[1] for ln in lines[1:]
                               if ln.count('"') >= 2 and _PIE_SLICE.match(ln)]
        shape["series"] = 1
        return shape
    if head.startswith("xychart"):
        shape["kind"] = "xy"
        for ln in lines[1:]:
            m = _XY_TITLE.match(ln)
            if m:
                shape["title"] = m.group(1)
            m = _XY_XAXIS.match(ln)
            if m:
                shape["categories"] = [x.strip().strip('"')
                                       for x in m.group(1).split(",") if x.strip()]
            m = _XY_YAXIS.match(ln)
            if m:
                shape["axis"] = m.group(1)
            if _XY_SERIES.match(ln):
                shape["series"] += 1
        return shape
    if head.startswith(("graph", "flowchart")) or head.startswith("---"):
        shape["kind"] = "flow"
        shape["nodes"] = sum(1 for ln in lines if "-->" in ln or "---" in ln) + 1
        return shape
    return shape
