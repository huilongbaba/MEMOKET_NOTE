"""LLM 供应商设置：本地模型 vs GPT。全局配置，不分用户——见 store.py 里
provider_config 表的注释。切换之后 llm.py（写作三件套/续写）和
kite_memory.py（抽取/问答/实体去重）都会跟着用新的供应商，不用重启。
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException

from ..database import store
from ..util.config import get_settings
from .schemas import ProviderConfigIn, ProviderConfigOut
from .deps import current_user

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _to_out(cfg: dict) -> ProviderConfigOut:
    key = cfg["gpt_api_key"]
    return ProviderConfigOut(
        provider=cfg["provider"],
        gpt_model=cfg["gpt_model"],
        gpt_base_url=cfg["gpt_base_url"],
        gpt_api_key_set=bool(key),
        gpt_api_key_preview=f"...{key[-4:]}" if key else "",
        asr_base_url=cfg["asr_base_url"],
        asr_default_url=get_settings().whisper_base_url,
        auto_sync_notes=bool(cfg.get("auto_sync_notes")),
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
    if not re.match(r"^https?://[^\s/]+", v):
        raise HTTPException(400, f"{what}要以 http:// 或 https:// 开头：{v[:60]}")
    return v


@router.post("/provider", response_model=ProviderConfigOut)
def set_provider(body: ProviderConfigIn):
    if body.provider not in ("local", "gpt"):
        raise HTTPException(400, "provider must be 'local' or 'gpt'")
    model = body.gpt_model.strip() if body.gpt_model is not None else None
    if model == "":
        raise HTTPException(400, "模型名不能为空")
    # 只有空白的 key = 没填，保留原值（之前「  」会被当成一个新 key 存下）
    key = body.gpt_api_key.strip() if body.gpt_api_key is not None else None
    if key == "":
        key = None
    cfg = store.set_provider_config(
        body.provider, gpt_api_key=key,
        gpt_model=model, gpt_base_url=_url(body.gpt_base_url, "模型地址", allow_empty=False),
        asr_base_url=_url(body.asr_base_url, "语音服务地址", allow_empty=True),
        auto_sync_notes=body.auto_sync_notes)
    return _to_out(cfg)


@router.get("/usage")
def usage(user: str = Depends(current_user)) -> dict:
    """模型用量：今天 / 7 天 / 30 天 / 全部的调用次数和 token，按功能分。只记本仓 util/llm 的调用
    （写作三件套、续写、块、校验…）；KITE 抽取走它自己的 provider，那部分在导入任务里按字数估。"""
    return store.usage_summary(user)
