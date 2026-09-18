"""阶段 5：有 oracle 的那三个模式（批 16）。

[IND] §2–3 的论断：图表 / 表格 / 分析三个模式**本来有执行 oracle**——
「每个数字都能追到源表」是**一次精确比对，不是一次判断**，而我们把它交给了
一个连源表都没给它看的打分模型（实测 `data_grounding` 2/2 满分）。

**这个文件是这一批的主要验收**，而不是 bench：批 11/13 反复记着，图表那一组
只有 1 篇真实用户语料带图、1 篇带表，而那篇的表每个格子都是占位符、那张
mermaid 本身就是坏的——**bench 上量不出可信的跨篇结论**。所以判据的正确性
靠单测 + 构造用例钉，真实语料只用来量一件事：**零误伤**（最后一节）。

判据窄在哪，逐条对应下面的「不许报」那一组。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from app.harness import modes
from app.harness.agent_loop import ToolTrace
from app.harness.checks import blockcheck, charts, numbers, structure
from app.harness.state import State
from app.harness.tools import ToolContext

TOOL_TABLE = (
    "list_tables 返回：\n"
    "| 渠道 | 点击 | 下单 |\n|---|---|---|\n"
    "| Kickstarter | 12700 | 214 |\n| 小红书 | 6720 | 98 |\n| 官网 | 2790 | 37 |\n")
CHART_FROM_TOOL = ("```mermaid\n"
                   "xychart-beta\n"
                   '    title "各渠道点击"\n'
                   '    x-axis ["Kickstarter", "小红书", "官网"]\n'
                   '    y-axis "点击"\n'
                   "    bar [12700, 6720, 2790]\n"
                   "```")


def _st(mode: str, content: str, *, note: str = "", facts: tuple[str, ...] = (TOOL_TABLE,),
        charts_out: tuple[str, ...] = ()) -> State:
    st = State(mode=modes.BLOCK[mode],
               ctx=ToolContext(user="u", note_id="n", content=note))
    st.content = content
    st.facts = list(facts)
    st.charts = list(charts_out)
    st.trace = ToolTrace(calls=[("list_tables", {}, TOOL_TABLE)] if facts else [])
    return st


# ------------------------------------------------ 5.1 图 / 表里的数 · 抓得住 ---

def test_图里的数就是工具返回的那几个时不报():
    assert numbers.chart_numbers_grounded(
        _st("chart", CHART_FROM_TOOL, charts_out=(CHART_FROM_TOOL,))) is None


def test_图里改掉一位数就报():
    """**这就是这条判据存在的理由**：`charts_from_tools` 只管「这段 mermaid 是不是
    工具原样返回的」，而模型学会过照抄工具输出再顺手改一个数——语法一模一样，
    那条判据放行。"""
    dirty = CHART_FROM_TOOL.replace("12700", "17200")
    v = numbers.chart_numbers_grounded(_st("chart", dirty))
    assert v is not None and "17200" in v.message
    assert v.dimension == "data_grounding"


def test_表格里编出来的格子会报():
    dirty = ("| 渠道 | 点击 |\n|---|---|\n| Kickstarter | 12700 |\n"
             "| 抖音 | 8450 |\n")          # 8450 哪儿都没有
    v = numbers.chart_numbers_grounded(_st("table", dirty))
    assert v is not None and "8450" in v.message


def test_饼图的数值位也算数():
    pie = '```mermaid\npie title 渠道占比\n    "甲" : 9999\n```'
    assert numbers.chart_numbers_grounded(_st("chart", pie)) is not None


def test_没有工具输出时一律不判():
    """手上没有 oracle 时「查无出处」和「无从判断」分不开。
    那一档该由 `charts_from_tools` / `table_present` 说「你还没调工具」。"""
    dirty = CHART_FROM_TOOL.replace("12700", "17200")
    assert numbers.chart_numbers_grounded(_st("chart", dirty, facts=())) is None
    assert numbers.numbers_from_tools(_st("eda", "占比达到 47.3%。", facts=())) is None


# ------------------------------------------------------- 5.1 判据窄在哪 ---

def test_图的标题和x轴标签里的数字不参与比对():
    """位置即判据。标题里的数、x 轴标签上的数都不是数据——把它们算进来，
    一张按分档命名的图每一轮都会被报一次。

    **标签用的是 8451 / 7732 这种"非年份、源头里也没有"的数**：第一版写的是
    年份（2019/2024/2026 年复盘），而年份另有一道过滤兜着，于是"标签也参与
    比对"这个突变从它底下穿过去了——**突变没被抓住，先怀疑用例不够**。
    """
    chart = ('```mermaid\nxychart-beta\n    title "分档 9911 以上"\n'
             '    x-axis ["8451", "7732"]\n    y-axis "点击"\n'
             "    bar [12700, 6720]\n```")
    assert numbers.chart_numbers_grounded(_st("chart", chart)) is None


def test_表里的年份列不报():
    """光秃秃一个四位整数落在 1900–2100 当年份看。误伤它的代价是模型去删一整列。"""
    t = "| 年份 | 点击 |\n|---|---|\n| 2019 | 12700 |\n| 2024 | 6720 |\n"
    assert numbers.chart_numbers_grounded(_st("table", t)) is None


def test_表头和分隔行不算数据格():
    """表头那一行即使整格是个数也不是数据格（「2019」「Q3」这类分档表头）。

    表头用的是 **8451——源头里没有的那个数**：第一版写的是 12700，
    而 12700 正好在工具返回里，于是"表头也当数据行"这个突变照样绿。
    """
    t = "| 8451 | 点击 |\n|---|---|\n| 甲 | 12700 |\n"
    assert numbers.chart_numbers_grounded(_st("table", t)) is None


def test_混着文字的格子不算数据格():
    """「约 40 台」「第 3 版」「2026-09-18」整格都不是一个数，一律不取——
    判据宁可窄：一个格子里混着文字就说明它不是纯粹的数据格。"""
    t = ("| 项 | 值 |\n|---|---|\n| 甲 | 约 8450 台 |\n| 乙 | 2026-09-18 |\n"
         "| 丙 | 第 3 版 |\n")
    assert blockcheck.table_numbers(t) == []


def test_百分数两个方向都算对上():
    """源表写 0.38、图里写 38（%）是对的；反过来也是。定死一个方向会把
    另一半真有出处的判成编造。"""
    known = {0.38}
    assert numbers.unsupported([38.0], known) == []
    assert numbers.unsupported([0.38], {38.0}) == []


def test_中文数量词和阿拉伯数字算同一个数():
    """正文写「4.2 万」、图里给 42000 是对的（`tabular.numbers_in_text` 的老规矩）。"""
    st = _st("chart", '```mermaid\npie title 曝光\n    "甲" : 42000\n```',
             note="官网曝光 4.2 万。")
    assert numbers.chart_numbers_grounded(st) is None


# ------------------------------------------------------ 5.2 正文的统计量 ---

def test_正文里工具没算过的统计量会报():
    st = _st("eda", "三个渠道的转化率合计 47.3%，每天平均 8271 次曝光。")
    v = numbers.numbers_from_tools(st)
    assert v is not None and "47.3" in v.message
    assert v.dimension == "numbers_from_tools"


def test_正文里真有出处的数不报():
    st = _st("eda", "Kickstarter 点击 12700，小红书 6720。")
    assert numbers.numbers_from_tools(st) is None


@pytest.mark.parametrize("text", [
    "详见第 3 节的说明。",                       # 序数
    "2026 年的目标还没定。",                     # 年份 + 年
    "## 2.1 背景\n这一节讲背景。",               # 章节编号
    "1. 先做这个\n2. 再做那个",                  # 有序列表
    "升级到 0.5.10 之后就好了。",                # 版本号
    "屏幕比例是 16:9，会议定在 14:30。",          # 比例 / 时间
    "这次一共三个渠道、补了 2 条记录、跑了 8 轮。",  # 小整数
    "会议记录见 [terrence-2046-2F3] 那条。",      # 引用 id
    "文档在 https://example.com/a/2026/1234 里。",  # 链接
    "型号是 H100，跑在 iOS16 上。",               # 型号
])
def test_这些数字不算数据(text):
    """**这一组是这条判据最容易出事的地方**，铁律原话：正文里「第 3 节」
    「2026 年」这类数字不是数据，误判成「编造」会逼模型去删真内容。

    这里的每一条要么来自铁律点名的形状，要么是在 24 篇真实用户笔记上
    **真的撞到过**的（2026上半年 / 100-200GB / 40m 那几条）。
    """
    assert numbers.numbers_from_tools(_st("eda", text)) is None, \
        f"这段里没有一个数该被当成统计量：{text!r}"


@pytest.mark.parametrize("text, must_not", [
    ("2026上半年实现等效 138 人。", 2026.0),      # 年份后面不跟「年」（真实笔记里的写法）
    ("跨柜带宽摔到 100-200GB。", -200.0),         # 区间不是一个负数
    ("单基站可覆盖 500-600 米。", -600.0),
    ("可实现 40m 的距离下识别。", 4e7),           # m 是米不是百万
    ("人一般最多开到 20kmh。", 2e4),              # k 是公里不是千
])
def test_这几个数根本不该被抽出来(text, must_not):
    """上一组查的是"报不报"，这一组查的是**抽取本身有没有凭空造出一个数**。
    后三条是在 24 篇真实用户笔记上真的撞到的：「40m 的距离」被读成四千万、
    「100-200GB」被读成 −200。抽错的数**一定**对不上源头，于是必然误报。"""
    assert must_not not in numbers.prose_statistics(text)


def test_围栏和表格里的数不算正文统计量():
    """图和表由 5.1 那条管，重复判会让同一个数被报两次、诊断自相矛盾。"""
    assert numbers.prose_statistics(CHART_FROM_TOOL) == []
    assert numbers.prose_statistics(
        "| 渠道 | 点击 |\n|---|---|\n| 甲 | 8450 |\n") == []


def test_k和m不当倍数后缀():
    """中文笔记里 `40m`/`3km`/`100kW` 绝大多数是**单位**不是倍数。
    24 篇真实笔记上「40m 的距离」被读成过四千万。少认一种只会漏、不会误伤。"""
    assert 4e7 not in numbers.prose_statistics("可实现 40m 的距离下识别。")


# ------------------------------------------- 5.1 表格列数（从 bench 搬过来）---

def test_列数对不上的表会报():
    t = "| 渠道 | 点击 | 下单 |\n|---|---|---|\n| 甲 | 12700 |\n"
    v = structure.table_columns_match(_st("table", t))
    assert v is not None and v.dimension == "table_validity"


def test_列数一致的两张表都不报():
    t = ("| 甲 | 乙 |\n|---|---|\n| 1 | 2 |\n\n正文。\n\n"
         "| 丙 | 丁 | 戊 |\n|---|---|---|\n| 1 | 2 | 3 |\n")
    assert structure.table_columns_match(_st("table", t)) is None


def test_正文里一根竖线不算表():
    assert structure.table_columns_match(_st("table", "写法是 a|b 这样。")) is None


# ------------------------------------------------------ 5.3 readability ---

def test_多系列图的图例数不上就报():
    """`mermaid_xy` 把系列名拼成「甲 / 乙」写进 y 轴，**那一整串还要过一次
    `safe_label(30)`**——名字一长就被切掉，图上两条柱、读者只看得到一个名字。
    这是我们自己的工具真的会吐出来的形状。"""
    c = ('```mermaid\nxychart-beta\n    title "曝光"\n    x-axis ["甲", "乙"]\n'
         '    y-axis "三月"\n    bar [1, 2]\n    bar [3, 4]\n```')
    v = charts.chart_readable(_st("eda", c))
    assert v is not None and "系列" in v.message


def test_没有y轴名字就报():
    c = ('```mermaid\nxychart-beta\n    title "曝光"\n    x-axis ["甲"]\n'
         "    bar [1]\n```")
    assert charts.chart_readable(_st("eda", c)) is not None


def test_x轴标签被截断就报():
    """blocks.py 里记着实拍：「三月Kickstarter」被截成「三月Kickstarte…」，
    省略号本身还占位置，读者反而认不出是哪个渠道。"""
    c = ('```mermaid\nxychart-beta\n    title "曝光"\n'
         '    x-axis ["三月Kickstarte…", "乙"]\n    y-axis "曝光"\n'
         "    bar [1, 2]\n```")
    v = charts.chart_readable(_st("eda", c))
    assert v is not None and "截断" in v.message


def test_类目太多就报():
    cats = ", ".join(f'"c{i}"' for i in range(charts.MAX_XY_CATEGORIES + 1))
    vals = ", ".join(str(i) for i in range(charts.MAX_XY_CATEGORIES + 1))
    c = (f'```mermaid\nxychart-beta\n    title "分布"\n    x-axis [{cats}]\n'
         f'    y-axis "条数"\n    bar [{vals}]\n```')
    assert charts.chart_readable(_st("eda", c)) is not None


def test_工具正常画出来的图不报():
    assert charts.chart_readable(_st("eda", CHART_FROM_TOOL)) is None


def test_笔记原来就有的图不算这一轮画的():
    """`charts_from_tools` 那段注释记着：判据只该管这次跑写出来的东西——
    第 604 轮实拍，用户自己画的两张图就是这么被修订那一步整个删掉的。"""
    bad = ('```mermaid\nxychart-beta\n    title "旧图"\n    x-axis ["甲"]\n'
           "    bar [1]\n```")
    st = _st("eda", bad)
    st.bag["content_at_start"] = bad
    assert charts.chart_readable(st) is None


# ---------------------------------------------------------------- 接线闸 ---

def test_四个有oracle的模式真的挂上了这几条():
    """**建了判据不等于用了判据。** 判据写得再对，`modes.py` 不挂它，
    生产里一次都不会跑。"""
    wanted = {
        "eda": {"chart_numbers_grounded", "numbers_from_tools", "chart_readable"},
        "chart": {"chart_numbers_grounded", "chart_readable"},
        "table": {"chart_numbers_grounded", "table_columns_match"},
        "analysis": {"chart_numbers_grounded", "numbers_from_tools", "chart_readable"},
    }
    for key, names in wanted.items():
        have = {c.__name__ for c in modes.BLOCK[key].checks}
        assert names <= have, f"{key} 少挂了 {sorted(names - have)}"


def test_其余四个模式一条都不挂():
    """`prompt` / `custom` 没有数据工具，`note` / `section` 是长文——
    给它们挂上等于拿一个没有 oracle 的模式去判"数字无据"。"""
    numeric = {"chart_numbers_grounded", "numbers_from_tools",
               "chart_readable", "table_columns_match"}
    for mode in modes.ALL:
        if mode.key in ("eda", "chart", "table", "analysis"):
            continue
        have = {c.__name__ for c in mode.checks}
        assert not (numeric & have), f"{mode.key} 不该挂 {sorted(numeric & have)}"


# ------------------------------------------------- 真实语料上的零误伤 ---

cl = pytest.importorskip("corpus_lineage")


@pytest.mark.skipif(not cl.DB_PATH.exists(), reason="本机没有 notes.sqlite3")
def test_真实用户笔记上一次都不误报():
    """**这一条量的是误伤，不是召回。**

    做法：把每一篇 `origin=user` 的真实笔记同时当作产出和源头——
    笔记里的每一个数按定义都追得到这篇笔记，所以**一次都不该开火**。
    开火就说明抽取或归一化有 bug（「4.2 万」对不上 42000、区间被读成负数、
    `40m` 被读成四千万——最后两种就是这么查出来的）。

    收工时的数（2026-09-18）：24 篇、图/表数值位候选 32 个、
    正文统计量候选 474 个、**开火 0 篇**。
    """
    kept, _dropped = cl.load_notes(keep={cl.ORIGIN_USER})
    assert len(kept) >= 20, "真实用户语料少于 20 篇，这条测试量不出东西"
    fired = []
    cand = 0
    for note in kept:
        body = note["content"] or ""
        st = _st("analysis", body, note=body, facts=("占位：这一轮调过工具",))
        cand += len(numbers.prose_statistics(body))
        for check in (numbers.chart_numbers_grounded, numbers.numbers_from_tools):
            verdict = check(st)
            if verdict:
                fired.append(f"{note['id']} / {check.__name__}：{verdict.message[:120]}")
    assert cand > 100, "候选太少，说明抽取被改窄到什么都不剩了"
    assert not fired, "真实笔记上误报了：\n  " + "\n  ".join(fired)


@pytest.mark.skipif(not cl.DB_PATH.exists(), reason="本机没有 notes.sqlite3")
def test_把真实笔记里的数改掉一位就抓得到():
    """上一条只说明"不乱报"，**一个恒返回 None 的判据也能通过它**。
    这一条是它的对面：在同一批真实笔记上植入一个改过的数，必须抓住。

    两个坑都是这条测试自己踩出来的，写在这儿免得下次再踩：

    * **偏移必须大过容差。** 比对带 0.5% 相对容差（正文写「4.2 万」、图里给
      42000 要算对上），第一版 `+7` 在 12700 上落在容差里，4 篇只抓住 1 篇
      ——判据没坏，是植入太轻。
    * **要替换的是原文里那个字面 token，不是归一化之后的值。** 「21万」的
      候选值是 210000，而 `"210000"` 这个串在原文里根本不存在，
      `str.replace` 一个字都没改，于是"植入版"跟干净版一模一样。
    """
    import re

    kept, _ = cl.load_notes(keep={cl.ORIGIN_USER})
    caught = tried = 0
    for note in kept:
        body = note["content"] or ""
        # 原文里字面写着的、三位以上的整数 token —— 替换它才真的改得动
        tokens = [m.group(0) for m in re.finditer(r"(?<![\d.])\d{3,}(?![\d.])", body)
                  if float(m.group(0)) in set(numbers.prose_statistics(body))]
        if not tokens:
            continue
        hacked = str(int(tokens[0]) * 3 + 1)
        if hacked in body:
            continue                     # 撞上原文里真有的数，这一篇跳过
        tried += 1
        dirty = body.replace(tokens[0], hacked, 1)
        st = _st("eda", dirty, note=body, facts=("占位：这一轮调过工具",))
        if numbers.numbers_from_tools(st):
            caught += 1
    # **4 是这份语料的上限，不是一个随手定的数**：24 篇 `origin=user` 里
    # 8 篇是空的、7 篇不足千字。批 11/13 那条硬约束（图表那一组只有 1 篇真
    # 语料）在这儿是同一件事——所以这条只当**下限自检**，跨篇结论一律不下。
    assert tried >= 4, f"能植入的篇数太少（{tried}），这条测试量不出东西"
    assert caught == tried, f"{tried} 篇里只抓住 {caught} 篇"
