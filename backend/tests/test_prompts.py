"""prompts.folder_context_block()：无限续写用来格式化同文件夹参考笔记。

    cd backend && python -m pytest tests/test_prompts.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import prompts  # noqa: E402


def test_folder_context_block_empty_list_returns_empty_string():
    assert prompts.folder_context_block([]) == ""


def test_folder_context_block_skips_notes_with_no_content():
    notes = [{"title": "空笔记", "content": "   "}]
    assert prompts.folder_context_block(notes) == ""


def test_folder_context_block_includes_title_and_excerpt():
    notes = [{"title": "供应商谈判", "content": "价格锁定在年底前"}]
    block = prompts.folder_context_block(notes)
    assert "供应商谈判" in block
    assert "价格锁定在年底前" in block


# ---------------------------------------------------------------- 标题 vs 加粗（TRACELOG A2-1）

def test_magic_tap_user_reminds_formatting_when_no_heading_yet():
    text = prompts.magic_tap_user("", [], "一句话种子内容，没有任何标题", [], [])
    assert "不代表不用格式" in text


def test_magic_tap_user_omits_reminder_once_a_heading_exists():
    text = prompts.magic_tap_user("", [], "## 已有标题\n正文内容", [], [])
    assert "不代表不用格式" not in text


def test_note_harness_continue_user_reminds_formatting_when_no_heading_yet():
    text = prompts.note_harness_continue_user("", [], "一句话种子内容，没有任何标题", [], [])
    assert "不代表不用格式" in text


def test_note_harness_continue_user_omits_reminder_once_a_heading_exists():
    text = prompts.note_harness_continue_user("", [], "## 已有标题\n正文内容", [], [])
    assert "不代表不用格式" not in text


def test_expand_user_includes_facts_when_given():
    # TRACELOG 发现 /api/expand 之前完全没查知识库，只能自己编听起来合理
    # 但查无实据的背景——修复后 expand_user 要能带上事实
    text = prompts.expand_user("正文", "选中片段", facts=["知识库里的真实事实"])
    assert "知识库里的真实事实" in text


def test_expand_user_omits_facts_section_when_none_given():
    text = prompts.expand_user("正文", "选中片段", facts=[])
    assert "知识库中的相关事实" not in text


def test_expand_system_instructs_grounding_over_invention():
    assert "查无实据" in prompts.EXPAND_SYSTEM


def test_edit_system_hunts_for_existing_repetition_across_rounds():
    # TRACELOG A2-1 跟进：真实跑智能续写 harness 3 轮后发现内容重复
    # （第二轮几乎原样重复第一轮的边界条件小节），第三轮的自动修订完全
    # 没有发现/删掉这个重复——EDIT_SYSTEM 原本只教"不要建议新的重复"，
    # 没教"主动找已经存在的重复"，这是两件不同的事。
    assert "专门找一遍正文里有没有已经存在的重复" in prompts.EDIT_SYSTEM


def test_folder_context_block_truncates_long_notes():
    long_content = "x" * 5000
    notes = [{"title": "长笔记", "content": long_content}]
    block = prompts.folder_context_block(notes)
    assert len(block) < 1000


def test_magic_tap_user_includes_folder_context_when_given():
    text = prompts.magic_tap_user(
        spine="", beats=[], content="已写内容", facts=[], profile=[],
        folder_context="【同文件夹其他笔记摘录】\n### 相关笔记\n内容",
    )
    assert "同文件夹其他笔记摘录" in text


def test_magic_tap_user_omits_folder_section_when_empty():
    text = prompts.magic_tap_user(
        spine="", beats=[], content="已写内容", facts=[], profile=[], folder_context="",
    )
    assert "同文件夹" not in text


# ---------------------------------------------------------------- 无限续写计划

def test_plan_user_includes_goal():
    text = prompts.plan_user("写一份产品规划", facts=[], folder_context="")
    assert "写一份产品规划" in text


def test_section_write_user_includes_focus_when_given():
    # "写完了没有"现在由 writer_harness.evaluate() 单独打分判定（见
    # app/harness_adapter.py），不再靠模型自己在正文末尾吐标记；这里只
    # 测 focus（上一轮打分里最弱的维度）会不会被正确带进 prompt。
    text = prompts.section_write_user(
        section_title="硬件续航", goal="", prior_summaries=[], content="",
        facts=[], folder_context="", profile=[], focus="non_repetition",
    )
    assert "上一轮评分里这一项最弱" in text


# TRACELOG [13]：真实测的一篇跟知识库主题完全不相关的笔记（个人专注力
# 习惯，knowledge base 全是硬件创业记录）——续写把不相关的检索事实硬编
# 成牵强类比（"就像平衡硬件软件APP各自开发进度一样"），读起来很突兀。
# MAGIC_TAP_SYSTEM 原来"给了事实就优先用"的指令没有给"这条事实其实跟
# 正文没关系，可以不用"的许可。
def test_magic_tap_system_allows_skipping_irrelevant_facts():
    assert "牵强的类比" in prompts.MAGIC_TAP_SYSTEM


def test_section_write_user_includes_prior_summaries_to_avoid_repetition():
    text = prompts.section_write_user(
        section_title="触发交互", goal="", prior_summaries=["硬件续航已经写完，重点是低功耗方案"],
        content="", facts=[], folder_context="", profile=[],
    )
    assert "硬件续航已经写完" in text


def test_section_write_user_reminds_formatting_until_a_heading_exists():
    # 反馈直接问"无限续写为什么没有格式" -- MAGIC_TAP_SYSTEM 的格式指令是
    # "延续已有格式"，正文里还没出现过 "## " 标题时没有"已有风格"可延续，
    # 这条提醒专门补这个缺口。触发条件是"没有 ## 标题"，不是"内容是否为
    # 空"——一段没有标题的纯文字种子内容（这正是真实触发过这个 bug 的场景：
    # 一句话种子，模型在第一轮里用 **加粗** 冒充标题）同样要提醒；已经出现
    # 过 ## 标题之后才不用再提醒。
    empty = prompts.section_write_user(
        section_title="X", goal="", prior_summaries=[], content="",
        facts=[], folder_context="", profile=[],
    )
    nonempty_no_heading = prompts.section_write_user(
        section_title="X", goal="", prior_summaries=[], content="已经写了一段内容，但还没有标题",
        facts=[], folder_context="", profile=[],
    )
    has_heading = prompts.section_write_user(
        section_title="X", goal="", prior_summaries=[], content="## 已有标题\n内容",
        facts=[], folder_context="", profile=[],
    )
    assert "不代表不用格式" in empty
    assert "不代表不用格式" in nonempty_no_heading
    assert "不代表不用格式" not in has_heading


def test_section_write_user_shows_placeholder_for_empty_content():
    text = prompts.section_write_user(
        section_title="X", goal="", prior_summaries=[], content="",
        facts=[], folder_context="", profile=[],
    )
    assert "还没开始写" in text


def test_more_sections_user_includes_summaries_and_goal():
    text = prompts.more_sections_user(
        goal="写一份产品规划", section_summaries=["第一段小结"], facts=[], folder_context="",
    )
    assert "写一份产品规划" in text
    assert "第一段小结" in text


def test_render_tracking_doc_shows_each_section_status():
    sections = [
        {"title": "硬件续航", "status": "done", "summary": "已锁定基线"},
        {"title": "触发交互", "status": "in_progress", "summary": ""},
        {"title": "反馈设计", "status": "pending", "summary": ""},
    ]
    doc = prompts.render_tracking_doc("写一份产品规划", "active", sections)
    assert "硬件续航" in doc
    assert "已锁定基线" in doc
    assert "触发交互" in doc
    assert "反馈设计" in doc
    assert "进行中" in doc  # plan 状态


def test_render_tracking_doc_handles_no_sections_yet():
    doc = prompts.render_tracking_doc("目标", "active", [])
    assert "目标" in doc


def test_edit_system_cleans_up_orphaned_headings_after_delete():
    # TRACELOG [10]：真实数据里发现修订删除了一节的全部内容，只留下一个
    # 标题孤零零地对着空行，读起来像正文缺了一截——EDIT_SYSTEM 要主动
    # 把这种空壳标题也一并删掉，不是只删内容不管标题
    assert "空壳标题" in prompts.EDIT_SYSTEM


def test_edit_user_carries_placeholder_lines():
    """占位符要作为具体位置喂给修订，不能只在续写规则里禁止。"""
    from app import prompts

    out = prompts.edit_user("张力", ["节拍"], "正文", [], [],
                            defect_lines=["| 众筹素材锁定 | 待指定 |"])
    assert "必须就地处理" in out and "待指定" in out
    assert "不许原样留着" in out
    assert "必须就地处理" not in prompts.edit_user("张力", ["节拍"], "正文", [], [])
