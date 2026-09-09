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


# ------------------------------------------------------------------ 形态 ---


def test_写不了的形态各归各类():
    from app.kb.extract_check import unusable_shape

    assert unusable_shape("沪江维多利亚有机会。") == "太短"
    assert unusable_shape("团队讨论了那个那个方案的成本结构和交付时间安排") == "口语填充/ASR 噪声"
    assert unusable_shape("硬件的良率问题到底要怎么解决才能赶上交付？") == "是提问不是事实"
    assert unusable_shape("Speaker B 说硬件这个设计") == "只有说话人+短语"
    assert unusable_shape(
        "外壳样件由模型厂出，每套 2300 元，要摊到头 50-100 台里") is None


def test_speaker标签单独报不混进无用():
    """规则明说了不许把 Speaker A/B/C 写进正文——归属放 who 字段。一条带
    标签但内容完整的事实仍然能写，只是标签本身是错的：那是 per-session 的
    临时代号，下一场会议里是另一个人。"""
    from app.kb.extract_check import shapes

    facts = [types.SimpleNamespace(
        text="Speaker A 认为外壳样件每套 2300 元的成本必须摊到头 50-100 台里")]
    got = shapes(facts)
    assert got["unusable"] == 0, "内容完整就不该算无用"
    assert got["speaker_labels"] == 1 and got["speaker_label_rate"] == 1.0


def test_形态判据不需要原文():
    """所以它能几毫秒扫完整个知识库，而数字那条要逐条比对原文。"""
    import inspect

    from app.kb import extract_check

    params = inspect.signature(extract_check.shapes).parameters
    assert list(params) == ["facts"]


def test_空文本不进分母():
    from app.kb.extract_check import shapes

    got = shapes([types.SimpleNamespace(text=""),
                  types.SimpleNamespace(text="  "),
                  types.SimpleNamespace(text="短")])
    assert got["facts"] == 1 and got["unusable"] == 1
