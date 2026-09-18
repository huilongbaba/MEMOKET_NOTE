"""Hooks for one section of a folder-level writing plan.

The plan loop -- pick the next section, decide whether the plan needs more
sections, keep the tracking note in sync -- stays in the router. What runs
here is one section: gather, continue (or repair), judge, repeat.

Long-form's merge rule is the opposite of the block harness's: each round
*appends* to what is already there, so ``produce`` joins rather than
replaces, and everything written in earlier rounds stays under judgement.
"""

from __future__ import annotations

import re

from typing import AsyncIterator

from .. import prompts
from .. import agent_loop
from .. import query_cache
from ...editor import outline
from .mirror import _record_dropped, _scrub_and_record
from ..tailing import acceptable_tail, needs_tail
from ...util import llm
from ..agent_loop import ToolTrace
from ..middleware import ledger as ledger_mw
from ..params import (AGENT_TOOLS, CONTINUE_MAX_TOKENS, CONTINUE_TAIL_TOKENS,
                      LEDGER_IN_PROMPT)
from ...database.retrieval import retrieve as _retrieve
from ..state import State

# 拿分段标题直接召回、无条件补进材料的条数。
ANCHOR_FACTS = 4
_FACT_ID = re.compile(r"^\s*\[([^\]\s]+)\]")


def _merge_anchored(st: State, title: str, facts: list[str]) -> list[str]:
    """把「分段标题直接召回」的几条摆到材料最前面。

    取材料走的是工具循环——模型自己决定查什么，而它会查偏。第 593 轮真跑实证：分段标题是
    「硬件线：设备与 APP 的连接稳定性及分阶段测试」，写出来整篇是华为 950 超节点 / 昇腾 /
    鲲鹏 / 欧拉——那批事实字面上也讲「硬件」「连接」「稳定性」「分阶段测试」，于是后面每一道
    判据都自洽地放行了：材料确实用上了（`material_used` 数特征词）、引用没有编造（一个都没引）、
    `topic_fidelity` 还给了满分。**根因在取材料那一步，不在写作。**

    直接拿标题 recall 一次是零 LLM、几十毫秒的事，而且实测对这个标题是准的（返回的全是用户
    自己项目的硬件 / APP 事实）。补在最前面：prompt 里靠前的权重更高，模型查偏时也总能看见
    对的材料。不去掉工具循环取回的——它多数时候更精准，这里要的只是一条下限。
    """
    try:
        anchored, _ids, _took = _retrieve(st.ctx.user, st.content, title, [],
                                          limit=ANCHOR_FACTS, title=title, anchor_first=True)
    except Exception:                      # noqa: BLE001 — 检索挂了不该拖垮这一轮
        return facts
    def fid(f: str) -> str:
        m = _FACT_ID.match(f)
        return m.group(1) if m else " ".join(f.split())[:40]
    seen: set[str] = set()
    out: list[str] = []
    for f in anchored + facts:
        k = fid(f)
        if k in seen:
            continue
        seen.add(k)
        out.append(f)
    return out


class SectionHooks:
    """One section of a plan. ``st.ctx.note_id`` is the note it writes into."""

    def __init__(self, *, goal: str, other_summaries: list[str],
                 folder_ctx: str = "", profile: list[str] | None = None):
        self.goal = goal
        self.other_summaries = list(other_summaries)
        self.folder_ctx = folder_ctx
        self.profile = list(profile or [])

    # ------------------------------------------------------------ gather --
    async def prepare(self, st: State) -> tuple[list[str], ToolTrace]:
        # 缓存路由（计划 3.3 / [CE] §4.6）：告诉后面每一次调用「这一整次跑属于
        # 哪篇笔记的哪个模式」，`llm._cache_key()` 再缀上步骤名（`ctx_feature`
        # 已经按步骤细分过了，不另造一套）。**设在这里而不是 `loop.py`**——
        # 这一批的铁律写着不许改 `loop.py` 的循环结构。
        llm.set_cache_key(st.ctx.note_id, st.mode.key)
        title = st.ctx.note_title
        trace = ToolTrace()
        if not AGENT_TOOLS:
            facts, _ids, _took = _retrieve(
                st.ctx.user, st.content, title, [], limit=6,
                title=title, anchor_first=True)
            return facts, trace

        # 账本摘要进检索规划（计划 2.4）。**批 26 之前全仓只有 `hooks/note.py`
        # 接了这一条**，8 个模式接了 1 个；而批 13 隔离量过「只开 2.5 = 17.2%、
        # 2.4+2.5 才 3.5%」，批 26 实测这条线上的重复查询率正好落在 14–40%
        # 那一档。**这不是推出来的，是先看见数再回代码里找到的。**
        topics = query_cache.dispatch("list_topics", {"limit": 40}, st.ctx)
        led = ledger_mw.ledger_of(st)
        # 主题树是这里直接调的、不进 `trace.calls`，`fold` 看不到它——
        # 缺口摘要要知道「有哪些方向一条都没取」就得先把分母折进去
        # （`hooks/note.py` 那条注释记着第一版 2.4 就是这么漏掉的）。
        ledger_mw.note_topics(led, topics)
        msgs = [
            {"role": "system", "content": prompts.compose_system(
                prompts.RETRIEVAL_PLAN_SYSTEM, st.mode.skill_scope, st.ctx.user,
                st.skill_menu, [])},
            {"role": "user", "content": prompts.retrieval_plan_user(
                title, self.goal, self.other_summaries, st.content,
                topics_overview=topics,
                # 这里读到的是第 1..n-1 轮的账本：`Ledger.after_prepare` 要等
                # 这一轮的工具循环跑完才折叠。
                ledger_gaps=(ledger_mw.gap_summary(led) if LEDGER_IN_PROMPT
                             else ""))},
        ]
        _extra, trace = await agent_loop.gather_context(
            msgs, st.ctx, groups=list(st.mode.groups))
        facts = _merge_anchored(st, title, list(trace.as_facts()))

        # A failed tool loop must not mean writing empty-handed: fall back to
        # the pre-agent keyword retrieval rather than producing a round with
        # no material behind it.
        if trace.error and not facts:
            facts, _ids, _took = _retrieve(
                st.ctx.user, st.content, title, [], limit=6,
                title=title, anchor_first=True)

        # A section title often anchors to a specific occasion ("that time",
        # "last week"). Those need the multi-hop lookup, which the plain tool
        # loop does not reach on its own.
        probe = f"{title}\n{st.content[-400:]}"
        if agent_loop.is_scoped_question(probe):
            hop = query_cache.dispatch(
                "search_session_context",
                {"question": f"{title}——{self.goal[:100]}", "limit": 10},
                st.ctx)
            hop_facts = [line.strip() for line in hop.splitlines()
                         if line.strip() and not line.strip().startswith("（")]
            facts = hop_facts + facts

        return facts, trace

    # ----------------------------------------------------------- produce --
    async def produce(self, st: State) -> AsyncIterator[str]:
        if st.bag.get("cleanup_only"):
            # The repair already happened in Revise's before_produce. Writing
            # more now is precisely what this round exists to avoid.
            return

        system = prompts.compose_system(prompts.MAGIC_TAP_SYSTEM, st.mode.skill_scope,
                                        st.ctx.user, st.skill_menu,
                                        st.skill_bodies)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompts.section_write_user(
                st.ctx.note_title, self.goal, self.other_summaries,
                st.content_for_continue(), st.facts, self.folder_ctx,
                self.profile, focus=st.bag.get("focus", ""),
                facts_index=st.bag.get("facts_index"))},
        ]

        text = ""
        stats: dict = {}
        async for piece in llm.stream(messages, max_tokens=CONTINUE_MAX_TOKENS,
                                      stats=stats):
            text += piece
            yield piece
        # Hitting the token ceiling truncates mid-sentence. Finish the
        # sentence rather than dropping it -- deleting what was written is
        # the one response that loses work.
        # 同单篇那条：撞上限 ≠ 切在句中，续回来的也要先看像不像半句（harness/tailing.py）
        if stats.get("finish_reason") == "length" and needs_tail(text):
            tail = messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": prompts.FINISH_THE_SENTENCE},
            ]
            tail_text = ""
            async for piece in llm.stream(tail, max_tokens=CONTINUE_TAIL_TOKENS):
                tail_text += piece
            if acceptable_tail(text, tail_text):
                text += tail_text
                yield tail_text

        # Drop paragraphs the note already contains before joining. This
        # guard lived only on the single-note harness once, and the first
        # benchmark of the folder path caught verbatim repetition inside a
        # single sentence.
        streamed = text
        text = outline.drop_already_written(st.content, text) or text
        # 跟单篇 harness 同一套镜像：剥掉的段 / 删掉的元话语句子都记进 st.bag，loop 发 dedup / scrub，
        # 客户端删同一份——这条路原来两样都没发（第 562 轮）
        _record_dropped(st, streamed, text)
        st.content = _scrub_and_record(st, prompts.join_round_text(st.content, text))

    # ------------------------------------------------------------ commit --
    async def commit(self, st: State) -> None:
        """The Save middleware persists every round. Marking the section done
        and re-syncing the tracking note are plan-level decisions and stay
        with the plan loop, which is the only place that can see the other
        sections."""
