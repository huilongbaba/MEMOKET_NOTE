"""集中配置。所有外部依赖的地址都从环境变量读，方便本地/商用切换。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM：任何 OpenAI 兼容端点。默认走内网 Muse-Glimmer-30B。
    llm_base_url: str = "http://192.168.77.8:8080/v1"
    llm_api_key: str = "no-key"
    llm_model: str = "muse-glimmer-30b"

    # 语音转写
    whisper_base_url: str = "http://192.168.77.8:8081"

    # KITE 记忆
    kite_data_dir: Path = Path("./data")
    kite_extract_model: str = "muse-glimmer-30b"

    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
