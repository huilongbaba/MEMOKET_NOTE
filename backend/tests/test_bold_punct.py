"""模型把标点写进粗体里，CommonMark 就不认闭合（实拍一串裸星号）。"""
from app.harness.checks import grounding_rules
from app.harness.checks.grounding_rules import fix_bold_punct


def test_标点挪到粗体外面():
    assert fix_bold_punct("**依赖链：**容量确认 → 下单") == "**依赖链**：容量确认 → 下单"
    assert fix_bold_punct("- **提出变更的人**：记录") == "- **提出变更的人**：记录"
    assert fix_bold_punct("**a，**b **c。**") == "**a**，b **c**。"


def test_代码块里不动():
    md = "```py\nx = '**a：**'\n```\n**b：**c"
    assert fix_bold_punct(md) == "```py\nx = '**a：**'\n```\n**b**：c"


def test_落盘路径经过它():
    assert grounding_rules.scrub_meta_sentences("**依赖链：**容量确认。") == "**依赖链**：容量确认。"
