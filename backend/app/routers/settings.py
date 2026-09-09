"""LLM 供应商设置：本地模型 vs GPT。全局配置，不分用户——见 store.py 里
provider_config 表的注释。切换之后 llm.py（写作三件套/续写）和
kite_memory.py（抽取/问答/实体去重）都会跟着用新的供应商，不用重启。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..database import store
from ..schemas import ProviderConfigIn, ProviderConfigOut

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _to_out(cfg: dict) -> ProviderConfigOut:
    key = cfg["gpt_api_key"]
    return ProviderConfigOut(
        provider=cfg["provider"],
        gpt_model=cfg["gpt_model"],
        gpt_base_url=cfg["gpt_base_url"],
        gpt_api_key_set=bool(key),
        gpt_api_key_preview=f"...{key[-4:]}" if key else "",
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
        gpt_model=body.gpt_model, gpt_base_url=body.gpt_base_url)
    return _to_out(cfg)
