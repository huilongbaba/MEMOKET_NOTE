"""P90：**i=607 查清了（判「不改」，更正 P88 ①）** + **`WHO_GENERIC=0.85` 的留出集造出来了**
+ **拆汉字闸那条路量完了（判「不通」）**。这一批**产品逻辑一个字节没改**。

① **`i=607` 不是「没治好」，它在 HEAD 上是好的**（更正 P88 ①，**并排写在
   `kb/topic_face` 文件头第 ⑧ 格**）。
   实测：HEAD 上 i=607 召回 **1 条**（`terrence-1431-12F5`）。
   它跟 i=293 **确实是同一条链**（`_cjk_terms` 那 16 个名额、三换三、`span` 断成 `pair`），
   但**方向相反**——i=293 是这条轴一开口就治好的，i=607 是这条轴一开口就打坏的。
   而 P88 那句「这一刀够不着大库」**说反了**：`WhoFace` 在大库上 `usable=False`
   → `generic()` 回 `None` → `who.generic(t) is not False` 为 `True`
   → **判「是 common」**，也就是**把话题面那一问整个按住**。
   全库实测：拆掉库大小闸、主语面照问 → **765 条一条都不变**；
   ⚠️ 再把 `SPEAKER_TAG_MAX` 摘掉 → **24 条变、全在 `terrence`、i=607 1 → 0**。
   **⇒ 大库上的安全来自「那个库的 `who` 恰好不是主语」这个偶然，不是来自这条轴判得准。**

② **`WHO_GENERIC = 0.85` 的留出集**（收 P88 ②）：两份、两个库、**204 条人标**。
   顺序是 P77 那条：**先造盲标单（只有词 + 命中它的事实，一个分数都没有）→ 标完 → 才揭晓**；
   **验的是「判不泛」那一头**（P77 那份验的是反着那一头）。
   A 栏（88，= 产品今天真问到的那一堆）：0.85 这一档 **挡错 0 / 假捞回 64.1%**；
   [0.80, 0.90] 整段挡错都是 **0**——**P88 那个平台复现了，不再是两个串顶着**。
   B 栏（116，**真盲**）：假捞回率每一档都在 66.7%–88.5%，**没有工作点**。
   ⚠️ **A 栏的盲性是造它的人自己弄坏的**，这件事写在 `_meta` 里，闸盯着它别被删掉。
   **判：不改 0.85**（[0.80,0.90] 产出逐条一样 = 旋钮动完产出一样）。

③ **拆汉字闸不通**（收 P88 ③）：全库变 6 条，逐条读完 **变好 0 / 中性 2 / 变差 4**
   （`p90-engate-6`）。**P88 ③ 那句预测实测对了**——`ai` 主语面 .819 < 0.85 被放进来。
   卡在两格：门槛（.819 落在汉字那一半的平台里，一个门槛服不了两个 population）
   和轴（**英文那半第一份留出集** `p90-holdout-en-60` 量出主语面在英文串上**没有信号**）。

出身：worktree HEAD `55166b7` · `scripts/recall_ruler.py` 765 条 ·
`notes=482篇/321250字/47dcc54be60aa4f2` · `terrence=11429185B/403a1183` ·
`terrence-rewrite=6594533B/8b6ba3bb`。
基线自己量的：后端带 `KITE_DATA_DIR` **3294 / 0 skipped**、不带 **3263 / 31 skipped**、
前端 **98 文件 / 883 条**。

⚠️ **四栏对这一批是瞎的**——这一批产品逻辑一个字节没改，四栏当然全绿。
说明事的是 `--cf-gates` 那十个数、`p90-engate-6` 那 6 条、和三份留出集里的 204 条人标。
"""

from __future__ import annotations

import inspect
import json
import pathlib
from collections import Counter

import pytest

from app.database.kb import topic_face as TF
from app.database.kite import kite_memory as KM
from scripts import floor_ruler as FR
from scripts import recall_ruler as RR

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "memory_sample.jsonl"

HAS_DB = (ROOT / "backend" / "data" / "notes.sqlite3").exists()
HAS_CORPUS = (RR.data_dir() / "terrence" / "codebook.xml").is_file()
NEEDS_CORPUS = pytest.mark.skipif(
    not (HAS_DB and HAS_CORPUS),
    reason=f"本机没有 notes.sqlite3（{HAS_DB}）或 KITE_DATA_DIR 下的 codebook（{HAS_CORPUS}）")


@pytest.fixture
def real_corpus(monkeypatch):
    """`conftest._isolated_db` 把 codebook 指到临时目录——要真语料的测试自己指回去。"""
    from app.database.kite import kite_memory as _km
    from app.util.config import get_settings as _gs
    monkeypatch.setattr(_km, "get_settings", _gs)
    yield


def _rows(set_name: str) -> list[dict]:
    out = []
    for line in FIX.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("set") == set_name and "_meta" not in r:
            out.append(r)
    return out


def _meta(set_name: str) -> dict:
    for line in FIX.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("set") == set_name and "_meta" in r:
            return r["_meta"]
    raise AssertionError(f"{set_name} 没有 _meta")


class _F:
    """一条假事实。`WhoFace` 只要 `.text` / `.who` / `.unit`——**不必有真语料**。"""

    def __init__(self, text, who, unit="u1", topics=()):
        self.text, self.who, self.unit, self.topics = text, who, unit, tuple(topics)


def _confusion(rows: list[dict], axis: str, th: float) -> tuple[int, int, int, int]:
    """(捞回, 假捞回, 挡住, 挡错)。**「说不好」不进分母。**

    尺子判「不泛」= `spread < th` = 会被捞回来；**产品只在这一头动手**，
    所以「假捞回」（尺子说不泛、人说泛）才是这份留出集要验的那个错法。
    """
    fr = bad = gen = miss = 0
    for r in rows:
        s, lab = r.get(axis), r["人标"]
        if s is None or lab == "说不好":
            continue
        if s < th:
            fr += 1
            bad += lab == "泛"
        else:
            gen += 1
            miss += lab == "不泛"
    return fr, bad, gen, miss


# ── ① i=607 那条链 ────────────────────────────────────────────────────

def test_第一条_三档反事实的数钉在源码里():
    """`--cf-gates` 那十个数是这一批 ① 和 ③ 两个判的全部分量。"""
    assert RR.EXPECT_CF_GATES_SIZE_CHANGED == 0
    assert RR.EXPECT_CF_GATES_TAG_CHANGED == 24
    assert RR.EXPECT_CF_GATES_TAG_LIBS == (("terrence", 24),)
    assert RR.EXPECT_CF_GATES_TAG_607 == (1, 0)
    assert RR.EXPECT_CF_GATES_EN_CHANGED == 6
    assert (RR.EXPECT_CF_GATES_EN_ADD, RR.EXPECT_CF_GATES_EN_DROP) == (25, 5)
    assert RR.EXPECT_CF_GATES_EN_EMPTY == 0
    assert RR.EXPECT_CF_GATES_EN_LIBS == (("terrence-rewrite", 6),)
    assert RR.EXPECT_CF_GATES_EN_IDX == (295, 296, 316, 318, 319, 320)


def test_第一条b_主语面闭嘴时common_term把它当is_common_拿假事实表直接测():
    """**这是 ① 的机制本身，不必有真语料。**

    `WhoFace` 在说话人标签过半的库上 `generic()` 回 `None`，而 `common_term()` 里
    那句 `who.generic(term) is not False` 对 `None` 为 **`True`** → 判「是 common」
    → **不捞回来**。所以主语面在大库上不是「什么都不做」，是**把话题面那一问整个按住**。
    P88 那句「够不着大库」说反的正是这一格。
    """
    tags = [_F(f"众筹页面第{i}版要改文案", who=w)
            for i, w in enumerate(["speaker a", "speaker b", "speaker_c", "Speaker D"] * 10)]
    face = TF.WhoFace(tags)
    assert face.usable is False
    assert face.generic("众筹") is None, "闭嘴那一档必须回 `None`，不是 `False`"
    # 产品那一句的逻辑本身（照抄 `common_term` 最后一行的形状）
    assert (face.generic("众筹") is not False) is True, (
        "`None is not False` 必须为真 —— 这一句就是「大库上一律不捞回来」的全部原因")
    # 反过来：真主语库上它会说话，而且能说「不泛」（= 真的会捞回来）。
    # **「不泛」要的是主语面窄**——所以这个串只出现在少数几个主语的事实里，
    # 而库里的主语远不止那几个（这正是 `spread = k / E(n)` 量的东西）。
    who_pool = ["团队", "项目团队", "李工", "用户", "周敏", "设计师", "供应商", "小黄",
                "工厂", "投资方", "中介", "教练"]
    real = [_F(f"别的事第{i}件", who=who_pool[i % len(who_pool)]) for i in range(96)]
    real += [_F(f"众筹页面第{i}版要改文案", who=w)
             for i, w in enumerate(["团队", "项目团队"] * 15)]
    assert TF.WhoFace(real).generic("众筹") is False


def test_第一条c_那四个串的主语面分数远低于门槛_所以真开口就会捞回来():
    """**① 最要紧的那一句**：大库上的安全不是「这条轴判得准」。

    拿假事实表把形状摆出来——一个 `who` 是真主语、串又到处都是的库，
    主语面照样会判「不泛」（= 捞回来）。真语料上那四个串实测是
    `用户`.460 / `需要`.473 / `产品`.559 / `手机`.534，**全都远低于 0.85**。
    """
    who_pool = ["团队", "项目团队", "李工", "周敏", "设计师", "供应商", "小黄",
                "工厂", "投资方", "中介", "教练", "老师"]
    # 库里主语很多；而这个串命中的事实**只落在三个主语上** → 主语面窄 → 判「不泛」
    facts = [_F(f"别的事第{i}件", who=who_pool[i % len(who_pool)], unit=f"u{i % 9}")
             for i in range(120)]
    facts += [_F(f"第{i}条事实里也提到用户", who=["团队", "项目团队", "李工"][i % 3],
                 unit=f"u{i % 9}") for i in range(40)]
    face = TF.WhoFace(facts)
    assert face.usable is True
    s = face.spread("用户")
    assert s is not None and s < TF.WHO_GENERIC, (
        f"主语面给了 {s} —— 一个到处都是的串在真主语库上照样判「不泛」，这正是 ① 那句话")
    assert face.generic("用户") is False, (
        "判「不泛」= `common_term()` 会把它从 `common` 手里捞回来 —— "
        "真语料上 `用户`(.460) / `需要`(.473) / `产品`(.559) / `手机`(.534) 就是这个形状")


@NEEDS_CORPUS
def test_第一条d_i607在HEAD上是好的_不是没治好(real_corpus):
    """**更正 P88 ①**：P88 收尾写「i=607 没治好」，而它在 HEAD 上召回 **1 条**。"""
    qs = RR.queries()
    user, q, _m, _o = qs[607]
    assert user == "terrence"
    mem = KM.UserMemory(user)
    facts, _t, _ms = mem.recall(q, limit=8, evidence=True)
    ids = [f.get("id") for f in facts]
    assert ids == ["terrence-1431-12F5"], (
        f"i=607 在 HEAD 上是 {ids} —— **P90 ① 整节重读**，它的前提是「HEAD 上有 1 条」")
    # 对照：i=293 也还是好的（P88 ① 治好的那一条，别让它悄悄回去）
    u2, q2, _m2, _o2 = qs[293]
    ids2 = [f.get("id") for f in KM.UserMemory(u2).recall(q2, limit=8, evidence=True)[0]]
    assert ids2 == ["terrence-1837F16"], f"i=293 退回去了：{ids2}"


@NEEDS_CORPUS
def test_第一条e_两道闸今天冗余但摘掉说话人标签那道就塌(real_corpus):
    """`--cf-gates` 三档一起跑，**接线自检先断言**。

    ⚠️ 它顺带钉死「那个 0 不等于那道闸没用」：`tag` 那一档 24 条、i=607 1→0。
    """
    g = RR.cf_gates()
    assert g["selfcheck_mismatch"] == 0, "复刻的 HEAD 跟产品对不上 —— 下面的数全部作废"
    assert len(g["size"]["changed"]) == RR.EXPECT_CF_GATES_SIZE_CHANGED
    assert len(g["tag"]["changed"]) == RR.EXPECT_CF_GATES_TAG_CHANGED
    assert g["tag"]["libs"] == RR.EXPECT_CF_GATES_TAG_LIBS
    assert g["tag"]["i607"] == RR.EXPECT_CF_GATES_TAG_607
    assert 607 in g["tag"]["changed"]
    assert g["en"]["changed"] == RR.EXPECT_CF_GATES_EN_IDX


def test_第一条f_更正是并排写的_P88那句错的话还留在源码里():
    """**删掉错的那句就不叫更正叫改口**（P86 立的规矩）。"""
    src = pathlib.Path(TF.__file__).read_text(encoding="utf-8")
    assert "**i=607（大库上同一张脸）没治好**——这一刀够不着大库" in src, (
        "P88 那句原话被删了 —— 更正必须**并排写**，不是改口")
    assert "`i=607` 根本不是「没治好」，它在 HEAD 上是好的" in src
    assert "「这一刀够不着大库」说反了——它够得着" in src
    # 那道闸的注释里也得有「别把 0 读成没用」这一句
    assert "两道闸今天是**冗余**的，但它们挡的**不是同一种库**" in src


# ── ② `WHO_GENERIC` 那个 0.85 的留出集 ────────────────────────────────

def test_第二条_三份留出集都在夹具里_条数对():
    for name, n in (("p90-holdout-who-a", 88), ("p90-holdout-who-b", 116),
                    ("p90-holdout-en-60", 60)):
        rows = _rows(name)
        assert len(rows) == n, f"{name} 是 {len(rows)} 条，不是 {n}"
        libs = Counter(r["user"] for r in rows)
        assert len(libs) == 2, f"{name} 只有 {dict(libs)} 一个库 —— P88 ② 那笔账没还上"


def test_第二条b_每条标注都带着摆给标的人看的东西_而且人标只有三种():
    """留出集的价值全在「**下一个人能自己重判一遍**」。只留一个标签的表谁也验不了。"""
    for name in ("p90-holdout-who-a", "p90-holdout-who-b", "p90-holdout-en-60"):
        for r in _rows(name):
            assert r["人标"] in ("泛", "不泛", "说不好"), (name, r)
            assert r["摆给标的人看的事实"], f"{name}/{r['串']} 没摆上下文，下一个人没法重判"
            assert r["labeled_by"] == "P90"


def test_第二条c_A栏085那一档_挡错0_假捞回41():
    """**从夹具重算，不是抄台账**（P88 那一课）。"""
    rows = _rows("p90-holdout-who-a")
    fr, bad, gen, miss = _confusion(rows, "who面", TF.WHO_GENERIC)
    assert (fr, bad, gen, miss) == (64, 41, 12, 0), (fr, bad, gen, miss)
    assert miss == 0, "「判泛」那一头一旦挡错，0.85 站得住的那一半就没了"
    assert bad / fr > 0.5, (
        "「判不泛」那一头的假捞回率掉到一半以下了 —— 那是好事，但 ② 那段话得重写")


def test_第二条d_080到090那一整段挡错都是0_平台不再是两个串顶着():
    """P88 自己标的最弱那一格：「平台两头各由**一个串**顶着」。这一批两头各 6 个标过的串。"""
    rows = _rows("p90-holdout-who-a")
    for th in (0.80, 0.85, 0.90):
        _fr, _bad, _gen, miss = _confusion(rows, "who面", th)
        assert miss == 0, f"门槛 {th} 挡错 {miss} 条 —— 平台塌了"
    # 平台下沿之外就开始要钱了
    assert _confusion(rows, "who面", 0.70)[3] > 0, "0.70 也不挡错的话，平台的下沿就不在 0.80"
    # 两头各有 ≥5 个标过的串（不是「一个串顶着」）
    have = [r for r in rows if r["who面"] is not None and r["人标"] != "说不好"]
    below = sorted((r["who面"] for r in have if r["who面"] < TF.WHO_GENERIC), reverse=True)[:6]
    above = sorted(r["who面"] for r in have if r["who面"] >= TF.WHO_GENERIC)[:6]
    assert len(below) >= 5 and len(above) >= 5


def test_第二条e_B栏没有一个能用的工作点():
    """**真盲的那一份**说的是这条轴本身有多弱。"""
    rows = _rows("p90-holdout-who-b")
    for th in (0.60, 0.70, 0.80, 0.85, 0.90, 1.00):
        fr, bad, _gen, _miss = _confusion(rows, "who面", th)
        assert fr and bad / fr > 0.6, (
            f"门槛 {th} 的假捞回率掉到 {bad / fr:.1%} —— B 栏那句「没有工作点」得重读")


def test_第二条f_A栏不盲这件事没被删掉():
    """**弱点写下来就不许被悄悄抹掉**（同 P86 「更正要并排写」那条）。"""
    m = _meta("p90-holdout-who-a")
    assert "⚠️ 它不是干净的盲标" in m, "A 栏的污染说明被删了 —— 那份标注就成了假的干净数据"
    assert "B 栏" in m["⚠️ 它不是干净的盲标"]
    for name in ("p90-holdout-who-a", "p90-holdout-who-b", "p90-holdout-en-60"):
        mm = _meta(name)
        assert "先造盲标单" in mm["顺序"] and "标完" in mm["顺序"]
        assert "判不泛" in mm["验的是哪一头"], f"{name} 没写清验的是哪一头（P84 ③ 那一课）"


# ── ③ 拆汉字闸那条路 ──────────────────────────────────────────────────

def test_第三条_那6条读下来是_变好0_中性2_变差4():
    rows = _rows("p90-engate-6")
    assert len(rows) == 6
    c = Counter(r["读下来"] for r in rows)
    assert c == {"变差": 4, "中性": 2}, f"{c} —— ③ 判「不通」的全部分量就是这三个数"
    assert tuple(sorted(r["i"] for r in rows)) == RR.EXPECT_CF_GATES_EN_IDX
    # 两条最要紧的读法钉死：i=295 是「1 条 + 7 句 ai 撞词」，i=319 是「1 赚 3 亏 4」
    by_i = {r["i"]: r for r in rows}
    assert by_i[295]["条数"] == "1→8" and by_i[295]["读下来"] == "变差"
    assert "179" in by_i[319]["why"], (
        "i=319 那条**真赚到的逐句出处**被从理由里抹掉了 —— 那条读法就只剩坏消息了")


@NEEDS_CORPUS
def test_第三条b_P88那句预测实测对了_ai会被放进来_app和agent不会(real_corpus):
    """P88 ③ 写的是：「0.85 在缝 (.747, .819) 的**上方**，拿这条轴去拆汉字闸会把 `ai` 放进来」。

    **实测：对。** 而且顺带说明这一刀为什么只有 6 条——`app` / `agent` 被主语面挡住了。
    """
    mem = KM.UserMemory("terrence-rewrite")
    store, _v = mem._index()
    idx = mem._grep_index(store)
    face = TF.WhoFace(store.facts.values(), units_for=idx.units_for)
    ai, app, agent = face.spread("ai"), face.spread("app"), face.spread("agent")
    assert ai is not None and ai < TF.WHO_GENERIC, (
        f"`ai` 的主语面是 {ai} —— P88 ③ 那句预测和 ③ 整节的前提都得重读")
    assert app is not None and app >= TF.WHO_GENERIC, f"`app` 是 {app}，主语面不再挡它"
    assert agent is not None and agent >= TF.WHO_GENERIC, f"`agent` 是 {agent}"


def test_第三条c_英文留出集说主语面在英文串上没有信号():
    """**英文那半第一份留出集**（收 P77 ③ / P79 ④ / P84 ③）。

    两条轴分开读：`who` 轴任何门槛都不能用；`topics` 轴低段是干净的
    ——**所以要拆汉字闸该走 `topics` + 一个英文专用低门槛，不是主语面。**
    """
    rows = _rows("p90-holdout-en-60")
    for th in (0.60, 0.70, 0.80, 0.85, 0.95):
        fr, bad, _g, _m = _confusion(rows, "who面", th)
        assert fr and bad / fr >= 0.55, (
            f"`who` 轴在门槛 {th} 上的假捞回率掉到 {bad / fr:.1%} —— ③ 卡格②那句话得重读")
    fr, bad, _g, _m = _confusion(rows, "topics面", 0.60)
    assert fr >= 8 and bad == 0, (
        f"`topics` 轴 ≤0.60 那一段不再干净了（捞回 {fr} / 假捞回 {bad}）—— "
        "③ 给出的那条「该走哪条路」就不成立了")
    # 两个最要紧的串，`who` 轴**都判反**
    by = {(r["user"], r["串"]): r for r in rows}
    assert by[("terrence-rewrite", "ai")]["人标"] == "泛"
    assert by[("terrence-rewrite", "ai")]["尺子判"] == "不泛"
    assert by[("terrence-rewrite", "agent")]["人标"] == "不泛"
    assert by[("terrence-rewrite", "agent")]["尺子判"] == "泛"


def test_第三条d_汉字闸和库大小闸都还在源码里_这一批一个字节没改():
    """**判「不通」就得让那道闸原样待着。**"""
    src = inspect.getsource(KM.UserMemory.common_term)
    assert "ask_face = total * R.COMMON_DF_RATIO < R.COMMON_DF_MIN" in src, "库大小闸没了"
    assert "if not (ask_face and TF.has_cjk(term)):" in src, "汉字闸没了"
    assert "return who.generic(term) is not False" in src, "主语面那一问没了"
    assert TF.WHO_GENERIC == 0.85 and TF.SPEAKER_TAG_MAX == 0.5
    assert TF.SPREAD_GENERIC == 0.75 and TF.SPREAD_MIN_HITS == 20


# ── ④ 登记 / 分母 ─────────────────────────────────────────────────────

def test_第四条_这一批的新数进了登记表():
    for name in ("EXPECT_CF_GATES_SIZE_CHANGED", "EXPECT_CF_GATES_TAG_CHANGED",
                 "EXPECT_CF_GATES_TAG_607", "EXPECT_CF_GATES_EN_CHANGED",
                 "EXPECT_CF_GATES_EN_DROP", "EXPECT_CF_GATES_EN_EMPTY"):
        key = ("backend/scripts/recall_ruler.py", name)
        assert key in FR.REGISTRY, f"{name} 没登记 —— 它一动没人知道该去重读什么"
        _tier, _base, why = FR.REGISTRY[key]
        assert len(why) >= 30, f"{name} 的「一动要去重读什么」写得太短：{why!r}"


def test_第四条b_下限那把尺全绿_而且两个只准往上的数抬到了合并后的真值():
    bad, checked, behind = FR.check()
    assert bad == [] and behind == [], (bad, behind)
    # ⚠️ 这里本来钉死 `== 95 and == 107`。第 816 轮合并（P92 加了 9 条登记）当场红——
    # 而这两个数正是第 810 轮为了**不在每次正当改动上红**才从各批测试里搬进 floor_ruler 的
    # （见那两个常数上面的注释）。钉死它们的值，等于把同一个洞又搬回来了一次。
    # 这一条要守的意思是「**合并时必须把它俩抬到合并后的真值**」——那就直接钉这件事：
    # 它俩 == 当下的真值。加登记不抬 → 红；抬了 → 绿；把登记删了 → 下面两条红。
    assert FR.REGISTRY_SIZE_FLOOR == len(FR.REGISTRY), (
        f"登记表 {len(FR.REGISTRY)} 条，而 REGISTRY_SIZE_FLOOR 还停在 "
        f"{FR.REGISTRY_SIZE_FLOOR}——合并后要把它抬到真值（只准往上，抬是绿的）")
    assert FR.CHECKED_COUNT_FLOOR == checked, (
        f"共核 {checked} 条，而 CHECKED_COUNT_FLOOR 还停在 {FR.CHECKED_COUNT_FLOOR}")
    assert len(FR.REGISTRY) >= FR.REGISTRY_SIZE_FLOOR
    assert checked >= FR.CHECKED_COUNT_FLOOR


def test_第四条c_47条那把尺的分母没被这274行标注动到():
    """这一批往 `memory_sample.jsonl` 追加了 274 行，**而那份夹具还被 47 条那把尺读着**。

    那把尺认的是 `sampled_from` / `hit` 那几格，这一批四组标注一格都没有
    ——所以它的分母一个没动。**顺手改到别人的分母是这个仓栽过的跤。**
    """
    all_rows = []
    for line in FIX.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            all_rows.append(json.loads(line))
    p90 = [r for r in all_rows if str(r.get("set", "")).startswith("p90-")]
    assert len(p90) == 274, len(p90)
    assert not any("sampled_from" in r for r in p90), (
        "这一批有标注带了 `sampled_from` —— 47 条那把尺的分母被动了")
    # 那把尺认的是 `set == "p34-sample47"`（`memory_sample_replay.DEFAULT_SET`）
    from scripts import memory_sample_replay as MSR
    sampled = [r for r in all_rows
               if r.get("set", MSR.DEFAULT_SET) == MSR.DEFAULT_SET and "_meta" not in r]
    assert len(sampled) == 47, f"47 条那把尺的分母变成 {len(sampled)} 了"
