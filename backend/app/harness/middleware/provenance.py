"""Show the user what the tools actually returned.

Grounding cannot be the model's own say-so. Every harness already had some
version of this -- each with its own event shape -- because the provenance
panel is what lets a user check a number instead of trusting it. One
implementation, one payload shape, every harness.
"""

from __future__ import annotations

from typing import AsyncIterator

from ..events import CUSTOM_ROUND, Event
from ..state import State


class Provenance:
    """Report what this round gathered: every tool call, then a summary.

    Named for what it is rather than for the object it reads. It was ``Trace``
    once, which collided with ``State.trace`` -- the tool trace itself -- and
    made "is this the middleware or the field" a question you had to answer by
    reading. Grounding that the user can check is the capability; ToolTrace is
    just where the data comes from.

    The summary is what the round counter and the sources panel read. It has
    to come *after* prepare rather than at the round's start, because before
    prepare there is nothing to report -- and a round header reading "0 facts"
    that never updates is worse than none.
    """

    name = "provenance"
    hooks = ("after_prepare",)
    after: tuple[str, ...] = ("facts",)   # Facts is what decides a call counted

    async def after_prepare(self, st: State) -> AsyncIterator[Event]:
        if st.trace is not None and st.trace.used:
            already = st.bag.setdefault("traced", 0)
            for name, args, result in st.trace.calls[already:]:
                yield Event.tool_result(name, args, result or "")
            st.bag["traced"] = len(st.trace.calls)

        yield Event.custom(CUSTOM_ROUND, {
            "round": st.round,
            "max_rounds": st.mode.max_rounds,
            "facts": len(st.facts_new),
            "sources": st.facts_new[:6],
            "revisions_applied": st.bag.get("revisions_applied", 0),
            "skipped_continue": bool(st.bag.get("cleanup_only")),
            # 「这一轮没查到」和「这个库压根是空的」在界面上原来长得一模一样：
            # 都只是 `facts: 0`，一个字的解释都没有。新用户点了续写，看到的是
            # 「第 1 轮：修订 0 处，续写中…」，完全不知道它手上没有任何材料
            # （第 676 轮）。
            "kb_empty": _kb_empty(st),
            # ---- 「这一轮为什么这么跑」的另外两样（计划 12.1）----
            #
            # ① **上一轮诊断出了什么、有没有真的改到检索计划。** 面板原来只
            # 显示检索预算和温度，而那两个数是 `adjust()` 的**结果**；真正决定
            # 这一轮去查什么的是那句自然语言诊断，它此前一个字都没露过面。
            # `in_plan` 不是自报：`hooks/note.prepare` 是回头在真正发出去的
            # 那条消息里找它（见那一行注释）。**键不在 = 这一轮压根没有检索
            # 规划这一步**（打磨 / 只清理 / 关了 AGENT_TOOLS），跟「有这一步但
            # 诊断没进去」不是一回事，所以用 None 而不是 False。
            **_steer_payload(st),
            # ② 这个模式一共有几条代码判据。**命中的那几条走 `check_hit`
            # 事件，可分母只有这里给得出来**——没有分母，「这一轮判据全过了」
            # 跟「判据根本没跑」在界面上长得一模一样（§21：建了判据不等于
            # 用了判据）。
            "checks_total": len(st.mode.checks),
            # ③ 深度门这一轮丢了几发（批 24）。`truncated` 特意不算它们，
            # 于是「模型发了 4 个调用全被丢掉」此前在界面上什么都看不见。
            "depth_dropped": int(getattr(st.trace, "dropped_depth", 0) or 0),
            "depth_dropped_all": bool(getattr(st.trace, "stopped_all_dropped", False)),
            # ④ 进 prompt 前被相关性筛剔掉的材料（P8 问题 5）：从上千条的主题里抽样回来、
            # 跟这篇零重合的那些。**pop 不是 get**：打磨 / 只清理轮不走取材料那一步，
            # 留着上一轮的值会把「这一轮没筛」报成「这一轮筛掉了 N 条」。
            **_irrelevant_payload(st.bag.pop("facts_irrelevant", None)),
        })


def _irrelevant_payload(dropped) -> dict:
    items = list(dropped or [])
    from ..checks.relevance import fact_body
    return {
        "facts_irrelevant": len(items),
        "irrelevant_sample": [fact_body(f)[:60] for f, _n in items[:3]],
    }


def _steer_payload(st: State) -> dict:
    """上一轮的诊断 + 它这一轮去了哪儿。

    三个键一起给，因为**单给哪一个都会误导**：只给原话，用户以为它进了检索
    计划；只给 `in_plan=False`，用户以为这条诊断被丢掉了——而内在质量那三维
    （重复 / 不连贯 / 跑题）本来就该走修订那条线，那是设计不是漏。
    """
    from ..policy import MATERIAL_DIMS
    dim = str(st.bag.get("focus") or "")
    return {
        "steer": (st.steer or "")[:300],
        "steer_dim": dim,
        # 这一维的诊断是不是**检索**能改善的那一类（`policy.MATERIAL_DIMS`）。
        # 由后端算：这份名单跟 `repair.INNER_QUALITY` 是互补的一对，前端
        # 再抄一份必然会漂。
        "steer_material": bool(dim) and dim in MATERIAL_DIMS,
        "steer_in_plan": st.bag.pop("steer_in_plan", None),
    }


def _kb_empty(st) -> bool:
    """这个用户的知识库一条事实都没有。读不出来就说「不是空的」——
    宁可少说一句，也不要对着一个读失败的索引告诉用户「你没有材料」。"""
    try:
        from ..tools.memory_tools import kb_is_empty
        return kb_is_empty(st.ctx.user)
    except Exception:      # noqa: BLE001
        return False
