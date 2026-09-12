"""删笔记要把挂在它上面的东西一起带走；运行记录每个 key 只留 50 条。"""
import pytest

from app.database import store


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    return store


def test_删笔记带走引用_版本_快照_运行记录(db):
    n = db.create_note("u", "甲", "据 [u-1-A] 所述，第一版")
    db.update_note("u", n["id"], "甲", "据 [u-1-A] 所述，第二版")   # 留一版历史
    db.save_snapshot("u", n["id"], "note", 1, "{}")
    db.record_harness_run(f"note:{n['id']}", "complete", 1, {}, [])
    assert db.list_revisions("u", n["id"]) and db.list_snapshots("u")
    db.delete_note("u", n["id"])
    with db.connect() as c:
        for table, col in (("note_citations", "note_id"), ("note_revisions", "note_id"),
                           ("harness_snapshots", "note_id")):
            assert c.execute(f"SELECT COUNT(*) FROM {table} WHERE {col}=?", (n["id"],)).fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM harness_runs WHERE key=?", (f"note:{n['id']}",)).fetchone()[0] == 0


def test_运行记录每个key只留50条(db):
    for i in range(60):
        db.record_harness_run("note:x", "complete", i, {}, [])
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM harness_runs WHERE key='note:x'").fetchone()[0] == 50
    assert db.recent_harness_runs("note:x", 1)[0]["rounds"] == 59
