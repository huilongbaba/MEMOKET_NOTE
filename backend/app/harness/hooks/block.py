"""Hooks for the ``/`` block harness: chart, table, EDA, analysis, prompt,
custom.

What makes this harness different from the long-form ones is one line in
``produce``: a block *replaces* its predecessor rather than continuing it.
Everything else -- accumulating facts across rounds, keeping the charts the
tools really emitted, best-of, stopping -- is shared machinery.
"""

from __future__ import annotations

from typing import AsyncIterator

from .. import agent_loop
from ..middleware import ledger as ledger_mw
from ..params import LEDGER_IN_PROMPT
from ...util import llm
from ..agent_loop import ToolTrace
from .. import prompts
from ..prompts import BLOCK_SYSTEM
from ..state import State
from ..score_context import AFTER_CHARS, BEFORE_CHARS, SELECTION_CHARS
from ..checks.grounding_rules import fix_bold_punct

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
        # 账本摘要进取材那一发（计划 2.4）。**批 26 之前 `gap_summary` 全仓
        # 只有一个读者（`hooks/note.py`），8 个模式接了 1 个**；而批 26 实测
        # 六个 block 模式一次跑内的重复查询率是 **14–40%**，正落在批 13
        # 「只开 2.5 = 17.2%」那一档，`note` 那条接了 2.4 的是 8.6%。
        #
        # **只进 `prepare` 这一发，不进 `produce`。** 它回答的是「还该查什么」，
        # 而写正文那一步问的是「怎么写」——把缺口摆给写作看，是给它一份
        # 「你没有的材料」清单，只会引出占位句。
        gaps = ""
        if LEDGER_IN_PROMPT:
            gaps = ledger_mw.gap_summary(ledger_mw.ledger_of(st))
        msgs = [{"role": "system", "content": self._system(st)},
                {"role": "user", "content": self._user(st, facts="", gaps=gaps)}]
        extra, trace = await agent_loop.gather_context(
            msgs, st.ctx, groups=list(st.mode.groups), max_iters=3)

        if st.mode.focus_groups and not _produced(trace, st.mode.focus_groups):
            # **进去那一侧故意不喂 `known_ids`、也不接着数迭代**（批 24 的 R2）。
            #
            # 看起来这是「同一件事只挡住一半」的又一例：第二次循环的
            # `seen_ids` 从空集起步，第一轮已经取到的事实在它眼里全是新的，
            # `BARREN_STOP` 失效；`trace2.iters` 也从 0 起步，`_cap_calls`
            # 的深度门在补图那一轮整个放开。`hooks/note.py` 恰恰是特意把账本
            # 的 `known_ids` 喂进来的，两处做法相反。
            #
            # **量完是分母为 0，而且是结构性的 0**：这一发的 `groups` 写死成
            # `st.mode.focus_groups`，全仓只有 EDA / ANALYSIS 两个模式声明过
            # 它，两个都是 `("chart",)`；`chart` 组里就 `chart_column` /
            # `chart_from_text` / `render_chart` 三个工具，
            # **跟 `FACT_TOOLS` / `BREADTH_TOOLS` 的交集都是空的**。
            # 而 `seen_ids` 只在 `if name in FACT_TOOLS` 里被读，深度门只丢
            # `name in BREADTH_TOOLS`——补图那一轮两条都走不到。
            #
            # 所以**不改**（批 22 的规矩：分母为 0 就写「不改」并说清理由）。
            # 改成把这两样传进来，加的是两条谁也证明不了它在挡什么的守卫
            # ——§21 说这比没有更糟。
            # **改成把分母钉住**：`tests/test_block_harness.py` 有一条闸，
            # 哪天有哪个模式的 `focus_groups` 里出现了事实类 / 广度类工具，
            # 它当场变红，那时候要做的正是把这两样接上。
            extra2, trace2 = await agent_loop.gather_context(
                msgs + extra + [{"role": "user", "content": _FOCUS_NUDGE}],
                st.ctx, groups=list(st.mode.focus_groups), max_iters=3)
            extra += extra2
            # 整份折进来，不是手抄两个字段——见 `ToolTrace.merge` 的注释：
            # 原来漏掉的 `stopped_barren` / `error` / `truncated` /
            # `barren_calls` 各自都有读者。
            trace.merge(trace2)

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
                [{"role": "system", "content": self._system(st)},
                 {"role": "user", "content": user}],
                max_tokens=st.mode.max_tokens, temperature=0.4):
            fresh += piece
            yield piece
        # Replace, don't append: each round rewrites the block from scratch.
        # 块生成不经过 scrub_meta_sentences，粗体标点那一步在这里单独做。
        st.content = fix_bold_punct(fresh.strip()) or st.content

    # ------------------------------------------------------------ commit --
    async def commit(self, st: State) -> None:
        """Nothing to persist. The block is handed to the editor, which
        decides where it lands; writing it server-side would insert it twice."""

    # ------------------------------------------------------------ prompt --
    def _system(self, st: State) -> str:
        """Base rules, the skills the user scoped to block work, and the menu
        of the rest. Same treatment as the two long-form harnesses -- the six
        block modes had no skill scope at all until now, so anything a user
        configured for them silently did nothing."""
        return prompts.compose_system(BLOCK_SYSTEM, st.mode.skill_scope,
                                      st.ctx.user, st.skill_menu,
                                      st.skill_bodies)


    def _user(self, st: State, *, facts: str, gaps: str = "") -> str:
        """The round's user message.

        Only the cursor's neighbourhood goes in, never the whole note. With
        the whole note the model continues the *end of the document* instead
        of filling the position it was asked about, and an eight-round run
        blows the context window besides.
        """
        parts: list[str] = []
        if gaps:
            # 摆在最前面，跟 `prompts.retrieval_plan_user` 同一条理由：
            # 先知道缺口，后面那些要求才有参照。**默认空串**——`produce`
            # 那一路一个字都不受影响。
            parts.append(gaps)
        parts += [f"【笔记标题】{self.title or '未命名'}",
                  f"【这一次要做的事】{st.mode.task}"]
        if self.prompt.strip():
            parts.append(f"【用户的具体要求】{self.prompt.strip()}")
        if self.selection.strip():
            parts.append("【用户选中的这一段（你的输出要替换掉它）】\n"
                         + self.selection.strip()[:SELECTION_CHARS])
        if self.profile:
            parts.append("【用户的写作偏好】\n"
                         + "\n".join(f"- {p}" for p in self.profile))
        if facts:
            parts.append("【工具查到的东西】\n" + facts)
        # 这三个取量常量在 `harness/score_context.py`，**写作和打分共用同一组**：
        # 批 8 给打分器补上下文时，`fits_context` 判的是「跟周围合不合」——
        # 写作看 900 字、打分看 300 字的话，它会去罚一段写作那一步根本没见过
        # 的上下文。
        parts.append("【光标前面的正文】\n" + (st.before[-BEFORE_CHARS:] or "（这里是开头）"))
        if st.after.strip():
            parts.append("【光标后面的正文】\n" + st.after[:AFTER_CHARS])
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
    from ..tools import registry
    wanted = set(registry.names(list(groups)))
    return any(name in wanted and res and not res.startswith("（")
               for name, _args, res in trace.calls)
