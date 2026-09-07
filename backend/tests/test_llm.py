"""llm.py 对 GPT 推理档模型（比如 gpt-5.x 系列）的参数兼容处理：
_rejects_temperature() 精确识别"这个模型不支持自定义 temperature"这一种
400，不是所有 400 都吞掉重试；_payload() 统一用 max_completion_tokens。

    cd backend && python -m pytest tests/test_llm.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import llm, store  # noqa: E402


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
