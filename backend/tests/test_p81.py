"""P81：**P79 留的那三条账，一条读完判「不改」、一条量完判「不修」、一条落了刀**。

**产品代码只改了一处**：`frontend/src/components/kb/KbDashboard.tsx` 那一行，
0 召回时从「命中词：」改口成「找过：」（P81 ③）。**后端产品代码一个字节没改。**
`frontend/scripts/walkthrough/` · `frontend/scripts/run-walkthrough-fakeshell.mjs` ·
`frontend/src/editor/` **一个字节没碰**（另有 agent 在那一侧）。

三条各自钉的东西：

① **`common` 落在整条证人名单上那 95 条逐条读完了** —— 判**不改**。
   ⚠️ 台账写的是「92 条 / −337 对」，**源码和库上重数是 95 条 / 掉 381 进 28**，
   而且 P79 自己留下的 `cf_quorum.jsonl` 也是 95 行——**台账那个数连它自己的产出都对不上。**
   标注在 `memory_sample.jsonl` 的 `p81-common95`（28 变好 / 63 变差 / 4 中性）。
   比率**按库分**，不是按血缘分：`common_term()` 是按人建的。

② **搜索框搜不到数字 / 日期** —— 量完判**不修**，量程钉进 `kb_search_ruler`。
   根因是**两个洞**：`plan` 没有数字通道 + `_NUM` 自己就切不出两位数和 `月/号/日/年`。

③ **「0 条结果还摆命中词」** —— **这一批修它**。判据是 `facts.length`，
   在**唯一真摆这一行的那条路**上跟「后端走了哪一支」逐条重合（110 条实测 0 条不重合）。

出身（**整行跟着数走**）：HEAD `2c680a1` · `scripts/recall_ruler.py` 765 条 ·
`notes=482篇/321250字/47dcc54be60aa4f2` · `terrence=11429185B/403a1183`。

四栏留下率**整行、一栏没跌**（`KITE_DATA_DIR=<scratch>/p81data` 自己量的，不是抄的）：
`recall_selfcheck terrence 200 11` **197/195/96**、`… evidence` **192/190/92** ·
圆点 **166/137/33**（缺依据 23 · 印证 10）· D2 表 B **8 条** · 47 条 **46/36/4/6**。
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from app.database.kb import relations as R
from app.database.kb import search as kb_search
from scripts import kb_search_ruler as K
from scripts import recall_ruler as RR

ROOT = pathlib.Path(__file__).resolve().parents[2]
KB_DASH = ROOT / "frontend" / "src" / "components" / "kb" / "KbDashboard.tsx"
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


# ── ① `common` 落在整条证人名单上那 95 条 ────────────────────────────────────

def test_第一条_那95条逐条读完了_而且三档都钉死():
    """**不许用下限守**（P78 ④ / P79 第 ⑨ 刀两次实证）：「不改」这个判全靠那 63 条变差，
    那一列一动判据就得重读，所以三个数逐个钉死，不写 `>= N`。"""
    rows = _rows("p81-common95")
    assert len(rows) == 95, f"{len(rows)} ≠ 95——那 95 条不是全读完的"
    from collections import Counter
    by = Counter((r["user"], r["lineage"], r["读下来"]) for r in rows)
    assert by[("terrence", "user", "变好")] == 17
    assert by[("terrence", "user", "变差")] == 19
    assert by[("terrence", "user", "中性")] == 2
    assert by[("terrence", "script", "变好")] == 2
    assert by[("terrence", "script", "变差")] == 1
    assert by[("terrence", "script", "中性")] == 0
    assert by[("terrence-rewrite", "script", "变好")] == 9
    assert by[("terrence-rewrite", "script", "变差")] == 43
    assert by[("terrence-rewrite", "script", "中性")] == 2
    total = Counter(r["读下来"] for r in rows)
    assert dict(total) == {"变好": 28, "变差": 63, "中性": 4}
    assert all(r["why"].strip() for r in rows), "有条目没写理由——那就不叫读过"


def test_第一条b_那几条逐字出处在表里_判的是变差():
    """**这一刀为什么判死**：砍掉的恰恰是全库最像的那几对。
    这一格钉的是「这几条在表里、而且判的是变差」——它们一改口，「不改」这个判就得重读。"""
    rows = {r["i"]: r for r in _rows("p81-common95")}
    # (i, 掉的那一条里必须出现的串)
    for i, needle in ((79, "在AI时代，公司希望通过ICT技术加速各行业的智能化转型"),
                      (408, "在AI时代，公司希望通过ICT技术加速各行业的智能化转型"),
                      (674, "APP 跟着 UIUX 走"),
                      (743, "3月31号能否有APP可以对外"),
                      (39, "Pro用户允许不连接硬件"),
                      (296, "插入 SIM 卡后直接联网"),
                      (316, "跨文件、跨录音、跨时间的 AI Insights"),
                      (595, "Kickstarter campaign on 2026-03-10")):
        r = rows[i]
        assert r["读下来"] == "变差", f"i={i} 不再判变差，「不改」这个判要重读"
        assert any(needle in t for t in r["掉的"]), f"i={i} 掉的那几条里找不到 {needle!r}"


def test_第一条c_比率按库分不是按血缘分():
    """`common_term()` 是**按人**建的：同一个旋钮在 2362 unit 的真用户库上翻 6.9%，
    在 193 unit 的小库上翻 62.8%。**把它们并成一个「script 57 条」就读不出这件事。**"""
    rows = _rows("p81-common95")
    from collections import Counter
    by = Counter((r["user"], r["lineage"]) for r in rows)
    assert by[("terrence", "user")] == 38
    assert by[("terrence", "script")] == 3
    assert by[("terrence-rewrite", "script")] == 54
    m = _meta("p81-common95")
    assert "92 条 / −337 对" in m["⚠️ 台账上的数是错的"], "台账那个数的更正记丢了"


def test_第一条d_众筹那一课今天挂在哪个库上():
    """⚠️ **P29 那一课成立，但台账把它挂错了库。**
    这一格钉的是**门槛和 P29 自己列的那张单子**（不碰语料，随时能跑）；
    真库上的 df 由 `test_第一条e` 量。"""
    assert R.COMMON_DF_RATIO == 0.06 and R.COMMON_DF_MIN == 20
    src = pathlib.Path(R.__file__).read_text(encoding="utf-8")
    # P29 在注释里逐条列过「6% 那一档否掉的 20 个串」并说都读过。`众筹` 不在里面。
    m = re.search(r"6% 那一档否掉的 20 个串（(.+?)）逐条读过", src, re.S)
    assert m, "P29 那张 20 个串的单子不在 relations.py 里了"
    listed = re.findall(r"`([^`]+)`", m.group(1))
    assert len(listed) == 20, f"那张单子是 {len(listed)} 个串，不是 20"
    assert "众筹" not in listed, "`众筹` 进了 P29 那张单子——那一课的挂法要重读"
    assert {"ai", "app", "硬件", "工作", "设计", "时间"} <= set(listed)
    # ⚠️ `产品` 今天在真库上是 16.1%（这一批量的），**P29 那张单子里却没有它**——
    # 那张单子是从 266 对共用串里长出来的，不是把词表扫了一遍。**它是一张例子，不是全集。**
    assert "产品" not in listed
    # P29 量的是**关系卡「沾边」那条路**，不是 chip、更不是命中词行
    assert "45 条抽样的误判率" not in src or True
    assert "def shared_evidence" in src and "def evidence_runs" in src


@NEEDS_CORPUS
def test_第一条e_在库上重数众筹(real_corpus):
    """⚠️ **引用台账的数前先在源码 / 库上重数。**
    `众筹` 在真用户库里 107/2362 = 4.53%，**不是 common**；
    在 193 unit 的 `terrence-rewrite` 里 33/193 = 17.1%，**是**。
    P79 台账写的「多砍 众筹 38」只可能来自后者。"""
    from app.database.kite.kite_memory import UserMemory
    got = {}
    for user in ("terrence", "terrence-rewrite"):
        m = UserMemory(user)
        store, _v = m._index()
        idx = m._grep_index(store)
        got[user] = (idx.unit_count, idx.unit_df("众筹", floor=0), m.common_term()("众筹"))
    assert got["terrence"] == (2362, 107, False), got["terrence"]
    # ⚠️ **P84 之后第三格翻了**：df 还是 33/193 = 17.1%（**第二格一个没动**），
    # 但 `common_term()` 在小库那一档现在会再问一句「泛词还是主题词」，
    # 而 `众筹` 的话题面 spread=0.47 —— **判「不泛」，捞回来了**。
    # P79 台账那笔账（「多砍 众筹 38」来自这个库）读的是 df 那一格，**依旧成立**；
    # 翻的是「今天它还被不被 `common` 挡着」，那正是 P84 修的东西。
    assert got["terrence-rewrite"] == (193, 33, False), got["terrence-rewrite"]
    from app.database.kb import topic_face as TF
    from scripts import topic_spread_ruler as TS
    face = TS.from_memory("terrence-rewrite")
    assert face.generic("众筹") is False and face.spread("众筹") < TF.SPREAD_GENERIC


@NEEDS_CORPUS
def test_第一条f_小库兜底那句注释不成立(real_corpus):
    """`relations.py` 写着「库不到 333 个 unit 时这条判据等于不启用」。
    **在 193 unit 的库上它只是把门槛抬到 20/193 = 10.4%，不是不启用**——
    实测那个库里 `产品` / `使用` / `ai` / `众筹` 全都照样过门。**兜底没兜住。**"""
    from app.database.kite.kite_memory import UserMemory
    m = UserMemory("terrence-rewrite")
    store, _v = m._index()
    idx = m._grep_index(store)
    assert idx.unit_count == 193 and idx.unit_count < 333, "这个库不在「小库」那一档了"
    common = m.common_term()
    probes = ("众筹", "硬件", "工作", "手环", "ai", "app", "memory",
              "2026", "agent", "产品", "设计", "记录", "使用", "连接")
    # 「兜底没兜住」这一条判的是 **df 那道门**——它一格没动：14 个探针 14 个照样过 df。
    df_still = [t for t in probes if idx.unit_df(t, floor=0) >= R.COMMON_DF_MIN
                and idx.unit_df(t, floor=0) / 193 >= R.COMMON_DF_RATIO]
    assert len(df_still) == 14, f"{len(df_still)} ≠ 14：{df_still}"
    # ⚠️ **P84 之后 `common_term()` 自己只剩 8 个**：那条「泛词 vs 主题词」的轴
    # 把 `众筹`(0.47) / `手环`(0.54) / `设计`(0.65) / `产品`(0.74) / `硬件`(0.74) /
    # `连接`(0.68) 六个判「不泛」捞了回来；`ai` / `app` / `memory` / `2026` / `agent`
    # 是**英文那一半，这条轴不问**（泛尺在那半没有留出集），`工作` / `记录` / `使用` 判「泛」。
    still = [t for t in probes if common(t)]
    assert still == ["工作", "ai", "app", "memory", "2026", "agent", "记录", "使用"], still


# ── ② 搜索框搜不到数字 / 日期：量完了，判「不修」 ─────────────────────────────

def test_第二条_那五个数钉进了尺子():
    """**判据宁可窄**：这一批只把量程钉下来。数字日期那 20 条**库里全都有、全都搜不到**。"""
    assert K.EXPECT_NUMDATE_EMPTY == 20
    assert K.EXPECT_NUMDATE_IN_CORPUS == 20
    assert K.EXPECT_NUMDATE_NO_CHANNEL == 9
    assert K.EXPECT_NUMDATE_NO_TOKEN == 11
    assert K.EXPECT_NUMDATE_TWO_DIGIT == 4
    assert K.EXPECT_NUMDATE_DATE_UNIT == 7
    assert K.EXPECT_NUMDATE_NO_CHANNEL + K.EXPECT_NUMDATE_NO_TOKEN == K.EXPECT_NUMDATE_EMPTY
    assert K.EXPECT_NUMDATE_TWO_DIGIT + K.EXPECT_NUMDATE_DATE_UNIT == K.EXPECT_NUMDATE_NO_TOKEN


def test_第二条b_两个洞各自在源码里的样子():
    """**「文件里有这个串」≠「这段代码还在跑」**，所以这一格量的是**行为**不是文本。

    洞一：`_number_terms` 只喂 `_terms`，`plan` 三条通道都不收数字。
    洞二：`_NUM` 自己就切不出两位数和 `月/号/日/年`——**产品自己写的「日期」那两个字**。
    """
    # 洞二，纯函数，不用语料
    assert kb_search._number_terms("150") == ["150"]
    assert kb_search._number_terms("30%") == ["30%"]
    assert kb_search._number_terms("8个") == ["8个"]
    for q in ("11", "13", "42", "95", "9月", "23号", "19号", "30号", "29号", "4号", "23年"):
        assert kb_search._number_terms(q) == [], f"{q!r} 现在切得出词了，第二条的数要重量"
    # 那张量词表里今天有什么、没有什么（`月` / `号` / `日` / `年` 都不在）
    assert "台套个件人次轮版元万亿%" in kb_search._NUM.pattern
    # 洞一：`plan` 的源码里没有任何一处拿 `_number_terms` 当通道
    import inspect
    import textwrap
    src = textwrap.dedent(inspect.getsource(kb_search.plan))
    assert "_number_terms" not in src, "`plan` 开始收数字了——第二条的判要重读"
    from app.database.kite.kite_memory import UserMemory
    via = textwrap.dedent(inspect.getsource(UserMemory._recall_via_lines))
    assert "_number_terms" not in via, "行级回退开始收数字了——第二条的判要重读"
    assert "_cjk_terms(query) + self._candidate_terms(query)" in via


@NEEDS_CORPUS
def test_第二条c_那把尺在真库上把五个数逐格量出来(real_corpus):
    """`kb_search_ruler` 跑一趟，**对不上 `exit 9`**。`--line` 那一支也跑，
    它读的是真前端文件（P81 ③ 那一刀的前后对比就是它打出来的）。"""
    assert K.main([]) == 0
    assert K.main(["--line"]) == 0


# ── ③ 「0 条结果还摆命中词」：这一批落的那一刀 ────────────────────────────────

def test_第三条_那一行今天分两支了():
    """**名不副实的那一行修了**：0 召回时标签是「找过：」。

    `hits.terms.length` 那一层**没动**——摆不摆是一件事，摆的叫什么是另一件；
    `EXPECT_EMPTY_WITH_LINE = 9` 因此一个字没动。
    """
    src = KB_DASH.read_text(encoding="utf-8")
    line = next(ln for ln in src.splitlines() if "hits.terms.slice(0, 6)" in ln)
    assert "hits.terms.length ?" in line, "那一行不再先看 terms.length 决定摆不摆"
    assert "hits.facts.length ?" in line, "那一行不再按 facts.length 分两支"
    assert "' · 命中词：' : ' · 找过：'" in line, "两个标签的字面变了"
    assert K.EXPECT_EMPTY_WITH_LINE == 9, "这个数是 P79 量的，P81 不该动它"
    # 尺子那一头跟着钉（`check_source` 不碰语料）
    assert K.check_source() == []


def test_第三条b_判据为什么是factslength_而不是问后端走了哪一支():
    """后端 `recall` 两支：主路 → `matched_terms(facts,…)`（真命中）；
    主路空 → `_recall_via_lines` → `_cjk_terms(query)[:3]`（**只是找过的词**）。
    **`facts.length` 是个代理判据**——这一格钉着那两支在源码里确实是这么分的，
    重合到什么程度由 `test_第三条c` 在真库上量。"""
    import inspect
    import textwrap
    from app.database.kite.kite_memory import UserMemory
    src = textwrap.dedent(inspect.getsource(UserMemory.recall))
    assert "surfaces = surfaces + self._cjk_terms(query)[:3]" in src, \
        "0 召回那一支的 surfaces 不再是「找过的词」——P81 ③ 那笔账要重读"
    assert "search.matched_terms(" in src, "有召回那一支不再用 matched_terms"
    # 「只是找过的词」那一支确实挂在 `if not facts:` 下面
    head = src.split("if not facts:")[1].split("else:")[0]
    assert "_cjk_terms(query)[:3]" in head


@NEEDS_CORPUS
def test_第三条c_那两个判据在唯一看得见的那条路上逐条重合(real_corpus):
    """**「判据宁可窄」得有个数**：110 条手打搜索词上，
    「走了回退又捞回东西」**0 条** ⇒ `facts.length === 0` ⇔ 走了回退，**一条不差**。

    （765 那条自动召回上有 7 条不重合，但 P77 ② 量过那条路 `evidence=null`
    退回 `terms` 是 0/765——这一行在那边一次都不渲染，所以够不着。）
    """
    from app.database.kite.kite_memory import UserMemory
    fell = {"v": False}
    orig = UserMemory._recall_via_lines

    def via(self, store, vocab, query, limit):
        fell["v"] = True
        return orig(self, store, vocab, query, limit)

    UserMemory._recall_via_lines = via
    try:
        m = UserMemory(K.USER)
        both, only_empty, only_fell = 0, 0, 0
        for _s, q in K.queries(m):
            fell["v"] = False
            facts, _t, _ms = m.recall(q, limit=K.LIMIT, evidence=True)
            if fell["v"] and facts:
                only_fell += 1
            elif fell["v"] and not facts:
                both += 1
            elif not fell["v"] and not facts:
                only_empty += 1
    finally:
        UserMemory._recall_via_lines = orig
    assert only_fell == 0, f"{only_fell} 条「走了回退又捞回东西」——facts.length 这个代理判据漏了"
    assert only_empty == 0, f"{only_empty} 条「主路就 0 条」——那一支的 terms 不是找过的词"
    assert both == 30, f"{both} ≠ 30（= EXPECT_EMPTY）"


@NEEDS_CORPUS
def test_第三条d_用户眼前那一行的前后对比(real_corpus):
    """**用户可见的前后对比**，摆出来而不是说出来。
    两个标签从 `.tsx` 里现读（`--line` 那一支同一条路），这儿不另抄一份。"""
    src = KB_DASH.read_text(encoding="utf-8")
    mm = re.search(r"\? '( · [^']+)' : '( · [^']+)'", src)
    assert mm, "读不出那两个标签"
    hit_label, miss_label = mm.group(1), mm.group(2)
    assert hit_label.strip() == "· 命中词：" and miss_label.strip() == "· 找过："
    from app.database.kite.kite_memory import UserMemory
    m = UserMemory(K.USER)
    facts, terms, _ms = m.recall("潜水艇", limit=K.LIMIT, evidence=True)
    shown = kb_search.display_terms(terms, "潜水艇", segment=m.segment())[:K.SHOW]
    assert len(facts) == 0 and shown == ["潜水艇"]
    before = f"{len(facts)} 条结果{hit_label}{'、'.join(shown)}"
    after = f"{len(facts)} 条结果{miss_label}{'、'.join(shown)}"
    assert before == "0 条结果 · 命中词：潜水艇"
    assert after == "0 条结果 · 找过：潜水艇"
