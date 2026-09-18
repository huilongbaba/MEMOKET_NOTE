"""跑批脚本碰真库的那两道闸（`scripts/db_guard.py`）。

被什么逼出来的：2026-09-17 批 13，实施 agent 报告「一篇笔记都没写」，
而实际上两篇 terrence 的真实笔记被改了——`e78306202d78` 从 1976 字掉到 650 字
（丢了 1326 字用户自己写的内容）。原文靠备份救回来了。

这是这个仓**第二次**踩同一个坑（第一次记在 `harness_quality_sample.py` 开头：
三篇真实笔记的原文永久丢失）。第一次之后写的是一段警告注释，第二次照样发生——
**所以这次写成能跑的闸。**
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load():
    spec = importlib.util.spec_from_file_location("db_guard", _SCRIPTS / "db_guard.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["db_guard"] = mod          # dataclass 解注解要从 sys.modules 取（批 5 记过）
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop("db_guard", None)
    return mod


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "notes.sqlite3"
    c = sqlite3.connect(p)
    c.executescript("""
        CREATE TABLE notes (id TEXT PRIMARY KEY, content TEXT, updated_at TEXT);
        CREATE TABLE note_revisions (id TEXT PRIMARY KEY, created_at TEXT);
        INSERT INTO notes VALUES ('a', '甲甲甲', '2026-09-01T00:00:00');
        INSERT INTO notes VALUES ('b', '乙乙',   '2026-09-02T00:00:00');
    """)
    c.commit(); c.close()
    return p


def test_只读连接写不了(db):
    """靠 `mode=ro` 而不是靠「记得别写 SQL」——**这次出事正是因为有人以为自己没写**。"""
    g = _load()
    conn = g.readonly(db)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("UPDATE notes SET content='改了' WHERE id='a'")


def test_要写就必须说理由(db):
    """必填参数会让「顺手写一下」变成「先想清楚」。"""
    g = _load()
    with pytest.raises(ValueError, match="为什么"):
        g.writable("", db=db)
    with pytest.raises(ValueError):
        g.writable("   ", db=db)
    conn = g.writable("单测：验证可写路径确实可写", db=db)
    conn.execute("UPDATE notes SET content='改了' WHERE id='a'")     # 不该抛


def test_跑批没动笔记就放行(db):
    g = _load()
    with g.Watch(db):
        pass                                    # 什么都没干


def test_改了内容就抓住_哪怕行数和时间戳都没变(db):
    """**三样一起看，因为任何一样单独都骗得过。**
    这一条专治「改内容不涨行、时间戳写回去」。"""
    g = _load()
    with pytest.raises(g.NotesTouched, match="总字数"):
        with g.Watch(db):
            c = sqlite3.connect(db)
            c.execute("UPDATE notes SET content='甲甲甲甲甲甲' WHERE id='a'")  # 时间戳不动
            c.commit(); c.close()


def test_加了一篇也抓住(db):
    g = _load()
    with pytest.raises(g.NotesTouched, match="行数"):
        with g.Watch(db):
            c = sqlite3.connect(db)
            c.execute("INSERT INTO notes VALUES ('c','丙','2026-09-03T00:00:00')")
            c.commit(); c.close()


def test_删一段加一段正好抵消也抓得住(db):
    """总字数不变，但 `updated_at` 变了——这就是第三个信号存在的理由。"""
    g = _load()
    with pytest.raises(g.NotesTouched, match="最后修改"):
        with g.Watch(db):
            c = sqlite3.connect(db)
            c.execute("UPDATE notes SET content='丙丙丙', updated_at='2026-09-09T00:00:00'"
                      " WHERE id='a'")
            c.commit(); c.close()


def test_真要写的跑批显式声明就放行(db):
    """压测那类确实要写笔记的跑批走这条，但**必须自己写出来**。"""
    g = _load()
    with g.Watch(db, allow=True):
        c = sqlite3.connect(db)
        c.execute("UPDATE notes SET content='压测写的' WHERE id='a'")
        c.commit(); c.close()


def test_跑批自己炸了不要被闸盖住(db):
    """本来就抛了异常时，闸不该把真异常换成自己的——那会让排查从
    「这里报错了」变成「笔记被动了」，指向完全错误的方向。"""
    g = _load()
    with pytest.raises(ZeroDivisionError):
        with g.Watch(db):
            sqlite3.connect(db).execute(
                "UPDATE notes SET content='顺手改了' WHERE id='a'")
            1 / 0


def test_只盯笔记和它的历史_不盯跑批本来就该写的表(db):
    """`harness_runs` / `llm_usage` 这些跑批本来就要写——算进指纹会让闸天天误报，
    而**一个天天误报的闸等于没有闸**。"""
    g = _load()
    assert set(g.WATCHED) == {"notes", "note_revisions"}
