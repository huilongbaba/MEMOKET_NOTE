"""集中配置。所有外部依赖的地址都从环境变量读，方便本地/商用切换。"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM：任何 OpenAI 兼容端点。
    #
    # **默认值是本机地址，不是哪台内网机器**（P19 #1 / P17 #1）：之前写死 `192.168.77.8:8080`，
    # 装好的包第一次打开，状态栏和每个 AI 按钮都对第一天用户报一个他没有的内网 IP。开发机那套
    # 走 `.env` / 环境变量（`backend/.env.example` 有样板），**不进默认值**。
    # 默认模型名留空 = 「还没配」：`store.llm_configured()` 据此让状态栏说「还没配模型 → 去设置」
    # 而不是「LLM 不可达 (某个地址)」。用户在设置页「本地模型」填地址 + 模型名，或选「OpenAI 兼容」
    # 填 key，都存 `provider_config` 表，优先于这里。
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_api_key: str = "no-key"
    llm_model: str = ""

    # 视觉（看图）。**独立于写作用的 LLM**：写作那边可能切到 GPT，而看图这件
    # 事可以走本地那台（数据不出内网）。留空 = 跟着当前写作模型走（`store.get_active_vision_config()`）；
    # 设置页「看图」一栏填了就用填的；这里的环境变量是部署覆盖。
    vision_base_url: str = ""
    vision_api_key: str = "no-key"
    vision_model: str = ""

    # 文生图。走 OpenAI 的图像接口（账号里有 gpt-image-2 / 1.5 / 1，实测出图
    # 干净、中文渲染正确，不需要自己部署）。key 留空则复用当前写作 provider 的。
    image_base_url: str = "https://api.openai.com/v1"
    image_api_key: str = ""
    image_model: str = "gpt-image-2"
    image_size: str = "1024x1024"

    # 语音转写（whisper.cpp server）。同上：默认本机端口，内网那台走 `.env`；设置页「语音服务」填了优先。
    whisper_base_url: str = "http://127.0.0.1:8081"

    # KITE 记忆
    # 数据落在哪。**打包之后绝不能是相对路径**——那会解析到 .app 包内部：
    # macOS 的应用包在真实安装场景下只读，而且**更新时整个包会被替换，
    # 用户数据跟着没**。实拍踩过：第一次打包出来的 .app 把 notes.sqlite3
    # 建在了 Contents/Resources/backend/data/ 里。
    #
    # 所以桌面版由 Electron 把系统的用户数据目录传进来
    # （KITE_DATA_DIR，pydantic-settings 自动认这个名字；见 desktop/src/backend.ts）；开发时保持
    # 相对 ./data 不变。
    kite_data_dir: Path = Path("./data")

    @field_validator("kite_data_dir")
    @classmethod
    def _anchor_data_dir(cls, v: Path) -> Path:
        # 相对路径按 backend/ 目录解析，不按进程的 cwd：在仓库根目录起一个脚本跑
        # UserMemory，会在仓库根下凭空建一个空的 data/terrence/codebook.xml，召回全空
        # （第 192 轮踩过）。绝对路径（桌面版传进来的 KITE_DATA_DIR、测试的 mkdtemp）不动。
        p = Path(v)
        if p.is_absolute():
            return p
        # **打包版（PyInstaller 冻结）不许退回相对路径**（P19 #2 / P17 #14）：这里的 `parents[2]` 在包里是
        # `Resources/backend/_internal/`，退回去就是把用户的库建在 .app 包内部——P17 拆开打包版看到
        # `_internal/data/notes.sqlite3`（0 篇）+ `backups/`，就是有人（P2 的我们）不带 KITE_DATA_DIR
        # 直接起过打包好的后端。桌面壳一定传 KITE_DATA_DIR（`desktop/src/backend.ts`）；手工起打包版
        # 的后端也得传，不传就在这里停下，别静默写进包里。
        if getattr(sys, "frozen", False):
            raise ValueError("打包版的后端必须由桌面壳传 KITE_DATA_DIR（绝对路径）——不能把用户数据建在 .app 包内部")
        return (Path(__file__).resolve().parents[2] / p).resolve()
    kite_extract_model: str = ""

    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def env_set(name: str) -> bool:
    """这个字段是不是**环境变量 / .env 给的**（而不是上面的默认值）。`store.llm_configured()` 靠它分清
    「开发机 .env 里配了内网那台」（算配好了）和「谁都没配、还是出厂默认」（状态栏要说「还没配模型」）。
    pydantic-settings 把来自 env 的字段记进 `model_fields_set`，默认值不记。"""
    return name in getattr(get_settings(), "model_fields_set", set())
