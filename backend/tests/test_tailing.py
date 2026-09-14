"""续尾的两道护栏（harness/tailing.py）——用户第 569 轮报的 `eriwa`。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.harness.tailing import acceptable_tail, needs_tail  # noqa: E402


def test_停在半句上才需要续尾():
    assert needs_tail("现有记录显示，这意味着")
    assert needs_tail("一行没写完的话")


def test_已经收尾的不续():
    for done in ("……实际人数和流失原因。", "是这样吗？", "别急！", "他说「就这么定」",
                 "```\ncode\n```", "| 列 | 值 |", "## 下一节的标题", "（括号收尾）", "", "   \n"):
        assert not needs_tail(done), done


def test_没闭合的代码块一定要续():
    """切在 ``` 里面，不补完整段渲染都坏——这时候「最后一个字符是不是标点」不作数。"""
    assert needs_tail("前面一段\n```python\nprint(1)")
    assert needs_tail("```\n未闭合。")


def test_中文正文续回纯ASCII碎片就丢掉():
    assert not acceptable_tail("……每一层的实际人数和流失原因。", "eriwa")
    assert not acceptable_tail("……这意味着", "  ")
    assert not acceptable_tail("……这意味着", "xyz")


def test_像样的续尾留着():
    assert acceptable_tail("……这意味着", "还需要补上实际人数。")
    assert acceptable_tail("... which means", "more data is needed.")   # 英文正文英文续尾
    assert acceptable_tail("……这意味着", "OK。")                        # 带句末标点就算
