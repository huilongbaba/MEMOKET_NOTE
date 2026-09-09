"""codebook 写入串行化。

KITE 的 ``Memory.remember()`` 全量重写 XML 且**不加锁** —— 源码 docstring 原话:

    Persisting rewrites the whole artifact and takes no lock, so two writers
    against the same file are not supported.

两个并发写会互相覆盖，结果是静默的数据损坏（不报错，事实凭空消失）。
单条入库时撞上的概率低，但批量导入会把并发写变成常态，所以必须挡住。

两层锁，缺一不可:

- **进程内**: ``threading.Lock``，覆盖 FastAPI ``BackgroundTasks`` 线程池里的并发。
- **跨进程**: 文件锁，覆盖 ``uvicorn --workers N`` 的多进程部署。
  只有进程内锁的话，多 worker 部署下照样损坏。

锁的粒度是**单个 codebook 文件**。不同用户是不同文件，可以并行 ——
KITE 只禁止同一文件的并发写，``recall()`` 甚至支持多文件同时 load。
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

# 一次 remember() 要调 LLM，本地 30B 上约 13s。批量导入时队列可能排很长，
# 所以默认超时给得比较宽松 —— 宁可等，也不要因为超时把任务判失败。
DEFAULT_TIMEOUT = 600.0

# 文件锁的轮询间隔。不用阻塞式加锁是因为 Windows 的 msvcrt 阻塞模式
# 只重试 10 次（约 10 秒）就抛异常，扛不住 13s 一次的写入。
_POLL_INTERVAL = 0.1

_thread_locks: dict[str, threading.Lock] = {}
_registry_guard = threading.Lock()


class WriteLockTimeout(RuntimeError):
    """等锁超时。调用方应把它当作可重试的失败，而不是数据错误。"""


def _thread_lock_for(key: str) -> threading.Lock:
    with _registry_guard:
        lock = _thread_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _thread_locks[key] = lock
        return lock


if os.name == "nt":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(fd: int) -> None:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass


@contextmanager
def write_lock(codebook_path: str | Path, timeout: float = DEFAULT_TIMEOUT):
    """独占某个 codebook 的写权限。

    用法::

        with write_lock(mem.path):
            memory.remember(...)

    锁文件是 codebook 旁边的 ``.lock``，不会被删除 —— 删除会和其他进程的
    打开操作竞争，反而制造出锁失效的窗口。空文件的开销可以忽略。
    """
    path = Path(codebook_path)
    key = str(path.resolve())
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    deadline = time.monotonic() + timeout
    thread_lock = _thread_lock_for(key)

    # 先拿进程内锁。它便宜，而且能让同进程的等待者不去空转文件锁。
    if not thread_lock.acquire(timeout=max(timeout, 0.0)):
        raise WriteLockTimeout(f"等待进程内写锁超时: {path}")

    fd = None
    try:
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        while True:
            if _try_lock(fd):
                break
            if time.monotonic() >= deadline:
                raise WriteLockTimeout(f"等待文件写锁超时: {lock_path}")
            time.sleep(_POLL_INTERVAL)

        try:
            yield path
        finally:
            _unlock(fd)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        thread_lock.release()
