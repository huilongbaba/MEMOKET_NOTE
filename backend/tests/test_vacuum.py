"""删掉的页要还给文件系统：sqlite 删行不缩文件，dev 库 81% 是空页（第 415 轮）。"""

from __future__ import annotations

import os

import pytest

from app.database import store


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    store.init_db() if hasattr(store, "init_db") else None
    return tmp_path / "notes.sqlite3"


def test_空页多了才_VACUUM_小库不动(db):
    ids = [store.create_note("u", f"n{i}", "x" * 20000)["id"] for i in range(300)]
    before = os.path.getsize(db)
    for i in ids:
        store.delete_note("u", i)
        store.purge_trash("u", i)
    assert os.path.getsize(db) >= before * 0.9          # 删完文件没缩
    r = store.vacuum_if_bloated()
    assert r["vacuumed"] and r["after_mb"] < r["before_mb"]
    assert os.path.getsize(db) < before * 0.5
    assert store.vacuum_if_bloated()["vacuumed"] is False   # 已经干净了


def test_小库不_VACUUM(db):
    store.create_note("u", "一篇", "小")
    assert store.vacuum_if_bloated()["vacuumed"] is False
