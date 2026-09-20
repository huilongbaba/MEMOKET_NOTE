"""P63：两把尺搬进仓库（`scripts/recall_ruler.py` / `scripts/margin_dot_ruler.py`）+ 圆点分档重量。

## 这些闸防的是什么

量具只要还在 scratch 里，下一批就复现不出上一批的数——P60 的「圆点 172 / 140 / 34」、
P34 那 47 条标注、P59 那 284 轮 run json，三次都是这么没的。搬进仓库解决了「还在不在」，
**没解决「会不会悄悄失效」**：一把口径跟着产品漂走了的尺子，照样每次都打出一个数来，
而且看不出毛病。所以这里的闸分两种：

  · **对拍闸**：尺子的口径参数 / 段落规则 / 六档名字，**逐个对着前端真源文件核**。
    P62 抓到的 `.mm-continues` / `.mm-adds`（前端里根本没有这两个类，于是那两档
    永远读 0）就是没有这道闸躺了三批的。
  · **量程闸**：五篇的**正文 sha8**、走查那篇的**字数和行号**、三档钉死的数
    （需要真库，本机没有就跳过）。P61 抓到「同一个 note id 两版正文」——
    光钉 id 是不够的。

## 圆点到底几档（P63 #2）

P52 / P58 / P60 三批的台账写着「圆点 **8** 个（冲突 2 / 印证 1 / 缺依据 2 / 合并 1）」。
P62 发现那四档加起来只有 6，判成「另外 2 颗掉进两个永远选不到的空档」。**两个都不对。**
量具那一行读的是 `document.querySelectorAll('[class*="mm-"]')`——**全文档、通配**，
而右栏「记忆」的图例每一档挂着一颗 `.mm-dot`（`RelatedMemory.tsx`）：

    8 = 图例 6 颗 + 落槽里真的 2 颗（冲突 1 · 缺依据/no_value 1）

那个「合并 1」从来不是一颗圆点：真库 482 篇 / 418 个含数字段上，**合并判据响过 2 次、
一次都没当上 `cands[0]`**（两次都被「延续」压着），所以 `.mm-merge` 的圆点**画不出来**。
**「选不到 ≠ 没有」的镜像不止「选到两个 ≠ 真有两个」，还有「选到八个 ≠ 真有八个」。**
"""

from __future__ import annotations

import pathlib
import re

import pytest

from scripts import harness_run_ledger as L
from scripts import margin_dot_ruler as D
from scripts import recall_ruler as R

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"
RECALL_TS = FRONTEND / "util" / "recallContext.ts"
MARGIN_TS = FRONTEND / "editor" / "marginMemory.ts"
STYLES = FRONTEND / "styles.css"
RELATED_TSX = FRONTEND / "components" / "RelatedMemory.tsx"
HAS_DB = (ROOT / "backend" / "data" / "notes.sqlite3").exists()
# 两把尺都要**两样**语料：笔记库 + `KITE_DATA_DIR` 下的 codebook。
# 只有库没有 codebook 时 `users_with_codebook()` 是空的，765 条会变成 0 条——
# **那不是「尺子坏了」，是语料没摆齐**，所以这两件事分开跳，跳过理由各自说清楚。
HAS_CORPUS = (R.data_dir() / "terrence" / "codebook.xml").is_file()
NEEDS_CORPUS = pytest.mark.skipif(
    not (HAS_DB and HAS_CORPUS),
    reason=f"本机没有 notes.sqlite3（{HAS_DB}）或 KITE_DATA_DIR 下的 codebook（{HAS_CORPUS}）")


# ── 765 条那把尺：口径跟前端对拍 ─────────────────────────────────────────────

def test_765条尺子的三个参数跟前端逐字一致():
    """`recallQuery` 的三个常数抄在 Python 这边，**抄错了不会报错，只会悄悄换一把尺**。"""
    src = RECALL_TS.read_text(encoding="utf-8")
    for name, got in (("RECALL_TAIL_CHARS", R.RECALL_TAIL_CHARS),
                      ("RECALL_MIN_CHARS", R.RECALL_MIN_CHARS),
                      ("RECALL_CONTEXT_BEFORE", R.RECALL_CONTEXT_BEFORE)):
        m = re.search(rf"export const {name}\s*=\s*(\d+)", src)
        assert m, f"前端里找不到 {name}"
        assert int(m.group(1)) == got, f"{name}: 前端 {m.group(1)} ≠ 尺子 {got}"


def test_765条尺子的光标档和末尾档():
    """`cursor` = 前一段（≤200 字）+ 本段；`tail` = 末 500 字。两档都要摆出来。"""
    body = "第一段写了一点东西。\n\n第二段也写了一点东西，够八个字。"
    q, mode = R.recall_query(body, "第二段也写了一点东西，够八个字。")
    assert mode == "cursor"
    assert "第一段写了一点东西" in q and "第二段也写了一点东西" in q

    q2, mode2 = R.recall_query(body, "短")            # 不够 8 字 → 退回末尾档
    assert mode2 == "tail" and q2.endswith("够八个字。")


def test_765条尺子_标题段走末尾档_而且前一段是标题时不带上():
    """`#` 开头的段落不当光标段；前一段是标题时也不拼进查询（前端那两个 `^#{1,6}\\s`）。"""
    _q, mode = R.recall_query("# 这是一个够长的标题行\n\n正文", "# 这是一个够长的标题行")
    assert mode == "tail"

    body = "# 这是一个够长的标题行\n\n第二段也写了一点东西，够八个字。"
    q, mode2 = R.recall_query(body, "第二段也写了一点东西，够八个字。")
    assert mode2 == "cursor" and "这是一个够长的标题行" not in q


def test_765条尺子对不上量程时会吵():
    """**一把默默换了量程还继续报数的尺子比没有尺子更糟。** `check()` 必须逐项点名。"""
    ok = [("u", f"q{i}", "cursor", "user") for i in range(R.EXPECT_CURSOR)]
    ok += [("u", f"t{i}", "tail", "user") for i in range(R.EXPECT_TAIL)]
    ok += [(f"u{i}", f"x{i}", "tail", "user") for i in range(1, R.EXPECT_USERS)]
    # 上面多塞了 EXPECT_USERS-1 条，先把条数这一项摆平不了——所以只核「对的那把不吵」用真跑，
    # 这里核的是「错的那把一定吵，而且点得出名字」。
    bad = R.check(ok[: R.EXPECT_TOTAL - 1])
    assert bad and any(b.startswith("queries") for b in bad)
    assert any(b.startswith("users") for b in bad)


# ── 圆点那把尺：口径跟前端对拍 ───────────────────────────────────────────────

def test_圆点六档跟前端的类名逐个对得上():
    """**这道闸就是 P62 那两个死选择器躺三批的解药。**

    六个 kind 三处各写了一遍：`relations.py` 判出来的、`marginMemory.RELATION_LABEL`、
    `styles.css` 的 `.mm-*`。任何一处多一个少一个，某一档就会「永远是 0」而不报错。
    """
    labels = re.search(r"RELATION_LABEL: Record<MemoryRelationKind, string> = \{(.+?)\}",
                       MARGIN_TS.read_text(encoding="utf-8"), re.S)
    assert labels
    fe_kinds = set(re.findall(r"(\w+):\s*'", labels.group(1)))
    assert fe_kinds == set(D.KINDS), f"前端 {sorted(fe_kinds)} ≠ 尺子 {sorted(D.KINDS)}"
    assert set(D.LABEL) == set(D.KINDS)

    css = STYLES.read_text(encoding="utf-8")
    for k in D.KINDS:
        assert re.search(rf"^\.mm-{k}\s*\{{", css, re.M), f"styles.css 里没有 .mm-{k}"
    # 反过来也核一遍：css 里不许有尺子不认识的 `.mm-<kind>`（`.mm-dot` 是圆点本体，不是档）
    css_kinds = {m for m in re.findall(r"^\.mm-([a-z]+)\s*\{", css, re.M)} - {"dot"}
    assert css_kinds == set(D.KINDS), f"styles.css 多出来 {sorted(css_kinds - set(D.KINDS))}"


def test_圆点的段落门槛跟前端一致():
    """`marginParagraphs`：含数字 · 不是 `#` 标题 · ≥8 字；连续非空行算一段。"""
    src = MARGIN_TS.read_text(encoding="utf-8")
    assert f"p.text.length >= {D.MIN_CHARS}" in src
    assert "/\\d/.test(p.text)" in src and "!p.text.startsWith('#')" in src

    paras = D.margin_paragraphs(
        "# 标题 2026 年\n\n这一段有数字 2026 年够八个字。\n接着的一行还在同一段。\n\n"
        "这一段没有数字所以不算。\n\n短 1\n")
    assert [p[0] for p in paras] == [3], paras          # 只有第 3 行起那一段
    assert "接着的一行还在同一段" in paras[0][1]


def test_缺依据的no_record不画点_其余都画():
    """`dotWorthy` 逐字：`no_record` 是整篇的属性，逐段画就是把同一句话说 89 遍。"""
    assert D.dot_worthy("unsupported", "no_record") is False
    assert D.dot_worthy("unsupported", "no_value") is True
    assert D.dot_worthy("unsupported", None) is True
    for k in set(D.KINDS) - {"unsupported"}:
        assert D.dot_worthy(k, "no_record") is True     # 只对「缺依据」那一档成立
    assert "m.relation === 'unsupported' && m.why === 'no_record'" \
        in MARGIN_TS.read_text(encoding="utf-8")


def test_右栏图例每档一颗圆点_这就是那个8的大半():
    """P52/P58/P60 那个「圆点 8 个」= 图例 6 颗 + 落槽 2 颗。**图例这 6 颗得钉住。**

    图例是 `Object.keys(RELATION_LABEL).map(...)`，所以它的颗数**恒等于档数**；
    只要还有人拿全文档的选择器去数圆点，这 6 颗就会再混进去一次。
    """
    assert D.LEGEND_DOTS == len(D.KINDS) == 6
    src = RELATED_TSX.read_text(encoding="utf-8")
    assert "Object.keys(RELATION_LABEL)" in src
    assert "'mm-dot mm-' + k" in src
    # 落槽里的圆点走 `.cm-memory-gutter`；数圆点必须带这个前缀，否则图例会一起进来
    assert ".cm-memory-gutter .mm-dot" in (FRONTEND / "editor" / "marginMemory.ts").read_text(
        encoding="utf-8")


def test_走查那篇的正文是按日志逐字重建的():
    """105 字 + 「预热名单」在第 8 行——两处独立核对，都出自 `$S/p60/log/b1b.txt`。"""
    assert len(D.WALK_CONTENT) == D.WALK_CHARS == 105
    assert "预热名单" in D.WALK_CONTENT.split("\n")[D.WALK_DOT_LINE]
    assert len(D.margin_paragraphs(D.WALK_CONTENT)) == 3      # 三段正文，标题不算


def test_五篇钉的是id加正文指纹_不是光id():
    """P61 抓到 P4 那一版的「N1」跟今天是同一个 id、**两版正文**（26,714 → 30,588 字）。

    只钉 id 的尺子在那种情况下照样报一个数出来，而那个数跟上一批的不是一回事。
    """
    assert len(D.NOTES) == 5
    assert len({v[0] for v in D.NOTES.values()}) == 5
    for name, (nid, chars, sha8) in D.NOTES.items():
        assert re.fullmatch(r"[0-9a-f]{12}", nid), name
        assert chars > 0 and re.fullmatch(r"[0-9a-f]{8}", sha8), name
    assert D.NOTES["N1"][1] == 30588, "N1 是 30,588 字那一版（P4 那版是 26,714 字）"


def test_圆点这把尺不开证据闸():
    """`relations_batch` 那条路 `evidence` 是关的（P32「差点砍错的那一刀」原样成立）。

    开了它圆点会变少，而右栏「记忆」那条路才是开着的——两条路混成一把尺，
    量出来的数哪一边都不是。
    """
    import inspect
    src = inspect.getsource(D.judge)
    assert "evidence" not in src
    assert f"limit=RECALL_LIMIT" in src and D.RECALL_LIMIT == 8
    assert D.SCOPE == "all"


# ── `_cjk_terms` 的 16：读完了，还是不改（P63 #4）────────────────────────────

def test_cjk_terms的上限还是16_这一批读完了还是没动():
    """P61 #2 量完没读、判「不改」；P63 **190 对一条不落读完了**，结论还是不改。

    按血缘分开之后：**用户真写的那 59 条查询上，进来的 100 对里不硬 43 对 = 43.0%**
    （库里今天平均 13%、P61 那一刀 9.4%），同时**掉错了 8 对硬的**。
    `_cjk_terms` 的名额是先到先得的滑窗，第 17~24 个几乎全是碎片；
    而 top-8 是固定预算，多进来的碎片是**顶掉别的查询维度**换来的。
    """
    import ast
    import inspect
    import textwrap

    from app.database.kite.kite_memory import UserMemory
    src = textwrap.dedent(inspect.getsource(UserMemory._cjk_terms))
    caps = [n.value for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Constant) and n.value == 16]
    assert len(caps) == 2, f"`_cjk_terms` 里的 16 应该正好两处，现在 {len(caps)} 处"

    # 行为那一半：一段长中文只给 16 个候选词（AST 钉不住「它真的在管事」）
    terms = UserMemory._cjk_terms(
        "华为的液冷散热设计使用水和乙二醇的配比重点针对最容易发热的芯片和显存进行散热"
        "以降低因单块芯片过热导致系统宕机的风险并且在柜内采用正交交换架构")
    assert len(terms) == 16, len(terms)


def test_那190对的标注全在仓里_而且带着血缘():
    """**「顺手量出来的数，当分母用之前得先逐条读」**——这一批把那 133 条读完了。

    标注进了 `memory_sample.jsonl` 的 `p63-cap24-190`：不是抽样，是全量枚举。
    每条查询带 `origin`，因为**不分血缘算出来的比率是错的**
    （28.8% → 43.0%，`corpus_lineage` 顶上记的批 4 / 批 6 同一个形状）。
    """
    import json
    fix = ROOT / "backend" / "tests" / "fixtures" / "memory_sample.jsonl"
    recs = [json.loads(ln) for ln in fix.read_text(encoding="utf-8").splitlines() if ln.strip()]
    mine = [r for r in recs if r.get("set") == "p63-cap24-190"]
    meta = [r for r in mine if "_meta" in r]
    body = [r for r in mine if "_meta" not in r]
    assert len(meta) == 1 and len(body) == 86

    gained = sum(len(r["gained"]) for r in body)
    dropped = sum(len(r["dropped"]) for r in body)
    assert (gained, dropped) == (153, 37), (gained, dropped)

    n = meta[0]["_meta"]["本组的数"]
    assert n["进"] == gained and n["掉"] == dropped
    assert sum(n["进来的"][k] for k in ("硬", "勉强", "不硬")) == gained
    assert sum(n["掉了的"].values()) == dropped
    # 每一对都判了，没有「读了一半」的
    for r in body:
        assert r["origin"] in ("user", "script", "fixture")
        for g in r["gained"]:
            assert g["判"] in ("硬", "勉强", "不硬")
        for d in r["dropped"]:
            assert d["判"].startswith(("硬", "勉强", "不硬"))
    # 血缘那张分表要跟正文里的 origin 对得上（**摆了就得加得起来**，P62 那个 8 的教训）
    lin = n["⚠️ 按血缘分开才是能用的那个数"]
    assert lin["user（用户真写的）"]["查询"] == sum(1 for r in body if r["origin"] == "user")
    assert lin["script（脚本产出）"]["查询"] == sum(1 for r in body if r["origin"] == "script")
    assert lin["fixture（纯夹具）"]["查询"] == sum(1 for r in body if r["origin"] == "fixture")
    assert sum(v["查询"] for v in lin.values()) == len(body)


# ── 量程闸（要真库，本机没有就跳过）────────────────────────────────────────────

# ── 跑批台账（P63 #3）──────────────────────────────────────────────────────

def test_跑批台账是追加式的_而且读得回来():
    """P61 #4 那个「0 次」的分母只有 3 轮，就是因为 P59 那 284 轮跟着 scratch 清掉了。

    台账进了 git 之后，分母只会涨不会缩——所以这里钉的是**下界**，不是等号。
    """
    runs = L.load()
    assert len(runs) >= 175, "台账只许追加，不许变短"
    assert sum(len(d["rounds"]) for d in runs) >= 489
    assert len({d["run"] for d in runs}) == len(runs), "同一份跑不许进两次"
    for d in runs[:5] + runs[-5:]:
        assert {"run", "src", "key", "mode", "created", "rounds"} <= set(d)
        for x in d["rounds"]:
            assert {"r", "status", "fired", "len"} <= set(x)
            assert isinstance(x["fired"], list)


def test_跑批台账里没有用户写的字():
    """顶上那句「一个字的正文都没有」要么是真的、要么就别写。

    真库 53 个 key 里有一个是拿**笔记标题**拼的（`note:stage3-量产未决项-74921`），
    所以 `safe_key()` 把非 ASCII 的尾巴换成 sha8——这道闸每次核一遍它真换了。
    """
    runs = L.load()
    for d in runs:
        assert d["key"].isascii(), f"key 里有非 ASCII：{d['key']!r}"
        for x in d["rounds"]:
            for f in x["fired"]:
                assert f.isascii() and f.replace("_", "").isalnum(), f
    assert L.safe_key("note:stage3-量产未决项-74921").startswith("note:x")
    assert L.safe_key("note:06647b9c2031") == "note:06647b9c2031"
    # 蒸馏出来的栏位里不许有正文那几栏
    assert not ({"content", "text", "passage", "body", "material"}
                & {k for d in runs[:20] for x in d["rounds"] for k in x})


def test_跑批台账两种fired_checks写法都认():
    """今天写的是 JSON 数组，老行是逗号分隔。**认错一种，那些轮就静悄悄变成「没响过」。**"""
    assert L._fired('["a","b"]') == ["a", "b"]
    assert L._fired("a,b") == ["a", "b"]
    assert L._fired("") == [] and L._fired(None) == []
    assert L._fired("{}") == []


@NEEDS_CORPUS
def test_765条尺子在真库上还是765条():
    qs = R.queries()
    assert R.check(qs) == [], R.identity(qs)
    assert len(qs) == 765


@pytest.mark.skipif(not HAS_DB, reason="本机没有 notes.sqlite3")
def test_五篇的正文指纹没变():
    """对不上就抛 `SystemExit`——**别换一把尺继续量。**"""
    assert set(D._note_contents()) == set(D.NOTES)
