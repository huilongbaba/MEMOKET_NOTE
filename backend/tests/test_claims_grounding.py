"""批 18 / 阶段 7 的两条 `P0`：

* **7.1** `checks/claims.py` —— `factual_grounding` 改 decompose-then-verify
  （[IND] §8①：FActScore / SAFE / VeriScore / Claimify）。
* **7.2** `checks/grounding.material_thin` —— 「这一节的材料够不够」
  （[LED] §10③ `Sufficient Context`），不够就触发仓里既有的弃答形态。

**这份测试最重要的一半是「不该开火」的那一半。** 铁律第 3 条写着
*误伤比漏报贵*，7.1 尤其：把一句有出处的话判成「编造」会逼模型把真内容删掉。
所以每一条「会开火」的用例后面都跟着至少一条「同样的形状、但有出处，不许开火」。
"""

from __future__ import annotations

import re

import pytest

from app.harness import modes, params
from app.harness.agent_loop import ToolTrace
from app.harness.checks import claims
from app.harness.checks import grounding, grounding_rules
from app.harness.state import State
from app.harness.tools import ToolContext


def _st(fresh: str, *, prior: str = "", facts: list[str] | None = None,
        note: str = "", ledger: dict | None = None, calls: int = 1,
        facts_new: list[str] | None = None, mode=None, bag: dict | None = None) -> State:
    """一个够用的 State。``prior`` 是这次跑在这一轮之前已经写出来的部分。"""
    st = State(mode=mode or modes.for_run(modes.NOTE), ctx=ToolContext(user="u", note_id="n"))
    st.fresh = fresh
    st.content = prior + fresh
    st.bag["content_at_start"] = note
    st.facts = list(facts or [])
    st.facts_new = list(facts_new or [])
    st.trace = ToolTrace()
    for i in range(calls):
        st.trace.calls.append(("filter_facts", {"topic": f"t{i}"}, "共 3 条，返回 3 条："))
    if ledger is not None:
        st.bag["ledger"] = ledger
    st.bag.update(bag or {})
    return st


FILLER = "这一段是为了把字数写够，后面才是要核对的那几句话。" * 6


# ======================================================== 7.1 拆解那一半 ===

def test_拆解到句级_不是段也不是子句():
    text = "第一句在这里，中间有个逗号。第二句在这里；第三句在这里！"
    assert claims.decompose(text) == ["第一句在这里，中间有个逗号。", "第二句在这里；", "第三句在这里！"]


def test_围栏和表格里的东西不参与拆解():
    """图里的节点名是内容不是断言，表格里的格子由 `checks/numbers` 那条管。"""
    text = ("正文一句话。\n"
            "```mermaid\nflowchart TD\n A[2027 年 4 月 9 日 交付]\n```\n"
            "| 日期 | 事项 |\n|---|---|\n| 2027 年 4 月 9 日 | 交付 |\n"
            "> 引用块里也有 2027 年 4 月 9 日。\n")
    assert not claims.date_atoms(" ".join(claims.decompose(text)))


def test_碎片率这个数是量得出来的():
    """粒度是个**要量的参数**（`Decomposition Dilemmas`），所以「带指代」这件事
    必须有一个函数说得出来——否则那张表里的 6.1% / 8.1% / 4.2% 是拍的。"""
    assert claims.has_anaphor("这个方案先放一放。")
    assert not claims.has_anaphor("硬件量产计划在四月启动。")


# ======================================================== 7.1 原子那一半 ===

def test_只抽完整日期_两个字段的一律不抽():
    """两字段那一档实测严苛档 21.7% 误伤，见 `claims.py` 模块文档「不取的四类」①。"""
    assert [a.surface for a in claims.date_atoms("2026 年 8 月 5 日定的。")] == ["2026 年 8 月 5 日"]
    assert [a.surface for a in claims.date_atoms("2026-08-05 定的。")] == ["2026-08-05"]
    assert not claims.date_atoms("3 月 31 日要交付。")
    assert not claims.date_atoms("2026 年 6 月上线。")
    assert not claims.date_atoms("2026 年上半年做完。")


def test_不合法的日期不当原子():
    assert not claims.date_atoms("版本号 2026.99.99 不是日期。")
    assert not claims.date_atoms("比例是 3:2:1。")


def test_署名必须紧跟言说动词():
    """不要求动词，这一类就退化成「所有拉丁专名」——那一档实测 45.4% 误伤。"""
    assert [a.surface for a in claims.attributed_atoms("Speaker K 提到这件事。")] == ["Speaker K"]
    assert not claims.attributed_atoms("我们在 Zoom 上开了个会。")
    assert not claims.attributed_atoms("这次用的是 Kickstarter 页面。")


def test_长得像名字的普通词不算署名():
    """`Owner 负责准确性` —— 24 篇真实笔记里实拍到的那一个。"""
    assert not claims.attributed_atoms("每份文档指定 Owner，Owner 负责准确性与时效性。")
    assert not claims.attributed_atoms("This 说法不成立。")


def test_没有中文人名这一类():
    """18 篇真实笔记 + 16 篇脚本产出里总共 4 个候选，3 个是错的
    （`江汽` 两次、`方案已` 一次）。整类不取，这条闸钉住它别被人"顺手补上"。"""
    assert not claims.atoms("江汽负责整车制造，方案已确认。")
    assert not claims.atoms("李文博确认了首年采购额。")


# ================================================ 7.1 SAFE ③：方向只有一个 ===

def test_源头里有正文里没写的材料_永远产生不了任何裁决():
    """**这是 SAFE 第三步在我们这儿的落地形态**，也是 `_FACTUAL_GROUNDING` 里
    那条吃过亏才写进 guidance 的规矩（「检索到的事实没有被全部用上，明确不算
    不足」）——它现在是结构性的：反方向那条路在这个模块里根本不存在。

    为它扣过一次分，下一轮正文里就「引入了大量未在知识库中出现的具体日期与人物」。
    """
    facts = [f"[f-{i}] 2026-0{i % 9 + 1}-1{i % 9} 一条谁也没写进正文的材料 {i}"
             for i in range(40)]
    st = _st(FILLER + "这一轮只写了些通用的话，一条材料都没落地。", facts=facts)
    assert claims.unsupported_specifics(st) is None


def test_同一个原子反复出现只查一次():
    a = claims.relevant(claims.atoms("2026 年 8 月 5 日。又是 2026-08-05。"))
    assert len(a) == 1


# ==================================================== 7.1 判据本体：开火 ===

def test_编造的日期和署名会被抓住():
    st = _st(FILLER + "2027 年 4 月 9 日，Speaker K 提到首年采购额已经谈定。",
             facts=["[f-1] 2026-08-05 硬件方案定了"])
    v = claims.unsupported_specifics(st)
    assert v is not None
    assert v.dimension == "factual_grounding"
    assert "2027 年 4 月 9 日" in v.message and "Speaker K" in v.message


def test_报出来的话不许要求去动别的句子():
    """报一个「查无出处」会逼模型动那句话。诊断必须把范围钉死在那几个字面上。"""
    st = _st(FILLER + "2027 年 4 月 9 日，Speaker K 提到这事。",
             facts=["[f-1] 一条材料"])
    v = claims.unsupported_specifics(st)
    assert "别去动别的句子" in v.message


# ================================================== 7.1 判据本体：不开火 ===

@pytest.mark.parametrize("where", ["facts", "note", "prior"])
def test_名字和日期只要在封闭材料里出现过就不开火(where):
    """源头**宁可多给**：整篇笔记 / 这次跑之前已经写出来的部分 / 事实块，
    任何一处有都算有出处。少给一处就会误伤。"""
    line = "2027 年 4 月 9 日，Speaker K 提到首年采购额已经谈定。"
    kw = {"facts": {"facts": ["[f-1] 2027-04-09 Speaker K 谈定首年采购额"]},
          "note": {"facts": ["[f-1] 别的材料"],
                   "note": "笔记原文里写着 2027 年 4 月 9 日，Speaker K 说的。"},
          "prior": {"facts": ["[f-1] 别的材料"],
                    "prior": "上一轮已经写过：2027-04-09 Speaker K 提到过。\n\n"}}[where]
    assert claims.unsupported_specifics(_st(FILLER + line, **kw)) is None


def test_源头只给到年月时正文多写一个日不算编造():
    """多出来的那个日确实没出处，但把它判成编造会逼模型删掉一句有依据的话。"""
    st = _st(FILLER + "2026 年 8 月 5 日定的方案。", facts=["[f-1] 2026-08 的方案讨论"])
    assert claims.unsupported_specifics(st) is None


def test_只判这一轮写的_不判用户自己原来的正文():
    st = _st(FILLER + "这一轮写的都是有出处的话。",
             prior="用户自己写的：2027 年 4 月 9 日，Speaker K 提到过。\n\n",
             facts=["[f-1] 一条材料"])
    assert claims.unsupported_specifics(st) is None


def test_待核对的那一段只能是这一轮写的():
    """**这条是突变验第一轮没抓住之后补的。**

    把 `fresh_text` 改成返回整篇正文，全套测试一条都没红——因为
    `sources()` 里本来就含着「这次跑之前已经写出来的部分」，整篇里多出来的
    那些原子按定义全都有出处，行为上看不出差别。看不出差别不等于没差别：
    字数下限、报出来的句子、以及将来任何一次源头口径的调整，都会立刻在这条
    缝上分岔。所以直接钉住这条缝本身。
    """
    st = _st("这一轮写的。", prior="上一轮写的：2027 年 4 月 9 日。\n\n")
    assert claims.fresh_text(st) == "这一轮写的。"
    assert "2027 年 4 月 9 日" in claims.sources(st)      # 它是**源头**，不是待核对的命题


def test_这一轮写的东西被挪到正文中间时照样分得干净():
    """`fresh` 不一定是 `content` 的**后缀**——定向续写会把这一轮写的插到光标处，
    后面还跟着用户原来的下文。**这一条是突变验第二轮补的**：把"子串"那条分支
    拿掉，`prior` 就等于整篇正文（里面含着 fresh 自己），判据从此对什么都不开火，
    而全套测试一声不吭。
    """
    line = "2027 年 4 月 9 日，Speaker K 提到这事。"
    st = _st(FILLER + line, facts=["[f-1] 一条材料"])
    st.content = "用户原来的上文。\n\n" + FILLER + line + "\n\n用户原来的下文。"
    assert claims.unsupported_specifics(st) is not None


def test_正文被清洗过之后宁可不判也不误伤():
    """`hooks/note._scrub_and_record` 会在流完之后从正文里删掉元话语句子，
    于是 `st.fresh` 不再是 `st.content` 的后缀。这时候「这一轮之前写了什么」
    分不干净——**已知的漏，不是 bug**：分不干净就把整篇都当源头，判据安静地
    不开火。反过来（分不干净就少给源头）会当场变成误伤，而那一档更贵。
    """
    line = "2027 年 4 月 9 日，Speaker K 提到这事。"
    st = _st(FILLER + line, facts=["[f-1] 一条材料"])
    # 清洗删掉了 fresh **中间**的一句：fresh 既不是 content 的后缀，也不是它的子串。
    st.fresh = FILLER + line + "这句谈证据够不够的话被删掉了。"
    st.content = "上一轮写的。" + FILLER + line
    assert claims.unsupported_specifics(st) is None


def test_手上没有任何材料时不判():
    """「查无出处」和「无从判断」分不开——跟批 16 那条「没有工具输出就不判」同一条纪律。
    这一档该由 7.2 的 `material_thin` 去说「你还没查 / 库里没有」。"""
    st = _st(FILLER + "2027 年 4 月 9 日，Speaker K 提到这事。", facts=[], calls=0)
    assert claims.unsupported_specifics(st) is None


def test_这一轮只写了一句话时不判():
    st = _st("2027 年 4 月 9 日定的。", facts=["[f-1] 一条材料"])
    assert claims.unsupported_specifics(st) is None


def test_真实笔记那一档零误伤_整篇同时当产出和源头():
    """批 16 那套方法：一篇笔记里的每个日期 / 名字按定义都追得到这篇笔记本身，
    所以一次都不该开火。这里用一段形状一样的合成正文钉住这个性质
    （真语料上的那一遍在台账批 18 里，24 篇 0 开火）。"""
    body = ("2026 年 8 月 5 日，Speaker A 提到硬件方案。" + FILLER
            + "2026 年 9 月 1 日，Speaker B 确认了交付节点。")
    st = _st(body, note=body, facts=["[f-1] 一条材料"])
    assert claims.unsupported_specifics(st) is None


# ============================================ 7.2 弃答形态：仓里早就有 ===

def test_认得出弃答句():
    assert grounding_rules.abstention_lines("这里需要补上验收测试的实际记录。")
    assert grounding_rules.abstention_lines("这一节还没有对应的记录。")
    assert not grounding_rules.abstention_lines("硬件量产计划在四月启动。")


def test_推荐的弃答写法不会被另外两条判据当场打回():
    """**判据之间不许打架。** 7.2 让模型写的那句话，如果被 `audit_voice_lines`
    当成审计腔整句删掉、或者被 `placeholder_lines` 当成占位符打回，
    那这条诊断就是个照办不了的要求——第 601 轮 `no_placeholder` 那次死锁的形状。
    """
    line = "这里需要补上验收测试的实际记录。"
    assert not grounding_rules.audit_voice_lines(line)
    assert not grounding_rules.placeholder_lines(line)
    assert not grounding_rules.scrub_meta_sentences_v(line)[1]
    assert grounding_rules.abstention_lines(line)


def test_判据自己给的那句写法必须过得了三道():
    """**光钉住「这里需要补上 XX 的实际记录」这句话本身不够**——判据实际递给
    模型的是 `_abstain_hint()` 拼出来的那句。把它改成「材料不足以说明」，
    钉住字面的那条测试照样绿，而生产里两条判据当场打起来。
    所以这里从**判据自己的输出**里把那句话摘出来再验一遍。
    """
    hint = grounding._abstain_hint("验收测试")
    quoted = re.search(r"「([^」]+)」", hint).group(1)
    assert grounding_rules.abstention_lines(quoted)
    assert not grounding_rules.audit_voice_lines(quoted)
    assert not grounding_rules.placeholder_lines(quoted)


def test_审计腔和弃答句是两件事():
    audit = "现有材料不足以说明这一点。"
    assert grounding_rules.audit_voice_lines(audit)
    assert not grounding_rules.abstention_lines(audit)


# ================================================ 7.2 判据本体：开火 ===

ASKED_EMPTY = {"queries": [{"key": "filter_facts\tx", "tool": "filter_facts",
                            "hit": 0, "empty": True}],
               "axes": {"topic:work_pricing": {"total": 0, "taken": 0}}, "facts": {}}
LONG = "这一节写满了一整段内容，全是任何人都能写的通用说法。" * 10


def test_查过了一条材料都没有_正文却照样写满():
    """`Sufficient Context` 的那个实测：材料不够时模型不弃答，直接答。"""
    st = _st(LONG, facts=[], ledger=ASKED_EMPTY)
    v = grounding.material_thin(st)
    assert v is not None
    assert "需要补上" in v.message


def test_问过的方向库里没有_这一轮又空手又零引用():
    st = _st(LONG, facts=["[f-1] 别的方向的材料"], facts_new=[], ledger=ASKED_EMPTY)
    v = grounding.material_thin(st)
    assert v is not None and "work_pricing" in v.message


# ================================================ 7.2 判据本体：不开火 ===

def test_手上有材料就一个字都不说():
    """**[LED] §4 的边界**：「众筹 41 条只用了 12 条」完全正常。
    账本用来发现空白，不用来逼着填满。"""
    st = _st(LONG, facts=["[f-1] 一条材料"], facts_new=["[f-1] 一条材料"],
             ledger={"queries": [{"key": "k", "tool": "filter_facts", "hit": 3,
                                  "empty": False}],
                     "axes": {"topic:众筹": {"total": 41, "taken": 12}}, "facts": {}})
    assert grounding.material_thin(st) is None


# 「你还有 29 条没用」这种会逼它去凑的写法，逐种形状列出来。
# **不能只禁「没用」两个字**：诊断里那句"查回来的材料用不完是正常的"正是在
# 拦住模型自己去凑，禁掉它等于把护栏也一起禁了。禁的是**带数的覆盖率**。
_COVERAGE_NAG = re.compile(
    r"\d+\s*条[^。）]{0,8}(?:没用|未用|没取|没写|剩)"
    r"|(?:用了|还有|剩下|只用了|还剩)\s*\d+\s*条"
    r"|\d+\s*/\s*\d+\s*条")


def test_报出来的话里不许出现用了几条还剩几条():
    """措辞上绝不能写成「你还有 29 条没用」这种会逼它去凑的话（[LED] §4）。"""
    for st in (_st(LONG, facts=[], ledger=ASKED_EMPTY),
               _st(LONG, facts=["[f-1] 材料"], facts_new=[], ledger=ASKED_EMPTY)):
        msg = grounding.material_thin(st).message
        assert not _COVERAGE_NAG.search(msg), msg


def test_这条禁令本身抓得住反面():
    """*突变没被抓住时先怀疑用例不够*——这条闸自己也得有反面用例。"""
    assert _COVERAGE_NAG.search("知识库里还有 29 条没用上。")
    assert _COVERAGE_NAG.search("这个方向只用了 12 条。")


def test_一次都没去查也照样判_但说法不一样():
    """**这条是批 18 第一次真跑当场否掉的一道闸。**

    原来照批 16「没有工具输出就不判」的样子写了「没发过查询就不判」，然后拿
    空库用户真跑：模型一次工具都没调，两轮写了 937 字纯通用内容、
    `stopped=complete`——判据被自己那道闸堵住了，一声没吭。
    两条纪律的区别：「查无出处」在没有 oracle 时确实说不出口，
    而「手上一条材料都没有」**直接看得见**。
    """
    st = _st(LONG, facts=[], ledger={"queries": [], "axes": {}, "facts": {}}, calls=0)
    assert grounding.material_thin(st) is not None


@pytest.mark.parametrize("kb_empty,expect", [(True, "知识库现在还是空的"),
                                             (False, "先去查")])
def test_没查过时按库空不空给两种下一步(monkeypatch, kb_empty, expect):
    """库是空的 → 去查也没用，直接弃答；库里有东西却没去查 → 下一步是**去查**。
    给一个照办不了的下一步，等于把剩下的轮次烧掉。"""
    monkeypatch.setattr(grounding, "_kb_empty", lambda _st: kb_empty)
    st = _st(LONG, facts=[], ledger={"queries": [], "axes": {}, "facts": {}}, calls=0)
    assert expect in grounding.material_thin(st).message


def test_打磨模式关掉():
    """打磨只修不写，它无权去检索也无权新增内容。"""
    st = _st(LONG, facts=[], ledger=ASKED_EMPTY, bag={"polish": True})
    assert grounding.material_thin(st) is None


def test_已经弃答过就不再拦一次():
    st = _st(LONG + "这里需要补上定价的实际记录。", facts=[], ledger=ASKED_EMPTY)
    assert grounding.material_thin(st) is None


def test_这一轮写得很短就不判():
    st = _st("补一句过渡。", facts=[], ledger=ASKED_EMPTY)
    assert grounding.material_thin(st) is None


def test_大纲模式关掉():
    st = _st(LONG, facts=[], ledger=ASKED_EMPTY, bag={"outline_mode": True})
    assert grounding.material_thin(st) is None


def test_这一轮有新材料就不判空方向那一档():
    st = _st(LONG, facts=["[f-1] 材料"], facts_new=["[f-2] 新材料"], ledger=ASKED_EMPTY)
    assert grounding.material_thin(st) is None


def test_这一轮有引用就不判空方向那一档():
    st = _st(LONG + " 有依据的一句 [u-111-1F1]。", facts=["[f-1] 材料"],
             facts_new=[], ledger=ASKED_EMPTY)
    assert grounding.material_thin(st) is None


def test_有分母的方向不算空白():
    """主题树列出来的方向都带真分母，它们不许混进「库里一条都没有」那一栏。"""
    st = _st(LONG, facts=["[f-1] 材料"], facts_new=[],
             ledger={"queries": [{"key": "k", "tool": "filter_facts", "hit": 0,
                                  "empty": True}],
                     "axes": {"topic:众筹": {"total": 41, "taken": 0}}, "facts": {}})
    assert grounding.barren_axes(st) == []
    assert grounding.material_thin(st) is None


def test_开关关掉就整条不跑(monkeypatch):
    monkeypatch.setattr(params, "SUFFICIENT_CONTEXT", False)
    assert grounding.material_thin(_st(LONG, facts=[], ledger=ASKED_EMPTY)) is None


# ============================================================== 接线 ===

@pytest.mark.parametrize("mode", [modes.NOTE, modes.SECTION])
def test_两条长文模式都挂上了这两条判据(mode):
    names = [c.__name__ for c in mode.checks]
    assert "material_thin" in names
    assert "unsupported_specifics" in names


@pytest.mark.parametrize("mode", [modes.NOTE, modes.SECTION])
def test_material_thin_必须排在_citations_present_前面(mode):
    """这一节压根没有材料时，`citations_present` 会说「把用到的那几条编号写上」
    ——一个照办不了的诊断会把剩下的轮次烧光（第 601 轮那次死锁的形状）。
    `Checks` 是「第一条命中的赢」，所以顺序就是判据。"""
    names = [c.__name__ for c in mode.checks]
    assert names.index("material_thin") < names.index("citations_present")


def test_block_模式一条都不许挂():
    """block 那六个模式没有账本、没有跨轮的事实累积，`st.fresh` 就是整块产出
    ——「这一轮写的」和「用户自己写的」分不开，挂上去就是拿一个分不清的判据
    去打用户的字。跟批 16「其余四个模式一条都不挂」同一条纪律。"""
    for mode in modes.BLOCK.values():
        names = [c.__name__ for c in mode.checks]
        assert "material_thin" not in names
        assert "unsupported_specifics" not in names
