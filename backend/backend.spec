# PyInstaller 打包说明。
#
# 目标：**装到一台没装 python 的机器上能用**。这是「做成 Electron」这件事
# 里唯一有真实失败风险的一步——界面再漂亮，装不上就没有意义。
#
# hiddenimports 存在的理由：PyInstaller 靠静态扫 import 找依赖，而按名字
# 动态加载的东西它扫不出来。漏一个的症状是打出来的程序**启动时才炸**，
# 而不是打包时报错。
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("memoket_kite")
    + collect_submodules("app")
    + [
        "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
    ]
)

datas = collect_data_files("memoket_kite")

a = Analysis(
    ["entry.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    # 打包体积：这些是开发期的东西，装机不需要
    excludes=["pytest", "pyflakes", "coverage", "PyInstaller"],
    noarchive=False,
)
# **包里不许带任何 `data/`**（P19 #2 / P17 #14）：P17 拆开打包版看到 `_internal/data/notes.sqlite3`（0 篇）
# + `backups/`——一份空库躺在包里，用户数据其实在 ~/Library/Application Support，P2 时我们就是在包里那份
# 上误跑过。那份不是 spec 打进去的（这里从没列过 data/），是打包好的后端被人不带 KITE_DATA_DIR 起过一次、
# 在 `_internal/` 下建的（`util/config.py` 现在冻结态下直接拒绝相对路径）。这里再加一道闸：不管谁
# 往 datas 里塞了 data/ 下的东西，一律剔掉，打完包 `_internal/` 下就不会有 data/。
a.datas = [d for d in a.datas if not str(d[0]).replace("\\", "/").startswith(("data/", "backend/data/"))]
assert not any(str(d[0]).replace("\\", "/").startswith("data/") for d in a.datas), "data/ 混进了打包清单"

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="memoket-note-backend",
    console=True,          # 日志要能被 Electron 的 stdout 管道读到
    strip=False, upx=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="memoket-note-backend",
)
