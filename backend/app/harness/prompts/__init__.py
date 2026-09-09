"""写作相关的提示词。

两条「线」来自产品构思文档：
  线 1 —— 为当前写作内容生成主线逻辑与骨架
  线 2 —— 结合骨架与已写内容，查询知识库后对文本做智能编辑

骨架的设计取舍见 ``writing.SKELETON_SYSTEM`` 的注释：从「内容大纲」改成
「结构功能」，是从文学写作的角度重新想过的，不是随手改的措辞。

这里原本是 app 根目录下一个 1119 行的 prompts.py——它既不属于 harness、
也不属于 database，在「app 只有四部分」这个划分里无处安放；而想改一句
续写提示词的人要在 1119 行里滚。按**主题**拆开（不是按调用方：MAGIC_TAP
这类被两条 harness 共用，按调用方拆会拆出交叉引用）：

    fragments.py  提示词里反复出现的积木：画像、骨架、标题格式提醒
    writing.py    写作本身：给骨架 · 改一遍 · 往下写（两条 harness 共用）
    selection.py  选中一段之后：改写 · 润色 · 展开 · 核查 · 回顾
    note.py       单篇笔记 harness：检索规划 · 改骨架 · 接着写
    plan.py       无限续写计划：拆分段 · 写一段 · 要不要再加几段
    skills.py     把启用的 skill 拼进 system prompt · 让模型写一个 skill
    block.py      块生成（`/` 唤起）

**对外仍然是一个扁平的 ``prompts.X``**，调用点一行没改：拆开是为了写的人
好找，不是为了让读的人多记一层路径。
"""

from .fragments import (
    FOCUS_LABELS,
    heading_format_reminder,
    profile_block,
    spine_beats_block,
)
from .writing import (
    EDIT_SYSTEM,
    MAGIC_TAP_SYSTEM,
    MAGIC_TAP_SYSTEM_LEAN,
    SKELETON_SYSTEM,
    edit_user,
    join_round_text,
    magic_tap_user,
    skeleton_user,
)
from .selection import (
    DIGEST_SYSTEM,
    EXPAND_SYSTEM,
    POLISH_SYSTEM,
    REWRITE_SYSTEM,
    VERIFY_SYSTEM,
    digest_user,
    expand_user,
    rewrite_user,
    verify_user,
)
from .note import (
    REPLAN_SYSTEM,
    RETRIEVAL_PLAN_SYSTEM,
    folder_context_block,
    note_harness_continue_user,
    replan_user,
    retrieval_plan_user,
)
from .plan import (
    MORE_SECTIONS_SYSTEM,
    PLAN_SYSTEM,
    more_sections_user,
    plan_user,
    render_tracking_doc,
    section_write_user,
)
from .skills import (
    SKILL_SCOPES,
    compose_system,
    skill_generate_system,
    skill_generate_user,
)
from .block import (
    BLOCK_SYSTEM,
)

__all__ = [
    "BLOCK_SYSTEM",
    "DIGEST_SYSTEM",
    "EDIT_SYSTEM",
    "EXPAND_SYSTEM",
    "FOCUS_LABELS",
    "MAGIC_TAP_SYSTEM",
    "MAGIC_TAP_SYSTEM_LEAN",
    "MORE_SECTIONS_SYSTEM",
    "PLAN_SYSTEM",
    "POLISH_SYSTEM",
    "REPLAN_SYSTEM",
    "RETRIEVAL_PLAN_SYSTEM",
    "REWRITE_SYSTEM",
    "SKELETON_SYSTEM",
    "SKILL_SCOPES",
    "VERIFY_SYSTEM",
    "compose_system",
    "digest_user",
    "edit_user",
    "expand_user",
    "folder_context_block",
    "heading_format_reminder",
    "join_round_text",
    "magic_tap_user",
    "more_sections_user",
    "note_harness_continue_user",
    "plan_user",
    "profile_block",
    "render_tracking_doc",
    "replan_user",
    "retrieval_plan_user",
    "rewrite_user",
    "section_write_user",
    "skeleton_user",
    "skill_generate_system",
    "skill_generate_user",
    "spine_beats_block",
    "verify_user",
]
