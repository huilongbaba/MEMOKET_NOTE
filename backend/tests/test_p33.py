"""P33：判据第一轮的措辞（#2）+ `MIN_VERBATIM_EN` 的样本（#4）。

#1（轮次卡片那堵墙）在前端，闸在 `frontend/src/editor/__tests__/p33.test.ts`；
#3（另外四个 block 模式的真跑素材）和 #5（`after_judge` 分母）是素材 / 数数，
代码一个字没改，台账里给表。
"""
from __future__ import annotations

from app.harness.checks import citations as C
from app.harness.checks.grounding import citations_present
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import Dimension, Mode

# ------------------------------------------------------------------ #2 ---
#
# P30 #1 把第 1 轮那句话的射程量死了：四批 20 跑终稿的**可引率只有 7.7–9.1%**，
# 也就是说旧那句「把真正用到的那几条的编号写在对应句子末尾」九成以上是冲着
# 「材料里根本没有逐字出处」的句子喊的——一条办不到的指令。
# 第 2 轮起 P24 已经换过（`said_before` 那一支），第 1 轮那句这一批才换。

FACTS = [
    "[terrence-2046-12F8] 硬件这边要准备 4 台主机和 15 套 PCBA。",
    "[terrence-1812-0F1] 老 MP 的最终时间是 7 月 29 号。",
]
# 一整段没有编号、也跟材料零逐字重合的正文（`MIN_CITED_ROUND_CHARS` 要够长）。
NO_SOURCE = "午餐会上需要把这条数据流拆成可以当场确认的责任链。" * 20
# 一句逐字对得上 `terrence-2046-12F8`（共享 ≥6 字连续汉字「4 台主机」+「15 套 PCBA」）。
ONE_SOURCE = "硬件这边要准备 4 台主机和 15 套 PCBA，别的先不动。" + "还要接着往下写很多字。" * 30


def _st(fresh: str, facts=FACTS, said_before: int = 0) -> State:
    """跟 `test_p24_harness._cite_state` 同一个形状：`citations_present` 要的是
    「手上有材料、这一轮写了整整一段、一个编号都没有」。"""
    mode = Mode(key="t", label="t", dims=(Dimension("factual_grounding", "..."),))
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n"))
    st.facts = list(facts)
    st.fresh = fresh
    st.content = fresh
    if said_before:
        st.bag["check_name_streak_prev"] = {"citations_present": said_before}
    return st


def test_2_第一轮_没有一句有逐字出处时_不再喊补编号():
    """**这是这一条的正题**：可引率 <10% 的那九成句子上，旧那句是办不到的指令。"""
    v = citations_present(_st(NO_SOURCE))
    assert v is not None
    m = v.message
    # 换成做得到的那件事
    assert "没有一句" in m and "编号补不出来" in m
    assert "把这一段改写成材料里真有的那几条" in m
    # 旧那句里那条办不到的要求必须消失
    assert "把真正用到的那几条的编号写在对应句子末尾" not in m
    # 但「第 1 轮」的身份不变：不许冒充第 2 轮
    assert "第 2 轮了" not in m
    # P15 #2 那条（引笔记也算）一个字不许掉
    assert "note://" in m
    # P30 定的：不报百分比
    assert "%" not in m and "％" not in m


def test_2_第一轮_有逐字出处就逐句点名_把编号给出来():
    v = citations_present(_st(ONE_SOURCE))
    assert v is not None
    m = v.message
    # 分子分母都报（P30 的 `citation_coverage` 口径）
    assert "1 句在材料里找得到逐字出处" in m and "0 句贴了编号" in m
    # 编号直接给，模型不用自己猜
    assert "[terrence-2046-12F8]" in m
    assert "编号照抄在句末就行" in m
    assert "%" not in m


def test_2_第一轮_定得到但每句都沾着好几条_不许说贴哪个():
    """`locate_sources` 按唯一性规则不说，判据也不许说——
    「一个像真的一样的引用比不引用更糟」（`citations_exist` 的原话）。"""
    both = FACTS + ["[terrence-9-9F9] 4 台主机和 15 套 PCBA 这批先不做包装。"]
    v = citations_present(_st(ONE_SOURCE, facts=both))
    assert v is not None
    m = v.message
    assert "贴哪个都可能错" in m and "先把句子写窄" in m
    # 有分母就得报出来
    assert "在材料里找得到逐字出处" in m
    # 绝不许在这一档甩出一个编号
    assert "[terrence-2046-12F8]" not in m and "[terrence-9-9F9]" not in m


def test_2_分母走的是_citation_coverage_不是第二套算法():
    """两套口径混着读正是被换掉的那一格的死因（P30 #1）。
    判据报的分母必须跟面板那一格是同一个函数算出来的。"""
    cov = C.citation_coverage(ONE_SOURCE, FACTS)
    v = citations_present(_st(ONE_SOURCE))
    assert v is not None
    assert f"{cov.located} 句在材料里找得到逐字出处" in v.message
    assert f"{cov.marked} 句贴了编号" in v.message
    # 第 1 轮 `marked` 恒等于 0（上面那道 `has_citation` 的早退挡掉了带编号的正文）
    assert cov.marked == 0


def test_2_第二轮起那句一个字没动():
    """P24 改的那两支这一批**不许**跟着漂——它们是另一个问题的答案。"""
    v = citations_present(_st(NO_SOURCE, said_before=1))
    assert v is not None and "第 2 轮了，还是一个编号都没有" in v.message
    assert "不要再去补编号了" in v.message
    v2 = citations_present(_st(ONE_SOURCE, said_before=1))
    assert v2 is not None and "第 2 轮了" in v2.message
    assert "[terrence-2046-12F8]" in v2.message


# ------------------------------------------------------------------ #4 ---
#
# `MIN_VERBATIM_EN = 4` 的样本（P30 留给下一批 #7）。
# **全库 482 篇里「英文为主」的只有 1 篇**（`p33/m4_en.py`：汉字占比的分布在
# 0.000 和 0.740 之间完全是空的，没有第二篇），于是量程从「篇」换成「句」
# （`p33/m4b_en_sents.py`：全库 3383 句里不含汉字的只有 21 句，19 句有材料）。
#
# 量出来的结论：
#   · **n=3 多出 3 句，3 句全是假的**——`to the next` / `speaker b says` /
#     `speaker a says`，全是功能词和转写模板（P30 在另一份语料上量到的同一类）；
#   · **n=4 和 n=5 在全库上一个字都不差**（各 3 句，全是真出处）——
#     这个语料**判不出 4 和 5 的差别**，所以改成 5 没有依据，4 保持不动；
#   · n=4 那几句里有一句是 P30 没有的**第二个真出处**，落在另一篇笔记上。

# `terrence/e78306202d78` 正文里那一句，和 `[terrence-1812-0F1]` 材料，逐字。
SLOGAN_SENT = ("Memocad exists because we believe that you think better, "
               "function better when you're not worried about forgetting")
SLOGAN_FACT = ("[terrence-1812-0F1]  [2026-02-25] Memocad exists because we believe "
               "that you think better, function better when you're not worried "
               "about forgetting.")
# 只有 n=3 才会命中的三句（`p33/m4d_n3.py` 逐条读出来的），和它们各自匹上的材料。
TEMPLATES = [
    ("Speaker B thinks the fast pace comes from passion and a desire to do things "
     "faster to move to the next step quickly.",
     "[terrence-385-9F8]  [2026-01-06] it just moves you to the next tab, which is "
     "the key points whereby it's going to remind you of maybe all the things from "
     "the text that you might need to remember or keep in memory",
     "to the next"),
    ("Speaker B says sometimes I'm rash. I often lost the major major things of the "
     "questions like a letter or a words.",
     "[terrence-379-23F5]  [2026-01-06] Speaker B says the tool would help avoid "
     "missing anything important because it would pull everything from the "
     "recordings instead of relying on memory.",
     "speaker b says"),
    ("Speaker A says sometimes students don't like to admit that they don't "
     "understand, and they don't feel comfortable to speak with the teacher.",
     "[terrence-1815-31F8]  [2026-02-25] Speaker A says you mean Anson, right?",
     "speaker a says"),
]


def test_4_门槛还是_4():
    assert C.MIN_VERBATIM_EN == 4


def test_4_真出处_第二篇笔记上那一句_n4_命中且唯一():
    """P30 定这个门槛时只有 `a941efecd390` 一句撑着。这是**第二篇笔记上的第二句**，
    而且它是材料的逐字引用（整句一模一样），不是模板。"""
    assert C._shares_verbatim_en(SLOGAN_SENT, SLOGAN_FACT)
    located = C.locate_sources(SLOGAN_SENT + "。", [SLOGAN_FACT])
    assert [fid for _s, fid in located] == ["terrence-1812-0F1"], "唯一命中，贴得出来"


def test_4_门槛退到_3_就把三句转写模板全放进来():
    """撤成 3 这一刀砍得到：三句全是功能词 / `speaker x says` 串，
    跟材料讲的事零关系。"""
    for sent, fact, shared in TEMPLATES:
        assert not C._shares_verbatim_en(sent, fact), f"n=4 不该命中：{shared}"
        assert C._shares_verbatim_en(sent, fact, n=3), f"n=3 会命中：{shared}"


def test_4_门槛抬到_5_在笔记正文这份语料上砍空了():
    """**「闸红了」不等于「闸抓到了东西」**（§21 P28 那条第五种），这一条把界划清楚。

    这一批新量的语料是**笔记正文**（`p33/m4b_en_sents.py`：全库 3383 句里
    19 句纯英文句有材料）。在它上面 n=4 和 n=5 **结果一模一样**——
    下面这条断言在 4 和 5 上都成立，也就是说**这份语料判不出 4 和 5 的差别**。

    4 和 5 的差别**在 P30 那份语料上**（跑出来的正文，不是笔记正文）：
    `a941` 那句 OneNote 跟材料的重合正好是 **4 个词**，抬到 5 就丢了，
    `test_p30.py::test_1_突变_英文门槛降到3就把转写模板认成出处` 守的正是它
    ——实测把门槛改成 5，红的就是那一条。
    **所以门槛不动的依据在 P30 那份语料，这一批扩的是 n=3 那一侧的反证。**
    """
    assert C._shares_verbatim_en(SLOGAN_SENT, SLOGAN_FACT, n=5)
    assert C._shares_verbatim_en(SLOGAN_SENT, SLOGAN_FACT, n=4)
    for sent, fact, _shared in TEMPLATES:
        assert not C._shares_verbatim_en(sent, fact, n=5)
        assert not C._shares_verbatim_en(sent, fact, n=4)
