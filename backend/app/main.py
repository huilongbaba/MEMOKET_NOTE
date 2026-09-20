"""memoket-NOTE 后端入口。"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
import os
import pathlib

import httpx
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .database import backup, store
from .database.ingest import asr
from .database.kite.kite_memory import UserMemory
from .util import llm, parent_watch
from .util.config import get_settings
from .routers import (assets, client_log, compose, compose_block, export, harness, import_sources, ingest, journey, kb, memory, note_harness, notes, profile,
                      settings as settings_router, skills, tree, writing_plan)

async def _memory_janitor_loop() -> None:
    """每分钟放掉闲置 5 分钟的知识库索引：一个 2 万条事实的索引约 200MB，桌面版常驻时不该
    一直抱着（用户反馈内存占用太高）。放掉之后下次用再花 1s 重建。"""
    while True:
        await asyncio.sleep(60)
        try:
            n = UserMemory.evict_idle()
            if n:
                print(f"[memory] 放掉了 {n} 项闲置索引")
        except Exception as exc:      # noqa: BLE001
            print(f"[memory] 清理索引失败：{exc}")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # FastAPI 的 on_event 已弃用（每次起后端 / 跑测试都刷一条 DeprecationWarning）；lifespan 一进一出，
    # 退出时把后台任务收掉，不留「Task was destroyed but it is pending」
    task = asyncio.create_task(_memory_janitor_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="memoket-NOTE", version="0.1.0", lifespan=_lifespan,
              description="AI 编辑器 + 知识库，长期记忆由 KITE 提供")

# 上次进程退出时没跑完的入库/导入任务：后台任务随进程消失，但数据库里的状态
# 还停在 queued/running。不清理的话进度面板永远显示「处理中…」，而且"同时只跑
# 一个导入任务"的检查会认为一直有任务在跑，用户再也导不进任何东西。
_orphans = store.sweep_orphan_jobs()
_stale_pauses = store.sweep_stale_snapshots()
_old_rows = store.sweep_old_rows()
_recited = store.reindex_citations()
if _recited:
    print(f"[startup] 重建了 {_recited} 篇笔记的引用表")
if any(_old_rows.values()):
    print(f"[startup] 清理了过期流水：{_old_rows}")
if _stale_pauses:
    print(f"[startup] 清理了 {_stale_pauses} 个超过 {store.SNAPSHOT_MAX_AGE_DAYS} 天没处置的轮末暂停")
_orphan_plans = store.sweep_orphan_plans()
_payloads = store.prune_job_payloads(pathlib.Path(get_settings().kite_data_dir) / "jobs")
_orphan_assets = store.sweep_orphan_assets(pathlib.Path(get_settings().kite_data_dir) / "assets")
if _orphan_assets["removed"]:
    print(f"[startup] 清掉 {_orphan_assets['removed']} 张没人引用的图（{_orphan_assets['bytes'] / 1024 / 1024:.1f}MB，超过 7 天）")
_vac = store.vacuum_if_bloated()
if _vac.get("vacuumed"):
    print(f"[startup] 笔记库 VACUUM：{_vac['before_mb']}MB → {_vac['after_mb']}MB（空页 {_vac['free_mb']}MB）")
if _payloads:
    print(f"[startup] 清理了 {_payloads} 个跑完的导入 payload")
if _orphan_plans:
    print(f"[startup] 作废 {_orphan_plans} 个父节点已删的写作计划")
if _orphans:
    print(f"[startup] 清理了 {_orphans} 个被中断的入库任务")

# 一天一份笔记库备份（database/backup.py）。备份失败不影响启动——但要说出来。
try:
    _bk = backup.maybe_backup(store._db_path())
    if _bk:
        print(f"[startup] 笔记库已备份到 {_bk}")
    _kb = backup.maybe_backup_kb(store._db_path().parent)
    if _kb:
        print(f"[startup] 知识库已备份：{len(_kb)} 个用户（一周一份）")
except Exception as _exc:                                  # noqa: BLE001
    print(f"[startup] 笔记库备份失败：{_exc}")


# 桌面版：父进程（Electron）被强杀时跟着退，别留下占着 sqlite 和端口的孤儿。
# 手工起的后端不传这个变量，不受影响。
parent_watch.install_from_env()

_settings = get_settings()
# 这个后端进程是什么时候起来的（P45 #2）。`pid` 会被系统回收复用，
# 「同一个 pid 但换了一条命」在崩溃重启那一下是真会发生的——加一个起点时间，
# 前端 / 壳核身份时就不是只靠一个会撞的数。
_STARTED_AT = __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds")
# 本地接口只信本机页面。CORS 只管「读得到读不到」：跨站页面用 <form> 或 multipart 发的 POST 是
# 「简单请求」，不预检、照样执行——一个恶意网页能往 127.0.0.1:47231 的导入 / 上传接口塞东西
# （第 158 轮巡检）。浏览器给跨站 POST 一定带 Origin（和 Sec-Fetch-Site），拿它们挡：写请求的
# 来源不是本机就 403。同源的 Electron 页面（http://127.0.0.1:<port>）和 Vite 开发页（localhost）不受影响，
# 命令行 / 测试客户端不带 Origin 也不受影响。
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


@app.exception_handler(httpx.HTTPError)
async def _llm_unreachable(_request: Request, exc: httpx.HTTPError):
    """模型侧的 httpx 异常从非流式路由（校验 / 重写 / 扩展 / 骨架 / 来龙去脉…）冒出来时，
    原来是一个光秃秃的 500，前端只能说「后端处理出错（多半是模型没应答）」。
    统一翻成 502 + `llm.describe_error` 那句话（P3）：连不上、拒绝、401、限流各说各的。"""
    return JSONResponse({"detail": llm.describe_error(exc)}, status_code=502)


@app.middleware("http")
async def _reject_cross_site_writes(request: Request, call_next):
    # 顺手给模型用量账本记下「谁、哪个功能」：路径去掉 /api/ 和 id 段（/api/notes/abc/sync → notes/sync）
    llm.ctx_user.set((request.headers.get("x-user-id") or "default").strip()[:64])
    parts = [p for p in request.url.path.split("/") if p and p != "api"]
    llm.ctx_feature.set("/".join(p for p in parts if not (len(p) >= 12 and all(ch in "0123456789abcdef" for ch in p)))[:60])
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin", "")
        if request.headers.get("sec-fetch-site", "") == "cross-site" or \
                (origin and (urlparse(origin).hostname or "") not in _LOCAL_HOSTS):
            return JSONResponse({"detail": "本地接口不接受来自别的网站的写请求"}, status_code=403)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(assets.router)
app.include_router(journey.router)
app.include_router(client_log.router)
app.include_router(notes.router)
app.include_router(tree.router)
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
app.include_router(export.router)




@app.get("/api/health")
async def health():
    """把两个外部依赖的状态一起报出来，方便定位「不是我的锅」。

    llm 这块报的是**当前生效**的供应商（走 get_active_llm_config()，会
    随设置页里的选择变）——不是 .env 里那个写死的默认值，用户切到 GPT
    之后这里也要跟着显示 GPT，不然这个健康检查在切换之后就是在撒谎。
    """
    active = store.get_active_llm_config()

    async def llm_healthy() -> bool:
        if not store.llm_configured()["configured"]:
            return False        # 出厂默认：不去敲一个谁都没配的地址
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{active['base_url']}/models",
                                     headers={"Authorization": f"Bearer {active['api_key']}"})
                return r.status_code == 200
        except Exception:
            return False

    # 两个探测并行：实测 LLM 1.6s + 语音（LAN 上没开的机器，等满超时）5s 串起来
    # 6.5s，桌面版每次启动、每次切供应商都要等这一下才知道红不红。
    llm_ok, asr_ok = await asyncio.gather(llm_healthy(), asr.healthy())
    import resource
    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024))
    # 当前 RSS：macOS 没有 /proc，问一次 ps（健康检查本来就是秒级的接口，不在乎这几毫秒）
    try:
        import subprocess
        rss_now_mb = int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(os.getpid())], timeout=2).strip()) // 1024
    except Exception:      # noqa: BLE001
        rss_now_mb = 0
    return {
        "status": "ok",
        # **「我是谁」**（P45 #2）。同一台机上开第二份 app 时，第二个窗口曾经连到
        # 第一份的后端上——两个窗口写同一个库，而屏幕上一个字都看不出来。P44 走查
        # 是靠 `lsof` 核端口上那个 uvicorn 的 venv 路径才发现的，**那个能力得在产品里**：
        #   · `pid`      —— 桌面壳拿它核「这个端口上的后端是不是我刚起的那个子进程」
        #                   （`desktop/src/backend.ts` 的 `waitHealthy`）。`freePort`
        #                   是「先 listen 再 close」，探测到 uvicorn 真 bind 之间那一小段
        #                   足够别人抢走——**这条堵不住，但堵不住就得认得出来**。
        #   · `data_dir` —— 前端核一次「这一屏上的字是不是这个库里的」（P44 教训 #2）。
        # 都是本机路径 / 进程号，不含用户内容：这个接口本来就只在 127.0.0.1 上。
        "backend": {
            "pid": os.getpid(),
            "data_dir": str(get_settings().kite_data_dir),
            "started_at": _STARTED_AT,
        },
        # `configured`（P19 #1）：没配过模型（出厂默认）时前端说「还没配模型 → 去设置」，不报地址
        "llm": {"ok": llm_ok, "base_url": active["base_url"], "model": active["model"], **store.llm_configured()},
        "asr": {"ok": asr_ok, "base_url": store.get_asr_base_url()},
        # 观测用：后端进程峰值 RSS（MB）和现在抱着几个知识库索引
        "memory": {"rss_peak_mb": rss_mb, "rss_mb": rss_now_mb, **UserMemory.cache_info()},
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


class _NoStoreIndex(StaticFiles):
    """托管前端，但 **`index.html` 一律不许缓存**。

    这是个真出过的 bug（第 744 轮）：升级安装包之后打开，界面还是**旧的**。
    Vite 给 JS/CSS 的文件名带内容哈希，本来就能安全长缓存；可 `index.html`
    不带哈希，它被 Chromium 的磁盘缓存留住之后，指向的还是**上一版的**资源名，
    于是整套旧界面一起从缓存里回来——用户看到的是「装了新版，界面没变」。
    （查的时候绕了一圈：装的包里 `index.html` 引的 JS 明明含新文案，
    渲染出来却是旧的；换一个 `--user` 数据目录立刻正常，才定位到缓存。）

    带哈希的资源照旧可缓存，只把入口文件设成 `no-store`。
    """

    async def get_response(self, path: str, scope):  # type: ignore[override]
        resp = await super().get_response(path, scope)
        if path in ("", ".", "index.html") or path.endswith("/index.html"):
            resp.headers["Cache-Control"] = "no-store, must-revalidate"
        return resp


_web = _web_dir()
if _web:
    # html=True：任何找不到的路径回落到 index.html
    app.mount("/", _NoStoreIndex(directory=str(_web), html=True), name="web")
    print(f"[startup] 托管前端：{_web}")
