"""一次跑到底花多少钱（计划 12.3 的分母）。

## 为什么要重建

`llm_usage` 从批 1 起就按步骤记账（`loop._step` 缀 `:tools` / `:judge`），
可它一行里**没有 run_id**；`harness_rounds` 有 run_id，可它没有 token。
于是「单次跑的成本」这个数在库里不存在，只能把两张表贴回去。

贴法：`harness_rounds` 每一行的 `created_at` 是**那一轮结束**的时刻，所以
一笔用量属于「时间上排在它后面、最近的那一行轮次」——300 秒以内算数
（一次调用最长 300s 超时）。

**这份重建有三处会错，逐条写在报告里，不藏着**：

1. **两次跑重叠**时，重叠那一段的用量会被算到先结束的那一轮头上
   （实测 158 次跑里有 11 对相邻跑是重叠的）；
2. **跑之前的调用贴不上**——`hooks.skeleton` 在 `loop.run` 之前跑完；
3. **挂掉的调用没有 usage、也就没有 `_record`**，白花的钱账上看不见。

所以批 23 顺手把 `harness_runs.tokens` / `.calls` 落了库：**下一次读这个数
的人不用再跑这个脚本**，这里留着是为了「上限当初是拿什么定的」可复现。

## 血缘

`harness_rounds` 里的跑绝大多数是测量脚本触发的，按 `corpus_lineage` 的规矩
**只看形状不算生产发生率**。成本这件事上「形状」正是要的东西——同一段代码、
同一个端点，一次 note 模式的跑要烧多少 token 跟是谁点的没关系。报告里另有
一段**真实用户使用**那几天的交叉验（按间隔聚类，只能当上界）。

## 用法

    cd backend && .venv/bin/python scripts/run_cost_probe.py
    cd backend && .venv/bin/python scripts/run_cost_probe.py --since 2026-09-17T12:00
"""

from __future__ import annotations

import argparse
import bisect
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db_guard                                            # noqa: E402

# 一笔用量最多往后找这么久的一行轮次。300s 是这个端点的调用超时。
WINDOW_S = 300
# 这几个 feature 是**判据灵敏度 bench** 的打分调用，跟任何一次跑都没关系
# （它拿历史产出直接调打分器，不进 `loop.run`）。留在池子里会被贴到隔壁。
NOT_A_RUN = ("bench/sensitivity",)
# 真实用户使用那一段按多长的间隔聚成「一次跑」。**这是上界不是真值**：
# 两次跑挨得近就会被并成一团，所以只拿它跟主口径互相印证，不单独报。
GAP_S = 120


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def q(values: list[int], p: float) -> int:
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * p))]


def attribute(conn, since: str) -> tuple[dict, list, dict]:
    rounds = conn.execute(
        "SELECT run_id, key, round, created_at FROM harness_rounds"
        " WHERE run_id<>'' ORDER BY created_at").fetchall()
    marks = sorted((_dt(r["created_at"]), r["run_id"], r["round"], r["key"]) for r in rounds)
    times = [m[0] for m in marks]

    usage = conn.execute(
        "SELECT created_at, feature, prompt_tokens, completion_tokens, cached_tokens"
        " FROM llm_usage WHERE created_at>=? ORDER BY created_at, id", (since,)).fetchall()

    per_run: dict[str, dict] = defaultdict(lambda: {"tokens": 0, "calls": 0, "cached": 0})
    unattributed: list[tuple[str, str]] = []
    for u in usage:
        if any(u["feature"].startswith(p) for p in NOT_A_RUN):
            continue
        t = _dt(u["created_at"])
        i = bisect.bisect_left(times, t)
        if i >= len(marks) or (times[i] - t).total_seconds() > WINDOW_S:
            unattributed.append((u["created_at"], u["feature"]))
            continue
        slot = per_run[marks[i][1]]
        slot["tokens"] += u["prompt_tokens"] + u["completion_tokens"]
        slot["calls"] += 1
        slot["cached"] += u["cached_tokens"]

    meta: dict[str, dict] = {}
    n_rounds = Counter(r["run_id"] for r in rounds)
    for r in rounds:
        meta.setdefault(r["run_id"], {"key": r["key"], "rounds": n_rounds[r["run_id"]]})

    # 重叠：按开始时间排序，下一次跑的第一轮落在上一次跑的最后一轮之前
    spans = {}
    for m in marks:
        spans.setdefault(m[1], [m[0], m[0]])[1] = m[0]
    ordered = sorted(spans.items(), key=lambda kv: kv[1][0])
    overlaps = sum(1 for a, b in zip(ordered, ordered[1:]) if b[1][0] < a[1][1])
    return per_run, unattributed, {"meta": meta, "overlaps": overlaps,
                                   "rounds": len(rounds)}


def production_clusters(conn) -> list[int]:
    """真实用户使用那几天，按间隔聚类的一次跑花多少。**只是上界。**"""
    rows = conn.execute(
        "SELECT created_at, prompt_tokens, completion_tokens FROM llm_usage"
        " WHERE feature LIKE 'note-harness%' OR feature LIKE 'writing-plan/run%'"
        " ORDER BY created_at, id").fetchall()
    out, cur, prev = [], 0, None
    for r in rows:
        t = _dt(r["created_at"])
        if prev is not None and (t - prev).total_seconds() > GAP_S:
            out.append(cur)
            cur = 0
        cur += r["prompt_tokens"] + r["completion_tokens"]
        prev = t
    if cur:
        out.append(cur)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-09-17T12:00",
                    help="只贴这个时刻之后的用量（更早的没有对应的轮次行）")
    args = ap.parse_args()

    with db_guard.Watch():
        conn = db_guard.readonly()
        per_run, unattributed, info = attribute(conn, args.since)
        prod = production_clusters(conn)
        conn.close()

    tokens = [v["tokens"] for v in per_run.values()]
    if not tokens:
        print("没有贴得上的跑——先跑一次真跑，或者把 --since 往前挪")
        return 1

    print(f"\n== 一次跑花多少（{len(per_run)} 次跑 / {info['rounds']} 轮）==")
    for name, p in (("p25", .25), ("中位", .5), ("p75", .75), ("p90", .9),
                    ("p95", .95), ("p99", .99)):
        print(f"  {name:4s} {q(tokens, p):>9,}")
    print(f"  最大 {max(tokens):>9,}    最小 {min(tokens):>9,}")

    per_round = [v["tokens"] / info["meta"][k]["rounds"] for k, v in per_run.items()]
    print(f"\n== 每轮 ==\n  中位 {int(statistics.median(per_round)):,}"
          f"  p90 {int(q([int(x) for x in per_round], .9)):,}"
          f"  最大 {int(max(per_round)):,}")

    by_mode: dict[str, list[int]] = defaultdict(list)
    for k, v in per_run.items():
        by_mode[info["meta"][k]["key"].split(":")[0]].append(v["tokens"])
    print("\n== 按模式 ==")
    for mode, xs in sorted(by_mode.items(), key=lambda kv: -statistics.median(kv[1])):
        print(f"  {mode:10s} {len(xs):>3} 次  中位 {int(statistics.median(xs)):>8,}"
              f"  最大 {max(xs):>8,}")

    print("\n== 这份重建错在哪（别藏着）==")
    print(f"  两次跑重叠的相邻对：{info['overlaps']}（重叠段的账会算到先结束那次头上）")
    print(f"  贴不上的用量行：{len(unattributed)}")
    for feat, n in Counter(f for _, f in unattributed).most_common(6):
        print(f"    {feat or '(空)':32s} {n}")

    if prod:
        print(f"\n== 交叉验：真实用户使用那几天按 {GAP_S}s 间隔聚类（**上界**）==")
        print(f"  {len(prod)} 团  中位 {int(statistics.median(prod)):,}"
              f"  p90 {q(prod, .9):,}  最大 {max(prod):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
