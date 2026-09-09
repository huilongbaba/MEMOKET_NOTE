import json

import pytest

from app.harness.checks.rubric import evaluate
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
async def test_malformed_json_falls_back_to_zero_scores_not_a_crash():
    llm = _MockLLM("not valid json at all")
    result = await evaluate(llm, content="some draft", dimensions=DIMENSIONS)
    assert result.status == "continue"
    assert all(s.level == 0 for s in result.scores.values())


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
