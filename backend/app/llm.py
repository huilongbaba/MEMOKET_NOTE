"""OpenAI 兼容的 LLM 客户端，支持流式。

默认指向内网 Muse-Glimmer-30B。两个必须处理的模型特性：

1. **思考内容关不掉**。该模型总会先输出 reasoning_content。实测
   reasoning_budget=0 / thinking_budget=0 / chat_template_kwargs 都压不住
   （最好的一档仍有 467 字符思考）。所以 max_tokens 必须为思考预留额度，
   否则正文会被截断甚至为空 —— 调用方传的是**想要的正文长度**，由
   REASONING_RESERVE 补上思考的开销。
2. **推理强度影响很大**。交互路径一律 reasoning_effort=low，实测比 high
   快 3 倍（单次调用 ~10s vs ~30s）。
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .config import get_settings


def _headers() -> dict[str, str]:
    s = get_settings()
    return {"Authorization": f"Bearer {s.llm_api_key}", "Content-Type": "application/json"}


# 为思考内容预留的 token 额度。实测低推理强度下思考约 400-700 字符
# （≈150-250 token），留 600 有安全余量。
REASONING_RESERVE = 600


def _payload(messages: list[dict], *, stream: bool, max_tokens: int,
             temperature: float, effort: str) -> dict:
    s = get_settings()
    body = {
        "model": s.llm_model,
        "messages": messages,
        # max_tokens 是调用方想要的正文长度，这里补上思考的开销
        "max_tokens": max_tokens + REASONING_RESERVE,
        "temperature": temperature,
        "stream": stream,
    }
    # 本地 llama.cpp 与 OpenAI 都认这个字段；商用端点不认时会被忽略。
    body["reasoning_effort"] = effort
    return body


async def complete(messages: list[dict], *, max_tokens: int = 1500,
                   temperature: float = 0.3, effort: str = "low") -> str:
    """一次性返回完整文本（用于需要拿到完整 JSON 的场景）。"""
    s = get_settings()
    async with httpx.AsyncClient(timeout=300.0) as client:
        r = await client.post(
            f"{s.llm_base_url}/chat/completions",
            headers=_headers(),
            json=_payload(messages, stream=False, max_tokens=max_tokens,
                          temperature=temperature, effort=effort),
        )
        r.raise_for_status()
        data = r.json()
    return (data["choices"][0]["message"].get("content") or "").strip()


async def stream(messages: list[dict], *, max_tokens: int = 1200,
                 temperature: float = 0.7, effort: str = "low") -> AsyncIterator[str]:
    """逐块产出正文。思考内容（reasoning_content）被丢弃，不进正文。"""
    s = get_settings()
    async with httpx.AsyncClient(timeout=600.0) as client:
        async with client.stream(
            "POST",
            f"{s.llm_base_url}/chat/completions",
            headers=_headers(),
            json=_payload(messages, stream=True, max_tokens=max_tokens,
                          temperature=temperature, effort=effort),
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                chunk = line[6:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    obj = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                piece = (choices[0].get("delta") or {}).get("content")
                if piece:
                    yield piece


def extract_json(text: str) -> dict | list | None:
    """从模型输出里抠出第一个完整的 JSON 对象/数组。

    模型经常会在 JSON 前后加解释文字或 ``` 围栏，直接 json.loads 会炸。
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        if text.startswith("json"):
            text = text[4:]
    # 按哪个定界符先出现来决定解析目标。固定先试 "{" 会把 JSON 数组
    # 截成它的第一个元素 —— 修订建议就是数组，踩过这个坑。
    candidates = [(text.find(o), o, c) for o, c in (("{", "}"), ("[", "]"))]
    candidates = sorted((c for c in candidates if c[0] >= 0), key=lambda x: x[0])
    for start, opener, closer in candidates:
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
    return None
