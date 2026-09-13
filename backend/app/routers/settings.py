"""LLM 供应商设置：本地模型 vs GPT。全局配置，不分用户——见 store.py 里
provider_config 表的注释。切换之后 llm.py（写作三件套/续写）和
kite_memory.py（抽取/问答/实体去重）都会跟着用新的供应商，不用重启。
"""

from __future__ import annotations

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


@router.post("/provider", response_model=ProviderConfigOut)
def set_provider(body: ProviderConfigIn):
    if body.provider not in ("local", "gpt"):
        raise HTTPException(400, "provider must be 'local' or 'gpt'")
    cfg = store.set_provider_config(
        body.provider, gpt_api_key=body.gpt_api_key,
        gpt_model=body.gpt_model, gpt_base_url=body.gpt_base_url,
        asr_base_url=body.asr_base_url, auto_sync_notes=body.auto_sync_notes)
    return _to_out(cfg)


@router.get("/usage")
def usage(user: str = Depends(current_user)) -> dict:
    """模型用量：今天 / 7 天 / 30 天 / 全部的调用次数和 token，按功能分。只记本仓 util/llm 的调用
    （写作三件套、续写、块、校验…）；KITE 抽取走它自己的 provider，那部分在导入任务里按字数估。"""
    return store.usage_summary(user)
