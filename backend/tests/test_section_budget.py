"""分段写作的「只开了个头就收尾」判据（计划 7.3 / [LONG] 建议四）。

第 605 轮实拍：用户说「把硬件、APP、市场三条线各写成一篇」，三节各跑一轮就
五维全 2 判 `complete`，交出来 620 / 434 / 429 字，而硬件那一档知识库里有
412 条事实、这一节用上了四条。

这一份测试钉两头：
* **正向**：那个形状（正文还只有一轮的量 + 材料还剩一大半）必须被抓住；
* **反向、而且更要紧**：每一个「不开火」的前提都单独有一条。这条判据的全部
  风险是**逼模型凑字数**（[LONG] §6 明确不建议为写得更长优化），所以「什么
  时候闭嘴」比「什么时候开火」更需要被钉死。
"""

from __future__ import annotations

import pytest

from app.harness import modes
from app.harness.checks.budget import (MIN_FACTS, MIN_SECTION_CHARS, USED_RATIO,
                                       section_budget)
from app.harness.state import State
from app.harness.tools import ToolContext

# 一节真实的分段正文（`众筹后：用户承接与产品交付` 的开头，逐字），截到
# 一轮的量——这正是「只开了个头」的形状。
OPENING = """## 从募集支持转入兑现承诺

众筹结束后，项目的主要任务就从“说服用户支持一个方向”转成“按承诺把产品交到用户手里”。支持者此时不再只是围观项目进展的人，而是等待具体权益、收货时间和使用体验兑现的用户。"""

# 十条材料，正文里一条都没写进去（`fact_usage` 数的是特征词重合）。
# **十条必须各说各的事**：第一版是同一个模板换数字，于是一句话同时命中十条
# （`fact_usage` 数的是 2-gram 重合，模板本身就贡献了一大半）——
# *造语料的时候，「看起来像材料」和「统计性质像材料」是两件事*（批 19 的老坑）。
FACTS = [
    "[2026-03-12] 手板厂之前打的那架外观结构样 2300 块钱一套。",
    "[2026-05-01] 五月份 PVE 的 DV 批只备一两百 KIT，做个五十、一百套。",
    "[2026-03-11] 设立美国子公司的原因是业务涉及 AI 硬件和美国市场上的数据。",
    "[2026-04-10] EVT 样品计划四月十号启动，十台到货排在六月十五号。",
    "[2026-02-20] Kickstarter 页面的预留档位定成 5 美元，三月上旬上线。",
    "[2026-06-03] DVT 时间线压在六月三号，模具是五月十七号的铜模。",
    "[2026-01-18] 渠道报备的行情价是按配件全包口径报的，亏掉十五个点。",
    "[2026-07-02] 第一批货预计六月中下旬交付，消费者最快七月初收到。",
    "[2026-04-16] 四月十六号作为对外对齐点，十人小范围可用先跑起来。",
    "[2026-05-20] 五月二十号用 T0 模具做 DVT，样机状态要能追到模具版本。",
]


# 「用了一点点，远不够」——**这才是 605 那次的形状**（412 条里用了 4 条）。
# 材料一条都没用上的那一档由 `material_used` 说（它排在前面），见下面那条
# 走真 middleware 的测试。
USED_ONE = OPENING + "\n\n手板厂之前打的那架外观结构样 2300 块钱一套，摊到首批五十套就是 46 元。"


def _st(*, content: str = OPENING, facts=None, round_: int = 1, **bag) -> State:
    st = State(mode=modes.for_run(modes.SECTION), ctx=ToolContext(user="u", note_id="n"))
    st.content = content
    st.facts = list(FACTS if facts is None else facts)
    st.round = round_
    st.bag.update(bag)
    return st


def test_只开了个头而材料还剩一大半就报():
    v = section_budget(_st())
    assert v is not None
    assert v.dimension == "section_coverage"
    assert "还只有一轮的量" in v.message and "10 条材料" in v.message


def test_诊断里不许出现逼它凑字数的措辞():
    """[LONG] §6：**不要为「写得更长」优化**。预算是下限判据，不是目标——
    「你还差 200 字」这种话会把一条诊断变成一个凑数指标（批 13 那条
    「覆盖率是诊断不是指标」同源）。所以诊断说的是**内容**：还没写到的那一面、
    还没用上的那条材料。"""
    msg = section_budget(_st()).message
    for banned in ("还差", "字数", "写满", "不少于", "至少写"):
        assert banned not in msg, f"诊断里出现了逼它凑的措辞：{banned}"


def test_写够了就不报():
    assert section_budget(_st(content="正" * MIN_SECTION_CHARS)) is None


def test_门槛落在两条真实分段正文之间():
    """**600 那个数的全部依据就是这一条。** 13 条有正文的真实分段（`script`
    血缘，分段模式自己在 `harness_rounds` 里 0 轮）最短的两条是 411 和 667：
    411 那条（《协作原则与工作心态》）四个小标题全是「信任而非监视」这种任何人
    都能写的通用常识，正是要抓的东西；667 那条读起来是写完了的。

    *这一条是补出来的*：上面那条「写够了就不报」用的是 `"正" * MIN_SECTION_CHARS`
    ——**门槛改成 700、900、2000 它都照样绿**，因为它跟着常量一起动。
    一个跟着被测常量一起变的断言，没有在断言任何东西。
    """
    assert section_budget(_st(content="正" * 411)) is not None
    assert section_budget(_st(content="正" * 667)) is None


def test_材料用掉一大半就不报():
    """**这一条是它窄下来的地方。** 一节写得短但材料用完了，是写完了，
    不是没写够——那时候再拦一轮就是纯粹在逼它凑。"""
    used = OPENING + "\n\n" + "\n".join(FACTS[:int(len(FACTS) * USED_RATIO) + 1])
    st = _st(content=used)
    assert len(used.replace("\n", "")) < MIN_SECTION_CHARS * 3   # 还是短的
    assert section_budget(st) is None


def test_材料太少不报():
    """两三条材料写进去也撑不出一节，那时候「用了几条」是个噪声比例。"""
    assert section_budget(_st(facts=FACTS[:MIN_FACTS - 1])) is None
    assert section_budget(_st(facts=[])) is None


def test_大纲模式和打磨模式都不报():
    """跟 `material_thin` / `material_used` 同一条理由：用户自己列的小节可能
    本来就只值几句话，打磨模式更是**无权新增内容**——拿一个它改善不了的东西
    打它，就是 `for_run` 注释里那条「永远到不了 complete」的坑。"""
    assert section_budget(_st(outline_mode=True)) is None
    assert section_budget(_st(polish=True)) is None


def test_最后一轮不拦():
    """判据短路会让这一轮没有分数（`rank()` 返回 `(-1, -1.0)`），而最后一轮
    之后没有下一轮去改善它——拦住只会把一轮产出从候选里摘掉。"""
    assert section_budget(_st(round_=modes.SECTION.max_rounds)) is None
    assert section_budget(_st(round_=modes.SECTION.max_rounds - 1)) is not None


# ------------------------------------------------- 接线那一半 ---


def test_挂在分段模式上而且排在最后():
    """它说的是「接着写还没写到的那一面」，而前面每一条说的都是「已经写的这些
    有毛病」。一条「接着写」压在「这里有占位符 / 引用是编的」前面，等于让模型
    在一堆烂摊子上再加一段——第 606 轮那次死锁的教训是判据之间的**先后本身
    就是设计**。"""
    assert modes.SECTION.checks[-1] is section_budget
    assert section_budget not in modes.NOTE.checks, (
        "单篇模式有 `beat_coverage` 在管「够不够」，而且它的正文是用户自己的")


def test_落在分段模式真有的那一维上():
    """`pick_dimension` 的老规矩：判据不许打一个这个模式根本没有的维度。"""
    dims = {d.name for d in modes.for_run(modes.SECTION).dims}
    assert "section_coverage" in dims
    assert section_budget(_st()).dimension in dims


@pytest.mark.anyio
async def test_真的会短路那一轮的打分并让回路接着写():
    """**建了判据不等于用了判据。** 上面几条测的都是这个函数返回什么；
    这一条走真的 `Checks` middleware，验它在回路里的形状：短路打分
    （`skip_judge`）、把 `section_coverage` 记成 0、状态是 `continue`
    ——也就是「这一节还没写完，接着写」，而不是停机。

    **素材用的是「用了一条、还剩九条」那一档**，不是「一条都没用上」：
    后者由排在前面的 `material_used` 先说（第一版用的正是那一档，于是这条
    测试其实一直在验 `material_used`，跟 7.3 一个字的关系都没有）。
    """
    from app.harness.middleware.checks import Checks

    st = _st(content=USED_ONE)
    events = [e async for e in Checks().before_judge(st)]
    assert st.skip_judge and st.ev is not None
    assert st.ev.status == "continue"
    assert st.ev.scores["section_coverage"].level == 0
    assert events and events[0].data["value"]["dimension"] == "section_coverage"
