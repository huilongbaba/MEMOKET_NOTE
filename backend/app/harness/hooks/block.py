"""Hooks for the ``/`` block harness: chart, table, EDA, analysis, prompt,
custom.

What makes this harness different from the long-form ones is one line in
``produce``: a block *replaces* its predecessor rather than continuing it.
Everything else -- accumulating facts across rounds, keeping the charts the
tools really emitted, best-of, stopping -- is shared machinery.
"""

from __future__ import annotations

from typing import AsyncIterator

from ... import agent_loop, llm
from ...agent_loop import ToolTrace
from ...prompts import BLOCK_SYSTEM
from ..state import State

# Sent into the focus round. The model has already explored by this point;
# this round exists only to turn what it found into a chart.
_FOCUS_NUDGE = (
    "上面已经查到的数据里，挑最值得看的画成图（chart_from_text / "
    "chart_column / render_chart）。这一轮只画图，不要再查新数据。")


class BlockHooks:
    """``prompt`` is the whole user-facing instruction for this round."""

    def __init__(self, *, prompt: str = "", selection: str = "",
                 profile: list[str] | None = None, title: str = ""):
        self.prompt = prompt
        self.selection = selection
        self.profile = list(profile or [])
        self.title = title

    # ------------------------------------------------------------ gather --
    async def prepare(self, st: State) -> tuple[list[str], ToolTrace]:
        msgs = [{"role": "system", "content": BLOCK_SYSTEM},
                {"role": "user", "content": self._user(st, facts="")}]
        extra, trace = await agent_loop.gather_context(
            msgs, st.ctx, groups=list(st.mode.groups), max_iters=3)

        if st.mode.focus_groups and not _produced(trace, st.mode.focus_groups):
            extra2, trace2 = await agent_loop.gather_context(
                msgs + extra + [{"role": "user", "content": _FOCUS_NUDGE}],
                st.ctx, groups=list(st.mode.focus_groups), max_iters=3)
            extra += extra2
            trace.calls += trace2.calls
            trace.iters += trace2.iters

        # Tool output goes back verbatim as well as summarised. Without the
        # raw text the model never sees the mermaid render_chart produced and
        # falls back to writing its own, which is the bug this harness exists
        # to prevent.
        facts = list(trace.as_facts()) if trace.used else []
        raw = [r for _n, _a, r in trace.calls if r and not r.startswith("（")]
        return facts + raw, trace

    # ----------------------------------------------------------- produce --
    async def produce(self, st: State) -> AsyncIterator[str]:
        user = self._user(st, facts="\n\n".join(st.facts))
        if st.steer:
            user += f"\n\n【上一轮的问题，这一轮要解决】\n{st.steer}"
        if st.content:
            user += ("\n\n【上一轮写出来的（要改掉上面说的问题，重写一遍，"
                     "不是在它后面接着写）】\n" + st.content
                     + "\n\n上一轮里那些 ```mermaid 代码块是工具生成的、"
                       "已经验证过能渲染，**直接原样搬过来**，不要自己重写、"
                       "也不要因为这一轮没再调工具就说画不出图。")
        fresh = ""
        async for piece in llm.stream(
                [{"role": "system", "content": BLOCK_SYSTEM},
                 {"role": "user", "content": user}],
                max_tokens=st.mode.max_tokens, temperature=0.4):
            fresh += piece
            yield piece
        # Replace, don't append: each round rewrites the block from scratch.
        st.content = fresh.strip() or st.content

    # ------------------------------------------------------------ commit --
    async def commit(self, st: State) -> None:
        """Nothing to persist. The block is handed to the editor, which
        decides where it lands; writing it server-side would insert it twice."""

    # ------------------------------------------------------------ prompt --
    def _user(self, st: State, *, facts: str) -> str:
        """The round's user message.

        Only the cursor's neighbourhood goes in, never the whole note. With
        the whole note the model continues the *end of the document* instead
        of filling the position it was asked about, and an eight-round run
        blows the context window besides.
        """
        parts = [f"【笔记标题】{self.title or '未命名'}",
                 f"【这一次要做的事】{st.mode.task}"]
        if self.prompt.strip():
            parts.append(f"【用户的具体要求】{self.prompt.strip()}")
        if self.selection.strip():
            parts.append("【用户选中的这一段（你的输出要替换掉它）】\n"
                         + self.selection.strip()[:2000])
        if self.profile:
            parts.append("【用户的写作偏好】\n"
                         + "\n".join(f"- {p}" for p in self.profile))
        for body in st.skill_bodies:
            parts.append(body)
        if facts:
            parts.append("【工具查到的东西】\n" + facts)
        parts.append("【光标前面的正文】\n" + (st.before[-900:] or "（这里是开头）"))
        if st.after.strip():
            parts.append("【光标后面的正文】\n" + st.after[:450])
        parts.append(
            "【怎么输出】\n只输出要插入到光标位置的那一块内容本身，"
            "不要写「好的」「以下是」这类开场白，不要复述上面的要求，"
            "不要重复光标前面已经有的内容。\n"
            "**这是插进一篇笔记里的一段，不是一篇独立报告。** 标题层级要比上文最近的"
            "标题深一级、数量克制；不要自带「数据质量」「接下来值得看什么」这类"
            "报告式章节——尤其后文可能已经有对应的章节了。\n"
            "图必须是工具返回的 ```mermaid 代码块**原样搬过来**，"
            "**绝对不要用「[柱状图：…]」这样的文字去描述一张图**。")
        return "\n\n".join(parts)


def _produced(trace: ToolTrace, groups: tuple[str, ...]) -> bool:
    """Did the focus groups actually yield something usable?

    Deliberately not "was a tool from those groups called". A charting tool
    that refused three times in a row -- too few data points, every value the
    same -- counts as called and drew nothing, and treating that as done is
    how the harness once shipped a chart-mode block with no chart in it.
    **Judge the output, not the behaviour.**
    """
    from ...tools import registry
    wanted = set(registry.names(list(groups)))
    return any(name in wanted and res and not res.startswith("（")
               for name, _args, res in trace.calls)
