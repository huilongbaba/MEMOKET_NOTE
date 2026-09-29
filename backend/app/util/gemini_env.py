"""桌面版的 Gemini 凭据：实现在 util/config.py（database 层只能从那里拿东西），这里只是原来的名字。"""

from __future__ import annotations

from .config import GEMINI_DEFAULT_MODEL as DEFAULT_MODEL
from .config import GEMINI_OPENAI_BASE, gemini_api_key, gemini_llm_config, gemini_model

__all__ = ["DEFAULT_MODEL", "GEMINI_OPENAI_BASE", "gemini_api_key", "gemini_llm_config", "gemini_model"]
