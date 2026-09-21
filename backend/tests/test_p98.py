"""P98：**半屏那道门动了**（收 P96 ②）+ **i=388 的根因**（收 P96 ①）+
**「都堵死」核了一遍，找到第三条路**（收 P96 ③）。

这一批**产品逻辑一个字节没改**（动的是那把没接进产品的尺的**屏级那道门**、
一支量具的读数、两份老闸里被这一刀改到的断言、这一份新闸、三组标注、四条新登记）。

① **半屏那道门：判「摘不得，但判据要换**（`第一条*`）。
   先**复现** P96 ⑦-d：分母 175 / 瞎掉 441 / 半屏拦下 7 屏 / 摘光 19 屏 —— **逐格相同**，
   那 7 屏**又逐条读了一遍，判逐条相同**。
   ⚠️ **摘门那笔账按库拆开是亏的**：多出来的 6 屏**全在小库**，
   多出来的那 1 屏假阳性（i=65）**在大库**，大库假阳性 **16.7% → 28.6%**，
   而 **83.8% 的查询落在大库**。⇒ **判「不摘」。**
   换上去的是 `family_cover`：**门槛还是「半屏」，只把「团」换成「这一族的话题码盖住几格」**
   ——因为**团是这一族大小的下界，不是这一族本身**。
   读数：判「是」12 → **17 屏**（真 16 / 假 1），**大库那一对 (5,1) 一格没动**，
   小库 (6,0) → **(11,0)**，半屏还拦着 **2 屏**（65 该拦 ✅ / 590 该放 ❌ 没捡回来）。
   **顺带还回一样东西**：P96 ⑦-b 代价第 3 条（en060 量具钝了一格，翻 3 屏 → 2 屏）
   **清了** —— 今天翻回 `(640, 642, 645)`，跟 `K` 那一版逐格相同。

② **i=388 为什么是假的**（`第二条*`）：团 5 条、**5 场不同录音**，
   共同 obj 是 `手环`（这库的主角物）、共同 topic 是 `work_product_design`
   （**整库 15.45%**，18 屏里最宽的码）—— **两条轴同时接近退化**，
   而它在 `M` 用的三条轴上**跟一个真的族长得一模一样**。
   **第四条路量了三条**：话题码有多泛（`work_product_design` 上**一真一假**，第一格就废）、
   obj 有多泛（没门槛分得开）、字面包含度（**门槛 0.07–0.10 真活 12/12、假活 1/6，比 `M` 还好**，
   **但两头重叠、缝只有一屏宽、没有留出集** ⇒ **这一批不走**）。

③ **「修团只有两条路，两条都堵死」核了**（`第三条*`）：**两条确实堵死**（重数了，数还更硬），
   但**「只有两条」不成立**——第三条是**话题码的 `obj` 分布画像**（cos 0.778 / 排 19 / 14196），
   **走到第三格实测：en060 的 i=641 团 3 → 4、半屏那道门原样放行**，
   HEAD 上 +1 真 0 假。**这一批也不走**（cut 是反推的、26 对没人读、HEAD 上几乎不动）。

出身：worktree HEAD `4cd2521` · `scripts/recall_ruler.py` 765 条 ·
`notes=482篇/321250字/47dcc54be60aa4f2` · `terrence=11429185B/403a1183`。
基线**自己量的**：后端带 `KITE_DATA_DIR` **3379 / 0 skipped**、前端 **101 文件 / 931 条**、
`floor_ruler` 开工 **看着 11 份 / 登记 121 条 / 共核 133 条 / 落后 0 / 对不上 0**。

⚠️ **四栏 / 圆点 / 47 条对这一批是瞎的**——产品逻辑一个字节没改。
说明事的是 `--cf-shape` 那一组数、`p98-door-7` / `p98-i388-18` / `p98-topicroad-3` 三组标注。
⚠️ **这份闸不要真语料**（同 `test_p94` / `test_p96`）：十组正反例的轴是从真语料冻下来的
字面表，跟语料对不对得上由 `--cf-shape` 在真语料上那一趟负责。
"""

from __future__ import annotations

import inspect
import json
import pathlib
import re

from app.database.kb import fact_distinct as FD
from scripts import floor_ruler as FR
from scripts import recall_ruler as RR
from test_p94 import (NEG7, NEGA, NEGC, NEGH, NEGK, NEGP, POS7, POS8, POSK, POST,  # noqa: F401
                      F, _clique, _Fact)

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "memory_sample.jsonl"
REPO = pathlib.Path(__file__).resolve().parent.parent.parent


def _rows(tag):
    out = []
    for ln in FIX.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        d = json.loads(ln)
        if d.get("set") == tag and "_meta" not in d:
            out.append(d)
    return out


def _meta(tag):
    for ln in FIX.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        d = json.loads(ln)
        if d.get("set") == tag and "_meta" in d:
            return d["_meta"]
    raise AssertionError(f"{tag} 没有 _meta —— 标注得写清「问的是什么」")


# ═══ 第一条：半屏那道门 ══════════════════════════════════════════════════

def test_第一条a_老那道门那7屏原样冻着而且复现过():
    """**引用台账的数之前先重数**：P96 那 7 屏 P98 复现过，逐格相同，冻在 `_P96` 里。"""
    assert RR.EXPECT_SHAPE_HALF_P96 == (65, 587, 588, 590, 595, 596, 597)
    assert RR.EXPECT_SHAPE_HALF_READ_P96 == (6, 1)
    # 摘光那道门的读数也原样冻着：19 = 12 + 7、真 17 = 11 + 6、假 2 = 1 + 1
    assert RR.EXPECT_SHAPE_NOHALF == (19, 17, 2)
    assert RR.EXPECT_SHAPE_NOHALF[0] == 12 + len(RR.EXPECT_SHAPE_HALF_P96)


def test_第一条b_摘门那笔账按库拆开是亏的():
    """**比率要按对的那条轴分**：摘门的收益全在小库、代价在大库。
    **这一条就是「判不摘」的数本身**。"""
    big_now = RR.EXPECT_SHAPE_READ_BIGLIB
    big_off = RR.EXPECT_SHAPE_NOHALF_BIGLIB
    assert big_now == (5, 1) and big_off == (5, 2)
    # 摘光只多抓 0 屏真的、多 1 屏假的 —— **在大库上纯亏**
    assert big_off[0] == big_now[0], "摘门在大库上一屏真的都没多抓到"
    assert big_off[1] == big_now[1] + 1, "摘门在大库上多的正好是 i=65 那一屏假的"
    assert big_now[1] / sum(big_now) < big_off[1] / sum(big_off), "摘门让大库假阳性变高"
    # 多出来的那一屏必须点名，而且必须是人读「该拦」的那一屏
    rows = {r["i"]: r for r in _rows("p98-door-7")}
    assert rows[65]["判"] == "该拦"
    assert rows[65]["新门"] == "仍然拦着", "i=65 那笔账一分都不许欠"


def test_第一条c_换的是判据不是摘门():
    """**一刀只动一处**，而且那一刀落在 `screen_shape` 的门上，不在 `same_thing` 上。"""
    src = inspect.getsource(FD.screen_shape)
    assert src.count("len(fam) * 2 >= n") == 1, "老那半句门必须原样留着"
    assert src.count("cover * 2 >= n") == 1, "新那半句该正好一份"
    # ⚠️ **一份一份点名核**：`FAMILY_MIN` 在 `screen_shape` 里有 3 份 ——
    # 文档串里 1 份 + 代码里 2 份（`n >= FAMILY_MIN` 和 `len(fam) >= FAMILY_MIN`）。
    assert src.count("FAMILY_MIN") == 3
    assert src.count("n >= FAMILY_MIN") == 1 and src.count("len(fam) >= FAMILY_MIN") == 1, \
        "两道老门（量得了 ≥3、团 ≥3）都得还在"
    # `same_thing` 这一批**逐字没动**（P96 那三条轴原样）
    body = inspect.getsource(FD.same_thing).split('"""', 2)[2]
    assert body.count("and a.unit != b.unit") == 1
    assert body.count("set(a.obj) & set(b.obj)") == 1
    assert body.count("set(a.topics) & set(b.topics)") == 1
    # `measurable` 也没动（`TOTAL` / `BLIND` 是它决的，这一刀不该动它们）
    assert "unit" not in inspect.getsource(FD.measurable)
    assert RR.EXPECT_SHAPE_TOTAL == 175 and RR.EXPECT_SHAPE_BLIND == 441


def test_第一条d_family_cover拴在团自己身上不是屏上最主导的码():
    """⚠️ **这一格是量出来的，不是想出来的**（第 ⑧-d 格）：
    拿「屏上最主导的 topic」当门，en060 的 i=641 会被一个**跟团无关**的码放行。"""
    src = inspect.getsource(FD.family_cover)
    assert "common" in src and "&" in src, "得先求团的**共同**码"
    assert "facts[i].topics" in src
    # 直接拿十组正反例里的一组核：团的共同码必须真的是团里每一条都挂着的
    facts = list(POS7[1])
    fam = FD.largest_family(facts)
    common = set(facts[fam[0]].topics)
    for i in fam[1:]:
        common &= set(facts[i].topics)
    cover = FD.family_cover(facts, fam)
    assert cover >= len(fam), "盖住的格数至少得有团那么多（团里每条都挂着共同码）"
    assert cover == max(sum(1 for f in facts if t in f.topics) for t in common)
    # 团 < FAMILY_MIN 时不说话（没有团就没有「这一族的话题码」）
    assert FD.family_cover(facts, fam[:2]) == 0
    # ⚠️ **只数「量得了」的格**（突变刀 ⑤′ 打的就是这一格：把 `idx` 换成整屏
    # 会让一条 `obj` 空的事实也进分子，而**判不了的格整格不进分母**，第 ⑥ 格）。
    blind = _Fact(facts[fam[0]].id)
    blind.obj = ()
    blind.topics = tuple(common)
    assert not FD.measurable(blind), "这一条得是「量不了」的"
    assert FD.family_cover(facts + [blind], fam) == cover, \
        "一条 `obj` 空的事实挂着这一族的码，**不许**把「盖住」顶上去"
    # 那一格的措辞得写在尺身上（突变刀打的就是这儿）
    assert "**必须是团自己的共同码，不是这一屏最主导的码。**" in FD.family_cover.__doc__


def test_第一条e_换门之后那一组数():
    """换门动了五个数、**没动四个**。没动的那四个里 `READ_BIGLIB` 最要紧。"""
    assert RR.EXPECT_SHAPE_HEAD == 17
    assert RR.EXPECT_SHAPE_EN060 == 20
    assert RR.EXPECT_SHAPE_READ == (16, 1)
    assert RR.EXPECT_SHAPE_READ_SMALLLIB == (11, 0)
    assert RR.EXPECT_SHAPE_HALF == (65, 590) and RR.EXPECT_SHAPE_HALF_READ == (1, 1)
    # 没动的四个
    assert RR.EXPECT_SHAPE_TOTAL == 175 and RR.EXPECT_SHAPE_BLIND == 441
    assert RR.EXPECT_SHAPE_FLIP_OFF == ()
    assert RR.EXPECT_SHAPE_READ_BIGLIB == (5, 1), \
        "**大库那一对一格没动**——这是「换门不是摘门」的凭据本身"
    # 三档必须严格套着：判「是」 ⊊ 摘光，判「是」+ 被门拦下 = 摘光
    assert RR.EXPECT_SHAPE_HEAD + len(RR.EXPECT_SHAPE_HALF) == RR.EXPECT_SHAPE_NOHALF[0]
    assert sum(RR.EXPECT_SHAPE_READ) == RR.EXPECT_SHAPE_HEAD
    big, small = RR.EXPECT_SHAPE_READ_BIGLIB, RR.EXPECT_SHAPE_READ_SMALLLIB
    assert (big[0] + small[0], big[1] + small[1]) == RR.EXPECT_SHAPE_READ
    # 按库那张表：只有 `terrence-rewrite` 那格动了
    libs = dict((u, n) for u, n, _d in RR.EXPECT_SHAPE_LIBS)
    assert libs["terrence"] == 6 and libs["terrence-rewrite"] == 9 and libs["shot-demo"] == 2
    assert sum(n for _u, n, _d in RR.EXPECT_SHAPE_LIBS) == RR.EXPECT_SHAPE_HEAD
    assert sum(d for _u, _n, d in RR.EXPECT_SHAPE_LIBS) == RR.EXPECT_SHAPE_TOTAL


def test_第一条f_换M那条代价清了():
    """P96 ⑦-b 代价第 3 条：「当 en060 量具那一头钝了一格」（翻 3 屏 → 2 屏）。
    **换门之后翻回三屏，跟 `K` 那一版逐格相同** —— 那条代价清了。

    ⚠️ **另外两条代价（i=94 丢了 / i=388 没治好）照旧欠着**，一条一条核。
    """
    assert RR.EXPECT_SHAPE_FLIP_ON == RR.EXPECT_SHAPE_FLIP_ON_K == (640, 642, 645)
    assert RR.EXPECT_SHAPE_EN060 - RR.EXPECT_SHAPE_HEAD == len(RR.EXPECT_SHAPE_FLIP_ON) == 3
    # **反例得真的落在被测分支里**
    assert set(RR.EXPECT_SHAPE_FLIP_ON) <= set(RR.EXPECT_CF_GATES_EN060_IDX)
    # 另外两条代价还欠着
    assert RR.EXPECT_SHAPE_LEFTOVER == (388,), "i=388 还是假的"
    assert 94 not in set(RR.EXPECT_SHAPE_FLIP_ON) | {22, 40, 307, 388, 591, 637, 638,
                                                     655, 656, 657, 677, 698}
    assert 94 not in RR.EXPECT_SHAPE_HALF, "i=94 是被 `M` 丢的（团掉到 2），不是被门拦的"
    for frag in ("**i=94 丢了**", "**i=388（`手环`）没治好**", "**当 en060 量具那一头钝了一格**"):
        assert frag in FD.__doc__, f"换 `M` 的代价少了一条：{frag}"


def test_第一条g_那7屏读完不重不漏而且新门的判都写着():
    rows = _rows("p98-door-7")
    assert len(rows) == 7
    assert {r["labeled_by"] for r in rows} == {"P98"}
    assert tuple(sorted(r["i"] for r in rows)) == RR.EXPECT_SHAPE_HALF_P96
    # **复现**：这 7 屏 P98 重读一遍，判跟 P96 逐条相同
    p96 = {r["i"]: r["判"] for r in _rows("p96-halfdoor-7")}
    assert {r["i"]: r["判"] for r in rows} == p96, "重读的判必须跟 P96 逐条相同（不同就得写更正）"
    放 = [r for r in rows if r["判"] == "该放"]
    assert (len(放), len(rows) - len(放)) == RR.EXPECT_SHAPE_HALF_READ_P96
    # 新门之后还拦着的必须正好是 `EXPECT_SHAPE_HALF`
    still = tuple(sorted(r["i"] for r in rows if r["新门"] == "仍然拦着"))
    assert still == RR.EXPECT_SHAPE_HALF == (65, 590)
    # 每一屏的「盖住」必须跟 `EXPECT_SHAPE_COVER7` 逐个对得上，而且门开不开只由它决
    cov = tuple(r["盖住"] for r in sorted(rows, key=lambda r: r["i"]))
    assert cov == RR.EXPECT_SHAPE_COVER7 == (3, 6, 6, 3, 8, 7, 7)
    for r in rows:
        assert r["团"] * 2 < r["量得了"], f"i={r['i']} 不是被老那道门拦下的"
        assert (r["盖住"] * 2 >= r["量得了"]) == (r["新门"] == "放行"), \
            f"i={r['i']}：新门开不开只该由「盖住」决"
    _meta("p98-door-7")


def test_第一条h_捡回来那5屏一个新的族都没带来():
    """⚠️ **7 屏不是 7 笔独立的账**，而且**捡回来的 5 屏一个新的族都不带来**——
    这一条挡的是「换门多抓了 5 屏 = 多认出 5 件事」那种读法。"""
    rows = {r["i"]: r for r in _rows("p98-door-7")}
    back = [i for i in (587, 588, 590, 595, 596, 597) if rows[i]["新门"] == "放行"]
    assert back == [587, 588, 595, 596, 597]
    # 五屏共同码只有一个，而那一族 i=22 / i=307 早就标出来了（都在判「是」的 17 屏里）
    assert {rows[i]["共同码"] for i in back} == {"crowdfunding_launch"}
    assert {22, 307} <= {22, 40, 307, 388, 587, 588, 591, 595, 596, 597,
                         637, 638, 655, 656, 657, 677, 698}
    # 没捡回来那一屏（i=590）的族，i=591 也早就标出来了
    assert rows[590]["共同码"] == "memory_powered_intelligence"
    assert "一个新的族都不带来" in _meta("p98-door-7")["读数"]


# ═══ 第二条：i=388 的根因 + 第四条路 ═══════════════════════════════════════

def test_第二条a_那18屏的轴表不重不漏():
    rows = _rows("p98-i388-18")
    assert len(rows) == 18
    assert {r["labeled_by"] for r in rows} == {"P98"}
    assert len({r["i"] for r in rows}) == 18
    # 判必须跟 `p94-shape-18` 逐条相同（这一组**不是新的人读**，是在旧读上量轴）
    old = {r["i"]: r["判"] for r in _rows("p94-shape-18")}
    assert {r["i"]: r["判"] for r in rows} == old
    assert sum(1 for r in rows if r["判"] == "真") == 12
    assert sum(1 for r in rows if r["判"] == "假") == 6


def test_第二条b_i388跟治好的那5屏差在哪():
    """`M` 治好的那 5 屏**团里都有同一场录音**；i=388 **五场全不同** —— 所以 `M` 拦不住。"""
    rows = {r["i"]: r for r in _rows("p98-i388-18")}
    治好的 = (101, 273, 337, 427, 575)
    for i in 治好的:
        assert rows[i]["判"] == "假"
        assert rows[i]["团里有没有同一场录音"] == "同", f"i={i} 该是同一场录音撑起来的"
    assert rows[388]["判"] == "假" and rows[388]["团里有没有同一场录音"] == "异"
    assert rows[388]["团K"] == 5, "i=388 的团是 5 条（比治好的那五屏都大）"
    # 两条轴同时接近退化：主角物 + 整库最宽的话题码
    assert rows[388]["共同obj"] == "手环"
    assert rows[388]["共同topic"] == "work_product_design"
    assert rows[388]["topicDF%"] == max(r["topicDF%"] for r in rows.values()
                                        if r["user"] == "terrence")
    assert "跟一个真的族长得一模一样" in _meta("p98-i388-18")["根因"]


def test_第二条c_话题码那条轴第一格就废():
    """**同一个共同 topic 码上一真一假** ⇒ 这条轴从定义上分不开它们。"""
    rows = {r["i"]: r for r in _rows("p98-i388-18")}
    assert rows[388]["共同topic"] == rows[677]["共同topic"] == "work_product_design"
    assert (rows[388]["判"], rows[677]["判"]) == ("假", "真")
    assert rows[388]["topicDF%"] == rows[677]["topicDF%"] == 15.45
    # `work` 上也是一真一假
    assert rows[273]["共同topic"] == rows[575]["共同topic"] == rows[698]["共同topic"] == "work"
    assert (rows[273]["判"], rows[575]["判"], rows[698]["判"]) == ("假", "假", "真")


def test_第二条d_obj那条轴也分不开():
    rows = [r for r in _rows("p98-i388-18")]
    真 = sorted(r["objDF%"] for r in rows if r["判"] == "真")
    假 = sorted(r["objDF%"] for r in rows if r["判"] == "假")
    # **两头套住**：真的那批的区间把假的那批整个包在里面（0.02 `slide` … 20.0 `battery`
    # vs 0.02 `chip` … 0.49 `手环`）⇒ **不管往哪个方向切，都会切掉真的**。
    assert 真[0] <= 假[0] and 真[-1] > 假[-1], "假的那批整个套在真的那批里面"
    for cut in (0.1, 0.3, 0.5, 1.0, 5.0):
        assert sum(1 for v in 真 if v < cut) > 0 or sum(1 for v in 假 if v >= cut) > 0, \
            f"门槛 {cut} 不该分得开（分得开就是这一条判错了）"
    # 尤其是 i=388 那个 0.49：它上面和下面都有人读「真」的
    assert any(v < 0.49 for v in 真) and any(v > 0.49 for v in 真)


def test_第二条e_第四条路量到哪一格判不走():
    """**「没有第四条路」也是结论，但要说清卡在哪一格**——这儿卡在**没有留出集**。"""
    rows = {r["i"]: r for r in _rows("p98-i388-18")}
    真 = sorted(r["字面包含mean"] for r in rows.values() if r["判"] == "真")
    假 = sorted(r["字面包含mean"] for r in rows.values() if r["判"] == "假")
    assert rows[388]["字面包含mean"] == 0.060
    # 门槛 0.07–0.10 上：真活 12/12、假活 1/6（**比 `M` 还好**）
    for cut in (0.07, 0.08, 0.09, 0.10):
        assert sum(1 for v in 真 if v >= cut) == 12
        assert sum(1 for v in 假 if v >= cut) == 1
    # ⚠️ **但两头是重叠的**，而且缝只有一屏宽
    assert max(假) > min(真), "假的那批最高（i=337 0.160）比真的那批最低（i=677 0.103）还高"
    assert 真[0] == 0.103 and max(假) == 0.160
    gap = [v for v in sorted(真 + 假) if 0.060 < v < 0.103]
    assert gap == [], "0.060 和 0.103 之间一屏都没有 —— 那条缝只有一屏宽"
    meta = _meta("p98-i388-18")
    assert "没有留出集" in meta["第四条路"]
    assert "这一批不走" in meta["第四条路"]
    assert "它不认字面" in FD.__doc__, "第 ⑥ 格那句话还在 —— 走字面那条路会改变这把尺是什么"


# ═══ 第三条：「都堵死」核了 + 第三条路 ═════════════════════════════════════

def test_第三条a_三条路都记着而且各有各卡的那一格():
    rows = _rows("p98-topicroad-3")
    assert len(rows) == 3
    assert {r["labeled_by"] for r in rows} == {"P98"}
    assert sorted(r["n"] for r in rows) == [0, 1, 2]
    by = {r["n"]: r for r in rows}
    assert by[0]["判"].startswith("堵死") and by[1]["判"].startswith("堵死")
    assert by[2]["判"].startswith("**活着")
    for r in rows:
        assert len(r["为什么"]) >= 80, f"第 {r['n']} 条路的理由太短"


def test_第三条b_两条老路是重数过的不是抄的():
    """**引用台账的数之前先重数**：单轴 `obj` P94 记的是小库 10 屏的读数，
    全库重数是 41 屏、还欠 23 屏人读。"""
    by = {r["n"]: r for r in _rows("p98-topicroad-3")}
    assert "全库重数" in by[0]["为什么"]
    assert "41 屏" in by[0]["为什么"] and "23 屏一屏都没人读过" in by[0]["为什么"]
    assert "3.4 倍" in by[0]["为什么"]
    # 共现那条：方向是反的，而且有机制
    assert "方向是反的" in by[1]["为什么"]
    assert "抽取时二选一" in by[1]["为什么"]
    assert "0.025" in by[1]["为什么"] and "排第 201" in by[1]["为什么"]


def test_第三条c_第三条路走到第三格而且说清了为什么不走():
    by = {r["n"]: r for r in _rows("p98-topicroad-3")}
    why = by[2]["为什么"]
    assert "cos 0.778" in why and "14196" in why
    assert "团 3 → 4" in why, "得走到「那一族真的打满 4」那一格"
    assert "cut 0.77 是拿目标那一对反推的" in why and "没有留出集" in why
    assert "26 对" in why and "一对都没人读过" in why
    # ⚠️ **别拿跟被测尺共用一条轴的东西当验收尺**：这条路改的正是它自己被判好坏的那个数
    assert "改动那个用来判它好不好的数" in why
    # 那一句「只有两条路」的更正并排写在尺身上
    assert "修团只有两条路，两条都堵死" in FD.__doc__, "P96 的原话不许抹掉"
    assert "但「**只有两条**」不成立" in FD.__doc__


def test_第三条d_这一条跟P94量entities那件事不是同一个问题():
    """⚠️ 任务书点名的那一格：P94 量 `entities`/`kind`/`who`「方向反着」，
    量的是「**一屏里这两条事实像不像**」；这一条问的是「**两个话题码是不是同一件事**」。
    **两个问题**——所以 P94 那个读数**不能直接搬过来**，得自己量。"""
    meta = _meta("p98-topicroad-3")
    assert "不是** P94 量" in meta["什么"] or "不是」P94" in meta["什么"] or \
        "**不是**" in meta["什么"]
    assert "是两个问题，别混" in meta["什么"]
    # P94 那张「八条轴并排」的表还在尺身上（它答的是另一个问题）
    assert "库里所有够得着的轴，在同一批正反例上并排摆了一遍" in FD.__doc__
    # 而这一批自己量了三条画像轴，只有 `obj` 那条够得着
    assert "只有 `obj` 这条轴够得着" in {r["n"]: r for r in _rows("p98-topicroad-3")}[2]["为什么"]


# ═══ 第四条：量具自检 + 登记 + 「没接进产品」 ══════════════════════════════

def test_第四条a_cf_shape自己多核三件事():
    """⚠️ **同一个字面量可能有第二 / 第三份**（这一课第六次咬人：这一批新加的
    `_P96` / `_READ_P96` 让 `count("EXPECT_SHAPE_HALF")` 从 3 变 7）。"""
    main = inspect.getsource(RR.main)
    assert len(re.findall(r"EXPECT_SHAPE_HALF(?!_)", main)) == 1
    assert len(re.findall(r"EXPECT_SHAPE_NOHALF(?!_)", main)) == 3
    assert main.count("EXPECT_SHAPE_NOHALF_BIGLIB") == 1
    assert main.count("EXPECT_SHAPE_COVER7") == 1
    for guard in ('if not set(g["head"]) < set(g["nohalf"]):',
                  'if set(g["head"]) | set(g["half"]) != set(g["nohalf"]):',
                  'if not set(EXPECT_SHAPE_HALF_P96) <= set(g["nohalf"]):'):
        assert main.count(guard) == 1, f"`--cf-shape` 的新自检少了一条（或多了一份）：{guard}"
    src = inspect.getsource(RR.cf_shape)
    assert src.count('"nohalf"') == 1 and src.count('"cover7"') == 1
    # ⚠️ 这个名字在 `cf_shape` 里**有两份**（注释里 1 份 + 代码里 1 份）——
    # 光数 1 会当场红，光数 2 又挡不住「注释还在、代码没了」。两条一起断。
    assert src.count("EXPECT_SHAPE_HALF_P96") == 2
    assert src.count("head[i][\"cover\"] for i in EXPECT_SHAPE_HALF_P96") == 1, \
        "`cover7` 那一档得对着老那 7 屏取"


def test_第四条b_新钉的数都进了floor_ruler():
    reg = FR.REGISTRY if hasattr(FR, "REGISTRY") else FR.ENTRIES
    for name in ("EXPECT_SHAPE_HALF_P96", "EXPECT_SHAPE_HALF_READ_P96",
                 "EXPECT_SHAPE_COVER7", "EXPECT_SHAPE_NOHALF_BIGLIB",
                 "EXPECT_SHAPE_HALF", "EXPECT_SHAPE_HALF_READ", "EXPECT_SHAPE_NOHALF"):
        key = ("backend/scripts/recall_ruler.py", name)
        assert key in reg, f"{name} 没登记"
        why = reg[key][2]
        assert len(why) > 40, f"{name} 的「一动去重读什么」写得太短：{why!r}"
        assert "重读" in why or "去读" in why, f"{name} 的 why 没说要去读什么：{why!r}"


def test_第四条c_两个floor抬到了本worktree的真值():
    assert FR.REGISTRY_SIZE_FLOOR == len(FR.REGISTRY) == 125
    assert FR.CHECKED_COUNT_FLOOR == 137


def test_第四条d_老标注的分母一个没动():
    assert len(_rows("p34-sample47")) == 47
    assert len(_rows("p94-shape-18")) == 18, "P94 那 18 条标注不许动"
    assert len(_rows("p96-halfdoor-7")) == 7, "P96 那 7 条标注不许动"
    assert len(_rows("p96-noobj-42")) == 42
    assert len(_rows("p96-i641-2")) == 2


def test_第四条e_产品逻辑一个字节没改():
    """这把尺**还是没接进产品**：`app/` 底下除了它自己，没有任何一处 import 它。"""
    hits = []
    for p in (REPO / "backend" / "app").rglob("*.py"):
        if p.name == "fact_distinct.py":
            continue
        if "fact_distinct" in p.read_text(encoding="utf-8"):
            hits.append(str(p.relative_to(REPO)))
    assert not hits, f"产品里有人 import 了这把尺：{hits}"


def test_第四条f_十组正反例上换门一组都没弄坏():
    """换门**不许**把十组正反例弄坏——正例 ≥ 期望、反例 < 期望。"""
    for name, facts, want in (POS8, POS7, POSK, POST):
        sh = FD.screen_shape(facts)
        assert sh["family"] >= want, f"{name} 该 ≥{want}"
        assert sh["flagged"], f"{name} 是正例，该判「是」"
    for name, facts, want in (NEG7, NEGH, NEGA, NEGP, NEGK, NEGC):
        sh = FD.screen_shape(facts)
        assert sh["family"] < want, f"{name} 该 <{want}"
        assert not sh["flagged"], f"{name} 是反例，该判「不是」"


def test_第四条g_新门那个口子两头都写在尺身上():
    """**它答不了什么**得写在尺自己身上，而且**两头都要有实拍**（P72 那条规矩）。"""
    doc = FD.__doc__
    assert "**会多放**" in doc and "**会少放**" in doc
    assert "test_p94::第二条b" in doc, "「会多放」那一头的实拍得点名"
    assert "**实拍在 i=590**" in doc, "「会少放」那一头的实拍得点名"
    assert "**「没量到」不等于「不会有」**" in doc
    assert "P98 把这条依赖加深了一格" in doc, "`topics` 那条禁令得跟着更硬"
