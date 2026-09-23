"""P55（`docs/TRACELOG-product.md` P55 节）：P53 复测读出来的三条新问题 + 两条老的。

  1. 语料垃圾词写进正文（P53 #1）——在 `tests/test_p19.py` 里（那条判据是 P19 建的，闸跟着它走）。
  2. 写出不存在的引用编号（P53 #2）：`citations.truncated_citations` + `citations_exist` 那一支。
  3. 代码判据短路打分 → 那一轮永远进不了 `best`（P53 #4）——正例在 `tests/test_p18.py`
     （`NOT_A_VETO` 那一组闸在那儿），这里只钉「为什么 `JUDGE_FLOOR` 接不住」。
  4. `max_rounds` 路上缺「`best` 不涨就停」（P53 #5）：`modes.best_stalled` + `SHIP_BEST_ON` + 前端那句话。
  5. `verify_beats` 第三种误标（P53 #7）：并列成分逐项核。

每条断言的量程写在 docstring 里（撤掉哪一行它红）。
**每个数都带着参数和语料**：脚本在 `<scratch>/p55_*.py`，语料是 `<scratch>/{p5,…,p53}/runs/*.json`。
"""

from __future__ import annotations

import asyncio
import dataclasses
import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.harness import loop, modes                                     # noqa: E402
from app.harness.checks import citations as cit                         # noqa: E402
from app.harness.checks import skeleton as sk                           # noqa: E402
from app.harness.checks.grounding import citations_exist                # noqa: E402
from app.harness.middleware.best_of import BestOf                       # noqa: E402
from app.harness.middleware.checks import JUDGE_FLOOR_AFTER_FIRST       # noqa: E402
from app.harness.state import State                                     # noqa: E402
from app.harness.tools import ToolContext                               # noqa: E402
from app.harness.types import Dimension, DimensionScore, Evaluation     # noqa: E402

USER = "p55"
DIMS = ("spine_fidelity", "beat_coverage", "non_repetition", "factual_grounding",
        "coherence", "material_use")


def _st(**kw) -> State:
    # `dims` 得是真的 `Dimension`：`checks.pick.pick_dimension` 读 `d.name`
    # （拿字符串元组塞进去会 AttributeError，而那是测试自己的坑，不是判据的）。
    dims = tuple(Dimension(d, "…") for d in DIMS)
    mode = dataclasses.replace(modes.NOTE, dims=dims, max_rounds=8, **kw)
    return State(mode=mode, ctx=ToolContext(user=USER, note_id="n", note_title="t"))


# ======================================================= 2. 被吃掉中段的引用编号（P53 #2）
#
# P53 实拍逐字（`<scratch>/p53/runs/3a3a96354546.json` r2 → 终稿）。
# `terrence-8F6` = 真编号 `terrence-1833-8F6` 被吃掉中段；D4 用 `fact_by_id` 回查过：查无此 id。
REAL_CUT = ("后者不能算作任务流成功，即使用户最终上传了文件；"
            "它说明页面或产品流程仍然把用户推回了额外步骤。[terrence-8F6]")
REAL_OK = "到5月，EVD标准样机预计有500到1000台。[terrence-2046-21F5]"
FACTS = ["[terrence-2046-21F5] 5 月 EVD 标准样机 500–1000 台"]
EXISTS_NONE = (lambda _fid: False)


def test_2_老的两条正则都看不见它_这才是病根():
    """**先把病根钉死**：不是「没查库」，是「压根没看见它」——`fact_by_id` 一次都没被问到。

    量程：把 `CITE` 放宽到两段，这条红（也正因为会红，才不去动它——`CITE` 跟
    `store._CITE` / 前端 `editor/factCite.ts` 是对拍的三处之一）。"""
    text = REAL_CUT + "\n\n" + REAL_OK
    assert cit.cited_ids(text) == ["terrence-2046-21F5"], "三段那条正则只认真编号"
    assert "terrence-8F6" not in cit.cited_ids(text)
    assert cit.malformed_citations(text) == [], "`_LOOSE` 要至少两条短横，两段的它也不收"


def test_2_新判据认得出来_并且查得到就不报():
    """量程：把 `truncated_citations` 里 `if exists(fid): continue` 那行删掉，第二条红。"""
    assert cit.truncated_citations(REAL_CUT, FACTS, EXISTS_NONE) == ["terrence-8F6"]
    assert cit.truncated_citations(REAL_CUT, FACTS, lambda _f: True) == [], "查得到就是真的"


@pytest.mark.parametrize("text, facts, why", [
    ("见 [Fig-1]、[TODO-2] 和 [see-A]。" + REAL_OK, FACTS, "不是这篇笔记自己的编号命名空间"),
    ("见 [Fig-1] 和 [TODO-2]。", [], "整篇没有一个合法编号 → 没有命名空间，一个都不报"),
    ("这一句挂 [terrence-2046-21F5]。", FACTS, "合法编号不许被当成残骸"),
])
def test_2_宁可窄_这几种一条都不许报(text, facts, why):
    """量程：把 `ns` 那两行（前缀必须来自本篇合法编号）删掉，第一、二条红。"""
    assert cit.truncated_citations(text, facts, EXISTS_NONE) == [], why


def test_2_判据接上了_而且只管这次跑新写的():
    """**接线洞单独一条断言**：`citations_exist` 真的调了 `truncated_citations`，
    而且用户开跑前就贴在正文里的那个一个字都不碰（P5 实拍 `a941efecd390` 被删 8 条正确引用
    就是从「把用户贴的当成本轮产物」开始的）。

    量程：① 把 `grounding.citations_exist` 里 `cut = [...]` 那几行删掉 → 第一段红；
    ② 把 `if f"[{fid}]" not in before` 那半行删掉 → 第二段红。"""
    st = _st()
    st.facts = list(FACTS)
    st.bag["content_at_start"] = ""
    st.content = REAL_CUT + "\n\n" + REAL_OK
    v = citations_exist(st)
    assert v is not None and "terrence-8F6" in v.message
    assert v.fix is not None and "[terrence-8F6]" not in v.fix(st.content)
    assert "[terrence-2046-21F5]" in v.fix(st.content), "真编号不许被误伤"
    assert v.fix_note, "动了手就得说一句（P26 #3）"

    st2 = _st()
    st2.facts = list(FACTS)
    st2.bag["content_at_start"] = REAL_CUT          # 用户自己原来就贴着它
    st2.content = REAL_CUT + "\n\n" + REAL_OK
    assert citations_exist(st2) is None, "开跑前正文里就有的不算这次跑编的"


# ============================================ 3. 短路轮进不了 best：JUDGE_FLOOR 为什么接不住
#
# P53 实拍 `603dca25403a`：r1 真打分 → r2/r3 短路 → **r4 真打分把 streak 归零** → r5 短路。
# `JUDGE_FLOOR_AFTER_FIRST = 3` 永远够不着。这一条把那个反事实钉住，
# 免得下一批又去动 `JUDGE_FLOOR`（那两段门槛是 P26 量过的，不是这条病的药）。
def test_3_judge_floor接不住603dca那条轨迹():
    """量程：把 `JUDGE_FLOOR_AFTER_FIRST` 改成 2，这条红——同时也就解释了为什么它不是这条病的药。"""
    streak, released = 0, []
    for rnd, short_circuited in ((1, False), (2, True), (3, True), (4, False), (5, True)):
        if streak >= JUDGE_FLOOR_AFTER_FIRST:
            released.append(rnd)
            streak = 0
            continue
        streak = streak + 1 if short_circuited else 0
    assert released == [], "五轮里一次都放行不了：最长只攒到 2"
    assert JUDGE_FLOOR_AFTER_FIRST == 3


# ================================================== 4. `best` 不涨就停（P53 #5 / modes.best_stalled）

def _judged(**levels) -> Evaluation:
    lv = {d: 2 for d in DIMS} | levels
    return Evaluation(scores={d: DimensionScore(level=lv[d], note="") for d in DIMS},
                      status="continue", weakest=min(lv, key=lv.get))


def _round(st: State, n: int, ev: Evaluation, content: str) -> None:
    st.round, st.ev, st.content = n, ev, content
    asyncio.run(BestOf().after_judge(st))
    st.ev = None


def test_4_best连四轮不涨就停_实拍3a3a那条轨迹():
    """P53 实拍 `3a3a96354546`：`best` 从 r3 的 [4, 1.667] 起 r4–r8 五轮一格没涨，跑满 8 轮。

    量程：把 `modes.BEST_STALL_ROUNDS` 改成 5，这条红（第 7 轮停不了）。"""
    st = _st()
    _round(st, 1, _judged(beat_coverage=0, coherence=0), "r1")
    _round(st, 2, _judged(beat_coverage=0, coherence=0), "r1 r2")
    _round(st, 3, _judged(coherence=1, non_repetition=1), "r1 r2 r3")
    top = st.best[0]
    stops = []
    for n in range(4, 9):
        _round(st, n, _judged(coherence=1, non_repetition=1), "r1 " * n)
        assert st.best[0] == top, f"r{n}：best 一格没涨"
        stops.append((n, modes.best_stalled(st)))
    assert [n for n, s in stops if s] == [7, 8], f"第 7 轮该停，实际 {stops}"
    assert modes.BEST_STALL_ROUNDS == 4


def test_4_best涨了就清零_不许误伤能写完的跑():
    """P53 / P22 实拍 `da080ca847cf`：best 在 r1 之后连着 3 轮没涨，**第 5 轮才 `complete` 并涨一格**。
    N=3 会在 r4 把它掐掉（量出来的两次误伤之一），N=4 不会。

    量程：把 `BEST_STALL_ROUNDS` 改成 3，这条红。"""
    st = _st()
    _round(st, 1, _judged(coherence=1), "r1")
    for n in (2, 3, 4):
        _round(st, n, _judged(coherence=1), "r1 " * n)
        assert modes.best_stalled(st) is None, f"r{n} 不许停"
    _round(st, 5, _judged(), "r1 r2 r3 r4 r5")
    assert st.best[1] == "r1 r2 r3 r4 r5", "第 5 轮涨了一格，best 换过来"
    assert st.bag["best_stall"] == 0, "涨了就清零"


def test_4_停了要交best_不是交这一轮():
    """量程：把 `"best_stalled"` 从 `loop.SHIP_BEST_ON` 里删掉，这条红——
    那会让这条规则变成「跑到最差的一轮就停在那儿」，比不加更糟。"""
    assert "best_stalled" in loop.SHIP_BEST_ON
    assert modes.best_stalled in modes.NOTE.stop_when
    # **`stalled` 排在它前面**：那条更具体（连正文都没变）。
    names = [f.__name__ for f in modes.NOTE.stop_when]
    assert names.index("stalled") < names.index("best_stalled")


def test_4_前端认得这个新的停机原因():
    """**接线洞单独一条断言**：后端加了一个 `reason`，前端那串三元里没有对应分支时
    它会落到「到达轮数上限，自动停止」——一句**反的**话（这条规则说的是再跑也不会更好）。

    量程：把 `App.tsx` 里 `reason === 'best_stalled'` 那一支删掉，这条红。"""
    app = (pathlib.Path(__file__).resolve().parents[2] / "frontend/src/App.tsx").read_text(encoding="utf-8")
    assert "reason === 'best_stalled'" in app
    i = app.index("reason === 'best_stalled'")
    j = app.index("'本次达到轮数上限但尚未达标")
    assert i < j, "得排在兜底那句前面，不然写了也走不到"


# ============================================ 5. 一条节拍列四件事、正文写了三件（P53 #7）
#
# P53 实拍 N4 B5 逐字（`<scratch>/p53/d1_skeleton_p53.json` 的 `e78306202d78`）。
BEAT_N4B5 = ("待补：把午餐会后的试点责任、接入对象、课程标签与时间表具体化，"
             "并明确如何在上市前验证“到了以后一打开答案就搁在那”是否真的取代了手动记录与二次整理。")
# 正文用实拍那篇的形状：接入对象在前一段、课程标签隔了很远的一段（超出 3 段窗口），试点责任全文没有。
# 形状照实拍摆：接入对象 / 时间表 / 上市前验证都落在同一个 3 段窗口里（覆盖率 0.806，**远超门槛**），
# **课程标签隔在窗口外的最后一段**，试点责任全文一个字没有——「已写（第 5 行起）」因此是假话。
NOTE_N4 = "\n\n".join([
    "陈校提到国际课程本土化和行业案例支撑的需求，午餐会被设为机制落地的转折点。",
    "录后仍需打开手机、手动上传和整理，二次整理把答案拖在后面。",
    "午餐会后要明确接入对象、具体化时间表，并在上市前验证“到了以后一打开答案就搁在那”"
    "是否真的取代了手动记录与二次整理。",
    "接入对象定为共创群与案例库，录音结束后自动推送到群里。",
    "上市前先验证一遍，时间表放在 6 月末到 7 月这个窗口。",
    "案例库按课程标签归档，教师按课程标签检索历史素材。",
])


def test_5_四件事写了三件_不许标已写():
    """量程：把 `verify_beats` 里 `and not uncovered_items(body, content)` 删掉，这条红。"""
    body = BEAT_N4B5.split("：", 1)[1]
    score, line = sk.beat_coverage(body, NOTE_N4)
    assert score >= sk.COVER_MIN, f"覆盖率照旧过门槛（{score}）——**病不在门槛上**"
    assert line is not None
    assert sk.uncovered_items(body, NOTE_N4), "并列项里有一项在那个窗口里连一半词元都没有"
    assert sk.verify_beats([BEAT_N4B5], NOTE_N4)[0].startswith("待补：")


def test_5_不再抬门槛_COVER_MIN一格没动():
    """P24 在 57 条节拍上量过：真·已写最低 0.165、真·待补最高 0.387，两簇本来就重叠，
    0.42 再往上会误伤真·已写。这一批**不动它**，另加一条。

    量程：改 `COVER_MIN`，这条红。"""
    assert sk.COVER_MIN == 0.42
    assert sk.COVER_ITEM_MIN == 0.5


def test_5_四件事都写了_照旧翻成已写():
    """反向那一半：并列项全在同一个窗口里，行为一个字不变。"""
    note = "\n\n".join([
        "午餐会之后的安排落到四件事上。",
        "试点责任由陈校指定的课程负责人承担，接入对象是共创群与案例库，"
        "课程标签按学科分档，时间表定在 6 月末到 7 月。",
        "上市前验证一遍打开就有答案、不用再手动记录和二次整理。",
    ])
    body = BEAT_N4B5.split("：", 1)[1]
    assert sk.uncovered_items(body, note) == []
    assert sk.verify_beats([BEAT_N4B5], note)[0].startswith("已写（正文第")


# P53 / P25 / P22 / P4 四批同一条节拍逐字（`603dca25403a` 的 B2）。配的正文是那篇的形状：
# 「行情判断」这一项在正文里写成「对行情…的判断」——双字词元只对得上一半。
BEAT_N5B2 = ("待补：把目标从“谁说了什么”推进到方案比较，"
             "明确需要并列呈现报价、行情判断、目标买家、成交周期、判断依据和待核实事项。")
NOTE_N5 = "\n\n".join([
    "这个月不同中介给了不同的报价，也各自解释了他们对行情、买家和成交周期的判断。",
    "比较表要并列呈现报价、目标买家、成交周期、判断依据和仍需核实的事项，"
    "并把每个中介对行情的判断照原话写进去。",
    "这样整理之后，下一步该继续问谁、补什么信息才明确得起来。",
])


def test_5_半数这个门槛两边都分得开():
    """`COVER_ITEM_MIN = 0.5` 得是个**证明得了自己**的数——两边各有一条实拍钉着：

    · 松一格（「任意一个词元就算写了」）→ P53 那条 N4 B5 漏出去（`课程标签` 命中 1/3 会被放行）；
    · 紧一格（「全部词元才算写了」）→ 这一条被误伤：`行情判断` 的词元是 `判断` / `情判`，
      正文写的是「对行情**的**判断」，`情判` 跨不过那个「的」——命中 1/2，**正好卡在 0.5 上**。
      全语料 89 条里这么被误伤的有 12 条，全是「行情判断 / 麦克风指示灯 / 转化阈值」这一族。

    量程：把 `uncovered_items` 里 `< COVER_ITEM_MIN * len(t)` 改成 `< len(t)` → 第二段红；
    改成 `< 0.01 * len(t)` → 第一段红。"""
    body4 = BEAT_N4B5.split("：", 1)[1]
    assert sk.uncovered_items(body4, NOTE_N4) == ["课程标签"], "松一格就会放它过去"
    assert len(_hits("课程标签", body4, NOTE_N4)) == 1, "它是「命中一个、不够一半」这一档"

    body5 = BEAT_N5B2.split("：", 1)[1]
    assert "行情判断" in sk.enum_inner_items(body5)
    assert _hits("行情判断", body5, NOTE_N5) == {"判断"}, "1/2，正好卡在门槛上"
    assert sk.uncovered_items(body5, NOTE_N5) == [], "紧一格就会误伤它"
    assert sk.verify_beats([BEAT_N5B2], NOTE_N5)[0].startswith("已写（正文第")


def _hits(item: str, body: str, content: str) -> set:
    """这一项的词元里，有哪几个落在那条节拍的最佳窗口里。**跟 `uncovered_items` 同一条路**
    （窗口的算法只有 `skeleton` 里那一份，测试不许另写一套——两套口径混着读是被换掉过的死因）。"""
    from app.harness.checks.skeleton import (COVER_WINDOW, _cov_terms, _paragraphs,
                                             _strip_placeholders)
    bt = _cov_terms(body)
    pt = [(ln, _cov_terms(t)) for ln, t in _paragraphs(_strip_placeholders(content))]
    best, union = 0.0, set()
    for i in range(len(pt)):
        u = set()
        for _ln, t in pt[i:i + COVER_WINDOW]:
            u |= t
        sc = len(bt & u) / len(bt)
        if sc > best:
            best, union = sc, u
    return _cov_terms(item) & union


def test_5_不列举的节拍一个字都不碰():
    """射程窄：没有「≥3 项顿号串」就压根不进这条规则。

    量程：把 `_ENUM_RUN` 里的 `{2,}` 改成 `{1,}`，这条红。"""
    plain = "待补：需要一个明确的结尾回扣开场，把前述案例归并成一套可复制的方法。"
    assert sk.enum_items(plain.split("：", 1)[1]) == []
    assert sk.uncovered_items(plain.split("：", 1)[1], NOTE_N4) == []
    two = "待补：把责任和时间表具体化。"
    assert sk.enum_items(two.split("：", 1)[1]) == [], "两项不算并列串"


def test_5_只用内部项_两端切错的不许凭空报漏项():
    """首项挂着动词 / 定语、末项拖着谓语，没有分词器就切不准——用它们会**凭空报一个漏项**。

    量程：把 `enum_inner_items` 的 `[1:-1]` 去掉，这条红。"""
    body = BEAT_N4B5.split("：", 1)[1]
    assert sk.enum_items(body) == ["餐会后的试点责任", "接入对象", "课程标签", "时间表"]
    assert sk.enum_inner_items(body) == ["接入对象", "课程标签"], "首末两项都被切错了，丢掉"
    # P22 实拍那条的末项被截成「证据逐」（原文是「证据、逐项填入表格」）——内部项里没有它。
    n5b4 = ("把本月各中介的实际金额、原话、买家反馈、时间范围和证据逐项填入表格，"
            "否则当前仍是整理模板。")
    assert "证据逐" in sk.enum_items(n5b4)
    assert "证据逐" not in sk.enum_inner_items(n5b4)


def test_5_verify_beats的另外两支行为一个字没变():
    """射程只有「missing → written」那一支：本来标「已写」的原样留着（连行号一起），
    没标的那一支照旧只看覆盖率。**头几刀把这两支也算进射程，是算错了射程。**

    量程：把 `and not uncovered_items(...)` 从第一支挪到第三支，第二段红。"""
    body = BEAT_N4B5.split("：", 1)[1]
    assert sk.uncovered_items(body, NOTE_N4), "前提：这条节拍在这篇正文上是有漏项的"
    kept = sk.verify_beats(["已写（正文第 3 行起）：" + body], NOTE_N4)[0]
    assert kept.startswith("已写（正文第 3 行起）："), "标了已写的不动（幂等，行号也留着）"
    bare = sk.verify_beats([body], NOTE_N4)[0]
    assert bare.startswith(sk.BEAT_WRITTEN), "没标的那一支照旧只看覆盖率"


# ==================================================================== 台账口径

def test_口径_这一批动了哪几处():
    """**改了什么要数得出来**（§21）。下一批读台账的人拿这条对，不用回去翻 diff。"""
    from app.harness.checks.language import JUNK_WORDS
    from app.harness.middleware.best_of import NOT_A_VETO
    assert JUNK_WORDS == ("一本道", "做爰片")                        # #1
    assert hasattr(cit, "truncated_citations")                        # #2
    assert NOT_A_VETO == ("done_criteria", "citations_present")       # #3
    assert modes.BEST_STALL_ROUNDS == 4                               # #4
    assert sk.COVER_ITEM_MIN == 0.5 and sk.COVER_MIN == 0.42          # #5（门槛没动）
    # `loop.py` 的循环结构一个字没动（这一批的硬约束）。
    src = (pathlib.Path(__file__).resolve().parents[1] / "app/harness/loop.py").read_text(encoding="utf-8")
    assert len(re.findall(r"^\s*while ", src, re.M)) == 0
    assert 'SHIP_BEST_ON = ("regressed", "cost_cap", "check_stuck", "best_stalled")' in src
