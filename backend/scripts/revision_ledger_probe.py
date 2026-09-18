"""`revisions_proposed` / `revisions_dropped` 这两列里到底有什么（计划 12.2）。

## 为什么要真跑

批 21 加了这两列（`harness_rounds`），批 21 / 批 22 **一次模型调用都没发**，
所以到批 23 为止**一行数据都没有**。批 21 的下一步②原话：

> 如果「静默 `continue`」那四条路占了大头（尤其锚点找不到），那该补的是
> 事件不是界面；如果大头是守卫拦下的，30.2% 本身就值得去看守卫是不是太狠。

这两条路要分开，靠的是一个**减法**：

    revisions_dropped（落库，= 提出 − 落地）
  − `dropped` 事件里真正的修订丢弃（守卫拦下的，用户看得见）
  = **静默 `continue` 的那几条**（不是 dict / op 不认识 / 锚点找不到 /
    改完跟原文一样）——「用户看不到、我们也没统计」里最看不见的一半。

`dropped` 事件有两类不是这个意思，要剔掉：**输出被截断**那一条和
**删掉一句元话语**那几条（`revise.py` 里发的），它们不是「一条修订被拦下」。

## 三条硬规矩（跟 `block_rounds_probe.py` 一样）

1. **绝对不碰用户的真实笔记。** Mode 加 `rails_off=("save",)`，整趟夹在
   `db_guard.Watch()` 里。`middleware/edits`（批 23 新加的采集）也认这一条，
   所以这趟连 `note_revisions` 都不会多一行。**命令不许经过任何管道**。
2. **种子的 `note_id` 是真实笔记**，因为工具取数、`content_at_start` 那些
   都要真的上下文——拿假笔记跑出来的修订分布不作数。正文从库里读，只读。
3. **spine / beats 直接给**，不让它现生成：那是一次跟这个问题无关的模型调用。

## 用法

    cd backend && .venv/bin/python scripts/revision_ledger_probe.py --runs 3
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db_guard                                            # noqa: E402

from app.database import store                             # noqa: E402
from app.harness import loop, modes                        # noqa: E402
from app.harness import tools                              # noqa: E402
from app.harness.events import CUSTOM_DROPPED, CUSTOM_REVISION   # noqa: E402
from app.harness.hooks.note import NoteHooks               # noqa: E402
from app.harness.state import State                        # noqa: E402

USER = "terrence"
NOTE_ID = "309f19202309"
SPINE = "把这篇里已经写下来的判断和它的依据对齐，缺依据的说清楚缺在哪"
BEATS = ["现状：手上已经有的记录说明了什么",
         "取舍：这一轮为什么这么定",
         "接下来：还缺哪几条才能下结论"]

# `dropped` 事件里**不是**「一条修订被守卫拦下」的那两类，按原话前缀认。
# 写死在这儿而不是去 import：`revise.py` 那两处发的是 f-string，没有可复用的
# 常量，而把它们算进守卫那一档会让「静默的那一半」凭空变小。
NOT_A_GUARD_DROP = ("修订输出被截断", "删掉一句元话语", "修订调用")


async def _one(rounds: int) -> dict:
    note = store.get_note(USER, NOTE_ID) or {}
    content = note.get("content") or ""
    mode = dataclasses.replace(
        modes.for_run(modes.NOTE, has_profile=False, polish=False),
        max_rounds=rounds, rails_off=("save",))
    st = State(mode=mode,
               ctx=tools.ToolContext(user=USER, note_id=NOTE_ID,
                                     note_title=note.get("title") or ""),
               content=content)
    st.bag["score_context"] = {"核心张力": SPINE,
                               "结构节拍": "\n".join(f"- {b}" for b in BEATS)}
    hooks = NoteHooks(spine=SPINE, beats=BEATS, profile=[])

    landed, guard_drops, other_drops = 0, 0, []
    t0 = time.perf_counter()
    async for event in loop.run(st, hooks):
        data = event.data or {}
        if data.get("name") == CUSTOM_REVISION:
            landed += 1
        elif data.get("name") == CUSTOM_DROPPED:
            detail = str((data.get("value") or {}).get("detail") or "")
            if detail.startswith(NOT_A_GUARD_DROP):
                other_drops.append(detail[:60])
            else:
                guard_drops += 1

    run_id = str(st.bag.get("run_id") or "")
    rows = store.rounds_of_run(run_id)
    return {
        "run_id": run_id,
        "rounds": len(rows),
        "stopped": st.stopped,
        "proposed": sum(r["revisions_proposed"] for r in rows),
        "dropped_col": sum(r["revisions_dropped"] for r in rows),
        "landed_events": landed,
        "guard_drop_events": guard_drops,
        "other_drop_events": other_drops,
        "per_round": [{"round": r["round"],
                       "proposed": r["revisions_proposed"],
                       "dropped": r["revisions_dropped"]} for r in rows],
        "seconds": round(time.perf_counter() - t0, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--rounds", type=int, default=3,
                    help="`Revise` 从第 2 轮才开工，所以 <2 的话这两列恒 0")
    ap.add_argument("--out", default="scripts/revision_ledger_log.jsonl")
    args = ap.parse_args()

    out: list[dict] = []
    with db_guard.Watch():
        for i in range(args.runs):
            try:
                out.append(asyncio.run(_one(args.rounds)))
                print(f"[{i + 1}/{args.runs}] {out[-1]}")
            except Exception as exc:                        # noqa: BLE001
                print(f"[!] 第 {i + 1} 次跑挂了：{type(exc).__name__}: {exc}")

    with open(args.out, "a", encoding="utf-8") as fh:
        for row in out:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    proposed = sum(r["proposed"] for r in out)
    dropped = sum(r["dropped_col"] for r in out)
    guard = sum(r["guard_drop_events"] for r in out)
    print(f"\n== {len(out)} 次跑、{sum(r['rounds'] for r in out)} 轮 ==")
    print(f"  提出（落库 revisions_proposed）      {proposed}")
    print(f"  落地（revision 事件）                {sum(r['landed_events'] for r in out)}")
    print(f"  丢掉（落库 revisions_dropped）        {dropped}"
          f"  = 提出的 {dropped / max(1, proposed) * 100:.1f}%")
    print(f"  其中守卫拦下、用户看得见的（dropped 事件）  {guard}")
    print(f"  **静默 continue 掉的（没事件、没人看见）**  {dropped - guard}")
    others = [d for r in out for d in r["other_drop_events"]]
    if others:
        print(f"  另有 {len(others)} 条 `dropped` 不是修订丢弃（截断 / 元话语）：")
        for d in others[:5]:
            print(f"    {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
