"""父进程没了，后端要跟着退。

这条来自一次实测：`pkill` 掉 Electron 之后，它拉起的 uvicorn **活了下来**
——`before-quit` 只在正常退出路径上触发，强杀、崩溃、活动监视器里「强制
退出」都不走那条路。留下的进程占着 sqlite 和端口，用户在活动监视器里看到
一个不知道是什么的 Python。
"""

from __future__ import annotations

import os
import threading
import time

from app.util import parent_watch


def test_父进程没变就一直不动(monkeypatch):
    fired = threading.Event()
    monkeypatch.setattr(parent_watch, "CHECK_SECONDS", 0.01)
    monkeypatch.setattr(os, "getppid", lambda: 4242)
    parent_watch.watch_parent(4242, on_orphan=fired.set)
    assert not fired.wait(0.15), "父进程还在，不该退"


def test_父进程变了就退(monkeypatch):
    fired = threading.Event()
    monkeypatch.setattr(parent_watch, "CHECK_SECONDS", 0.01)
    # 父进程死掉之后，子进程会被系统重新挂到 1 名下——这就是那个信号
    monkeypatch.setattr(os, "getppid", lambda: 1)
    parent_watch.watch_parent(4242, on_orphan=fired.set)
    assert fired.wait(1.0), "父进程没了却没退"


def test_没传父进程号就不装看门狗(monkeypatch):
    monkeypatch.delenv("MEMOKET_NOTE_PARENT_PID", raising=False)
    assert parent_watch.install_from_env() is None


def test_父进程号是1时不装(monkeypatch):
    """已经是孤儿了（或者根本没父亲），装了只会立刻自杀。"""
    monkeypatch.setenv("MEMOKET_NOTE_PARENT_PID", "1")
    assert parent_watch.install_from_env() is None


def test_看门狗是守护线程不拖住退出(monkeypatch):
    monkeypatch.setattr(parent_watch, "CHECK_SECONDS", 10.0)
    monkeypatch.setattr(os, "getppid", lambda: 4242)
    t = parent_watch.watch_parent(4242, on_orphan=lambda: None)
    assert t is not None and t.daemon, "非守护线程会让进程退不干净"
    _ = time


def test_stdout_断了也照样退(monkeypatch):
    """**这条是复现出来的真 bug。**

    看门狗原来是先 print 再 os._exit，而它的 stdout 是通往父进程的管道。
    父进程一死管道就断，print 抛 BrokenPipeError，异常从线程函数里跑出去，
    线程静默死掉，os._exit 永远执行不到——那句日志恰好在看门狗唯一该起
    作用的场景里把看门狗弄死了。

    实测：强杀 Electron 之后后端活了 15 秒以上；而受控实验里 stdout 是
    终端、管道不会断，所以一切正常——**测试环境比真实环境宽容，是这类
    bug 藏身的地方。**
    """
    import builtins

    exited: list[int] = []
    monkeypatch.setattr(parent_watch, "CHECK_SECONDS", 0.01)
    monkeypatch.setattr(os, "getppid", lambda: 1)
    monkeypatch.setattr(os, "_exit", lambda code: exited.append(code))

    def boom(*a, **kw):
        raise BrokenPipeError("管道断了")

    monkeypatch.setattr(builtins, "print", boom)
    parent_watch.watch_parent(4242)          # 不传 on_orphan，走真实退出路径
    for _ in range(100):
        if exited:
            break
        time.sleep(0.01)
    assert exited == [0], "stdout 断了就退不掉了"
