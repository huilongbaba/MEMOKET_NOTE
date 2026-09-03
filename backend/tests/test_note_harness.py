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


def test_consecutive_inserts_on_same_anchor_keep_model_order():
    # 真实质量采样抓到的 bug：模型按正确顺序给了两条 insert（先「### 3.」
    # 后「### 4.」）、锚点完全相同，但 insert 语义是「紧贴锚点末尾插入」，
    # 第二条又插回锚点正后方，把第一条顶到后面，正文里编号 4 就排到了 3
    # 前面。批量自动应用时必须用 insert_offset 累计已插入长度。
    content = "锚点句。"
    first = "\n\n### 3. 第三节"
    second = "\n\n### 4. 第四节"

    # 旧行为（不传 insert_offset）会颠倒顺序——这里明确固定住"为什么需要
    # 这个参数"，不是抽象地测新参数能用
    naive = _apply_revision(content, "insert", "锚点句。", first)
    naive = _apply_revision(naive, "insert", "锚点句。", second)
    assert naive.index("第四节") < naive.index("第三节")

    stepped = _apply_revision(content, "insert", "锚点句。", first, insert_offset=0)
    stepped = _apply_revision(stepped, "insert", "锚点句。", second, insert_offset=len(first))
    assert stepped.index("第三节") < stepped.index("第四节")


def test_apply_revision_insert_offset_defaults_to_old_behavior():
    # 前端逐条接受走的是单条应用，不传 offset，行为必须跟以前一模一样
    assert _apply_revision("开头。结尾。", "insert", "开头。", "中间。") == "开头。中间。结尾。"


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
