"""在那份固定的 47 条标注上，拿**当前代码**重放一遍召回的证据判据（P38 #1）。

**为什么有这个文件。** P27 / P29 / P32 / P34 各自抽了 45–47 条逐条读过，
**四份标注全丢了**（scratch 目录被清）。于是 P34 只能重抽一份，还得专门解释
「这张抽样表说明不了什么」。标注是这条线上最贵的东西——它是人一条一条读出来的，
代码可以重跑，人读不能。**所以它进仓库。**

样本：`tests/fixtures/memory_sample.jsonl`（47 条 + 一行 `_meta` 写着口径）。
库侧：`tests/fixtures/memory_sample_corpus.json`——`qualifies` 的三个注入口
（`common` / `attested` / `segment`）全部来自这个人的 11 MB codebook，
那份库进不了仓库，所以把**这 47 条上会被问到的那点答案**冻下来，判据就能离线重放。

**这份样本能答什么、答不了什么**（口径原样写在 `_meta` 里，这里重复一遍最要紧的那句）：
它是**分层抽的**（血缘 × 命中形状），不是随机的。它能答「判据改动的方向对不对」，
**答不了「全库误判率是多少」**。而且改动幅度小的时候它的分辨率不够——
P34 只动了 7.1% 的对，47 条上期望只有 3 条会变，实际变了 1 条。
**那种批次的证据是把变了的对全部逐条读一遍，不是这张表。**

用法：
    python -m scripts.memory_sample_replay            # 人看的表
    python -m scripts.memory_sample_replay --json     # 机器读的
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
SAMPLE = FIXTURES / "memory_sample.jsonl"
CORPUS = FIXTURES / "memory_sample_corpus.json"

_CJK_ONLY = re.compile(r"[一-鿿]{2,8}\Z")


def load_sample(path: Path = SAMPLE) -> tuple[dict, list[dict]]:
    """回 `(_meta, 47 条)`。第一行是 `_meta`，其余每行一条标注。"""
    meta: dict = {}
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if "_meta" in obj:
            meta = obj["_meta"]
        else:
            rows.append(obj)
    return meta, rows


class FrozenCorpus:
    """冻下来的库侧事实，装成 `UserMemory` 那三个注入口的样子。

    `df` 里记的是 `[units_for(词) 的大小, unit_df(词, floor=0)]`；**查不到 = df 0**
    （建夹具时 df 0 的条目不记，省下九成体积）。`[null, null]` = 这个词预筛不了
    （形状里有正则元字符），调用方按「不知道」处理——跟真索引一个字不差。
    """

    def __init__(self, blob: dict, user: str) -> None:
        u = blob["users"][user]
        self._df: dict[str, list] = u["df"]
        self._vocab = set(u["vocab"])
        self.unit_count: int = u["unit_count"]

    def unit_df(self, term: str, *, floor: int = 0):
        rec = self._df.get(term)
        if rec is None:
            return 0
        sub, exact = rec
        if sub is None:
            return None
        if sub < floor:
            return sub
        return exact

    # ---- 三个注入口，跟 `kite_memory` 那三个方法一一对应 ----

    def common_term(self):
        from app.database.kb import relations as R

        total = self.unit_count
        if not total:
            return None

        def is_common(term: str) -> bool:
            n = self.unit_df(term, floor=R.COMMON_DF_MIN)
            return n is not None and n >= R.COMMON_DF_MIN and n / total >= R.COMMON_DF_RATIO

        return is_common

    def vocab_term(self):
        if not self._vocab:
            return None
        return lambda term: term in self._vocab

    def segment(self):
        from app.database.kb import tokenize as tok
        from app.database.kite.kite_memory import _corpus_word

        extra = {w for w in self._vocab if _CJK_ONLY.match(w)}
        attest = _corpus_word(self) if self.unit_count else None
        t = tok.Tokenizer(extra, attest=attest)
        if not t.enabled():
            return None
        return t.cut


def replay(rows: list[dict], corpus_blob: dict) -> list[dict]:
    """每条标注 + **当前代码**判它留不留，以及它凭哪几条证据留下来。"""
    from app.database.kb import search

    per_user: dict[str, FrozenCorpus] = {}
    out: list[dict] = []
    for r in rows:
        c = per_user.get(r["user"])
        if c is None:
            c = per_user[r["user"]] = FrozenCorpus(corpus_blob, r["user"])
        common, attested, segment = c.common_term(), c.vocab_term(), c.segment()
        ev = search.evidence(r["hit"], r["query"], common=common,
                             attested=attested, segment=segment)
        kept = search.qualifies(r["hit"], r["query"], common=common,
                                attested=attested, segment=segment)
        out.append({**r, "kept": kept, "evidence": ev})
    return out


def tally(judged: list[dict]) -> dict:
    kept = [r for r in judged if r["kept"]]
    n = len(kept)
    by = {k: sum(1 for r in kept if r["label"] == k) for k in ("hard", "meh", "bad")}
    return {"留下": n, "hard": by["hard"], "meh": by["meh"], "bad": by["bad"],
            "误判率": round(by["bad"] / n, 4) if n else 0.0}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--verbose", action="store_true", help="逐条打出来")
    args = ap.parse_args()

    meta, rows = load_sample()
    judged = replay(rows, json.loads(CORPUS.read_text(encoding="utf-8")))
    now = tally(judged)
    hist = meta.get("历史", [])

    if args.json:
        print(json.dumps({"now": now, "history": hist,
                          "rows": [{"i": r["i"], "label": r["label"], "kept": r["kept"],
                                    "evidence": r["evidence"]} for r in judged]},
                         ensure_ascii=False))
        return 0

    print(f"样本：{SAMPLE.name}（{len(rows)} 条，{meta.get('谁标的', '')}）")
    print(f"口径：{meta.get('怎么抽的', '')}")
    print(f"答不了：{meta.get('答不了什么', '')}")
    print()
    print(f"{'批':<12}{'留下':>6}{'硬':>6}{'勉强':>6}{'不硬':>6}{'误判率':>9}")
    for h in hist:
        print(f"{h['批']:<12}{h['留下']:>6}{h['hard']:>6}{h['meh']:>6}"
              f"{h['bad']:>6}{h['误判率']:>9}")
    print(f"{'当前代码':<12}{now['留下']:>6}{now['hard']:>6}{now['meh']:>6}"
          f"{now['bad']:>6}{now['误判率'] * 100:>8.0f}%")

    if args.verbose:
        for r in judged:
            mark = "留" if r["kept"] else "砍"
            terms = "/".join(f"{e['term']}({e['why']})" for e in r["evidence"]) or "—"
            print(f"[{r['i']:>2}] {mark} {r['label']:<5} {r['lineage']}/{r['shape']:<12} {terms}")
    return 0


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    os.environ.setdefault("KITE_DATA_DIR", "/nonexistent-memory-sample-replay")
    raise SystemExit(main())
