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


#: 默认那一组 —— P34 分层抽的 47 条，`replay` / `tally` / P38 那几条闸都在它上面
DEFAULT_SET = "p34-sample47"


def load_sample(path: Path = SAMPLE, *, set_name: str = DEFAULT_SET) -> tuple[dict, list[dict]]:
    """回 `(_meta, 这一组的那些条)`。

    文件里现在装着**三组**（P42 A3 起，每组一行 `_meta` + 若干条，用 `set` 分开）：
      · `p34-sample47` —— P34 分层抽的 47 条，`qualifies` 的重放和 P38 那三条闸都在它上面
      · `p42-allpair82` —— 「两个弱证据凑够 2」那一形状的**全部** 82 对，冻的是**位置指标**
      · `p44-frag64` —— P44 的两条显示过滤在**用户看得见的前 3 个**里砍掉的**全部** 64 串次，
        冻的是**查询的分词结果**（`cut`），所以 `display_stats` 离线就能逐条重算

    **三组各答各的，谁也别拿去跟谁比**：前两组标的是「这条召回沾不沾边」，
    第三组标的是「这个词摆出来是不是碎的」，连标注体系都不是一回事（每组 `_meta` 里都写着）。

    **默认只回第一组**，这样 P38 写的一切（replay / tally / 三条闸）一个字不用改。
    老格式（没有 `set` 字段）按默认组算——夹具是资产，读它的代码不许挑格式。
    """
    meta: dict = {}
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if obj.get("set", DEFAULT_SET) != set_name:
            continue
        if "_meta" in obj:
            meta = obj["_meta"]
        else:
            rows.append({k: v for k, v in obj.items() if k != "set"})
    return meta, rows


def position_stats(terms: list[str], query: str, fact: str) -> dict:
    """证据串在**查询**和**事实**里的排布（P42 A1）。**纯函数，不碰库。**

    量的是「两串离得近不近」这件事的两个侧面：`qgaps` 是相邻两串在挤掉空白的查询里
    隔了几个字，`fgaps` 是同样两串在事实里隔了几个字（负数 = 在事实里反了序 / 重叠），
    `dmax = max|qgap - fgap|`——**一整句原话逐字对上时它是 0**。

    P42 A1 拿全库 82 对量完的结论是**这个量程分不开**：`dmax ≤ 5` 那一档虽然
    「留下的 24 条一条误判都没有」，但代价是 25 硬换 30 不硬（1.20 : 1），
    按这条线的账法不够。数留在 `memory_sample.jsonl` 的 `p42-allpair82` 那一组里，
    下一批要再试位置判据，拿这个函数在那 82 条上重算，**不用再读一遍**。
    """
    ws = re.compile(r"\s+")
    q, f = ws.sub("", (query or "").lower()), ws.sub("", (fact or "").lower())

    def locate(run: str, hay: str, near=None):
        idx = [m.start() for m in re.finditer(re.escape(run), hay)]
        if not idx:
            return None
        return idx[0] if near is None else min(idx, key=lambda i: abs(i - near))

    qpos = {}
    for r in terms:
        i = locate(r, q)
        if i is not None:
            qpos[r] = (i, i + len(r))
    ordered = sorted((r for r in terms if r in qpos), key=lambda r: qpos[r][0])
    fpos, prev = {}, None
    for r in ordered:
        i = locate(r, f, near=prev)
        if i is not None:
            fpos[r] = (i, i + len(r))
            prev = i + len(r)
    both = [r for r in ordered if r in fpos]
    if len(both) < 2:
        return {"qgaps": None, "fgaps": None, "qgapmax": None, "fgapmax": None,
                "dmax": None, "qspan": None, "fspan": None, "sameorder": None}
    qg = [qpos[b][0] - qpos[a][1] for a, b in zip(both, both[1:])]
    fg = [fpos[b][0] - fpos[a][1] for a, b in zip(both, both[1:])]
    return {"qgaps": qg, "fgaps": fg, "qgapmax": max(qg), "fgapmax": max(fg),
            "dmax": max(abs(x - y) for x, y in zip(qg, fg)),
            "qspan": qpos[both[-1]][1] - qpos[both[0]][0],
            "fspan": fpos[both[-1]][1] - fpos[both[0]][0],
            "sameorder": all(g >= 0 for g in fg)}


#: `display_stats` 认的两把尺子。**冻下来的标注属于它当时那一把**——
#: 拿今天的尺子去核 P44 冻的那 64 条，红的不是代码而是「尺子换过了」这件事本身。
RULERS = ("p44", "p46")


def display_stats(run: str, query: str, cut: list[str], ruler: str = "p46") -> dict:
    """这一串**摆不摆得到用户眼前**，摆出来长什么样（P44 / P46）。**纯函数，不碰库。**

    `cut` 是**冻下来的**「查询挤掉空白之后的分词结果」——所以这一层跟
    `position_stats` 一样离线就能重算：不问库、不问 codebook、不问冻结的 df。
    下一批要换一把尺子（比如「碎片补成整词」而不是丢掉），拿这个函数在
    `memory_sample.jsonl` 的 `p44-frag64` 那一组上重跑，**不用再读一遍 64 条**。
    **P46 就是这么用它的**（见 `tests/test_p46.py::test_P44那64条在新尺子下重跑`）。

    `ruler`：
      · `p44` —— 一律剥 `_EDGE_STOP`。`p44-frag64` 那一组冻的标注是按这一把出的。
      · `p46` —— 多认一条「它自己就是一个词的不剥」（`search.is_whole_token`）。默认这一把，
        因为默认该是**今天的代码在做什么**；要核对冻下来的资产就显式传 `p44`。

    回 `{"label", "aligned", "rule", "shown", "ruler"}`：
    `rule` 空串 = 摆得出来；`R1-跨词边界` / `R2-合不出两个字` = 被那一条砍了。
    """
    from app.database.kb import search

    if ruler not in RULERS:
        raise ValueError(f"没有这把尺子：{ruler!r}，只有 {RULERS}")
    squeezed = re.sub(r"\s+", "", (query or "").lower())
    joined = "".join(cut)
    if cut and joined != squeezed:
        raise ValueError(f"冻下来的分词拼不回查询：{joined[:40]!r} != {squeezed[:40]!r}")
    segment = (lambda _t: cut) if cut else None
    label = (search.evidence_label(run) if ruler == "p44"
             else search.evidence_label(run, squeezed, segment))
    aligned = search._aligned(label, squeezed, segment)
    if aligned is False:
        rule = "R1-跨词边界"
    elif not run.isascii() and len(label) < 2:
        rule = "R2-合不出两个字"
    else:
        rule = ""
    return {"label": label, "aligned": aligned, "rule": rule, "shown": not rule, "ruler": ruler}


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
