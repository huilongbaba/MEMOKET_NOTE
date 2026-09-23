"""P65：取词那一层的**排序**（①，改了）+ 收工那行的字数口径（②，量完）+ P59 留的第 2/3 条（③）。

## ① 这一刀是什么，不是什么

**不是**换名额。名额那条路 P60 / P61 / P63 三批走完了：cap 24 / 32 / 48 / 400 各一档
全库对拍过，P63 还把 cap 24 那 190 对一条不落读完了，结论一路是「不改」。
P63 收尾写下的是**问题不在名额在排序**——`记忆` 这种真词排在第 17 位，
而 `了智` / `的业务` / `另一方` 这些碎片占着前 16。

**是**给那 16 个名额排个次序：`_cjk_terms` 先转一遍**实词**，转不满再让**碎片**接着填。
判据用的是 `_strong_enough` 那一把尺（`kb/search._weigher` → `tokenize.content_chars`
→ `>= STRONG_CJK_MIN`），**同一个函数、同一份口径，没有另起一把、没有新阈值**。
轮转（P4 立的片段公平性）在每一档里**逐字保留**，`weigh is None` 那一支跟 P63 的 HEAD
**逐条相同**——`_cjk_greps` 的退路、行级回退、`matched_terms` 今天都还走它。

全库对拍（765 条那把尺，`evidence=True`，语料 `corpus=11429185B/403a1183`）：

| | 有召回 | 召回对 | top-8 变了 | 成员真变了 | 进 | 掉 | 空→有 | 有→空 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| HEAD（P63 那一版） | 337 / 765 | 1345 | — | — | — | — | — | — |
| 这一批 | **341** | **1347** | 84 | 71 | 78 | 76 | 8 | 4 |

> HEAD 那一行 **337 / 1345 跟 P63 台账逐格相同**——同一台机器上真跑出来的，不是抄的。

154 对**一条不落读完了**，标注在 `memory_sample.jsonl` 的 `p65-order-154`，
**按血缘分开**（P63 那条教训，这是第四次）。

## ② / ③ 这两条**量完没改**，闸钉的是量出来的数

`ship_best` 回退的名单不止 `loop.SHIP_BEST_ON` 那四个，**轮数用尽那个 `else:` 也换**；
台账（175 跑 / 489 轮）里 8 跑会回退，而**判据真响过的轮还是 3**，分母一格没长。
"""

from __future__ import annotations

import ast
import inspect
import json
import pathlib
import textwrap

import pytest

from app.database.kb import search as kb_search
from app.database.kb import tokenize as tok
from app.database.kite.kite_memory import UserMemory
from scripts import harness_run_ledger as L
from scripts import recall_ruler as R

ROOT = pathlib.Path(__file__).resolve().parents[2]
HAS_DB = (ROOT / "backend" / "data" / "notes.sqlite3").exists()
HAS_CORPUS = (R.data_dir() / "terrence" / "codebook.xml").is_file()
NEEDS_CORPUS = pytest.mark.skipif(
    not (HAS_DB and HAS_CORPUS),
    reason=f"本机没有 notes.sqlite3（{HAS_DB}）或 KITE_DATA_DIR 下的 codebook（{HAS_CORPUS}）")

# 这段话里 `华为` / `芯片` / `显存` 是词，`以降低` / `导致系` / `块芯` 是滑窗碎片。
LONG_CN = ("华为的液冷散热设计使用水和乙二醇的配比重点针对最容易发热的芯片和显存进行散热"
           "以降低因单块芯片过热导致系统宕机的风险并且在柜内采用正交交换架构")
# 真库里那条查询（`p65-order-154` 的 user #12 / #26）。**带标点**，所以它是好几个片段
# ——`_cjk_terms` 的轮转是按片段来的，**一整段不带标点的中文只有一个片段，看不出轮转**，
# 也就看不出这一刀在两个片段之间做了什么。判据宁可窄：两种文本各钉各的。
RUNS_CN = "除了智能计算的部分，华为还有一个芯片就是鲲鹏，CPU。"


def _seg():
    """一个真的分词器（底表，不带这个人的专名）。"""
    return tok.default().cut


def _weigh(q: str):
    return kb_search._weigher(q, _seg(), None)


# ── ① 取词那一层的排序 ──────────────────────────────────────────────────────

def test_不给weigh就是原样_跟P63那一版逐字相同():
    """**`weigh is None` 这一支一个字都不许动。**

    `_cjk_greps` 的退路、`_recall_via_lines`、`matched_terms`、面板那几条路今天都走它，
    而它们这一批**没接线**。P61 #1 那句「换量程时 fallback 分支的阈值要逐字保持原样」
    在这儿的对应物就是这条：不给尺子，就还是「每个句段头三个字」的轮转。
    """
    # HEAD 那一版的算法，逐字抄（量具自检的那一份，`<scratch>/p65/terms65.py` 同源）
    import re

    from app.database.kite.kite_memory import STOPWORDS
    runs = [r for r in re.findall(r"[一-鿿]{2,}", LONG_CN) if r not in STOPWORDS]
    runs.reverse()
    per_run = []
    for run in runs:
        grams = []
        for size in (3, 2):
            for i in range(len(run) - size + 1):
                g = run[i:i + size]
                if g not in STOPWORDS and g not in grams:
                    grams.append(g)
        if grams:
            per_run.append(grams)
    out, depth = [], 0
    while len(out) < 16 and any(depth < len(g) for g in per_run):
        for grams in per_run:
            if depth < len(grams) and grams[depth] not in out:
                out.append(grams[depth])
                if len(out) >= 16:
                    break
        depth += 1

    assert UserMemory._cjk_terms(LONG_CN) == out
    assert UserMemory._cjk_terms(LONG_CN, None) == out


def test_给了尺子之后_实词排在碎片前面():
    """这一刀买到的那件事本身，拿真库里那条查询钉（`p65-order-154` 的 user #12 / #26）。"""
    weigh = _weigh(RUNS_CN)
    new = UserMemory._cjk_terms(RUNS_CN, weigh)
    old = UserMemory._cjk_terms(RUNS_CN)
    assert len(new) == 16 and len(old) == 16

    solid = [t for t in new if (weigh(t) or 0) >= kb_search.STRONG_CJK_MIN]
    # **先给实词**：实词占的是前面连续的那一段，不是散在中间
    assert new[:len(solid)] == solid, new
    # 真词进来了，HEAD 那一版里它们一个都进不去
    for w in ("华为", "芯片", "鲲鹏", "智能", "计算"):
        assert w in new and w not in old, (w, new, old)
    # 而横跨词边界的碎片被挤出去了
    for f in ("为还有", "还有一", "有一个", "一个芯", "算的部", "片就是"):
        assert f in old and f not in new, (f, new, old)


def test_只换序不换名额_进来的一个都不是新词():
    """**纯换序**：新名单里的每一个词，在不封顶的老轮转里本来就在——
    这一刀不放进任何一个今天进不来的候选，也不会少给一条查询词。"""
    weigh = _weigh(LONG_CN)
    new = UserMemory._cjk_terms(LONG_CN, weigh)

    import re

    from app.database.kite.kite_memory import STOPWORDS, _rotate
    runs = [r for r in re.findall(r"[一-鿿]{2,}", LONG_CN) if r not in STOPWORDS]
    runs.reverse()
    per_run = []
    for run in runs:
        grams = []
        for size in (3, 2):
            for i in range(len(run) - size + 1):
                g = run[i:i + size]
                if g not in STOPWORDS and g not in grams:
                    grams.append(g)
        if grams:
            per_run.append(grams)
    full = _rotate(per_run, [], 10**9)      # 不封顶的全序
    assert set(new) <= set(full)
    assert len(new) == len(set(new)) == 16


def test_轮转本身一个字没动_两档各自还是按片段轮流():
    """P4 立的那条「别让第一个长片段吃光配额」**在每一档里原样成立**。

    造一个局面：**最靠光标那个片段**（`runs.reverse()` 之后排在最前的那个，也就是
    正文里最后那一段）实词多得一个人就吃得下 16 个名额；正文前面那一段也有实词。
    轮转在的话，前面那一段的第一个实词必须也在名单里。

    ⚠️ **反例得真的落在被测分支里**：第一版把两段写反了，断言的那个词正好落在
    `runs.reverse()` 之后的第一个片段上——于是「只看第一个片段」这把突变刀
    （第 ⑤ 刀）一刀下去它照样绿。**一条对着错片段的断言是绿的，不是对的。**
    """
    head = "产品方向商业找人。"      # 正文在前 → reverse 之后排在**后面**
    tail = "境外用户欧美用户隐私安全硬约束范围锚点全流程交易数据合规审查要求。"
    text = head + tail
    per = [r for r in __import__("re").findall(r"[一-鿿]{2,}", text)]
    assert len(per) == 2 and per[0].startswith("产品方向"), per

    new = UserMemory._cjk_terms(text, _weigh(text))
    assert len(new) == 16
    # 光第二段（reverse 之后排最前那个）就有 16 个以上候选——轮转不在的话它会吃光
    assert len(UserMemory._cjk_terms(tail, _weigh(tail))) == 16
    assert any(w in new for w in ("产品", "方向", "商业")), new


def test_weigh回None的串不许插队():
    """定位不到 = 「不知道」，**不给它插队**，仍排在碎片那一档里。

    这跟 `content_chars` 顶上那句「不许当成 0」不冲突：那句说的是「当成 0 就把一条召回
    判死」，这里最坏只是顺序没变，一个词都不会因此被踢出去。

    ⚠️ **反例得真的落在被测分支里**：第一版的假尺子**对每一个串都回 `None`**，
    于是「`None` 当成实词」这把突变刀（第 ④ 刀）一刀下去，两档里一档是全部、
    一档是空，转出来的东西跟原样**一模一样**，闸照样绿。
    要摆出差别，尺子必须**有的回数、有的回 `None`**——回 `None` 的那个得跟一个
    真实词抢名次，才看得出它有没有插队。
    """
    real = _weigh(RUNS_CN)
    seen, nones = [], []

    def weigh(g):
        seen.append(g)
        n = real(g)
        # 让**排在最后面那个真实词**假装定位不到：它一插队就看得见
        if g == "鲲鹏":
            nones.append(g)
            return None
        return n

    got = UserMemory._cjk_terms(RUNS_CN, weigh)
    assert seen and nones, "尺子根本没被问过——那这条测的不是这件事"
    base = UserMemory._cjk_terms(RUNS_CN, real)
    assert "鲲鹏" in base, base
    # 回 `None` 的那个掉到碎片那一档去了：它排在**所有实词后面**
    solid = [t for t in got if (real(t) or 0) >= kb_search.STRONG_CJK_MIN and t != "鲲鹏"]
    assert got[:len(solid)] == solid, got
    assert "鲲鹏" not in got[:len(solid)], got


def test_接线洞_rank真的把尺子递到了取词那一层():
    """**这是接线洞那一条**（P61 #1 那三个实参同一个形状，单独钉）。

    `rank` 拿着 `segment` / `common`，`_terms` 得真的收到 `_weigher(...)` 的返回值。
    省了它，`_cjk_terms` 整条退回 P63 的轮转，而**四栏留下率里没有一栏看得见这件事**
    ——它只在同主题自召回那一列上差 25 分，而那一列不是每批都跑。
    """
    import types

    got = {}
    real = kb_search._terms

    def spy(memory, query, weigh=None):
        got["weigh"] = weigh
        return real(memory, query, weigh)

    class _Store:
        facts = {"f0": types.SimpleNamespace(text="华为的芯片", topics=(), entities=())}

    mem = types.SimpleNamespace(
        _candidate_terms=lambda t: [],
        _cjk_terms=lambda t, weigh=None: ["华为"],
    )
    kb_search._terms = spy
    try:
        kb_search.rank([{"id": "f0"}], LONG_CN, mem, _Store(), limit=5,
                       evidence=False, segment=_seg())
    finally:
        kb_search._terms = real
    assert callable(got.get("weigh")), "`rank` 没把尺子递下去——接线洞又开了"
    assert (got["weigh"]("华为") or 0) >= kb_search.STRONG_CJK_MIN

    # 不给 `segment` 时必须递 `None`（那条路今天逐字等于 P4 那一版）
    got.clear()
    kb_search._terms = spy
    try:
        kb_search.rank([{"id": "f0"}], LONG_CN, mem, _Store(), limit=5, evidence=False)
    finally:
        kb_search._terms = real
    assert got["weigh"] is None


def test_名额还是16_这一批动的是排序不是名额():
    """P61 / P63 两批的 AST 闸这一批照样得过：**两处 `16`，一个大于 3 的数都不许多。**"""
    src = textwrap.dedent(inspect.getsource(UserMemory._cjk_terms))
    fn = ast.parse(src)
    caps = sorted({n.value for n in ast.walk(fn)
                   if isinstance(n, ast.Constant) and isinstance(n.value, int) and n.value > 3})
    assert caps == [16], f"`_cjk_terms` 的上限动了：{caps}"
    assert len([n for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and n.value == 16]) == 2
    assert len(UserMemory._cjk_terms(LONG_CN, _weigh(LONG_CN))) == 16


def test_content_chars提前收工之后逐字还是那个数():
    """把尺子挪到取词那一层之后一条查询要问上千下，所以 `content_chars` 加了一句
    「越过右端就 break」。**它只许更快，不许更改**——这里拿一整段真中文的
    每一个 2/3 字窗口逐个对，跟不提前收工的算法比。"""
    seg = _seg()
    squeezed = kb_search.squeeze(LONG_CN)
    toks = list(seg(squeezed))

    def slow(run: str):
        i = squeezed.find(run)
        if i < 0:
            return None
        j, total, pos = i + len(run), 0, 0
        for t in toks:
            a, b = pos, pos + len(t)
            pos = b
            ov = min(b, j) - max(a, i)
            if ov >= 2 and len(t) >= 2 and tok._CJK.fullmatch(t):
                if not kb_search._is_cn_filler(t):
                    total += len(t)
        return total

    n = 0
    for size in (2, 3):
        for i in range(len(squeezed) - size + 1):
            g = squeezed[i:i + size]
            assert tok.content_chars(g, squeezed, lambda _s: toks,
                                     kb_search._is_cn_filler) == slow(g), g
            n += 1
    assert n > 100, n


@NEEDS_CORPUS
def test_那154对的标注全在仓里_而且带着血缘():
    """**「顺手量出来的数，当分母用之前得先逐条读」**——这一批把 71 条 / 154 对读完了。"""
    fix = ROOT / "backend" / "tests" / "fixtures" / "memory_sample.jsonl"
    recs = [json.loads(ln) for ln in fix.read_text(encoding="utf-8").splitlines() if ln.strip()]
    mine = [r for r in recs if r.get("set") == "p65-order-154"]
    meta = [r for r in mine if "_meta" in r]
    body = [r for r in mine if "_meta" not in r]
    assert len(meta) == 1 and len(body) == 71

    gained = sum(len(r["gained"]) for r in body)
    dropped = sum(len(r["dropped"]) for r in body)
    assert (gained, dropped) == (78, 76), (gained, dropped)

    n = meta[0]["_meta"]["本组的数"]
    assert n["混在一起"]["进"] == gained and n["混在一起"]["掉"] == dropped
    # **摆了就得加得起来**（P62 那个 8 的教训）
    assert sum(n["混在一起"][k] for k in ("硬", "勉强", "不硬")) == gained
    assert sum(n["混在一起"][k] for k in
               ("掉错了（硬）", "掉的勉强", "掉对了（不硬）")) == dropped

    per = n["⚠️ 按血缘分开才是能用的那个数（P63 第三次，这一批第四次）"]
    assert {k.split("（")[0] for k in per} == {"user", "script", "fixture"}
    assert sum(v["进"] for v in per.values()) == gained
    assert sum(v["掉"] for v in per.values()) == dropped
    # 每一对都判了，没有「读了一半」的
    for r in body:
        for x in r["gained"]:
            assert x["判"] in ("硬", "勉强", "不硬"), x
        for x in r["dropped"]:
            assert x["判"] in ("掉错了", "勉强", "掉对了"), x
    # 血缘是 `corpus_lineage` 那三档，不是另写一份名单
    from scripts import corpus_lineage
    assert {r["origin"] for r in body} <= set(corpus_lineage.ORIGINS)


@NEEDS_CORPUS
def test_765条尺子在真库上还是765条_这一批没动语料():
    qs = R.queries()
    assert not R.check(qs)
    assert R.corpus_tag("terrence") == "11429185B/403a1183"


# ── ② 收工那行的字数口径：量完了 ─────────────────────────────────────────────

def test_回退名单不止SHIP_BEST_ON_轮数用尽那个else也换():
    """**先把名单摆对**。`loop.SHIP_BEST_ON` 是四个，可 `loop.py` 轮数用尽那个 `else:`
    也把 `st.content` 换成 `st.best[1]`（`hooks/note.commit` 的注释里 P45 #1 逐字记着，
    `test_p45::test_接线洞_交最好那一轮发生在最后一个after_round之后` 钉住了那条分支）。
    **数「有多少跑会回退」时漏掉它，答案就是 0——而真值是 8。**
    """
    from app.harness import loop
    assert set(loop.SHIP_BEST_ON) == {"regressed", "cost_cap", "check_stuck", "best_stalled"}
    src = inspect.getsource(loop.run) if hasattr(loop, "run") else \
        (ROOT / "backend" / "app" / "harness" / "loop.py").read_text(encoding="utf-8")
    # `st.content = st.best[1]` 在 loop.py 里正好两处：`SHIP_BEST_ON` 那支 + 那个 `else:`
    assert src.count("st.content = st.best[1]") == 2, \
        "`交最好那一轮` 的落点变了——回退名单得跟着重数一遍"


def test_台账里会ship_best回退的跑是8_而且不是全都无害():
    """P64 #1 说的「先量」。语料 = 进了 git 的那份跑批台账。

    175 跑里停机理由**记下来了**的只有 17 跑（其余 158 跑那一栏是空的），
    其中 **8 跑是 `max_rounds`** = 会回退；`SHIP_BEST_ON` 那四个理由**一次都没出现过**。
    8 跑全是 3 轮，逐轮字数都不一样——**没有一跑是「最后一轮正好就是 best」那种无害情况**，
    最坏口径差 16 ~ 1333 字，P64 实拍那 320 字落在这个量级里。
    """
    from app.harness.loop import SHIP_BEST_ON
    rollback = set(SHIP_BEST_ON) | {"max_rounds"}
    rows = [json.loads(ln) for ln in L.LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()]
    known = [r for r in rows if r.get("stopped")]
    hit = [r for r in rows if (r.get("stopped") or "") in rollback]
    assert (len(rows), len(known), len(hit)) == (175, 17, 8)
    assert {r["stopped"] for r in hit} == {"max_rounds"}
    worst = []
    for r in hit:
        lens = [d["len"] for d in sorted(r["rounds"], key=lambda d: d["r"])]
        assert len(lens) == 3 and len(set(lens)) == 3, (r["run"], lens)
        worst.append(max(abs(lens[-1] - x) for x in lens[:-1]))
    assert min(worst) == 16 and max(worst) == 1333, worst


def test_产品那几处打字数的地方_口径本身是对的():
    """**量完的另一半：判不出 P64 #1 是产品的。**

    会打「+N 字」的产品代码有两处，两处都拿**交出去的那一份**重算：

      · `App.tsx` 的收工那行 —— 算 `delta` 之前先 `liveContentRef.current = serverContent`；
      · `util/runRounds.runTitle` —— 从 `note_revisions` 的收尾行 `chars` 减起点。

    而后端交出去的确实是回退之后那一份（`test_p45` 两条闸）。所以那 320 字的差
    **更像读它的那个走查脚本**（P64 同一批抓到四个量具问题，而走查脚本不在 git）。
    **写「没核」，不写「没做」**（P62 立的规矩）：这一批没起壳，复现不了，所以不改。
    """
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    i = app.index("const delta = liveContentRef.current.length - runBaseRef.current.length")
    # 往回找最近的一次对齐：必须在算 delta **之前**
    j = app.rindex("liveContentRef.current = serverContent", 0, i)
    assert j < i
    # 中间不许再有一次「不看服务端就改 liveContentRef」的写法
    between = app[j:i]
    assert "liveContentRef.current =" not in between.replace(
        "liveContentRef.current = serverContent", "", 1), between[:400]

    rr = (ROOT / "frontend" / "src" / "util" / "runRounds.ts").read_text(encoding="utf-8")
    assert "run.rounds[n - 1].after?.chars" in rr
    assert "run.rounds[0].before.chars" in rr


# ── ③ P59 留的第 2 / 3 条 ───────────────────────────────────────────────────

def test_那6个模式的分母一格没长_所以还是答不了():
    """**P63 说「每批 `--append` 分母会自己长」——这一批去数了，它没长。**

    台账还是 175 跑 / 489 轮、出身全是 `p63-realdb`、时间跨度还是 09-17 ~ 09-18，
    **判据真响过的轮还是 3**，跟 P61 #4 量的那份逐格相同。
    原因查清楚了：走查那种跑落在 `$S/pNN/<udd>/data` 里，`--append` 只导真库，
    而真库自 P63 之后没有新的跑。**要让分母长，得让走查那一趟的 udd 也导一次。**
    """
    rows = [json.loads(ln) for ln in L.LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows) == 175
    assert sum(len(r["rounds"]) for r in rows) == 489
    assert {r.get("src") for r in rows} == {"p63-realdb"}
    fired = [(r, d) for r in rows for d in r["rounds"] if d.get("fired")]
    assert len(fired) == 3, "分母长了——那这条结论可以重问了，别再抄 P61 的"


def test_那6个模式跑满的历史里还是没有一次判据连响到底():
    """P61 #4 那条结论在进了 git 的台账上**复现得出来**（这才是搬进仓库买到的东西）。"""
    from app.harness import modes as M
    no_stuck = sorted(k for k, m in M.BLOCK.items() if M.check_stuck not in (m.stop_when or ()))
    assert no_stuck == ["analysis", "chart", "custom", "eda", "prompt", "table"]
    assert M.check_stuck in M.NOTE.stop_when and M.check_stuck in M.SECTION.stop_when

    rows = [json.loads(ln) for ln in L.LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()]
    n = M.CHECK_STUCK_ROUNDS
    hits = []
    for r in rows:
        rs = sorted(r["rounds"], key=lambda d: d["r"])
        if len(rs) < n:
            continue
        names = [set(d.get("fired") or ()) for d in rs[-n:]]
        if all(names) and set.intersection(*names) and (r.get("stopped") or "") == "max_rounds":
            hits.append(r["run"])
    assert hits == [], hits


def test_3_stuck_rounds那条结论今天更硬了_advisory让它买得更少():
    """**P61 #3 说「不改」，这一批去核了一遍：结论成立，而且理由比 P61 写的那三条更硬。**

    P61 的账是「`JUDGE_FLOOR` 已经在 r2 放行，改完买不到东西」。P59 落地 `advisory` 之后
    局面又变了一格，而且是**朝着更不该改的方向**：

      · `STUCK_ROUNDS` 够不着的第一大户是 `citations_present`（判词里带「这一轮写了 N 字」，
        每轮都不一样）。它那两档 `located == 0` 现在是 `advisory=True`
        ——P58 量过，这条判据报得出档的 **29 轮全是这一档**。
      · `advisory` 那一支**每一轮**都放行（不用攒 streak），所以那个大户今天根本不经过
        `STUCK_ROUNDS`：改不改它，对这条判据一分钱都买不到。
      · 而且真改了会**倒亏**：`streak > STUCK_ROUNDS` 那一支排在 `advisory` **前面**，
        又**不写 `check_released`、不写 `advisories`**。按判据名数的话 r3 起会被它抢先，
        于是 P24 #5 那条「判据还在响就不算写完」失效、P58 A 那条「判词得自己找条路进
        下一轮 prompt」也断掉——正是 P58 A 注释里写的「比原来更糟」。

    **就此结案，别再挂着。**
    """
    from app.harness.checks import grounding
    from app.harness.middleware import checks as C

    src = inspect.getsource(C)
    i = src.index("if streak > STUCK_ROUNDS:")
    j = src.index("if verdict.advisory:")
    assert i < j, "两支的先后换了——上面那段账得重算"
    stuck_branch = src[i:j]
    assert "check_released" not in stuck_branch
    assert "advisories" not in stuck_branch
    # 键还是带判词原文的那一份（P61 #3 钉的那条，原样留着）
    assert 'key = f"{verdict.dimension}\\u0000{verdict.message}"' in src
    assert "streak = cur[key]" in src

    # `citations_present` 的 `located == 0` 两档 + material_thin 的两档确实是 advisory
    g = inspect.getsource(grounding)
    assert g.count("advisory=True") == 4
