"""事实自召回复测：随机抽 N 条事实，拿原文 / 前 40 字当查询，看自己在不在 top-5。

    .venv/bin/python scripts/recall_selfcheck.py [user] [n] [seed]

不打模型，几十秒。第 388 轮（seed 7, n 60）58/57；第 527 轮把英文虚词 / 说话人标签从
查询词和 grep 槽里剔掉之后 60/60，seed 11 n 200 是 196/194。数字掉了就是召回退化。
"""
from __future__ import annotations

import random
import statistics
import sys

sys.path.insert(0, ".")
from app.database.kite.kite_memory import UserMemory  # noqa: E402


def main(user: str = "terrence", n: int = 60, seed: int = 7) -> None:
    m = UserMemory(user)
    idx = m._index()
    store = idx[0] if isinstance(idx, tuple) else idx
    facts = list(store.facts.values())
    random.seed(seed)
    sample = random.sample(facts, min(n, len(facts)))

    def hit(q: str, fid: str) -> tuple[bool, float]:
        rows, _terms, took = m.recall(q, limit=5)
        ids = [(r.get("id") if isinstance(r, dict) else getattr(r, "id", None)) for r in rows]
        return fid in ids, took

    full = short = 0
    times: list[float] = []
    misses: list[str] = []
    for f in sample:
        h, t = hit(f.text, f.id)
        full += h
        times.append(t)
        if not h:
            misses.append(f"{f.id} {f.text[:60]!r}")
        h2, _ = hit(f.text[:40], f.id)
        short += h2
    print(f"user={user} seed={seed} n={len(sample)}: full {full}/{len(sample)}  short40 {short}/{len(sample)}  median {statistics.median(times):.0f} ms")
    for line in misses:
        print("MISS", line)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0] if a else "terrence", int(a[1]) if len(a) > 1 else 60, int(a[2]) if len(a) > 2 else 7)
