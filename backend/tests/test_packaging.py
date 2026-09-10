"""打包相关的约定。

这些不是「代码对不对」，是**装到别人机器上会不会出事**——而那件事只有真的
打一次包、跑一次 .app 才看得见，所以把已经踩过的坑固定成断言。
"""

from __future__ import annotations

import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_数据目录能被环境变量指定(monkeypatch, tmp_path):
    """**打包之后数据绝不能落在相对路径。**

    实拍踩过：第一次打包出来的 .app 把 notes.sqlite3 建在了
    `Contents/Resources/backend/data/` 里——macOS 的应用包在真实安装场景下
    只读，而且**更新时整个包会被替换，用户的笔记跟着没**。

    所以桌面版靠 KITE_DATA_DIR 把系统的用户数据目录传进来。这条断言盯住
    那个环境变量还认。
    """
    from app.util import config

    monkeypatch.setenv("KITE_DATA_DIR", str(tmp_path / "somewhere"))
    config.get_settings.cache_clear()
    try:
        assert config.get_settings().kite_data_dir == tmp_path / "somewhere"
    finally:
        config.get_settings.cache_clear()


def test_桌面版真的把数据目录传下去了():
    """光有环境变量支持不够——Electron 那边得真的设它。

    只在打包时设（`app.isPackaged`），开发时保持相对 ./data，跟手工起后端
    用的是同一个库。
    """
    src = (ROOT / "desktop" / "src" / "backend.ts").read_text(encoding="utf-8")
    assert "KITE_DATA_DIR" in src, "Electron 没把数据目录传给后端"
    main = (ROOT / "desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "getPath('userData')" in main, "没用系统的用户数据目录"
    assert "app.isPackaged" in main, "开发时不该改数据目录，否则跟手工起的后端不是同一个库"


def test_打包配置把前后端都装进去():
    """两样少一样，装出来的应用就是废的：少前端 = 白屏，少后端 = 起不来。"""
    pkg = json.loads((ROOT / "desktop" / "package.json").read_text(encoding="utf-8"))
    dests = {r["to"] for r in pkg["build"]["extraResources"]}
    assert dests == {"web", "backend"}, f"打包资源不对：{dests}"


def test_打包入口存在且不是靠模块路径起服务():
    """PyInstaller 出来的是可执行程序，拿到的是命令行参数而不是
    `uvicorn app.main:app` 那套模块路径。"""
    entry = (ROOT / "backend" / "entry.py").read_text(encoding="utf-8")
    assert "freeze_support" in entry, \
        "冻结的程序里子进程会重新执行入口，不调 freeze_support 会无限 fork"
    assert "uvicorn.run(" in entry


@pytest.mark.parametrize("name", ["uvicorn", "memoket_kite", "app"])
def test_打包说明收集了动态导入的包(name):
    """PyInstaller 靠静态扫 import 找依赖，按名字动态加载的它扫不出来。
    漏一个的症状是**打出来的程序启动时才炸**，不是打包时报错。"""
    spec = (ROOT / "backend" / "backend.spec").read_text(encoding="utf-8")
    assert f'collect_submodules("{name}")' in spec
