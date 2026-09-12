"""启动时的笔记库自动备份：一天一份、留 7 日 + 3 月。"""
from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from app.database import backup, store


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    monkeypatch.setattr(backup, "backup_dir", lambda: (tmp_path / "backups").mkdir(exist_ok=True) or tmp_path / "backups")
    return store


def test_一天只备一份_且是一致快照(db, tmp_path):
    n = db.create_note("u", "甲", "正文")
    p = backup.maybe_backup(db._db_path(), date(2026, 9, 12))
    assert p and p.name == "notes-20260912.sqlite3"
    assert backup.maybe_backup(db._db_path(), date(2026, 9, 12)) is None
    c = sqlite3.connect(p)
    assert c.execute("SELECT title FROM notes WHERE id=?", (n["id"],)).fetchone()[0] == "甲"


def test_修剪_留七日加每月第一份(tmp_path, monkeypatch):
    d = tmp_path / "backups"; d.mkdir()
    monkeypatch.setattr(backup, "backup_dir", lambda: d)
    days = ["20260601", "20260602", "20260715", "20260801", "20260810"] + [f"202609{i:02d}" for i in range(1, 13)]
    for s in days:
        (d / f"notes-{s}.sqlite3").write_bytes(b"x")
    backup.prune(d)
    left = sorted(p.name[6:14] for p in d.iterdir())
    # 最近 7 日：0906..0912；每月第一份（最近 3 个月：07/08/09 → 0715 0801 0901）
    assert left == ["20260715", "20260801", "20260901", "20260906", "20260907", "20260908", "20260909", "20260910", "20260911", "20260912"]


def test_知识库一周一份留两份(tmp_path, monkeypatch):
    d = tmp_path / "backups"; d.mkdir()
    monkeypatch.setattr(backup, "backup_dir", lambda: d)
    (tmp_path / "u1").mkdir(); (tmp_path / "u1" / "codebook.xml").write_text("<x/>")
    (tmp_path / "u2").mkdir()                          # 没有知识库的用户跳过
    made = backup.maybe_backup_kb(tmp_path, date(2026, 9, 12))
    assert [p.name for p in made] == ["codebook-2026W37.xml"]
    assert backup.maybe_backup_kb(tmp_path, date(2026, 9, 13)) == []      # 同一周
    backup.maybe_backup_kb(tmp_path, date(2026, 9, 20))
    backup.maybe_backup_kb(tmp_path, date(2026, 9, 27))
    left = sorted(p.name for p in (d / "kb" / "u1").iterdir())
    assert left == ["codebook-2026W38.xml", "codebook-2026W39.xml"]
