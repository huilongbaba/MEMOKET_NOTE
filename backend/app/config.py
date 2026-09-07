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

    # 视觉（看图）。**独立于写作用的 LLM**：写作那边可能切到 GPT，而看图这件
    # 事要走本地那台（数据不出内网，而且它确实带视觉——实测能读出图里的表格
    # 结构和数字）。留空表示复用 llm_* 那一套。
    vision_base_url: str = "http://192.168.77.8:8080/v1"
    vision_api_key: str = "no-key"
    vision_model: str = "muse-glimmer-30b"

    # 文生图。走 OpenAI 的图像接口（账号里有 gpt-image-2 / 1.5 / 1，实测出图
    # 干净、中文渲染正确，不需要自己部署）。key 留空则复用当前写作 provider 的。
    image_base_url: str = "https://api.openai.com/v1"
    image_api_key: str = ""
    image_model: str = "gpt-image-2"
    image_size: str = "1024x1024"

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
