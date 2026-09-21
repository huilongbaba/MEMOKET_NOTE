"""P83：**底下那 5 张记忆卡也分一分**（收 P80 留的第 ① 条）+ **走查 note id 每批重取**（收 P80 #7）。

## A：那 5 张卡

P80 把**那一行**改老实了（「命中：X（前一段带进来的）」），**卡还是混着的**。
先量：`scripts/card_origin_ruler.py` 在真语料上走 727 条 cursor 查询——
**卡 964 张 / 会被盖戳的 133 张 / 有戳的查询 62 条（混着 29 · 整屏全是 33）**。
133/964 不是零头，33 条整屏全是前一段的更是最坏那一档 ⇒ **判「改」**。

判据**两条都成立才标**（照抄 P80 的形状）：① 卡里一个「光标这段的命中词」都没有
（**一票否决**）；② 至少有一个「前一段带进来的命中词」。
**召回和 `out[:8]` 一个字没动**——变的只有「怎么说」。

这一份钉三样：
  · **两边那份判据逐行一致**（Python 那把尺 ←→ 前端 `cardFromBefore`，读的是真源文件）；
  · **六个量程**（带语料才跑）；
  · **`queries()` 的 765 / 727 / 38 一格没动**——P83 给 `recall_ruler` 加了
    `recall_query3` / `queries_ctx`，**只加不改**，这一条是它的证据。

## B：`@LAST_NEW_NOTE`

P80 问题 #7：清单里写死的 `openNoteById` 目标是**上一批**现造的那篇，
真库里没有 → 当场 FAIL，看起来像产品坏了。`go.sh` 这一批加了占位符，
`check-walkthrough-runnable.mts` 第 ⑧ 条钉住「别再写死」。
这一份从 `pytest` 这一侧再钉一遍那三处接线（**`npm test` 那条链红了这边也得红**
——P81 那一跤：同一行被三个地方钉着，而突变闸只收了两个）。
"""

from __future__ import annotations

import pathlib
import re

import pytest

from scripts import card_origin_ruler as C
from scripts import floor_ruler as F
from scripts import recall_ruler as RR

ROOT = pathlib.Path(__file__).resolve().parents[2]
CTX_TS = ROOT / "frontend" / "src" / "util" / "recallContext.ts"
REL_TSX = ROOT / "frontend" / "src" / "components" / "RelatedMemory.tsx"
GO_SH = ROOT / "frontend" / "scripts" / "walkthrough" / "go.sh"
B1OLD = ROOT / "frontend" / "scripts" / "walkthrough" / "steps" / "b1old.mjs"
RUNNABLE = ROOT / "frontend" / "scripts" / "check-walkthrough-runnable.mts"
FAKESHELL_RUN = ROOT / "frontend" / "scripts" / "run-walkthrough-fakeshell.mjs"

HAS_DB = (C.BACKEND / "data" / "notes.sqlite3").is_file()
HAS_CORPUS = (RR.data_dir() / "terrence" / "codebook.xml").is_file()
NEEDS_CORPUS = pytest.mark.skipif(
    not (HAS_DB and HAS_CORPUS),
    reason=f"本机没有 notes.sqlite3（{HAS_DB}）或 KITE_DATA_DIR 下的 codebook（{HAS_CORPUS}）")


def _bare(p: pathlib.Path) -> str:
    """整行注释摘掉再判——**「文件里有这个串」≠「这段代码还在跑」**。"""
    out, block = [], False
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if block:
            if "*/" in s:
                block = False
            continue
        if s.startswith("/*"):
            block = "*/" not in s
            continue
        if s.startswith("//") or s.startswith("*") or s.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


# ── A：判据两边一致 ─────────────────────────────────────────────────────────

def test_前端那份判据还在原地():
    """`card_origin_ruler.check_source()` 自己就是那条对拍，这里让它在 `pytest` 里也红。"""
    assert C.check_source() == []


def test_那把尺跟前端是同一条判据_例反例各四条():
    """**先喂它该红该绿的**：光跑一遍「都绿」分不清「判对了」和「判据坏了」。"""
    before = "公司大模型平台适配了 60 多个主流大模型，金融行业的智能客服、智能风控。"
    here = "智影相机让游客生成唐风、文物穿越风格的大片。"
    # `诊断智影` **两头都没有**：它是后端在拼好的查询上、跨着两段接缝切出来的碎词。
    # ⚠️ 这一条是**第 ② 刀逼出来的**：没有它的时候，把判据②放宽成「只要不在这一段里
    # 就盖」一刀砍下去**测试全绿**——例反例自己分不开那两条判据。
    pool = ["主流", "智能风", "智影相机", "诊断智影"]
    # 例：只沾前一段的词 → 标
    assert C.card_from_before("三季度把主流大模型的名单过了一遍", pool, here, before) is True
    assert C.card_from_before("智能风控那次评审的结论", pool, here, before) is True
    # 反例四种，**一条都不许标**
    assert C.card_from_before("关于智影相机的季度汇报", pool, here, before) is False      # 一票否决
    assert C.card_from_before("智能风控评审顺带聊到智影相机", pool, here, before) is False  # 两边都沾 → 否决
    assert C.card_from_before("仓库盘点单据的归档规则", pool, here, before) is False       # 一个都不沾
    assert C.card_from_before("三季度把主流大模型的名单过了一遍", pool, here, "") is False  # 没有前一段
    # **两头都没有那种**：判据②要的是「确实在前一段里」，不是「不在这一段里」
    assert "诊断智影" not in before and "诊断智影" not in here
    assert C.card_from_before("诊断智影这个说法是接缝上切出来的", pool, here, before) is False


def test_拿哪几个词去判是三档不是两档():
    assert C.evidence_pool([{"term": "甲"}], ["乙"]) == ["甲"]
    # `[]` = 判过了、一条都摆不出来 → **一个词都不拿**（退回 `terms` 就是 P44 问题 #3）
    assert C.evidence_pool([], ["乙"]) == []
    # `None` = 没人判过 → 退回 `terms` 是对的
    assert C.evidence_pool(None, ["乙"]) == ["乙"]


def test_前端那两条判据的形状():
    """钉的是**一票否决**那一条本身：改成「只要不在这一段里就盖」当场红。"""
    t = _bare(CTX_TS)
    assert "export function cardFromBefore(" in t
    assert "if (termFromBefore(t, paragraph, before)) fromBefore = true" in t
    assert "else if (inPara.includes(t)) return false" in t, "一票否决那一条没了"
    c = _bare(REL_TSX)
    assert "const pool = evidencePool(evidence, terms)" in c
    assert "cardFromBefore(text, pool, qCtx.paragraph, qCtx.before)" in c, \
        "盖戳用的不是**发那一问时**的那两段——张冠李戴又来一次"
    assert "fromBefore(f.text) &&" in c, "盖戳那一步没接在卡上"
    assert "mem-card-from-before" in c


def test_召回那一层一个字没动():
    """P80 划的边界，这一批沿用：**只动「怎么说」不动「捞什么」**。"""
    c = _bare(REL_TSX)
    assert "const RECALL_LIMIT = 8" in c
    assert "const LIST_MAX = 5" in c
    assert "recall(q.query, RECALL_LIMIT)" in c


# ── A：量程（带语料才跑）────────────────────────────────────────────────────

@pytest.fixture
def real_corpus(monkeypatch):
    """`conftest._isolated_db` 把 codebook 指到临时目录——**要真语料的测试自己指回去**
    （同 `test_p79.real_corpus`）。指回去的是 `KITE_DATA_DIR` 那一份（跑批用的拷贝），
    **不是主仓那份真库**。

    ⚠️ 第一版漏了这一条，`walk()` 当场量到 **0 张卡**，六个量程全红——
    **「跑得动」不等于「量的是那份语料」**。"""
    from app.database.kite import kite_memory as _km
    from app.util.config import get_settings as _gs
    monkeypatch.setattr(_km, "get_settings", _gs)
    yield


@NEEDS_CORPUS
def test_记忆卡那把尺的六个量程(real_corpus):
    g = C.walk()
    # **先证明它真量到了东西**：0 张卡的时候「对得上」是句空话
    assert g["with_cards"] > 0, "一张卡都没量到——语料没指回去（`real_corpus` 那条）"
    assert C.check(g) == [], g


@NEEDS_CORPUS
def test_recall_ruler_只加不改():
    """P83 给它加了 `recall_query3` / `queries_ctx`。**三个数一格不许动。**"""
    qs = RR.queries()
    assert RR.check(qs) == []
    assert len(qs) == RR.EXPECT_TOTAL == 765
    # `queries()` 就是 `queries_ctx()` 的前四格——**一份走法，两个投影**
    ctx = RR.queries_ctx()
    assert [(u, q, m, o) for u, q, m, o, _p, _b in ctx] == qs


def test_recall_query3_的第三格():
    doc = "# 标题\n\n前一段讲的是智能风控和智能客服这件事情。\n\n这一段讲智影相机在博物馆落地。\n"
    para = "这一段讲智影相机在博物馆落地。"
    q, mode, before = RR.recall_query3(doc, para)
    assert mode == "cursor"
    assert "智能风控" in before and "智影相机" not in before
    # `recall_query` 是它的前两格，**逐字相同**
    assert RR.recall_query(doc, para) == (q, mode)
    # 标题不算前一段；末尾档没有前一段可言
    assert RR.recall_query3(doc, "")[2] == ""
    assert RR.recall_query3(doc, "前一段讲的是智能风控和智能客服这件事情。")[2] == ""


# ── A：新钉的数都进了登记表 ─────────────────────────────────────────────────

def test_八个新钉的数都在_floor_ruler_里登记着():
    """P80 / P81 合并那一跤：两个 worktree 各加各的钉死数，谁都看不见对方。"""
    for name in ("SHOW", "MAX_ASKED", "EXPECT_CARDS", "EXPECT_MARKED",
                 "EXPECT_QUERIES_WITH_MARK", "EXPECT_MIXED",
                 "EXPECT_ALL_MARKED", "EXPECT_WITH_CARDS"):
        key = ("backend/scripts/card_origin_ruler.py", name)
        assert key in F.REGISTRY, f"{name} 没登记"
        kind, base, why = F.REGISTRY[key]
        assert kind == F.PINNED
        assert base == getattr(C, name)
        assert len(why) > 20, f"{name} 的「一动要去重读什么」写得太短"
    assert "backend/scripts/card_origin_ruler.py" in F.WATCHED


def test_下限那把尺自己还是绿的():
    bad, _checked, behind = F.check()
    assert bad == []
    assert behind == []


# ── B：`@LAST_NEW_NOTE` 那三处接线 ──────────────────────────────────────────

def test_go_sh_真的换了那个占位符():
    go = _bare(GO_SH)
    assert "line=${line//@LAST_NEW_NOTE/$last_new_note}" in go
    assert re.search(r"新建出来的 note id: \[0-9a-f\]\{12\}", go), \
        "`@LAST_NEW_NOTE` 没有来源了——它得从上一步自己的日志里接"
    assert "不拿上一批的 id 顶上去" in go, \
        "「这一趟还没造过新笔记」那一档没了——**「没有」和「拿旧的凑一个」不是一回事**"


def test_那一行的源头还在():
    assert "新建出来的 note id:" in _bare(B1OLD)


def test_步骤脚本和go_sh的代码行里一个写死的note_id都没有():
    """跟 `check-walkthrough-runnable.mts` 第 ⑧ 条**钉的是同一件事**，两条链各一份
    （P81 那一跤：同一行被三个地方钉着，而突变闸只收了两个）。"""
    rx = re.compile(r"(?<![0-9a-f])[0-9a-f]{12}(?![0-9a-f])")
    # 先喂它一个该红的：这条正则真的扒得到 note id
    assert rx.search("b1b.mjs b1b 6cec5c7275c8")
    assert not rx.search("const MIN_STEPS = 8")
    steps = sorted((ROOT / "frontend" / "scripts" / "walkthrough" / "steps").glob("*.mjs"))
    assert len(steps) >= 30
    bad = []
    for f in [*steps, GO_SH]:
        for m in rx.finditer(_bare(f)):
            bad.append(f"{f.name}: {m.group(0)}")
    assert bad == [], "每一趟造出来的都是新的一篇，清单里用 `@LAST_NEW_NOTE`"


def test_那条闸自己在_runnable_里():
    r = RUNNABLE.read_text(encoding="utf-8")
    assert "@LAST_NEW_NOTE" in r and "NOTE_ID_RE" in r and "ID_CASES" in r


def test_假壳那条闸自己的截图也有前缀了():
    """P80 问题 #9：它真跑一趟落 28 张，一直叫 `p70-*`——**它没设前缀**。"""
    s = _bare(FAKESHELL_RUN)
    assert "WALKTHROUGH_SHOT_PREFIX: process.env.WALKTHROUGH_SHOT_PREFIX || 'fakeshell'" in s
