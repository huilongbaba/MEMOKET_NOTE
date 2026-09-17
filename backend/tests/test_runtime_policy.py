"""策略控制器的单测。

每条规则都对应一个真实观测到的失败，所以测试也按「那个失败会不会被正确
响应」来写，不是按函数分支覆盖来写。控制器是纯函数，这些测试不需要模型、
不需要网络，跑起来是毫秒级——这正是把它写成确定性代码而不是再叫一次模型
的理由之一。
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.harness.policy import (
    REVISIONS_MAX,
    TEMP_MIN,
    TOOL_ITERS_MAX,
    RoundFeedback,
    RuntimePolicy,
    adjust,
    from_history,
)


def test_all_green_keeps_runtime_stable():
    """全达标时不该乱动参数——只有观测到问题才调整。"""
    p = RuntimePolicy()
    fb = RoundFeedback(scores={"factual_grounding": 2, "coherence": 2,
                               "non_repetition": 2}, tool_calls=2, tool_facts=5)
    new, reasons = adjust(p, fb)
    assert new.tool_iters == p.tool_iters
    assert new.max_revisions == p.max_revisions
    assert new.continue_temperature == p.continue_temperature
    assert new.steer == ""
    assert reasons == []


def test_weak_grounding_raises_tool_budget_and_feeds_the_note_back():
    """真实失败：正文写出「4月10号硬件就位」这类具体日期，打分判"查无此事"，
    而下一轮的检索预算和策略一点没变。打分写的那句诊断此前完全被丢掉。"""
    fb = RoundFeedback(
        scores={"factual_grounding": 0},
        notes={"factual_grounding": "使用了知识库中未出现的具体日期和人物"},
        tool_calls=3, tool_facts=4)
    new, reasons = adjust(RuntimePolicy(), fb)

    assert new.tool_iters == 3                      # 2 -> 3
    assert new.require_verification is True
    assert "使用了知识库中未出现的具体日期和人物" in new.steer   # 原话喂回去
    assert "查不到就把那句改写成不含具体人名" in new.steer
    assert any("factual_grounding" in r for r in reasons)


def test_keyword_only_retrieval_with_weak_grounding_demands_precise_path():
    """实测：六次检索全是 search_memory，四次召回了知识库里完全不相关的
    英文内容（中英混合长查询让关键词匹配串味）。原来只判「零召回」，抓不到
    「召回了但召回的是垃圾」——那种情况 tool_facts 不是 0。"""
    fb = RoundFeedback(scores={"factual_grounding": 0}, tool_calls=6, tool_facts=8,
                       tools_used=("search_memory",))
    new, reasons = adjust(RuntimePolicy(), fb)
    assert "filter_facts" in new.steer
    assert any("改走 filter_facts" in r for r in reasons)


def test_precise_path_already_used_is_not_nagged():
    """已经在用精确路径就别再要求换——这条规则只针对"只会用关键词检索"。"""
    fb = RoundFeedback(scores={"factual_grounding": 0}, tool_calls=3, tool_facts=5,
                       tools_used=("filter_facts", "list_topics"))
    new, _ = adjust(RuntimePolicy(), fb)
    assert "改用 filter_facts" not in new.steer


def test_zero_recall_switches_retrieval_path_instead_of_retrying():
    """真实失败：search_memory 长查询串味，召回了完全不相关的内容。
    这时重试同一条路径没意义，应该改走 list_topics → filter_facts。"""
    fb = RoundFeedback(scores={"factual_grounding": 2}, tool_calls=3, tool_facts=0)
    new, reasons = adjust(RuntimePolicy(), fb)
    assert "list_topics" in new.steer and "filter_facts" in new.steer
    assert "不要继续换措辞重试" in new.steer
    assert any("零召回" in r for r in reasons)


def test_broken_coherence_lowers_temperature_and_buys_revision_budget():
    """真实失败：同一小节标题出现两次、两个收束板块。这类问题靠"再写一段"
    好不了，靠的是更确定的输出和更多清理额度。"""
    fb = RoundFeedback(scores={"coherence": 0, "non_repetition": 2})
    new, _ = adjust(RuntimePolicy(), fb)
    assert new.continue_temperature < RuntimePolicy().continue_temperature
    assert new.max_revisions == RuntimePolicy().max_revisions + 2


def test_repetition_zero_adds_revision_budget():
    fb = RoundFeedback(scores={"non_repetition": 0, "coherence": 2})
    new, _ = adjust(RuntimePolicy(), fb)
    assert new.max_revisions == RuntimePolicy().max_revisions + 2


def test_stuck_dimension_escalates_only_after_two_rounds():
    """真实失败：清理↔续写震荡五轮撞 max_rounds。单轮分数看不出震荡，
    只有"连续几轮同一维度不达标"看得出来，所以升级动作看连续计数。"""
    p = RuntimePolicy()
    fb = RoundFeedback(scores={"beat_coverage": 1})

    p1, r1 = adjust(p, fb)
    assert p1.stuck_dims["beat_coverage"] == 1
    assert not any("连续" in r for r in r1)          # 第一轮不升级

    p2, r2 = adjust(p1, fb)
    assert p2.stuck_dims["beat_coverage"] == 2
    assert any("连续 2 轮未达标" in r for r in r2)
    assert "换一个思路" in p2.steer


def test_recovering_a_dimension_clears_its_stuck_counter():
    p, _ = adjust(RuntimePolicy(), RoundFeedback(scores={"coherence": 1}))
    assert p.stuck_dims.get("coherence") == 1
    p2, _ = adjust(p, RoundFeedback(scores={"coherence": 2}))
    assert "coherence" not in p2.stuck_dims


def test_budget_is_returned_when_the_tool_loop_ran_dry():
    """工具每多跑一轮 = 一次模型调用。事实这一维稳了、上一轮工具循环
    **自己停了**（连着两次调用一条新 id 都没带回来），就没理由继续付这个钱。

    计划 2.5。这个信号是 `agent_loop` 里代码算出来的，不是模型自称的。
    """
    fb = RoundFeedback(scores={"factual_grounding": 2}, tool_calls=3,
                       tool_stopped_barren=True)
    new, reasons = adjust(RuntimePolicy(tool_iters=2), fb)
    assert new.tool_iters == 1
    assert any("工具预算 -1" in r for r in reasons)


def test_honestly_not_retrieving_no_longer_costs_budget():
    """**这条是计划 2.5 换掉的那个脏信号本身。**

    `policy.py` 顶上那段注释记着：「上一轮没用工具」既可能是 agent 正当判断
    「这段不用查」、也可能是它懒得查，两者被当成同一个信号，于是真实 A/B
    日志里预算被一路扣到了下界——**因为它诚实回答了"这段不用查"**。
    换成 `tool_stopped_barren` 之后，一轮都没查的不再扣预算。
    """
    fb = RoundFeedback(scores={"factual_grounding": 2}, tool_calls=0, tool_facts=0)
    p = RuntimePolicy(tool_iters=2)
    for _ in range(6):
        p, reasons = adjust(p, fb)
        assert not any("工具预算 -1" in r for r in reasons)
    assert p.tool_iters == 2, "没查 ≠ 不需要检索能力"


def test_budget_never_falls_to_zero_and_disables_retrieval():
    """0 意味着工具循环根本不跑，agent 从此再也查不了。彻底关掉检索是配置
    决定（MEMOKET_AGENT_TOOLS=0），不该是反馈能自己走进去的状态。"""
    p = RuntimePolicy(tool_iters=2)
    fb = RoundFeedback(scores={"factual_grounding": 2}, tool_calls=3,
                       tool_stopped_barren=True)
    for _ in range(6):
        p, _ = adjust(p, fb)
    assert p.tool_iters >= 1


def test_budgets_stay_inside_bounds_under_repeated_pressure():
    """连续很多轮都不达标时，参数不能无限膨胀——单轮时间会爆。"""
    p = RuntimePolicy()
    fb = RoundFeedback(scores={"factual_grounding": 0, "coherence": 0,
                               "non_repetition": 0})
    for _ in range(10):
        p, _ = adjust(p, fb)
    assert p.tool_iters <= TOOL_ITERS_MAX
    assert p.max_revisions <= REVISIONS_MAX
    assert p.continue_temperature >= TEMP_MIN


def test_missing_dimension_is_treated_as_passing():
    """打分失败或某维度缺失时不该触发降级动作——缺信号不是坏信号。"""
    new, reasons = adjust(RuntimePolicy(), RoundFeedback(scores={}))
    assert new.require_verification is False
    assert not any("factual_grounding" in r for r in reasons)


# ------------------------------------------------------------------ 跨 run


@dataclass
class FakeRun:
    weak_dimensions: list


def test_history_seeds_first_round_for_chronic_weakness():
    """RunHistoryStore 一直在记录每次 run 的未达标维度，但 recent() 从来
    没被调用过——同一篇笔记前几次都栽在同一维度上，第一轮就该带着策略开跑。"""
    runs = [FakeRun(["factual_grounding"]), FakeRun(["factual_grounding", "coherence"]),
            FakeRun(["factual_grounding"])]
    p, reasons = from_history(runs)
    assert p.tool_iters == 3 and p.require_verification is True
    assert any("反复不达标" in r for r in reasons)
    # 历史推出的策略不该让本次运行一上来就以为"已经连续卡了两轮"
    assert p.stuck_dims == {}


def test_history_ignores_one_off_failures():
    """偶尔一次不达标是噪声，不是经验。"""
    runs = [FakeRun(["coherence"]), FakeRun([]), FakeRun([])]
    p, reasons = from_history(runs)
    assert p == RuntimePolicy() or (p.tool_iters == 2 and not reasons)


def test_history_with_no_runs_returns_defaults():
    p, reasons = from_history([])
    assert p.tool_iters == RuntimePolicy().tool_iters
    assert reasons == []


def test_material_use_failure_is_steered_hardest():
    """查到了材料却没写进正文——这是最严重的一条。

    其他维度都在查"有没有毛病"，只有这条在查"有没有价值"：一篇零知识库
    内容的通用文章可以六维全 2、判定 complete，而这个产品的全部价值恰恰
    在于"写你自己的东西"。
    """
    fb = RoundFeedback(
        scores={"material_use": 0},
        notes={"material_use": "这一轮从知识库检索到了 6 条材料，但正文里一条都没用上"})
    new, reasons = adjust(RuntimePolicy(), fb)
    assert "一条都没用上" in new.steer
    assert "宁可只写两句实的" in new.steer
    assert any("material_use" in r for r in reasons)


def test_空知识库不再发那条不可能成立的换路建议():
    """第 676 轮拿一个全新用户实跑续写抓到的：`gather_subject` 返回
    「（没有匹配的事实）」，策略器把它读成「这条查询没命中」，于是发出
    「先 list_topics 看有哪些主题，再 filter_facts 精确取」——**而库是空的，
    一个主题都没有**。整整一轮花在一条不可能成立的建议上。

    空库是这次写作的前提，不是这一轮的失败：停止检索，缺材料整篇只说一次。
    """
    p = RuntimePolicy()
    fb = RoundFeedback(scores={"factual_grounding": 1}, tool_calls=3, tool_facts=0,
                       tools_used=("search_memory",), kb_empty=True)
    new, reasons = adjust(p, fb)
    assert not any("零召回" in r for r in reasons), "空库还劝人换检索路径"
    assert not any("filter_facts" in r for r in reasons), "空库还劝人改用 filter_facts"
    assert any("知识库是空的" in r for r in reasons)
    assert "别再调检索工具" in new.steer
    assert "只说一次" in new.steer

    # 而库里有东西、只是这一轮没查到：原来那条建议照发
    fb2 = RoundFeedback(scores={"factual_grounding": 1}, tool_calls=3, tool_facts=0,
                        tools_used=("search_memory",), kb_empty=False)
    _new2, reasons2 = adjust(p, fb2)
    assert any("零召回" in r for r in reasons2)


def test_空库时不会在同一个prompt里既叫查实又叫别查():
    """第 676 轮实跑的第二轮 steer，前后两句自相矛盾：
    「这一轮先把这些点查实——查得到就用查到的原话」 + 「知识库是空的…别再调
    检索工具了」。模型拿到的是一份互相打架的指令。"""
    fb = RoundFeedback(scores={"factual_grounding": 0}, notes={"factual_grounding": "有占位句"},
                       tool_calls=1, tool_facts=0, kb_empty=True)
    new, _ = adjust(RuntimePolicy(), fb)
    assert "查实" not in new.steer, "空库还叫模型去查实"
    assert "知识库是空的，查不到任何东西" in new.steer
    assert "别再调检索工具" in new.steer

    fb2 = RoundFeedback(scores={"factual_grounding": 0}, notes={"factual_grounding": "有占位句"},
                        tool_calls=1, tool_facts=0, kb_empty=False)
    new2, _ = adjust(RuntimePolicy(), fb2)
    assert "先把这些点查实" in new2.steer, "库里有东西时这条还得在"


# ------------------------------------------------------- steer 分流 ---
#
# 第 765 轮（计划 1.5）。`steer` 唯一的去处是 `prompts/note.retrieval_plan_user`
# ——「这一轮该去知识库查哪些事实」。内在质量的诊断进那个 prompt 是纯噪声：
# 查什么都修不了重复。见 `harness-mechanism-rethink.md` §1 错配一。

def test_内在质量卡住不往检索规划里塞话():
    """`non_repetition` 连续两轮不达标，升级提示**不进 steer**。

    之前的行为：「「non_repetition」这一项已经连续 2 轮没达标，换一个思路」
    被原样塞进决定去查什么的 prompt。它在那儿只能占 token、把注意力从
    「这一节缺哪些材料」上引开。
    """
    p = RuntimePolicy()
    fb = RoundFeedback(scores={"non_repetition": 1})
    p1, _ = adjust(p, fb)
    p2, reasons = adjust(p1, fb)

    assert p2.stuck_dims["non_repetition"] == 2
    assert any("连续 2 轮未达标" in r for r in reasons), "SSE 里还得看得见它卡住了"
    assert "non_repetition" not in p2.steer, "重复的诊断进了检索规划 prompt"
    assert "换一个思路" not in p2.steer


def test_材料类卡住照旧要升级():
    """反过来这一半不能被改坏：检索能修的那几维，卡住了还是要说。"""
    for dim in ("factual_grounding", "material_use", "beat_coverage", "section_coverage"):
        fb = RoundFeedback(scores={dim: 1})
        p1, _ = adjust(RuntimePolicy(), fb)
        p2, _ = adjust(p1, fb)
        assert "换一个思路" in p2.steer, f"{dim} 卡住了却没升级"
        assert dim in p2.steer


def test_材料类和内在质量同时卡住时优先升级材料类():
    """一次只升级一个，挑的时候材料类优先——要是先撞上一个卡住的
    `non_repetition` 就收工，同样卡住的 `beat_coverage` 会一句话都得不到。"""
    fb = RoundFeedback(scores={"non_repetition": 1, "beat_coverage": 1})
    p1, _ = adjust(RuntimePolicy(), fb)
    p2, _ = adjust(p1, fb)
    assert "beat_coverage" in p2.steer
    assert "non_repetition" not in p2.steer


def test_内在质量的诊断走的是修订那条线():
    """分流不等于丢掉：它换了一条路。

    `loop._weak_note` → `st.bag["focus_note"]` → `middleware/revise.py` →
    修订 prompt。这条线是唯一能让已经写坏的文字变对的，**这一批一个字都
    没动它**。
    """
    import pathlib

    from app.harness.loop import _weak_note
    from app.harness.modes import NOTE
    from app.harness.state import State
    from app.harness.tools import ToolContext
    from app.harness.types import DimensionScore, Evaluation

    st = State(mode=NOTE, ctx=ToolContext(user="u", note_id="n"))
    st.ev = Evaluation(scores={"non_repetition": DimensionScore(1, "同一件事说了两遍")},
                       status="continue", weakest="non_repetition")
    assert _weak_note(st) == "同一件事说了两遍"

    revise = (pathlib.Path(__file__).resolve().parent.parent / "app" / "harness"
              / "middleware" / "revise.py").read_text(encoding="utf-8")
    assert 'focus_note=st.bag.get("focus_note", "")' in revise


def test_上一轮的分数不许喂给这一轮的打分器():
    """第 765 轮（计划 4.7）。`st.bag["last_scores"]` 是死状态——写了，
    全仓没有一处读。删掉它，并把「别接上」写在原地。

    理由不是省两行：LLM 评委有实测的 anchoring bias，先给一个参考分会让它
    跟着那个数走，而 `_no_progress` / `_regressed` / `Repair` 三处全都依赖
    两轮之间**独立**打出来的分。
    """
    import pathlib

    app = pathlib.Path(__file__).resolve().parent.parent / "app"
    hits = [f"{p.relative_to(app)}:{i}" for p in app.rglob("*.py")
            for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if "last_scores" in ln and not ln.lstrip().startswith("#")]
    assert not hits, f"last_scores 又长回来了：{hits}"

    loop = (app / "harness" / "loop.py").read_text(encoding="utf-8")
    assert "anchoring" in loop.lower() and "不要把上一轮的分数喂给这一轮的打分器" in loop, \
        "钉住它的那段注释没了——下一个人会好心地把它接回去"


@pytest.mark.anyio
async def test_打分器手上拿不到上一轮的任何东西(monkeypatch):
    """上一条是**词法**的：它只会在有人原样写回 `last_scores` 这个名字时变红。
    这一条盯的是性质本身——**上一轮的评判结果，一个字都不该出现在这一轮的
    打分 prompt 里**。换个变量名、或者顺手把 `focus_note`（上一轮打分模型写的
    那句诊断）塞进 `score_context`，词法那条一样绿，这一条会红。

    做法是给上一轮的评语埋一个哨兵串，然后把 `_evaluate` 真正递给打分器的
    四样东西渲染成 prompt，看哨兵在不在里面。
    """
    from app.harness import loop
    from app.harness.checks.rubric import _build_prompt
    from app.harness.modes import NOTE
    from app.harness.state import State
    from app.harness.tools import ToolContext
    from app.harness.types import DimensionScore, Evaluation

    sentinel = "哨兵-上一轮的评判-勿入打分prompt"
    seen: dict = {}

    async def _fake_evaluate(_llm, **kw):
        seen.update(kw)
        return None

    monkeypatch.setattr(loop, "evaluate", _fake_evaluate)
    monkeypatch.setattr(loop.harness_adapter, "AppLLMClient", lambda: object())

    st = State(mode=NOTE, ctx=ToolContext(user="u", note_id="n"))
    st.content = "正文第一段。\n\n正文第二段。"
    st.bag["score_context"] = {"核心张力": "一句话主线"}
    # 上一轮判完之后 loop 留在 bag 里的两样东西，都带上哨兵
    st.ev = Evaluation(scores={"non_repetition": DimensionScore(1, sentinel)},
                       status="continue", weakest="non_repetition")
    st.bag["focus"] = st.ev.weakest
    st.bag["focus_note"] = loop._weak_note(st)
    assert sentinel in st.bag["focus_note"], "哨兵没埋进去，这条测试就是空的"

    await loop._evaluate(st)

    assert set(seen) == {"content", "dimensions", "dup_hints", "context"}, \
        f"打分器多收/少收了东西：{sorted(seen)}"
    prompt = _build_prompt(seen["content"], seen["dimensions"],
                           seen["context"], tuple(seen["dup_hints"]))
    assert sentinel not in prompt, "上一轮的评判漏进了这一轮的打分 prompt"
