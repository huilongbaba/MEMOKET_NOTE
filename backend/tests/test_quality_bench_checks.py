"""质量 bench 的判定函数自身的回归测试。

为什么需要这个：判定函数一旦失效，所有测量结果都是假的，而且看起来一切
正常——真实踩过，`_single_ending` 第一版用"收束标记之后还剩多少字符"配
400 字阈值，对中文太宽，原始缺陷文本（收束后接了两整节）只有 176 字，
被判成"没问题"，于是那一轮"通过"完全没有意义。判定函数是测量工具，工具
本身要先有测试。

每个用例都固定住一个真实发生过的判定：真阳性必须继续抓到，历史上出过的
误报必须继续不报。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

editing = pytest.importorskip("editing_quality_bench")
writing = pytest.importorskip("writing_quality_bench")


# ------------------------------------------------------------ editing 判定

def test_single_ending_catches_sections_after_closing_marker():
    """第一版阈值判定漏掉的那份原始缺陷文本，现在必须判成没修好。"""
    bad = ("## 定价策略\n\n综上所述，两种模式都无法单独成立。\n\n"
           "## 订阅制的具体设计\n\n按功能分层。\n\n"
           "## 买断制的兜底方案\n\n一次性价格覆盖硬件成本。\n")
    ok, _ = editing._single_ending(bad)
    assert not ok
    ok, _ = editing._single_ending("## 定价\n\n正文。\n\n综上所述，用混合形态。\n")
    assert ok


def test_numbering_check_rejects_vacuous_pass():
    """编号被整个改写掉时不能报"正确"——判定函数什么都没量到就报通过，
    跟 `_single_ending` 阈值失效是同一类错误，实测真的发生过。"""
    seed = [c for c in editing.CASES if c["id"] == "编号错乱"][0]["seed"]
    assert editing._numbering_in_order(seed)[0] is False        # 原始缺陷

    # 改成粗体标签、数字全没了，但四项内容都在——这是真修好了
    rewritten = ("## 四项核心挑战\n\n**录制信任**成本高。\n\n**关联价值**难感知。\n\n"
                 "**图谱自维护**不可信。\n\n**总结不够行动化**。\n")
    assert editing._numbering_in_order(rewritten)[0] is True

    # 丢了一项，不算修好
    assert editing._numbering_in_order(
        "**录制信任**\n**关联价值**\n**图谱自维护**\n")[0] is False

    # 把小节挪到跟编号匹配的位置，也是正确修法
    assert editing._numbering_in_order(
        "### 1. 录制信任\n### 2. 关联价值\n### 3. 总结不够行动化\n### 4. 图谱自维护\n")[0] is True


def test_empty_heading_needs_level_awareness():
    """父标题领着子标题是正常结构，只有同级或更浅的下一个标题才算空壳。

    实测误报过：`## 本地模型还是云端` 后面跟 `### 二选一的处境`，被判成
    空壳，但那一节的内容就在子节里。
    """
    # 真空壳：同级标题紧跟
    assert editing._no_empty_heading("## A\n\n## B\n\n正文\n")[0] is False
    # 父带子：不算空壳
    assert editing._no_empty_heading("## A\n\n### A1\n\n正文\n")[0] is True
    # 子节结束后回到同级，前一节有内容
    assert editing._no_empty_heading("## A\n\n正文\n\n## B\n\n正文\n")[0] is True
    # 文档末尾的光杆标题
    assert editing._no_empty_heading("## A\n\n正文\n\n## B\n")[0] is False
    # 更浅的下一个标题（### 之后直接 ##）
    assert editing._no_empty_heading("## A\n\n### A1\n\n## B\n\n正文\n")[0] is False


# ------------------------------------------------------------ writing 判定

def test_topic_collision_catches_same_topic_restated():
    """同一主题换标题重讲——机械查重查不出来的那种重复。"""
    ok, detail = writing._no_topic_collision(
        "## 订阅制的具体设计\nx\n\n## 订阅分层与用量计费的落地细节\ny\n")
    assert not ok and "订阅" in detail


def test_topic_collision_allows_parallel_contrasting_sections():
    """两个方案各论适用边界是对照结构，是好写法，历史上误报过。"""
    assert writing._no_topic_collision(
        "## 买断制的适用边界\nx\n\n## 订阅制的适用边界\ny\n")[0]


def test_topic_collision_ignores_titles_too_short_to_judge():
    """"定价策略"去掉功能词只剩一个词元，跟任何含它的标题都 100% 重合。"""
    assert writing._no_topic_collision(
        "## 定价策略\nx\n\n## 混合定价的承接点\ny\n")[0]


def test_template_heading_flags_scaffolding_prefix():
    assert writing._no_template_heading("## 收束\n正文\n")[0] is False
    assert writing._no_template_heading("## 收束：从个案到复盘框架\n正文\n")[0] is False
    assert writing._no_template_heading("## 从个案到复盘框架\n正文\n")[0] is True


def test_figures_must_be_hedged_only_when_invented():
    seed = "## 定价\n\n订阅与买断各有支持者。\n"
    invented = seed + "## 分层\n\n基础版 $9/月，专业版 $29/月，企业版 $99/月。\n"
    assert writing._figures_are_hedged(invented, seed)[0] is False
    hedged = seed + "## 分层\n\n粗算一版：基础版 $9/月，专业版 $29/月，企业版 $99/月。\n"
    assert writing._figures_are_hedged(hedged, seed)[0] is True
    # 种子里已有的数字不算凭空生成
    seed2 = "## 进度\n\n样机 5 月 20 日出，模具 5 月 17 日到位。\n"
    assert writing._figures_are_hedged(seed2 + "## 影响\n\n5 月 20 日与 5 月 17 日两个点都要复核。\n", seed2)[0]


def test_prompt_example_leak_detects_verbatim_copy():
    assert writing._no_prompt_example_leak("## 混合形态：买断覆盖硬件，订阅覆盖运营\nx\n")[0] is False
    assert writing._no_prompt_example_leak("## 定价的收支节奏\nx\n")[0] is True


def test_blank_runs():
    assert writing._no_blank_runs("a\n\n\n\nb")[0] is False
    assert writing._no_blank_runs("a\n\nb")[0] is True
