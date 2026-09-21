"""P96：**治 P94 留下的三格**——大库那 6 屏假阳性 · `obj` 缺的那一头 · i=641。

这一批**产品逻辑一个字节没改**（动的是那把没接进产品的尺、一支量具读数、
一份闸、三组标注、七条登记）。

① **先核了「稀疏化那条量法能不能直接量 `obj`」——判「不能」**（`第一条*`）。
   P75/P88 那条 `spread = k / E(n)` 接得上（只换一个「谁算命中」的口，数学一行不用抄），
   **但数在读过的那 18 屏上正反例完全重叠，而且方向是反的**：
   P94 点名的泛 obj **`广告` 打 0.361（全场最低 = 最不泛）**，而人读「真」的 `product` 打 0.752。
   ⇒ 卡在 P92 那句话的同一格换了个轴：**「不泛」≠「挂它的两条事实说的是同一件事」。**
   **没造第二把尺**，仓库里一个字节都没留。

② **判据从 `K` 换成 `M`**（`obj∩ ∧ topics∩ **∧ 不同 unit**，`第二条*`）。
   P94 量过 `M`、判「不要」，用的分母是**十组手挑的正反例**（`K`/`M` 在那十组上都全对）。
   P96 换成**读过的那 18 屏**重量：**6 屏假阳性治好 5 屏**（`chip`/`agent`/`广告` 那三对），
   代价是**丢 1 屏真的（i=94）** + **i=388（`手环`）没治好** + **当 en060 量具钝了一格**
   （翻 3 屏 → 2 屏）。大库假阳性 **50% → 16.7%**。

③ **441 屏「瞎掉」拆开了**（`第三条*`）：P94 ⑤-2 把它整笔归给「43.3% 的事实没有 `obj`」。
   拆开是 **空屏 419 / 无 topics 3 / 真能归到 obj 头上的 19 屏**。
   ⇒ **补抽取那一头的上限是 19 屏（2.5%），不是 441 屏。** 那 43.3% 本身也是三笔账
   （甲 881 / 乙 667 / 丙 7288），42 条人读下来**只有 24 条是真漏了**。**判：不补。**

④ **半屏那道门量清了**（`第四条*`）：P94 ⑤ 那一刀在**十组手挑的正反例**上量到
   「一格都没承重」。换成**全库 765 屏**它拦着 **7 屏**——**1 屏该拦 / 6 屏该放**。
   ⇒ **一条在正反例上没承重的门 ≠ 一条永远绿的闸。** 这一批**没动它**（一刀只动一处）。

⑤ **i=641 更正了**（`第五条*`）：P94 ⑤-4 把「团 3 / 8 格」记成 HEAD 的召回缺陷。
   重数下来 **HEAD 上 i=641 是团 2，人读也该判「不是」，尺子判对了**；
   那个团 3 是 **en060** 那一屏的。**别把反事实里的伤亡记成 HEAD 缺陷。**
   而 en060 那一屏漏在**团**上不在门上：`topics` 把同一族劈开了
   （`ai_memory_os` vs `memory_powered_intelligence`）。

出身：worktree HEAD `9bdc738` · `scripts/recall_ruler.py` 765 条 ·
`notes=482篇/321250字/47dcc54be60aa4f2` · `terrence=11429185B/403a1183`。
基线**自己量的**：后端带 `KITE_DATA_DIR` **3354 / 0 skipped**、前端 **101 文件 / 931 条**、
`floor_ruler` 开工 **看着 11 份 / 登记 114 条 / 共核 126 条 / 落后 0 / 对不上 0**。

⚠️ **四栏对这一批也是瞎的**——产品逻辑一个字节没改。说明事的是 `--cf-shape` 那一组数、
`p96-halfdoor-7` / `p96-noobj-42` / `p96-i641-2` 三组人读、和这份闸。
⚠️ **这份闸不要真语料**（同 `test_p94`）：十组正反例的轴是从真语料冻下来的字面表，
跟语料对不对得上由 `--cf-shape` 在真语料上那一趟负责。
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


def _K(a, b):
    """**P94 那一版判据（两条轴）**，冻在这儿当镜子。"""
    return bool(set(a.obj) & set(b.obj)) and bool(set(a.topics) & set(b.topics))


# ═══ 第一条：稀疏化那条量法量不了 `obj` ═══════════════════════════════════

def test_第一条a_两头完全重叠而且方向是反的():
    """`EXPECT_SHAPE_OBJFACE` = ((真的那批 min, max), (假的那批 min, max))。

    **判「不能用」靠的就是这两对**：区间重叠 ⇒ 没有任何一个门槛分得开；
    而且**全场最低分落在「假」那一头**（`广告` 0.361）⇒ 方向还是反的。
    """
    (tlo, thi), (flo, fhi) = RR.EXPECT_SHAPE_OBJFACE
    assert tlo < thi and flo < fhi
    # 区间真的重叠（不是「挨着」）：假的上沿比真的上沿还高，假的下沿比真的下沿还低
    assert fhi > thi, "人读『假』的那一头得分最高的比人读『真』的最高的还高"
    assert flo < tlo, "人读『假』的那一头得分最低的比人读『真』的最低的还低"
    assert flo == min(tlo, thi, flo, fhi), "全场最低分必须落在『假』那一头（`广告` 0.361）"
    # 真要拿一个门槛去分，随便取哪个都会切错——挑两个具体门槛点名核
    for th in (0.5, 0.6, 0.7, 0.75):
        assert not (thi < th <= flo or fhi < th <= tlo), f"门槛 {th} 不该分得开（分得开就是这一条判错了）"


def test_第一条b_没在仓库里留下第二把泛尺():
    """**能用就别再造一把**（任务书那一句）。判「不能用」之后，
    那个 `ObjPickFace` 只活在 scratch 里——仓库里**一个字节都没留**。"""
    bad = []
    for p in list((REPO / "backend" / "app").rglob("*.py")) + list((REPO / "backend" / "scripts").rglob("*.py")):
        t = p.read_text(encoding="utf-8")
        # ⚠️ 核的是**定义**，不是提名字：`fact_distinct` 的文件头**正文里**
        # 写着「那个 `ObjPickFace` 只活在 scratch 里」，那一句得留着。
        for m in re.finditer(r"^\s*class\s+(\w*Obj\w*Face|\w*ObjSpread\w*)\b", t, re.M):
            bad.append(f"{p.relative_to(REPO)}:{m.group(1)}")
    assert not bad, f"仓库里留下了第二把泛尺：{bad}"
    # 反过来：那一句「没造第二把尺」得真的写在尺身上
    assert "只活在 scratch 里" in FD.__doc__


def test_第一条c_那条量法为什么量不了写在尺自己身上():
    """照 P72 的规矩：**判「不能用」的理由写在尺自己身上，一条一条点名核**。"""
    doc = FD.__doc__
    for frag in ("稀疏化那条量法量不了 `obj`",
                 "obj 码是**归一化过的英文码**",
                 "**两头完全重叠**",
                 "`SPREAD_MIN_HITS = 20`",
                 "**没造第二把尺**"):
        assert frag in doc, f"第 ⑦-a 格少了一条：{frag}"


# ═══ 第二条：判据换成 `M` ════════════════════════════════════════════════

def test_第二条a_same_thing今天是三条轴():
    """**逐字核**那一条新轴在，而且只有一份。"""
    src = inspect.getsource(FD.same_thing)
    body = src.split('"""', 2)[2]
    assert body.count("and a.unit != b.unit") == 1, "「不同 unit」那一条不见了或者有第二份"
    assert body.count("set(a.obj) & set(b.obj)") == 1
    assert body.count("set(a.topics) & set(b.topics)") == 1
    # 三条都得真的承重：一条一条摘掉看会不会多放行
    a, b = _Fact("1458F12"), _Fact("1458F17")   # 同 obj 同 topics，**同一场录音**
    assert set(a.obj) & set(b.obj) and set(a.topics) & set(b.topics) and a.unit == b.unit
    assert _K(a, b) and not FD.same_thing(a, b), "同一场录音那两条，`K` 说同、`M` 说不同"


def test_第二条b_M严格比K窄():
    """`M = K ∧ …` ⇒ 在**任何**一组事实上 `M` 的团都不可能比 `K` 大。
    十组正反例一组一组核（不是只核一组）。"""
    for name, facts, _w in (POS8, POS7, POSK, POST, NEG7, NEGH, NEGA, NEGP, NEGK, NEGC):
        k, m = _clique(facts, _K), _clique(facts, FD.same_thing)
        assert m <= k, f"{name}: `M` 团 {m} > `K` 团 {k} —— 那 `M` 就不是 `K` 的收窄版"


def test_第二条c_十组正反例上M仍然全对():
    """换判据**不许**把十组正反例弄坏——正例 ≥ 期望、反例 < 期望。"""
    for name, facts, want in (POS8, POS7, POSK, POST):
        assert _clique(facts, FD.same_thing) >= want, f"{name} 该 ≥{want}"
    for name, facts, want in (NEG7, NEGH, NEGA, NEGP, NEGK, NEGC):
        assert _clique(facts, FD.same_thing) < want, f"{name} 该 <{want}"


def test_第二条d_治好的和没治好的都点名():
    """**「治好 5/6」和「治好 6/6」是两句话**，差的那一屏得点名写着。"""
    assert RR.EXPECT_SHAPE_READ_BIGLIB == (5, 1)
    assert RR.EXPECT_SHAPE_LEFTOVER == (388,)
    # 剩下那一屏的形状写在尺身上（五场不同录音 ⇒ 不同 unit 那条轴拦不住）
    assert "i=388（`手环`）没治好" in FD.__doc__
    assert "出自五场不同的录音" in FD.__doc__
    # 代价那三条一条一条核
    for frag in ("**i=94 丢了**", "**i=388（`手环`）没治好**", "**当 en060 量具那一头钝了一格**"):
        assert frag in FD.__doc__, f"换 `M` 的代价少了一条：{frag}"
    # ⚠️ **那个口子的措辞也得钉着**（突变刀 ⑥′ 打的就是这一格）：
    # `M` 的代价是「同一场录音里的重复说法一律放行」——写反了就等于把这条尺的
    # 已知口子说成了它拦得住的东西。
    assert "* **同一场录音里的重复说法它一律放行**" in FD.__doc__


def test_第二条e_换判据不该动measurable决的那两个数():
    """`TOTAL` / `BLIND` 是 `measurable` 决的，**换 `same_thing` 不该动它们**。
    这是这一刀的自检：它俩要是跟着动了，说明这一刀没落在该落的地方。"""
    assert RR.EXPECT_SHAPE_TOTAL == 175 and RR.EXPECT_SHAPE_BLIND == 441
    src = inspect.getsource(FD.measurable)
    assert "unit" not in src, "`measurable` 不该沾 unit —— 那一刀只该落在 `same_thing` 上"


def test_第二条f_那一族跨七场录音所以M不伤它():
    """`M` 不是新旋钮，它是 P94 ② 那条发现的**正写法**：
    「同一句话的多种说法」正好长在不同的人 / 场合 / 体裁上。"""
    fam = POS7[1]
    assert len({f.unit for f in fam}) == len(fam) == 7, "那一族七条出自七场各不相同的录音"
    assert _clique(fam, FD.same_thing) == _clique(fam, _K) == 4, "所以 `M` 在它身上一格都没砍"


# ═══ 第三条：441 屏拆账 + `obj` 缺的那一头 ═══════════════════════════════

def test_第三条a_拆账加起来等于原来那个数():
    """**一个数是不是两笔账混成一笔，先拆开看**——拆完得能加回去。"""
    assert RR.EXPECT_SHAPE_BLIND_WHY == (419, 3, 19)
    assert sum(RR.EXPECT_SHAPE_BLIND_WHY) == RR.EXPECT_SHAPE_BLIND
    空, 无topics, 只缺obj = RR.EXPECT_SHAPE_BLIND_WHY
    assert 空 / RR.EXPECT_SHAPE_BLIND > 0.9, "九成以上是空屏 —— 跟 obj 一点关系没有"
    assert 只缺obj / RR.EXPECT_SHAPE_BLIND < 0.05, "真能归到 obj 头上的不到 5%"


def test_第三条b_补抽取的上限点名钉着():
    """**「做不出来」也是结论，但要给出那个上限的数。**"""
    assert RR.EXPECT_SHAPE_BLIND_WHY[2] == 19
    meta = _meta("p96-noobj-42")
    assert "补抽取的上限是 19 屏，不是 441 屏" in meta["⚠️ 别拿它当补抽取的理由"]
    assert "**补抽取那一头」的上限是 19 屏**" in FD.__doc__ or "的上限是 19 屏" in FD.__doc__


def test_第三条c_那42条读完不重不漏而且三档都有():
    rows = _rows("p96-noobj-42")
    assert len(rows) == 42, f"p96-noobj-42 应该 42 条，实际 {len(rows)}"
    assert {r["labeled_by"] for r in rows} == {"P96"}
    assert sorted(r["n"] for r in rows) == list(range(42)), "42 条得不重不漏"
    assert len({r["id"] for r in rows}) == 42, "42 个 id 不许重"
    c = {}
    for r in rows:
        c[r["判"]] = c.get(r["判"], 0) + 1
    assert c == {"漏": 24, "本来就没有对象": 11, "只有代词或ASR碎片": 7}, c
    assert sum(c.values()) == 42
    # 每条都得写清「为什么」
    for r in rows:
        assert len(r["为什么"]) >= 6, f"n={r['n']} 的理由太短：{r['为什么']!r}"


def test_第三条d_那43点3不是这把尺瞎掉的原因():
    """⚠️ **P94 ⑤-2 那句话方向对、量级错了两个数量级**，更正得并排写着。"""
    doc = FD.__doc__
    # P94 原话还在（更正要并排写，不许抹掉）
    # ⚠️ **这句话在尺身上有两份**：P94 ⑤-2 的原话 + P96 ⑦-c 引用它那一份。
    # 只写 `in doc` 的话，摘掉任意一份都照样绿 —— **这一课第五次咬人**
    # （P88/P90/P92/P94 各一次，P96 这一次是突变刀的锚点唯一性检查抓到的）。
    assert doc.count("441/765 屏上一个字都说不出来") == 2, \
        "这句话该正好两份：P94 ⑤-2 的原话，和 P96 ⑦-c 引用它那一份"
    # P96 的更正也在
    assert "**441 屏「瞎掉」是两笔账混成一笔**" in doc
    assert "方向对、量级错了两个数量级" in doc


# ═══ 第四条：半屏那道门 ══════════════════════════════════════════════════

def test_第四条a_它在全库上真拦东西():
    """**一条在正反例上一格都没承重的门，跟一条永远绿的闸是同一族**——
    这一条就是那个反例：**它在十组手挑的正反例上没承重，在全库上拦着 7 屏**。"""
    assert RR.EXPECT_SHAPE_HALF == (65, 587, 588, 590, 595, 596, 597)
    assert len(RR.EXPECT_SHAPE_HALF) == 7
    assert RR.EXPECT_SHAPE_HALF_READ == (6, 1)
    assert sum(RR.EXPECT_SHAPE_HALF_READ) == len(RR.EXPECT_SHAPE_HALF)
    # 判「是」的那 12 屏和被门拦下的那 7 屏**必须不相交**
    assert not set(RR.EXPECT_SHAPE_HALF) & {22, 40, 307, 388, 591, 637, 638, 655, 656, 657, 677, 698}
    # 摘掉门的读数：19 = 12 + 7，真 17 = 11 + 6，假 2 = 1 + 1
    n, t, f = RR.EXPECT_SHAPE_NOHALF
    assert n == RR.EXPECT_SHAPE_HEAD + len(RR.EXPECT_SHAPE_HALF) == 19
    assert (t, f) == (RR.EXPECT_SHAPE_READ[0] + RR.EXPECT_SHAPE_HALF_READ[0],
                      RR.EXPECT_SHAPE_READ[1] + RR.EXPECT_SHAPE_HALF_READ[1]) == (17, 2)


def test_第四条b_这一批没动那道门():
    """**一刀只动一处**：这一批动的是 `same_thing`，半屏那道门**逐字没动**。"""
    src = inspect.getsource(FD.screen_shape)
    assert "len(fam) * 2 >= n" in src, "半屏那道门不见了"
    assert src.count("len(fam) * 2 >= n") == 1
    assert "FAMILY_MIN" in src and FD.FAMILY_MIN == 3
    assert "**这一批没动它**" in FD.__doc__


def test_第四条c_那7屏读完不重不漏():
    rows = _rows("p96-halfdoor-7")
    assert len(rows) == 7
    assert {r["labeled_by"] for r in rows} == {"P96"}
    assert tuple(sorted(r["i"] for r in rows)) == RR.EXPECT_SHAPE_HALF
    放 = [r for r in rows if r["判"] == "该放"]
    拦 = [r for r in rows if r["判"] == "该拦"]
    assert (len(放), len(拦)) == RR.EXPECT_SHAPE_HALF_READ
    assert [r["i"] for r in 拦] == [65], "该拦的只有 i=65 那一屏"
    # 七屏的团都正好卡在「≥3 但不到半屏」上 —— 不然它们根本不该在这一组里
    for r in rows:
        assert r["团"] >= FD.FAMILY_MIN
        assert r["团"] * 2 < r["量得了"], f"i={r['i']} 不是被半屏拦下的"
    _meta("p96-halfdoor-7")


def test_第四条d_相邻段落那两组在标注里点了名():
    """⚠️ **7 屏不是 7 笔独立的账**（587/588 一组、595/596/597 一组）。"""
    rows = {r["i"]: r for r in _rows("p96-halfdoor-7")}
    assert "相邻段落" in rows[588]["为什么"]
    assert "相邻段落" in rows[596]["为什么"] and "相邻段落" in rows[597]["为什么"]


# ═══ 第五条：i=641 更正 ══════════════════════════════════════════════════

def test_第五条a_两个分支分开记着():
    rows = _rows("p96-i641-2")
    assert len(rows) == 2
    by = {r["分支"]: r for r in rows}
    assert set(by) == {"HEAD", "en060"}
    assert by["HEAD"]["判"] == "不是" and by["HEAD"]["团K"] == 2 and by["HEAD"]["团M"] == 1
    assert by["en060"]["判"] == "是" and by["en060"]["团K"] == 3 and by["en060"]["团M"] == 3
    assert all(r["i"] == 641 and r["量得了"] == 8 for r in rows)
    meta = _meta("p96-i641-2")
    assert "不是 HEAD 的" in meta["什么"]
    assert "不在半屏那道门上，在**团**上" in meta["漏在哪儿"]


def test_第五条b_i641在en060真的变了的那11条里():
    """**反例得真的落在被测分支里**：i=641 得是 en060 动过的屏，
    不然「HEAD 和 en060 两屏不一样」这句话就没有来源。"""
    assert 641 in RR.EXPECT_CF_GATES_EN060_IDX
    # 而它**不在**翻成「是」的那批里 —— 它正是「en060 造了灌屏但尺子没标出来」的那一格
    assert 641 not in RR.EXPECT_SHAPE_FLIP_ON
    assert 641 not in RR.EXPECT_SHAPE_FLIP_ON_K, "`K` 那一版也没标出来 —— 换判据不是原因"


def test_第五条c_更正并排写在尺身上():
    doc = FD.__doc__
    assert "`i=641` 人读判「是」" in doc, "P94 的原话不许抹掉"
    assert "**i=641：HEAD 上判「不是」是对的**" in doc
    assert "别把反事实里的伤亡记成 HEAD 缺陷" in doc
    assert "**该修的是团，不是门**" in doc


# ═══ 第六条：量具自己的自检 + 登记 ════════════════════════════════════════

def test_第六条a_cf_shape自己核三件事():
    """⚠️ **同一个字面量可能有第二 / 第三份**（P88/P90/P92/P94 连着四批都咬过）——
    **一份一份点名核**，不许只断言「这个名字在源码里出现过」。"""
    main = inspect.getsource(RR.main)
    # `EXPECT_SHAPE_HALF` 在 `main` 里出现 3 次，但**只有 1 次是这个常数本身**，
    # 另外 2 次是 `EXPECT_SHAPE_HALF_READ`。光数 3 会被 `_READ` 那两份骗过去。
    assert main.count("EXPECT_SHAPE_HALF") == 3
    assert main.count("EXPECT_SHAPE_HALF_READ") == 2
    assert len(re.findall(r"EXPECT_SHAPE_HALF(?!_)", main)) == 1, \
        "`main` 里 `EXPECT_SHAPE_HALF` 本身该正好一份"
    assert main.count("EXPECT_SHAPE_BLIND_WHY") == 1
    for guard in ('if sum(g["blind_why"]) + g["total"] < 0 or sum(g["blind_why"]) != g["blind"]:',
                  'if set(g["head"]) & set(g["half"]):',
                  'if set(g["flip_on"]) - set(EXPECT_CF_GATES_EN060_IDX):'):
        assert main.count(guard) == 1, f"`--cf-shape` 的自检少了一条（或多了一份）：{guard}"
    src = inspect.getsource(RR.cf_shape)
    assert src.count('"half"') == 1 and src.count('"blind_why"') == 1
    assert src.count("_swap_run") == 2, "换 `common_term` 得走 `_swap_run` 那一份实现（签名一次 + 调一次）"
    assert "EXPECT_CF_GATES_PURGES" in src, "得断言缓存清了两次，不然右边那趟量的还是 HEAD 的屏"


def test_第六条b_新钉的数都进了floor_ruler():
    reg = FR.REGISTRY if hasattr(FR, "REGISTRY") else FR.ENTRIES
    for name in ("EXPECT_SHAPE_BLIND_WHY", "EXPECT_SHAPE_FLIP_ON_K", "EXPECT_SHAPE_LEFTOVER",
                 "EXPECT_SHAPE_HALF", "EXPECT_SHAPE_HALF_READ", "EXPECT_SHAPE_NOHALF",
                 "EXPECT_SHAPE_OBJFACE"):
        key = ("backend/scripts/recall_ruler.py", name)
        assert key in reg, f"{name} 没登记"
        why = reg[key][2]
        assert len(why) > 40, f"{name} 的「一动去重读什么」写得太短：{why!r}"
        assert "重读" in why or "去读" in why, f"{name} 的 why 没说要去读什么：{why!r}"


def test_第六条c_两个floor抬到了本worktree的真值():
    """**加了登记就同时把那两个 floor 抬到真值**（`test_p90::第四条b` 钉的是「== 真值」本身）。"""
    assert FR.REGISTRY_SIZE_FLOOR == len(FR.REGISTRY) == 121
    assert FR.CHECKED_COUNT_FLOOR == 133


def test_第六条d_47条那把尺的分母一个没动():
    assert len(_rows("p34-sample47")) == 47
    assert len(_rows("p94-shape-18")) == 18, "P94 那 18 条标注不许动"


def test_第六条e_产品逻辑一个字节没改():
    """这把尺**还是没接进产品**：`app/` 底下除了它自己，没有任何一处 import 它。"""
    hits = []
    for p in (REPO / "backend" / "app").rglob("*.py"):
        if p.name == "fact_distinct.py":
            continue
        if "fact_distinct" in p.read_text(encoding="utf-8"):
            hits.append(str(p.relative_to(REPO)))
    assert not hits, f"产品里有人 import 了这把尺：{hits}"
