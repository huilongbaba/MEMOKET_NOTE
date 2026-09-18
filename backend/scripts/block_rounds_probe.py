"""六个 block 模式**真的用掉几轮，其中几轮是白跑的**（计划 4.6 / [EVAL] 问题三）。

## 为什么要先量

[EVAL] 问题三的原话是「不建议现在就加，**加之前先看每轮数据**」。而现在
`harness_rounds` 里有真实轮次数据了（批 10 / 13 落的）——只是 block 那一侧
**几乎是空的**：354 行里只有 7 行是 block 模式（全是 `prompt`），4 次跑。
拿 4 次跑去定停机条件，跟拍脑袋没区别。

所以这个脚本补的是**分母**：六个模式各跑几次真跑，记下

* 一次跑用掉几轮、怎么停的；
* 第 N 轮（N≥2）跟第 N-1 轮的产出**像不像**（block 的 `produce` 是**替换**
  不是追加，所以两轮产出可以直接比）；
* 第 N 轮有没有**成为新的最好那一轮**（`State.rank()`，`BestOf` 交的就是它）。

**「白跑」在这里有一个确定的定义**：第 N 轮既没有成为新的最好那一轮，
产出跟上一轮又几乎一样（相似度 ≥ `SAME_RATIO`）。两个条件都要，因为
单看任何一个都会把正常轮次算进去——一轮可能改得很多但没改好（不算白跑，
`regressed` 管它），也可能只动了一个字却正好补上了最后一个不达标的维度。

## 三条硬规矩

1. **绝对不碰用户的真实笔记。** block 模式本来就不挂 `Save`
   （`hooks/block.commit` 是空的），这里再给 Mode 加一层
   `rails_off=("save",)` 兜底，整趟夹在 `db_guard.Watch()` 里。
   **命令不许经过任何管道**——批 16 那次事故是 `| tail` 把退出码吞了。
2. **不画文生图。** `chart` 模式带 `image` 组，`render_image` 一次要几十秒
   还要花外部账；这里 `exclude` 掉它。**这会让 chart 那一行偏乐观**
   （少了一条最慢的路径），报数的时候要说明。
3. 种子里的 `note_id` 是真实笔记，因为 `fits_context` / `heading_fits` /
   工具取数全都要真的前后文——**拿假笔记跑出来的轮次分布不作数**。

## 用法

    cd backend && .venv/bin/python scripts/block_rounds_probe.py --repeats 2
    cd backend && .venv/bin/python scripts/block_rounds_probe.py --only prompt
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import difflib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db_guard                                            # noqa: E402

from app.database import store                             # noqa: E402
from app.harness import loop, modes, score_context, tools   # noqa: E402
from app.harness.events import CUSTOM_EVALUATE             # noqa: E402
from app.harness.hooks.block import BlockHooks             # noqa: E402
from app.harness.state import State                        # noqa: E402

# 两轮产出像到这个份上就当「什么都没变」。0.95 不是拍的：block 的
# `produce` 每轮整块重写，措辞总会飘一点；实测（见台账批 19）把线放到 0.90
# 会把「真的改了一小节」也算进来，收到 0.98 又会漏掉「只换了几个词」。
SAME_RATIO = 0.95

USER = "terrence"
# 这篇里有一张真的数据表（benchmark 分数，正文 414 字符处），光标放在表后面。
NOTE_WITH_TABLE = "309f19202309"


@dataclasses.dataclass
class Seed:
    mode: str
    note_id: str
    cursor: int
    prompt: str = ""
    selection: str = ""


SEEDS: list[Seed] = [
    Seed("eda", NOTE_WITH_TABLE, 1000),
    Seed("chart", NOTE_WITH_TABLE, 1000, prompt="把这张表里几个方法的总分画成对比图"),
    Seed("table", NOTE_WITH_TABLE, 1000, prompt="把上面几个方法的 token 开销和总分整理成一张表"),
    Seed("analysis", NOTE_WITH_TABLE, 1000, prompt="哪个方法的总分最高，领先第二名多少"),
    Seed("prompt", NOTE_WITH_TABLE, 1000, prompt="用两段话说明这张表说明了什么，不要列点"),
    Seed("custom", NOTE_WITH_TABLE, 1000, prompt="把这段改得更简洁，保留全部数字"),
]


def _context_block(content: str, cursor: int, span: int = 900) -> tuple[str, str]:
    """跟 `routers/compose_block._context_block` 一模一样。**共用不了**：
    那个函数住在 router 里，import 它会把整个 FastAPI 栈拖进来。
    抄一份的代价是它可能漂——所以下面有一条断言逐字对着它。"""
    cur = max(0, min(cursor, len(content)))
    return content[max(0, cur - span):cur], content[cur:cur + span // 2]


async def _run_one(seed: Seed) -> dict:
    note = store.get_note(USER, seed.note_id) or {}
    content = note.get("content") or ""
    title = note.get("title") or ""
    selection = seed.selection or (content[seed.cursor:seed.cursor + 300]
                                   if seed.mode == "custom" else "")

    mode = modes.BLOCK[seed.mode]
    # 兜底：block 本来就不挂 Save，这一行是"万一以后挂了"的保险。
    # chart 的文生图排掉，理由见模块头第 2 条。
    mode = dataclasses.replace(
        mode, rails_off=("save",),
        exclude=tuple(mode.exclude) + (("render_image",) if seed.mode == "chart" else ()))

    before, after = _context_block(content, seed.cursor)
    st = State(mode=mode,
               ctx=tools.ToolContext(user=USER, note_id=seed.note_id,
                                     note_title=title, content=content,
                                     cursor=seed.cursor),
               before=before, after=after)
    st.bag["score_context"] = score_context.for_block(
        before=before, after=after, prompt=seed.prompt, selection=selection)
    st.bag.update(prompt=seed.prompt, selection=selection, profile=[])
    hooks = BlockHooks(prompt=seed.prompt, selection=selection, title=title)

    rounds: list[dict] = []
    stopped = ""
    t0 = time.perf_counter()
    async for event in loop.run(st, hooks):
        data = event.data or {}
        if data.get("name") == CUSTOM_EVALUATE:
            value = data.get("value") or {}
            rounds.append({"round": value.get("round"),
                           "status": value.get("status"),
                           "scores": {k: v["level"]
                                      for k, v in (value.get("scores") or {}).items()},
                           "content": st.content})
        if event.type == "RUN_FINISHED":
            stopped = (event.data or {}).get("reason", "") or ""
    return {"mode": seed.mode, "rounds": rounds, "stopped": stopped,
            "seconds": round(time.perf_counter() - t0, 1)}


def _rank(scores: dict[str, int]) -> tuple[int, float]:
    """跟 `State.rank()` 同一个折叠。**不 import 它**是因为那个方法读的是
    `State.ev`，而这里手上只有事件里那份分数快照。"""
    levels = list(scores.values())
    if not levels:
        return (-1, -1.0)
    return (sum(1 for v in levels if v >= 2), sum(levels) / len(levels))


def analyse(runs: list[dict]) -> dict:
    total_rounds = wasted = same = no_gain = 0
    per_mode: dict[str, dict] = {}
    for run in runs:
        rounds = run["rounds"]
        slot = per_mode.setdefault(run["mode"], {"runs": 0, "rounds": 0, "wasted": 0,
                                                 "stopped": {}})
        slot["runs"] += 1
        slot["rounds"] += len(rounds)
        slot["stopped"][run["stopped"]] = slot["stopped"].get(run["stopped"], 0) + 1
        total_rounds += len(rounds)
        best = (-1, -1.0)
        for i, r in enumerate(rounds):
            rank = _rank(r["scores"])
            became_best = rank > best
            best = max(best, rank)
            if i == 0:
                continue
            ratio = difflib.SequenceMatcher(
                None, rounds[i - 1]["content"], r["content"]).ratio()
            r["same_as_prev"] = round(ratio, 3)
            r["became_best"] = became_best
            same += ratio >= SAME_RATIO
            no_gain += not became_best
            if ratio >= SAME_RATIO and not became_best:
                wasted += 1
                slot["wasted"] += 1
    return {"runs": len(runs), "rounds": total_rounds, "wasted": wasted,
            "same_as_prev": same, "no_gain": no_gain, "per_mode": per_mode}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default="scripts/block_rounds_log.jsonl")
    args = ap.parse_args()

    seeds = [s for s in SEEDS if not args.only or s.mode == args.only]
    runs: list[dict] = []
    with db_guard.Watch():
        for _ in range(args.repeats):
            for seed in seeds:
                try:
                    runs.append(asyncio.run(_run_one(seed)))
                except Exception as exc:                   # noqa: BLE001
                    print(f"[!] {seed.mode} 跑挂了：{type(exc).__name__}: {exc}")
        report = analyse(runs)

    with open(args.out, "a", encoding="utf-8") as fh:
        for run in runs:
            fh.write(json.dumps({**run, "rounds": [
                {k: v for k, v in r.items() if k != "content"} for r in run["rounds"]]},
                ensure_ascii=False) + "\n")

    print(f"\n跑了 {report['runs']} 次、共 {report['rounds']} 轮")
    print(f"第 2 轮起：跟上一轮几乎一样 {report['same_as_prev']} 轮、"
          f"没成为新的最好那轮 {report['no_gain']} 轮、"
          f"**两样都占（白跑）{report['wasted']} 轮**")
    print(f"\n{'模式':10s} {'跑':>3s} {'轮':>3s} {'白跑':>4s}  停机原因")
    for mode, slot in report["per_mode"].items():
        print(f"{mode:10s} {slot['runs']:3d} {slot['rounds']:3d} {slot['wasted']:4d}  "
              f"{slot['stopped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
