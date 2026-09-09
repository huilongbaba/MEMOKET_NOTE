"""抽取的确定性判据：数字有没有出处。

三条候选判据只做了这一条，因为只有这一条在真实数据上存在：
同场会议内高度相似的事实对 1/26258、一条塞三件事的 6/2922（0.2%）、
数字找不到出处约 10%。把三条都做出来是照抄设计，不是读数据。

这一条本身也是量出来才有意义的：朴素版本（「事实里每个数字都要在原文里
出现」）会判 31%，而其中大部分是对的——年份来自会话日期、``10,000`` 被
数字正则读成两个数、句子里的日期把自己的月和日也算了进去。剔掉这些之后
剩 10%，剩下的才是有意思的那种：模型自己算出来的（112 ÷ 1.5 = 74.6）、
和它推断而不是读到的年份。
"""

from __future__ import annotations

import types

from app.kb.extract_check import numbers_without_source, rate


def test_原文里有的数字不算问题():
    assert numbers_without_source("售价约为849美元。", "他说售价849美元左右") == []


def test_编出来的数字会被指出来():
    assert numbers_without_source("售价约为849美元。", "他说售价挺贵的") == ["849"]


def test_年份来自会话日期不算编造():
    """抽取把「三月中旬」补成「2026年3月中旬」是在补全记录，不是编造。
    这一条占了朴素判据误报的三分之二。"""
    assert numbers_without_source(
        "团队计划在2026年3月中旬开始接触投资者。",
        "计划三月中旬开始接触投资者", when="2026-03-09") == []


def test_句子里的日期不按三个数字拆():
    assert numbers_without_source(
        "计划在 2026-03-09 至 2026-03-10 完成网站更新。",
        "计划这两天完成网站更新", when="2026-03-09") == []


def test_千位分隔不被读成两个数():
    """``10,000`` 被数字正则读成 10 和 000，于是一条正确的事实被判有问题。"""
    assert numbers_without_source("先充值 10,000 美元用于广告投放。",
                                  "先充值 10000 美元投广告") == []


def test_原文写的是中文数字也算有出处():
    assert numbers_without_source("默认收音距离是3米。", "默认收音距离是三米") == []
    assert numbers_without_source("样机做20套。", "样机做二十套") == []


def test_一位数不参与判定():
    """长一点的原文里几乎必然出现「1」，它的有无什么都证明不了。"""
    assert numbers_without_source("方案 1 更好。", "完全无关的一段话") == []


def test_没有原文时不判():
    """判不了跟判为有问题是两回事——把前者当后者报，就是在制造假阳性。"""
    assert numbers_without_source("售价849美元。", "") == []


def test_比率按可核对的那部分算():
    """按全部事实算的话，一批很差的抽取会被一堆不含数字的事实稀释掉。"""
    facts = [
        types.SimpleNamespace(id="a", text="售价849美元。", unit="u1", when=""),
        types.SimpleNamespace(id="b", text="他觉得贵。", unit="u1", when=""),
        types.SimpleNamespace(id="c", text="卖了25台。", unit="u1", when=""),
    ]
    got = rate(facts, {"u1": "他说卖了25台，觉得贵"})
    assert got["checked"] == 2, "不含数字的那条不该进分母"
    assert got["flagged"] == 1 and got["rate"] == 0.5
    assert got["examples"][0]["numbers"] == ["849"]
