"""看图：把一张图交给带视觉能力的模型。

**可以独立于写作用的那个 LLM**：写作可能切到 GPT，而看图走本地那台
（设置页「看图」一栏 / ``VISION_BASE_URL``）——图片不出内网，而且实测本地的 muse-glimmer-30b
确实带视觉（能读出图里的表格结构和数字，``capabilities`` 里也报了
``multimodal``）。没单独配就跟着写作模型走（``store.get_active_vision_config``，P19 #1）。

这里只做一件事：发一次带图的请求，把文字结果拿回来。判断"是不是表格"、
"转成什么格式"是调用方的事。
"""

from __future__ import annotations

import base64

import httpx

from ..database import store


class VisionError(RuntimeError):
    pass


async def ask_image(prompt: str, image: bytes, mime: str = "image/png",
                    *, max_tokens: int = 1200, timeout: float = 300.0,
                    system: str = "") -> str:
    """给模型看一张图并提问，返回它的回答。

    图走 data URI 内联，不落盘也不对外暴露 URL——这条路径上的图可能是用户
    随手截的一张含敏感信息的屏，不该为了让模型能取到它而先публи出去。
    """
    # 设置页「看图」填了就用它，没填跟着写作模型走（P19 #1；之前只读 .env）
    cfg = store.get_active_vision_config()
    b64 = base64.b64encode(image).decode()
    # **要求要放 system，别拼在图旁边那段文字里。** 实测（Daily Journey 的 P0，
    # 本地 muse-glimmer-30b）：拼在一起时模型会把要求原样复述一遍、然后用英文
    # 自言自语，压根不输出答案；挪到 system 之后立刻守规矩。
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ]})
    body = {
        "model": cfg["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    headers = {"Authorization": f"Bearer {cfg['api_key'] or 'no-key'}"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(f"{cfg['base_url']}/chat/completions",
                             json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as exc:
        raise VisionError(f"看图模型返回 {exc.response.status_code}："
                          f"{exc.response.text[:200]}") from exc
    except httpx.HTTPError as exc:
        raise VisionError(f"连不上看图模型（{cfg['base_url']}）：{exc}——去设置里「看图」一栏测一下") from exc
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError) as exc:
        raise VisionError(f"看图模型返回的结构不认识：{str(data)[:200]}") from exc
    # 有些本地模型把内容写在 reasoning_content 里、content 是空的（实测
    # muse-glimmer 在 max_tokens 不够时就这样），两个都要看
    return (msg.get("content") or msg.get("reasoning_content") or "").strip()
