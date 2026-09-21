"""**那把量「同一个东西被抽成了两个码」的尺**（P102，第 821 轮）。

    .venv/bin/python scripts/code_pair_ruler.py             # 打出身 + 核对，对不上 exit 9
    .venv/bin/python scripts/code_pair_ruler.py --list      # 顺带把候选对逐条打出来
    .venv/bin/python scripts/code_pair_ruler.py --impact    # ⚠️ 贵：765 屏上五支反事实各跑一趟

---

## ① 它量的是什么，以及**它不是 `same_thing`**

P100 ④ 拍到一个形状：H05 那一屏四条都在说「用 hello@memocat.ai 当对外联系邮箱」，
漏掉的两条**被抽成了另一个码、而且两条轴同时**
（`e_mail` ↔ `e_mail_address`、`work` ↔ `work_marketing`）。

这把尺问的是 **「一对码 `(A, B)` 是不是同一个东西的两种写法」**——
**判的是码，不是事实**。「这两条事实说的是不是同一件事」是
`kb/fact_distinct.same_thing` 的问题，**是另一个问题**
（`p98-topicroad-3` 的 `_meta` 第一条已经点过这一格，这儿再钉一遍）。

两张码表：

* **`obj` 码表** = 全库 `<fact obj="…">` 按空格切出来的不同串
  （抽取那一头的口径逐字在 `memoket_kite/core/algebra.py`：`(fe.get("obj") or "").split()`）；
* **`topics` 码表** = `<vocab><topic code="…">`。
  实测 `topics=` 属性里的码**是 vocab 的子集**（六个库逐个核过，`attr - vocab` 全是 0），
  所以拿 vocab 当码表是对的。

## ② 两条口径，**都没有门槛可调**（这一条是这把尺存在的理由）

| 口径 | 怎么判 | 干什么用 |
|---|---|---|
| **R2 字面包含** | `lower()` + 去掉非字母数字非汉字之后，一个码的字面是另一个的**真子串** | **估计口径** |
| **R1 共享词元** | 按非字母数字切；ASCII 段就是它自己，含汉字的段取**全部 2-gram**（单字太吵：`广告`/`报告` 共享 `告`） | **漏检探针**（严格更宽） |

**为什么不是共现、也不是分布**（两条都在台账里判过）：

* **共现**：P98 ② 量过判死，**而且方向是反的**——
  `ai_memory_os`（df 36）和 `memory_powered_intelligence`（df 45）
  在同一条事实上只共现 2 次、Jaccard 0.025、613 对里排 201。
  **同义码正因为是同义，抽取时二选一，所以反而不共现。**
* **`obj` 分布 cos**：P98 ③ 走到第三格还活着，**但它停在「cut 0.77 是拿目标那一对反推的」**
  （那一对自己是 0.7777，cut 取 0.778 就够不着）。

**字面包含没有 cut 可调**，所以它出来的数**不可能是反推出来的**。
⚠️ 代价写在第 ④ 格：**它的召回从一开始就不许声称**。

## ③ 读数（`p102-codepairs-330`，330 对**盲标**，`RULE.md` 在读第一对之前写的）

| 库 · 轴 | 码 | R2 对 | 读法 | `S` 同义 | `H` 上下位 | `N` 无关 | `S` 率 | `S+H` 率 |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| `terrence` · `topics` | 129 | 140 | **普查**（点名那 1 对摘出） | 22 | 114 | 3 | **15.8%** | **97.8%** |
| `terrence` · `obj` | 3299 | 4017 | 随机 60 | 4 | 22 | 34 | **6.7%** | 43.3% |
| `terrence-rewrite` · `topics` | 200 | 24 | **普查** | 2 | 20 | 2 | 8.3% | 91.7% |
| `terrence-rewrite` · `obj` | 1237 | 1002 | 随机 40 | 8 | 17 | 15 | **20.0%** | 62.5% |
| `shot-demo` · `obj` | 30 | 5 | **普查** | 2 | 2 | 1 | 40.0% | 80.0% |
| `fresh678c` · `topics` | 9 | 1 | **普查** | 0 | 1 | 0 | 0% | 100% |
| 合计 | | | 269 行 | **38** | 176 | 55 | **14.1%** | 79.6% |

`S` = 互换之后没有信息损失；`H` = 真子类 / 真部分；`N` = 字面撞上、所指不同。
**`S` 和 `H` 分开打**，因为**补救不是一回事**：`S` 该合，`H` 该在用的时候沿层级走一步、
**不该合**（合了丢子类）。

⚠️ **`S`/`H` 那条界的细则是看见 330 行之后才落下来的**（`RULE.md` 追加 ①，并排记着）。
它只挪 `S`/`H` 的界，不挪 `S+H` 跟 `N` 的界 ⇒ **`S+H` 那个数比 `S` 硬**。

## ④ **它答不了什么**（照 P72 的规矩写在尺自己身上）

* **召回，一格都答不了。** R2 够不着字面不沾的那一类：
  `ai_memory_os` ↔ `memory_powered_intelligence`（P98 ③ 点名那一对）
  在 `terrence-rewrite` 上落在 **R1\\R2**，R2 一次都捞不到它。
* **漏检探针 60 行读完一对 `S` 都没有**（`terrence` 两条轴各 30），
  但 **0/30 的 95% 上界还有 ~9.5%** ——折到 `terrence·topics` 那 1813 对 R1\\R2 上
  **最多还有约 170 对没被看见**。**「没读到」不是「没有」。**
* **`obj` 那两档是抽样**（60 / 40），置信区间很宽；`topics` 两档是**普查**，没有抽样误差。
* **它不判 `obj` 是不是抽歪了**（那是 P96 ③ 那笔账，判过「不补」）。

## ⑤ 层级是**库里本来就记着**的（这一批量出来的第二件事）

`<topic parents="…">` 在 `terrence` 上 129 个码里 **123 个有父**、
`terrence-rewrite` 200 个码里 **194 个有父**——**但那棵树只有两层**
（6 个根 `work`/`project`/`personal`/`learning`/`health`/`finance`，
`terrence` 深度分布 6 / 113 / 10）。
所以 `work_product` 和 `work_product_design` **在库里是兄弟，不是父子**。
R2 捞到的 140 对里 **84 对就是库里已记的边、56 对库里没记**。

⇒ **「上下位那一半要不要在用的时候走一步」不需要新数据**，
而它值不值得走，第 ⑥ 格量了。

## ⑥ 合了之后 765 屏上发生什么（`--impact`，`p102-merge-read-18` 逐条读过）

| 支 | 判「是」 | 新增 | 掉 | **新增里真的** |
|---|---:|---:|---:|---|
| HEAD（`M`） | 17 | — | — | — |
| **`S`（只合人读过判同义的那些）** | **17** | **0** | **0** | — |
| `R2`（`topics` 换字面包含） | 20 | 3 | 0 | **0/3** |
| `R2X`（两条轴都换） | 21 | 4 | 0 | **0/4** |
| `SH`（同义 + 上下位一起合） | 29 | 12 | 0 | **0/12** |
| `PAR`（沿库里的 `parents` 走满） | 31 | 14 | 0 | **1/14**（i=590） |

**五支加起来 18 屏，只有 1 屏真的**（i=590，正是 P98 ③ 追的那一族）。
**五支一屏都没掉。**

⚠️ **`S` 那个 0 要分得开两种**：**不是合表没开口**——765 屏召回到的事实 **2463 对**里
`S` 让 **4 对**从「不是」翻成「是」、**2 屏的团从 1 涨到 2**（i=694 / i=696），
但 `FAMILY_MIN = 3`，**够不着门**。
⇒ 准确说法是「**开了口、顶不过门**」，不是「一点用都没有」。

⚠️ **别把这五支反事实里的伤亡记成 HEAD 缺陷**（P96 ④ 那一课）。

## ⑦ 出身

每次都打一行：两张码表各多大 + 两条口径各捞到多少 + 人读那三档 + 语料指纹。
照 `recall_selfcheck` 那条规矩——「同样的参数在不同语料上是不同的数」，
所以**整行抄进台账，出身跟着走**。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import xml.etree.ElementTree as ET  # noqa: E402

FIXTURE = BACKEND / "tests" / "fixtures" / "memory_sample.jsonl"
SET_PAIRS = "p102-codepairs-330"
SET_READ = "p102-merge-read-18"

# 只有这六个库的 codebook 非空（`recall_ruler` 自报 `users 6` 的那六个）。
# **顺序钉死**，读数按这个顺序摆。
LIBS: tuple[str, ...] = ("fresh678", "fresh678b", "fresh678c", "shot-demo",
                         "terrence", "terrence-rewrite")

# ── 钉死的量程 ────────────────────────────────────────────────────────────
# **这几个数是这把尺自己的身份**：对不上说明码表或语料变了，
# 那一刻这一批所有读数全部失效 —— 所以宁可 `exit 9`。

# 两张码表各多大：`{库: (事实数, obj 码, topics 码)}`
EXPECT_TABLES = {
    "fresh678": (17, 11, 10), "fresh678b": (15, 10, 9), "fresh678c": (14, 9, 9),
    "shot-demo": (45, 30, 17), "terrence": (20417, 3299, 129),
    "terrence-rewrite": (2922, 1237, 200),
}

# 两条口径各捞到多少对：`{(库, 轴): (R1\R2, R2)}`。**候选对为 0 的不列。**
EXPECT_PAIRS = {
    ("fresh678c", "topics"): (1, 1),
    ("shot-demo", "obj"): (1, 5), ("shot-demo", "topics"): (5, 0),
    ("terrence", "obj"): (3687, 4017), ("terrence", "topics"): (1813, 140),
    ("terrence-rewrite", "obj"): (1502, 1002), ("terrence-rewrite", "topics"): (603, 24),
}

# 人读 330 对的读数，按 (轴, 口径) 分：`(n, S, H, N, ?)`。
# ⚠️ **台账点名那一对（`work` ↔ `work_marketing`）摘出分母**，所以 269 + 60 + 1 = 330。
EXPECT_READ = {
    ("obj", "R2"): (105, 14, 41, 50, 0),
    ("topics", "R2"): (164, 24, 135, 5, 0),
    ("obj", "R1only"): (30, 0, 2, 28, 0),
    ("topics", "R1only"): (30, 0, 1, 29, 0),
}
# 摘出分母的那几对：台账点过名、标注的人认得出来的。
EXPECT_NAMED = 1

# 层级库里本来记着多少：`{库: (有父的码, 库内父子边, 这些边里 R2 也捞到的)}`
EXPECT_PARENTS = {"terrence": (123, 123, 84), "terrence-rewrite": (194, 194, 13),
                  "shot-demo": (11, 11, 0)}

# 765 屏上五支反事实：`{支: (判是, 新增, 掉)}`。**只有 `--impact` 才核。**
EXPECT_IMPACT = {"HEAD": (17, 0, 0), "S": (17, 0, 0), "R2": (20, 3, 0),
                 "R2X": (21, 4, 0), "SH": (29, 12, 0), "PAR": (31, 14, 0)}
# `S` 那一支开口开了几次：(量过的事实对, 翻成「是」的对, 团变大的屏)。
# **这三个数是「开了口、顶不过门」那句话本身**，一动那句话就得重读。
EXPECT_FIRE = (2463, 4, 2)
# 五支新增的并集逐条读完：(屏数, 真, 假)
EXPECT_MERGE_READ = (18, 1, 17)

_SPLIT = re.compile(r"[^0-9A-Za-z一-鿿]+")
_FLAT = re.compile(r"[^0-9a-z一-鿿]+")


def _is_cjk(s: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in s)


def tokens(code: str) -> set[str]:
    """R1 的切分。含汉字的一段取**全部 2-gram**，不取单字。"""
    out: set[str] = set()
    for part in _SPLIT.split(code.lower()):
        if not part:
            continue
        if _is_cjk(part) and len(part) > 1:
            out.update(part[i:i + 2] for i in range(len(part) - 1))
        else:
            out.add(part)
    return out


def flat(code: str) -> str:
    """R2 的规范化。"""
    return _FLAT.sub("", code.lower())


def data_dir() -> Path:
    return Path(os.environ.get("KITE_DATA_DIR") or (BACKEND / "data"))


def tables(lib: str) -> dict[str, list[str]]:
    """一个库的两张码表 + 事实数。"""
    root = ET.parse(data_dir() / lib / "codebook.xml").getroot()
    facts = root.findall(".//fact")
    obj: set[str] = set()
    attr: set[str] = set()
    for f in facts:
        obj.update((f.get("obj") or "").split())
        attr.update((f.get("topics") or "").split())
    voc = {t.get("code") for t in root.findall(".//vocab/topic") if t.get("code")}
    # **`topics=` 属性里的码必须是 vocab 的子集**，否则「拿 vocab 当码表」这句话就不成立
    if attr - voc:
        raise AssertionError(
            f"{lib}: `topics=` 里有 {len(attr - voc)} 个码不在 vocab 里 —— "
            "这把尺拿 vocab 当 `topics` 码表，这一条不成立它的读数全废")
    return {"facts": facts, "obj": sorted(obj), "topics": sorted(voc)}


def candidates(codes: list[str]) -> tuple[set, set]:
    """回 `(R1\\R2, R2)`。**两条口径互斥着回**，省得下游再减一次。"""
    tk = {c: tokens(c) for c in codes}
    fl = {c: flat(c) for c in codes}
    r1o: set[tuple[str, str]] = set()
    r2: set[tuple[str, str]] = set()
    for a, b in combinations(codes, 2):
        fa, fb = fl[a], fl[b]
        if fa != fb and (fa in fb or fb in fa):
            r2.add((a, b))
        elif tk[a] & tk[b]:
            r1o.add((a, b))
    return r1o, r2


def parents(lib: str) -> dict[str, list[str]]:
    root = ET.parse(data_dir() / lib / "codebook.xml").getroot()
    return {t.get("code"): [p for p in (t.get("parents") or "").split() if p]
            for t in root.findall(".//vocab/topic") if t.get("code")}


def annotations(which: str) -> list[dict]:
    out = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("set") == which and "_meta" not in row:
            out.append(row)
    return out


def identity() -> str:
    parts = []
    for lib in LIBS:
        p = data_dir() / lib / "codebook.xml"
        raw = p.read_bytes()
        parts.append(f"{lib}={len(raw)}B/{hashlib.sha256(raw).hexdigest()[:8]}")
    return "ruler=codepair libs=%d corpus[%s]" % (len(LIBS), " ".join(parts))


def measure() -> dict:
    tbl: dict[str, tuple[int, int, int]] = {}
    pairs: dict[tuple[str, str], tuple[int, int]] = {}
    for lib in LIBS:
        t = tables(lib)
        tbl[lib] = (len(t["facts"]), len(t["obj"]), len(t["topics"]))
        for axis in ("obj", "topics"):
            r1o, r2 = candidates(t[axis])
            if r1o or r2:
                pairs[(lib, axis)] = (len(r1o), len(r2))
    par: dict[str, tuple[int, int, int]] = {}
    for lib, _want in EXPECT_PARENTS.items():
        pmap = parents(lib)
        codes = set(pmap)
        edges = {(min(p, c), max(p, c)) for c, ps in pmap.items() for p in ps if p in codes}
        _r1o, r2 = candidates(sorted(codes))
        par[lib] = (sum(1 for v in pmap.values() if v), len(edges), len(r2 & edges))
    read: dict[tuple[str, str], tuple[int, ...]] = {}
    named = 0
    for row in annotations(SET_PAIRS):
        if row.get("named_in_ledger"):
            named += 1
            continue
        k = (row["axis"], row["mode"])
        c = Counter(dict(zip(("n", "S", "H", "N", "?"), read.get(k, (0, 0, 0, 0, 0)))))
        c["n"] += 1
        c[row["label"]] += 1
        read[k] = (c["n"], c["S"], c["H"], c["N"], c["?"])
    rd = Counter(r["verdict"] for r in annotations(SET_READ))
    return {"tables": tbl, "pairs": pairs, "parents": par, "read": read, "named": named,
            "merge_read": (sum(rd.values()), rd["真"], rd["假"])}


def _cmp(bad: list[str], name: str, got, want) -> None:
    if got != want:
        bad.append(f"{name}: 实得 {got!r}，钉死的是 {want!r}")


def check(g: dict) -> list[str]:
    bad: list[str] = []
    _cmp(bad, "两张码表", g["tables"], EXPECT_TABLES)
    _cmp(bad, "候选对", g["pairs"], EXPECT_PAIRS)
    _cmp(bad, "人读读数", g["read"], EXPECT_READ)
    _cmp(bad, "摘出分母的点名对", g["named"], EXPECT_NAMED)
    _cmp(bad, "库里记着的层级", g["parents"], EXPECT_PARENTS)
    _cmp(bad, "变了的屏逐条读", g["merge_read"], EXPECT_MERGE_READ)
    # 自检：人读那四档加起来 + 摘出的 = 330
    total = sum(v[0] for v in g["read"].values()) + g["named"]
    if total != 330:
        bad.append(f"人读合计 {total} ≠ 330 —— 标注表被动过了")
    # 自检：每一档 S+H+N+? == n
    for k, v in g["read"].items():
        if sum(v[1:]) != v[0]:
            bad.append(f"{k} 四档加起来 {sum(v[1:])} ≠ {v[0]}")
    return bad


def impact() -> dict:
    """⚠️ **贵**：765 屏 × 六支。只有 `--impact` 才跑。"""
    from app.database.kb import fact_distinct as FD
    from app.database.kite.kite_memory import UserMemory
    import recall_ruler as RR

    pmaps = {lib: parents(lib) for lib in LIBS}
    merge: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in annotations(SET_PAIRS):
        for tag in ("S", "SH"):
            if row["label"] == "S" or (tag == "SH" and row["label"] == "H"):
                merge.setdefault((tag, row["lib"], row["axis"]), {})
                merge[(tag, row["lib"], row["axis"])].setdefault("_pairs", [])
                merge[(tag, row["lib"], row["axis"])]["_pairs"].append((row["a"], row["b"]))
    uf: dict[tuple[str, str, str], dict[str, str]] = {}
    for k, v in merge.items():
        par: dict[str, str] = {}

        def find(x: str) -> str:
            par.setdefault(x, x)
            while par[x] != x:
                par[x] = par[par[x]]
                x = par[x]
            return x
        for a, b in v["_pairs"]:
            ra, rb = find(a), find(b)
            if ra != rb:
                par[ra] = rb
        uf[k] = {x: find(x) for x in par}

    cur = {"user": "", "tag": "HEAD"}
    orig = FD.same_thing

    def closure(codes):
        pm = pmaps.get(cur["user"], {})
        out, stack = set(codes), list(codes)
        while stack:
            c = stack.pop()
            for p in pm.get(c, ()):
                if p not in out:
                    out.add(p)
                    stack.append(p)
        return out

    def hit(xs, ys):
        fx = [flat(x) for x in xs if flat(x)]
        fy = [flat(y) for y in ys if flat(y)]
        return any(a == b or a in b or b in a for a in fx for b in fy)

    def canon(axis, codes):
        m = uf.get((cur["tag"], cur["user"], axis), {})
        return {m.get(c, c) for c in codes}

    def swapped(a, b):
        if a.unit == b.unit:
            return False
        t = cur["tag"]
        if t == "PAR":
            return bool(closure(a.topics) & closure(b.topics)) and bool(set(a.obj) & set(b.obj))
        if t == "R2":
            return hit(a.topics, b.topics) and bool(set(a.obj) & set(b.obj))
        if t == "R2X":
            return hit(a.topics, b.topics) and hit(a.obj, b.obj)
        return (bool(canon("obj", a.obj) & canon("obj", b.obj))
                and bool(canon("topics", a.topics) & canon("topics", b.topics)))

    qs = RR.queries()

    def run(tag):
        cur["tag"] = tag
        FD.same_thing = orig if tag == "HEAD" else swapped
        mems: dict = {}
        for k in list(UserMemory._cache):
            if k.endswith("#whoface") or k.endswith("#topicface"):
                UserMemory._cache.pop(k, None)
        out = []
        for user, q, _m, _o in qs:
            cur["user"] = user
            m = mems.get(user) or mems.setdefault(user, UserMemory(user))
            facts, _t, _ms = m.recall(q, limit=8, evidence=True)
            store, _v = m._index()
            recs = [store.facts[f["id"]] for f in facts if f.get("id") in store.facts]
            out.append((user, recs, FD.screen_shape(recs)))
        FD.same_thing = orig
        return out

    res = {t: run(t) for t in ("HEAD", "S", "R2", "R2X", "SH", "PAR")}
    den = [i for i, (_u, _r, s) in enumerate(res["HEAD"]) if s["measurable"] >= 3]
    base = {i for i in den if res["HEAD"][i][2]["flagged"]}
    out = {}
    union: set[int] = set()
    for t in EXPECT_IMPACT:
        f = {i for i in den if res[t][i][2]["flagged"]}
        out[t] = (len(f), len(f - base), len(base - f))
        union |= (f - base)
    # `S` 开了几次口
    cur["tag"] = "S"
    seen = flips = grow = 0
    for i, (user, recs, _s) in enumerate(res["HEAD"]):
        cur["user"] = user
        idx = [j for j, f in enumerate(recs) if FD.measurable(f)]
        for a, b in combinations(idx, 2):
            seen += 1
            if swapped(recs[a], recs[b]) and not orig(recs[a], recs[b]):
                flips += 1
        if len(idx) >= 3:
            f0 = len(FD.largest_family(recs))
            FD.same_thing = swapped
            f1 = len(FD.largest_family(recs))
            FD.same_thing = orig
            if f1 != f0:
                grow += 1
    return {"impact": out, "fire": (seen, flips, grow), "union": tuple(sorted(union))}


def main(argv: list[str]) -> int:
    g = measure()
    print(identity())
    print("两张码表（%d 个库）：" % len(LIBS))
    for lib in LIBS:
        n, o, t = g["tables"][lib]
        print("  %-18s 事实 %6d · obj 码 %5d · topics 码 %4d" % (lib, n, o, t))
    print("候选对（R2 字面包含 / R1\\R2 共享词元，**都没有门槛可调**）：")
    for (lib, axis), (r1o, r2) in sorted(g["pairs"].items()):
        print("  %-18s %-7s R2 %5d · R1\\R2 %5d" % (lib, axis, r2, r1o))
    print("人读 330 对（`%s`，点名摘出 %d 对）：" % (SET_PAIRS, g["named"]))
    for k in sorted(g["read"]):
        n, s, h, nn, q = g["read"][k]
        print("  %-7s %-7s n=%3d · S %2d (%4.1f%%) · H %3d · N %2d · ? %d · S+H %5.1f%%"
              % (k[0], k[1], n, s, 100 * s / n, h, nn, q, 100 * (s + h) / n))
    print("库里本来记着的层级（`<topic parents=>`）：")
    for lib in sorted(g["parents"]):
        wp, e, r2 = g["parents"][lib]
        print("  %-18s 有父的码 %3d · 库内父子边 %3d · 其中 R2 也捞到 %3d" % (lib, wp, e, r2))
    n, t, f = g["merge_read"]
    print("合了之后变了的屏逐条读（`%s`）：%d 屏 · 真 %d · 假 %d" % (SET_READ, n, t, f))

    bad = check(g)

    if "--list" in argv:
        for lib in LIBS:
            tb = tables(lib)
            for axis in ("obj", "topics"):
                r1o, r2 = candidates(tb[axis])
                for a, b in sorted(r2):
                    print("  R2     %-18s %-7s %s ↔ %s" % (lib, axis, a, b))
                for a, b in sorted(r1o):
                    print("  R1\\R2  %-18s %-7s %s ↔ %s" % (lib, axis, a, b))

    if "--impact" in argv:
        im = impact()
        print("765 屏上五支反事实（HEAD 判是 %d 屏）：" % im["impact"]["HEAD"][0])
        for t in ("S", "R2", "R2X", "SH", "PAR"):
            n, on, off = im["impact"][t]
            print("  %-5s 判是 %3d · 新增 %2d · 掉 %d" % (t, n, on, off))
        print("  `S` 开口：事实对 %d · 翻成「是」%d · 团变大的屏 %d" % im["fire"])
        print("  五支新增的并集 %d 屏：%s" % (len(im["union"]), list(im["union"])))
        _cmp(bad, "五支反事实", im["impact"], EXPECT_IMPACT)
        _cmp(bad, "`S` 开口", im["fire"], EXPECT_FIRE)
        if len(im["union"]) != EXPECT_MERGE_READ[0]:
            bad.append(f"并集 {len(im['union'])} 屏 ≠ 逐条读的 {EXPECT_MERGE_READ[0]} 屏")

    if bad:
        for b in bad:
            print("✗ " + b)
        print("⚠️ **对不上就意味着这一批所有拿它当分母的数全部失效**，别悄悄换一把尺继续量")
        return 9
    print("ruler OK = 码表对那把尺（P102 第 821 轮逐格相同）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
