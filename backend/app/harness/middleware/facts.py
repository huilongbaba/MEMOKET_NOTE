"""Accumulate material across rounds, and trim it -- welded together.

Two separate bugs came out of doing only one half:

* **Reset per round.** The output accumulates but the material didn't, so
  round 3's scoring judged the whole piece using only round 3's material.
  This shipped in note_harness, then again in compose_block, then sat
  undiscovered in writing_plan (where measurements later showed its rounds
  losing 0.278 on average while the other two held steady).
* **No ceiling.** Three separate accumulators grew without bound.

Welding them means there is no way to write "accumulate but don't trim".
"""

from __future__ import annotations

import re

from ..params import FACT_INDEX
from ..state import State

# 材料行开头的事实 id：``[terrence-2046-2F3] 正文……``。跟 `ledger._FACT_LINE`
# 是同一种形状——**故意不共用那一个**：那边的正则带 `re.M` 是拿来扫整段工具
# 返回体的，这边匹配的是单独一行，共用会让「改一处修 A、顺手破 B」变成可能。
_FACT_ID = re.compile(r"^\[([A-Za-z0-9_\-]+)\]")


class Facts:
    """Fold this round's haul into the run's material.

    Note this trims a *list of fact strings*; it is not the same thing as
    ``Compact``, which folds a long body of prose into section summaries.
    Different shapes, different functions -- they were conflated once in the
    design and it produced a call to a function that doesn't exist.
    """

    name = "facts"
    hooks = ("after_prepare",)
    after: tuple[str, ...] = ()

    async def after_prepare(self, st: State) -> None:
        if st.bag.get("cleanup_only"):
            # A repair round does not go looking for material, so "found
            # nothing" is not a finding about the material. Counting it as a
            # dry round measured wrong immediately: two repair rounds in a row
            # and the run stopped with "material_used_up" on a note whose
            # knowledge base had just returned 22 facts.
            return
        # ---- 事实索引取代 `[-40:]`（计划 3.2 / [CE] §7 / [MR] §3.5）----
        #
        # 原来这里是 `st.facts = (st.facts + fresh)[-st.mode.fact_budget:]`。
        # `[-40:]` 是**从头部丢**，[CE] §7 把它排在信息损失的最差那一档
        # （按位置丢，完全不看重要性），三条代价：
        #
        #   1. **丢信息**——攒满之后每来一条新的就挤掉一条旧的，永久没了；
        #   2. **断缓存前缀**——整块事实每加一条就整体平移，前缀从这里起
        #      逐字都不一样（[CE] §2①）；
        #   3. **换进换出**——规划器不知道 A 曾经在过，过两轮又查一次把 A
        #      取回来，再挤掉另一条。每一次都花一次工具调用（[MR] §1）。
        #
        # 改法：**全量只追加地攒在 `facts_all` 里，一条不丢**；进 prompt 的
        # 是「更早那些压成一行索引（id + 一行）+ 最近 fact_budget 条逐字」。
        # 索引行是**指针**——`fact_sources` 这个工具本来就在，全文随时取得回来。
        #
        # 两条缓解跟正文那一半是同一对（[CE] §7 明写「必须一起上」）：
        # 索引块里写清楚怎么取全文；**最近那几条永远逐字给**，一次工具都不调
        # 也写得下去。
        all_facts = st.bag.setdefault("facts_all", [])
        # 托盘（P14，`harness/tray.py` 第三条）：用户摊在桌上的那几行**钉在 `st.facts` 头上**，
        # 不进 `facts_all`（它们不是哪一轮「取到」的，每轮都在）、不算 fresh（不影响 dry_rounds）、
        # 不受 `fact_budget` 窗口滚动、也不压进「更早几轮」的一行索引。
        pinned = [f for f in (st.bag.get("tray_lines") or []) if f]
        fresh = [f for f in st.facts_new if f not in all_facts and f not in pinned]
        all_facts.extend(fresh)
        if FACT_INDEX:
            budget = st.mode.fact_budget
            st.facts = pinned + (all_facts[-budget:] if budget else list(all_facts))
            st.bag["facts_index"] = _index_lines(
                all_facts[:-budget] if budget else [], st.bag.get("ledger"))
        else:
            # 回退：一字不差的老行为（`params.FACT_INDEX`），托盘照样钉在头上。
            st.facts = pinned + all_facts[-st.mode.fact_budget:]
            st.bag["facts_index"] = []

        if st.trace is not None:
            for chart in _mermaid_of(st.trace):
                if chart not in st.charts:
                    st.charts.append(chart)

        # A round that brought back nothing new. Long-form harnesses use this
        # to notice the topic is exhausted -- though see the note in modes.py:
        # the existing threshold almost never fires, because every round
        # retrieves fact rows that differ in wording while saying the same thing.
        st.bag["dry_rounds"] = 0 if fresh else st.bag.get("dry_rounds", 0) + 1


def _index_lines(older: list[str], ledger: dict | None) -> list[str]:
    """更早那些事实 → 一行一条的索引。

    **一行从哪来：账本**（`middleware/ledger.py` 的 `facts[fid]["line"]`）。
    它已经在存 id + 一行 + 状态 + 日期了——**那就是这份索引，不另造一份**。
    账本里没有的（`_retrieve` 兜底回来的、多跳结果这类不带 id 的），退回按
    原文截一段：漏掉它比截短它更糟，那等于又丢了一条。
    """
    facts = ((ledger or {}).get("facts") or {})
    out: list[str] = []
    for f in older:
        m = _FACT_ID.match(f)
        fid = m.group(1) if m else ""
        line = (facts.get(fid) or {}).get("line") if fid else ""
        if not line:
            line = f[len(fid) + 2:].strip() if fid else f
            line = line[:60]
        out.append(f"[{fid}] {line}" if fid else line)
    return out


def _mermaid_of(trace) -> list[str]:
    """Mermaid blocks the tools actually emitted.

    Kept so ``charts_from_tools`` can compare byte-for-byte: the model has
    been observed copying a tool's output and adjusting it, which produces
    charts that look right and don't render.
    """
    from ..checks.blockcheck import mermaid_blocks

    out: list[str] = []
    for _name, _args, result in trace.calls:
        out.extend(mermaid_blocks(result or ""))
    return out
