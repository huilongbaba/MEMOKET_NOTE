"""批 22 的分母：`best_of` 的 `rank()` 标量折叠，跟 Pareto 挑差在哪。

    cd backend && .venv/bin/python scripts/best_of_pareto_probe.py

**只读**（`db_guard.readonly()` + `Watch()`），一次模型调用都不发。

## 为什么要有这么一个脚本

计划 11.2 的依据是第 602 轮的一次实拍：四轮全被代码判据打回、`rank()` 一律
`(0, 0.0)`、best 从头到尾钉在第 1 轮，后三轮的修订全被扔掉。
[IND] §6⑤（GEPA）的做法是保留 Pareto 前沿、不把多维分数压成一个标量。

**但是**：`harness_rounds` 里已经有真实的多轮分数向量（批 10 / 13 落的），
「换成 Pareto 会不会挑到不同的那一轮」是个能直接算出来的问题，不该靠推理。
这个脚本把每一次跑重放一遍，报四组数：

| 段 | 量什么 |
|---|---|
| ① 折叠会不会挑错 | `rank()` 挑的那一轮，有没有被同一次跑里别的轮次 **Pareto 支配** |
| ② 前沿有多大 | 前沿有几个成员；`rank()` 挑的是不是最靠后的那个前沿成员 |
| ③ 602 那个形状还在不在 | 全程判据短路（所有轮次 `rank()` 都是 `(0, 0.0)`）的跑，best 落在第几轮 |
| ④ 覆盖反转 | 后一轮把某个**覆盖**维度写达标、代价是别的维度掉一档，于是排名反而更低 |

## 口径说明（每一条都踩过）

* **判据短路那一轮的分数是伪造的**（`middleware/checks.py` 只塞一个维度、
  分数 0），跟真打出来的向量根本不可比——所以支配比较只在「真打过分**且
  维度集合相同**」的轮次之间做。这跟 `Ledger` 不把它记进 `score_vectors`、
  `Repair` / `loop._regressed` 开头排除 `skip_judge` 是同一条理由。
* **`rank()` 的平手归后来者**（`>=`）照原样复现，否则③会报出一个假的 602。
* `harness_rounds` 里的跑**绝大多数是测量脚本触发的**（soak / bench / 探针）。
  按 `corpus_lineage` 的规矩，这里报的是**形状**：哪一类分歧存在、长什么样。
  比例只在同一张表内部当相对量用，不要拿去当生产发生率。
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import db_guard  # noqa: E402

# 跟 `app/harness/state.py` 的 `COVERAGE_DIMS` 是同一份名单。这里手抄一份而
# 不是 import：脚本只连 sqlite，不该把整个 app 包（连着 kite / fastapi）拖起来。
# 抄错的代价由 `tests/test_scripts_import.py` 之外的一条断言兜着——见
# `tests/test_best_of_pareto.py::test_探针脚本抄的覆盖维度名单跟实现一致`。
COVERAGE_DIMS = ("beat_coverage", "section_coverage", "material_use")


def rank(scores: dict) -> tuple[int, float]:
    """逐字复现 `State.rank()`：没打上分的垫底，否则 (达标维度数, 均分)。"""
    if not scores:
        return (-1, -1.0)
    levels = list(scores.values())
    return (sum(1 for v in levels if v >= 2), sum(levels) / len(levels))


def kind(scores: dict) -> str:
    """真打过分 / 判据短路伪造的 / 压根没打上分。

    **靠维度个数分**：伪造的那份只有一个维度（`middleware/checks.py`），
    而八个模式的 `dims` 最少也有 3 个。库里实测：`note` 的 365 轮里
    单维 237 轮、六维 125 轮、零维 3 轮，中间没有别的取值。
    """
    if not scores:
        return "unscored"
    return "blocked" if len(scores) == 1 else "scored"


def load_runs(db=db_guard.DEFAULT_DB) -> dict[str, list[dict]]:
    conn = db_guard.readonly(db)
    runs: dict[str, list[dict]] = collections.defaultdict(list)
    for row in conn.execute(
            "SELECT run_id, key, round, scores, content_len "
            "FROM harness_rounds ORDER BY run_id, round"):
        r = dict(row)
        r["sc"] = json.loads(r["scores"] or "{}")
        runs[r["run_id"]].append(r)
    conn.close()
    return runs


def dominates(a: dict, b: dict, dims: list[str]) -> bool:
    """a 每一维都不比 b 差，且至少一维更好。"""
    return (all(a[d] >= b[d] for d in dims) and any(a[d] > b[d] for d in dims))


def best_of(rounds: list[dict]) -> dict:
    """复现 `BestOf.after_judge`，**平手归后来者**。"""
    best, picked = None, None
    for r in rounds:
        k = rank(r["sc"])
        if best is None or k >= best:
            best, picked = k, r
    return picked


def analyse(runs: dict[str, list[dict]]) -> dict:
    out = collections.Counter()
    domin: list[tuple] = []
    tiebreak: list[tuple] = []
    inversions: list[tuple] = []
    for _rid, rs in runs.items():
        if len(rs) < 2:
            out["单轮跑"] += 1
            continue
        out["多轮跑"] += 1

        # ③ 602 那个形状
        if all(kind(x["sc"]) != "scored" for x in rs):
            out["全程判据短路的多轮跑"] += 1
            if best_of(rs) is rs[-1]:
                out["…其中 best 落在最后一轮"] += 1

        # ④ 覆盖反转：逐轮重放，问「这一轮把覆盖写达标了，却排名更低」
        best, holder = None, None
        for r in rs:
            k = rank(r["sc"])
            if (holder is not None and kind(r["sc"]) == "scored"
                    and kind(holder["sc"]) == "scored" and k < best
                    and best[0] >= max(1, len(r["sc"]) - 1)
                    and not _cov_unmet(r["sc"]) and _cov_unmet(holder["sc"])):
                out["武装且覆盖反转"] += 1
                inversions.append((rs[0]["key"], holder["round"], r["round"],
                                   holder["content_len"], r["content_len"]))
            elif (holder is not None and kind(r["sc"]) == "scored" and k < best
                  and best[0] >= max(1, len(r["sc"]) - 1)):
                out["武装但 best 也写够了"] += 1
            if best is None or k >= best:
                best, holder = k, r

        # ①② 支配 / 前沿
        scored = [x for x in rs if kind(x["sc"]) == "scored"]
        shapes = {tuple(sorted(x["sc"])) for x in scored}
        if len(scored) < 2 or len(shapes) != 1:
            continue
        out["可比多轮跑"] += 1
        dims = sorted(scored[0]["sc"])
        front = [x for x in scored
                 if not any(dominates(y["sc"], x["sc"], dims) for y in scored)]
        pick = best_of(scored)
        if any(dominates(y["sc"], pick["sc"], dims) for y in scored):
            out["rank 挑的那一轮被支配"] += 1
            domin.append((rs[0]["key"], pick["round"]))
        if len(front) == 1:
            out["前沿只有一个成员"] += 1
        elif front[-1] is pick:
            out["前沿多成员，rank 挑的正是最后一个前沿成员"] += 1
        else:
            out["前沿多成员，rank 挑的不是最后一个"] += 1
            tiebreak.append((rs[0]["key"], pick["round"], front[-1]["round"],
                             pick["content_len"], front[-1]["content_len"]))
    return {"counts": out, "dominated": domin,
            "tiebreak": tiebreak, "inversions": inversions}


def _cov_unmet(scores: dict) -> bool:
    return any(scores[d] < 2 for d in COVERAGE_DIMS if d in scores)


def main() -> int:
    with db_guard.Watch():
        res = analyse(load_runs())
    for k, v in res["counts"].most_common():
        print(f"{k:>42}  {v}")
    print()
    print("① rank 挑的那一轮被 Pareto 支配的：", len(res["dominated"]) or "0 次")
    for row in res["dominated"]:
        print("   ", row)
    print("② 前沿多成员、但 rank 挑的不是最靠后那个（key, rank 挑第几轮, "
          "最后一个前沿成员是第几轮, 两者正文长度）：")
    for row in res["tiebreak"]:
        print("   ", row)
    print("④ 覆盖反转（key, best 是第几轮, 这一轮, best 正文长度, 这一轮正文长度）：")
    for row in res["inversions"]:
        print("   ", row)
    return 0


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(main())
