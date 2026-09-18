"""跑之前，把这篇「完成标准」里代码判得了的那几条挂成这一次跑的判据（P13 #1）。

跟 `middleware/checklist.py` 同一条理由、同一个做法：`Mode` 必须是纯数据，而这条判据的
内容来自用户在标题下写的那句「完成标准」——所以不写死在 `Mode.checks` 上，`before_run`
时 `dataclasses.replace` 出一份这次跑专用的 Mode。判定本身在 `checks/done.py`（跟前端
`util/doneChecks.ts` 是同一份，两边闸盯着）。

一个字都不判的时候一条判据都不挂：没写完成标准、写的全是代码判不了的（「争议点两边都写」）、
或者代码判得了的全被用户勾掉了——那时 `checks_total` 跟没有这个功能时一样。
"""

from __future__ import annotations

import dataclasses

from ...editor import intent as doc_intent
from ..checks import done as done_checks
from ..state import State


class DoneCriteria:
    """`note` 专用（分段 harness 没有笔记级意图，那条线用的是计划的 goal）。挂在 `extra_mw` 上。"""

    name = "done_criteria"
    hooks = ("before_run",)
    after: tuple[str, ...] = ()

    async def before_run(self, st: State) -> None:
        done = doc_intent.done_of(st.ctx.intent)
        if not done:
            return
        checked = tuple(getattr(st.ctx, "intent_checked", ()) or ())
        if not done_checks.judgeable(done, checked, polish=bool(st.bag.get("polish"))):
            return
        if done_checks.done_criteria not in st.mode.checks:
            st.mode = dataclasses.replace(st.mode, checks=insert_done(st.mode.checks))


# 它排在哪（P15 #1）。P13 照 `instruction_constraints` 抄成排最后（第 17 条）——真跑 4 轮一次没轮到：
# 第 1 轮 `citations_present`（第 10 条）先响，第 2–4 轮 `no_same_sources_twice`（第 14 条）连响三轮停机。
# 先量后定（台账 P15 #1 那张拦截表）：p5–p14 共 22 次真跑、74 次判据命中里，材料族（`citations_present` 36 /
# `material_thin` 3 / `material_used` 1 / `no_placeholder` 1）41 次、重复族（`no_same_sources_twice` 27 /
# `no_repeated_lists` 5）+ 图 1 共 33 次；带完成标准的三次真跑 19 轮离线重放，它会响的 5 轮里 1 轮是材料族先响
# **且说的是同一件事**（补编号），4 轮是重复族先响、说的是另一件事。所以插在**材料族之后、重复族之前**：
# 材料族说的跟它是一回事，让材料族先说不亏；重复族说的是另一件事，用户明写的标准不该排在它后面。
# 「第一条响的赢」不改：量出来两条同时成立的那一轮说的是同一句话，同时报只是重复。
_AFTER = "material_used"


def insert_done(checks: tuple) -> tuple:
    """把 `done_criteria` 插在 `material_used` 后面；这个模式没有它就排最后。"""
    names = [getattr(c, "__name__", "") for c in checks]
    pos = names.index(_AFTER) + 1 if _AFTER in names else len(checks)
    return checks[:pos] + (done_checks.done_criteria,) + checks[pos:]
