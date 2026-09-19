"""Daily Journey 的分段：切走一下下又切回来的，要并回去。

第 633 轮实测（51 分钟真实使用）：18 段里有 6 段是 1 帧的瞬时切换——瞟一眼
飞书、看一眼终端又切回来。它们不是「在做另一件事」，是同一件事里的插曲。
留着的话一天切出 **169 段**；并回去之后是 **75 段**，正好落在方案预测的区间里。
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.journey_probe import BLIP_SEC, merge_blips     # noqa: E402

BASE = dt.datetime(2026, 9, 14, 18, 0)


def seg(app: str, m0: float, m1: float, n: int = 5) -> dict:
    return {"app": app, "title": "", "n": n, "frames": [],
            "start": BASE + dt.timedelta(minutes=m0),
            "end": BASE + dt.timedelta(minutes=m1)}


def shape(segs: list[dict]) -> list[tuple[str, int, int]]:
    return [(s["app"], int((s["start"] - BASE).total_seconds() // 60),
             int((s["end"] - BASE).total_seconds() // 60)) for s in segs]


def test_同一个应用的短段被吸收_但长段照旧分开():
    """短的那一段并进前一段；**两段都长就不并**——同一个应用里换了文件、换了
    页面，画面变化足够大才会切段，那就是真的换了件事在做。"""
    got = merge_blips([seg("Code", 0, 5), seg("Code", 5, 5.2), seg("Code", 5.2, 9)])
    assert shape(got) == [("Code", 0, 5), ("Code", 5, 9)]


def test_切走一下又切回来_并回原来那段():
    """A → B（很短）→ A：B 是插曲，不是新的一段。"""
    got = merge_blips([seg("Code", 0, 5), seg("Safari", 5, 5.5), seg("Code", 5.5, 12)])
    assert shape(got) == [("Code", 0, 12)]


def test_真的换了件事就算它短也留着():
    """**光看一段短不短不足以判断。** 真换了件事只做 30 秒，那也是一段——
    判据是「前后两段是同一个应用」，不是「这段很短」。"""
    got = merge_blips([seg("Code", 0, 5), seg("Safari", 5, 5.5), seg("Feishu", 5.5, 12)])
    assert shape(got) == [("Code", 0, 5), ("Safari", 5, 5), ("Feishu", 5, 12)]


def test_切走很久不算插曲():
    long = BLIP_SEC / 60 + 1
    got = merge_blips([seg("Code", 0, 5), seg("Safari", 5, 5 + long), seg("Code", 5 + long, 20)])
    assert [g["app"] for g in got] == ["Code", "Safari", "Code"]


def test_空的和只有一段的都不炸():
    assert merge_blips([]) == []
    assert shape(merge_blips([seg("Code", 0, 3)])) == [("Code", 0, 3)]


def test_隔了很久的短段不并_人离开又回来那一下不是插曲():
    """第 778 轮（P20）真实数据：09-18 一段 Code `07:03–10:07` 184 分钟、`n` 只有 59。
    人离开三小时回来，回来那一 tick 切出的新段（一次采样、同一个应用）被当成
    插曲并回去，`end` 一下跳过整段空白——日报里就成了「连续没被打断 3 小时」。"""
    got = merge_blips([seg("Code", 0, 15), seg("Code", 184, 184.25, n=1)])
    assert shape(got) == [("Code", 0, 15), ("Code", 184, 184)]
    # A B(短) A 那一路也一样：B 跟前后不挨着就不是「切走又切回来」
    got = merge_blips([seg("Code", 0, 15), seg("Safari", 100, 100.5, n=2), seg("Code", 101, 110)])
    assert [s["app"] for s in got] == ["Code", "Safari", "Code"]
