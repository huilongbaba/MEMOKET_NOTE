"""**那把量「英文 ≥3 那道门」的尺**（P77）。P75 ① 留的那笔账，这一份是来还它的。

    .venv/bin/python scripts/en_gate_ruler.py          # 反例两头 + 全库解剖，对不上 exit 9
    .venv/bin/python scripts/en_gate_ruler.py --cf     # 再加换量程的**全库 top-8 对拍**（慢）

---

## 量的是哪一行

`kb/search._strong_enough` 里的这一支：

    n = weigh(h) if weigh is not None else None
    if n is None:
        if len(h) >= 3:          # 英文 / 数字 / 定位不到：原样那把尺
            return True
        continue

`_weigher` 只管**纯汉字**的串（`_ALL_CJK`），别的一律回 `None`；纯汉字串在查询里
定位不到时 `content_chars` 也回 `None`。所以这道门管的是**三类**：
英文串、带数字的串、以及在查询里定位不到的汉字串。
**「被这道门挡掉」= `weigh(h) is None` 且 `len(h) < 3`** ——它没资格**单独**扛起这一条召回。

## P75 ① 说的那笔账，量下来是什么样

P75 判「泛闸不接」，三条理由里的第一条指着这道门：i=373/374 掉的那条真沾边的
「T0 按 EV 这个阶段往前排…5 月 15-18 号」，扛着它的是判泛的 `阶段`，
而「具体的 `ev` / `dvt`」被这道门挡在外面。

**逐条读下来，那句话对一半**（P77 ①）：

* `ev` **确实**被挡（2 个字母），`t0` 也被挡；
* `dvt` **没有**——三个字母正好够，这道门今天放它过。
  **引用前先核它还在不在**（P71 ③ 立的那条）：`dvt` 在被挡的那 14 种里一次都没出现。

## 它今天到底挡掉了什么（真库 terrence / 765 条那把尺）

**14 种 / 568 串次**，全部是 2 个字（这个仓库里没有更短的串：`_EN` 至少两个字母、
`_cjk_terms` 的窗口最短 2 字）。所以**「放宽到 2」跟「不设门」在这个库上逐格相同**
——那不是两档旋钮，是同一档。

| 串 | 串次 | 这一串翻过盘几次 |
|---|---:|---:|
| `ai` | 451 | 6 |
| `ui` | 34 | 0 |
| `os` | 21 | 0 |
| `pr` | 14 | 0 |
| `t0` | 12 | 0 |
| `mp` | 11 | 0 |
| `pc` | 6 | 0 |
| `8个` `5%` `ev` `go` `q3` `ib` `ce` | 4/3/3/3/2/2/2 | 2/3/0/0/0/0/0 |

**「挡掉了」不等于「因此少了一条召回」**：557 次调用里有被挡的串，
可真正**因为它才判 False** 的只有 **11 次 / 7 条查询**——其余每一次都有别的串扛着。
而那 11 次里扛旗的是 `ai`(6) / `5%`(3) / `8个`(2)，**一个真·产品术语都没有**；
`ev` / `t0` / `q3` / `ib` 被挡了 19 串次，**一次都没改变过判**。

## 换量程（全库 top-8 对拍，`--cf`）

| | 有召回 | 召回对 | top-8 变了 |
|---|---:|---:|---:|
| 今天（≥3） | 341/765 | 1347 | — |
| 放宽到 2（= 不设门） | 342/765 | 1353 | **2**（user 2，**两条都变差**） |
| 收紧到 4 | 317/765 | 1225 | **67** |

放宽那两条正是 `_strong_enough` 注释里记着的那个形状
（「24 条变动里一度混进 6 条全靠 `ui` / `os` 撞进来的，**教室方案的项目表召回一屏 UI 设计讨论**」）
——i=128 就是那条教室方案的查询。**P77 判：不动。**
"""

from __future__ import annotations

import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database.kb import search as kb_search  # noqa: E402

# 产品那一行里的那个数。**这里是抄件，不是源头**——`check_source()` 每次都回去核
# 源文件里那一行还在不在，对不上就 `exit 9`（「文件里有这个串」≠「这段代码还在跑」
# 的反面：这里要的恰恰是「那一行还在源文件里」这个前提）。
EN_STRONG_MIN = 3

# 真库 terrence / `recall_ruler` 那 765 条上钉死的量程（P77 ① 实测）。
EXPECT_BLOCKED_OCC = 568
EXPECT_BLOCKED_KINDS = 14
EXPECT_TOP_BLOCKED = ("ai", 451)
EXPECT_FLIP_AT_2 = 11          # 放宽到 2（= 不设门）会翻盘的调用数
EXPECT_FLIP_QUERIES_AT_2 = 7
EXPECT_FLIP_AT_4 = 213         # 收紧到 4 会翻盘的调用数
EXPECT_FLIP_QUERIES_AT_4 = 100
# `--cf` 那三行
EXPECT_CF = {2: (342, 1353, 2), 1: (342, 1353, 2), 4: (317, 1225, 67)}

# ── **quorum 有多脆**（P82 ②，量了没改）──────────────────────────────────────
#
# 这把尺记的是每一次 `_strong_enough` 的 `(cl, ns)`，所以「`len(cl) >= 2` 这个 quorum
# 到底撑着多少东西」**是它手上已经有的数**，白拿不要钱。P81 ④ 顺手读到 i=595/596
# 「几乎同一条查询判反」，只记了形状没量分量——这四个数是那个分量。
#
#   · `len(cl)` 分布：0 → 312743 · 1 → 61339 · **2 → 1499** · 3 → 179 · 4 → 40 · 5 → 27
#     · 6 → 11 · 7 → 15 · 8 → 8 · 9 → 2 · 10 → 1
#   · 判 True 的一共 1771 次，其中 **1488 次证人正好两条**——**少一条就翻 False**。
#     **84.0% 的「过了」全押在第二条证人身上。**
#   · `len(cl)==2` 也是**唯一**一档「够了 quorum 还会被后面那道 `≥3 字 / 实词` 判回去」的
#     （1499 里 False 11 次）；≥3 那几档一次都没有。
#
# ⚠️ **「一条查询多出一段就翻盘」不等于脆**（P82 ② 读出来的，照实记）：
# 765 里「一条是另一条前缀」的查询对有 79 对，两边 top-8 并集上判反 132/281 = 47.0%——
# 但那 36 对有翻盘的里**长的那条中位多出 78% 的正文**，那不叫「几乎同一条」。
# 收紧到「只多出 ≤25%」那一档，全库**只剩 4 次翻盘**（其中 3 次证人正好两条）。
# **真正的脆在上面那个 84.0%，不在这个 47%。**
EXPECT_QUORUM_CALLS = 375864     # `_strong_enough` 被问了多少次
EXPECT_QUORUM_TRUE = 1771        # 其中判 True 的
EXPECT_QUORUM_EDGE = 1488        # 判 True 且**证人正好两条**（少一条就翻）
EXPECT_QUORUM_REJECT_AT_2 = 11   # 够了 quorum 却被后面那道门判回去的（只有这一档有）
# `--quorum` 那一行：**用户眼前**那 1347 条召回对，各自靠几条证人撑着
EXPECT_QUORUM_SHOWN = (1347, 298, 778, 1049)   # (召回对, 短查询·这道门不问, 正好两条, 这道门管着的)

_CJK_ALL = re.compile(r"^[一-鿿]+$")


def decide(cl: list[str], ns: list, en_min: int) -> bool:
    """`_strong_enough` 的判，**逐行照抄**，只把那个 `3` 换成 `en_min`。

    `ns[i]` = `weigh(cl[i])`（`None` = 这一层判不了）。**顺序和 `break` 照原样**
    ——顺序换了就不是同一把尺（第一个够硬的就返回）。
    """
    if len(cl) < kb_search.LONG_QUERY_MIN_WORDS:
        return False
    for h, n in zip(cl, ns):
        if n is None:
            if len(h) >= en_min:
                return True
            continue
        if n >= kb_search.STRONG_CJK_MIN:
            return True
    return False


def blocked(cl: list[str], ns: list, en_min: int = EN_STRONG_MIN) -> list[str]:
    """这一次调用里，被这道门挡在外面的那些串。"""
    return [h for h, n in zip(cl, ns) if n is None and len(h) < en_min]


def kind(h: str) -> str:
    if h.isascii():
        return "英文" if h[:1].isalpha() else "数字/符号"
    return "汉字·定位不到" if _CJK_ALL.match(h) else "混合"


def check_source() -> list[str]:
    """**那一行还在不在源文件里**。不在就说明这把尺量的不是今天在跑的那道门。"""
    import inspect
    import textwrap
    src = textwrap.dedent(inspect.getsource(kb_search._strong_enough))
    bad = []
    if f"if len(h) >= {EN_STRONG_MIN}:" not in src:
        bad.append(f"`_strong_enough` 里找不到 `if len(h) >= {EN_STRONG_MIN}:`")
    if "n = weigh(h) if weigh is not None else None" not in src:
        bad.append("`_strong_enough` 里那一行 `weigh` 的接线变了")
    if kb_search.STRONG_CJK_MIN != 2 or kb_search.LONG_QUERY_MIN_WORDS != 2:
        bad.append("同一个函数里另外两个门槛变了，这把尺量出来的数跟着废")
    return bad


# ------------------------------------------------------------------ 反例两头
#
# **任何「核对」先喂它一个该红 / 该绿的反例**（样例 `scripts/check_shipped_source.py`、
# `scripts/topic_spread_ruler.py`）。这一组喂的是**假的 (cl, ns)**，不需要真语料：
#   · 该被挡的：两个 2 字母的英文串 → `EN_MIN=3` 判 False、`EN_MIN=2` 判 True（**它在动**）；
#   · 该放过的：`dvt` 三个字母 → 两档都 True（**P75 说它被挡，那句话是记错的**）；
#   · **对照**：纯汉字那一档（`ns` 有数）两档都 True——这道门**只管 `None` 那一档**，
#     换量程动不到它。这一格是「绿有个数」的那个绿。
BATTERY: tuple[tuple[str, list[str], list, int, bool], ...] = (
    ("两个 2 字母：≥3 挡住", ["ai", "ui"], [None, None], 3, False),
    ("两个 2 字母：≥2 放行", ["ai", "ui"], [None, None], 2, True),
    ("dvt 三个字母：≥3 **放行**", ["dvt", "ai"], [None, None], 3, True),
    ("dvt 三个字母：≥4 才挡得住", ["dvt", "ai"], [None, None], 4, False),
    ("对照·汉字实词：≥3 True", ["华为", "阿里"], [2, 2], 3, True),
    ("对照·汉字实词：≥2 也 True", ["华为", "阿里"], [2, 2], 2, True),
    ("对照·汉字实词：≥9 还是 True", ["华为", "阿里"], [2, 2], 9, True),
    ("只有一条证据串：门再松也 False", ["ai"], [None], 1, False),
    ("汉字碎片（实词 0 字）+ 2 字母：≥3 挡住", ["可以实", "ai"], [0, None], 3, False),
    ("汉字碎片 + 2 字母：≥2 就放行", ["可以实", "ai"], [0, None], 2, True),
)


def run_battery() -> list[str]:
    bad = []
    for name, cl, ns, en, want in BATTERY:
        got = decide(cl, ns, en)
        if got is not want:
            bad.append(f"{name}: {got} ≠ {want}")
    # 挡掉的那一列本身也喂一格：`dvt` 不许出现在被挡的名单里
    if blocked(["dvt", "ai", "t0"], [None, None, None], 3) != ["ai", "t0"]:
        bad.append("blocked() 的名单不对")
    return bad


# ------------------------------------------------------------------ 真库那一头

def measure(cf: bool = False) -> dict:
    """全库 765 条跑一趟（`EN_MIN=3`），把每一次 `_strong_enough` 的 (cl, ns) 记下来。

    **抄件先跟真货逐条相同才往下量**（同 P75 那条）：`EN_MIN=3` 时这份抄件
    必须跟没动过的 `_strong_enough` 在 765 条上给出一模一样的 top-8。
    """
    from app.database.kite.kite_memory import UserMemory
    from scripts import recall_ruler

    qs = recall_ruler.queries()
    bad = recall_ruler.check(qs)
    if bad:
        raise SystemExit("尺子对不上：" + "；".join(bad))

    mems: dict[str, UserMemory] = {}

    def mem(u):
        if u not in mems:
            mems[u] = UserMemory(u)
        return mems[u]

    def run(en_min, record):
        orig = kb_search._strong_enough
        calls: list[tuple] = []
        cur = {"i": -1, "o": ""}

        def patched(hits, query="", segment=None, common=None):
            cl = kb_search._clusters(hits)
            if len(cl) < kb_search.LONG_QUERY_MIN_WORDS:
                if record:
                    calls.append((cur["i"], cur["o"], cl, []))
                return False
            weigh = kb_search._weigher(query, segment, common)
            # **整列都算**（真货碰到第一个够硬的就 `break`）：只影响算多少下，不影响判
            ns = [(weigh(h) if weigh is not None else None) for h in cl]
            if record:
                calls.append((cur["i"], cur["o"], cl, ns))
            return decide(cl, ns, en_min)

        kb_search._strong_enough = patched if en_min is not None else orig
        try:
            out = []
            for i, (user, q, _m, origin) in enumerate(qs):
                cur.update(i=i, o=origin)
                rows, _s, _ms = mem(user).recall(q, limit=8, evidence=True)
                out.append([r.get("id") for r in rows])
        finally:
            kb_search._strong_enough = orig
        return out, calls

    truth, _ = run(None, False)
    copy3, calls = run(3, True)
    if truth != copy3:
        raise SystemExit("抄件在 EN_MIN=3 下跟真货对不上——往下量的每个数都无效")

    occ, by_kind, by_lineage = Counter(), Counter(), defaultdict(Counter)
    flip = {2: set(), 1: set(), 4: set()}
    flip_calls = Counter()
    resp = defaultdict(Counter)
    ncalls = len(calls)
    nshort = sum(1 for _i, _o, _cl, ns in calls if not ns)
    for i, origin, cl, ns in calls:
        if not ns:
            continue
        for h in blocked(cl, ns):
            occ[h] += 1
            by_kind[kind(h)] += 1
            by_lineage[origin][h] += 1
        v3 = decide(cl, ns, 3)
        for m in (2, 1, 4):
            if decide(cl, ns, m) != v3:
                flip[m].add(i)
                flip_calls[m] += 1
                for h, n in zip(cl, ns):
                    if n is None and (m <= len(h) < 3 if m < 3 else len(h) == 3):
                        resp[m][h] += 1
                        break

    # quorum 那一格（P82 ②）：这把尺手上已经有 (cl, ns)，白拿
    band = Counter(len(cl) for _i, _o, cl, _ns in calls)
    qtrue = sum(1 for _i, _o, cl, ns in calls if ns and decide(cl, ns, EN_STRONG_MIN))
    qedge = sum(1 for _i, _o, cl, ns in calls
                if ns and len(cl) == 2 and decide(cl, ns, EN_STRONG_MIN))
    qrej = sum(1 for _i, _o, cl, ns in calls
               if ns and len(cl) == 2 and not decide(cl, ns, EN_STRONG_MIN))
    out = {"calls": ncalls, "short": nshort, "occ": occ, "kind": by_kind,
           "lineage": by_lineage, "flip": {k: len(v) for k, v in flip.items()},
           "flip_calls": dict(flip_calls), "resp": {k: v.most_common(8) for k, v in resp.items()},
           "hit": sum(1 for ids in truth if ids), "pairs": sum(len(ids) for ids in truth),
           "band": dict(sorted(band.items())), "qtrue": qtrue, "qedge": qedge, "qrej": qrej}
    if cf:
        out["cf"] = {}
        for en in (2, 1, 4):
            r, _ = run(en, False)
            out["cf"][en] = (sum(1 for ids in r if ids), sum(len(ids) for ids in r),
                             sum(1 for a, b in zip(truth, r) if a != b))
    return out


def quorum_shown() -> tuple[int, int, int, int]:
    """**用户眼前**那 1347 条召回对，各自靠几条证人撑着（P82 ②，`--quorum`）。

    上面 `measure()` 数的是**调用**——候选池里绝大多数是 `len(cl)==0` 的路人。
    这一支只看**真摆到屏幕上的那几条**：`(召回对, 短查询这道门不问的, 正好两条的, 这道门管着的)`。
    判据逐行照 `rank` 里那一处算（`_terms` → `_hits` → `_clusters`），**不另起一把尺**。
    """
    from app.database.kite.kite_memory import UserMemory
    from scripts import recall_ruler

    qs = recall_ruler.queries()
    mems: dict[str, UserMemory] = {}
    stores: dict[str, object] = {}
    shown = short = edge = managed = 0
    for user, q, _m, _o in qs:
        m = mems.get(user) or mems.setdefault(user, UserMemory(user))
        facts, _t, _ms = m.recall(q, limit=8, evidence=True)
        if not facts:
            continue
        if user not in stores:
            stores[user], _v = m._index()
        st = stores[user]
        cq = kb_search.clean_query(q)
        is_long = len(cq.strip()) >= kb_search.LONG_QUERY
        weigh = kb_search._weigher(cq, m.segment(), m.common_term())
        terms = kb_search._terms(m, cq, weigh)
        for r in facts:
            shown += 1
            if not is_long:
                short += 1
                continue
            managed += 1
            f = st.facts.get(r.get("id"))
            cl = kb_search._clusters(kb_search._hits(terms, (f.text if f else "") or ""))
            if len(cl) == 2:
                edge += 1
    return (shown, short, edge, managed)


def corpus_tag(user: str = "terrence") -> str:
    import hashlib
    root = Path(os.environ.get("KITE_DATA_DIR") or (BACKEND / "data"))
    cb = root / user / "codebook.xml"
    if not cb.is_file():
        return "no-codebook"
    return f"{cb.stat().st_size}B/{hashlib.sha256(cb.read_bytes()).hexdigest()[:8]}"


def main(argv: list[str]) -> int:
    bad = check_source() + run_battery()
    if bad:
        print("反例 / 源文件那一头对不上：" + "；".join(bad), file=sys.stderr)
        return 9
    print(f"ruler=en-gate en_min={EN_STRONG_MIN} corpus={corpus_tag()}：反例 "
          f"{len(BATTERY)} 格全对上（有红有绿，对照那三格换量程也不动）")
    if "--battery-only" in argv:
        return 0

    m = measure(cf="--cf" in argv)
    print(f"  `_strong_enough` 被问 {m['calls']} 次（其中 {m['short']} 次串数 <2 直接 False）；"
          f"有召回 {m['hit']}/765 · 召回对 {m['pairs']}")
    print(f"  **被这道门挡掉**：{sum(m['occ'].values())} 串次 / {len(m['occ'])} 种"
          f"  按类型 {dict(m['kind'])}")
    print(f"  按血缘（串次）：{ {k: sum(v.values()) for k, v in m['lineage'].items()} }")
    for h, n in m["occ"].most_common():
        lin = " ".join(f"{k}{m['lineage'][k][h]}" for k in ("user", "script", "fixture")
                       if m["lineage"][k][h])
        print(f"    {h!r:8} {kind(h):10} 串次 {n:5}  [{lin}]")
    print(f"  放宽到 2 会翻盘的调用 {m['flip_calls'].get(2, 0)} 次 / "
          f"{m['flip'][2]} 条查询，扛旗的 {m['resp'][2]}")
    print(f"  不设门（1）会翻盘的调用 {m['flip_calls'].get(1, 0)} 次 / {m['flip'][1]} 条查询"
          "  ——**跟放宽到 2 逐格相同**（这个库里没有 1 个字的串）")
    print(f"  收紧到 4 会翻盘的调用 {m['flip_calls'].get(4, 0)} 次 / {m['flip'][4]} 条查询，"
          f"掉掉的 {m['resp'][4]}")
    if "cf" in m:
        for en in (2, 1, 4):
            h, p, c = m["cf"][en]
            print(f"  换量程 EN_MIN={en}：有召回 {h}/765 · 召回对 {p} · top-8 变了 {c}")
    # quorum 那一格（P82 ②）
    print(f"  **quorum（`len(cl) >= {kb_search.LONG_QUERY_MIN_WORDS}`）有多脆**："
          f"证人条数分布 {m['band']}")
    print(f"    判 True {m['qtrue']} 次，其中**证人正好两条** {m['qedge']} 次 = "
          f"{m['qedge'] / max(1, m['qtrue']):.1%}——**少一条就翻 False**")
    print(f"    「够了 quorum 又被后面那道门判回去」只在这一档有：{m['qrej']} / "
          f"{m['band'].get(2, 0)}（≥3 那几档 0 次）")
    shown = None
    if "--quorum" in argv:
        shown = quorum_shown()
        print(f"    **用户眼前**那 {shown[0]} 条召回对：这道门管着 {shown[3]} 条"
              f"（另 {shown[1]} 条是短查询，这道门不问），其中**正好两条证人撑着的 {shown[2]}** = "
              f"{shown[2] / max(1, shown[3]):.1%}")

    bad = []
    for name, got, want in (("quorum 调用数", m["calls"], EXPECT_QUORUM_CALLS),
                            ("quorum True", m["qtrue"], EXPECT_QUORUM_TRUE),
                            ("quorum 正好两条", m["qedge"], EXPECT_QUORUM_EDGE),
                            ("quorum 两条又被判回去", m["qrej"], EXPECT_QUORUM_REJECT_AT_2)):
        if got != want:
            bad.append(f"{name} {got} ≠ {want}")
    if shown is not None and shown != EXPECT_QUORUM_SHOWN:
        bad.append(f"用户眼前那一档 {shown} ≠ {EXPECT_QUORUM_SHOWN}")
    if sum(m["occ"].values()) != EXPECT_BLOCKED_OCC:
        bad.append(f"挡掉串次 {sum(m['occ'].values())} ≠ {EXPECT_BLOCKED_OCC}")
    if len(m["occ"]) != EXPECT_BLOCKED_KINDS:
        bad.append(f"挡掉种数 {len(m['occ'])} ≠ {EXPECT_BLOCKED_KINDS}")
    if m["occ"].most_common(1)[0] != EXPECT_TOP_BLOCKED:
        bad.append(f"挡得最多的那一个 {m['occ'].most_common(1)[0]} ≠ {EXPECT_TOP_BLOCKED}")
    if "dvt" in m["occ"]:
        bad.append("`dvt` 出现在被挡的名单里——那跟这把尺的结论相反")
    if m["flip_calls"].get(2, 0) != EXPECT_FLIP_AT_2 or m["flip"][2] != EXPECT_FLIP_QUERIES_AT_2:
        bad.append(f"放宽到 2 翻盘 {m['flip_calls'].get(2, 0)}/{m['flip'][2]} ≠ "
                   f"{EXPECT_FLIP_AT_2}/{EXPECT_FLIP_QUERIES_AT_2}")
    if (m["flip_calls"].get(1, 0), m["flip"][1]) != (m["flip_calls"].get(2, 0), m["flip"][2]):
        bad.append("「不设门」跟「放宽到 2」不再逐格相同——这个库里出现了 1 个字的串")
    if m["flip_calls"].get(4, 0) != EXPECT_FLIP_AT_4 or m["flip"][4] != EXPECT_FLIP_QUERIES_AT_4:
        bad.append(f"收紧到 4 翻盘 {m['flip_calls'].get(4, 0)}/{m['flip'][4]} ≠ "
                   f"{EXPECT_FLIP_AT_4}/{EXPECT_FLIP_QUERIES_AT_4}")
    if "cf" in m:
        for en, want in EXPECT_CF.items():
            if tuple(m["cf"][en]) != want:
                bad.append(f"EN_MIN={en} 对拍 {tuple(m['cf'][en])} ≠ {want}")
    if bad:
        print("真库那一头对不上：" + "；".join(bad), file=sys.stderr)
        print("**这一刻 P77 ① 那几个数全部失效**——先查口径 / 语料，别换尺子继续量。",
              file=sys.stderr)
        return 9
    print("en-gate ruler OK（P77 ① 逐格相同）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
