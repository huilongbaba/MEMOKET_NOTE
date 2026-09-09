"""文生图。

走 OpenAI 的图像接口——账号里有 gpt-image-2 / 1.5 / 1（实测 gpt-image-2 出图
干净、中文渲染正确、约 37 秒），**不需要自己去 HuggingFace 部署一套**。

生成的图落到附件目录，正文里只留一个短链接：不内联成 data URI，因为笔记
正文存在 sqlite 里，一张 600KB 的图 base64 之后会跟着每一次自动保存、每一轮
harness 的上下文一起搬来搬去。
"""

from __future__ import annotations

import base64
import hashlib
import httpx

from ..config import get_settings
from ..store import get_active_llm_config


class ImageGenError(RuntimeError):
    pass


def _key() -> str:
    s = get_settings()
    if s.image_api_key:
        return s.image_api_key
    # 没单独配就复用当前写作 provider 的 key——多数情况下就是同一个 OpenAI 账号
    return (get_active_llm_config() or {}).get("api_key", "")


async def generate(prompt: str, *, timeout: float = 300.0) -> tuple[bytes, str]:
    """按提示词生成一张图，返回 (png 字节, 用到的模型名)。"""
    s = get_settings()
    key = _key()
    if not key:
        raise ImageGenError("没有可用的图像模型 key（设置里配 image_api_key，"
                            "或者把写作 provider 切到一个支持出图的账号）")
    body = {"model": s.image_model, "prompt": prompt, "size": s.image_size, "n": 1}
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(f"{s.image_base_url}/images/generations", json=body,
                             headers={"Authorization": f"Bearer {key}",
                                      "Content-Type": "application/json"})
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as exc:
        raise ImageGenError(f"图像模型返回 {exc.response.status_code}："
                            f"{exc.response.text[:200]}") from exc
    except httpx.HTTPError as exc:
        raise ImageGenError(f"连不上图像模型：{exc}") from exc

    item = (data.get("data") or [{}])[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"]), s.image_model
    url = item.get("url")
    if not url:
        raise ImageGenError(f"图像模型没返回图：{str(data)[:200]}")
    async with httpx.AsyncClient(timeout=timeout) as c:
        got = await c.get(url)
        got.raise_for_status()
        return got.content, s.image_model


def save(png: bytes) -> str:
    """存进附件目录，返回可以直接写进 markdown 的 URL。跟 assets 路由同一套
    内容哈希命名，同一张图不会存两份。"""
    d = get_settings().kite_data_dir / "assets"
    d.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(png).hexdigest()[:24] + ".png"
    path = d / name
    if not path.exists():
        path.write_bytes(png)
    return f"/api/assets/{name}"
