"""事实自召回复测：随机抽 N 条事实，拿原文 / 前 40 字当查询，看自己在不在 top-5。

    .venv/bin/python scripts/recall_selfcheck.py [user] [n] [seed] [evidence]

不打模型，几十秒。第 388 轮（seed 7, n 60）58/57；第 527 轮把英文虚词 / 说话人标签从
查询词和 grep 槽里剔掉之后 60/60，seed 11 n 200 是 196/194。数字掉了就是召回退化。
"""
from __future__ import annotations

import random
import statistics
import sys

sys.path.insert(0, ".")
from app.database.kite.kite_memory import UserMemory  # noqa: E402


def _corpus_tag(user: str) -> str:
    """语料的出身：`KITE_DATA_DIR` 下这个人的 codebook 有多大、内容摘要是什么。

    **为什么要它**（第 777 轮）：台账上同一格「留下率」躺着两组数、都没写参数——
    P34 记 197/195/95，P42–P48 **五批记着同一个 194/190/103**，而那五批各自都改过
    `kb/` 的代码。实测：同一份语料上 `terrence 200 11` 稳定 197/195/95，
    而 194/190/103 在 seed 7/11/42 三档里一档都对不上。**那个数不是每批真跑的，是抄的。**

    光有参数还不够：P29 抓到过一份「拷贝」里四个 `codebook.xml` 是 718 字节的空壳，
    而那一批所有「全库」的数都建在它上面。**同样的参数在不同语料上是不同的数。**
    所以这一格把「在哪份语料上跑的」跟数字绑在一起——**整行抄进台账，出身跟着走。**
    """
    import hashlib
    import os
    from pathlib import Path
    root = Path(os.environ.get("KITE_DATA_DIR") or (Path(__file__).resolve().parent.parent / "data"))
    cb = root / user / "codebook.xml"
    if not cb.is_file():
        return "no-codebook"
    return f"{cb.stat().st_size}B/{hashlib.sha256(cb.read_bytes()).hexdigest()[:8]}"


def main(user: str = "terrence", n: int = 60, seed: int = 7, evidence: bool = False) -> None:
    """`evidence` 那一档是**右栏那条路真走的**（`routers/memory.recall` 的 `evidence=True`）。

    **为什么补这个开关**（P61）：台账「留下率不许跌」四栏里第四栏一直是
    「`evidence=True` 190 / 185 / 68」这种手写数，P46 / P54 / P56 三次在旁边打过
    「⚠️ 这个数没带参数、复现不出来」——因为**这个脚本根本没有这一档**，
    那一栏是每批各自在 scratch 里改一份跑出来的，而 scratch 每批都会被清掉。
    补一个位置参数就够：`recall_selfcheck.py terrence 200 11 evidence`，
    出身（用户 / 种子 / n / 语料指纹 / 走的哪条路）**全在它自己打出来的那一行里**。
    """
    m = UserMemory(user)
    idx = m._index()
    store = idx[0] if isinstance(idx, tuple) else idx
    facts = list(store.facts.values())
    random.seed(seed)
    sample = random.sample(facts, min(n, len(facts)))

    def hit(q: str, fid: str) -> tuple[bool, float]:
        rows, _terms, took = m.recall(q, limit=5, evidence=evidence)
        ids = [(r.get("id") if isinstance(r, dict) else getattr(r, "id", None)) for r in rows]
        return fid in ids, took

    full = short = topic = 0
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
        # 第三个口径（search.py 文档里那 53% 那条）：排除它自己，前 5 里有没有同主题的别的事实
        rows, _terms, _took = m.recall(f.text[:40], limit=6, evidence=evidence)
        mine = set(getattr(f, "topics", ()) or ())
        others = [r for r in rows if (r.get("id") if isinstance(r, dict) else getattr(r, "id", None)) != f.id][:5]
        if mine and any(mine & set((store.facts.get(r.get("id") if isinstance(r, dict) else getattr(r, "id", "")) or f).topics or ()) for r in others):
            topic += 1
    head = "evidence=True " if evidence else ""
    print(f"{head}user={user} seed={seed} n={len(sample)} corpus={_corpus_tag(user)}: full {full}/{len(sample)}  short40 {short}/{len(sample)}  sametopic(excl self, short40) {topic}/{len(sample)}  median {statistics.median(times):.0f} ms")
    for line in misses:
        print("MISS", line)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0] if a else "terrence", int(a[1]) if len(a) > 1 else 60, int(a[2]) if len(a) > 2 else 7,
         len(a) > 3 and a[3] == "evidence")
