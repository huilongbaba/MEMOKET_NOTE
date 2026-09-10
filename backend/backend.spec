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
