"""孤儿资产清理：没有任何笔记 / 历史版本 / 最近删除引用、且超过 7 天的图删掉；新的、有引用的留着。"""

from __future__ import annotations

import os
import time

import pytest

from app.database import store


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    return tmp_path


def _asset(d, name, age_days):
    p = d / name
    p.write_bytes(b"x" * 100)
    old = time.time() - age_days * 86400
    os.utime(p, (old, old))
    return p


def test_只删老的且没人引用的(db):
    assets = db / "assets"
    assets.mkdir()
    used = _asset(assets, "aaaaaaaaaaaaaaaaaaaaaaaa.png", 30)
    orphan_old = _asset(assets, "bbbbbbbbbbbbbbbbbbbbbbbb.png", 30)
    orphan_new = _asset(assets, "cccccccccccccccccccccccc.png", 1)
    in_trash = _asset(assets, "dddddddddddddddddddddddd.png", 30)
    store.create_note("u", "图", f"![](/api/assets/{used.name})")
    n = store.create_note("u", "要删的", f"![](/api/assets/{in_trash.name})")
    store.delete_note("u", n["id"])          # 进最近删除，payload 里还带着引用
    r = store.sweep_orphan_assets(assets, min_age_days=7)
    assert r == {"removed": 1, "bytes": 100}
    assert used.exists() and in_trash.exists() and orphan_new.exists() and not orphan_old.exists()


def test_没有资产目录也不报错(db):
    assert store.sweep_orphan_assets(db / "nope") == {"removed": 0, "bytes": 0}
