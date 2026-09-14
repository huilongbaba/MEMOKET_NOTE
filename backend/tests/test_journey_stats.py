"""日报里**数出来的那一半**（docs/daily-journey-plan.md §4.1）。

这个仓库的老规矩：能用规则算准的就不交给模型。时长、连续专注的块、反复
来回的地方全在这里算——模型数时长会数错，而它数错的时候读起来跟数对了
一模一样。
"""

from __future__ import annotations

from app.journey.stats import CHURN_VISITS, day_stats, render_churn, render_time_block, say_span


def seg(start: str, end: str, app: str = "Code", title: str = "", desc: str = "x"):
    return {"start": f"2026-09-14T{start}:00+08:00", "end": f"2026-09-14T{end}:00+08:00",
            "app": app, "title": title, "desc": desc}


def test_一天没有记录也要算得出来():
    st = day_stats("2026-09-14", [])
    assert st.total_secs == 0 and st.apps == [] and st.first is None
    assert "这一天没有记录" in render_time_block(st)


def test_按应用汇总并按时长排序():
    st = day_stats("2026-09-14", [
        seg("09:00", "09:30", "Code"),
        seg("09:30", "09:40", "Safari"),
        seg("10:00", "11:00", "Code"),
    ])
    assert [(a.app, a.segments) for a in st.apps] == [("Code", 2), ("Safari", 1)]
    assert st.apps[0].secs == 90 * 60
    assert st.total_secs == 100 * 60


def test_中间空出来的时间不算进总时长_但要单独报出来():
    """「记到 4 小时」和「从早上 9 点到晚上 6 点」是两个数，混成一个就骗人了。"""
    st = day_stats("2026-09-14", [seg("09:00", "10:00"), seg("14:00", "15:00")])
    assert st.total_secs == 2 * 3600            # 真正记到的
    assert st.span_secs == 6 * 3600             # 头到尾
    assert st.gap_secs == 4 * 3600
    block = render_time_block(st)
    assert "记到 2 小时，中间有 4 小时没在记。" in block


def test_同一个应用连着的段并成一块连续专注():
    st = day_stats("2026-09-14", [
        seg("09:00", "09:20", "Code"), seg("09:20", "09:50", "Code"),
        seg("09:50", "10:05", "Safari"),
    ])
    assert [(x.app, x.secs) for x in st.stretches] == [("Code", 50 * 60), ("Safari", 15 * 60)]


def test_一块连续专注要说出在哪个文件上():
    """「下午有 52 分钟在 Code」几乎没有信息量，「在 capture.ts」才有。
    取的是这块里占时间最长的那个标题，不是第一个。"""
    st = day_stats("2026-09-14", [
        seg("09:00", "09:05", "Code", "a.py"),
        seg("09:05", "09:40", "Code", "capture.ts"),
        seg("09:40", "09:45", "Code", "a.py"),
    ])
    assert st.stretches[0].title == "capture.ts"
    assert "Code · capture.ts" in render_time_block(st)


def test_中间隔太久就不是一块连续专注():
    """隔了一顿午饭的两段 Code 不是「连续专注两小时」。"""
    st = day_stats("2026-09-14", [seg("09:00", "10:00", "Code"), seg("12:00", "13:00", "Code")])
    assert [x.secs for x in st.stretches] == [3600, 3600]


def test_太短的块不进连续专注():
    st = day_stats("2026-09-14", [seg("09:00", "09:05", "Code"), seg("09:05", "09:09", "Safari")])
    assert st.stretches == []


def test_反复回到同一处才算打转_连着的几段只算一次():
    a = ("Code", "journey.py")
    st = day_stats("2026-09-14", [
        seg("09:00", "09:10", *a), seg("09:10", "09:20", *a),   # 连着 = 一次停留
        seg("09:20", "09:25", "Safari", "文档"),
        seg("09:25", "09:35", *a),                              # 第二次
        seg("09:35", "09:40", "Safari", "文档"),
        seg("09:40", "09:50", *a),                              # 第三次
    ])
    churn = {c.title: c for c in st.churn}
    assert churn["journey.py"].visits == CHURN_VISITS
    assert churn["journey.py"].secs == 40 * 60
    assert "文档" not in churn                                   # 只去过两次，不算
    assert "journey.py" in render_churn(st)


def test_没有标题的段不参与打转统计():
    """没标题分不清是不是同一处——`Code` 和 `Code` 可能是两个完全不同的文件。"""
    st = day_stats("2026-09-14", [
        seg("09:00", "09:10", "Code", ""), seg("09:10", "09:15", "Safari", ""),
        seg("09:15", "09:25", "Code", ""), seg("09:25", "09:30", "Safari", ""),
        seg("09:30", "09:40", "Code", ""),
    ])
    assert st.churn == []


def test_落盘顺序被打乱也要算对():
    """补描述、跨天换目录都可能打乱顺序，而连续专注和打转都依赖顺序。"""
    rows = [seg("14:00", "15:00", "Safari"), seg("09:00", "10:00", "Code")]
    st = day_stats("2026-09-14", rows)
    assert st.first.hour == 9 and st.last.hour == 15
    assert st.gap_secs == 4 * 3600


def test_一行坏时间戳被跳过_其余照算():
    st = day_stats("2026-09-14", [seg("09:00", "10:00"), {"app": "X", "start": "坏", "end": "更坏"}])
    assert st.total_secs == 3600 and [a.app for a in st.apps] == ["Code"]


def test_时长写成人话():
    assert say_span(20) == "不到 1 分钟"
    assert say_span(600) == "10 分钟"
    assert say_span(3600) == "1 小时"
    assert say_span(3600 + 720) == "1 小时 12 分钟"


def test_时间那一节是代码写的_模型不参与():
    """这一节原样进日报，提示词里明说不要重算——所以它必须自己就是完整的。"""
    st = day_stats("2026-09-14", [seg("09:00", "10:00", "Code", "a.py"),
                                  seg("10:00", "10:30", "Safari", "文档")])
    block = render_time_block(st)
    assert block.startswith("## 时间去哪了")
    assert "**Code** 1 小时" in block and "**Safari** 30 分钟" in block
    assert "09:00 – 10:30" in block
