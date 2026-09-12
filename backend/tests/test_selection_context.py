"""选区动作的「完整正文」块：长文只给选区周围一段。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.harness.prompts.selection import (  # noqa: E402
    expand_user, rewrite_user, selection_context, verify_user,
)


def _long() -> str:
    return "\n\n".join(f"第{i}段：讨论了排期和样机{i}，硬件部分应把节点、状态和证据拆开记录。" for i in range(600))


def test_short_content_untouched():
    assert selection_context("短正文", "短") == "短正文"


def test_long_content_windowed_around_selection():
    content = _long()
    sel = "讨论了排期和样机300"
    ctx = selection_context(content, sel)
    assert sel in ctx
    assert len(ctx) < 8000
    assert ctx.startswith("…（前面还有") and ctx.rstrip().endswith("字，略）")
    # 切口在段落边界：窗口正文以「第」开头
    body = ctx.split("\n\n", 1)[1]
    assert body.startswith("第")


def test_selection_not_found_falls_back_to_head():
    ctx = selection_context(_long(), "不存在的句子")
    assert ctx.startswith("第0段") and "后面还有" in ctx


def test_three_prompts_all_use_window():
    content = _long()
    sel = "讨论了排期和样机300"
    for text in (rewrite_user(content, sel, "", []), expand_user(content, sel), verify_user(content, sel, [])):
        assert sel in text and "前面还有" in text and len(text) < 12000
