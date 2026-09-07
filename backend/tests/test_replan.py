"""骨架重规划的单测。

重点全在**收敛保护**上，不在"能不能改"上：让目标可变本身不难，难的是
改了之后还能收敛。所有保护都实现在纯函数里，因为不能指望模型自觉遵守
约束——它只要多返回几条 add，正文就永远写不完。
"""

from __future__ import annotations

from app.replan import MAX_BEATS, MAX_REPLANS, apply_beat_ops, should_replan


# ------------------------------------------------------------------ 触发条件

def test_replans_when_content_is_on_topic_but_beats_keep_failing():
    """正文扣题（spine 达标）却连续两轮过不了节拍——问题多半在节拍要求错了，
    不在正文没写到。典型是节拍全是「建立警示性处境」这种放在任何文章上都
    成立的修辞功能位，正文没法覆盖它，只能不断堆套话。"""
    ok, why = should_replan(
        scores={"beat_coverage": 1, "spine_fidelity": 2},
        stuck_dims={"beat_coverage": 2}, tool_facts=0, replans_used=0)
    assert ok and "节拍本身要求错了" in why


def test_replans_when_retrieval_brought_material_beats_never_foresaw():
    """检索带回材料但节拍仍不达标——新信息进来了，目标却没跟着更新。
    这是「骨架在信息最少时定死」最直接的表现。"""
    ok, why = should_replan(
        scores={"beat_coverage": 1, "spine_fidelity": 2},
        stuck_dims={}, tool_facts=9, replans_used=0)
    assert ok and "9 条具体材料" in why


def test_does_not_replan_when_beats_are_met():
    ok, _ = should_replan(scores={"beat_coverage": 2, "spine_fidelity": 2},
                          stuck_dims={"beat_coverage": 5}, tool_facts=9, replans_used=0)
    assert not ok


def test_does_not_replan_when_content_is_off_topic():
    """spine 也不达标 = 正文本身跑题了，该修正文不该改目标。
    这时候动骨架就是拿目标去迁就跑偏的正文。"""
    ok, _ = should_replan(scores={"beat_coverage": 0, "spine_fidelity": 0},
                          stuck_dims={"beat_coverage": 3}, tool_facts=0, replans_used=0)
    assert not ok


def test_stops_after_budget_is_used_up():
    """目标一直在飘，beat_coverage 就失去了基准的意义。"""
    ok, _ = should_replan(scores={"beat_coverage": 0, "spine_fidelity": 2},
                          stuck_dims={"beat_coverage": 3}, tool_facts=9,
                          replans_used=MAX_REPLANS)
    assert not ok


# ------------------------------------------------------------------ 收敛保护

def test_rewrite_replaces_in_place_and_is_logged():
    beats = ["建立警示性处境", "预判读者追问"]
    out, log = apply_beat_ops(beats, [
        {"op": "rewrite", "index": 0, "text": "用手板 2300/套说明打样费怎么摊"}])
    assert out[0] == "用手板 2300/套说明打样费怎么摊"
    assert out[1] == "预判读者追问"
    assert "改写第 1 条" in log[0]


def test_drop_removes_the_beat():
    out, log = apply_beat_ops(["a", "b", "c"], [{"op": "drop", "index": 1}])
    assert out == ["a", "c"]
    assert "删掉第 2 条" in log[0]


def test_beat_count_can_never_grow():
    """最关键的一条保护：新增最多补回删掉的条数。否则每次重规划都多几条，
    正文永远写不完——目标可变的代价必须封在这里。"""
    out, log = apply_beat_ops(["a", "b", "c"], [
        {"op": "add", "text": "新1"}, {"op": "add", "text": "新2"}])
    assert out == ["a", "b", "c"]                       # 一条都没加进去
    assert any("不能净增" in x for x in log)

    out2, _ = apply_beat_ops(["a", "b", "c"], [
        {"op": "drop", "index": 0},
        {"op": "add", "text": "新1"}, {"op": "add", "text": "新2"}])
    assert len(out2) == 3                               # 删一条只能补一条
    assert "新1" in out2 and "新2" not in out2


def test_never_drops_the_last_beat():
    """全删光了 beat_coverage 就没有基准了。"""
    out, _ = apply_beat_ops(["只剩这一条"], [{"op": "drop", "index": 0}])
    assert out == ["只剩这一条"]


def test_total_stays_within_cap():
    beats = [f"b{i}" for i in range(MAX_BEATS)]
    out, _ = apply_beat_ops(beats, [{"op": "drop", "index": 0},
                                    {"op": "add", "text": "新1"},
                                    {"op": "add", "text": "新2"}])
    assert len(out) <= MAX_BEATS


def test_malformed_ops_are_ignored_not_crashed():
    """模型返回的东西永远可能是任何形状。"""
    out, log = apply_beat_ops(["a", "b"], [
        "不是对象", {"op": "unknown", "index": 0}, {"op": "rewrite", "index": 99, "text": "x"},
        {"op": "rewrite", "index": 0, "text": ""}, {"op": "drop", "index": -5},
        {"op": "add"},
    ])
    assert out == ["a", "b"]
    assert log == []


def test_rewrite_to_identical_text_is_not_logged_as_a_change():
    """没变化就不该报"改了"——变更记录会进 SSE 给用户看，不能有噪声。"""
    out, log = apply_beat_ops(["a", "b"], [{"op": "rewrite", "index": 0, "text": "a"}])
    assert out == ["a", "b"] and log == []


def test_duplicate_add_is_skipped():
    out, _ = apply_beat_ops(["a", "b"], [{"op": "drop", "index": 1},
                                         {"op": "add", "text": "a"}])
    assert out == ["a"]
