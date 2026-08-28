"""memoket-NOTE 后端入口。"""

from __future__ import annotations

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import asr
from .config import get_settings
from .routers import compose, ingest, memory, notes, profile

app = FastAPI(title="memoket-NOTE", version="0.1.0",
              description="AI 编辑器 + 知识库，长期记忆由 KITE 提供")

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(notes.router)
app.include_router(ingest.router)
app.include_router(memory.router)
app.include_router(compose.router)
app.include_router(profile.router)


@app.get("/api/health")
async def health():
    """把两个外部依赖的状态一起报出来，方便定位「不是我的锅」。"""
    s = get_settings()
    llm_ok = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{s.llm_base_url}/models",
                                 headers={"Authorization": f"Bearer {s.llm_api_key}"})
            llm_ok = r.status_code == 200
    except Exception:
        llm_ok = False

    return {
        "status": "ok",
        "llm": {"ok": llm_ok, "base_url": s.llm_base_url, "model": s.llm_model},
        "asr": {"ok": await asr.healthy(), "base_url": s.whisper_base_url},
    }
