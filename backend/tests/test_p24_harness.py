"""P24：P22 复测读出来的 harness 侧五条。

每一条都钉两面——**正向**（P22 那处实拍的原文进去，现在判对了）和
**反向 / 突变**（把改动抠掉一点点，断言就该红；不该误伤的那些照旧不开火）。

  #1 `verify_beats` 把真·待补翻成「已写」 → `checks/skeleton.py`
  #2 续写这一步从不写引用编号        → `checks/citations.py` + `checks/grounding.py`
  #3 `check_stuck` 被交替响的判据绕过 → `modes.py` + `middleware/checks.py`
  #4 重复变多（10 → 12 处）          → `checks/blockcheck.py` + `checks/structure.py`
  #5 18 轮只有 6 轮真打分            → `middleware/checks.py`
"""

from __future__ import annotations

import dataclasses

import pytest

from app.harness.checks import blockcheck, skeleton as sk
from app.harness.checks.citations import locate_sources
from app.harness.checks.grounding import citations_present
from app.harness.checks.structure import PARA_ECHO_RATIO, no_echoed_text
from app.harness.middleware.checks import JUDGE_FLOOR, Checks
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import Dimension, DimensionScore, Evaluation, Mode, Verdict


def _st(checks=(), dims=("factual_grounding", "non_repetition")) -> State:
    mode = Mode(key="t", label="t", skill_scope="test_scope",
                dims=tuple(Dimension(d, "...") for d in dims),
                checks=tuple(checks))
    return State(mode=mode, ctx=ToolContext(user="u", note_id="n"))


# ------------------------------------------------------------------ #1 ---

# P22 N5 `603dca25403a` 的正文，逐字（表就是它的第 7–11 行）。
TABLE_NOTE = (
    "我这个月干了不少和卖房有关的沟通：不同中介给了不同的报价，也各自解释了他们对行情、买家和成交周期的判断。"
    "普通总结能把这些聊天和电话压缩成几段话，会议纪要也能列出“谁说了什么”，但这还不够。"
    "真正有用的结果，应该把分散在不同对话里的报价和理由放在一起，指出它们之间的差异，"
    "再告诉我下一步该继续问谁、补什么信息、哪些判断需要拿出来比较。\n\n"
    "所以，产出不应只是“这几位中介分别说了什么”，而应进一步变成：当前有哪些方案、每个方案依据是什么、"
    "分歧在哪里，以及我今天能据此做什么决定。**总结只是把内容变短，判断结果则要让我少做一次整理、比对和重新回忆。\n\n"
    "落地时，至少要把各中介的具体方案放在同一张表里比较，不能只写“有人看高、有人看低”：\n\n"
    "| 中介 | 报价 | 对行情的判断 | 目标买家 | 预计成交周期 | 判断依据 | 仍需核实 |\n"
    "|---|---:|---|---|---|---|---|\n"
    "| A | 填写具体金额 | 填写原话或明确判断 | 填写买家类型 | 填写时间范围 | 可比成交、带看反馈或其他材料 | 填写待核实内容 |\n"
    "| B | 填写具体金额 | 填写原话或明确判断 | 填写买家类型 | 填写时间范围 | 可比成交、带看反馈或其他材料 | 填写待核实内容 |\n"
    "表中要把内容分成三类：已经发生、可以核实的事实；中介基于经验作出的推测；以及彼此直接冲突的比如，"
    "报价不同本身不是结论，关键是要继续追问：这个价格对应哪些可比成交案例。\n\n"
    "这样整理后，下一步才会明确：要求报价偏高或偏低的中介补充可比案例，向对买家判断最具体的人核实近期带看和反馈，"
    "要求给出成交周期依据；在关键依据尚未补齐前，暂缓接受任何一个单独的报价或周期判断。\n")
BEAT_N5B4 = ("待补：把本月各中介的实际金额、原话、买家反馈、时间范围和证据逐项填入表格，"
             "否则当前仍是整理模板，尚未形成针对这些中介的比较结论。")


def test_1_占位格不算已写_P22实拍那条待补保持待补():
    assert sk.verify_beats([BEAT_N5B4], TABLE_NOTE)[0].startswith("待补：")


def test_1_占位格那一条要对分数下断言_不然它是个证明不了自己的守卫():
    """**这条是突变验逼出来的。**

    第一版只断言「结论是待补」，而门槛已经提到 0.42 —— 把 `_strip_placeholders`
    从 `beat_coverage` 里整个拿掉，结论照样是「待补」（0.371 < 0.42），全套一条没红。
    §21 那条规矩说得很清楚：**留着一条谁也证明不了它在挡什么的守卫，比没有更糟**；
    两条路里选「把它挡住的那件事变成可观测的」——断言落在**分数**上。

    它挡的是**机制**：N5 B4 命中的 13 个词元里有 5 个（金额 / 原话 / 买家 / 时间 / 范围）
    逐字来自「填写具体金额」这种格子。抹掉之后 0.371 → 0.229，
    余量从离门槛 0.049 变成 0.19。两条（口径 + 门槛）各自都够把 P22 那两处挡住，
    但只有口径修的是「为什么会命中」。
    """
    body = BEAT_N5B4.split("：", 1)[1]
    assert sk.beat_coverage(body, TABLE_NOTE)[0] <= 0.25, "占位格没被抹掉"
    keep = sk._strip_placeholders
    try:
        sk._strip_placeholders = lambda content: content
        assert sk.beat_coverage(body, TABLE_NOTE)[0] >= 0.35, "不抹的话它就是靠占位格命中的"
    finally:
        sk._strip_placeholders = keep


def test_1_突变_把占位格剔除去掉_门槛再退回0_30就又翻成已写了():
    """两条守卫一起拿掉，P22 #1 那处实拍原样复现（「已写（正文第 7 行起）」）。"""
    keep = sk._strip_placeholders
    try:
        sk._strip_placeholders = lambda content: content
        got = sk.verify_beats([BEAT_N5B4], TABLE_NOTE, threshold=0.30)[0]
        assert got.startswith("已写（正文第 7 行起）"), "守卫一拿掉就该复现"
    finally:
        sk._strip_placeholders = keep
    # 门槛那一半单独也够：口径修好了，但门槛退回 0.30 呢？—— 0.229 还是在门槛下，所以这里
    # 断言的是**另一条实拍**（N3 B5，正文里没有占位格可抹，全靠门槛挡住）。
    assert 0.30 < 0.387 < sk.COVER_MIN


def test_1_真写了的照样翻过来():
    """反向那一半：格子里填的是真数字，节拍说「已经填了」，就该翻成「已写」。"""
    filled = TABLE_NOTE.replace("填写具体金额", "310 万").replace("填写原话或明确判断", "看涨") \
                       .replace("填写买家类型", "学位房家庭").replace("填写时间范围", "两个月") \
                       .replace("填写待核实内容", "带看记录")
    beat = "待补：把各中介的报价、对行情的判断、目标买家、预计成交周期和判断依据逐项填进比较表。"
    assert sk.verify_beats([beat], filled)[0].startswith("已写（正文第")


def test_1_抹掉占位格不改行号也不改分段():
    stripped = sk._strip_placeholders(TABLE_NOTE)
    assert stripped.count("\n") == TABLE_NOTE.count("\n")
    assert [ln for ln, _t in sk._paragraphs(stripped)] == \
           [ln for ln, _t in sk._paragraphs(TABLE_NOTE)]
    # 整行就是一个占位符时，留一个非空字符——不然一段会被劈成两段
    two = "上面这段。\n待补\n下面这段。"
    assert len(sk._paragraphs(sk._strip_placeholders(two))) == len(sk._paragraphs(two)) == 1


def test_1_门槛落在两批量出来的缺口里():
    assert 0.387 < sk.COVER_MIN < 0.458


# ------------------------------------------------------------------ #2 ---

FACTS = ["[terrence-1833-8F6] T0的话，基本上要到5月15号。",
         "（2026-05-15 · speaker c · plan）",
         "[terrence-2046-12F8] EVT 准备 4 台主机，15 套 PCBA",
         "（2026-04-16 · speaker_c · plan）"]


def test_2_逐字定位_能定到唯一一条才回():
    out = locate_sources("硬件这边要准备 4 台主机和 15 套 PCBA，别的先不动。", FACTS)
    assert out == [("硬件这边要准备 4 台主机和 15 套 PCBA，别的先不动", "terrence-2046-12F8")]


def test_2_定不到就不回_不硬贴():
    """P22 五跑量出来的分母就在这儿：78 句没编号的句子里 72 句是这个形状。"""
    assert locate_sources("午餐会上需要把这条数据流拆成可以当场确认的责任链。", FACTS) == []


def test_2_两条都沾上的不回_贴哪个都可能错():
    both = FACTS + ["[terrence-9-9F9] 4 台主机这批先不做包装", "（2026-04-16 · x · plan）"]
    assert locate_sources("这一批准备 4 台主机。", both) == []


def _cite_state(fresh: str, said_before: int) -> State:
    st = _st(dims=("factual_grounding",))
    st.facts = list(FACTS)
    st.fresh = fresh
    st.content = fresh
    if said_before:
        st.bag["check_name_streak_prev"] = {"citations_present": said_before}
    return st


def test_2_第一轮还是原来那句话():
    v = citations_present(_cite_state("没有编号的一大段。" * 40, 0))
    assert v is not None and "一个 [事实编号] 都没有" in v.message and "第 2 轮了" not in v.message


def test_2_第二轮起换一句话说_能定位的逐句点名():
    fresh = "硬件这边要准备 4 台主机和 15 套 PCBA，别的先不动。" + "还要接着往下写很多字。" * 30
    v = citations_present(_cite_state(fresh, 1))
    assert v is not None and "[terrence-2046-12F8]" in v.message and "第 2 轮了" in v.message


def test_2_第二轮起一句都定不到就换一条做得到的要求():
    v = citations_present(_cite_state("午餐会上需要把这条数据流拆成可以当场确认的责任链。" * 20, 2))
    assert v is not None
    assert "没有一句能在材料里找到逐字的出处" in v.message
    assert "不要再去补编号了" in v.message, "办不到的指令不许再喊第三遍"


def test_2_突变_连响计数丢了就退回原来那句():
    """`check_name_streak_prev` 是 P19 #6 留给判据读的那一份；读不到就升不了级。"""
    st = _cite_state("午餐会上需要把这条数据流拆成可以当场确认的责任链。" * 20, 2)
    st.bag.pop("check_name_streak_prev")
    v = citations_present(st)
    assert v is not None and "第 3 轮了" not in v.message


# ------------------------------------------------------------------ #4 ---

# P22 `e78306202d78` 最终正文里那一句，逐字。
ECHO_SENT = ("试点不应从细碎功能清单开始，而应先串起几个大节点。"
             "项目本身包含硬件、嵌入式和 APP，并按 KO、EVT、T0、DVT、PVT、MP 推进；"
             "其中 T0 预计到 5 月 15 日左右，"
             "项目本身包含硬件、嵌入式和 APP，并按 KO、EVT、T0、DVT、PVT、MP 推进；"
             "这一节点划分来自项目原有排期 [terrence-1833-8F6]，"
             "因此午餐会上应把录后数据流作为独立的验证项 [terrence-1833-8F6]。")


def _echo_state(content: str, before: str = "") -> State:
    st = _st(dims=("non_repetition", "factual_grounding"))
    st.content = content
    st.bag["content_at_start"] = before
    return st


def test_4_句内逐字回声_P22实拍那句被抓住并修掉():
    st = _echo_state(ECHO_SENT)
    v = no_echoed_text(st)
    assert v is not None and v.fix is not None
    fixed = v.fix(st.content)
    assert fixed.count("并按 KO、EVT、T0、DVT、PVT、MP 推进；") == 1
    assert v.fix_done(fixed) is True
    assert len(fixed) < len(st.content) and "其中 T0 预计到 5 月 15 日左右" in fixed


def test_4_同段重编号_修完只剩第一个():
    st = _echo_state(ECHO_SENT)
    once = no_echoed_text(st).fix(st.content)          # 先把句内回声修掉
    st.content = once
    v = no_echoed_text(st)
    assert v is not None and "贴了两次" in v.message
    fixed = v.fix(st.content)
    assert fixed.count("[terrence-1833-8F6]") == 1 and v.fix_done(fixed) is True


def test_4_量程_开跑前就有的不报():
    assert no_echoed_text(_echo_state(ECHO_SENT, before=ECHO_SENT)) is None


def test_4_突变_门槛降到8个汉字就会误伤用户原文():
    """真库里「通过正交交换的架构」（9 字）这种人话里的重提，≥8 就会被当成缺陷。"""
    human = ("第一个就是华为通过自研的灵衢交换架构，柜内通过正交交换的架构可以达到所有部件直连，"
             "以前不同模块之间都是有线连接，而现在通过正交交换的架构，所有部件都像走上高速公路直达。")
    assert blockcheck.echoed_sentence(human) is None, "12 个汉字这一档不该碰它"
    # 把门槛降到 8：同一段人话当场被判成缺陷 —— 这就是 12 这个数的由来
    keep = blockcheck.ECHO_MIN_CJK
    try:
        blockcheck.ECHO_MIN_CJK = 8
        assert blockcheck.echoed_sentence(human) is not None
    finally:
        blockcheck.ECHO_MIN_CJK = keep


def test_4_表格行和引用串不算回声():
    assert blockcheck.echoed_sentence("| 甲 | 乙 |\n|---|---|\n| 1 | 2 |") is None
    ids = " ".join(f"[terrence-2046-12F{i}]" for i in range(1, 6)) + " 这些节点都在四月那一批里定下来的。"
    assert blockcheck.echoed_sentence(ids) is None


def test_4_判据真的挂在两个长文模式上():
    """**建了判据不等于用了判据**（§21 那条，仓里栽过三次）。
    `test_harness_modes` 那条闸只问「每条判据都得开过火」——从 `note` 上摘掉、
    `section` 上还留着的话，它一声不吭地绿着。"""
    from app.harness import modes
    for mode in (modes.NOTE, modes.SECTION):
        assert no_echoed_text in mode.checks, f"{mode.key} 上没挂 no_echoed_text"


def test_4_两段几乎相同_只报不修():
    a = ("这个取舍也呼应产品前提。目标用户不是记忆力近乎完美的人，"
         "而是需要把思考外化、让素材自动进入协作系统的使用者，把录后手动上传的劳动去掉。")
    b = ("这条路径也与使用前提一致。目标用户不是记忆力近乎完美的人，"
         "而是需要把思考外化、让素材自动进入协作系统的使用者，把录后手动上传的劳动去掉。")
    v = no_echoed_text(_echo_state(a + "\n\n" + b))
    assert v is not None and v.fix is None and "几乎是同一段" in v.message
    assert PARA_ECHO_RATIO == 0.85


def test_4_光秃秃的编号段不算两段相同():
    """真库 `df3b4f7e` 那 0.810 就是两行编号——这是格式，不是重复写。

    **素材得真的过得了 0.85 那道门槛**，否则测的是门槛不是这条守卫
    （第一版拿的是真库那两行，difflib 只有 0.81，把 `_bare` 整条拿掉照样绿）。
    """
    from app.harness.middleware import repeats
    a = "[terrence-1346-1F3] [terrence-1346-1F9] [terrence-1346-1F7] [terrence-1346-1F5]"
    b = "[terrence-1346-1F3] [terrence-1346-1F9] [terrence-1346-1F7] [terrence-1346-1F4]"
    hits = repeats.find_repeats(a + "\n\n" + b)
    assert hits and hits[0].similarity >= PARA_ECHO_RATIO, "素材没到门槛，测的就不是这条守卫"
    assert no_echoed_text(_echo_state(a + "\n\n" + b)) is None


# ------------------------------------------------------------------ #3 #5 ---

def _always(dim: str, msg: str):
    return lambda st: Verdict(dim, msg)


async def _round(st: State) -> list:
    st.ev, st.skip_judge = None, False
    return [e async for e in Checks().before_judge(st)]


@pytest.mark.anyio
async def test_5_连着饿死两轮之后第三轮必须真打分():
    msgs = iter(["甲", "乙", "丙", "丁"])
    st = _st([lambda s: Verdict("factual_grounding", next(msgs))])
    for k in range(JUDGE_FLOOR):
        await _round(st)
        assert st.skip_judge, f"第 {k + 1} 轮照旧先判后花钱"
    evs = await _round(st)
    assert not st.skip_judge and st.ev is None, "连着饿死两轮了，这一轮得让打分器跑"
    assert evs[-1].data["value"]["judge_floor"] == JUDGE_FLOOR, "事件要说清是被谁放行的"


@pytest.mark.anyio
async def test_5_放行那一轮不许判写完了():
    msgs = iter(["甲", "乙", "丙"])
    st = _st([lambda s: Verdict("factual_grounding", next(msgs))])
    for _ in range(JUDGE_FLOOR + 1):
        await _round(st)
    st.ev = Evaluation(scores={"factual_grounding": DimensionScore(2, "")}, status="complete")
    await Checks().after_judge(st)
    assert st.ev.status == "continue", "判据还在响就不算写完"


@pytest.mark.anyio
async def test_5_真打过分的那一轮计数归零():
    fires = iter([True, True, False, True, True])
    st = _st([lambda s: Verdict("factual_grounding", "同一句") if next(fires) else None])
    await _round(st); await _round(st)
    await _round(st)                                   # 这一轮没报 → 真打分 → 归零
    assert st.bag["short_circuit_streak"] == 0
    for _ in range(JUDGE_FLOOR):
        await _round(st)
        assert st.skip_judge, "归零之后要重新饿满才放行"


@pytest.mark.anyio
async def test_5_正常判据命中的那一轮照旧不花打分调用():
    """反向：这条改动只该在「连着饿死」时生效，别把先判后花钱那条纪律拆了。"""
    st = _st([_always("factual_grounding", "第一段有占位句")])
    await _round(st)
    assert st.skip_judge and st.ev is not None and st.ev.scores["factual_grounding"].level == 0


@pytest.mark.anyio
async def test_3_窗口口径严格是连响口径的超集():
    """连续 3 轮当然也是「最近 4 轮里 3 次」——新规则只会更早停，不会更晚停。"""
    from app.harness import modes
    st = _st([_always("factual_grounding", "x")])
    for k in range(1, 4):
        st.bag["short_circuit_streak"] = 0          # 把 #5 按住，这条测的是 #3
        await _round(st)
        assert (modes.check_stuck(st) == "check_stuck") is (k >= 3)


@pytest.mark.anyio
async def test_3_窗口滑出去就不算了():
    from app.harness import modes
    fires = iter([True, True, False, False, False])
    st = _st([lambda s: Verdict("factual_grounding", "同一句") if next(fires) else None])
    for _ in range(5):
        st.bag["short_circuit_streak"] = 0
        await _round(st)
        assert modes.check_stuck(st) is None


@pytest.mark.anyio
async def test_3_没有窗口那份时退回连响口径():
    """直接构造 State 的老单测不会有 `check_name_rounds`；那时按 P6 那版回答。"""
    from app.harness import modes
    st = _st()
    st.bag["check_name_streak"] = {"citations_present": 4}
    assert modes.check_stuck_detail(st) == ("citations_present", 4)
    assert modes.check_stuck(st) == "check_stuck"


def test_3_窗口长度和次数是两个数():
    from app.harness import modes
    from app.harness.middleware.checks import CHECK_WINDOW
    assert modes.CHECK_STUCK_WINDOW >= modes.CHECK_STUCK_ROUNDS
    assert CHECK_WINDOW >= modes.CHECK_STUCK_WINDOW, "存的轮数不够，窗口就永远填不满"


@pytest.mark.anyio
async def test_3_突变_窗口缩到和次数一样长就抓不住交替():
    """P22 那个形状（A 在 r1/r2/r4 响）要靠窗口比次数长一轮才抓得住。"""
    from app.harness import modes
    plan = iter(["A", "A", "B", "A"])
    cur = {"who": ""}

    def cites_missing(s):                      # 连响计数按**判据名**，两条得有各自的名字
        return Verdict("factual_grounding", "甲") if cur["who"] == "A" else None

    def lists_repeated(s):
        return Verdict("factual_grounding", "乙") if cur["who"] == "B" else None

    st = _st([cites_missing, lists_repeated])
    keep = modes.CHECK_STUCK_WINDOW
    try:
        modes.CHECK_STUCK_WINDOW = modes.CHECK_STUCK_ROUNDS      # 4 → 3，等于退回「连续」
        for _ in range(4):
            cur["who"] = next(plan)
            st.bag["short_circuit_streak"] = 0
            await _round(st)
        assert modes.check_stuck(st) is None, "窗口一缩短就该复现 P22 那个绕过"
    finally:
        modes.CHECK_STUCK_WINDOW = keep
    assert modes.check_stuck(st) == "check_stuck", "窗口放回 4 就抓得住"


def test_3_state_可以被dataclasses_replace_而窗口不跟着分叉():
    """`middleware/checks` 的 fix 探针会 `dataclasses.replace(st, content=…)`，
    bag 是同一个对象——窗口那份不能因此被复制成两份。"""
    st = _st()
    st.bag["check_name_rounds"] = [{"a": 1}]
    probe = dataclasses.replace(st, content="x")
    probe.bag["check_name_rounds"].append({"b": 1})
    assert len(st.bag["check_name_rounds"]) == 2
