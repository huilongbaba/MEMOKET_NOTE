"""P86：**大库那 175 条读完了（判「不接」）** + **那条轴分不开两种「窄」（判「分不开」）**
+ **i=293 的真根因查清了（更正 P84 ⑥，判「不改」）**。

三条账，**产品的判据一个字节没改**——这一批改的是**量具、文档和登记**：
`recall_ruler.py` 多了一支 `--cf-bigcorpus`（P84 ⑤ 那个 175 的量具，**两个旋钮分开跑**），
`kb/topic_face.py` 文件头多了第 ④⑤ 格（大库的判、五个候选信号的表），
`kite_memory._cjk_terms` 的 docstring 多了「那 16 是整屏变空的真根因」那一节。

① **大库那 175 条**（收 P84 ⑤）。P84 只量了形状没读；这一批读完了，而且**先把那 175 拆开**：
   它是**两道闸一起拆**量出来的，而「大库接不接」只该看**只拆库大小闸**那一档。

   | 拆哪道闸 | 全库变了 | 落在 | 大库那几条 |
   |---|---:|---|---|
   | 只拆库大小（汉字闸留着）| 53 | `terrence` 25 · `terrence-rewrite` 28 | **变好 8 / 中性 7 / 变差 10** |
   | 两道闸全拆 | **175** | `terrence` **134** · `terrence-rewrite` 41 | **变好 14 / 中性 27 / 变差 93** |

   **小库 14:7（两倍）· 大库 8:10（净亏）——形状是相反的，不是变淡 → 判「不接」。**
   标注 `p86-bigsize-25`（判据那一组）和 `p86-bigcorpus-175`（上界那一组）。

② **那条轴分不开两种「窄」**（收 P84 ②）。五个候选信号喂了两批反例：
   S1 `own` / S2 `ride` / S3 `dup` / S5 加权话题大小 **全部分不开，而且 S2 是反着的**
   （`手环`/`佩戴` 骑库的头号话题，`agent`/`ai` 不骑）。根因：**单主题库里话题码本身就是
   产品专用的**，所以「串 → 话题多重集」对两种「窄」给出的是同一个形状——
   **要分开它们的信息不在 `topics` 里**。S6（跟库自己的主语同现）分得开，
   **但造不出来**：库里出现最多的实体码是 `app`（正是要挡的那几个串之一），
   大库里最多的是 `speaker_a/b/c`（根本没有主语）。**废掉的四版 + 造不出来的那一版都记在
   `kb/topic_face.py` 文件头第 ⑤ 格。**

③ **i=293**（收 P84 ⑥ / P82）。P84 记的「排名挤压（被挤出 top-8）」**是错的**：
   它基准上只有 **1 条**候选、变完 0 条，只有一条的时候没有「被谁挤出 top-8」这回事。
   真根因是 `_cjk_terms` 那 **16 个名额**：`公司` 被捞回来 → `大公司`/`公司病`/`公司运`
   进了实词档 → **把 `开安克` 挤出 16 个** → `离开安克` 合不成 `span`，
   `evidence` 退成 `('离开安', 'pair')` → `qualifies` + `_strong_enough` **两道闸同时翻**。
   **判「不改」**：能修它的旋钮就是那个 16，而它正是 P63 把 cap 24 那 190 对一条不落
   读完之后判「不改」的那一个。

出身（**整行跟着数走**）：HEAD `425bf41` · `scripts/recall_ruler.py` 765 条 ·
`notes=482篇/321250字/47dcc54be60aa4f2` · `terrence=11429185B/403a1183` ·
`terrence-rewrite=6594533B/8b6ba3bb`。

基线自己量的（`KITE_DATA_DIR=<scratch>/p86data`）：后端带 `KITE_DATA_DIR` **3205 / 0 skipped**、
不带 **3182 / 23 skipped**、前端 **97 文件 / 858 条**。

⚠️ 四栏对这三条**全是瞎的**（产品判据没动，四栏必然逐格相同）——
**四栏全绿在这一批说明不了任何事**，说明事的是 `--cf-bigcorpus` 那八个数和下面这几条闸。
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter

import pytest

from app.database.kb import search as S
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
    """`conftest._isolated_db` 把 codebook 指到临时目录——要真语料的测试自己指回去。
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
        if r.get("set") == set_name and "_meta" not in r and "什么" not in r:
            out.append(r)
    return out


def _meta(set_name: str) -> dict:
    for line in FIX.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("set") == set_name and "什么" in r:
            return r
    raise AssertionError(f"{set_name} 没有 _meta")


# ── ① 大库那一档：两个旋钮分开，判「不接」 ──────────────────────────────

def test_第一条_那175条的量具进了仓库_而且两个旋钮是分开的():
    """**量具躺在 scratch 里的账**（P63 那一课）：这一批的数必须有一份仓库里的实现能重跑出来。
    而且它得**把两个旋钮分开**——P84 那个 175 是两闸一起拆量出来的，混着读就判错。"""
    assert hasattr(RR, "cf_bigcorpus") and hasattr(RR, "_axis_variant")
    src = pathlib.Path(RR.__file__).read_text(encoding="utf-8")
    assert '"--cf-bigcorpus" in argv' in src, "这一支没接进 `main()`，跑 ruler 根本量不到"
    # **两个旋钮真的是两个**：`_axis_variant` 的两个实参各自独立
    # ⚠️ **P88 给它加了第三个实参 `ask_who`**，这两档**故意钉死 `ask_who=False`**：
    # 它们问的是「**P84 那条轴**拆闸会怎样」，而那 175 条就是在这个形状上读完的。
    # 带上 P88 那条主语面轴的话大库那一档会整片塌掉（`terrence` 的 `who` 93.8% 是
    # 说话人标签，主语面在那儿一律回 `None`），这张表就不是 P86 读过的那 175 条了。
    assert '_axis_variant(False, True, ask_who=False)' in src \
        and '_axis_variant(False, False, ask_who=False)' in src, \
        "`size` / `both` 两档不是用两套实参跑出来的——那就不是两个旋钮"
    # **接线自检不许被摘掉**：复刻的 HEAD 必须跟产品那一份对拍
    assert '_axis_variant(True, True)' in src and 'selfcheck_mismatch' in src, \
        "复刻 HEAD 的自检没了——量具接错层会静静地给出漂亮的数（P84 那一课）"
    assert 'if g["selfcheck_mismatch"]:' in src, "自检算了却没让它红"


def test_第一条b_那八个数逐个钉死_不写下限():
    """**不许用下限守**（P78 ④ / P79 第 ⑨ 刀两次实证）：「不接」这个判全靠
    `size` 那一档的 8 : 10，任何一个数动了判据就得重读，所以逐个钉死。"""
    assert RR.EXPECT_CF_BIG_SIZE_CHANGED == 53
    assert RR.EXPECT_CF_BIG_SIZE_ADD == 108
    assert RR.EXPECT_CF_BIG_SIZE_DROP == 33
    assert RR.EXPECT_CF_BIG_SIZE_LIBS == (("terrence", 25), ("terrence-rewrite", 28))
    assert RR.EXPECT_CF_BIG_BOTH_CHANGED == 175, "P84 ⑤ 记的那个 175"
    assert RR.EXPECT_CF_BIG_BOTH_ADD == 577
    assert RR.EXPECT_CF_BIG_BOTH_DROP == 80
    assert RR.EXPECT_CF_BIG_BOTH_LIBS == (("terrence", 134), ("terrence-rewrite", 41))
    # **两档必须对得上**：`size` 在小库那一行 = HEAD 那一支的 28（小库上这个旋钮不动它）
    assert dict(RR.EXPECT_CF_BIG_SIZE_LIBS)["terrence-rewrite"] == RR.EXPECT_CF_SPREAD_CHANGED
    # 175 = 134 + 41，两个库加起来就是全部（没有第三个库被够着）
    assert sum(n for _u, n in RR.EXPECT_CF_BIG_BOTH_LIBS) == RR.EXPECT_CF_BIG_BOTH_CHANGED
    assert sum(n for _u, n in RR.EXPECT_CF_BIG_SIZE_LIBS) == RR.EXPECT_CF_BIG_SIZE_CHANGED
    # **进 / 掉 的不对称本身就是判据**：7:1 说明它不是「多召回一点」，是把空屏灌满
    assert RR.EXPECT_CF_BIG_BOTH_ADD > 6 * RR.EXPECT_CF_BIG_BOTH_DROP


def test_第一条c_大库那25条读完了_而且三档逐个钉死():
    """判「不接」的全部分量就是这三个数。**8 : 10 是净亏**，一列一动就得重读。"""
    rows = _rows("p86-bigsize-25")
    assert len(rows) == 25, f"{len(rows)} ≠ 25——那 25 条不是全读完的"
    assert dict(Counter(r["读下来"] for r in rows)) == {"变好": 8, "中性": 7, "变差": 10}
    assert {r["user"] for r in rows} == {"terrence"}, "这一组只该装大库那一边"
    assert all(r["why"].strip() for r in rows), "有条目没写理由——那就不叫读过"
    # **方向判据**：变差 > 变好。这一条一翻，「不接」就得重判
    g = Counter(r["读下来"] for r in rows)
    assert g["变差"] > g["变好"], "大库那一档不再是净亏了——「不接」这个判要重读"


def test_第一条d_那175条读完了_按库分的三档逐个钉死():
    """**比率要按对的那条轴分**（按库，不是按血缘）——这一格就是 P81 ① 那一课。"""
    rows = _rows("p86-bigcorpus-175")
    assert len(rows) == 175, f"{len(rows)} ≠ 175——那 175 条不是全读完的"
    by = {u: dict(Counter(r["读下来"] for r in rows if r["user"] == u))
          for u in {r["user"] for r in rows}}
    assert by == {
        "terrence": {"变好": 14, "中性": 27, "变差": 93},
        "terrence-rewrite": {"变好": 10, "中性": 13, "变差": 18},
    }
    assert all(r["why"].strip() for r in rows), "有条目没写理由——那就不叫读过"
    # 大库那 134 条里 user 血缘 124 / script 10（**那是真实用户那条路**，重点在它）
    t = [r for r in rows if r["user"] == "terrence"]
    assert dict(Counter(r["lineage"] for r in t)) == {"user": 124, "script": 10}


def test_第一条e_变好变差两头各钉几条实打实的():
    """**绿有个数**：变好那一档钉「逐句出处真被捞回来了」，
    变差那一档钉「逐句出处被挤掉了 / 0 条变成一屏撞词」。这几条一改口，「不接」就得重读。"""
    rows = {r["i"]: r for r in _rows("p86-bigcorpus-175")}
    for i, needle in ((3, "境外的一些用户，特别是欧美用户的一些数据隐私安全"),
                      (81, "60多个主流大模型"),
                      (297, "软件是产品未来持续产生价值"),
                      (623, "预热页面")):
        assert rows[i]["读下来"] == "变好", f"i={i} 不再判变好"
        assert any(needle in t for t in rows[i]["进的"]), f"i={i} 进的里找不到 {needle!r}"
    # **代价那一栏**：两条逐字出处被挤掉，两条空屏被 `ai` 灌满
    for i in (78, 407):
        assert rows[i]["读下来"] == "变差"
        assert any("专注的领域主要是ICT" in t for t in rows[i]["掉的"]), \
            f"i={i} 掉的那条 ICT 逐字出处没了——**变差那一栏是这条判的分量**"
    for i in (118, 284):
        assert rows[i]["读下来"] == "变差" and rows[i]["条数"].startswith("0→")
        assert len(rows[i]["进的"]) == 8, f"i={i} 不再是「0 条 → 一整屏」"
    # **i=607 是 i=293 在大库上的同一张脸**：1→0，整屏变空
    assert rows[607]["读下来"] == "变差" and rows[607]["条数"] == "1→0"
    assert rows[293]["读下来"] == "变差" and rows[293]["条数"] == "1→0"


def test_第一条f_跟P84那41条读得不一样这件事照实记了():
    """**预测 / 口径差了就照实记**（P84 那 41 条读成 17:17，这一批重读是 10:18）。
    标注是冻下来的——P84 那 28 条一个字没改，差异写在这一组的 `_meta` 里。"""
    m = _meta("p86-bigcorpus-175")
    key = "跟 P84 ② 记的 41 条对不上的地方，照实记"
    assert "变好 17 / 变差 17" in m[key] and "变好 10 / 变差 18" in m[key]
    assert "屏没满时多进来一条弱噪声" in m[key], "口径差在哪没写清楚"
    assert "两边的判一样" in m[key]
    # P84 那一组**一个字没改**
    p84 = _rows("p84-spread-28")
    assert len(p84) == 28
    assert dict(Counter(r["读下来"] for r in p84)) == {"变好": 14, "变差": 7, "中性": 7}


def test_第一条g_大库的判写进了产品那份注释():
    """**判写在判据旁边**（这个仓的规矩）：下一个人改 `common_term()` 时得看见这张表。"""
    src = pathlib.Path(
        ROOT / "backend" / "app" / "database" / "kb" / "topic_face.py").read_text(encoding="utf-8")
    assert "大库那一档实测过了，判「不接」" in src
    assert "recall_ruler.py --cf-bigcorpus" in src, "量具在哪没写，下一批没法重跑"
    assert "8 / 中性 7 / 变差 10" in src and "14 / 中性 27 / 变差 93" in src
    assert "形状是相反的，不是变淡" in src, "「不是效果小一点，是方向不对」这句话没写"
    assert "p86-bigcorpus-175" in src, "标注在哪没写"


# ── ② 那条轴分不开两种「窄」：五个候选，四个分不开、一个造不出来 ─────────

def test_第二条_五个候选信号的表写进了产品那份注释_含废掉的那几版():
    """**废掉的版本照实记**（P75 废三版、P77 废两版都记了）。
    这一格尤其要记**方向**：S2 不是「差一点」，是**反着的**——下一批别再试它。"""
    src = pathlib.Path(
        ROOT / "backend" / "app" / "database" / "kb" / "topic_face.py").read_text(encoding="utf-8")
    for sig in ("S1 `own`", "S2 `ride`", "S3 `dup`", "S5 加权话题大小", "S6 跟**库自己的主语**同现"):
        assert sig in src, f"候选 {sig} 没记进去"
    assert "**反向**" in src, "S2 是反着的这件事没记——下一批会再试一遍"
    assert "要分开它们的信息不在 `topics` 里" in src, "根因那一句没写"
    assert "`app`（134）" in src and "speaker_a" in src, \
        "S6 造不出来的实测证据（库里最多的实体是 app / speaker_a）没记"
    assert "这个库是关于谁的" in src, "缺的那一块是什么没点名"


@NEEDS_CORPUS
def test_第二条b_S6那条分界线是真的量出来的_不是推的(real_corpus):
    """**先喂反例证明新信号在动**：两批反例各喂一批，S6 必须真的把它们分开。
    这一条钉的不是「要接 S6」（没接），钉的是**「它确实分得开」这个实测**
    ——下一批要是能把「库的主语」弄出来，这条分界线就是它的起点。"""
    import re

    from app.database.kite.kite_memory import UserMemory
    m = UserMemory("terrence-rewrite")
    store, _v = m._index()
    idx = m._grep_index(store)
    face = m._topic_face(store, idx)
    assert face is not None
    subj = re.compile(r"memo\s?ket|memo\s?cat|memu\s?ket|memo\s?cent|memocad|mmok", re.I)

    def cooc(term: str) -> float:
        rx = face._rx(term)
        hits = [f for f in face._pool(term) if rx.search(getattr(f, "text", "") or "")]
        assert hits, f"{term!r} 在这个库里一条都没命中——反例喂错了"
        return sum(1 for f in hits if subj.search(f.text or "")) / len(hits)

    # A = 该判「指着一个具体东西」的；B = 该判「整个库都在讲这件事」的
    a = {t: cooc(t) for t in ("众筹", "手环", "官网", "样机", "佩戴", "支付", "订阅", "录音")}
    b = {t: cooc(t) for t in ("agent", "ai", "memory", "app")}
    assert max(a.values()) < min(b.values()), f"S6 不再分得开：A={a} B={b}"
    assert min(b.values()) > 3 * max(a.values()), "间隔塌了，那条分界线不再稳"
    # **这条轴自己分不开**——两批反例的 spread 是重叠的，这正是 P84 ② 记下的那句话
    sa = [face.spread(t) for t in a]
    sb = [face.spread(t) for t in b]
    assert min(sb) < max(sa), "那条轴忽然分得开了？——P84 ② 那句话和这一批的结论都要重读"


@NEEDS_CORPUS
def test_第二条c_S6造不出来这件事是实测的(real_corpus):
    """**不许拿「出现最多的实体」当库的主语**：那会让 `app` 自己给自己背书。
    这一条把「造不出来」钉成实测，而不是一句推断。"""
    from app.database.kite.kite_memory import UserMemory
    for user, expect in (("terrence-rewrite", "app"), ("terrence", "speaker_a")):
        m = UserMemory(user)
        store, _v = m._index()
        c: Counter = Counter()
        for f in store.facts.values():
            for e in (getattr(f, "entities", None) or ()):
                c[e] += 1
        top = c.most_common(1)[0][0]
        assert top == expect, f"{user} 出现最多的实体码从 {expect!r} 变成 {top!r} 了——S6 那条判要重读"
    # 小库里真正的主语 `memocat` **排在 `app` 后面**，所以「取最多的」拿到的是错的那个
    m = UserMemory("terrence-rewrite")
    store, _v = m._index()
    c = Counter()
    for f in store.facts.values():
        for e in (getattr(f, "entities", None) or ()):
            c[e] += 1
    names = [k for k, _n in c.most_common(3)]
    assert "app" in names and "memocat" in names and names.index("app") < names.index("memocat")


# ── ③ i=293：真根因是那 16 个名额，不是排名挤压 ─────────────────────────

@NEEDS_CORPUS
def test_第三条_i293的真根因_一次只动一样(real_corpus):
    """**更正 P84 ⑥**。三个反事实钉着同一条因果链，**一刀只动一处**：

      C 对照：HEAD 原样                    → `开安克` 不在、`pair`、进不来
      A：只把 `公司` 单独按回 `common`      → `开安克` 回来、`span` 回来、进得来
      B：只把 `_cjk_terms` 那 16 抬到 17    → 同样全部回来

    A 和 B 都能救它，而两条路动的是**同一个东西**：那 16 个名额谁拿。

    ## ⚠️ P88 ② 把这条链的最前面那一环改掉了 —— **这一条整条重挂，一个断言没删**

    **并排读**：上面那三刀（C / A / B）说的话今天**一个字都还成立**，
    但它们的「HEAD 原样」指的是 **P88 之前**那一版 `common_term()`。
    P88 在 `common_term()` 里串了一条主语面轴（`kb/topic_face.WhoFace`），
    它判 `公司` 主语面 .900 ≥ `WHO_GENERIC` → **不再捞回来**，
    也就是**自动地做了 A 那一刀本来要手按的那件事**。

    所以这一条今天挂在 `p86_common`（= 那一版的逐字复刻，`ask_who=False`）上跑，
    三刀原样；末尾多一条断言：**今天的 HEAD 上 i=293 是好的**
    （`开安克` 在、`span` 在、`qualifies` 放行）——那正是这条链被治好的证据。
    """
    from app.database.kite.kite_memory import UserMemory
    qs = RR.queries()
    user, q, _mode, _o = qs[293]
    assert user == "terrence-rewrite" and "离开安克" in q
    assert len(q.strip()) >= S.LONG_QUERY, "它不再是长查询了，`_strong_enough` 那道闸就不开了"

    m = UserMemory(user)
    store, _v = m._index()
    idx = m._grep_index(store)
    fact = store.facts.get("terrence-1837F16")
    assert fact is not None and "离开安克" in fact.text
    segment, attested = m.segment(), m.vocab_term()
    # **P86 那一版的 `common_term()`**（P88 之前的产品）：`recall_ruler` 里那份逐字复刻，
    # `--cf-whoaxis` 每跑一次都拿它的三闸全开版跟产品对拍，所以它不会悄悄飘走。
    head_common = RR._axis_variant(True, True, ask_who=False)(m)
    today_common = UserMemory.common_term(m)

    def look(common, cap=16):
        real = KM._rotate
        if cap != 16:
            KM._rotate = lambda src, into, n: real(src, into, cap if n == 16 else n)
        try:
            terms = S._terms(m, q, S._weigher(q, segment, common))
        finally:
            KM._rotate = real
        hits = S._hits(terms, fact.text)
        ev = S.evidence(hits, q, common=common, attested=attested, segment=segment)
        return {
            "有开安克": "开安克" in terms,
            "hits": hits,
            "why": [e.get("why") for e in (ev or [])],
            "strong": S._strong_enough(hits, q, segment, common),
            "qualifies": S.qualifies(hits, q, common=common,
                                     attested=attested, segment=segment),
        }

    # C 对照：HEAD 原样 —— 这就是「整屏变空」那一版
    c = look(head_common)
    assert c["有开安克"] is False, "`开安克` 又在 16 个名额里了——那这条账的形状变了"
    assert c["hits"] == ["离开安"] and c["why"] == ["pair"]
    assert c["strong"] is False and c["qualifies"] is False

    # A：一刀只动一处 —— 单独把 `公司` 按回 common
    a = look(lambda t: True if t == "公司" else head_common(t))
    assert a["有开安克"] is True, "把 `公司` 按回去也救不回 `开安克`——根因判错了"
    assert a["hits"] == ["离开安", "开安克"] and a["why"] == ["span"]
    assert a["strong"] is True and a["qualifies"] is True

    # B：一刀只动一处 —— 只把那 16 抬到 17
    b = look(head_common, cap=17)
    assert b["有开安克"] is True and b["why"] == ["span"]
    assert b["strong"] is True and b["qualifies"] is True

    # **`公司` 真的被那条轴捞回来了**（这条因果链的第一环）
    assert head_common("公司") is False, "`公司` 不再被捞回来了——A 那一刀就不是「只动一处」了"

    # ── P88 ②：**今天的 HEAD 上这条链已经被治好了**，而且治的正是最前面那一环 ──
    assert today_common("公司") is True, \
        "`公司` 又被捞回来了——那 P88 那条主语面轴没在这条路上，i=293 会再次整屏变空"
    today = look(today_common)
    assert today["有开安克"] is True, "`开安克` 没回到那 16 个名额里——P88 ② 那条判要重读"
    assert today["hits"] == ["离开安", "开安克"] and today["why"] == ["span"]
    assert today["strong"] is True and today["qualifies"] is True
    # **那 16 一个字没动**：不是靠抬名额治好的（这正是 P88 ② 要的那条路）
    assert "_rotate(second, _rotate(first, [], 16), 16)" in \
        pathlib.Path(KM.__file__).read_text(encoding="utf-8")


def test_第三条b_那16个名额是硬编码的_而且它就在这条路上():
    """根因指着的那个数得**真的在源码里**，不是我说的。"""
    src = pathlib.Path(KM.__file__).read_text(encoding="utf-8")
    assert "_rotate(second, _rotate(first, [], 16), 16)" in src, \
        "那 16 不在这儿了——P86 ③ 那条根因得重查"


def test_第三条c_更正写进了源码_而且说清楚了错在哪():
    """**预测错了照实记**——而且是**更正**，不是偷偷改口：
    错的那句话（排名挤压）和对的那句话（16 个名额）**都得在**，不然下一个人看不出发生过什么。"""
    src = pathlib.Path(KM.__file__).read_text(encoding="utf-8")
    assert "更正 P84 ⑥" in src, "没写这是在更正谁"
    assert "排名挤压" in src, "错的那句话没留下来——那就不叫更正，叫改口"
    assert "只有一条的时候没有" in src, "为什么它不可能是排名挤压，理由没写"
    assert "`开安克` 挤出了这 16 个" in src, "真根因没写"
    assert "quorum 是最后那道说「不」的闸，但它说得没错" in src, \
        "P82 那条 quorum 的账跟这条的关系没说清"
    assert "判「不改」" in src and "190 对" in src, \
        "为什么这一批不改（那个 16 是 P63 读完 190 对判过的）没写"


def test_第三条d_i293在两组标注里都没改口():
    """i=293 是 P82 / P84 / P86 三批都碰到的同一条。**它在哪一组里都得是「变差 · 1→0」。**"""
    for s in ("p84-spread-28", "p86-bigcorpus-175"):
        row = next(r for r in _rows(s) if r["i"] == 293)
        assert row["读下来"] == "变差" and row["条数"] == "1→0", f"{s} 里的 i=293 改口了"
        assert any("离开安克" in t for t in row["掉的"]), f"{s} 里掉的那条正文被换掉了"
    # 真根因写进了 175 那一组的 `_meta`（**标注不改口，账记在 `_meta` 里**）
    m = _meta("p86-bigcorpus-175")
    k = "这一组顺手查清的一件事（留给 P86 ③）"
    assert "那句话是错的" in m[k] and "16 个名额" in m[k] and "i=607" in m[k]


# ── ④ 登记 / 完整性 ────────────────────────────────────────────────────

def test_第四条_这一批新钉的八个数都登记了():
    """**新钉的数进 `floor_ruler` 的 `REGISTRY`**，而且每条都得写「它一动要去重读什么」。"""
    for name in ("EXPECT_CF_BIG_SIZE_CHANGED", "EXPECT_CF_BIG_SIZE_ADD",
                 "EXPECT_CF_BIG_SIZE_DROP", "EXPECT_CF_BIG_SIZE_LIBS",
                 "EXPECT_CF_BIG_BOTH_CHANGED", "EXPECT_CF_BIG_BOTH_ADD",
                 "EXPECT_CF_BIG_BOTH_DROP", "EXPECT_CF_BIG_BOTH_LIBS"):
        key = ("backend/scripts/recall_ruler.py", name)
        assert key in FR.REGISTRY, f"{name} 没登记"
        kind, base, why = FR.REGISTRY[key]
        assert kind == FR.PINNED, f"{name} 不该是「只准往上」——它是实测结论，一动就得重读"
        assert getattr(RR, name) == base, f"{name} 跟登记的基线飘开了"
        assert len(why) > 30, f"{name} 的「一动要去重读什么」写得太短，等于没写"


def test_第四条b_登记表自己那两个只准往上的数没被调低():
    """⚠️ **别在这儿钉「登记表有多少条」那种全局数**（第 810 轮 P84+P85 同时栽过）：
    那个数每批都会涨，合并时必红。去问 `floor_ruler` 里那两个「只准往上」的数。"""
    bad, n, behind = FR.check()
    assert bad == [], "下限那把尺对不上：" + "；".join(bad)
    assert len(FR.REGISTRY) >= FR.REGISTRY_SIZE_FLOOR
    assert n >= FR.CHECKED_COUNT_FLOOR, \
        f"共核 {n} 条，少于记在 floor_ruler 里的 {FR.CHECKED_COUNT_FLOOR} 条"
    assert behind == [], "有下限抬了而登记没跟上：" + "；".join(behind)


def test_第四条c_这一批产品的判据一个字节没改():
    """**P86 这一批三条判全是「不改」**——那就得有一条闸看着产品判据真的没动。
    `common_term()` 那三条限制、`SPREAD_GENERIC`、`SPREAD_MIN_HITS` 逐个核。

    ⚠️ **P88 动了第三条，照实改这一条断言**（并排写，别把上面那句删了）：
    P88 ① 在「话题面判不泛」**后面**又串了一条主语面轴，所以那一句从
    `return face.generic(term) is not False` 变成了
    `if face.generic(term) is not False: return True` + 再问一句 `_who_face`。
    **前两条（库大小闸、汉字闸）和两个门槛一个字节没动**，这一条照旧钉着它们；
    第三条改钉「话题面那一问还在、而且它后面串的是主语面」——
    判据只窄不宽（只做减法）这件事由 `test_p88::第一条d` 单独钉。
    """
    from app.database.kb import topic_face as TF
    assert TF.SPREAD_GENERIC == 0.75 and TF.SPREAD_MIN_HITS == 20
    src = pathlib.Path(
        ROOT / "backend" / "app" / "database" / "kite" / "kite_memory.py").read_text(encoding="utf-8")
    for need in ("ask_face = total * R.COMMON_DF_RATIO < R.COMMON_DF_MIN",
                 "if not (ask_face and TF.has_cjk(term)):",
                 "if face.generic(term) is not False:",
                 "who = self._who_face(store, idx)"):
        assert need in src, f"`common_term()` 里那句 `{need}` 没了——这一批说好三条都不改"
