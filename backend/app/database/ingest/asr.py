"""Whisper Turbo 客户端（whisper.cpp server）。

服务端把 --inference-path 设成了 /v1/audio/transcriptions，所以路径与
OpenAI 一致。language/duration 等是 whisper.cpp 的扩展参数。
"""

from __future__ import annotations

import httpx

from ...util.config import get_settings


async def transcribe(data: bytes, filename: str = "audio.wav",
                     language: str = "auto") -> str:
    s = get_settings()
    async with httpx.AsyncClient(timeout=1800.0) as client:
        r = await client.post(
            f"{s.whisper_base_url}/v1/audio/transcriptions",
            files={"file": (filename, data)},
            data={"response_format": "json", "language": language,
                  "temperature": "0.0"},
        )
        r.raise_for_status()
        payload = r.json()
    return (payload.get("text") or "").strip()


async def healthy() -> bool:
    # 2s 够了：语音服务要么在本机/局域网秒回，要么根本没开——5s 只是让健康检查多等 3s
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{s.whisper_base_url}/health")
            return r.status_code == 200
    except Exception:
        return False
