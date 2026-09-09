"""memoket-NOTE 后端入口。"""

from __future__ import annotations

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import asr, store
from .config import get_settings
from .routers import (assets, compose, compose_block, folders, import_sources, ingest, kb, memory, note_harness, notes, profile,
                      settings as settings_router, skills, writing_plan)

app = FastAPI(title="memoket-NOTE", version="0.1.0",
              description="AI 编辑器 + 知识库，长期记忆由 KITE 提供")

# 上次进程退出时没跑完的入库/导入任务：后台任务随进程消失，但数据库里的状态
# 还停在 queued/running。不清理的话进度面板永远显示「处理中…」，而且"同时只跑
# 一个导入任务"的检查会认为一直有任务在跑，用户再也导不进任何东西。
_orphans = store.sweep_orphan_jobs()
if _orphans:
    print(f"[startup] 清理了 {_orphans} 个被中断的入库任务")


_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(assets.router)
app.include_router(notes.router)
app.include_router(folders.router)
app.include_router(writing_plan.router)
app.include_router(note_harness.router)
app.include_router(skills.router)
app.include_router(ingest.router)
app.include_router(import_sources.router)
app.include_router(memory.router)
app.include_router(kb.router)
app.include_router(compose.router)
app.include_router(compose_block.router)
app.include_router(profile.router)
app.include_router(settings_router.router)


@app.get("/api/health")
async def health():
    """把两个外部依赖的状态一起报出来，方便定位「不是我的锅」。

    llm 这块报的是**当前生效**的供应商（走 get_active_llm_config()，会
    随设置页里的选择变）——不是 .env 里那个写死的默认值，用户切到 GPT
    之后这里也要跟着显示 GPT，不然这个健康检查在切换之后就是在撒谎。
    """
    active = store.get_active_llm_config()
    s = get_settings()
    llm_ok = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{active['base_url']}/models",
                                 headers={"Authorization": f"Bearer {active['api_key']}"})
            llm_ok = r.status_code == 200
    except Exception:
        llm_ok = False

    return {
        "status": "ok",
        "llm": {"ok": llm_ok, "base_url": active["base_url"], "model": active["model"]},
        "asr": {"ok": await asr.healthy(), "base_url": s.whisper_base_url},
    }
