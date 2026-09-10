"""memoket-NOTE 后端入口。"""

from __future__ import annotations

import os
import pathlib

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import store
from .database.ingest import asr
from .util import parent_watch
from .util.config import get_settings
from .routers import (assets, compose, compose_block, folders, harness, import_sources, ingest, kb, memory, note_harness, notes, profile,
                      settings as settings_router, skills, writing_plan)

app = FastAPI(title="memoket-NOTE", version="0.1.0",
              description="AI 编辑器 + 知识库，长期记忆由 KITE 提供")

# 上次进程退出时没跑完的入库/导入任务：后台任务随进程消失，但数据库里的状态
# 还停在 queued/running。不清理的话进度面板永远显示「处理中…」，而且"同时只跑
# 一个导入任务"的检查会认为一直有任务在跑，用户再也导不进任何东西。
_orphans = store.sweep_orphan_jobs()
if _orphans:
    print(f"[startup] 清理了 {_orphans} 个被中断的入库任务")


# 桌面版：父进程（Electron）被强杀时跟着退，别留下占着 sqlite 和端口的孤儿。
# 手工起的后端不传这个变量，不受影响。
parent_watch.install_from_env()

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
app.include_router(harness.router)
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


# ---------------------------------------------------------------- 桌面版
#
# **打包好的前端由后端自己托管。** 桌面版（Electron）不走 file://，而是直接
# 连 http://127.0.0.1:<port>/ ——因为前端里所有请求写的都是 `/api/...` 这样的
# 相对路径。用 file:// 加载的话这些路径全部失效，就得在前端引入一个「API 根
# 地址」的概念，然后每个 fetch 都要带上它，桌面和网页两套行为从此分叉。
#
# 同源托管是最省事的做法：一行 mount，前端一个字都不用改，也没有跨域。
#
# 必须挂在所有 router 之后：mount("/") 会兜住前面没匹配上的一切请求。
def _web_dir() -> pathlib.Path | None:
    """打包好的前端在哪。找不到就不挂——开发时前端跑在 vite 上，这里本来
    就该是空的。"""
    env = os.getenv("MEMOKET_NOTE_WEB_DIR")
    if env:
        p = pathlib.Path(env)
        return p if (p / "index.html").exists() else None
    p = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "dist"
    return p if (p / "index.html").exists() else None


@app.api_route("/api/{rest:path}",
               methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
               include_in_schema=False)
async def _api_not_found(rest: str):
    """没匹配上任何 router 的 /api 路径，明确回 404。

    **必须挡在下面那个 mount 前面。** 不挡的话 SPA 的兜底会把它接走：写错
    一个路径不再是 404，而是 200 + 一整篇 index.html，前端 JSON.parse 当场
    炸在一个跟真实原因毫无关系的地方。（StaticFiles 对 POST 回 405，同样
    误导。）
    """
    raise HTTPException(404, f"没有这个端点：/api/{rest}")


_web = _web_dir()
if _web:
    # html=True：任何找不到的路径回落到 index.html
    app.mount("/", StaticFiles(directory=str(_web), html=True), name="web")
    print(f"[startup] 托管前端：{_web}")
