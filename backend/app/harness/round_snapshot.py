"""烧之前的快照（P16，agent-native-editor §3.2 / 痛点 8）。

## 为什么

分层账本在前端 9/12 就做完了：每层能开关、接受、撤回。但**接受 = 烧进正文，层就没了**——
用户「改了三轮，想留第一轮、丢第三轮」这件事，只在烧之前做得到。方案原话：
「历史版本保留每次烧之前的快照」。

## 怎么做

这里不是 middleware（`middleware/**` 另一条线在改），是套在 `loop.run` 事件流外面的一层：

* `STEP_STARTED`（第 N 轮开始、`before_round` 还没跑）→ 把 loop 手里此刻的 `st.content` 存成
  `note_revisions` 一行：`reason='round'`、`round_no=N`、`run_id` 指回这次跑。这就是第 N 轮
  **烧之前**的正文——修订 pass 跑在这之后，所以「之前」是真的之前。
* `RUN_FINISHED`（跑完 / 暂停等处置）→ 最后一轮的「之后」。正常跑完的跑 `Edits.after_run` 已经落了
  `reason='harness'` 一行（带 `round_no`，P18 #2），这里看到它就不再存；没有（暂停、没进 `harness_runs`）
  才存 `reason='run_end'`。第 N 轮的「之后」= 同一次跑里紧跟着它的下一行（第 N+1 轮的 round 行 /
  harness / run_end）。P16 那阵子同一份正文存了 `run_end` + `harness` 两行，老数据前端两种都认。

## 边界

* **只在「产出会变成那篇笔记」的跑上存**（`middleware/save.writes_note`）：`rails_off=("save",)`
  的跑批脚本一行都不许往 `note_revisions` 里写（它是 `db_guard` 指纹盯着的两张表之一，批 14 / 16
  的事故）；block 模式的 `st.content` 是一个块，不是这篇笔记。
* `run_id` 是 `Ledger` 在第 1 轮 `after_prepare` 才生成的，第 1 轮的 `STEP_STARTED` 比它早——
  所以这里先生成，`Ledger` 只在没有时才生成，同一个值。
* 存不进去不影响这次跑（跟 `middleware/edits` 同一条规矩：采集不承重）。
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

from ..database import store
from .events import Event, EventType
from .middleware.save import writes_note
from .state import State


def _run_id(st: State) -> str:
    if not st.bag.get("run_id"):
        st.bag["run_id"] = uuid.uuid4().hex[:12]
    return str(st.bag["run_id"])


def _save(st: State, reason: str, round_no: int) -> str:
    """返回版本 id；不该存 / 存不下回空串。"""
    if not writes_note(st) or not st.ctx.note_id or not (st.content or "").strip():
        return ""
    try:
        return store.snapshot_content(st.ctx.user, st.ctx.note_id, st.ctx.note_title, st.content,
                                      reason, run_id=_run_id(st), round_no=round_no)
    except Exception:                                   # noqa: BLE001
        return ""      # 快照不承重：写不进去也不能影响这次跑交出去的正文


async def with_round_snapshots(events: AsyncIterator[Event], st: State) -> AsyncIterator[Event]:
    """套在 `loop.run(st, hooks)` 外面：每轮开始前、收尾时各存一版，事件原样透传。"""
    last_round = 0
    async for event in events:
        if event.type is EventType.STEP_STARTED:
            last_round = int(event.data.get("step") or st.round or 0)
            _save(st, store.REVISION_REASON_ROUND, last_round)
        elif event.type is EventType.RUN_FINISHED and last_round:
            # 一轮都没跑（precheck 挡下）就没有「之后」可存。
            # `Edits` 已经落了这次跑的 `harness` 行（同一份正文、带 round_no）就不再存第二行（P18 #2）。
            if not (st.ctx.note_id and store.find_run_revision(
                    st.ctx.user, st.ctx.note_id, str(st.bag.get("run_id") or ""), store.REVISION_REASON_HARNESS)):
                _save(st, store.REVISION_REASON_RUN_END, last_round)
        yield event
