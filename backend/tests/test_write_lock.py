"""写入串行化的回归测试。

这里不调 LLM，也不用真的 KITE —— 只复现它的**写入模式**：
把整个 XML 读进内存、改、再全量写回。丢失更新只取决于这个模式本身，
和抽取逻辑无关，所以模拟就够了，而且跑得快、结果确定。

第一个测试先证明「不加锁真的会丢数据」。没有它，后面的测试通过了也说明
不了什么 —— 可能只是并发压根没撞上。

    cd backend && python -m pytest tests/test_write_lock.py -v
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.kite.kite_writer import WriteLockTimeout, write_lock  # noqa: E402

WRITERS = 8
SEED = "<codebook>\n</codebook>\n"


def _append_session(path: Path, tag: str, settle: float = 0.01) -> None:
    """复现 KITE remember() 的写入模式：全量读 -> 改 -> 全量写。

    settle 模拟 remember() 里那次 LLM 调用（实测约 13 秒）——
    读和写之间的这段时间，正是丢失更新的窗口。
    """
    text = path.read_text(encoding="utf-8")
    time.sleep(settle)
    text = text.replace("</codebook>", f"  <session id=\"{tag}\"/>\n</codebook>")
    path.write_text(text, encoding="utf-8")


def _run_concurrently(fn, count: int) -> None:
    threads = [threading.Thread(target=fn, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def test_unlocked_writes_lose_data(tmp_path):
    """基线：不加锁时并发写会互相覆盖。

    这个测试断言的是「缺陷存在」。如果哪天它失败了，说明写入模式变了，
    下面那个测试的意义也需要重新评估。
    """
    book = tmp_path / "codebook.xml"
    book.write_text(SEED, encoding="utf-8")

    _run_concurrently(lambda i: _append_session(book, f"s{i}"), WRITERS)

    survived = book.read_text(encoding="utf-8").count("<session ")
    assert survived < WRITERS, (
        f"预期出现丢失更新，但 {WRITERS} 个写入全部存活。"
        "并发可能没有真正重叠，调大 settle 再试。"
    )


def test_locked_writes_all_survive(tmp_path):
    """加锁后每个写入都不丢。"""
    book = tmp_path / "codebook.xml"
    book.write_text(SEED, encoding="utf-8")

    def writer(i: int) -> None:
        with write_lock(book, timeout=60):
            _append_session(book, f"s{i}")

    _run_concurrently(writer, WRITERS)

    text = book.read_text(encoding="utf-8")
    assert text.count("<session ") == WRITERS
    for i in range(WRITERS):
        assert f'id="s{i}"' in text, f"s{i} 丢失"


def test_lock_is_exclusive(tmp_path):
    """同一时刻只有一个持有者。"""
    book = tmp_path / "codebook.xml"
    book.write_text(SEED, encoding="utf-8")

    inside = 0
    overlaps = 0
    guard = threading.Lock()

    def writer(_i: int) -> None:
        nonlocal inside, overlaps
        with write_lock(book, timeout=60):
            with guard:
                inside += 1
                if inside > 1:
                    overlaps += 1
            time.sleep(0.02)
            with guard:
                inside -= 1

    _run_concurrently(writer, WRITERS)
    assert overlaps == 0


def test_different_codebooks_do_not_block(tmp_path):
    """不同用户的 codebook 是不同文件，必须能并行。

    KITE 只禁止同一文件的并发写。要是把不同用户也串起来，
    批量导入的吞吐会白白损失一个数量级。
    """
    books = []
    for i in range(4):
        b = tmp_path / f"user{i}" / "codebook.xml"
        b.parent.mkdir(parents=True)
        b.write_text(SEED, encoding="utf-8")
        books.append(b)

    hold = 0.3

    def writer(i: int) -> None:
        with write_lock(books[i], timeout=30):
            time.sleep(hold)

    t0 = time.monotonic()
    _run_concurrently(writer, len(books))
    elapsed = time.monotonic() - t0

    assert elapsed < hold * len(books) * 0.6, (
        f"耗时 {elapsed:.2f}s，接近串行的 {hold * len(books):.2f}s —— "
        "不同 codebook 之间不该互相阻塞"
    )


def test_timeout_raises(tmp_path):
    """等不到锁时抛 WriteLockTimeout，而不是静默继续写。"""
    book = tmp_path / "codebook.xml"
    book.write_text(SEED, encoding="utf-8")

    released = threading.Event()

    def holder() -> None:
        with write_lock(book, timeout=30):
            released.wait(2.0)

    t = threading.Thread(target=holder)
    t.start()
    time.sleep(0.2)

    try:
        with pytest.raises(WriteLockTimeout):
            with write_lock(book, timeout=0.3):
                pytest.fail("不该拿到锁")
    finally:
        released.set()
        t.join()


CHILD = """
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from app.kite.kite_writer import write_lock

book = Path(sys.argv[2])
with write_lock(book, timeout=60):
    text = book.read_text(encoding="utf-8")
    time.sleep(0.3)
    book.write_text(text.replace("</codebook>",
                    '  <session id="%s"/>\\n</codebook>' % sys.argv[3]),
                    encoding="utf-8")
"""


def test_cross_process_lock(tmp_path):
    """跨进程互斥 —— uvicorn --workers N 是多进程，线程锁管不到。"""
    book = tmp_path / "codebook.xml"
    book.write_text(SEED, encoding="utf-8")

    child = tmp_path / "child.py"
    child.write_text(CHILD, encoding="utf-8")
    app_root = str(Path(__file__).resolve().parent.parent)

    procs = [
        subprocess.Popen([sys.executable, str(child), app_root, str(book), f"p{i}"])
        for i in range(4)
    ]
    for p in procs:
        assert p.wait(timeout=120) == 0

    text = book.read_text(encoding="utf-8")
    assert text.count("<session ") == 4, "跨进程写入发生了丢失更新"
