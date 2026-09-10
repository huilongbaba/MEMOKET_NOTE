"""父进程没了就跟着退。

桌面版里后端是 Electron 的子进程。**父进程被强杀时，我们收不到任何通知**
——`before-quit` 只在正常退出路径上触发，`SIGKILL`、崩溃、活动监视器里
「强制退出」都不走那条路。于是留下一个占着 sqlite 和端口的 Python 进程，
下次启动时它还在，端口是随机的所以不冲突，但那份 sqlite 连接和后台任务
还活着，而且用户在活动监视器里看到一个杀不掉的东西。

做法是最土也最可靠的一种：盯着 `os.getppid()`。父进程一死，子进程会被
系统重新挂到 1（launchd/init）名下——这个信号是确定性的、跨平台的，不
依赖任何信号送达。

只在 Electron 明确要求时启用（它会传 MEMOKET_NOTE_PARENT_PID）。手工
`uvicorn` 起的后端不受影响。
"""

from __future__ import annotations

import os
import threading
import time

CHECK_SECONDS = 2.0


def watch_parent(expected_ppid: int, *, on_orphan=None) -> threading.Thread | None:
    """父进程变了就退出整个进程。返回那个看门狗线程（测试用）。"""
    if expected_ppid <= 1:
        return None

    def loop() -> None:
        while True:
            time.sleep(CHECK_SECONDS)
            if os.getppid() == expected_ppid:
                continue

            if on_orphan is not None:
                on_orphan()
                return

            # **先退，再说话。** 这里曾经是先 print 后 os._exit，而 print
            # 写的正是通往父进程的那根管道——父进程一死管道就断，print 抛
            # BrokenPipeError，异常从线程函数里跑出去，线程静默死掉，
            # os._exit 永远执行不到。那句日志恰好在看门狗唯一该起作用的
            # 场景里把看门狗弄死了。实测：强杀 Electron 之后后端活了 15 秒
            # 以上，而受控测试里（stdout 是终端，管道不会断）一切正常。
            try:
                print(f"[watchdog] 父进程 {expected_ppid} 没了，跟着退出", flush=True)
            except Exception:      # noqa: BLE001  管道断了、句柄没了，都不重要
                pass
            os._exit(0)
            # 真实情况下上面那行不返回。**但被替换掉时会返回**——测试里把
            # os._exit 换成记录函数，没有这个 return 的话线程会继续 while True
            # 转下去；测试结束、monkeypatch 还原之后它拿到的就是真的
            # os._exit(0)，把 pytest 整个干掉，退出码 0、输出截断在半行。
            # 实测踩过，症状是「测试跑到一半没了，还说成功」。
            return

    t = threading.Thread(target=loop, name="parent-watchdog", daemon=True)
    t.start()
    return t


def install_from_env(*, on_orphan=None) -> threading.Thread | None:
    raw = os.getenv("MEMOKET_NOTE_PARENT_PID", "")
    if not raw.isdigit():
        return None
    return watch_parent(int(raw), on_orphan=on_orphan)
