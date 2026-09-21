"""P79：**`ai` 那一个词量完了（判「不该动」）** + **知识库搜索框那条路有尺了**（新）+
**「离线那条查询 ≠ 用户眼前那一条」量完了（判 P78 ⑤ 的根因判错了）**。

**产品代码只改了一处**：`kb/search.display_terms` 合并命中窗口时**不跨过用户自己打的空白**
（新函数 `kb/search.squeezed_gaps`）。全库 765 条：**top-8 变 0 · 证据 chip 变 0 ·
命中词行变 1**（i=658 `# 9 月 14 日 周一\\n你好`：`周一你好` → `周一`、`你好`）。
`frontend/scripts/walkthrough/` · `frontend/scripts/run-walkthrough-fakeshell.mjs` ·
`frontend/src/editor/` **一个字节没碰**（另有 agent 在那一侧）。

出身（**整行跟着数走**）：HEAD `833e30f` · `scripts/recall_ruler.py` 765 条
（cursor 727 / tail 38 · 血缘 user 549 / script 178 / fixture 38）·
`notes=482篇/321250字/47dcc54be60aa4f2` · `terrence=11429185B/403a1183`。

四栏留下率**整行、一栏没跌**（`KITE_DATA_DIR=<scratch>/p79data` 自己量的，不是抄的）：
`recall_selfcheck terrence 200 11` **197/195/96**、`… evidence` **192/190/92** ·
圆点 **166/137/33**（缺依据 23 · 印证 10）· D2 表 B **8 条**（N2 5 · N4 3）· 47 条 **46/36/4/6**。

**这个文件钉的是「结论的前提」**：三条结论（`ai` 该不该动 / 搜索框那一行摆得对不对 /
离线那把尺该不该打折扣）全是「先量再改」量完判的，前提一变结论就得重量。
"""

from __future__ import annotations

import inspect
import json
import pathlib
import re
import textwrap

import pytest

from app.database.kb import search as kb_search
from scripts import kb_search_ruler as K
from scripts import recall_ruler as R

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"
KB_DASH = FRONTEND / "components" / "kb" / "KbDashboard.tsx"
EDITOR_TSX = FRONTEND / "components" / "MarkdownEditor.tsx"
FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "memory_sample.jsonl"

HAS_DB = (ROOT / "backend" / "data" / "notes.sqlite3").exists()
HAS_CORPUS = (R.data_dir() / "terrence" / "codebook.xml").is_file()
NEEDS_CORPUS = pytest.mark.skipif(
    not (HAS_DB and HAS_CORPUS),
    reason=f"本机没有 notes.sqlite3（{HAS_DB}）或 KITE_DATA_DIR 下的 codebook（{HAS_CORPUS}）")


@pytest.fixture
def real_corpus(monkeypatch):
    """`conftest._isolated_db` 把 codebook 指到临时目录——**要真语料的测试自己指回去**
    （conftest 顶上那句话）。指回去的是 `KITE_DATA_DIR` 那一份（跑批用的拷贝），
    **不是主仓那份真库**。"""
    from app.database.kite import kite_memory as _km
    from app.util.config import get_settings as _gs
    monkeypatch.setattr(_km, "get_settings", _gs)
    yield


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


# ── ① 这一刀本身：反例有红有绿 ──────────────────────────────────────────────

def test_第一条_空白那道边界_六格反例有红有绿():
    """**任何「核对」先喂它一个该红 / 该绿的反例。**

    `kb_search_ruler.BATTERY` 六格喂的是**假的 terms + 假的切词器**，不需要真语料。
    每一格两个期望：今天的，和把 `squeezed_gaps` 打成空集（守卫恒不成立 =
    **逐字退回改之前那一版**）的。三格必须两档**不同**（这一刀在动），
    三格必须两档**相同**（对照：真重叠跨空格、标点隔开、没有空格）——**绿有个数。**
    """
    assert K.run_battery() == []
    assert len(K.BATTERY) == 6
    same = [n for n, _t, _q, _tk, a, b in K.BATTERY if a == b]
    diff = [n for n, _t, _q, _tk, a, b in K.BATTERY if a != b]
    assert len(same) == 3 and len(diff) == 3, (same, diff)


def test_第一条b_squeezed_gaps_按串本身判():
    """`squeezed_gaps` 回的是 `squeeze()` 之后**前面刚被挤掉过空白**的下标。

    差一位就是静默错（`squeeze` 顶上那句话）——所以这一格逐个偏移钉死。
    """
    assert kb_search.squeezed_gaps("广州 深圳") == {2}
    assert kb_search.squeezed_gaps("广州深圳") == set()
    assert kb_search.squeezed_gaps("周一\n你好") == {2}
    assert kb_search.squeezed_gaps("  a  b ") == {0, 1}        # 开头的空白也算一处
    assert kb_search.squeezed_gaps("") == set()
    assert kb_search.squeezed_gaps(None) == set()              # type: ignore[arg-type]
    # 跟 `squeeze` 是同一份口径：下标落在 squeeze 之后那个串上
    q = "a b  c"
    assert kb_search.squeeze(q) == "abc"
    assert kb_search.squeezed_gaps(q) == {1, 2}


def test_第一条c_这一刀只挡相邻_真重叠照合():
    """**判据宁可窄**：一个命中串本来就可能跨过被挤掉的空格（用户打 `华 为`，
    `华为` 这一串在 squeezed 里横跨它）。那时候两段是同一个词的两半，不是两个词。"""
    seg = K._fake_segment(("华为",))
    assert kb_search.display_terms(["华为"], "华 为", segment=seg) == ["华为"]
    seg2 = K._fake_segment(("广州", "深圳"))
    assert kb_search.display_terms(["广州", "深圳"], "广州 深圳", segment=seg2) == ["广州", "深圳"]


def test_第一条d_守卫那一行还在源码里():
    """**「文件里有这个串」≠「这段代码还在跑」的反面**：这里要的恰恰是那一行还在。"""
    src = _src(kb_search.display_terms)
    assert "gaps = squeezed_gaps(query)" in src
    assert "not (a == merged[-1][1] and a in gaps)" in src
    # `evidence_runs` 那一处**故意不合相邻**（P27 立的），这一刀没去碰它
    assert "if merged and a < merged[-1][1]:" in _src(kb_search.evidence_runs)


def test_第一条e_跨空白那条判据自己也有反例():
    """`crosses_gap` 判的是**串本身**错不错，不是「这一刀动没动它」——
    两个数都要，缺一个就分不清「旋钮在动」和「产出对了」。"""
    assert K.crosses_gap("广州深圳", "广州深圳", {2}) is True
    assert K.crosses_gap("广州", "广州深圳", {2}) is False
    assert K.crosses_gap("深圳", "广州深圳", {2}) is False
    assert K.crosses_gap("广州深圳", "广州深圳", set()) is False


# ── ② 知识库搜索框那条路：口径跟前端对拍 ────────────────────────────────────

def test_第二条_那条路今天还在_而且连空结果都照摆():
    """**P48 ③ 判过「今天 0 个用户看得见」，P69 已经更正为「不成立」。**
    这一格再核一遍：那一行今天仍然在摆——**0 召回也照摆**（真库上 9/10 条）。

    ⚠️ **P81 ③ 落刀之后这条断言改了两处，照实记**（原文留在下面）：

    * 原来钉的是 `"命中词：' + hits.terms.slice(0, 6)"` 一整串。P81 ③ 把那一行
      拆成两个标签（有召回「命中词：」/ 0 召回「找过：」），这一串不再逐字存在。
      **钉的东西变了，钉的那件事没变**：`slice(0, 6)` 还在 ⇒ `SHOW=6` 还成立。
    * 原来还钉着 `"facts.length" not in line`——那正是 P79 ② 报的 bug 本身
      （「那一行只看 `terms.length`，`facts.length` 一个字都没问」）。
      **P81 ③ 修的就是它**，所以这一条现在反过来断言：那一行**必须**看 `facts.length`。

    `EXPECT_EMPTY_WITH_LINE = 9` 这个数 **P81 一个字没动**——
    **摆不摆是一件事，摆的叫什么是另一件。**
    """
    src = KB_DASH.read_text(encoding="utf-8")
    assert "hits.terms.slice(0, 6)" in src, "那一行不再 slice(0, 6)，SHOW=6 跟着废"
    assert "recall(q, 20)" in src, "limit 变了，这把尺的 LIMIT=20 跟着废"
    line = next(ln for ln in src.splitlines() if "hits.terms.slice(0, 6)" in ln)
    assert "hits.terms.length ?" in line, "那一行不再先看 terms.length 决定摆不摆"
    assert "hits.facts.length ?" in line, "P81 ③ 那一刀不在了——0 召回又开始叫「命中词」"
    assert "' · 命中词：' : ' · 找过：'" in line, "P81 ③ 那两个标签变了"
    assert K.SHOW == 6 and K.LIMIT == 20


def test_第二条b_那把新尺的口径自检不掺真语料():
    """`check_source()` 读的是真前端文件；`run_battery()` 不碰语料。**先证口径再量。**"""
    assert K.check_source() == []
    assert K.EXPECT_TOTAL == sum(n for _k, n in K.STRATA) == 110
    assert K.EXPECT_GAP_MERGED_HEAD == 3 and K.EXPECT_GAP_MERGED_NOW == 0


@NEEDS_CORPUS
def test_第二条c_那把新尺在真库上逐格对得上(real_corpus):
    """110 条手打搜索词跑一趟，**对不上 `exit 9`**（同 `en_gate_ruler` / `topic_spread_ruler`）。"""
    assert K.main(["--battery-only"]) == 0
    assert K.main([]) == 0


@NEEDS_CORPUS
def test_第二条d_那三条两个词的搜索_今天摆的是两个词(real_corpus):
    """`广州 深圳` 改之前摆「命中词：**广州深圳**」——一个库里没有、用户也没打过的词。"""
    from app.database.kite.kite_memory import UserMemory
    m = UserMemory("terrence")
    for q, want in (("广州 深圳", ["广州", "深圳"]),
                    ("上海 深圳", ["上海", "深圳"]),
                    ("亚马逊 苹果", ["亚马逊", "苹果"])):
        _facts, terms, _ms = m.recall(q, limit=K.LIMIT, evidence=True)
        now = K._shown(m, terms, q, gaps=True)
        head = K._shown(m, terms, q, gaps=False)
        assert now == want, (q, now)
        assert head == ["".join(want)], (q, head)     # 改之前真的是接成一个词


# ── ③ 离线那条查询 vs 产品窗口 ──────────────────────────────────────────────

def test_第三条_产品那个分段抄件跟前端逐字一致():
    """`recall_ruler.paragraph_at` 是 `MarkdownEditor.paragraphAt` 的抄件。
    **抄错了不会报错，只会悄悄换一把尺**（同 `test_p63` 那三个参数）。"""
    assert R.check_paragraph_at_source() == []
    src = EDITOR_TSX.read_text(encoding="utf-8")
    assert "export function paragraphAt(" in src


def test_第三条b_两处分段差在哪_标题那一档():
    """两处分段口径**唯一**的差：离线只按空行切，产品**在标题行上也断**、
    而且标题行自己单独算一段。别的地方逐格相同。"""
    # 标题跟正文之间没有空行 → 产品断开、离线粘在一起
    lines = ["## 小标题", "正文一句话", "", "另一段"]
    assert R.paragraph_at(lines, 1) == "## 小标题"
    assert R.paragraph_at(lines, 2) == "正文一句话"
    assert "\n\n".join(x for x in "\n".join(lines).split("\n\n")).startswith("## 小标题")
    assert re.split(r"\n\s*\n", "\n".join(lines))[0] == "## 小标题\n正文一句话"
    # 空行上没有段（产品会退回末 500 字那一支）
    assert R.paragraph_at(lines, 3) == ""
    # 没有标题的时候两边一样
    plain = ["第一行", "第二行", "", "第三行"]
    assert R.paragraph_at(plain, 1) == "第一行\n第二行"
    assert R.paragraph_at(plain, 2) == "第一行\n第二行"
    assert re.split(r"\n\s*\n", "\n".join(plain))[0] == "第一行\n第二行"


@NEEDS_CORPUS
def test_第三条c_765条里该打折扣的只有一条():
    """**P78 ⑤ 说「这件事影响的是我们过去所有离线数」——量下来不是。**

    765 条里产品**产不出来的只有 1 条**（i=630：离线把一个前面没空行的 `### 标题`
    粘进了段里）。剩下 764 条产品原样产得出来，**拿它们量出来的数不打折扣**。
    反过来产品还能产出 16 条离线没有的，那是离线**少覆盖**，不是量偏。
    """
    g = R.window_gap()
    assert g["offline"] == R.EXPECT_TOTAL == 765
    assert g["product"] == R.EXPECT_PROD_TOTAL == 780
    assert len(g["only_offline"]) == R.EXPECT_ONLY_OFFLINE == 1
    assert len(g["only_product"]) == R.EXPECT_ONLY_PRODUCT == 16
    only = g["only_offline"][0][1]
    assert only.rstrip().endswith("兑现闸门**"), only[-40:]
    assert "###" in only, "那一条之所以产不出来，就是因为尾巴上粘着一个标题"


@NEEDS_CORPUS
def test_第三条d_P78点名的那三段_产品原样产得出来():
    """**P78 ⑤ 的根因判错了，照实记。**

    P78 写的是「产品的窗口是光标段 + 前一段，约 200 字，而离线尺子那一条是整 300 字」。
    实测：i=80 那 300 字的查询**产品原样产得出来**，而且壳上读到的那条「尾巴」
    （`…60 多个主流大模型，用更简单、更高效…智能风控…`）**本来就在这 300 字里**
    ——没有任何东西被截掉。`RECALL_CONTEXT_BEFORE = 200` 卡的只有**前一段**，
    光标那一段本身不卡长度（`recallQuery` 逐行可查）。
    """
    qs = R.queries()
    prod = R.product_queries()
    for i in (80, 120, 253, 410, 442, 558):
        user, q, _m, _o = qs[i]
        assert (user, q) in prod, f"i={i} 产品产不出来"
    assert len(qs[80][1]) == 300
    assert "60 多个主流大模型" in qs[80][1] and "智能风控" in qs[80][1]
    assert R.RECALL_CONTEXT_BEFORE == 200


# ── ④ `ai` 那一个词：量完判「不该动」，**这个文件钉的是那个判的前提** ────────────

def test_第四条_ai在证据那一列上今天已经是零():
    """P79 ① 的第一条理由：**它不是没人管，是已经有人管了。**

    `evidence()` 第一件事就是 `common(r) → continue`，而 `ai` 在 terrence 的库里
    df = 359/2362 = 15.2%，远过 `COMMON_DF_RATIO`。所以证据 chip 那一列上
    `ai` 在 765 条里出现 **0 次**（实测）。
    """
    src = _src(kb_search.evidence)
    assert "if common is not None and common(r):" in src
    assert "continue" in src
    # 而 `_strong_enough` 的证人名单**没问 `common`**——一屏两把尺，这就是 P79 ① 的靶子
    se = _src(kb_search._strong_enough)
    assert "cl = _clusters(hits)" in se
    assert "common(" not in se, "如果这里开始问 common 了，P79 ① 那 25 条要重读"


def test_第四条b_ai被挡住只是因为它两个字母():
    """P79 ① 的第二条理由：**「长度」跟「泛不泛」不是一条轴。**

    `_strong_enough` 里 `ai` 过不了的是 `len(h) >= 3`（英文 / 数字 / 定位不到那一档），
    而 P75 那把量「泛」的尺判它 **0.74「不泛」**（差 0.01 到门槛）；
    它判「泛」的 `go` 0.92 / `ask` 0.87 / `pro` 0.80 **今天全部放行**。
    换轴之前泛尺在英文那一半**没有留出集**（P77 ③ 那 80 条全是汉字），所以这一批不换。
    """
    assert kb_search._strong_enough(["ai", "ui"], "x" * 200) is False
    assert kb_search._strong_enough(["ask", "pro"], "x" * 200) is True
    assert kb_search.EVIDENCE_EN_MIN == 3      # 孪生常量，P32 量过，这一批也没碰


def test_第四条c_这一批的标注在仓库里():
    """`ai` 那 25 条**逐条读完**的标注（P79 ①）+ 110 条手打搜索词那把新尺的出身。"""
    rows = _rows("p79-ai-25")
    assert len(rows) == 25
    labels = {r["读下来"] for r in rows}
    assert labels <= {"变好", "变差", "中性"}, labels
    # **钉死一个数，不写下限**（P78 ④ 那一课：`MIN_*` 这类下限挡不住自己被调低）。
    # 「不动」这个判全靠那 8 条变差——这一列一动，那个判就得重读。
    got = {k: sum(1 for r in rows if r["读下来"] == k) for k in ("变好", "变差", "中性")}
    assert got == {"变好": 11, "变差": 8, "中性": 6}, got
    meta = _meta("p79-ai-25")
    assert "退回" in json.dumps(meta, ensure_ascii=False)
    kb = _rows("p79-kbq-110")
    assert len(kb) == 110
    assert {r["档"] for r in kb} == {k for k, _n in K.STRATA}
