"""OpenAI 兼容的 LLM 客户端，支持流式。

默认指向内网 Muse-Glimmer-30B，但供应商可以在设置页切到 GPT（见
store.get_active_llm_config()）。几个必须处理的模型特性：

1. **思考内容关不掉**（本地模型）。该模型总会先输出 reasoning_content。
   实测 reasoning_budget=0 / thinking_budget=0 / chat_template_kwargs 都
   压不住（最好的一档仍有 467 字符思考）。所以 token 额度必须为思考预留，
   否则正文会被截断甚至为空 —— 调用方传的是**想要的正文长度**，由
   REASONING_RESERVE 补上思考的开销。
2. **推理强度影响很大**（本地模型）。交互路径一律 reasoning_effort=low，
   实测比 high 快 3 倍（单次调用 ~10s vs ~30s）。
3. **GPT 的推理档模型（比如 gpt-5.x 系列）参数要求不一样**——实测过
   （真实调用 + 读 OpenAI 报错原文，不是猜的）：
   - 不认 ``max_tokens``，只认 ``max_completion_tokens``；本地 llama.cpp
     两个都认（实测 max_completion_tokens 一样能正确截断），所以统一用
     ``max_completion_tokens`` 一个字段，不用按供应商分叉。
   - ``temperature`` 只认默认值 1，传别的值直接 400（错误信息："Only the
     default (1) value is supported"）。本地模型的 temperature 调参
     （比如 EDIT_SYSTEM 用 0.1 追求确定性、续写用 0.7 要有变化）是真实
     调过、有效果差异的，不能为了兼容 GPT 推理档就整体去掉——所以不是
     一开始就不发 temperature，是发送后如果撞到这个特定的 400 错误，
     剥掉 temperature 重试一次。这样本地模型/GPT 非推理档模型的
     temperature 调参完全不受影响，只有真的不支持的模型会走这条兜底。
"""

from __future__ import annotations

import re

import json
from typing import AsyncIterator

import httpx

from ..database import store


def _headers() -> dict[str, str]:
    cfg = store.get_active_llm_config()
    return {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}


# 为思考内容预留的 token 额度。实测低推理强度下思考约 400-700 字符
# （≈150-250 token），留 600 有安全余量。
REASONING_RESERVE = 600


_DATA_URI = re.compile(r"\]\(data:[a-zA-Z0-9.+/-]+;base64,[^)\s]{16,}\)")


def sanitize_messages(messages: list[dict]) -> list[dict]:
    """文本消息里内嵌的 base64（`![x](data:image/png;base64,…)`）换成占位。

    一张截图几十 KB 的 base64 进提示词等于把 token 烧在没有语义的字母上，还会把
    正文挤出上下文。放在这一层而不是各个 prompt 函数里：出口只有一个。**列表型
    content（vision 的 image_url 分块）不动**——那是有意送图的。"""
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, str) and "data:" in c:
            m = {**m, "content": _DATA_URI.sub("](内嵌图片)", c)}
        out.append(m)
    return out


def _payload(messages: list[dict], *, stream: bool, max_tokens: int,
             temperature: float, effort: str,
             tools: list[dict] | None = None) -> dict:
    cfg = store.get_active_llm_config()
    body = {
        "model": cfg["model"],
        "messages": sanitize_messages(messages),
        # max_tokens 是调用方想要的正文长度，这里补上思考的开销。用
        # max_completion_tokens 而不是 max_tokens——见模块文档字符串第 3 条。
        "max_completion_tokens": max_tokens + REASONING_RESERVE,
        "temperature": temperature,
        "stream": stream,
    }
    # 本地 llama.cpp 与 OpenAI 都认这个字段；商用端点不认时会被忽略。
    body["reasoning_effort"] = effort
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    return body


def _rejects_effort_with_tools(status_code: int, body: bytes) -> bool:
    """判断这次 400 是不是"这个模型不能同时带工具和 reasoning_effort"。

    实测 gpt-5.6-luna 的原话：``Function tools with reasoning_effort are not
    supported for gpt-5.6-luna in /v1/chat/completions. To use function tools,
    use /v1/responses or set reasoning_effort to 'none'.``

    不能一刀切去掉 reasoning_effort——本地模型必须带 low，实测比 high 快
    3 倍。所以跟 temperature 那条一样：只有撞上这个特定错误才降级重试。
    """
    if status_code != 400:
        return False
    try:
        err = json.loads(body).get("error") or {}
    except (json.JSONDecodeError, AttributeError):
        return False
    return (err.get("param") == "reasoning_effort"
            and "tool" in str(err.get("message", "")).lower())


def _rejects_temperature(status_code: int, body: bytes) -> bool:
    """判断这次 400 是不是"这个模型不支持自定义 temperature"这个特定错误——
    不是所有 400 都该吞掉重试，只有这一种确定是"参数不支持"而不是"请求
    本身有问题"才值得剥掉参数重试。"""
    if status_code != 400:
        return False
    try:
        err = json.loads(body).get("error") or {}
    except (json.JSONDecodeError, AttributeError):
        return False
    return err.get("param") == "temperature" and err.get("code") == "unsupported_value"


async def complete(messages: list[dict], *, max_tokens: int = 1500,
                   temperature: float = 0.3, effort: str = "low") -> str:
    """一次性返回完整文本（用于需要拿到完整 JSON 的场景）。"""
    cfg = store.get_active_llm_config()
    payload = _payload(messages, stream=False, max_tokens=max_tokens,
                       temperature=temperature, effort=effort)
    async with httpx.AsyncClient(timeout=300.0) as client:
        r = await client.post(f"{cfg['base_url']}/chat/completions",
                              headers=_headers(), json=payload)
        if _rejects_temperature(r.status_code, r.content):
            payload.pop("temperature", None)
            r = await client.post(f"{cfg['base_url']}/chat/completions",
                                  headers=_headers(), json=payload)
        r.raise_for_status()
        data = r.json()
    return (data["choices"][0]["message"].get("content") or "").strip()


async def complete_raw(messages: list[dict], *, max_tokens: int = 1500,
                       temperature: float = 0.3, effort: str = "low",
                       tools: list[dict] | None = None) -> dict:
    """跟 complete() 同一条路径，但返回**整个 assistant message**而不是正文
    字符串——带 tools 调用时必须拿到 ``tool_calls`` 字段，只取 content 会
    把工具调用整个丢掉（模型决定调工具时 content 通常是空的）。

    返回形如 ``{"role": "assistant", "content": ..., "tool_calls": [...]}``，
    可以原样 append 回 messages 继续对话，这是 OpenAI 工具协议要求的：
    tool 结果消息必须紧跟在发起调用的那条 assistant 消息之后。
    """
    cfg = store.get_active_llm_config()
    payload = _payload(messages, stream=False, max_tokens=max_tokens,
                       temperature=temperature, effort=effort, tools=tools)
    async with httpx.AsyncClient(timeout=300.0) as client:
        r = await client.post(f"{cfg['base_url']}/chat/completions",
                              headers=_headers(), json=payload)
        if _rejects_effort_with_tools(r.status_code, r.content):
            # 带工具时这个模型不认 reasoning_effort，改成 none 重试
            payload["reasoning_effort"] = "none"
            r = await client.post(f"{cfg['base_url']}/chat/completions",
                                  headers=_headers(), json=payload)
        if _rejects_temperature(r.status_code, r.content):
            payload.pop("temperature", None)
            r = await client.post(f"{cfg['base_url']}/chat/completions",
                                  headers=_headers(), json=payload)
        if r.status_code >= 500:
            # 本地模型服务端偶发 5xx（复现不出来：同样的 payload 串行、并发、
            # 各种尺寸都正常）。带工具的调用只有这一次、不是流式，重试一次
            # 的代价远小于丢掉整个检索步骤——丢掉的后果是模型手里零事实，
            # 直接掉进"没材料只能编"那个已知最差状态。
            r = await client.post(f"{cfg['base_url']}/chat/completions",
                                  headers=_headers(), json=payload)
        r.raise_for_status()
        data = r.json()
    msg = data["choices"][0]["message"]
    # 规整成可以直接 append 回 messages 的形状：content 缺失时补空字符串
    # （有的端点在纯工具调用时干脆不返回 content 字段），并且只保留协议
    # 需要的三个键——reasoning_content 之类的私有字段回传给某些端点会 400。
    out: dict = {"role": "assistant", "content": msg.get("content") or ""}
    if msg.get("tool_calls"):
        out["tool_calls"] = msg["tool_calls"]
    return out


async def stream(messages: list[dict], *, max_tokens: int = 1200,
                 temperature: float = 0.7, effort: str = "low",
                 stats: dict | None = None) -> AsyncIterator[str]:
    """逐块产出正文。思考内容（reasoning_content）被丢弃，不进正文。

    ``stats`` 是个可写字典，跑完会填上 ``finish_reason``。调用方靠它区分
    「模型自己写完了」和「撞 token 上限被切断」——后者要把话补完，**绝不能
    把已经写出来的内容删掉**：那是拿丢内容掩盖截断。
    """
    cfg = store.get_active_llm_config()
    payload = _payload(messages, stream=True, max_tokens=max_tokens,
                       temperature=temperature, effort=effort)
    async with httpx.AsyncClient(timeout=600.0) as client:
        url = f"{cfg['base_url']}/chat/completions"
        # 先按原样发一次；如果撞上"这个模型不支持自定义 temperature"，把
        # 请求体读完（流式响应不会自动缓冲 body，要 aread() 才能拿到内容
        # 去判断是不是这个特定错误），剥掉 temperature 重试——跟 complete()
        # 同一个兜底逻辑，只是流式响应不能像普通响应那样先拿到完整结果
        # 再决定要不要重试，得在真正开始消费 SSE 流之前就判断好。
        async with client.stream("POST", url, headers=_headers(), json=payload) as probe:
            # **只有 400 才把 body 读完**。之前无条件 ``await probe.aread()``——那会把整个
            # 流式响应先攒完再交给 _consume_sse，于是"流式"是假的：实测 88 个 delta 全在
            # 最后 0.7 秒里到，第一个字要等 3.5 秒。
            if probe.status_code == 400 and _rejects_temperature(400, await probe.aread()):
                payload.pop("temperature", None)
            else:
                probe.raise_for_status()
                async for piece in _consume_sse(probe, stats):
                    yield piece
                return
        async with client.stream("POST", url, headers=_headers(), json=payload) as r:
            r.raise_for_status()
            async for piece in _consume_sse(r, stats):
                yield piece


async def stream_events(messages: list[dict], *, max_tokens: int = 1200,
                        temperature: float = 0.3, effort: str = "low",
                        ) -> AsyncIterator[tuple[str, str]]:
    """跟 stream() 同一条路，但产出 ``(kind, text)``：kind 是 "thinking"
    （模型的 reasoning_content）或 "output"（正文）。

    stream() 一直在丢掉 reasoning_content——那本来就是"agent 在想什么"，
    是这套东西最值得给用户看的部分。整个 run 里除了续写之外的三步
    （检索规划、修订、打分）都是非流式的，界面上几十秒完全不动，用户
    看不到任何进展。用这个接口就能把它们也流出去。

    调用方仍然要自己把 output 拼起来解析 JSON——流式只是为了显示，
    解析必须等完整文本。
    """
    cfg = store.get_active_llm_config()
    payload = _payload(messages, stream=True, max_tokens=max_tokens,
                       temperature=temperature, effort=effort)
    async with httpx.AsyncClient(timeout=300.0) as client:
        url = f"{cfg['base_url']}/chat/completions"
        async with client.stream("POST", url, headers=_headers(), json=payload) as probe:
            if probe.status_code == 400 and _rejects_temperature(400, await probe.aread()):
                payload.pop("temperature", None)
            else:
                probe.raise_for_status()
                async for ev in _consume_tagged(probe):
                    yield ev
                return
        async with client.stream("POST", url, headers=_headers(), json=payload) as r:
            r.raise_for_status()
            async for ev in _consume_tagged(r):
                yield ev


async def _consume_tagged(r: httpx.Response) -> AsyncIterator[tuple[str, str]]:
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
        delta = choices[0].get("delta") or {}
        think = delta.get("reasoning_content")
        if think:
            yield ("thinking", think)
        piece = delta.get("content")
        if piece:
            yield ("output", piece)


async def _consume_sse(r: httpx.Response, stats: dict | None = None) -> AsyncIterator[str]:
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
        if stats is not None and choices[0].get("finish_reason"):
            stats["finish_reason"] = choices[0]["finish_reason"]
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
    pairs = {"{": "}", "[": "]"}
    starts = [(text.find(o), o) for o in pairs]
    starts = sorted((s for s in starts if s[0] >= 0), key=lambda x: x[0])
    for start, opener in starts:
        # 括号栈，不是单一 depth 计数器 —— 修订建议这种"数组套对象"的真实
        # 输出，栈顶元素随时可能从 "]" 切到 "}" 再切回来，用单一开合符号的
        # depth 计数在截断修复时会把内层对象漏掉（实测踩过：数组在断尾修复
        # 时只补了外层 "]"，内层 "{" 没人管，json.loads 直接炸）。
        stack = [pairs[opener]]
        in_str = False
        escape = False
        end_index = None
        for i in range(start + 1, len(text)):
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
            elif ch in pairs:
                stack.append(pairs[ch])
            elif stack and ch == stack[-1]:
                stack.pop()
                if not stack:
                    end_index = i
                    break
        if end_index is not None:
            try:
                return json.loads(text[start:end_index + 1])
            except json.JSONDecodeError:
                continue
        if stack:
            # Ran out of text with brackets still open -- the model's own
            # output got cut off before the final bracket(s), observed for
            # real (not hypothetical) even on short, otherwise-valid-looking
            # responses, not just ones truncated by hitting max_tokens.
            # Close the dangling string (if any), then every still-open
            # bracket innermost-first (the stack is already in that order),
            # and retry once.
            repaired = text[start:]
            if in_str:
                repaired += '"'
            repaired += "".join(reversed(stack))
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                continue
    return None
