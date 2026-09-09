"""看图：把一张图交给带视觉能力的模型。

**独立于写作用的那个 LLM**：写作可能切到 GPT，而看图走本地那台
（``vision_base_url``）——图片不出内网，而且实测本地的 muse-glimmer-30b
确实带视觉（能读出图里的表格结构和数字，``capabilities`` 里也报了
``multimodal``）。

这里只做一件事：发一次带图的请求，把文字结果拿回来。判断"是不是表格"、
"转成什么格式"是调用方的事。
"""

from __future__ import annotations

import base64

import httpx

from ..util.config import get_settings


class VisionError(RuntimeError):
    pass


async def ask_image(prompt: str, image: bytes, mime: str = "image/png",
                    *, max_tokens: int = 1200, timeout: float = 300.0) -> str:
    """给模型看一张图并提问，返回它的回答。

    图走 data URI 内联，不落盘也不对外暴露 URL——这条路径上的图可能是用户
    随手截的一张含敏感信息的屏，不该为了让模型能取到它而先публи出去。
    """
    s = get_settings()
    b64 = base64.b64encode(image).decode()
    body = {
        "model": s.vision_model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ]}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    headers = {"Authorization": f"Bearer {s.vision_api_key or 'no-key'}"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(f"{s.vision_base_url}/chat/completions",
                             json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as exc:
        raise VisionError(f"看图模型返回 {exc.response.status_code}："
                          f"{exc.response.text[:200]}") from exc
    except httpx.HTTPError as exc:
        raise VisionError(f"连不上看图模型（{s.vision_base_url}）：{exc}") from exc
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError) as exc:
        raise VisionError(f"看图模型返回的结构不认识：{str(data)[:200]}") from exc
    # 有些本地模型把内容写在 reasoning_content 里、content 是空的（实测
    # muse-glimmer 在 max_tokens 不够时就这样），两个都要看
    return (msg.get("content") or msg.get("reasoning_content") or "").strip()
