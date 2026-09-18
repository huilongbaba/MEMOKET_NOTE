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
            st.mode = dataclasses.replace(st.mode, checks=st.mode.checks + (done_checks.done_criteria,))
