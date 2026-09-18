"""整篇动作开跑前规则能判死的临界条件（P3，`docs/edge-cases.md`）。

**前端 `editor/preconditions.ts` 是同一份**：这里的每一句话前端原样有一份，
`tests/test_p3_edge_cases.py` 逐句核对两边一致——前端先拦是为了**不发请求**
（用户点了立刻看到那句话），后端再拦是为了发了也不花一次模型调用。
块生成那一组（空指令 / 空选区 / 超长）在 `routers/compose_block.block_precondition`，
是 P1 立的同一套纪律。
"""

from __future__ import annotations

# 动作 → 空正文时给用户看的那句话。**说清楚要做什么**，不只说「空的」。
EMPTY_NOTE: dict[str, str] = {
    "skeleton": "先写点内容（或标题）再生成骨架",
    "tap": "先写点内容（或标题）再续写",
    "harness": "先写个标题或几句话，智能续写才有东西可接",
    "polish": "正文是空的——打磨没有可改的内容",
    "restructure": "正文是空的——智能排版没有可排的内容",
    "slides": "这篇还没有正文，没有可以做成幻灯片的内容",
    "ingest": "正文是空的，先写点东西再存入知识库",
}

# 这几样只看正文，不认标题：标题一句话排不了版、做不了幻灯片、抽不出事实。
_BODY_ONLY = {"polish", "restructure", "slides", "ingest"}


def note_precondition(action: str, content: str, title: str = "") -> str:
    """返回给用户看的那句话；空串 = 放行。纯函数，前端有同款。"""
    if action not in EMPTY_NOTE:
        return ""
    has_body = bool((content or "").strip())
    has_title = bool((title or "").strip()) and action not in _BODY_ONLY
    if has_body or has_title:
        return ""
    return EMPTY_NOTE[action]
