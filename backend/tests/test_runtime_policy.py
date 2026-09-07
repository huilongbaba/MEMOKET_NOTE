"""策略控制器的单测。

每条规则都对应一个真实观测到的失败，所以测试也按「那个失败会不会被正确
响应」来写，不是按函数分支覆盖来写。控制器是纯函数，这些测试不需要模型、
不需要网络，跑起来是毫秒级——这正是把它写成确定性代码而不是再叫一次模型
的理由之一。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.runtime_policy import (
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


def test_budget_is_returned_when_tools_were_not_needed():
    """工具每多跑一轮 = 一次本地模型调用（20-90 秒）。事实这一维稳了、
    上一轮也没真用上工具，就没理由继续付这个钱。"""
    fb = RoundFeedback(scores={"factual_grounding": 2}, tool_calls=0, tool_facts=0)
    new, reasons = adjust(RuntimePolicy(tool_iters=2), fb)
    assert new.tool_iters == 1
    assert any("工具预算 -1" in r for r in reasons)


def test_budget_never_falls_to_zero_and_disables_retrieval():
    """真实 A/B 日志里看出来的：连续几轮 agent 正当判断「不需要检索」，
    预算被一路扣到 0——而 0 意味着工具循环根本不跑，它从此再也查不了。
    因为它诚实回答了"这段不用查"就永久剥夺检索能力，是错的。"""
    p = RuntimePolicy(tool_iters=2)
    fb = RoundFeedback(scores={"factual_grounding": 2}, tool_calls=0, tool_facts=0)
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
