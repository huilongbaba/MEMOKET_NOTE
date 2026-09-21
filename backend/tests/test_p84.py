"""P84：**把「泛词」和「主题词」分开的那条轴造出来了，接了**（收 P82 ①）。

P81 读 95 条、P82 读 49 条，根因是同一句话：
**近义改写句跟查询共用的正是这个库的主题词，而单主题库里主题词的 df 天然就高。
df 高 ≠ 它不是证据。** P82 试过按库大小把 `common` 整条关掉，**变好 16 / 变差 23 → 退回**
——那个旋钮砍掉的是 `common` 兼着的**第二份工**（口水词兜底）。

**这一批换轴，不动门槛。** 轴是 `FactRecord.topics` 的话题面（P75 造的那把尺，
**核下来能直接用，没再造第二把**）：实现从 `scripts/topic_spread_ruler.py` 搬进
`app/database/kb/topic_face.py`，尺子改成 import 那一份，**一份实现两个用途**。

`UserMemory.common_term()` 里加的是**一问**，不是一道新门：df 已经判 True 之后，
**只在小库那一档（`total * RATIO < MIN`）、只对汉字串、只有明确判「不泛」时**才捞回来。

全库对拍（`recall_ruler --cf-spread`）：765 里变 **28 条，全部落在 `terrence-rewrite`
（28/86 = 32.6%）**，逐条读完 **变好 14 / 变差 7 / 中性 7 → 接**。标注 `p84-spread-28`。

⚠️ **不限汉字的那一版先量过、读完了，是白干**：41 条 / 变好 17 / 变差 17。
变差那一栏是系统性的（`ai` / `agent` / `memory` / `app` 一起被捞回来，四条查询的整屏被
六句几乎一模一样的英文定位套话灌满）。**「只问汉字」这条限制不是这一批现编的**
——P77 ③ / P79 ④ 两批都把「泛尺在英文那一半没有留出集」记成了待办；
**但选它是在读完那 41 条之后，顺序照实记在 `p84-spread-28` 的 `_meta` 里。**

出身（**整行跟着数走**）：HEAD `6fa51a2` · `scripts/recall_ruler.py` 765 条 ·
`notes=482篇/321250字/47dcc54be60aa4f2` · `terrence=11429185B/403a1183` ·
`terrence-rewrite=6594533B/8b6ba3bb`。

四栏留下率**整行、一栏没跌**（`KITE_DATA_DIR=<scratch>/p84data` 自己量的）：
`recall_selfcheck terrence 200 11` **197/195/96**、`… evidence` **192/190/92** ·
圆点 **166/137/33**（缺依据 23 · 印证 10）· D2 表 B **8 条** · 47 条 **46/36/4/6（13%）**。

⚠️ **四栏对这一刀基本是瞎的**（P82 那一课，这一批照办）：前三栏全建在 `terrence` 上，
而这条轴一条都动不到 `terrence`。47 条那一栏里有 15 条在 `terrence-rewrite`，
**实测走到这条新分支 4 次、4 次都判「泛」** → 照旧算 common，
所以那 46/36/4/6 是真的没动，**不是因为没走到**（闸在 `第四条c`）。
唯一真看得见它的是 765 那把尺按库分之后的那一行。

⚠️ **爆炸半径照实记**：`card_origin_ruler` 的两个**分母**动了
（卡总数 964 → **977**、摆出了卡的查询 312 → **314**），
而 P83 A 那四个数（marked 133 / with_mark 62 / mixed 29 / all_marked 33）**一格没动**。
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter

import pytest

from app.database.kb import relations as R
from app.database.kb import topic_face as TF
from scripts import card_origin_ruler as CO
from scripts import floor_ruler as FR
from scripts import recall_ruler as RR
from scripts import topic_spread_ruler as TS

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "memory_sample.jsonl"
CORPUS_FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "memory_sample_corpus.json"

HAS_DB = (ROOT / "backend" / "data" / "notes.sqlite3").exists()
HAS_CORPUS = (RR.data_dir() / "terrence" / "codebook.xml").is_file()
NEEDS_CORPUS = pytest.mark.skipif(
    not (HAS_DB and HAS_CORPUS),
    reason=f"本机没有 notes.sqlite3（{HAS_DB}）或 KITE_DATA_DIR 下的 codebook（{HAS_CORPUS}）")


@pytest.fixture
def real_corpus(monkeypatch):
    """`conftest._isolated_db` 把 codebook 指到临时目录——**要真语料的测试自己指回去**。
    指回去的是 `KITE_DATA_DIR` 那一份（跑批用的拷贝），**不是主仓那份真库**。"""
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
    """一条假事实。`TopicFace` 只要 `.text` / `.topics` / `.unit` 三样。"""

    def __init__(self, text, topics, unit="u"):
        self.text, self.topics, self.unit = text, topics, unit


# ── ① 那条轴本身：三档、不是恒真也不是恒假 ────────────────────────────────

def test_第一条_那条轴三档都在_而且判不了不许当不泛用():
    """**反例两头先摆出来**（这个仓每批的规矩），而且**例子里要有「两条判据分得开」的那一种**
    （P83 第 ② 刀）：下面 `主题词` 和 `泛词` **出现次数一模一样**（各 30 条），
    df 那条轴上它们完全分不开，**只有话题面这条轴分得开**。"""
    facts = []
    for i in range(30):
        facts.append(_F(f"第{i}句讲主题词", [f"t{i % 3}"], unit=f"u{i}"))     # 收在 3 个话题里
        facts.append(_F(f"第{i}句讲泛词", [f"t{i % 30}"], unit=f"u{i}"))       # 摊在 30 个话题里
    face = TF.TopicFace(facts)
    assert face.face("主题词")[0] == face.face("泛词")[0] == 30, "两串的出现次数得一样，否则不叫分得开"
    assert face.generic("主题词") is False
    assert face.generic("泛词") is True
    # 第三档：库里一次都没有 / 有但不够 `SPREAD_MIN_HITS` —— **都是判不了，不是「不泛」**
    assert face.generic("库里没有这一串") is None
    few = TF.TopicFace([_F("只有五条", [f"t{i}"], unit=f"u{i}") for i in range(5)])
    assert few.face("只有五条")[0] == 5 < TF.SPREAD_MIN_HITS
    assert few.generic("只有五条") is None, "样本不够被当成了「不泛」——那条轴就成了恒假"


def test_第一条b_两个门槛没动_而且尺子那份镜子还对得上():
    """**这一批换的是轴，不是门槛**：`SPREAD_GENERIC` / `SPREAD_MIN_HITS` 一个字没动。
    实现搬进产品之后尺子里留的是**钉死的镜子**（`floor_ruler` 只认模块级字面量），
    所以这儿、`topic_spread_ruler.main()` 各核一遍。"""
    assert TF.SPREAD_MIN_HITS == 20
    assert TF.SPREAD_GENERIC == 0.75
    assert TS.SPREAD_MIN_HITS == TF.SPREAD_MIN_HITS
    assert TS.SPREAD_GENERIC == TF.SPREAD_GENERIC
    assert TS.check_mirror() == []
    # **一份实现两个用途**：尺子里的 `TopicFace` 就是产品里那一个，不是抄的第二份
    assert TS.TopicFace is TF.TopicFace


def test_第一条c_它够不着哪儿_写在产品源码里():
    """P75 那把尺自己写过「阈值和准确率读在同一批数上，没有留出集」。
    这一批把**它够不着的三格**原样写进产品源码——**说清楚它没验过什么，而不是假装验过**。"""
    src = pathlib.Path(TF.__file__).read_text(encoding="utf-8")
    for need in ("英文那一半没有留出集", "12/38", "变好 17 / 变差 17", "变好 14 / 变差 7",
                 "在小库上没有留出集", "「判不泛」那一头"):
        assert need in src, f"`kb/topic_face.py` 里找不到 {need!r}"


# ── ② 接进 `common_term()` 的那一问：**窄** ──────────────────────────────

@NEEDS_CORPUS
def test_第二条_大库上一个字都不动(real_corpus):
    """**判据宁可窄**：`terrence`（2362 unit）上 `total * RATIO = 141.7 ≥ 20`，
    那一问根本不问。这一格一翻，四栏那四个数就不再是「对这一刀是瞎的」，得整批重读。"""
    from app.database.kite.kite_memory import UserMemory
    m = UserMemory("terrence")
    store, _v = m._index()
    idx = m._grep_index(store)
    assert idx.unit_count == 2362
    assert idx.unit_count * R.COMMON_DF_RATIO >= R.COMMON_DF_MIN, "大库那一档的前提没了"
    common = m.common_term()
    # `ai` 在真库上 spread=0.74 判「不泛」——**但大库上根本不问它**，所以照旧是 common
    face = TS.from_memory("terrence")
    assert face.generic("ai") is False, "这一格的反例本身没落在被测分支上了"
    assert common("ai") is True, "大库上那一问被问了——判据的范围超了"
    assert common("数据") is True and common("产品") is True


@NEEDS_CORPUS
def test_第二条b_英文那一半不问_汉字那一半才问(real_corpus):
    """**泛尺在英文那一半没有留出集**（P77 ③ / P79 ④），所以那半原样走 df。
    ⚠️ **反例得真的落在被测分支里**：下面四个英文串在小库上 `generic` 判的都是「不泛」
    ——也就是说**只要问了就会被捞回来**，它们照旧是 common 只可能是因为「没问」。"""
    from app.database.kite.kite_memory import UserMemory
    m = UserMemory("terrence-rewrite")
    store, _v = m._index()
    idx = m._grep_index(store)
    assert idx.unit_count * R.COMMON_DF_RATIO < R.COMMON_DF_MIN, "这个库不在小库那一档了"
    common = m.common_term()
    face = TS.from_memory("terrence-rewrite")
    for t in ("ai", "app", "agent", "memory"):
        assert not TF.has_cjk(t)
        assert face.generic(t) is False, f"{t!r} 在这个库上不再判「不泛」——这条反例失效了"
        assert common(t) is True, f"{t!r} 被那条轴捞回来了——「只问汉字」那一句没生效"
    # 对照：同一个库上的汉字串，判「不泛」的就真被捞回来了
    assert face.generic("众筹") is False and common("众筹") is False
    # 对照：汉字串判「泛」的照旧是 common —— **不是恒真也不是恒假**
    assert face.generic("因此") is True and common("因此") is True


@NEEDS_CORPUS
def test_第二条c_判不了一律照旧算common(real_corpus, monkeypatch):
    """`None` 当 `False` 用不得（同 `_aligned` 那条）：`SPREAD_MIN_HITS` 以下那一档
    不是「不泛」，是**样本不够**。

    ⚠️ **这一格是突变验第 ⑧ 刀补出来的，照实记**：`is not False` 改成 `is True`
    （= 把 `None` 当「不泛」用）**那一刀第一版没红**——因为在这份语料上
    **df-common 的 190 个串里一个都没落在「判不了」那一档**（144 泛 / 46 不泛 / 0 判不了）：
    df ≥ 20 个 unit 几乎必然带来 ≥ 20 个话题次。**那不是闸没用，是这条路上真没有例子。**
    所以这一格自己造一个：把那个库的话题面换成一份**恒回 `None`** 的，
    再问 `common_term()`——**它必须照旧算 common**。"""
    from app.database.kite.kite_memory import UserMemory

    # 先在真面上确认这一档真的空着（这条断言本身就是上面那段话的闸）
    real = TS.from_memory("terrence-rewrite")
    assert real.generic("众筹") is False, "反例的前提没了"

    class _AllNone:
        def generic(self, _term):
            return None

    m = UserMemory("terrence-rewrite")
    monkeypatch.setattr(UserMemory, "_topic_face", lambda self, store, idx: _AllNone())
    common = m.common_term()
    # `众筹` df 33/193 = 17.1% 过 df 那道门；话题面回 `None` = 判不了 → **照旧算 common**
    assert common("众筹") is True, "「判不了」被当成「不泛」用了——判据比它该有的宽"
    # 对照：本来就过不了 df 那道门的串，回的还是 False（不是被这一格弄成恒真了）
    assert common("瓷器纹") is False

    # 纯函数那一头也钉一遍：`SPREAD_MIN_HITS` 以下就是 `None`
    face = TF.TopicFace([_F("零零散散", ["t1"], unit=f"u{i}") for i in range(5)])
    assert face.generic("零零散散") is None


# ── ③ 全库对拍：28 条逐条读完 ────────────────────────────────────────────

def test_第三条_那把尺把反事实钉下来了():
    """**量具进了仓库**（`recall_ruler` 模块注释里那条规矩）。
    ⚠️ `--cf-common` 的基准同时改成了 `_df_only_common`——**否则 P82 那 49 就不是那个 49**。"""
    assert RR.EXPECT_CF_SPREAD_CHANGED == 28
    assert RR.EXPECT_CF_SPREAD_ADD == 36
    assert RR.EXPECT_CF_SPREAD_DROP == 16
    assert RR.EXPECT_CF_SPREAD_HIT == (345, 341)
    assert RR.EXPECT_CF_SPREAD_LIBS == (("terrence-rewrite", 28),)
    assert RR.EXPECT_CF_SPREAD_RESCUED == 63
    # **只够得着一个库**：这一条一翻，四栏就不再是「瞎的」，得整批重读
    assert RR.EXPECT_CF_SPREAD_LIBS[0][1] == RR.EXPECT_CF_SPREAD_CHANGED
    # 按库分的分母（P81 ① 那一课）：`terrence-rewrite` 那一档的分母是 86
    assert RR.EXPECT_BY_LIB[("terrence-rewrite", "script")] == 86
    # P82 那一支逐格没动，而且它的基准现在是「只看 df」那一版
    assert RR.EXPECT_CF_COMMON_CHANGED == 49 and RR.EXPECT_CF_COMMON_HIT == (341, 347)
    src = pathlib.Path(RR.__file__).read_text(encoding="utf-8")
    assert "def _df_only_common(self):" in src
    assert "fn = _df_only_common(self)" in src, \
        "`--cf-common` 的基准又变回 HEAD 了——那 49 条里会混进 P84 这条轴的差"


def test_第三条b_那28条逐条读完了_而且三档都钉死():
    """**不许用下限守**（P78 ④ / P79 第 ⑨ 刀两次实证）：「接」这个判全靠那 14 : 7，
    一列一动判据就得重读，所以三个数逐个钉死，不写 `>= N`。"""
    rows = _rows("p84-spread-28")
    assert len(rows) == 28, f"{len(rows)} ≠ 28——那 28 条不是全读完的"
    assert dict(Counter(r["读下来"] for r in rows)) == {"变好": 14, "变差": 7, "中性": 7}
    # **全部落在同一个库上**，这是这一条判的前提
    assert {(r["user"], r["lineage"]) for r in rows} == {("terrence-rewrite", "script")}
    assert all(r["why"].strip() for r in rows), "有条目没写理由——那就不叫读过"
    assert sum(1 for r in rows if r["只换名次"]) == 3, "只换名次的那三条（585/589/664）变了"


def test_第三条c_变好变差两头各钉几条实打实的():
    """**绿有个数**：变好那一档钉的是「逐句出处真被捞回来了」，
    变差那一档钉的是「真沾边的被挤掉了 / 0 条变成一屏撞词」。
    这几条一改口，「接」这个判就得重读。"""
    rows = {r["i"]: r for r in _rows("p84-spread-28")}
    for i, needle in ((316, "179美元"), (320, "179美元"),
                      (297, "软件是产品未来持续产生价值"),
                      (591, "五名消费者中有三人"),
                      (598, "上线版本与用户在六月或七月收到的版本")):
        assert rows[i]["读下来"] == "变好", f"i={i} 不再判变好，「接」这个判要重读"
        assert any(needle in t for t in rows[i]["进的"]), f"i={i} 进的里找不到 {needle!r}"
    for i, needle in ((293, "离开安克"), (41, "note-taking"),
                      (687, "构建品牌故事")):
        assert rows[i]["读下来"] == "变差", f"i={i} 不再判变差——**变差那一栏是这条判的代价**"
        assert any(needle in t for t in rows[i]["掉的"]), f"i={i} 掉的里找不到 {needle!r}"
    for i in (686, 692):
        assert rows[i]["读下来"] == "变差" and rows[i]["条数"] == "0→5"
        assert any("包装盒" in t for t in rows[i]["进的"]), f"i={i} 那一屏 KOL 撞词没了"
    # i=293 是 P82 那一刀栽过的同一条 —— **同一个坑这一批也没躲开，照实钉**
    assert rows[293]["条数"] == "1→0"


def test_第三条d_不限汉字那一版是白干_这件事写进了台账():
    """**预测 / 试过的路都照实记**：41 条 / 17 : 17 那一版量过、读过、没接。
    这一条也把「顺序」钉住：限制是先有的（P77 ③ / P79 ④），选它是在读完 41 条之后。"""
    m = _meta("p84-spread-28")
    key = "⚠️ 不限汉字的那一版先量过，是白干"
    assert "41 条" in m[key] and "变好 17 / 变差 17" in m[key]
    assert "wearable AI agent" in m[key], "那六句定位套话的形状没记下来"
    assert "顺序照实记" in m[key]
    assert "12/38" in m["⚠️ 那条轴自己够不着哪儿"], "留出集验不了这个用法这件事没记"
    assert "消费者" in m["⚠️ 它没把 P82 那份「第二份工」全接住"]


# ── ④ 爆炸半径 / 四栏 ───────────────────────────────────────────────────

def test_第四条_记忆卡那把尺的分母动了_但那四个数没动():
    """**爆炸半径照实记**：P83 A 那一节的四条判（133 / 62 / 29 / 33）建在卡总数上，
    这一批把分母从 964 抬到 977。**四个数一格没动**，所以那四条判不用重读——
    但这件事得有个闸看着，不能靠人记得。"""
    assert CO.EXPECT_CARDS == 977 and CO.EXPECT_WITH_CARDS == 314
    assert CO.EXPECT_MARKED == 133
    assert CO.EXPECT_QUERIES_WITH_MARK == 62
    assert CO.EXPECT_MIXED == 29
    assert CO.EXPECT_ALL_MARKED == 33
    assert CO.EXPECT_MIXED + CO.EXPECT_ALL_MARKED == CO.EXPECT_QUERIES_WITH_MARK


def test_第四条b_新钉的数全登记了_而且那把尺自己是绿的():
    """**新加闸门常数不登记就当场红**（`floor_ruler` 的完整性闸）。"""
    for name in ("EXPECT_CF_SPREAD_CHANGED", "EXPECT_CF_SPREAD_ADD", "EXPECT_CF_SPREAD_DROP",
                 "EXPECT_CF_SPREAD_HIT", "EXPECT_CF_SPREAD_LIBS", "EXPECT_CF_SPREAD_RESCUED"):
        key = ("backend/scripts/recall_ruler.py", name)
        assert key in FR.REGISTRY, f"{name} 没登记"
        kind, want, why = FR.REGISTRY[key]
        assert kind == FR.PINNED and getattr(RR, name) == want
        assert why.strip(), f"{name} 登记了但没写「一动要去重读什么」"
    # 分母那两条的登记也跟着改了，而且写清楚了「那四个数没动」
    assert FR.REGISTRY[("backend/scripts/card_origin_ruler.py", "EXPECT_CARDS")][1] == 977
    assert "那四个数一格没动" in FR.REGISTRY[
        ("backend/scripts/card_origin_ruler.py", "EXPECT_CARDS")][2]
    bad, n, missing = FR.check()
    assert (bad, missing) == ([], []), (bad, missing)
    # ⚠️ 这里本来钉死 78，第 810 轮合并时跟 test_p85 那条一起红了（理由同那边）。
    assert n >= FR.CHECKED_COUNT_FLOOR, (
        f"共核 {n} 条，少于记在 floor_ruler 里的 {FR.CHECKED_COUNT_FLOOR} 条"
        "——有人把登记或例反例删了，去读 diff 里那几行数据")


def test_第四条c_47条那一栏真的走到了这条新分支():
    """⚠️ **「四栏没跌」得分成两件事说**：47 条里有 15 条在 `terrence-rewrite`，
    所以它**走得到**这条新分支——实测走了 4 次、4 次都判「泛」→ 照旧算 common。
    **46/36/4/6 是真的没动，不是因为没走到。**

    冻下来的那张 `generic` 表也在这一格里钉着：**查不到得当场抛，不许静默放行**
    ——静默那条路会让这份重放悄悄量的是 P84 之前的代码，而表面上照样全绿。"""
    from scripts import memory_sample_replay as MR

    blob = json.loads(CORPUS_FIX.read_text(encoding="utf-8"))
    small = blob["users"]["terrence-rewrite"]
    assert small["unit_count"] == 193
    assert len(small["generic"]) == 190, "冻下来的那张表换了大小——重放的口径变了"
    assert sum(1 for v in small["generic"].values() if v is False) == 46
    # 大库那一档**不该有**这张表（它根本不问）
    assert "generic" not in blob["users"]["terrence"]

    hit = Counter()
    orig = MR.FrozenCorpus.common_term

    def patched(self):
        fn = orig(self)
        if fn is None:
            return None

        def wrap(term):
            n = self.unit_df(term, floor=R.COMMON_DF_MIN)
            if (n is not None and n >= R.COMMON_DF_MIN
                    and n / self.unit_count >= R.COMMON_DF_RATIO
                    and TF.has_cjk(term)
                    and self.unit_count * R.COMMON_DF_RATIO < R.COMMON_DF_MIN):
                hit[self._user] += 1
            return fn(term)
        return wrap

    MR.FrozenCorpus.common_term = patched
    try:
        _meta_s, rows = MR.load_sample()
        judged = MR.replay(rows, blob)
    finally:
        MR.FrozenCorpus.common_term = orig
    assert dict(hit) == {"terrence-rewrite": 4}, \
        f"47 条走到这条新分支的次数变了：{dict(hit)}——「四栏没跌」这句话得重说"
    t = MR.tally(judged)
    assert (t["留下"], t["hard"], t["meh"], t["bad"]) == (46, 36, 4, 6)


def test_第四条d_冻表里查不到当场抛_不许静默放行():
    """**刀要真砍到**（P82 栽过两次）：这一格拿一份**缺了键**的假夹具喂它，
    确认它是抛，而不是悄悄走 `True`。"""
    from scripts import memory_sample_replay as MR

    blob = json.loads(CORPUS_FIX.read_text(encoding="utf-8"))
    blob["users"]["terrence-rewrite"]["generic"] = {}      # 整张表抽走
    c = MR.FrozenCorpus(blob, "terrence-rewrite")
    fn = c.common_term()
    with pytest.raises(KeyError, match="generic"):
        fn("众筹")
    # 对照：英文那一半根本不问这张表，所以抽走了也照样回答
    # （`app` 在这个库上 df 56/193 = 29.0%，过 df 那道门；`ai` 没进冻下来的 df 表，用不了）
    assert fn("app") is True
