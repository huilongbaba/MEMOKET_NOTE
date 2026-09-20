"""P77：**英文 ≥3 那道门量完了**（`scripts/en_gate_ruler.py`，新）+ 那 925 量完了 +
**一份留出标注造出来了**——三条**全是「量了没改」**。

**产品代码一行没改。** 改的只有 `scripts/en_gate_ruler.py`（新）、这个文件（新）、
`tests/fixtures/memory_sample.jsonl`（+203 行标注）、两份文档。
`frontend/scripts/walkthrough/` · `frontend/scripts/run-walkthrough-fakeshell.mjs` ·
`frontend/src/editor/` **一个字节没碰**（另有 agent 在那一侧）。

出身（**整行跟着数走**）：HEAD `0ab4d59` · `scripts/recall_ruler.py` 765 条
（cursor 727 / tail 38 · 血缘 user 549 / script 178 / fixture 38）·
`notes=482篇/321250字/47dcc54be60aa4f2` · `terrence=11429185B/403a1183`。

四栏留下率**整行、一栏没跌**（`KITE_DATA_DIR=<scratch>/p77data` 自己量的，不是抄的）：
`recall_selfcheck terrence 200 11` **197/195/96**、`… evidence` **192/190/92** ·
圆点 **166/137/33** · D2 表 B **8 条**（N2 5 · N4 3）· 47 条 **46/36/4/6**。

**这个文件钉的是「结论的前提」**：三条结论（这道门挡的是什么 / 那 925 是什么 /
留出集上 97.5% 站不站得住）全是「先量再改」量完判的，前提一变结论就得重量。
"""

from __future__ import annotations

import inspect
import json
import pathlib
import textwrap

from app.database.kb import search as kb_search
from scripts import en_gate_ruler as G

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "memory_sample.jsonl"


def _src(fn) -> str:
    return textwrap.dedent(inspect.getsource(fn))


def _rows(setname: str) -> list[dict]:
    out = []
    for line in FIX.read_text("utf-8").splitlines():
        d = json.loads(line)
        if d.get("set") == setname and "_meta" not in d:
            out.append(d)
    return out


def _meta(setname: str) -> dict:
    for line in FIX.read_text("utf-8").splitlines():
        d = json.loads(line)
        if d.get("set") == setname and "_meta" in d:
            return d["_meta"]
    raise AssertionError(f"{setname} 的 _meta 不在")


# ── ① 反例：该红的红、该绿的绿，**对照那几格换量程也不动** ──────────────────────

def test_第一条_这把尺自己的反例十格_有红有绿():
    """**任何「核对」先喂它一个该红 / 该绿的反例**（样例 `scripts/check_shipped_source.py`）。

    `en_gate_ruler.BATTERY` 十格喂的是**假的 (串, weigh)**，不需要真语料：
    · 两个 2 字母的英文串 → `EN_MIN=3` 判 False、`EN_MIN=2` 判 True（**它在动**）；
    · `dvt` 三个字母 → `≥3` 就放行（**P75 ① 说它被挡，那句话记错了**）；
    · **对照**：纯汉字实词（`weigh` 有数）在 2 / 3 / 9 三档都 True
      ——这道门只管 `None` 那一档，换量程动不到它。**这一格是「绿有个数」的那个绿。**

    真库那一头的反例在 `scripts/en_gate_ruler.py` 的 `main()` 里（对不上 `exit 9`），
    跟这一格**不是同一份**。
    """
    assert G.run_battery() == []
    assert len(G.BATTERY) == 10
    # 三档都要有：该 True 的、该 False 的、换量程也不动的对照
    wants = [w for _n, _cl, _ns, _e, w in G.BATTERY]
    assert True in wants and False in wants
    assert G.decide(["dvt", "ai"], [None, None], 3) is True, "三个字母今天是过得去的"
    assert G.blocked(["dvt", "ai", "t0"], [None, None, None], 3) == ["ai", "t0"]


def test_第一条b_抄件跟产品那一行逐行一致():
    """`decide()` 是 `_strong_enough` 的抄件。**抄件跟原件对不上，量出来的数全废。**

    这一格不比字符串，比**行为**：把产品那个函数的分支在 `EN_MIN=3` 下逐格走一遍。
    """
    cases = [
        (["ai", "ui"], [None, None], False),      # 两个 2 字母 → 挡住
        (["dvt", "ai"], [None, None], True),      # 3 字母 → 过
        (["华为", "阿里"], [2, 2], True),          # 实词 2 字 → 过（跟这道门无关）
        (["可以实", "的数据"], [0, 0], False),      # 碎片 0 字 → 不过
        (["ai"], [None], False),                  # 只有一条串 → 不过
    ]
    for cl, ns, want in cases:
        assert G.decide(cl, ns, 3) is want, (cl, ns)
    # 源文件那一头：`check_source()` 是回去核真源文件的，空 = 对得上
    assert G.check_source() == []


def test_第二条_那道门今天逐字没动_而且这三个常量是它的前提():
    """## 判：**不动**（`kb/search.py` 一个字没碰）

    | | 有召回 | 召回对 | top-8 变了 |
    |---|---:|---:|---:|
    | 今天（≥3） | 341/765 | 1347 | — |
    | 放宽到 2（**= 不设门**） | 342/765 | 1353 | **2**（两条都变差） |
    | 收紧到 4 | 317/765 | 1225 | **67**（变差 47 · 变好 19 · 中性 1） |

    放宽那 2 条正是 `_strong_enough` 注释里记着的那个形状
    （「一度混进 6 条全靠 `ui` / `os` 撞进来的，**教室方案的项目表召回一屏 UI 设计讨论**」）
    ——`p77-en-cf2` 的 i=128 就是那条教室方案的查询。
    """
    src = _src(kb_search._strong_enough)
    assert "if len(h) >= 3:" in src
    assert "n = weigh(h) if weigh is not None else None" in src
    assert "if n >= STRONG_CJK_MIN:" in src
    assert kb_search.STRONG_CJK_MIN == 2
    assert kb_search.LONG_QUERY_MIN_WORDS == 2
    assert kb_search.LONG_QUERY == 100
    # 孪生常量（P32 定的那一对）也没被顺手带走
    assert kb_search.EVIDENCE_EN_MIN == 3 and kb_search.EVIDENCE_CJK_MIN == 4
    # 这道门**只有这一个调用点**——多一个，765 那一趟记下来的 375864 次就不是全部了
    whole = (ROOT / "backend" / "app" / "database" / "kb" / "search.py").read_text("utf-8")
    assert whole.count("_strong_enough(") == 2, "一个 def + 一个调用点"
    assert "if long_query and not _strong_enough(hits, query, segment, common):" in whole


def test_第三条_挡掉的那14种和它们的量_全在标注里():
    """## ① 这道门挡掉了什么（真库 terrence / 765 条那把尺）

    **14 种 / 568 串次**（英文 561 · 数字/符号 3 · 混合 4；
    血缘 user 405 / script 156 / fixture 7），落在 557 次调用上。

    `ai` 一个占 451（79.4%）。**「挡掉了」不等于「因此少了一条召回」**：
    真正因为它才判 False 的只有 **11 次 / 7 条查询**，而那 11 次里扛旗的是
    `ai`(6) / `5%`(3) / `8个`(2)——**一个真·产品术语都没有**；
    `ev` / `t0` / `q3` / `ib` 被挡了 19 串次，**一次都没改变过判**。
    """
    rows = _rows("p77-engate-14")
    assert len(rows) == 14
    assert sum(r["串次"] for r in rows) == G.EXPECT_BLOCKED_OCC == 568
    top = max(rows, key=lambda r: r["串次"])
    assert (top["term"], top["串次"]) == G.EXPECT_TOP_BLOCKED == ("ai", 451)
    terms = {r["term"] for r in rows}
    assert "dvt" not in terms, "P75 ① 说 dvt 被挡——量下来没有，这一格钉的就是那条更正"
    assert {"ev", "t0", "q3", "ib", "mp"} <= terms
    # **每一个被挡的串都是 2 个字**——这正是「不设门 ≡ 放宽到 2」成立的全部理由
    assert all(len(r["term"]) == 2 for r in rows), [r["term"] for r in rows]
    # 翻过盘的只有三个，而且都是噪声
    flipped = {r["term"] for r in rows if r["翻过盘"]}
    assert flipped == {"ai", "5%", "8个"}
    assert all(r["读下来"] == "噪声" for r in rows if r["term"] in flipped)
    assert G.EXPECT_FLIP_AT_2 == 11 and G.EXPECT_FLIP_QUERIES_AT_2 == 7
    assert G.EXPECT_FLIP_AT_4 == 213 and G.EXPECT_FLIP_QUERIES_AT_4 == 100
    assert G.EXPECT_CF[2] == G.EXPECT_CF[1] == (342, 1353, 2)
    assert G.EXPECT_CF[4] == (317, 1225, 67)


def test_第三条b_不设门跟放宽到2逐格相同_它的前提在取词那一层():
    """**「2 / 4 / 不设门」里的「不设门」不是第三档旋钮**：这个库上它跟「放宽到 2」逐格相同。

    前提不在这道门上，在**取词那一层**——这个仓库里压根出不来 1 个字的串：
    · 英文候选词 `_EN` 至少两个字母（`[A-Za-z][A-Za-z0-9_-]{1,}`）；
    · 中文 n-gram 窗口最短 2 字；
    · `_number_terms` 那三个形状最短也是 2 个字符。
    **这一条一旦不成立，`EXPECT_CF[1] == EXPECT_CF[2]` 那一格当场破。**
    """
    kite = (ROOT / "backend" / "app" / "database" / "kite" / "kite_memory.py").read_text("utf-8")
    assert r're.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}", text.lower())' in kite, "英文候选词的下限变了"
    assert kb_search._NUM.pattern == r"\d+月\d+|\d+(?:\.\d+)?[台套个件人次轮版元万亿%]|\d{3,}(?:\.\d+)?"
    assert min(len(t) for t in kb_search._number_terms("4月16日 15套 380mAh 5% 2")) == 2
    # 门槛 1 和 2 在「没有 1 个字的串」这个前提下是同一档
    for cl, ns in ((["ai", "ui"], [None, None]), (["5%", "8个"], [None, None])):
        assert G.decide(cl, ns, 1) == G.decide(cl, ns, 2)


def test_第四条_那925是什么_以及它今天摆到哪儿去了():
    """## ② 那 925（P75 ④ 留的那一格）

    **分母先修一格**：925 里有 **28 串次 / 8 种**不是「库里没有」，是**话题尺的定位口径**
    跟 `_hits` 不一样（`_hits` 两边 `squeeze`，`TopicFace.face` 在原文上 `re.search`，
    而库里写的是「4 月 16 日」带空格）。挤掉空白之后照样一次都没有的是 **897 串次 / 549 种**。

    **渲染那一层才是判据**（765 条实测）：424 条 `facts=0` → 那一行**压根不渲染**；
    335 条 `evidence` 有东西 → 摆 chip，`terms` 用不上；6 条 `evidence=[]` → 那句话，
    `terms` 也用不上；**走到 `terms` 那一支的 0 条**。
    ⇒ 这 925 在右栏「记忆」那一行上**一条都摆不到用户眼前**。

    **判：不改。** 唯一真摆 `terms` 的是 `KbDashboard` 的「命中词：」（知识库搜索框，
    没有 evidence 兜底），而那条路的查询是用户手打的搜索词——**765 那把尺量的不是那条路**。
    """
    rel = (ROOT / "frontend" / "src" / "components" / "RelatedMemory.tsx").read_text("utf-8")
    # 「有召回才渲染那一行」——424 条看不见，靠的就是这一行
    assert "{facts.length > 0 && !loading && (" in rel
    assert "{evidenceLine(mode, evidence, terms)}" in rel
    ctx = (ROOT / "frontend" / "src" / "util" / "recallContext.ts").read_text("utf-8")
    # `evidenceLine` 三支：有 chip 摆 chip · `[]` 说那句话 · **只有 `null` 才退回 terms**
    assert "if (evidence && evidence.length) {" in ctx
    assert "if (evidence) return head + '，' + NO_EVIDENCE_LINE" in ctx
    assert "return head + (terms.length ? '，命中：' + terms.slice(0, 6).join('、') : '')" in ctx
    # 另一条真摆 terms 的路还在（它是「判据宁可窄」那一条的全部理由）
    kb = (ROOT / "frontend" / "src" / "components" / "kb" / "KbDashboard.tsx").read_text("utf-8")
    assert "' · 命中词：' + hits.terms.slice(0, 6).join('、')" in kb
    # 后端那一头：`display_terms` 仍然只有一个调用点，喂的仍然是 `surfaces`
    router = (ROOT / "backend" / "app" / "routers" / "memory.py").read_text("utf-8")
    assert router.count("display_terms(") == 1
    assert "display_terms(terms, body.query, segment=mem.segment())" in router
    m = _meta("p77-z925-23")
    assert "897" in m["分母要修一格"] and "28" in m["分母要修一格"]
    assert len(_rows("p77-z925-23")) == 23


def test_第五条_留出标注造出来了_而且顺序是对的():
    """## ③ 留出标注（P75 ② 留的那一格）

    **跟 P75 那 116 种不是同一片**：从 terrence 全库切出来的 11698 种纯汉字 token 里，
    剔掉 P75 标过的 110 种、也剔掉 765 条摆出去过的 1210 种（剩 11386 种），
    种子 77 均匀随机、**不分层**（分层就等于先看了尺子的判），收满 80 种判得了的。

    **顺序**：先造盲标单（只有词 + 3 句上下文，一个 `spread` 都没有）→ 标完 80 条 →
    才跑揭晓。⚠️ **顺序反了就不是留出集了**。

    | 门槛 | 判泛 | 准确率 | 假阳性 | 真不泛认出来 |
    |---|---:|---:|---|---:|
    | 0.65 | 54 | 98.1% | `电话` | 11/12 |
    | **0.75（今天这把）** | **42** | **100%** | **—** | **12/12** |
    | 0.80 | 35 | 100% | — | 12/12 |

    **P75 那个 97.5% 在留出集上站得住。**
    ⚠️ 同一份留出集上 0.75 的**召回**只有 61.8%（68 个真泛认出 42）——
    但那 26 个「假阴性」大半是「这个词在**这个库里**其实收得住」（`展示` 0.45 /
    `搜索` 0.54 / `投资` 0.43），**尺子问的和人标问的不是同一个问题**，
    这个 61.8% 不能直接当缺陷读。
    """
    rows = _rows("p77-holdout-80")
    assert len(rows) == 80
    old = {d["term"] for d in _rows("p75-generic-116")}
    assert old and not ({r["term"] for r in rows} & old), "留出集跟 P75 那批有交集就不是留出集"
    m = _meta("p77-holdout-80")
    assert "种子 77" in m["抽自"] and "不分层" in m["怎么抽的"]
    assert "先造盲标单" in m["⚠️ 顺序"] and "标完" in m["⚠️ 顺序"]
    said = [r for r in rows if r["尺子判(0.75)"] == "泛"]
    assert len(said) == 42
    assert all(r["人标"] == "泛" for r in said), "0.75 在留出集上一个假阳性都没有"
    # 真不泛那一头也得认出来（不然「准确率 100%」可能只是因为它恒说泛）
    neg = [r for r in rows if r["人标"] == "不泛"]
    assert len(neg) == 12
    assert all(r["尺子判(0.75)"] == "不泛" for r in neg)
    # 0.65 那一档**有**一个假阳性——**有红有绿**，这把尺不是恒对
    said65 = [r for r in rows if r["尺子判(0.65)"] == "泛"]
    assert len(said65) == 54
    assert [r["term"] for r in said65 if r["人标"] == "不泛"] == ["电话"]
    # 被核的那把尺自己没被这一批动过
    from scripts import topic_spread_ruler as R
    assert R.SPREAD_MIN_HITS == 20 and R.SPREAD_GENERIC == 0.75


def test_第六条_换量程那两批逐条读完了_而且方向记清楚了():
    """放宽到 2 变了 **2** 条（`p77-en-cf2`，**两条都变差**）；
    收紧到 4 变了 **67** 条（`p77-en-cf4`，变差 47 · 变好 19 · 中性 1，掉 124 对 / 进 2 对）。

    **四栏一栏都没动**（`recall_selfcheck` 197/195/96 与 192/190/92 · 47 条 46/36/4/6
    在 `EN_MIN=2` 下逐格相同）——**这不等于这一刀没影响**：影响落在四栏够不着的那 2 条上，
    而那 2 条是变差的。**别拿聚合分当判据。**
    圆点那一栏倒是动了（真画 33 → 40）：`evidence=False` 那条路上 `segment` 是 `None`，
    **每一个串**都落在这道门上，爆炸半径比 `evidence=True` 那条路大得多。
    """
    cf2 = _rows("p77-en-cf2")
    assert len(cf2) == 2 and {r["i"] for r in cf2} == {128, 672}
    assert all(r["读下来"] == "变差" for r in cf2)
    cf4 = _rows("p77-en-cf4")
    assert len(cf4) == 67
    from collections import Counter
    c = Counter(r["读下来"] for r in cf4)
    assert (c["变差"], c["变好"], c["中性"]) == (47, 19, 1), c
    # 圆点那条路上这道门管的是**所有**串——`evidence=False` 时 `segment` 不给
    rec = _src(__import__("app.database.kite.kite_memory", fromlist=["x"]).UserMemory.recall)
    assert "segment = self.segment() if evidence else None" in rec


def test_第七条_P75那笔账还完了_结论跟P75的预期相反():
    """## P75 ① 那笔账的结果

    P75 说「泛闸要接，得先把英文那道门量清楚，不然这一刀是在替另一处的洞买单」。
    还完之后（`p77-cf75-11`，11 条逐条读完）：

    | | 有召回 | 召回对 | 跟真货比 top-8 变了 |
    |---|---:|---:|---:|
    | A 泛闸恒回 False（抄件自检） | 341 | 1347 | **0** |
    | B 泛闸 / 英文 ≥3（**P75 那一趟，逐格复现**） | 331 | 1329 | 16（user 12 / script 4） |
    | C 泛闸 / 英文 ≥2（**账还完**） | 339 | 1347 | 9（user 7 / script 2） |

    **账还了，可结论反过来**：放宽英文确实救回 i=373 / 374 那两条（`ev` 扛旗），
    但同一刀把 P75 亲口记在「变好」那一栏的 6 条（142/143/463/464/191/507）**原样还了回去**，
    外加 3 条新噪声。**那道门不是在替另一处买单——它正是让泛闸那 13 条变好成立的东西。**
    """
    rows = _rows("p77-cf75-11")
    assert len(rows) == 11
    assert {373, 374} <= {r["i"] for r in rows}
    back = [r for r in rows if "变好" in r["读下来"]]
    assert {r["i"] for r in back} == {142, 143, 191, 463, 464, 507}
    saved = [r for r in rows if "救回来" in r["读下来"]]
    assert {r["i"] for r in saved} == {373, 374}
    m = _meta("p77-cf75-11")
    assert "331 / 1329" in m["量程"] and "339 / 1347" in m["量程"]
    # 泛闸**今天仍然没接**（P75 判的那条，这一批一个字没动）
    whole = (ROOT / "backend" / "app" / "database" / "kb" / "search.py").read_text("utf-8")
    assert "topic_spread" not in whole and "generic" not in _src(kb_search._strong_enough)


def test_第八条_台账里写着这一批三条都没改():
    """**三条全是「量了没改」**，台账得写清楚是哪三条、各自为什么。"""
    doc = (ROOT / "docs" / "TRACELOG-product.md").read_text("utf-8")
    assert "## P77 ·" in doc
    for s in ("英文 ≥3", "925", "留出", "`dvt` 三个字母", "897", "不设门"):
        assert s in doc, s
    plan = (ROOT / "docs" / "product-readiness-plan.md").read_text("utf-8")
    assert "P77" in plan


def test_第九条_口径那六个数的前提_以及这把新尺子在仓库里():
    """**这一批所有的数都建在同一个口径上**：765 条那把尺 × `mem.recall(…, evidence=True)`
    × `display_terms(surfaces, q, segment=mem.segment())`，跑出来
    **3673 串次 / 含汉字 2543 / 种 1210 / 汉串均字 2.89 / 有召回 341 / 召回对 1347**
    ——六格跟 P75 ③ 相同。**口径一变，① ② 两条的每一个数都失效。**

    ⚠️ 那个 `1210` 是**全部串**的种数；**汉串的种数是 1012**（P71 ① / P75 ③ 那张表
    并排摆着，容易读成同一列）。这一批把它写清楚，**没去改 P75 那一节的数**。

    还有一条：**量具得在仓库里**（P63 立的，这是第五次为同一件事付钱）——
    `scripts/en_gate_ruler.py` 带三样：口径写死在代码里、出身跟着数一起打出来、
    **对不上 `exit 9`**。
    """
    from scripts import recall_ruler as RR
    assert (RR.EXPECT_TOTAL, RR.EXPECT_CURSOR, RR.EXPECT_TAIL, RR.EXPECT_USERS) == (765, 727, 38, 6)
    assert (RR.RECALL_TAIL_CHARS, RR.RECALL_MIN_CHARS, RR.RECALL_CONTEXT_BEFORE) == (500, 8, 200)
    # 新量具在仓库里，而且它的 `main()` 对不上会 `exit 9`
    assert (ROOT / "backend" / "scripts" / "en_gate_ruler.py").is_file()
    main_src = _src(G.main)
    assert "return 9" in main_src and "run_battery()" in main_src and "check_source()" in main_src
    # 上一批那把尺这一批一个字没动（它是 ③ 那一条被核的对象）
    from scripts import topic_spread_ruler as R
    assert R.SPREAD_MIN_HITS == 20 and R.SPREAD_GENERIC == 0.75
    assert R.BATTERY_UNDECIDED == ("昇腾", "瓷器纹")
