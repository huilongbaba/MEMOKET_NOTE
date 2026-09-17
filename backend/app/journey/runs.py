"""把**连着说同一件事**的段并成一块。

前端有一份一模一样的（`frontend/src/util/journeyRuns.ts`），两边干的事不一样：
  · 前端用它排时间轴——一段连续的事摊成八行近似重复，那一页就读成流水账；
  · 后端用它喂日报——**同一件事喂八遍，模型会把它当成八件事来权衡**，
    而这一天真正推进了什么反而被这八遍压下去。

**两份实现必须一致**，所以进了 `frontend/scripts/check-journey-merge.mts`
那个对拍脚本（它本来就是管「壳和后端两份分段实现别漂」的）。
判据怎么定的、门槛为什么是 .45，见 TS 那一份的注释——数是在真实产出上量的。
"""

from __future__ import annotations

from datetime import datetime

SIM = 0.45
GAP_MIN = 15


def similar(a: str, b: str) -> float:
    """两句话像不像。二元组 Dice——**中文没有词边界**，按字切二元组对中文和
    夹在中间的英文标识符都成立。这里不用 `difflib`：跟前端那份必须逐位对得上，
    而 `SequenceMatcher` 没法在 TS 里原样复刻。"""
    def grams(s: str) -> set[str]:
        t = "".join(s.lower().split())
        return {t[i:i + 2] for i in range(len(t) - 1)}
    A, B = grams(a), grams(b)
    if not A or not B:
        return 0.0
    return 2 * len(A & B) / (len(A) + len(B))


def _minutes_between(a: str, b: str) -> float:
    try:
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60
    except (TypeError, ValueError):
        return float("inf")          # 时间读不出来就当隔得很远：宁可不并


def group_runs(segs: list[dict]) -> list[dict]:
    """并成块。每块 `{"segs": [...], "start", "end", "app", "desc"}`。

    `desc` 取**最长的那一句**：它们说的是同一件事，取信息最多的那条——
    具体的文件名 / 报错往往只出现在其中一条里。
    """
    runs: list[dict] = []
    for s in segs:
        cur = runs[-1] if runs else None
        lead = cur["segs"][0] if cur else None
        fits = False
        if cur is not None and lead is not None and cur["app"] == s.get("app", ""):
            if _minutes_between(cur["end"], s.get("start", "")) < GAP_MIN:
                ld, sd = (lead.get("desc") or "").strip(), (s.get("desc") or "").strip()
                # 跟**块首**比，不跟上一条比：一条一条往下传会飘
                # （a 像 b、b 像 c，而 a 跟 c 已经是两件事了）。
                fits = similar(ld, sd) >= SIM if (ld or sd) else True
        if not fits:
            runs.append({"segs": [s], "start": s.get("start", ""), "end": s.get("end", ""),
                         "app": s.get("app", ""), "desc": s.get("desc") or ""})
            continue
        cur["segs"].append(s)
        cur["end"] = s.get("end", "")
        if len((s.get("desc") or "").strip()) > len(cur["desc"].strip()):
            cur["desc"] = s.get("desc") or ""
    return runs
