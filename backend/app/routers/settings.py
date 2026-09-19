"""LLM 供应商设置：本地模型 vs OpenAI 兼容（GPT 等）。全局配置，不分用户——见 store.py 里
provider_config 表的注释。切换之后 llm.py（写作三件套/续写）和
kite_memory.py（抽取/问答/实体去重）都会跟着用新的供应商，不用重启。

P19 #1：本地模型有了自己的地址 / 模型名 / key；看图可以跟着写作模型走或单独配；每一栏都有
「测一下」（`POST /provider/test`：真发一次 `/models`，拿不到再发最小的一次 completion，结果当场回）。
"""

from __future__ import annotations

import re
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ..database import store
from ..util.config import get_settings
from .schemas import ProviderConfigIn, ProviderConfigOut, ProviderTestIn, ProviderTestOut
from .deps import current_user

router = APIRouter(prefix="/api/settings", tags=["settings"])

_URL_RE = re.compile(r"^https?://[^\s/]+")


def _to_out(cfg: dict) -> ProviderConfigOut:
    key = cfg["gpt_api_key"]
    s = get_settings()
    active = store.get_active_llm_config()
    vision = store.get_active_vision_config()
    conf = store.llm_configured()
    return ProviderConfigOut(
        provider=cfg["provider"],
        gpt_model=cfg["gpt_model"],
        gpt_base_url=cfg["gpt_base_url"],
        gpt_api_key_set=bool(key),
        gpt_api_key_preview=f"...{key[-4:]}" if key else "",
        asr_base_url=cfg["asr_base_url"],
        asr_default_url=s.whisper_base_url,
        auto_sync_notes=bool(cfg.get("auto_sync_notes")),
        vision_base_url=cfg["vision_base_url"],
        vision_model=cfg["vision_model"],
        vision_api_key_set=bool(cfg["vision_api_key"]),
        vision_follows_llm=bool(vision["follows_llm"]),
        vision_active_url=vision["base_url"],
        vision_active_model=vision["model"],
        local_base_url=cfg["local_base_url"],
        local_model=cfg["local_model"],
        local_api_key_set=bool(cfg["local_api_key"]),
        local_default_url=s.llm_base_url,
        local_default_model=s.llm_model,
        configured=conf["configured"],
        configured_source=conf["source"],
        active_url=active["base_url"],
        active_model=active["model"],
    )


@router.get("/provider", response_model=ProviderConfigOut)
def get_provider():
    return _to_out(store.get_provider_config())


def _url(v: str | None, what: str, allow_empty: bool) -> str | None:
    """接口曾把「not a url」「192.168.1.1:8081」（没 scheme）原样存下（第 251 轮实测），之后每次
    调模型 / 转写都是一个莫名其妙的连接错误。这里只认 http(s)://，去掉尾部斜杠。"""
    if v is None:
        return None
    v = v.strip().rstrip("/")
    if not v:
        if allow_empty:
            return ""
        raise HTTPException(400, f"{what}不能为空")
    if not _URL_RE.match(v):
        raise HTTPException(400, f"{what}要以 http:// 或 https:// 开头：{v[:60]}")
    return v


def _key(v: str | None) -> str | None:
    # 只有空白的 key = 没填，保留原值（之前「  」会被当成一个新 key 存下）
    if v is None:
        return None
    v = v.strip()
    return v or None


@router.post("/provider", response_model=ProviderConfigOut)
def set_provider(body: ProviderConfigIn):
    if body.provider not in ("local", "gpt"):
        raise HTTPException(400, "provider must be 'local' or 'gpt'")
    model = body.gpt_model.strip() if body.gpt_model is not None else None
    if model == "":
        raise HTTPException(400, "模型名不能为空")
    cfg = store.set_provider_config(
        body.provider, gpt_api_key=_key(body.gpt_api_key),
        gpt_model=model, gpt_base_url=_url(body.gpt_base_url, "模型地址", allow_empty=False),
        asr_base_url=_url(body.asr_base_url, "语音服务地址", allow_empty=True),
        auto_sync_notes=body.auto_sync_notes,
        # 本地模型 / 看图：地址传空串 = 清掉退回默认（跟语音地址一样，空是合法值）；key 空白 = 不改
        local_base_url=_url(body.local_base_url, "本地模型地址", allow_empty=True),
        local_model=body.local_model.strip() if body.local_model is not None else None,
        local_api_key=_key(body.local_api_key),
        vision_base_url=_url(body.vision_base_url, "看图模型地址", allow_empty=True),
        vision_model=body.vision_model.strip() if body.vision_model is not None else None,
        vision_api_key=_key(body.vision_api_key))
    return _to_out(cfg)


def _saved_key(slot: str) -> str:
    cfg = store.get_provider_config()
    return {"local": cfg["local_api_key"], "gpt": cfg["gpt_api_key"], "vision": cfg["vision_api_key"]}.get(slot, "")


async def probe_endpoint(kind: str, base_url: str, model: str = "", api_key: str = "",
                         *, timeout: float = 8.0, client: httpx.AsyncClient | None = None) -> ProviderTestOut:
    """真连一次。语音：`GET {base}/health`。模型：先 `GET {base}/models`（列出有哪些模型、填的那个在不在），
    列表拿不到（有些网关不实现）就发一次 `max_tokens=1` 的 chat completion。**结果是一句人话**，
    带的是这次实际连的地址，不是别处的默认值。

    **看图那一栏还要多发一张图**（P23 #4）：`kind == "vision"` 时不止问「连得上吗」，而是把
    `util/probe_image` 现画的那张写着三位数的图发过去让它读——纯文字模型也连得上、也回 200，
    「连上了」这句话证明不了它带视觉。"""
    t0 = time.perf_counter()
    base = base_url.strip().rstrip("/")
    if not _URL_RE.match(base):
        return ProviderTestOut(ok=False, message=f"地址要以 http:// 或 https:// 开头：{base[:60] or '（空）'}")

    def ms() -> int:
        return int((time.perf_counter() - t0) * 1000)

    own = client is None
    c = client or httpx.AsyncClient(timeout=timeout)
    try:
        if kind == "asr":
            try:
                r = await c.get(f"{base}/health")
            except httpx.HTTPError as exc:
                return ProviderTestOut(ok=False, message=f"连不上语音服务 {base}：{type(exc).__name__}——确认 whisper.cpp server 开着、地址端口对", elapsed_ms=ms())
            if r.status_code == 200:
                return ProviderTestOut(ok=True, message=f"语音服务在 {base}，{ms()} ms 应答", elapsed_ms=ms())
            return ProviderTestOut(ok=False, message=f"{base}/health 返回 {r.status_code}——这不像 whisper.cpp server", elapsed_ms=ms())

        async def vision_ok(found: bool | None) -> ProviderTestOut:
            """**看图那一栏：真发一张图**（P23 #4）。P19 给三栏都接了「测一下」，看图那一栏走的
            却是跟写作模型一模一样的探针（`/models` 或一次纯文字 completion）——那句「连上了」
            证明不了它带视觉，一台纯文字模型原样通过，用户要等到点「图片转表格」才发现不认图。
            探针图上写着一个三位数（`util/probe_image`），读对了才算过（瞎猜 1/900）。
            走的是 `vision.ask_image` 本身，不是另拼一份请求——闸要守来源（P21）。"""
            from ..editor import vision
            from ..util.probe_image import PROBE_NUMBER, probe_png
            try:
                answer = await vision.ask_image(
                    f"这张图上写着一个三位数，只回那三个数字，别写别的。",
                    probe_png(), max_tokens=24, timeout=timeout,
                    cfg={"base_url": base, "model": model, "api_key": api_key})
            except vision.VisionError as exc:
                return ProviderTestOut(
                    ok=False, models=models[:50], model_found=found, elapsed_ms=ms(),
                    message=f"连上了，但发一张图过去失败了：{str(exc)[:160]}"
                            "——多半是这个模型不收图片，换一个带视觉的（比如 qwen2.5vl）")
            if PROBE_NUMBER in answer:
                return ProviderTestOut(ok=True, models=models[:50], model_found=found, elapsed_ms=ms(),
                                       message=f"「{model}」认出了图里的 {PROBE_NUMBER}，带视觉（{ms()} ms）")
            return ProviderTestOut(
                ok=False, models=models[:50], model_found=found, elapsed_ms=ms(),
                message=f"「{model}」收下了图，却没读出图里的 {PROBE_NUMBER}（它回的是「{answer[:60] or '（空）'}」）"
                        "——这台多半不带视觉，屏幕活动 / 图片转表格会得到胡编的结果")

        headers = {"Authorization": f"Bearer {api_key or 'no-key'}"}
        models: list[str] = []
        list_err = ""
        try:
            r = await c.get(f"{base}/models", headers=headers)
            if r.status_code in (401, 403):
                return ProviderTestOut(ok=False, message=f"{base} 拒绝了请求（{r.status_code}）：API key 不对或没权限", elapsed_ms=ms())
            if r.status_code == 200:
                data = r.json()
                items = data.get("data") if isinstance(data, dict) else data
                models = [str(m.get("id") or m.get("name") or "") for m in (items or []) if isinstance(m, dict)]
                models = [m for m in models if m]
            else:
                list_err = f"/models 返回 {r.status_code}"
        except httpx.HTTPError as exc:
            return ProviderTestOut(ok=False, message=f"连不上 {base}：{type(exc).__name__}——确认服务开着、地址端口对（本机 Ollama 是 http://127.0.0.1:11434/v1）", elapsed_ms=ms())
        except ValueError:
            list_err = "/models 回的不是 JSON"
        if models:
            if not model:
                return ProviderTestOut(ok=True, message=f"连上了，{len(models)} 个模型可用；模型名还没填，先用第一个「{models[0]}」", models=models[:50], model_found=None, elapsed_ms=ms())
            if model in models:
                if kind == "vision":
                    return await vision_ok(True)
                return ProviderTestOut(ok=True, message=f"连上了，「{model}」在 {base} 上可用（{ms()} ms）", models=models[:50], model_found=True, elapsed_ms=ms())
            shown = "、".join(models[:5]) + ("…" if len(models) > 5 else "")
            return ProviderTestOut(ok=False, message=f"连上了，但 {base} 上没有「{model}」——有的是：{shown}", models=models[:50], model_found=False, elapsed_ms=ms())
        # 列表拿不到：发一次最小的 completion
        if not model:
            return ProviderTestOut(ok=False, message=f"连上了 {base}，但拿不到模型列表（{list_err or '空列表'}），模型名又没填——填上模型名再测", elapsed_ms=ms())
        if kind == "vision":
            return await vision_ok(None)
        try:
            r = await c.post(f"{base}/chat/completions", headers=headers,
                             json={"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1})
        except httpx.HTTPError as exc:
            return ProviderTestOut(ok=False, message=f"连不上 {base}：{type(exc).__name__}", elapsed_ms=ms())
        if r.status_code == 200:
            return ProviderTestOut(ok=True, message=f"「{model}」在 {base} 上应答了（{ms()} ms）", model_found=None, elapsed_ms=ms())
        if r.status_code in (401, 403):
            return ProviderTestOut(ok=False, message=f"{base} 拒绝了请求（{r.status_code}）：API key 不对或没权限", elapsed_ms=ms())
        if r.status_code == 404:
            return ProviderTestOut(ok=False, message=f"{base} 上没有「{model}」这个模型或接口（404）", elapsed_ms=ms())
        return ProviderTestOut(ok=False, message=f"{base} 返回 {r.status_code}：{r.text[:120]}", elapsed_ms=ms())
    finally:
        if own:
            await c.aclose()


@router.post("/provider/test", response_model=ProviderTestOut)
async def test_provider(body: ProviderTestIn):
    if body.kind not in ("llm", "vision", "asr"):
        raise HTTPException(400, "kind must be llm / vision / asr")
    key = (body.api_key or "").strip() or _saved_key(body.saved_key_of)
    return await probe_endpoint(body.kind, body.base_url, body.model.strip(), key)


@router.get("/usage")
def usage(user: str = Depends(current_user)) -> dict:
    """模型用量：今天 / 7 天 / 30 天 / 全部的调用次数和 token，按功能分。只记本仓 util/llm 的调用
    （写作三件套、续写、块、校验…）；KITE 抽取走它自己的 provider，那部分在导入任务里按字数估。"""
    return store.usage_summary(user)
