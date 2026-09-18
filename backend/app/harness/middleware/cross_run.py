"""这一次跑完，比上一次差吗（计划 9.3 / [EFF] P2）。

`BestOf` 和 `loop._regressed` 都只管**一次跑内部**「哪一轮最好」。用户第二次
点「跑」的时候，**没有任何东西在比「这次跑完是不是比上次差」**——而实测三篇
笔记反复跑同一篇，分数是单调下滑的：9→6→4、9→7→4→3。

`harness_runs` 里一直有历史（`policy.from_history` 已经在读它拿弱维度），
这里拿同一份数据回答另一个问题。

**只报，不替用户决定。** 计划第 4 节「不做」里写死了：不做跨跑自动回滚。
所以这个 middleware 一个字都不改，只发一条 `cross_run` 事件；界面那一半
（计划 12.4）把它显示成一句话 + 一条「上一版在历史里」的指路。

**可比才比**（同批 22 那份 Pareto 重放的口径）：两次跑的**维度集合必须相
同**，而且两边都得真打过分。维度集合会随「有没有风格档案」「是不是打磨
模式」变（`modes.for_run`），拿不同的维度集合折叠出来的两个标量比大小，
比出来的是配置差异不是质量差异。

**为什么跑在 `History` 前面**：`History` 这一步就把这次跑写进 `harness_runs`
了，之后再去读「最近一次」读到的是自己。这条依赖不靠注释：`History` 声明
了 `after=("cross_run",)`，`middleware/_order.verify` 每次组链都验一遍。
"""

from __future__ import annotations

from typing import AsyncIterator

from .. import adapter as harness_adapter
from ..events import CUSTOM_CROSS_RUN, Event
from ..state import State


def _rank(scores: dict[str, int]) -> tuple[int, float]:
    """跟 `State.rank()` 同一个折叠。**不 import 它**是因为那个方法读的是
    `State.ev`，而这里手上是两份历史分数向量。"""
    levels = list(scores.values())
    if not levels:
        return (-1, -1.0)
    return (sum(1 for v in levels if v >= 2), sum(levels) / len(levels))


def compare(now: dict[str, int], last: dict[str, int]) -> dict | None:
    """这次比上次差在哪。不可比 / 没变差返回 None。"""
    if not now or not last or set(now) != set(last):
        return None
    a, b = _rank(now), _rank(last)
    if a >= b:
        return None
    worse = sorted(d for d in now if now[d] < last[d])
    return {
        "met": a[0], "last_met": b[0],
        "mean": round(a[1], 2), "last_mean": round(b[1], 2),
        "dimensions": worse,
    }


class CrossRun:
    name = "cross_run"
    hooks = ("after_run",)
    after: tuple[str, ...] = ()

    async def after_run(self, st: State) -> AsyncIterator[Event]:
        from .history import records_this_run, final_scores

        if not records_this_run(st):
            # 这次跑自己都不会进历史（一轮没跑过 / 停下来等处置），拿它跟
            # 上一次比没有意义——`History` 的条件是唯一一份，别在这儿抄。
            return
        now = final_scores(st)
        if not now:
            return
        recent = harness_adapter.SqliteRunHistoryStore().recent(
            f"{st.mode.key}:{st.ctx.note_id}", limit=1)
        if not recent:
            return
        diff = compare(now, recent[0].final_scores or {})
        if diff is None:
            return
        names = "、".join(diff["dimensions"])
        yield Event.custom(CUSTOM_CROSS_RUN, {
            **diff,
            "detail": (f"这次跑完比上一次差：达标 {diff['last_met']} 维 → "
                       f"{diff['met']} 维（{names} 掉了档）。上一次的正文在"
                       f"「历史版本」里，要回去随时可以。"),
        })
