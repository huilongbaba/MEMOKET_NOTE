"""跑之前，把用户那条指令变成这一次专属的判据（计划 6.1 + 6.2 / [IND] §4）。

两样东西，一次挂上去：

* **能用代码判准的**（字数 / 段数 / 「必须提到 X」）→ 一条 `Check`
  （`checks/instructions.instruction_constraints`）。判据在 `before_judge` 里
  跑，命中就短路打分调用——一分钱模型的钱都不花。
* **判不准的** → 一次模型调用生成的 instruction-specific checklist，
  每条一个**二元**维度（`harness/checklist.py`）。

**为什么是 middleware 而不是写进 `Mode`**：`Mode` 必须是纯数据
（`types.Mode` 的原话：「skills 在运行时层叠上去，所以这里不能放任何只有代码
才供得上的东西」），而这两样的内容来自用户刚打的那句话。做法照 `for_run()`
那一条既有的路子——`dataclasses.replace` 出一份这次跑专用的 Mode。

**一次跑只生成一次**（`before_run`，不是 `before_round`）：指令整趟不变，
每轮重生成既多花钱，又会让判据在轮与轮之间漂——那样连"这一轮比上一轮好不好"
都不再可比（`_regressed` / `BestOf` 全靠跨轮可比）。

## 这一步多花多少钱

`prompt` / `custom` 的 `max_rounds=3`，一次跑本来是「每轮 1 次检索规划
（工具循环可能多几次）+ 1 次续写 + 至多 1 次打分」。生成 checklist 是
**整趟一次**、prompt 里只有指令（加上 `custom` 的选区）。

批 17 在真库上实测两条指令（`309f19202309`，同一篇同一位置，开关两臂各跑一次）：

| | 这一次调用 | 占这一趟 prompt token | 占墙上时间 |
|---|---|---:|---:|
| 「分三点总结…必须提到「众筹」」 | 373 prompt / 91 completion / 2.5s | **3.0%** | 8.7% |
| 「接着写一段…不超过 200 字」 | 358 prompt / 8 completion / 2.0s | **5.9%** | 13.8% |

第二条那 8 个 completion token 是 `{"items": []}`——**唯一的要求已经被代码
判了**，模型很正确地什么都没再加，这一趟于是退回原来那三条维度。
"""

from __future__ import annotations

import dataclasses

from .. import checklist as synth
from .. import params
from ..checks.instructions import Constraint, extract, instruction_constraints
from ..state import State

# 账本里这一步叫什么。`loop._step` 已经在按步骤给 `ctx_feature` 缀名
# （`:tools` / `:judge`），这里借同一套——**不另造第二套步骤名**，
# 否则「这一步花了多少」在用量表里又得按两种写法各查一遍。
STEP = "checklist"


class Checklist:
    """`prompt` / `custom` 专用。挂在 `extra_mw` 上，不进 `BASE`。

    不进 BASE 是有依据的，不是保守：别的六个模式里，用户那条指令要么不存在
    （chart / table / eda 常常什么都不打），要么是模式自己的 task 而不是用户
    的要求——对着一句系统写死的话生成"这一次专属"的判据，生成出来的必然是
    通用条目，也就是 RaR 论文里效果明显更差的那一档。
    """

    name = "checklist"
    hooks = ("before_run",)
    after: tuple[str, ...] = ()

    async def before_run(self, st: State) -> None:
        if not params.PROMPT_CHECKLIST:
            return
        instruction = (st.bag.get("prompt") or "").strip()
        if not instruction:
            # 用户什么都没打（`/` 直接回车）。**这时候一条判据都不该加**：
            # 没有指令就没有"这一条指令特有的要求"，硬生成只会拿模式的 task
            # 编出一堆通用条目。
            return

        constraints = st.bag.get("prompt_constraints")
        if constraints is None:
            constraints = list(extract(instruction))
            st.bag["prompt_constraints"] = constraints
        constraints = tuple(c for c in constraints if isinstance(c, Constraint))

        items = st.bag.get("checklist")
        if items is None:
            items = list(await self._synthesize(st, instruction, constraints))
            st.bag["checklist"] = items
        # 恢复的跑（`snapshot.loads`）走的就是上面这个 `is None` 分支的另一边：
        # bag 里已经有上次生成好的条目，**不再花第二次调用**，也保证暂停前后
        # 判的是同一张清单。
        items = tuple(x for x in items if isinstance(x, synth.Item))

        self._attach(st, items, constraints)

    # ------------------------------------------------------------------
    async def _synthesize(self, st: State, instruction: str,
                          constraints: tuple[Constraint, ...]) -> tuple[synth.Item, ...]:
        """生成清单。**任何失败都只意味着"这次不加判据"**，不许把一次跑弄崩。

        `loop._fire` 确实会把 middleware 抛的异常接成一个警告事件，但那会在
        界面上冒出一条用户看不懂的报错，而这一步失败的正确表现是「跟没有这个
        功能时一模一样」。
        """
        from .. import adapter                    # 延迟 import：middleware 不该在模块层拉起 app 侧
        try:
            with _step():
                return await synth.synthesize(
                    adapter.AppLLMClient(), instruction,
                    selection=(st.bag.get("selection") or ""),
                    constraints=constraints)
        except Exception:                                  # noqa: BLE001
            return ()

    def _attach(self, st: State, items: tuple[synth.Item, ...],
                constraints: tuple[Constraint, ...]) -> None:
        """把生成出来的判据挂进这一次跑的 Mode。

        两样都可能是空的，而且**空的时候一个字都不加**：
        没有条目就不动 `dims`，没有约束就不挂那条 check——退回去正好是
        `PROMPT_DIMS` / `CUSTOM_DIMS` 原来那三条（计划 6.1 要求的兜底路径）。
        """
        dims = st.mode.dims + synth.to_dimensions(items)
        checks = st.mode.checks
        if constraints and instruction_constraints not in checks:
            checks = checks + (instruction_constraints,)
        if dims != st.mode.dims or checks != st.mode.checks:
            st.mode = dataclasses.replace(st.mode, dims=dims, checks=checks)


class _step:
    """把这一次调用记在 `…:checklist` 名下。

    借 `loop._step`（**不抄第二份**）：账本按 `ctx_feature` 分步骤，两处各写一份
    「怎么拼步骤名」的话，用量表里迟早出现两种拼法、而那张表正是用来回答
    「多花的这次调用值不值」的。
    """

    def __enter__(self):
        from .. import loop
        self._cm = loop._step(STEP)
        return self._cm.__enter__()

    def __exit__(self, *exc):
        return self._cm.__exit__(*exc)
