"""这次跑花了多少，以及花超了就停（计划 12.3 / [MECH] §7）。

[MECH] §7 的原话是「成本从不进入停机决策」：`judge` 只说 continue /
complete / blocked，不问「再花十几秒值不值」，而数据是反的——

    跑 1 轮   17 次   达标 53%
    跑 2 轮   10 次   达标 30%
    跑 3–4 轮  7 次   达标 29%

**这个 middleware 不解决那件事**（「继续」该不该有收益预期是另一笔）。
它只做两件事，都是"先能看见"那一层：

1. **把这次跑的开销记下来**——`llm_usage` 一直在按步骤记账，可它一行里没有
   run_id，于是「一次跑花多少」只能靠时间窗口重建（批 23 就是这么量的，
   158 次跑贴上了 1880 行用量、63 行贴不上，两次跑重叠时还会算到隔壁）。
   这里把它落进 `harness_runs.tokens` / `.calls`，从此是一个能直接 SELECT
   的数。
2. **超了就停下来告诉用户**，不静默截断（上限和它的分布依据写在
   `params.RUN_TOKEN_CAP`）。

**账本从哪来**：`util/llm._record` 是全仓唯一一处记用量的地方，`before_run`
在那条调用链上绑一个 dict（`llm.bind_usage_sink`），此后每一笔往上加。

**量不到的那一档要说清楚**：
* 开跑**之前**的调用不算——`hooks.skeleton` 在 router 里、在 `loop.run`
  之前跑完（实测 `skeleton` 这个 feature 一共 25 笔、平均 ≈2.3k token）；
* 挂掉的调用不算——没有 usage 就没有 `_record`，超时 / 400 那几笔是白花的
  钱，账上看不见。**所以这个数是偏低的**，上限因此也偏保守。
"""

from __future__ import annotations

from typing import AsyncIterator

from ...util import llm
from .. import params
from ..events import CUSTOM_COST, CUSTOM_WARNING, Event
from ..state import State


def spent(st: State) -> int:
    """这次跑到目前为止的 token（入 + 出）。没绑账本就是 0。"""
    sink = st.bag.get("cost") or {}
    return int(sink.get("prompt_tokens", 0)) + int(sink.get("completion_tokens", 0))


def over_cap(st: State) -> bool:
    """花超了没有。上限 ≤ 0 = 关掉这条规则。

    **住在这儿而不是 `loop.py` 里**：停机规则 `_over_budget` 和这个
    middleware 的报信都要问同一个问题，写两份会飘（同 `State.coverage_unmet`
    在批 22 被搬进 `state.py` 的理由）。
    """
    cap = int(st.bag.get("token_cap") or 0)
    return cap > 0 and spent(st) >= cap


class Cost:
    """每一轮结束时结一次账；超了发一条 `cost`，停机规则跟着收工。"""

    name = "cost"
    hooks = ("before_run", "after_round")
    after: tuple[str, ...] = ()

    async def before_run(self, st: State) -> None:
        # 恢复一次暂停的跑时，快照里已经有上半场的账（bag 进快照），接着记。
        sink = st.bag.setdefault("cost", {"calls": 0, "prompt_tokens": 0,
                                          "completion_tokens": 0, "cached_tokens": 0})
        llm.bind_usage_sink(sink)
        # 上限存进 bag 而不是每次现读 `params`：一次跑中途改环境变量就换了
        # 判据，那样"这次跑为什么停了"事后答不出来。
        st.bag.setdefault("token_cap", params.RUN_TOKEN_CAP)

    async def after_round(self, st: State) -> AsyncIterator[Event]:
        sink = st.bag.get("cost") or {}
        if sink.get("tally_error"):
            # 记账本身出错过。**不静默**：这时 `spent()` 偏低，上限会判「没超」。
            yield Event.custom(CUSTOM_WARNING, {
                "middleware": self.name, "hook": "after_round",
                "error": f"这次跑有 {sink['tally_error']} 笔用量没记上，成本数字偏低",
            })
        if not over_cap(st):
            return
        yield Event.custom(CUSTOM_COST, {
            "round": st.round,
            "tokens": spent(st),
            "cap": int(st.bag.get("token_cap") or 0),
            "calls": int(sink.get("calls", 0)),
            "detail": (f"这次跑到第 {st.round} 轮已经花掉 {spent(st):,} token"
                       f"（{sink.get('calls', 0)} 次调用），到了单次跑的上限 "
                       f"{int(st.bag.get('token_cap') or 0):,}，就停在这儿了"),
        })
