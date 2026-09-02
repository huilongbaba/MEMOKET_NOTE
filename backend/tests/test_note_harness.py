"""单篇笔记 harness：note_harness._apply_revision() 的锚点应用语义（跟
前端 RevisionPanel.tsx 的 applyRevision() 是同一套语义，Python 版本），
以及 prompts.note_harness_continue_user()/edit_user() 的拼装。

"完不完整"的判断已经迁到 writer_harness.evaluate()（见
writer_harness/tests/test_rubric.py），这里不再重复测；_beats_status()
和 NOTE_HARNESS_DONE_MARKER 已经随之删除。

    cd backend && python -m pytest tests/test_note_harness.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import prompts  # noqa: E402
from app.routers.note_harness import _apply_revision  # noqa: E402


def test_apply_revision_replace():
    result = _apply_revision("正文里有一段旧内容在这里。", "replace", "旧内容", "新内容")
    assert result == "正文里有一段新内容在这里。"


def test_apply_revision_insert_after_anchor():
    result = _apply_revision("开头。结尾。", "insert", "开头。", "中间。")
    assert result == "开头。中间。结尾。"


def test_apply_revision_insert_before_anchor():
    result = _apply_revision("开头。结尾。", "insert_before", "结尾。", "中间。")
    assert result == "开头。中间。结尾。"


def test_apply_revision_delete():
    result = _apply_revision("保留这段，删掉这段，保留这段。", "delete", "，删掉这段", "")
    assert result == "保留这段，保留这段。"


def test_apply_revision_missing_anchor_returns_unchanged():
    result = _apply_revision("正文内容", "replace", "找不到的锚点", "新内容")
    assert result == "正文内容"


def test_apply_revision_only_touches_first_occurrence():
    # find() 找第一处，跟前端 indexOf() 语义一致——重复出现的锚点里，
    # 修订只作用在第一个匹配上，不是全局替换
    result = _apply_revision("重复 重复 重复", "replace", "重复", "改了")
    assert result == "改了 重复 重复"


def test_note_harness_continue_user_includes_beats_and_facts():
    text = prompts.note_harness_continue_user(
        spine="核心张力", beats=["节拍一"], content="正文", facts=["事实一"], profile=[],
    )
    assert "核心张力" in text
    assert "节拍一" in text
    assert "事实一" in text


def test_edit_user_includes_focus_when_given():
    text = prompts.edit_user(
        spine="", beats=[], content="正文", facts=[], profile=[], focus="non_repetition",
    )
    assert "这一轮优先检查" in text


def test_edit_user_omits_focus_block_when_not_given():
    text = prompts.edit_user(
        spine="", beats=[], content="正文", facts=[], profile=[],
    )
    assert "这一轮优先检查" not in text
