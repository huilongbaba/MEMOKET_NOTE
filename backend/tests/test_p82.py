"""P82：**P81 留的那三条账，一条量完判「换不了」、一条量完了、一条量完判「形状记错了」**。

**产品代码一个字节没改**（后端 + 前端都是）。`kb/relations.py` 改的只有一段**注释**
——那段注释里有一句是错的（P81 量到），这一批把它按实测重写了。
`frontend/scripts/walkthrough/` · `frontend/scripts/run-walkthrough-fakeshell.mjs` ·
`frontend/src/editor/` **一个字节没碰**（另有 agent 在那一侧）。

① **`COMMON_DF_MIN` 那道小库兜底** —— **量完判「换不了」**。
   「库不到 333 个 unit 时这条判据等于不启用」这句注释是错的（P81 量到）；
   这一批**把它真做出来**在全库上对拍：765 里变 **49 条，全部落在 `terrence-rewrite`
   （49/86 = 57.0%）**，逐条读完 **变好 16 / 变差 23 / 中性 10 → 退回**。
   根因量出来了：`common_term()` 在那个库上**兼着口水词兜底**（`因此` / `如果` / `团队` /
   `用户` / `说明` 今天只有它挡着，`_is_cn_filler` 那张表里一个都没有）。
   量具进了仓库：`recall_ruler --cf-common`；标注 `p82-off333-49`。

② **quorum 有多脆** —— **量完了，没改**。`_strong_enough` 在 765 上被问 375864 次、
   判 True 1771 次，其中 **1488 次证人正好两条 = 84.0%**（少一条就翻 False）；
   **用户眼前**那 1347 条召回对里这道门管着 1049 条、**778 条靠正好两条撑着 = 74.2%**。
   ⚠️ P81 ④ 说的「几乎同一条查询判反」**没那么脆**：那 79 对前缀查询里长的那条中位
   多出 78% 正文，收紧到「只多出 ≤25%」全库只剩 4 次翻盘。量具：`en_gate_ruler --quorum`。

③ **`_terms` 摆出用户没打完的串** —— **量完判「P81 那笔账的形状记错了」**。
   `9月14日 → 9月14` 是 `search._number_terms` 的产出，**不是屏幕上那一行**：
   唯一真渲染那一行的路是 `recall()` 回的 `terms`（= `surfaces` + `_cjk_terms[:3]`），
   **`_number_terms` 一个字都进不去**。20 种用户真会打的日期 / 数字写法实测，
   屏幕上一共只摆出 **2 串**（`179美元`→`美元`、`1万台`→`万台`，数字被整个丢掉），
   `9月14` 一次都没出现。110 条那一档「只摆了一截」**0 条**。量具：`kb_search_ruler --writings`。

出身（**整行跟着数走**）：HEAD `e41eab6` · `scripts/recall_ruler.py` 765 条 ·
`notes=482篇/321250字/47dcc54be60aa4f2` · `terrence=11429185B/403a1183` ·
`terrence-rewrite=6594533B/8b6ba3bb`。

四栏留下率**整行、一栏没跌**（`KITE_DATA_DIR=<scratch>/p82data` 自己量的）：
`recall_selfcheck terrence 200 11` **197/195/96**、`… evidence` **192/190/92** ·
圆点 **166/137/33**（缺依据 23 · 印证 10）· D2 表 B **8 条** · 47 条 **46/36/4/6（13%）**。

⚠️ **四栏对 ① 那一刀是瞎的**（这一批读出来的）：四栏**全部建在 `terrence` 上**，
而那个旋钮一条都动不到 `terrence`。**四栏全绿不等于那一刀没事**——
唯一看得见它的是 765 那把尺**按库分**之后的那一行（`recall_ruler --by-lib`）。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from app.database.kb import relations as R
from app.database.kb import search as kb_search
from scripts import en_gate_ruler as EG
from scripts import floor_ruler as FR
from scripts import kb_search_ruler as K
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


# ── ① `COMMON_DF_MIN` 那道小库兜底：量完判「换不了」 ─────────────────────────

def test_第一条_那句错的注释不在了_新的那段说的是实测():
    """**改的只有注释，代码一个字节没动**——这一格两头都钉：那两个常数原样，
    而那句「等于不启用」不许再出现（它一回来，下一批就会照着它去接）。"""
    assert R.COMMON_DF_RATIO == 0.06 and R.COMMON_DF_MIN == 20
    src = pathlib.Path(R.__file__).read_text(encoding="utf-8")
    assert "库不到 333 个 unit 时这条判据等于不启用" not in src, \
        "那句错的注释回来了——P81 已经量过它不成立"
    # 新的那段得说清楚三件事：有效门槛是什么、在哪一档没兜住、为什么换不了
    for need in ("max(6%, 20/total)", "10.4%", "14 / 14", "20–333",
                 "变好 16 / 变差 23 / 中性 10", "兼着口水词兜底"):
        assert need in src, f"`relations.py` 那段注释里找不到 {need!r}"
    # P29 那张 20 个串的单子**没动**（`test_p81::第一条d` 靠它）
    assert "6% 那一档否掉的 20 个串" in src


def test_第一条b_那49条逐条读完了_而且三档都钉死():
    """**不许用下限守**（P78 ④ / P79 第 ⑨ 刀两次实证）：「换不了」这个判全靠那 23 条变差，
    那一列一动判据就得重读，所以三个数逐个钉死，不写 `>= N`。"""
    rows = _rows("p82-off333-49")
    assert len(rows) == 49, f"{len(rows)} ≠ 49——那 49 条不是全读完的"
    from collections import Counter
    total = Counter(r["读下来"] for r in rows)
    assert dict(total) == {"变差": 23, "变好": 16, "中性": 10}
    # **全部落在同一个库上**，这是这一条判的前提
    assert {(r["user"], r["lineage"]) for r in rows} == {("terrence-rewrite", "script")}
    assert all(r["why"].strip() for r in rows), "有条目没写理由——那就不叫读过"
    m = _meta("p82-off333-49")
    assert "四栏全绿不等于这一刀没事" in m["⚠️ 四栏看不见这条"]


def test_第一条c_那几条逐字出处在表里_判的是变差():
    """**这一刀为什么退回**：0 条结果的那几屏被撞词灌满了。
    这一格钉的是「这几条在表里、而且判的是变差」——它们一改口，「换不了」这个判就得重读。"""
    rows = {r["i"]: r for r in _rows("p82-off333-49")}
    for i, needle in ((293, "离开安克"),
                      (295, "AI辅助编程"),
                      (296, "继续招聘少量AI和软件类人才"),
                      (686, "包装盒打开过程"),
                      (688, "表带Logo"),
                      (665, "可穿戴的学生设备")):
        r = rows[i]
        assert r["读下来"] == "变差", f"i={i} 不再判变差，「换不了」这个判要重读"
        blob = "".join(r["掉的"]) + "".join(r["进的"])
        assert needle in blob, f"i={i} 掉 / 进的那几条里找不到 {needle!r}"
    # 变好那一档也钉两条（**绿有个数**）：179 美元那条逐句出处确实是被这一刀捞回来的
    assert rows[316]["读下来"] == "变好"
    assert any("179美元" in t for t in rows[316]["进的"])
    assert rows[601]["读下来"] == "变好" and rows[601]["条数"] == "0→1"


def test_第一条d_那把尺把反事实钉下来了():
    """**量具进了仓库**（`recall_ruler` 自己模块注释里那条规矩：
    「一把量具进不了仓库，它量出来的数下一批就复现不出来」）。"""
    assert RR.EXPECT_CF_COMMON_CHANGED == 49
    assert RR.EXPECT_CF_COMMON_DROP == 52
    assert RR.EXPECT_CF_COMMON_ADD == 140
    assert RR.EXPECT_CF_COMMON_HIT == (341, 347)
    assert RR.EXPECT_CF_COMMON_LIBS == (("terrence-rewrite", 49),)
    # 按库分的分母（P81 ① 那一课）：`terrence-rewrite` 那一档的分母是 86
    assert RR.EXPECT_BY_LIB[("terrence-rewrite", "script")] == 86
    assert sum(RR.EXPECT_BY_LIB.values()) == RR.EXPECT_TOTAL == 765
    assert RR.EXPECT_CF_COMMON_LIBS[0][1] == RR.EXPECT_CF_COMMON_CHANGED, \
        "「变了的全落在一个库上」这件事不成立了——按库分那张表要重读"


@NEEDS_CORPUS
def test_第一条e_六个库各自的有效门槛(real_corpus):
    """⚠️ **兜底只在 20–333 那一档没兜住**，而真实用户正落在那一档。
    ≤20 unit 的库上 `MIN=20` 本来就够不着（探针 0/14），≥333 unit 的库上它本来就不绑定。"""
    from app.database.kite.kite_memory import UserMemory
    probes = ("众筹", "硬件", "工作", "手环", "ai", "app", "memory",
              "2026", "agent", "产品", "设计", "记录", "使用", "连接")
    got = {}
    for user in RR.users_with_codebook():
        m = UserMemory(user)
        store, _v = m._index()
        idx = m._grep_index(store)
        fn = m.common_term()
        got[user] = (idx.unit_count, sum(1 for t in probes if fn and fn(t)))
    # ⚠️ **P84 之后 `terrence-rewrite` 那一格从 14 掉到 8**：df 那道门一格没动
    # （14 个探针 14 个照样过 df，闸在 `test_p81::第一条f`），掉的是 P84 那条轴
    # 从 `common` 手里捞回来的六个串。**「兜底只在 20–333 那一档没兜住」这条判照旧成立**
    # ——它说的正是 df 那道门，而 P84 补的就是那一档。
    assert got == {"fresh678": (2, 0), "fresh678b": (2, 0), "fresh678c": (2, 0),
                   "shot-demo": (11, 0), "terrence": (2362, 6),
                   "terrence-rewrite": (193, 8)}, got
    # MIN 是不是绑定约束，就是「库大小 × 6% 够不够得着 20」这一句
    assert R.COMMON_DF_MIN / R.COMMON_DF_RATIO == pytest.approx(333.33, abs=0.01)


@NEEDS_CORPUS
def test_第一条f_这一刀为什么退回_那几个口水串今天只有common挡着(real_corpus):
    """**根因，不是猜的**：关掉 `common` 之后冒出来当证据的那几串，
    在 193 unit 的库上 `_is_cn_filler` **一个都不认**，今天挡住它们的只有 `common`；
    同样这几串在 2362 unit 的真库上 df 本来就低，那边谁都不挡也没事。
    **这一格一翻，「换不了」那条判就得重读。**"""
    from app.database.kite.kite_memory import UserMemory
    small = UserMemory("terrence-rewrite").common_term()
    big = UserMemory("terrence").common_term()
    for t in ("因此", "团队", "说明", "消费者", "连接"):
        assert not kb_search._is_cn_filler(t), f"{t!r} 进了口水词表——根因要重读"
        assert big(t) is False, f"{t!r} 在 2362 unit 的真库上也成了 common"
    # ⚠️ **P84 之后这五串在小库上分成了两档，照实钉**：那条「泛词 vs 主题词」的轴
    # 认出了 `因此`(spread 0.97) / `团队`(0.77) / `说明`(0.77) 是泛词 —— **P82 的根因
    # 在这三串上成立，而且现在是被那条轴顶着，不再只靠 df**；
    # 而 `消费者`(0.72) / `连接`(0.68) 被判「不泛」捞了回来。
    # **P82 那条「换不了」的判不受影响**（它判的是「只按库大小关掉整条判据」那个旋钮，
    # 49 条逐条读的结论一个字没改）；变的是「谁在挡这五串」。
    for t in ("因此", "团队", "说明"):
        assert small(t) is True, f"{t!r} 在 193 unit 的库上不再是 common——根因要重读"
    for t in ("消费者", "连接"):
        assert small(t) is False, f"{t!r} 没被 P84 那条轴捞回来——那 28 条标注要重读"
    # `如果` / `用户` 两个库上都是 common —— **对照**：不是每一串都只有小库挡
    assert small("如果") and big("如果")
    assert small("用户") and big("用户")


# ── ② quorum 有多脆：量完了，没改 ──────────────────────────────────────────

def test_第二条_那四个数钉进了尺子():
    """**先量别急着改**：这一批只把 quorum 的分量钉下来。"""
    # ⚠️ **P84 之后这五个数各抬了一点**：那条「泛词 vs 主题词」的轴在小库上多放了
    # 63 个串进证人名单，于是这道门多被问了几趟。**P82 ② 那条判一个字没变**——
    # 84.0% → 84.1%、74.2% → 74.3%，**换的是分母，不是形状**。
    assert EG.EXPECT_QUORUM_CALLS == 375963      # P84 之前 375864
    assert EG.EXPECT_QUORUM_TRUE == 1821         # P84 之前 1771
    assert EG.EXPECT_QUORUM_EDGE == 1531         # P84 之前 1488
    assert EG.EXPECT_QUORUM_REJECT_AT_2 == 11    # **这一个一格没动**
    assert EG.EXPECT_QUORUM_SHOWN == (1367, 301, 792, 1066)   # P84 之前 (1347, 298, 778, 1049)
    # **84.1% 就是这条判本身**（算术，不是又抄一个数）；P84 之前那一版是 84.0%
    assert round(EG.EXPECT_QUORUM_EDGE / EG.EXPECT_QUORUM_TRUE * 100, 1) == 84.1
    assert round(1488 / 1771 * 100, 1) == 84.0
    shown, short, edge, managed = EG.EXPECT_QUORUM_SHOWN
    assert short + managed == shown, "用户眼前那一档三个数对不上"
    assert round(edge / managed * 100, 1) == 74.3      # P84 之前 74.2
    assert round(778 / 1049 * 100, 1) == 74.2          # P82 当时那一版
    # ⚠️ 1347 是 P77 起每批都在对的那个数，**P84 把它抬到 1367**——
    # 那条轴在小库上多捞回 20 对召回。它一动说明的**正是召回本身变了**，
    # 而这一整节要说的「quorum 有多脆」那个形状（84% / 74%）反倒一格没动。
    assert shown == 1367


def test_第二条b_quorum就是那一行_而且它只有2():
    """**「文件里有这个串」≠「这段代码还在跑」**，所以这一格量的是**行为**不是文本。
    quorum = `len(cl) < LONG_QUERY_MIN_WORDS → False`，而那个数是 2。"""
    assert kb_search.LONG_QUERY_MIN_WORDS == 2
    # 一条证人：门再松也 False；两条：够了（`decide` 是 `_strong_enough` 的逐行抄件）
    assert EG.decide(["华为"], [2], 3) is False
    assert EG.decide(["华为", "阿里"], [2, 2], 3) is True
    # **少一条就翻**：这就是那 1488 次的形状
    assert EG.decide(["华为", "阿里"], [2, 2], 3) != EG.decide(["华为"], [2], 3)
    # 源码那一行还在（`check_source` 顺带核 `LONG_QUERY_MIN_WORDS != 2` 就红）
    assert EG.check_source() == []


def test_第二条c_几乎同一条查询判反_没那么脆():
    """⚠️ **预测错了照实记**：任务书按 P81 ④ 的形状猜「quorum 脆在查询对上」，
    量下来 79 对前缀查询里**长的那条中位多出 78% 的正文**——那不叫「几乎同一条」。
    收紧到「只多出 ≤25%」全库只剩 4 次翻盘。**真正的脆在 84.0%，不在那个 47%。**
    这一格钉的是**那段话写在尺子上**（它是这一条判的全部内容）。"""
    src = pathlib.Path(EG.__file__).read_text(encoding="utf-8")
    for need in ("79 对", "132/281 = 47.0%", "中位多出 78%", "只剩 4 次翻盘",
                 "真正的脆在上面那个 84.0%"):
        assert need in src, f"`en_gate_ruler` 那段注释里找不到 {need!r}"


# ── ③ `_terms` 摆出用户没打完的串：形状记错了 ───────────────────────────────

def test_第三条_那四个数钉进了尺子():
    assert K.EXPECT_SHOWN_TOTAL == 108
    assert K.EXPECT_PARTIAL_SHOWN == 0
    assert K.EXPECT_DATEWRITE_SHOWN == 2
    assert K.EXPECT_DATEWRITE_PARTIAL == 2
    assert len(K.DATE_WRITINGS) == 20 and len(set(K.DATE_WRITINGS)) == 20
    assert K.EXPECT_DATEWRITE_PARTIAL == K.EXPECT_DATEWRITE_SHOWN, \
        "日期写法那一档摆出来的每一串都名不副实——这件事不成立了就得重读"


def test_第三条b_那个截断串够不着屏幕_判的是行为不是文本():
    """`_number_terms` **确实**切出 `9月14`（P81 记的那一半是对的），
    可 `UserMemory.recall()` 回的 `terms` 是 `surfaces + _cjk_terms(query)[:3]`
    ——**`_number_terms` 一个字都进不去**，而那条路是唯一真渲染那一行的。"""
    assert kb_search._number_terms("9月14日") == ["9月14"]
    assert kb_search._number_terms("2026-09") == ["2026"]
    assert kb_search._number_terms("2025/10/27") == ["2025"]
    import inspect
    import textwrap
    from app.database.kite.kite_memory import UserMemory
    src = textwrap.dedent(inspect.getsource(UserMemory.recall))
    assert "_number_terms" not in src, "`recall()` 开始收数字了——第三条的判要重读"
    assert "surfaces = surfaces + self._cjk_terms(query)[:3]" in src
    # `/recall` 那一头把 `terms` 交给 `display_terms` 的接线也钉着
    router = (ROOT / "backend" / "app" / "routers" / "memory.py").read_text(encoding="utf-8")
    assert "terms=search.display_terms(terms, body.query, segment=mem.segment())" in router


def test_第三条c_partial_shown那个判据自己先喂反例():
    """**任何「核对」先喂它一个该红 / 该绿的反例。** 这一组喂的是假的 shown + 假的查询。"""
    # 该红：屏幕只摆了 `美元`，用户打的是 `179美元`，整串没同行摆着
    assert K.partial_shown(["美元"], "179美元") == [("179美元", "美元")]
    assert K.partial_shown(["万台"], "1万台") == [("1万台", "万台")]
    # 该绿：整串自己摆着
    assert K.partial_shown(["179美元"], "179美元") == []
    # 该绿：整串**同行也摆着**（`命中词：ai、极梦ai`）——那不是没打完
    assert K.partial_shown(["ai", "极梦ai"], "极梦ai") == []
    # 该绿：两个词的查询，各摆各的
    assert K.partial_shown(["广州", "深圳"], "广州 深圳") == []
    # 该绿：什么都不摆
    assert K.partial_shown([], "9月14日") == []
    # **对照**：摆了一个查询里根本没有的串 → 这个判据不管它（`EXPECT_UNASKED` 管）
    assert K.partial_shown(["潜水艇"], "羽毛球") == []


@NEEDS_CORPUS
def test_第三条d_用户眼前那一行_20种日期写法逐条(real_corpus):
    """**用户可见的对比，摆出来而不是说出来。**
    「找过：9月14」跟「找过：9月14日」**哪个更诚实——都不诚实**：
    这条路上 `terms` 是空的，那一行整段不渲染，而后端确实什么都没找过。"""
    from app.database.kite.kite_memory import UserMemory
    m = UserMemory(K.USER)
    rows = K.date_writings(m)
    assert len(rows) == 20
    shown_total = sum(len(r["shown"]) for r in rows)
    partial = [r for r in rows if r["partial"]]
    assert shown_total == K.EXPECT_DATEWRITE_SHOWN == 2
    assert len(partial) == K.EXPECT_DATEWRITE_PARTIAL == 2
    assert [(r["q"], r["shown"]) for r in partial] == [("179美元", ["美元"]), ("1万台", ["万台"])]
    # **那个截断串一次都没上过屏**
    by_q = {r["q"]: r for r in rows}
    assert by_q["9月14日"]["num"] == ["9月14"] and by_q["9月14日"]["shown"] == []
    assert by_q["2026-09"]["num"] == ["2026"] and by_q["2026-09"]["shown"] == []
    # 用户眼前那一行：0 结果 + terms 空 = 整段不渲染（`KbDashboard` 那一行 `hits.terms.length`）
    assert by_q["9月14日"]["n"] == 0
    dash = (ROOT / "frontend" / "src" / "components" / "kb"
            / "KbDashboard.tsx").read_text(encoding="utf-8")
    line = next(ln for ln in dash.splitlines() if "hits.terms.slice(0, 6)" in ln)
    assert "hits.terms.length ?" in line, "那一行不再先看 terms.length 决定摆不摆"


@NEEDS_CORPUS
def test_第三条e_那110条上一条都没有(real_corpus):
    from app.database.kite.kite_memory import UserMemory
    m = UserMemory(K.USER)
    got = K.measure(m)
    rows = got["rows"]
    assert sum(len(r["shown"]) for r in rows) == K.EXPECT_SHOWN_TOTAL == 108
    assert [r["q"] for r in rows if r["partial"]] == []


# ── 登记表：新钉的这 15 个数一个都不许漏 ────────────────────────────────────

def test_新钉的数全登记了_而且那把尺自己是绿的():
    """**P80 造的那条规矩**：新加一个闸门常数不登记 = 当场红。
    这一批加了 15 个，跑之前先亲眼看见它把 15 个全报出来了（照实记，那是「该红的反例」）。"""
    for key in (("backend/scripts/recall_ruler.py", "EXPECT_BY_LIB"),
                ("backend/scripts/recall_ruler.py", "EXPECT_CF_COMMON_CHANGED"),
                ("backend/scripts/recall_ruler.py", "EXPECT_CF_COMMON_DROP"),
                ("backend/scripts/recall_ruler.py", "EXPECT_CF_COMMON_ADD"),
                ("backend/scripts/recall_ruler.py", "EXPECT_CF_COMMON_HIT"),
                ("backend/scripts/recall_ruler.py", "EXPECT_CF_COMMON_LIBS"),
                ("backend/scripts/en_gate_ruler.py", "EXPECT_QUORUM_CALLS"),
                ("backend/scripts/en_gate_ruler.py", "EXPECT_QUORUM_TRUE"),
                ("backend/scripts/en_gate_ruler.py", "EXPECT_QUORUM_EDGE"),
                ("backend/scripts/en_gate_ruler.py", "EXPECT_QUORUM_REJECT_AT_2"),
                ("backend/scripts/en_gate_ruler.py", "EXPECT_QUORUM_SHOWN"),
                ("backend/scripts/kb_search_ruler.py", "EXPECT_SHOWN_TOTAL"),
                ("backend/scripts/kb_search_ruler.py", "EXPECT_PARTIAL_SHOWN"),
                ("backend/scripts/kb_search_ruler.py", "EXPECT_DATEWRITE_SHOWN"),
                ("backend/scripts/kb_search_ruler.py", "EXPECT_DATEWRITE_PARTIAL")):
        assert key in FR.REGISTRY, f"{key} 没登记"
        kind, _base, why = FR.REGISTRY[key]
        assert kind == FR.PINNED
        assert len(why) > 30, f"{key} 的「一动要去重读什么」写得太短"
    assert FR.main(["--quiet"] if False else []) == 0
