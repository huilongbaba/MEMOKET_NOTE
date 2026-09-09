"""The harness runtime: one loop, shared by every writing feature.

A harness = one ``Mode`` (configuration) + one ``Hooks`` (three callbacks).
Everything else -- the round loop, the event contract, the middleware chain,
the two kinds of judgement -- is shared and lives here.

See ``docs/harness-framework.md`` for the reasoning behind every decision in
this package. The short version:

* The loop is hardcoded. All 12 frameworks surveyed do it this way; we had
  three hand-copied loops (555 + 245 + 156 lines) and paid for it four times
  over with "one harness has it, the other doesn't" bugs.
* Judgement splits in two: ``Check`` (code decides) and ``Dimension`` (model
  decides). Anything code can decide reliably must not be left to the model,
  because the scorer and the thing being scored are the same local model --
  its blind spots overlap exactly with the writer's.
* Capabilities are middleware, on by default. Opt-out is explicit; opt-in
  is how things get forgotten.

这个包里的文件分三类，按「读代码时会先找哪个」排：

**① 循环本身**——加一条 harness 不用碰这几个
    loop.py       run()：取材料 → 生成 → 判 → 停不停
    state.py      State：一次 run 的全部数据
    types.py      Mode · Hooks · Middleware · Check · Verdict · Dimension …
    modes.py      8 个功能的全部配置 + 停机条件 + 运行时维度裁剪
    events.py     AG-UI 事件契约
    params.py     跨 harness 的两个续写预算 + AGENT_TOOLS 开关

**② 循环用得上的能力**
    agent_loop.py 工具循环：让模型自己决定查什么
    skills.py     SKILL.md 目录的读写
    adapter.py    app 和 harness 之间的接缝（两个 Protocol 的实现）
    snapshot.py   State ⇄ JSON，轮末暂停用

**③ 某一个 middleware 背后的纯逻辑**——都是「给个字符串就能测」的规则，
    单独成文件是因为它们比使用它们的 middleware 长
    revision.py       修订怎么定位、怎么应用、四道防线   → middleware/revise
    policy.py         这一轮的观测怎么变成下一轮的参数   → middleware/runtime
    replan_rules.py   骨架该不该改、改完合不合法         → middleware/replan

子包：``hooks/``（每条 harness 自己写的三个回调）· ``middleware/``（能力
包）· ``checks/``（判据，代码判和模型判两半）· ``tools/``（模型能按名字
调的东西）· ``sandbox/``（第三方 skill 脚本的笼子）。
"""

from .events import Event, EventType
from .state import State
from .types import Check, Hooks, Middleware, Mode, StopCondition, Verdict

__all__ = [
    "Check",
    "Event",
    "EventType",
    "Hooks",
    "Middleware",
    "Mode",
    "State",
    "StopCondition",
    "Verdict",
]
