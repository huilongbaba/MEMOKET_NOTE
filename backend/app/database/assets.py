"""资产（粘贴的图、录音）落在哪。路由层不许互相 import，目录规则放这里给
assets 路由和整库导出共用。"""

from __future__ import annotations

from pathlib import Path

from ..util.config import get_settings


def assets_dir() -> Path:
    d = Path(get_settings().kite_data_dir) / "assets"
    d.mkdir(parents=True, exist_ok=True)
    return d
