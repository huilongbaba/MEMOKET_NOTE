"""打包后的后端入口。

**为什么要这个文件而不是直接打 uvicorn**：PyInstaller 打出来的是一个可执行
程序，它拿到的是命令行参数（`--host` / `--port`），不是 `uvicorn` 那套模块
路径。这里把参数解析出来，用编程方式起 uvicorn。

顺带解决 PyInstaller 的一个老问题：**动态导入的东西它扫不出来**。
`app.main` 里 `from .routers import (...)` 是静态的没问题，但 KITE 那边有
按名字加载的地方——所以 spec 文件里有 hiddenimports。
"""

from __future__ import annotations

import argparse
import multiprocessing
import sys


def main() -> None:
    # **必须第一件事做。** 冻结的程序里子进程会重新执行入口，不调这个的话
    # macOS 上会无限 fork 出新窗口（PyInstaller 的经典坑）。
    multiprocessing.freeze_support()

    ap = argparse.ArgumentParser(prog="memoket-note-backend")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    import uvicorn

    from app.main import app

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    sys.exit(main())
