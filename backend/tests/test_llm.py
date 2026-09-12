"""llm.py 对 GPT 推理档模型（比如 gpt-5.x 系列）的参数兼容处理：
_rejects_temperature() 精确识别"这个模型不支持自定义 temperature"这一种
400，不是所有 400 都吞掉重试；_payload() 统一用 max_completion_tokens。

    cd backend && python -m pytest tests/test_llm.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import store
from app.util import llm# noqa: E402


def test_payload_uses_max_completion_tokens_not_max_tokens(monkeypatch):
    monkeypatch.setattr(store, "get_active_llm_config",
                        lambda: {"base_url": "http://x", "api_key": "k", "model": "m"})
    body = llm._payload([{"role": "user", "content": "hi"}], stream=False,
                        max_tokens=100, temperature=0.3, effort="low")
    assert "max_completion_tokens" in body
    assert "max_tokens" not in body
    assert body["max_completion_tokens"] == 100 + llm.REASONING_RESERVE


def test_rejects_temperature_recognizes_the_specific_openai_error():
    body = json.dumps({"error": {
        "message": "Unsupported value: 'temperature' does not support 0.3 with this model.",
        "type": "invalid_request_error", "param": "temperature", "code": "unsupported_value",
    }}).encode()
    assert llm._rejects_temperature(400, body) is True


def test_rejects_temperature_ignores_unrelated_400s():
    # 同样是 400，但不是 temperature 这个参数——不该被当成"剥掉 temperature
    # 重试"的信号，否则会把真实的请求错误悄悄吞掉、重试一个同样会失败的
    # 请求，白白多打一次调用还是报不出真正的错误原因
    body = json.dumps({"error": {
        "message": "Unsupported parameter: 'max_tokens' is not supported with this model.",
        "type": "invalid_request_error", "param": "max_tokens", "code": "unsupported_parameter",
    }}).encode()
    assert llm._rejects_temperature(400, body) is False


def test_rejects_temperature_ignores_non_400_status():
    body = json.dumps({"error": {"param": "temperature", "code": "unsupported_value"}}).encode()
    assert llm._rejects_temperature(401, body) is False
    assert llm._rejects_temperature(500, body) is False


def test_rejects_temperature_handles_non_json_body_gracefully():
    assert llm._rejects_temperature(400, b"not json at all") is False
    assert llm._rejects_temperature(400, b"") is False


# ------------------------------------------------ 模型流怎么被解析 ---
#
# 这两个解析器决定了上层看到什么：`_consume_sse` 给出的 finish_reason 是
# 「撞到 token 上限、要把那半句写完」这条逻辑的唯一依据，解析漏了它，
# 两条 harness 都会把被切断的正文当成写完了。此前零覆盖。

class _FakeResponse:
    """只提供 aiter_lines()，够这两个解析器用。"""

    def __init__(self, lines):
        self._lines = list(lines)

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _sse(*objs):
    import json as _json

    return [f"data: {_json.dumps(o)}" for o in objs]


def _drain(agen):
    import asyncio

    async def go():
        return [x async for x in agen]
    return asyncio.run(go())


def test_流里的内容片段按顺序取出来():
    from app.util.llm import _consume_sse

    lines = _sse({"choices": [{"delta": {"content": "甲"}}]},
                 {"choices": [{"delta": {"content": "乙"}}]}) + ["data: [DONE]"]
    assert _drain(_consume_sse(_FakeResponse(lines))) == ["甲", "乙"]


def test_finish_reason被记进stats():
    """上层靠它判断「是不是被 token 上限拦腰切了」。漏掉这一步，被切断的
    正文会被当成写完了，那半句就永远补不上。"""
    from app.util.llm import _consume_sse

    stats: dict = {}
    lines = _sse({"choices": [{"delta": {"content": "写到一半"},
                               "finish_reason": None}]},
                 {"choices": [{"delta": {}, "finish_reason": "length"}]})
    _drain(_consume_sse(_FakeResponse(lines), stats))
    assert stats["finish_reason"] == "length"


def test_坏行和心跳行不会打断整条流():
    """真实服务会插入注释行、空行，偶尔还有半截 JSON。为一行坏数据放弃
    整次生成，代价是几十秒的工作量。"""
    from app.util.llm import _consume_sse

    lines = ([": keep-alive", "", "data: {这不是合法 JSON"]
             + _sse({"choices": [{"delta": {"content": "还是拿到了"}}]})
             + ["data: {\"choices\": []}", "data: [DONE]",
                "data: {\"choices\": [{\"delta\": {\"content\": \"DONE 之后的不要\"}}]}"])
    assert _drain(_consume_sse(_FakeResponse(lines))) == ["还是拿到了"]


def test_思考过程和正文分开标出来():
    """reasoning_content 一度被整个丢掉——那本来就是「agent 在想什么」，
    是这一步最值得看的东西。"""
    from app.util.llm import _consume_tagged

    lines = _sse({"choices": [{"delta": {"reasoning_content": "先想一想"}}]},
                 {"choices": [{"delta": {"content": "再写出来"}}]},
                 {"choices": [{"delta": {"reasoning_content": "又想了想",
                                         "content": "接着写"}}]})
    assert _drain(_consume_tagged(_FakeResponse(lines))) == [
        ("thinking", "先想一想"), ("output", "再写出来"),
        ("thinking", "又想了想"), ("output", "接着写")]


def test_complete_json_撞上限就翻倍预算再要一次(monkeypatch):
    """extract_json 修断尾很宽容：`["第一节", "第二节", "第三` 会被修成两节的合法列表——
    分段计划撞上限时用户拿到的是安静地少了几节的计划。所以要 JSON 的调用撞上限
    要翻倍预算重试，而不是把断尾修一修就当结果。"""
    import asyncio

    from app.util import llm

    calls: list[int] = []

    async def fake_complete(messages, *, max_tokens=0, temperature=0.0, effort="low", stats=None):
        calls.append(max_tokens)
        if len(calls) == 1:
            stats["finish_reason"] = "length"
            return '["第一节", "第二节", "第三'
        stats["finish_reason"] = "stop"
        return '["第一节", "第二节", "第三节"]'

    monkeypatch.setattr(llm, "complete", fake_complete)
    out = asyncio.run(llm.complete_json([{"role": "user", "content": "x"}], max_tokens=600))
    assert calls == [600, 1200]
    assert out == ["第一节", "第二节", "第三节"]


def test_complete_json_没撞上限只要一次(monkeypatch):
    import asyncio

    from app.util import llm

    calls: list[int] = []

    async def fake_complete(messages, *, max_tokens=0, temperature=0.0, effort="low", stats=None):
        calls.append(max_tokens)
        stats["finish_reason"] = "stop"
        return '{"a": 1}'

    monkeypatch.setattr(llm, "complete", fake_complete)
    assert asyncio.run(llm.complete_json([{"role": "user", "content": "x"}], max_tokens=300)) == {"a": 1}
    assert calls == [300]
