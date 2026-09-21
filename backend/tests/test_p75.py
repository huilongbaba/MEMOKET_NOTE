"""P75：**那把量「泛」的尺造出来了**（`scripts/topic_spread_ruler.py`，新），
量完了、逐种读完了，**判「不接进 `search.py`」**。

**产品代码一行没改。** 改的只有 `scripts/topic_spread_ruler.py`（新）、这个文件（新）、
`tests/fixtures/memory_sample.jsonl`（+132 行标注）、两份文档。
`frontend/scripts/walkthrough/` · `frontend/scripts/run-walkthrough-fakeshell.mjs` ·
`frontend/src/editor/` **一个字节没碰**（另有 agent 在那一侧）。

出身（**整行跟着数走**）：HEAD `7ec5d55` · `scripts/recall_ruler.py` 765 条
（cursor 727 / tail 38 · 血缘 user 549 / script 178 / fixture 38）·
`notes=482篇/321250字/47dcc54be60aa4f2` · `terrence=11429185B/403a1183`。

四栏留下率**整行、一栏没跌**（`KITE_DATA_DIR=<scratch>/p75data` 自己量的，不是抄的）：
`recall_selfcheck terrence 200 11` **197/195/96**、`… evidence` **192/190/92** ·
圆点 **166/137/33** · D2 表 B **8 条**（N2 5 · N4 3）。

**这个文件钉的是「结论的前提」**——三条结论（尺子长这样 / 量出来这些数 / 判不接）
全是「先量再改」量完判的，前提一变结论就得重量。
"""

from __future__ import annotations

import inspect
import json
import pathlib
import textwrap

from app.database.kb import search as kb_search
from scripts import topic_spread_ruler as R

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _src(fn) -> str:
    return textwrap.dedent(inspect.getsource(fn))


class _F:
    """一条假事实。`TopicFace` 只要 `.text` / `.topics` / `.unit` 三样——
    **所以反例不必有真语料**，也就不会出现「在真库上碰巧对」那种对。"""

    __slots__ = ("text", "topics", "unit")

    def __init__(self, text, topics, unit="u"):
        self.text, self.topics, self.unit = text, tuple(topics), unit


def _corpus():
    """一份 60 条的假库：6 个话题各 10 条。
    `泛词` 每个话题都出现 → 话题面跟随手抓一把一样宽；
    `专词` 只落在一个话题里 → 把话题收住了。"""
    topics = [f"t{i}" for i in range(6)]
    facts = []
    for i, t in enumerate(topics):
        for j in range(10):
            words = ["泛词"] if j < 6 else []
            if t == "t0":
                words.append("专词")
            facts.append(_F(f"第{i}-{j}段 " + "".join(words) + "内容", (t,), unit=f"u{i}"))
    return facts


# ── ① 反例两头 + 第三档 ─────────────────────────────────────────────────────

def test_第一条_泛尺造出来了_该红的红该绿的绿还有判不了那一档():
    """**先喂反例证明它在动**（样例 `scripts/check_shipped_source.py`）。

    这一格喂的是**假语料**，三档各一个：
    · `泛词` 在 6 个话题里各出现 6 次（n=36）→ 话题面 = 随手抓一把 → **判泛**；
    · `专词` 只在 t0 里出现 4 次（n=4）→ 不够 `SPREAD_MIN_HITS` → **判不了**；
    · `没有这个串` → n=0 → **判不了**。
    **有红有绿有第三档，不是恒真也不是恒假。**

    真语料那一头的反例在 `scripts/topic_spread_ruler.py` 的 `main()` 里
    （terrence 上三组 6+6+2，`exit 9`），跟这一格**不是同一份**——
    一份证「判据本身会动」，一份证「在这个人的真库上判对了」。
    """
    face = R.TopicFace(_corpus())
    assert face.generic("泛词") is True
    n, k = face.face("泛词")
    assert (n, k) == (36, 6), (n, k)
    assert face.spread("泛词") > R.SPREAD_GENERIC

    # `专词` 全落在 t0 的那 10 条上：n=10 < SPREAD_MIN_HITS=20 → **判不了**，
    # **不是「判它不泛」**。这一格钉的就是「样本不够 ≠ 结论」。
    assert face.face("专词") == (10, 1)
    assert face.generic("专词") is None


def test_第一条b_判不了那一档是None不是False():
    """`None` 跟 `False` 分得开（同 `_aligned` 那条规矩：判不了 ≠ 判它不泛）。"""
    face = R.TopicFace(_corpus())
    assert face.generic("库里根本没有这一串") is None
    assert face.face("库里根本没有这一串") == (0, 0)
    # 刚好卡在门槛下一格：`第0-` 只在 u0 那 10 条里
    assert face.face("第0-") == (10, 1)
    assert face.spread("第0-") is None
    assert face.generic("第0-") is None


def test_第一条c_门槛两头各喂一个():
    """阈值两侧各一个：一个 ≥ `SPREAD_GENERIC` 判泛，一个 < 判不泛，
    **而且两个的 n 一样大**——「它不是 IDF」这句话在假语料上也得成立。"""
    topics = [f"t{i}" for i in range(8)]
    facts = []
    for i, t in enumerate(topics):
        for j in range(10):
            w = "散串" if j < 3 else ""          # 8 个话题 × 3 = 24 次，铺满 8 个话题
            w2 = "聚串" if (i < 2 and j < 6) else ""   # 2 个话题 × 6 = 12 次… 不够，补
            facts.append(_F(f"x{i}{j}{w}{w2}", (t,), unit=f"u{i}"))
    for j in range(12):
        facts.append(_F(f"y{j}聚串", ("t0",), unit="u0"))    # 聚串共 24 次，压在 2 个话题里
    face = R.TopicFace(facts)
    n1, _ = face.face("散串")
    n2, _ = face.face("聚串")
    assert n1 == n2 == 24, (n1, n2)
    assert face.generic("散串") is True
    assert face.generic("聚串") is False
    # **同 n，两头相反**——这一条一旦不成立，这把尺就退化成了 df
    assert face.spread("散串") > R.SPREAD_GENERIC > face.spread("聚串")


def test_第一条d_稀疏化那条曲线本身():
    """**这一格是突变验第 ⑤ 刀补出来的**：把 `expected()` 换成「话题总数」
    （= 不做稀疏化，退回「种数 / 话题总数」），上面三格**一条都没红**。
    「反例得真的落在被测分支里」——那三格喂的语料都够大，`E(n)` 已经贴到话题总数了。

    真正钉住这条曲线的是它的两头：抽 **1** 条事实指望看见的话题数**正好是 1**
    （Σp_i = 1），抽很多条才慢慢逼近话题总数。**除以话题总数就不是这条曲线。**
    """
    face = R.TopicFace(_corpus())
    assert len(face.ps) == 6
    assert abs(face.expected(1) - 1.0) < 1e-9          # 抽 1 条 = 1 个话题
    assert face.expected(1) < face.expected(5) < face.expected(50)
    assert face.expected(50) < len(face.ps)            # 永远够不到话题总数
    assert abs(face.expected(10000) - len(face.ps)) < 1e-6


def test_第二条_预筛给不给结果必须一样():
    """`units_for` 是快路不是判据。给一个**正确的**预筛、给一个**回 None 的**预筛，
    跟不给，三样结果逐格相同。

    真库上核过 **1062 种、对不上 0**（`<scratch>/p75/prefilter.py`，
    量程是 765 条摆出去的那批串里 terrence 那一半）。
    """
    facts = _corpus()
    plain = R.TopicFace(facts)
    good = R.TopicFace(facts, units_for=lambda t: frozenset(f"u{i}" for i in range(6)))
    dunno = R.TopicFace(facts, units_for=lambda t: None)
    boom = R.TopicFace(facts, units_for=lambda t: (_ for _ in ()).throw(RuntimeError("坏了")))
    for t in ("泛词", "专词", "没有这个串"):
        assert plain.face(t) == good.face(t) == dunno.face(t) == boom.face(t), t


def test_第二条b_ascii串按词边界核_不是子串():
    """**这一格也是突变验补出来的**（第 ⑥ 刀：把 ASCII 那条词边界正则换成子串，
    上面几格一条都没红——**假语料里压根没有会撞的 ASCII 串**）。

    判据逐字照 `kite_memory._GrepIndex.unit_df` 那条：`pr` 拿子串数去数会在
    product / approve 里命中（真库上 692 个 unit，而它真正作为一个词只在 33 个里）。
    中文没有词边界，**子串就是要的那个数**——所以这一格两头都喂。
    """
    facts = [_F("我们的 product 排期", ("t0",), "u0"),
             _F("approve 了没有", ("t1",), "u1"),
             _F("pr 那条要发", ("t2",), "u2"),
             _F("PR 稿明天给", ("t3",), "u3"),
             _F("这是产品设计", ("t4",), "u4"),
             _F("产品要上线", ("t5",), "u5")]
    face = R.TopicFace(facts)
    assert face.face("pr") == (2, 2)       # 只数 `pr` / `PR` 两条，不数 product / approve
    assert face.face("产品") == (2, 2)      # 中文照旧按子串（「产品设计」里那个也算）


# ── ② 全库量出来的数 ────────────────────────────────────────────────────────

def test_第三条_全库量出来的数_钉住它的前提():
    """## 全库 765 条，摆出去的串里「泛」占多少（`KITE_DATA_DIR=<scratch>/p75data`）

    先证口径：这一趟跑出来 **摆出去 3673 串次 / 含汉字 2543 / 有召回 341 条**——
    **2543 跟 P71 ① 那张表逐格相同**（那一刀之后的 `display_terms`），
    所以量的是同一件事。⚠️ P73 ③ 记的是「摆出去的汉串 3064 串次」，**跟这个对不上**；
    今天这一趟按 `routers/memory.recall` 的真口径（`surfaces` → `display_terms`）
    重量是 2543，账记在台账 P75。

    | | 串次 | 泛 | 不泛 | 判不了 |
    |---|---:|---:|---:|---:|
    | 全部摆出去的 | 3673 | 323（8.8%） | 1192 | 2158（58.8%） |
    | **含汉字的** | 2543 | **232（9.1%）** | 728 | **1583（62.2%）** |

    **判得了的那 960 个汉串次里，泛占 24.2%。**

    ⚠️ **按血缘分开**：user **172 / 1815 = 9.5%**（判得了的里 26.1%）·
    script 60 / 570 = 10.5%（19.9%）· fixture **0 / 158**（**158 个全判不了**）。

    判不了那 1583 拆开：**库里一次都没有这一串 925** + 有但不够 20 次 658。
    **前一档是另一件事**——`display_terms` 合出来的窗口本来就不保证在库里存在，
    那是 P73 ②「够不着」那一格的亲戚，不归这把尺管。

    按行算：摆出过汉串的 710 条查询里，**207 条（29.2%）的行里至少有一个泛的**。

    ## 逐种读完了，准确率

    判得了且 `spread ≥ 0.65`（设计集上定的那个门槛，收紧前的超集）的 **116 种 / 478 串次**
    **逐种读完**，标注 `memory_sample.jsonl` 的 `p75-generic-116`：

    | 门槛 | 种 | 串次 | 真泛 | 假阳性 | 准确率 |
    |---|---:|---:|---:|---|---:|
    | 0.65 | 116 | 478 | 110 | 电脑 · 存储 · 银行 · 量产 · 手机 · 大模型 | 94.8% |
    | **0.75（今天这把）** | **81** | **232** | **79** | 电脑 · 存储 | **97.5%** |
    | 0.80 | 54 | 115 | 53 | 存储 | 98.1% |

    **P73 ③ 那把 79.7% 准的尺没接进去；这把 97.5%。**
    ⚠️ 但阈值和准确率**读在同一批数上**，没有留出集——这一条见下一格。
    """
    assert R.SPREAD_MIN_HITS == 20
    assert R.SPREAD_GENERIC == 0.75
    # 量程的前提：`display_terms` 全仓库仍然只有一个调用点，喂的仍然是 `surfaces`
    # （接线一变，2543 那个数就废了——同 P73 ② 钉的那一条）
    router = (ROOT / "backend" / "app" / "routers" / "memory.py").read_text("utf-8")
    assert router.count("display_terms(") == 1
    assert "display_terms(terms, body.query, segment=mem.segment())" in router
    hits = [p for p in (ROOT / "backend" / "app").rglob("*.py")
            if "display_terms(" in p.read_text("utf-8")
            and p.name not in ("search.py", "memory.py")]
    assert hits == [], hits
    # 话题轴的前提：`FactRecord.topics` 还是那条轴
    # ⚠️ **P88 挪了地方，没换东西**：轴原来写死在 `__init__` 的循环里，P88 把它拆成
    # `_keys()` 一个方法好让 `WhoFace` 换轴（稀疏化那段数学一行都没抄）。
    # 这一条要钉的是「`TopicFace` 的轴仍然是 `topics`」，所以跟着挪到 `_keys` 上，
    # **判据一个字没放宽**；顺手再钉一句「`__init__` 是拿 `_keys` 在数」，
    # 免得有人只改 `_keys` 而 `__init__` 还在读别的东西。
    assert "getattr(f, \"topics\", None)" in _src(R.TopicFace._keys)
    assert "self._keys(f)" in _src(R.TopicFace.__init__)
    assert R.TopicFace.AXIS == "topics"


def test_第四条_判不接进search_三条理由_钉住每一条的前提():
    """## 判：**不接**（`kb/search.py` 一个字没碰）

    先把「接了会怎样」量完了（`<scratch>/p75/cf.py`，`_strong_enough` 那道门再加一句
    「站得住的那一条不能是泛的」）。**抄件先在「恒不泛」下跟真货 765 条逐条相同、对不上 0**，
    证完才往下量。

    | | 有召回 | 召回对 | top-8 变了 | 血缘 |
    |---|---:|---:|---:|---|
    | 基线 | 341/765 | 1347 | — | — |
    | 加泛闸 | 331/765 | 1329 | **16** | user 12 / script 4 |

    **16 条逐条读完**（标注 `p75-cf16`）：**变好 13 · 变差 3**；
    按血缘 user **11 好 / 1 差**、script **2 好 / 2 差**。

    四栏**一栏没跌**，而且**这个绿是有个数的**：同一趟里这一刀被问过 **8420 次**、
    原本判 True 的 **165 次**、被它**改口成 False 的 29 次**——
    **不是「闸够不着所以没动」**。（量法 `<scratch>/p75/cf_selfcheck2.py`。）

    ### 三条理由

    1. **3 条变差里 2 条是同一个形状，而那个形状指着另一处。**
       i=373 / 374 掉的是「T0 按 EV 这个阶段往前排…5 月 15-18 号」——**真沾边**。
       扛着它的是 `阶段`（判泛），而真正具体的 `ev` / `dvt` 被**英文 ≥3 个字母**
       那条门槛（`EVIDENCE_CJK_MIN` 那段注释里的 `len(h) >= 3`）挡在外面。
       **泛闸要接，得先把英文那道门量清楚**，不然这一刀是在替另一处的洞买单。
       **一刀只动一处。**
    2. **验收尺不独立。** 阈值在这 765 条上定、准确率也在这 765 条上读；
       而四栏里唯一会动的 `sametopic` **跟这把尺共用 `fact.topics` 这条轴**
       ——拿它验收就是「按 k 排完再按 k 量」（P73 ② 那张脸、P4 那一跤）。
       真要接，先得有一份**这批数据之外**的标注。
    3. **这把尺今天只够得着三分之一**（判得了 37.8% / 判不了 62.2%）。
       照这个覆盖面接进 `_strong_enough`，等于给三分之一的词加一道门、
       另外三分之二原样——**那是一道口径不齐的门**。

    **数都在这儿了**，下一批要接，缺的是 ① 英文那道门的账 ② 一份留出标注。
    """
    src = _src(kb_search._strong_enough)
    # 没接：`_strong_enough` 的形参和门槛逐字没动
    assert "def _strong_enough(hits: list[str], query: str = \"\", segment=None, common=None)" in src
    assert "if n >= STRONG_CJK_MIN:" in src
    assert "generic" not in src and "spread" not in src
    assert kb_search.STRONG_CJK_MIN == 2
    assert kb_search.LONG_QUERY_MIN_WORDS == 2
    # 理由 1 的前提：英文那道门还是「≥3」，而且就在这个函数里
    assert "if len(h) >= 3:" in src
    # 整个 kb/ 这一侧都没接上这把尺
    whole = (ROOT / "backend" / "app" / "database" / "kb" / "search.py").read_text("utf-8")
    assert "topic_spread" not in whole
    # 理由 2 的前提：`sametopic` 那一栏走的确实是 `topics`（共用轴 ⇒ 不能当验收）
    sc = (ROOT / "backend" / "scripts" / "recall_selfcheck.py").read_text("utf-8")
    assert "sametopic" in sc and 'getattr(f, "topics", ())' in sc


def test_第五条_废掉的三版照实记在台账里():
    """**废掉的版本是这一批最值钱的产出之一**（P73 废两版、P74 废两版，这一批废三版）。

    1. **峰值 / 平均 tf**（「有没有哪一段是真在谈它」）——两组分不开：
       `华为` 平均 3.1 比 `众筹` 1.67 还高（真库上 `华为` 有一个 unit 里出现 14 次）。
    2. **头词测试**（「有多少个不同的更长的词以它结尾」，`计划`→`原计划`/`按计划`）——
       `时间` 19 种、`产品` 6 种，可 `华为`/`苹果`/`客户`/`团队`/`负责人` **全是 0**，
       而 `硬件` 3 种。**它只够得着「类名」那一族，大厂名那一族一个都够不着。**
    3. **同伴一致性**（「跟它同台最多的那个实词覆盖它几成的 unit」）——
       两组全落在 0.62–1.00，**被 `这个`/`我们`/`一个` 这种口水词占满**，一点没分开。

    三版的量法和数在 `docs/TRACELOG-product.md` 的 P75 节。
    """
    doc = (ROOT / "docs" / "TRACELOG-product.md").read_text("utf-8")
    assert "## P75 ·" in doc
    for s in ("峰值", "头词", "同伴一致性", "废掉的三版"):
        assert s in doc, s


def test_第六条_这一批的标注进了memory_sample():
    """**新标注当批进 `memory_sample.jsonl`**（P63 那一课：量具和标注一起进仓库）。"""
    path = ROOT / "backend" / "tests" / "fixtures" / "memory_sample.jsonl"
    rows = [json.loads(ln) for ln in path.read_text("utf-8").splitlines() if ln.strip()]
    g = [r for r in rows if r.get("set") == "p75-generic-116"]
    c = [r for r in rows if r.get("set") == "p75-cf16"]
    assert len(g) == 116, len(g)
    assert len(c) == 16, len(c)
    # 准确率那一栏是从这些标注里数出来的，不是手写的
    tight = [r for r in g if r["spread"] >= R.SPREAD_GENERIC]
    assert len(tight) == 81, len(tight)
    assert sum(1 for r in tight if r["对不对"] == "对") == 79
    assert sorted(r["term"] for r in tight if r["对不对"] == "假阳性") == ["存储", "电脑"]
    assert sum(1 for r in c if r["判"] == "变好") == 13
    assert sum(1 for r in c if r["判"] == "变差") == 3
    assert sorted(r["i"] for r in c if r["判"] == "变差") == [373, 374, 653]


def test_第七条_反例三组还钉在尺子里():
    """`main()` 那三组反例（泛 6 · 不泛 6 · 判不了 2）+ 同 n 对照是这把尺的身份。
    **少一组就成了恒真或恒假**，对不上 `exit 9`。"""
    assert len(R.BATTERY_GENERIC) == 6
    assert len(R.BATTERY_SPECIFIC) == 6
    assert len(R.BATTERY_UNDECIDED) == 2
    assert "华为" in R.BATTERY_SPECIFIC      # P73 点名的那个，真库上它 **不泛**（0.33）
    assert "计划" in R.BATTERY_GENERIC and "情况" in R.BATTERY_GENERIC
    src = _src(R.main)
    assert "return 9" in src
    assert "同 n 对照（它不是 IDF）" in src
