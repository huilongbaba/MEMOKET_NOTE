"""判据卡死之后要放行。

第 601 轮真跑读出来的死锁：`no_placeholder` 每轮都拿正文**第一段**（这次
续写根本没碰的旧文字）打回，四轮全打回，`scores` 里从头到尾只有一项——
打分器一次都没跑起来，`complete` 结构上就到不了。修订那一步是试过的：
模型第 2/3/4 轮都提了针对那段的修订，每次都被空改守卫丢掉。判据说改、
模型改、守卫丢，合起来是个谁也出不去的环。

所以测的是这条性质：**同一条判据原样卡满 STUCK_ROUNDS 轮之后，不再短路
打分**，但事件照发。
"""

from __future__ import annotations

import pytest

from app.harness.middleware.checks import STUCK_ROUNDS, Checks
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import Dimension, Mode, Verdict


def _st(checks) -> State:
    mode = Mode(key="t", label="t", skill_scope="test_scope",
                dims=(Dimension("factual_grounding", "..."),
                      Dimension("style_fit", "...")),
                checks=tuple(checks))
    return State(mode=mode, ctx=ToolContext(user="u", note_id="n"))


async def _round(st: State, *, floor: bool = True) -> list:
    """跑一轮 `before_judge`。

    `floor=False` 把 `JUDGE_FLOOR`（P24 #5：连着几轮没真打分就放行）按住。
    这两条机制是**正交**的：`STUCK_ROUNDS` 数的是「同一条判据原样卡了几轮」，
    `JUDGE_FLOOR` 数的是「连着几轮一次分都没打上」。下面几条测的是前者，
    不按住的话第三轮会被后者放行，测出来的就不是它自己那条性质了。
    后者自己的性质在 `test_p24_harness.py` 里单独钉。
    """
    st.ev, st.skip_judge = None, False
    if not floor:
        st.bag["short_circuit_streak"] = 0
    return [e async for e in Checks().before_judge(st)]


def _always(dimension: str, message: str):
    return lambda st: Verdict(dimension, message)


@pytest.mark.anyio
async def test_同一条判据卡满之后不再短路打分():
    st = _st([_always("factual_grounding", "第一段有占位句")])

    for n in range(1, STUCK_ROUNDS + 1):
        evs = await _round(st)
        assert st.skip_judge, f"第 {n} 轮就该拦住——拦几轮是给修订的机会"
        assert len(evs) == 1

    evs = await _round(st)
    assert not st.skip_judge, "卡满了还拦，就是把剩下的轮数烧掉"
    assert st.ev is None, "不短路就不能自己写好 Evaluation，那是打分器的活"
    assert evs[0].data["value"]["stuck_rounds"] == STUCK_ROUNDS + 1, "事件要照发"


@pytest.mark.anyio
async def test_中间改好过一轮计数就断():
    """它是「连着卡了几轮」，不是「累计报过几次」。"""
    fires = iter([True, True, False, True, True])
    st = _st([lambda st: Verdict("factual_grounding", "同一句话")
              if next(fires) else None])

    await _round(st); await _round(st)
    await _round(st)                      # 这一轮没报 → 断
    for _ in range(2):
        assert (await _round(st)) and st.skip_judge, "断过之后要重新数满才放行"


@pytest.mark.anyio
async def test_原话变了就重新数():
    """判据原话里带着出问题的那一行；原话变了说明那一行动过了。"""
    msgs = iter(["占位句：A", "占位句：A", "占位句：B", "占位句：B"])
    st = _st([lambda st: Verdict("factual_grounding", next(msgs))])

    for _ in range(4):
        await _round(st, floor=False)
        assert st.skip_judge, "每次都是新报的，不该被当成卡死"


@pytest.mark.anyio
async def test_卡死的那条放行之后后面的判据还能拦():
    """短路本来就是为了「一次只给一个清楚的指令」——这条动不了，
    不等于后面那条也动不了。"""
    st = _st([_always("factual_grounding", "改不动的老问题"),
              _always("style_fit", "这一轮新写出来的问题")])

    for _ in range(STUCK_ROUNDS):
        await _round(st, floor=False)
    evs = await _round(st, floor=False)

    assert st.skip_judge and st.ev is not None
    assert st.ev.weakest == "style_fit", "该轮到后面那条说话了"
    assert [e.data["value"]["dimension"] for e in evs] == \
        ["factual_grounding", "style_fit"], "两条都要让用户看见"


def test_笔记原来就有的图不算这一轮手写的():
    """第 604 轮真跑实拍的内容损毁。

    `st.charts` 只记**这一次跑**里工具画过的图，于是用户自己画的、或上一次
    跑留下的 mermaid 每一轮都被判成「模型手写的、模仿工具输出」——两张语法
    完全正确的流程图就这样被修订那一步整个删掉，删完下一轮又报「这条流程是
    用箭头串在正文里的，不是一张图」，删图和要图来回打架。

    判据只该管这次跑写出来的东西；对开跑时就在的图，那句指控本身是假的。
    """
    from app.harness.checks.charts import charts_from_tools

    # 例子要挑「还必须走工具」的那一类：最简流程图第 607 轮起手写也放行了，
    # 拿它当例子的话测的就不是「新旧之分」而是别的事了。
    old = "```mermaid\nxychart-beta\n  title 上次跑留下的\n  bar [1, 2, 3]\n```"
    mine = "```mermaid\nxychart-beta\n  y-axis \"曝光\" 0 --> 260000\n```"

    st = _st([])
    st.bag["content_at_start"] = "一段正文。\n\n" + old
    st.content = st.bag["content_at_start"]
    assert charts_from_tools(st) is None, "开跑时就在的图不是这一轮手写的"

    st.content += "\n\n" + mine
    v = charts_from_tools(st)
    assert v is not None and "y-axis" in v.message, "这一轮新写的手写图照样要拦"

    # 没记开跑快照的老路径（别的 harness / 单测）不能因此崩掉
    st2 = _st([]); st2.content = old
    assert charts_from_tools(st2) is not None


@pytest.mark.anyio
async def test_判据打回的那一轮不该触发只修不写():
    """第 606 轮实拍的死锁：手写 mermaid 的判据落在 `coherence` 上
    （`pick_dimension` 的兜底——分段模式没有 has_charts 这个维度），
    而 `coherence` 在 INNER_QUALITY 里 → 下一轮 cleanup_only →
    `produce()` 直接返回 → 模型根本没机会去调画图工具，而那正是这条判据
    要求的修法。两轮原地打转、一次分都没打上，`no_progress` 收场。

    **批 19 把这条死锁的两截都断了**，而且这条测试的后半截跟着改了：

    * 4.4 断的是**兜底落点**：图表判据在长文模式下现在落到
      `checks.pick.MECHANICS`，那个桶根本不在 `INNER_QUALITY` 里
      （`tests/test_coherence_bucket.py` 有闸钉着这一对）。所以
      「判据命中那一轮不算数」这个补丁**不再是唯一防线**。
    * 4.5 断的是**另一截**：`coherence` 没有位置级探测器，为它排一轮
      「只修不写」等于让修订那一步空手上场。所以下面第二段的断言
      **反过来了**——原来写着「打分器真判 coherence 不合格时，只修不写
      仍然对」，现在那句话不成立了，依据见 `middleware/repair.STOP_ONLY`
      上面那三条实测。

    第一段那个 `skip_judge` 分支**留着**，它挡的是另一个性质：判据伪造的
    Evaluation 只有一个维度，`Repair` 的整个设计前提是读完整的分数向量。
    """
    from app.harness.middleware.repair import Repair
    from app.harness.types import DimensionScore, Evaluation

    st = _st([])
    fake = Evaluation(scores={"coherence": DimensionScore(0, "有张手写的图")},
                      status="continue", weakest="coherence")

    st.ev, st.skip_judge = fake, True
    [e async for e in Repair().after_judge(st)]
    assert not st.bag["cleanup_only"], "判据伪造的单维度分数不该决定下一轮写不写"

    st.ev, st.skip_judge = fake, False
    [e async for e in Repair().after_judge(st)]
    assert not st.bag["cleanup_only"], (
        "coherence 没有位置级探测器，为它排一轮只修不写 = 修订空手上场")

    # 而**有**探测器的那一维照旧排得出修复轮——4.5 只摘掉 coherence 这一条路。
    st.ev = Evaluation(
        scores={"coherence": DimensionScore(0, ""),
                "non_repetition": DimensionScore(0, "同一件事说了两遍")},
        status="continue", weakest="non_repetition")
    [e async for e in Repair().after_judge(st)]
    assert st.bag["cleanup_only"]


def test_挂了图表判据的模式必须带得动画图的工具():
    """判据点名要调的工具，模式得真的有。

    第 606 轮真跑实拍：两个长文模式只有 ("memory", "skill")，却双双挂着
    `no_fake_charts` / `charts_from_tools`，而判据原话是「调 render_chart /
    chart_from_text」。模型手上没有那个工具，只能手写 mermaid → 被拦 →
    再手写。文件夹三节里有两节的第 1、2、4 轮全烧在这上面。
    """
    from app.harness import modes
    from app.harness.checks import charts as chart_checks

    # P8 起只有 `no_fake_charts` 是「要图」的判据；`charts_from_tools` 在没有 chart 组的
    # 模式里不再要求「下一轮再调工具」，而是把手写的直接摘掉（`fix`）——`note` 就是这样
    # （P8 问题 7：续写整篇不画图，要图走「/ 智能插图」）。
    for mode in (modes.NOTE, modes.SECTION, modes.EDA, modes.CHART):
        if chart_checks.no_fake_charts in mode.checks:
            assert "chart" in mode.groups, (
                f"{mode.key} 挂了图表判据却没有 chart 工具组——"
                "判据会要求它做一件它做不到的事，每一轮都要求一次")
    assert "chart" not in modes.NOTE.groups and chart_checks.no_fake_charts not in modes.NOTE.checks, \
        "P8：续写整篇不画图（P5 / P6 十跑 5 张图只有 1 张用户会留）"
    assert chart_checks.charts_from_tools in modes.NOTE.checks, "手写 mermaid 的兜底得留着（没有工具就直接摘掉）"


def test_流程图判据点名的工具真的会画流程图():
    """`chart_from_text` 只会饼 / 柱 / 折线。指着一个做不到的工具，
    模型只能手写 mermaid，然后被下一条判据拦掉。"""
    from app.harness.checks import charts as chart_checks
    from app.harness.tools import registry

    st = _st([])
    st.content = ("依赖链：容量确认 → 下单 → EVD标准样机 → 样机发出 → 真实使用 → 用户证言。")
    v = chart_checks.no_fake_charts(st)
    assert v is not None and "render_chart" in v.message
    from app.harness import modes
    import app.harness.tools  # noqa: F401  注册表靠 import 填起来

    assert "render_chart" in registry.names(list(modes.SECTION.groups)), \
        "判据点名的工具，这个模式得真的发得出去"
    assert "flow" in (registry.get("render_chart").description), \
        "chart_from_text 只会饼 / 柱 / 折线，会画流程图的是 render_chart"


def test_手写的最简流程图放行_别的照旧必须工具产出():
    """第 607 轮把四次真跑里模型写出来的 mermaid 全收集起来看了一遍：
    9 块全是 `graph TD` / `flowchart LR` 加几行 `A[x] --> B[y]`，**9 块全合法**。
    判据把九张有用的流程图全拒了，换来一个模型多半完成不了的工具往返
    （写正文那一步没有工具）。

    语料和反例都在 `tests/fixtures/mermaid_corpus.json`，前端
    `scripts/check-mermaid-grammar.mts` 拿真 mermaid 再验一遍「放行的确实
    渲染得出来」——这条语法是手写正则，光我自己说它对不算数。
    """
    import json
    from pathlib import Path

    from app.harness.checks.blockcheck import is_plain_flowchart, unauthorized_charts

    corpus = json.loads((Path(__file__).parent / "fixtures" / "mermaid_corpus.json")
                        .read_text(encoding="utf-8"))
    for block in corpus["accept"]:
        assert is_plain_flowchart(block), f"真跑里写出来的合法流程图被拒了：\n{block}"
    for block in corpus["reject"]:
        assert not is_plain_flowchart(block), f"这块不该放行：\n{block}"

    # xychart 那类才是真会写坏的地方，照旧必须工具原样给
    bad = "```mermaid\nxychart-beta\n  y-axis \"曝光\" 0 --> 260000\n```"
    assert unauthorized_charts(bad, [])
    assert not unauthorized_charts("```mermaid\ngraph TD\nA[甲] --> B[乙]\n```", [])


@pytest.mark.anyio
async def test_修复对某一档分数试过一次没用就不再为它花轮次():
    """实拍（第 647 轮，真跑 4 轮）：`non_repetition` 每轮都判 0，
    第 2 轮排修复、第 3 轮修完还是 0、**第 4 轮又排一次修复**——
    二十轮上限下就是十轮空转。而那一轮判的是「同一个论点换个说法又说了一遍」，
    正文里一对逐字重复都没有，修订那一步手上全是词面手段，改不动它。
    """
    from app.harness.middleware.repair import Repair
    from app.harness.types import DimensionScore, Evaluation

    st = _st([])
    rep = Repair()

    def judged(level: int) -> None:
        st.ev = Evaluation(scores={"non_repetition": DimensionScore(level, "又说了一遍")},
                           status="continue", weakest="non_repetition")
        st.skip_judge = False

    judged(0)
    [e async for e in rep.after_judge(st)]
    assert st.bag["cleanup_only"], "第一次判不合格：该排一轮只修不写"

    judged(0)                                   # 修完那一轮，分数没动
    evs = [e async for e in rep.after_judge(st)]
    assert not st.bag["cleanup_only"], "修过一轮没动分，下一轮该去写，不该再修"
    assert evs and evs[0].data["value"].get("gave_up") == ["non_repetition"], "放弃了要说出来"

    judged(0)                                   # 再判一次：还是不该再排修复
    [e async for e in rep.after_judge(st)]
    assert not st.bag["cleanup_only"], "已经证明修不动的那一档，别隔一轮又来一次"

    judged(1)                                   # 分数动了 → 上次修复是有效的，重新给机会
    [e async for e in rep.after_judge(st)]
    assert st.bag["cleanup_only"], "分数一动就该重新给一次修复机会"

    judged(2)                                   # 达标：账一笔勾销
    [e async for e in rep.after_judge(st)]
    assert not st.bag["cleanup_only"]
    assert "non_repetition" not in st.bag["repair_failed"]


@pytest.mark.anyio
async def test_跑题也算内在质量要排一轮只修不写():
    """第 765 轮（计划 1.4）。`topic_fidelity` 以前是个孤儿：既不在
    `INNER_QUALITY`、也不在 `loop.COVERAGE_DIMS`，分段模式实测 16 次里
    **7 次判它不达标**，而两条执行器选择规则一条都不看它——它唯一能做的是
    把 `status` 钉在 `continue` 上，然后看着回路把轮数跑满。

    归内在质量的理由：**已经跑题的那段文字，不会因为后面补了几段切题的就
    不跑题了。** 追加只会让它更差，只有修订能让它变对。
    """
    from app.harness.middleware.repair import INNER_QUALITY, Repair
    from app.harness.types import DimensionScore, Evaluation

    assert "topic_fidelity" in INNER_QUALITY

    st = _st([])
    st.ev = Evaluation(
        scores={"topic_fidelity": DimensionScore(1, "写到了该由别的分段覆盖的内容"),
                "section_coverage": DimensionScore(2, "")},
        status="continue", weakest="topic_fidelity")
    st.skip_judge = False
    evs = [e async for e in Repair().after_judge(st)]
    assert st.bag["cleanup_only"], "跑题该排一轮只修不写"
    assert evs and evs[0].data["value"]["dimensions"] == ["topic_fidelity"]


def test_三族维度的名单互不重叠():
    """同一个维度名写在三个文件里（`repair.INNER_QUALITY` /
    `loop.COVERAGE_DIMS` / `policy.MATERIAL_DIMS`），而 `policy.py` 在分层
    测试的 PURE 名单里、不能 import 另外两个——所以只能各写一份，再用这条
    测试对账。`topic_fidelity` 当初就是这么漏成孤儿的。
    """
    from app.harness.loop import COVERAGE_DIMS
    from app.harness.middleware.repair import INNER_QUALITY
    from app.harness.policy import MATERIAL_DIMS

    assert not set(INNER_QUALITY) & set(COVERAGE_DIMS), "一个维度不能既是缺陷又是缺口"
    assert not set(INNER_QUALITY) & set(MATERIAL_DIMS), \
        "内在质量的诊断不该有资格进检索规划"
    assert set(COVERAGE_DIMS) <= set(MATERIAL_DIMS), \
        "覆盖度不达标 = 还得接着写，检索正是为它服务的"


def test_长文的每一个维度都得有人管():
    """上一条只证明三个名单**互不重叠**——而 `topic_fidelity` 当初的毛病不是
    重叠，是**哪个名单都没有它**。重叠测试对孤儿完全免疫：把它从
    `INNER_QUALITY` 拿掉，上一条照样绿。

    所以这一条反过来查：长文两个模式声明的维度，逐个看落没落进三个名单
    （内在质量 / 覆盖度 / 检索可改善）。落不进的是孤儿——**孤儿的分数只能
    把 `status` 钉在 continue 上，没有任何一条执行器规则会因为它做事。**

    剩下的两个孤儿是**明知故留**的，各自写了理由；名单写死在这里，就是为了
    下一个孤儿（无论是新加的维度，还是有人把 `topic_fidelity` 挪出去）必须
    先改这行测试、先说清楚理由。
    """
    from app.harness.loop import COVERAGE_DIMS
    from app.harness.middleware.repair import INNER_QUALITY
    from app.harness.modes import _note_dims, _section_dims
    from app.harness.policy import MATERIAL_DIMS

    classified = set(INNER_QUALITY) | set(COVERAGE_DIMS) | set(MATERIAL_DIMS)
    known_orphans = {
        # 实测 1.88–1.96 封顶（`harness-mechanism-rethink.md` §1）：对着一份
        # 没人验过的计划打分太容易满足，它几乎从不是最弱那一维，归哪一族都
        # 不会改变任何一轮的走向。真要动它，先解决「计划本身没被验过」。
        "spine_fidelity",
        # 形状上是内在质量（文风是已写文字的属性，续写不会把它改对），但
        # 它只在有 profile 的跑里才挂上，而且从没实测到它把回路卡住过。
        # **判据宁可窄一点**：没有实测失败逼出来的改动不做。
        "style_fit",
    }

    for name, dims in (("note", _note_dims(True, False)),
                       ("note-polish", _note_dims(True, True)),
                       ("section", _section_dims(True))):
        orphans = {d.name for d in dims} - classified
        assert orphans == known_orphans & {d.name for d in dims}, \
            f"{name} 多了一个没人管的维度：{orphans - known_orphans}"
