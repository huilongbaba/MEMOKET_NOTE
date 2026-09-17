import json

import pytest

from app.harness.checks.rubric import ScoreParseError, evaluate
from app.harness.types import Dimension, DupHint


class _MockLLM:
    def __init__(self, response: str):
        self.response = response
        self.last_messages: list[dict] | None = None

    async def complete(self, messages, **kwargs):
        self.last_messages = messages
        return self.response


DIMENSIONS = [
    Dimension("coherence", "high: stays on topic; low: drifts into unrelated listing"),
    Dimension("non_repetition", "high: no restated claims; low: same point said twice"),
]


@pytest.mark.asyncio
async def test_complete_when_all_dimensions_meet_bar():
    llm = _MockLLM(json.dumps({
        "scores": {
            "coherence": {"level": 2, "note": "on topic throughout"},
            "non_repetition": {"level": 2, "note": "no repeats found"},
        },
        "blocked": False, "blocked_reason": "",
    }))
    result = await evaluate(llm, content="some draft", dimensions=DIMENSIONS)
    assert result.status == "complete"
    assert result.weakest is None


@pytest.mark.asyncio
async def test_continue_reports_weakest_dimension():
    llm = _MockLLM(json.dumps({
        "scores": {
            "coherence": {"level": 2, "note": "fine"},
            "non_repetition": {"level": 0, "note": "same conclusion appears twice"},
        },
        "blocked": False, "blocked_reason": "",
    }))
    result = await evaluate(llm, content="some draft", dimensions=DIMENSIONS)
    assert result.status == "continue"
    assert result.weakest == "non_repetition"


@pytest.mark.asyncio
async def test_blocked_is_trusted_from_model_regardless_of_scores():
    llm = _MockLLM(json.dumps({
        "scores": {
            "coherence": {"level": 2, "note": "fine"},
            "non_repetition": {"level": 2, "note": "fine"},
        },
        "blocked": True, "blocked_reason": "content contradicts the stated goal",
    }))
    result = await evaluate(llm, content="some draft", dimensions=DIMENSIONS)
    assert result.status == "blocked"
    assert result.blocked_reason == "content contradicts the stated goal"


@pytest.mark.asyncio
async def test_解析不出分数要抛出来_不能悄悄当成全0分():
    """计划 1.7。这条用例以前叫 `..._falls_back_to_zero_scores_not_a_crash`，
    断言的正是现在这个 bug：解析失败 → 每个维度 `level=0` → 照常返回一份
    `Evaluation`。那份"全 0 分"在下游跟「模型真判每一项都远不达标」
    **一个字节都分不出来**——`Repair` 会排 `cleanup_only` 白扔一轮，
    `BestOf` 的 `rank()` 给它 `(0, 0.0)`（比"没判过"的 `(-1, -1.0)` 还高），
    `extract_judge` 的汇总会把它算进 `below_bar`。

    「不崩」是对的，「假装判过」不是。现在抛 `ScoreParseError`，
    跟超时/连接断合并成同一条「这一轮没判」。
    """
    llm = _MockLLM("not valid json at all")
    with pytest.raises(ScoreParseError):
        await evaluate(llm, content="some draft", dimensions=DIMENSIONS)


@pytest.mark.asyncio
async def test_真的每一维都判0分不算解析失败():
    """**判据宁可窄一点。** 全 0 分是个合法的判断结果——正文可能真的很差。
    只有「一个维度都没解析出可用的 level」才算没判上分。
    误伤这一档的代价是：真写得极差的那一轮被当成没打分，`rank()` 垫底、
    `Repair` 一轮修复都排不上，回路只能空跑到上限。
    """
    llm = _MockLLM(json.dumps({
        "scores": {
            "coherence": {"level": 0, "note": "整段跑题"},
            "non_repetition": {"level": 0, "note": "同一句说了四遍"},
        },
        "blocked": False, "blocked_reason": "",
    }))
    result = await evaluate(llm, content="some draft", dimensions=DIMENSIONS)
    assert result.status == "continue"
    assert all(s.level == 0 for s in result.scores.values())


@pytest.mark.asyncio
async def test_只判上一个维度也算判过了():
    """模型漏掉一个维度 ≠ 接口没返回。漏的那维照旧按 0 补齐（老行为），
    但整轮算判过——这是"窄"的另一半：门槛是 0 个，不是"全都有"。
    """
    llm = _MockLLM(json.dumps({
        "scores": {"coherence": {"level": 2, "note": "on topic"}},
        "blocked": False, "blocked_reason": "",
    }))
    result = await evaluate(llm, content="some draft", dimensions=DIMENSIONS)
    assert result.status == "continue"
    assert result.scores["coherence"].level == 2
    assert result.scores["non_repetition"].level == 0


@pytest.mark.asyncio
async def test_JSON能解析但一个维度名都对不上也算没判上():
    """比"整段不是 JSON"更阴的一种：返回体结构完美、`scores` 也是个 dict，
    只是键全换了名（模型自己发明维度名、或者上游传错了 dimensions）。
    结果一样是每维 `level=0`，所以也得算没判上。
    """
    llm = _MockLLM(json.dumps({
        "scores": {"清晰度": {"level": 2, "note": "好"},
                   "结构": {"level": 1, "note": "一般"}},
        "blocked": False, "blocked_reason": "",
    }))
    with pytest.raises(ScoreParseError):
        await evaluate(llm, content="some draft", dimensions=DIMENSIONS)


@pytest.mark.asyncio
async def test_level值不合法也算没判上():
    """`{"level": "high"}` / `{"level": 7}`：键对得上、值用不了。
    老代码在这儿也是静默落回 0。
    """
    llm = _MockLLM(json.dumps({
        "scores": {"coherence": {"level": "high", "note": "好"},
                   "non_repetition": {"level": 7, "note": "好"}},
        "blocked": False, "blocked_reason": "",
    }))
    with pytest.raises(ScoreParseError):
        await evaluate(llm, content="some draft", dimensions=DIMENSIONS)


@pytest.mark.asyncio
async def test_模型说blocked时就算没有分数也不算解析失败():
    """**有意留窄的那个例外。** `blocked` 为真说明 JSON 本身解析成功了
    （解析不出来时 `blocked` 只能是 False），模型明确说了「再跑也没用」——
    那是一份真裁决。而且 `_blocked` 会让回路当轮停机，全 0 分不会流进
    下一轮的 `Repair` / `BestOf`。把它一起抛掉是拿真信号换整齐。
    """
    llm = _MockLLM(json.dumps({
        "scores": {}, "blocked": True,
        "blocked_reason": "正文跟目标结构性冲突，再写几轮也修不了",
    }))
    result = await evaluate(llm, content="some draft", dimensions=DIMENSIONS)
    assert result.status == "blocked"
    assert result.blocked_reason.startswith("正文跟目标")


@pytest.mark.asyncio
async def test_json_wrapped_in_code_fence_still_parses():
    payload = json.dumps({
        "scores": {
            "coherence": {"level": 2, "note": "ok"},
            "non_repetition": {"level": 2, "note": "ok"},
        },
        "blocked": False, "blocked_reason": "",
    })
    llm = _MockLLM(f"```json\n{payload}\n```")
    result = await evaluate(llm, content="some draft", dimensions=DIMENSIONS)
    assert result.status == "complete"


@pytest.mark.asyncio
async def test_context_and_dup_hints_reach_the_prompt():
    llm = _MockLLM(json.dumps({
        "scores": {
            "coherence": {"level": 2, "note": "ok"},
            "non_repetition": {"level": 2, "note": "ok"},
        },
        "blocked": False, "blocked_reason": "",
    }))
    await evaluate(
        llm, content="draft body", dimensions=DIMENSIONS,
        context={"goal": "explain the migration"},
        dup_hints=[DupHint(a="para A text", b="para B text", similarity=0.9)],
    )
    user_msg = llm.last_messages[1]["content"]
    assert "explain the migration" in user_msg
    assert "para A text"[:20] in user_msg
    assert "draft body" in user_msg


@pytest.mark.asyncio
async def test_rejects_empty_dimensions():
    llm = _MockLLM("{}")
    with pytest.raises(ValueError):
        await evaluate(llm, content="x", dimensions=[])
