"""从笔记里认出表格数据，并对它做**确定性**的统计。

这是「数据可视化 / 智能数据分析」能不能信的分界线：

    模型决定**算什么、画什么**；数字和图表语法由代码算出来、拼出来。

反过来做（让模型自己算平均值、自己写 mermaid 语法）是这个功能最容易翻车的
地方——数字会被编，图表语法会有错（用户已经碰到过"mermaid 语法错误，自动
修复也没成功"）。所以这里全是纯函数：解析、统计、渲染，不碰 LLM，可单测。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

# markdown 表格：至少两行，第二行是 |---|---| 这种分隔行
_MD_TABLE = re.compile(
    r"(?:^\|.*\|[ \t]*\n)"          # 表头
    r"(?:^\|[\s:|-]+\|[ \t]*\n)"    # 分隔行
    r"(?:^\|.*\|[ \t]*\n?)+",       # 数据行
    re.M)
# ```csv / ```tsv 代码块
_FENCED = re.compile(r"^```(csv|tsv)[ \t]*\n(.*?)^```", re.M | re.S)
_NUM = re.compile(r"^-?[\d,]+(?:\.\d+)?%?$")


@dataclass
class Table:
    """一份表格数据。``index`` 是它在笔记里出现的顺序，工具用它定位。

    ``start``/``end`` 是它在正文里的字符位置。**用来判断哪张表离光标最近**——
    用户在某个位置按 `/数据可视化`，要分析的是他跟前那张表，不是全文里随便
    一张。没有位置信息的话，一篇有五张表的笔记，模型只能瞎猜一个编号。
    """

    index: int
    source: str                 # markdown / csv / tsv
    columns: list[str]
    rows: list[list[str]]
    start: int = 0
    end: int = 0

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.rows), len(self.columns)

    def column(self, name: str) -> list[str]:
        if name not in self.columns:
            raise KeyError(name)
        i = self.columns.index(name)
        return [r[i] if i < len(r) else "" for r in self.rows]


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def find_tables(text: str) -> list[Table]:
    """把笔记里所有表格找出来，按出现顺序编号。

    同时认 markdown 表格和 ```csv/```tsv 代码块——用户手打的、从别处粘的、
    以及上一轮 AI 生成的表格，都能被后面的分析工具直接拿来用。
    """
    out: list[Table] = []
    for m in _MD_TABLE.finditer(text or ""):
        lines = [ln for ln in m.group(0).splitlines() if ln.strip()]
        if len(lines) < 3:
            continue
        cols = _cells(lines[0])
        rows = [_cells(ln) for ln in lines[2:]]
        rows = [r for r in rows if any(c for c in r)]
        if cols and rows:
            out.append(Table(len(out), "markdown", cols, rows, m.start(), m.end()))
    for m in _FENCED.finditer(text or ""):
        sep = "\t" if m.group(1) == "tsv" else ","
        lines = [ln for ln in m.group(2).splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        cols = [c.strip() for c in lines[0].split(sep)]
        rows = [[c.strip() for c in ln.split(sep)] for ln in lines[1:]]
        out.append(Table(len(out), m.group(1), cols, rows, m.start(), m.end()))
    return out


def to_number(cell: str) -> float | None:
    """``1,234``、``12.5%``、``-3`` 都算数字；``暂无``、空串不算。

    百分号**保留原值**（12.5% → 12.5）而不是除以 100：用户看到的表格里写的
    是 12.5，统计结果也该是同一套刻度，否则对不上。
    """
    s = (cell or "").strip()
    if not s or not _NUM.match(s):
        return None
    try:
        return float(s.rstrip("%").replace(",", ""))
    except ValueError:
        return None


def numeric(values: list[str]) -> list[float]:
    return [v for v in (to_number(x) for x in values) if v is not None]


def is_numeric_column(values: list[str]) -> bool:
    """一列里过半的非空格子能解析成数字，就当数值列。

    不要求全部：真实表格里常有「暂无」「-」这类占位，一个占位就把整列判成
    文本，EDA 就什么都算不出来了。
    """
    filled = [v for v in values if (v or "").strip()]
    if not filled:
        return False
    return len(numeric(filled)) * 2 >= len(filled)


def quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return math.nan
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def describe_column(name: str, values: list[str]) -> dict:
    """一列的画像。数值列给分布，文本列给取值分布。"""
    filled = [v for v in values if (v or "").strip()]
    base = {"列": name, "总行数": len(values), "缺失": len(values) - len(filled)}
    if is_numeric_column(values):
        nums = sorted(numeric(filled))
        n = len(nums)
        mean = sum(nums) / n
        var = sum((x - mean) ** 2 for x in nums) / n if n > 1 else 0.0
        return {**base, "类型": "数值", "有效值": n, "最小": nums[0], "最大": nums[-1],
                "均值": round(mean, 4), "中位数": round(quantile(nums, 0.5), 4),
                "P25": round(quantile(nums, 0.25), 4), "P75": round(quantile(nums, 0.75), 4),
                "标准差": round(math.sqrt(var), 4), "求和": round(sum(nums), 4)}
    counts: dict[str, int] = {}
    for v in filled:
        counts[v] = counts.get(v, 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    return {**base, "类型": "文本", "不同取值": len(counts),
            "最常见": [{"值": k, "次数": v} for k, v in top]}


AGGS = ("sum", "mean", "count", "max", "min", "median")


def aggregate(table: Table, group_by: str, value: str, agg: str) -> list[tuple[str, float]]:
    """按某一列分组，对另一列做聚合。``agg`` 取 AGGS 之一。"""
    if agg not in AGGS:
        raise ValueError(f"不支持的聚合方式 {agg!r}，可用：{'、'.join(AGGS)}")
    keys = table.column(group_by)
    vals = table.column(value)
    buckets: dict[str, list[float]] = {}
    for k, v in zip(keys, vals):
        key = (k or "").strip() or "（空）"
        if agg == "count":
            buckets.setdefault(key, []).append(1.0)
            continue
        num = to_number(v)
        if num is not None:
            buckets.setdefault(key, []).append(num)
    out: list[tuple[str, float]] = []
    for k, xs in buckets.items():
        if not xs:
            continue
        if agg in ("sum", "count"):
            r = sum(xs)
        elif agg == "mean":
            r = sum(xs) / len(xs)
        elif agg == "max":
            r = max(xs)
        elif agg == "min":
            r = min(xs)
        else:
            r = quantile(sorted(xs), 0.5)
        out.append((k, round(r, 4)))
    return sorted(out, key=lambda kv: -kv[1])


def correlate(table: Table, x: str, y: str) -> dict:
    """两列的皮尔逊相关。**只用两列都是数字的那些行**，并把用了几行说清楚
    ——样本量是判断这个系数值不值得信的前提，不能只给一个光秃秃的 r。"""
    xs_raw, ys_raw = table.column(x), table.column(y)
    pairs = [(a, b) for a, b in ((to_number(p), to_number(q)) for p, q in zip(xs_raw, ys_raw))
             if a is not None and b is not None]
    n = len(pairs)
    if n < 3:
        return {"x": x, "y": y, "n": n, "r": None,
                "说明": "两列都是数字的行不足 3 行，算不出有意义的相关"}
    mx = sum(a for a, _ in pairs) / n
    my = sum(b for _, b in pairs) / n
    cov = sum((a - mx) * (b - my) for a, b in pairs)
    vx = math.sqrt(sum((a - mx) ** 2 for a, _ in pairs))
    vy = math.sqrt(sum((b - my) ** 2 for _, b in pairs))
    if not vx or not vy:
        return {"x": x, "y": y, "n": n, "r": None, "说明": "有一列没有变化，相关无定义"}
    return {"x": x, "y": y, "n": n, "r": round(cov / (vx * vy), 4)}


def histogram(values: list[str], bins: int = 8) -> tuple[list[str], list[float]]:
    """数值列的分布：分箱之后返回 (区间标签, 每箱个数)。

    **这是数据可视化里最核心的一张图**，而 mermaid 没有直方图——用 xychart 的柱状图
    画分箱结果就是直方图。分箱由代码算，模型只决定"要看哪一列的分布"。

    箱数按数据量收敛（少于 bins*2 个点时用 √n），不然十几个点分八箱、
    每箱一两个，看不出任何形状。
    """
    nums = sorted(numeric(values))
    if len(nums) < 2:
        return [], []
    lo, hi = nums[0], nums[-1]
    if hi == lo:
        return [_fmt_edge(lo)], [float(len(nums))]
    n = max(2, min(bins, int(len(nums) ** 0.5) if len(nums) < bins * 2 else bins))
    step = (hi - lo) / n
    counts = [0.0] * n
    for v in nums:
        idx = min(n - 1, int((v - lo) / step))
        counts[idx] += 1
    labels = [f"{_fmt_edge(lo + i * step)}~{_fmt_edge(lo + (i + 1) * step)}" for i in range(n)]
    return labels, counts


def _fmt_edge(v: float) -> str:
    """分箱边界的显示。整数就不要拖小数，大数用 k/M 收短——区间标签要挤进
    x 轴，写成 42000.0000 就全糊在一起了。"""
    a = abs(v)
    if a >= 1_000_000:
        return f"{v / 1_000_000:.1f}M".replace(".0M", "M")
    if a >= 1000:
        return f"{v / 1000:.1f}k".replace(".0k", "k")
    return str(int(v)) if float(v).is_integer() else f"{v:.4g}"


def nearest(tables: list[Table], cursor: int) -> Table | None:
    """离光标最近的那张表。表内的位置距离算 0。"""
    if not tables:
        return None
    def dist(t: Table) -> int:
        if t.start <= cursor <= t.end:
            return 0
        return t.start - cursor if cursor < t.start else cursor - t.end
    return min(tables, key=dist)


def distance(t: Table, cursor: int) -> int:
    if t.start <= cursor <= t.end:
        return 0
    return t.start - cursor if cursor < t.start else cursor - t.end


# 正文里的数字：认「42000」「42,000」「4.2万」「1.5亿」「3千」这些写法。
# 中文数量词必须认——笔记里几乎没人写「42000」，都写「4.2 万」。
_UNITS = {"万": 1e4, "萬": 1e4, "亿": 1e8, "億": 1e8, "千": 1e3, "百": 1e2,
          "k": 1e3, "K": 1e3, "m": 1e6, "M": 1e6, "w": 1e4, "W": 1e4}
_TEXT_NUM = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s*([万萬亿億千百kKmMwW])?")


def numbers_in_text(text: str) -> set[float]:
    """正文里出现过的所有数值（含中文数量词换算）。

    用来验证「模型从文字里读出来的数」是不是真的写在原文里。抽取是语义判断
    （知道「4.2 万」对应的是「官网曝光」），**数值对不对则由代码验证**——
    模型抄错一位数，图就是错的，而错的图比没有图更糟。
    """
    out: set[float] = set()
    for m in _TEXT_NUM.finditer(text or ""):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        out.add(v)
        if m.group(2):
            out.add(v * _UNITS[m.group(2)])
    return out


def unsupported_numbers(text: str, values: list[float], *, rel: float = 0.005) -> list[float]:
    """这些数里，哪些在正文里找不到出处。

    ``rel`` 容忍相对误差：正文写「4.2 万」，模型给 42000 是对的；写「约 4 万」
    给 42000 就不该放行。0.5% 足够覆盖小数点表示的差异，又拦得住抄错一位。
    """
    have = numbers_in_text(text)
    bad: list[float] = []
    for v in values:
        if any(abs(v - h) <= max(rel * abs(v), 1e-9) for h in have):
            continue
        bad.append(v)
    return bad


# 一句话的边界：中文句号/问号/叹号/分号，以及换行。逗号不算——
# 「4 台服务器，每台 8 卡」拆开就看不出这两个数是一回事了。
_SENT_END = re.compile(r"[。！？；!?;]+|\n+")

# 「有数字」不等于「有可画的数」：引用 id（[terrence-1462-9F5]）、日期（8 月 5 日、2026-08-05）、
# 序数（第 5 位）、链接里的数字都不是量。实拍数据可视化把「第 5、10、15 位用户」画成柱子，
# 就是因为这一层没过滤（第 153 轮）。
_NOT_A_QUANTITY = (
    re.compile(r"\[[A-Za-z][A-Za-z0-9_-]*-(?:\d+|[0-9a-f]{12})-[0-9A-Fa-f]+\]"),   # 引用 id
    re.compile(r"https?://\S+"),
    re.compile(r"\d{4}\s*[-/年.]\s*\d{1,2}(?:\s*[-/月.]\s*\d{1,2}\s*日?)?"),        # 2026-08-05 / 2026 年 8 月
    re.compile(r"\d{1,2}\s*月\s*\d{1,2}\s*[日号]?"),                                # 8 月 5 日
    re.compile(r"\d{1,2}\s*[日号]\b|\d{1,2}\s*[日号](?=[^\d])"),                    # 5 号
    re.compile(r"第\s*\d+(?:\s*[、,，/和及]\s*\d+)*"),                              # 第 5 位 / 第 5、10、15 位
    re.compile(r"[A-Za-z]+\d+[A-Za-z0-9]*"),                                        # Q3、iOS16、F1
)


def has_quantity(sentence: str) -> bool:
    """去掉引用 id / 日期 / 序数 / 链接 / 型号之后还剩数字，才算「这句里有可画的数」。"""
    s = sentence
    for pat in _NOT_A_QUANTITY:
        s = pat.sub(" ", s)
    return any(ch.isdigit() for ch in s)


def sentences_with_numbers(text: str, cursor: int, radius: int = 1200) -> list[str]:
    """光标前后 ``radius`` 字以内、**含数字的句子**，按到光标的距离排序。

    做成"返回原句"而不是"返回数值"，是因为模型需要的是**标签和单位**：
    单看 `{10, 75, 98}` 谁也不知道 10 是倍数、75 和 98 是百分比，画出来
    就是三根量纲不同的柱子挤在一根轴上。原句里写着「效率提升 10 倍、
    成本降幅 75%」，这个信息不能丢。

    表格里的行也含数字，但那是 find_tables 的活儿，这里排除掉——不然
    一张表会被拆成十几个"句子"淹掉正文。
    """
    text = text or ""
    if not text.strip():
        return []
    lo, hi = max(0, cursor - radius), min(len(text), cursor + radius)
    spans = [(tb.start, tb.end) for tb in find_tables(text)]

    # 自己切句而不是 re.split：split 会把分隔符吃掉，偏移量就对不上了，
    # 而这里**全靠偏移量算到光标的距离**。
    bounds = [lo]
    for m in _SENT_END.finditer(text, lo, hi):
        bounds.append(m.end())
    bounds.append(hi)

    out: list[tuple[int, str]] = []
    for a, b in zip(bounds, bounds[1:]):
        if b <= a:
            continue
        s = text[a:b].strip()
        if len(s) < 6 or not has_quantity(s):
            continue
        if any(ts <= a <= te for ts, te in spans):     # 表格内部的行不算正文
            continue
        d = 0 if a <= cursor <= b else min(abs(cursor - a), abs(cursor - b))
        out.append((d, s))
    out.sort(key=lambda x: x[0])
    seen: list[str] = []
    for _d, s in out:
        if s not in seen:
            seen.append(s)
    return seen


# 数字后面紧跟的单位：`%`、`倍`、`台`、`亿参数`、`公里`…
# 只取紧邻的那几个字，中间隔了标点就算取不到——「1.79）」后面是括号，
# 宁可认成"未知"也不要瞎猜，未知不参与一致性判断。
_UNIT_AFTER = re.compile(r"\s*(%|％|[\u4e00-\u9fffA-Za-z]{1,4})")


def unit_near(text: str, value: float, cursor: int, *, rel: float = 0.005) -> str:
    """这个数值**离光标最近的那次出现**后面紧跟的单位；取不到返回空串。

    必须限定"离光标最近的那次"：一篇三万字的笔记里「10」出现几十次，后面
    跟着"倍""秒""%""月"什么都有，全收一遍等于没有判据（实测就是这么废掉的）。
    模型画的是光标跟前那段话里的数，判据也该取那一处。
    """
    best, bestd = "", None
    for m in _TEXT_NUM.finditer(text or ""):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if m.group(2):
            v *= _UNITS[m.group(2)]
        if abs(v - value) > max(rel * abs(value), 1e-9):
            continue
        d = abs(m.start() - cursor)
        if bestd is None or d < bestd:
            u = _UNIT_AFTER.match(text, m.end())
            best, bestd = (u.group(1) if u else ""), d
    return best


def mixed_units(text: str, values: list[float], cursor: int) -> dict[str, list[float]]:
    """这组数在光标附近带了几种单位。返回 {单位: [数值…]}，只含**取得到**单位的。

    多于一种就是量纲混了，画进一张图柱子高度之间没有意义——实测抓到过
    「效率提升 10 倍」和「576 台服务器」画成同一排柱子。取不到单位的数不
    参与判断：宁可漏判也不要因为一个右括号误拦一张对的图。
    """
    by: dict[str, list[float]] = {}
    for v in values:
        u = unit_near(text, v, cursor)
        if u:
            by.setdefault(u, []).append(v)
    return by if len(by) > 1 else {}


_MD_HEADING = re.compile(r"^#{1,6} ", re.M)


def headings_between(text: str, cursor: int, start: int, end: int) -> int:
    """光标和一张表之间隔着几个 markdown 标题。

    标题是**明确的话题边界**，比字数距离硬：跨过一个 `##` 就是另一件事了，
    哪怕它只在两百字外。反过来，同一节里的表隔得再远也还是同一件事。
    """
    lo, hi = (cursor, start) if cursor < start else (end, cursor)
    if hi <= lo:
        return 0
    return len(_MD_HEADING.findall(text or "", lo, hi))


def _sentence_span(text: str, pos: int) -> tuple[int, int]:
    """pos 所在句子的起止。句边界用 _SENT_END，跟 sentences_with_numbers 一致。"""
    a = 0
    for m in _SENT_END.finditer(text, 0, pos):
        a = m.end()
    m2 = _SENT_END.search(text, pos)
    return a, (m2.end() if m2 else len(text))


def _occurrences(text: str, value: float, rel: float) -> list[tuple[int, str]]:
    """这个数值在正文里的每一次出现：(位置, 紧跟的单位或空串)。"""
    out = []
    for m in _TEXT_NUM.finditer(text or ""):
        try:
            got = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if m.group(2):
            got *= _UNITS[m.group(2)]
        if abs(got - value) > max(rel * abs(value), 1e-9):
            continue
        a = _UNIT_AFTER.match(text, m.end())
        out.append((m.start(), a.group(1) if a else ""))
    return out


def without_unit(text: str, values: list[float], unit: str,
                 *, rel: float = 0.005) -> list[float]:
    """这些数里，哪些不该画进这张「单位是 unit」的图。

    两条都得挡住，而它们互相拉扯：

    · **编造的对照值**。实测模型给一张单值图凑对照，写「传统方案 = 1 倍」——
      原文根本没有「1 倍」。光验"这个数出现过"拦不住：三万字里「1」出现
      48 次，随便一个数都有出处。
    · **省了单位的同组项**。原文写「昇腾 38%（…沐曦 1.79）」，最后一项省了
      百分号，那是行文习惯。拒掉它会让沐曦从图里消失，而一组数据里少一项
      比多一项更糟。

    区别在**同不同句**：1.79 跟那几个 % 写在同一句里，编造的 1 不跟任何一个
    带「倍」的数同句。所以判据是：带对单位的直接过；没带的，只有跟某个过了的
    数同句才过。
    """
    u = (unit or "").strip()
    if not u:
        return []
    occ = {v: _occurrences(text, v, rel) for v in values}
    spans = [_sentence_span(text, pos) for v in values
             for pos, got in occ[v] if got == u]
    # **没有一个值带着这个单位时，这条判据不生效。** 原文常常压根不写单位
    # （「三月 100，四月 120」），那时"谁不带 u"对每个值都成立，整张图会被
    # 全拒。判据要抓的是"混进来一个不属于这组的数"，前提是这组里有个锚点。
    if not spans:
        return []
    bad = []
    for v in values:
        if any(got == u for _p, got in occ[v]):
            continue
        if any(a <= p <= b for p, _g in occ[v] for a, b in spans):
            continue
        bad.append(v)
    return bad
