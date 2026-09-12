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


def test_建笔记时引用就进反查表(db):
    n = db.create_note("u", "甲", "据 [u-7-B] 所述")
    assert [x["id"] for x in db.notes_citing("u", "u-7-B")] == [n["id"]]


def test_老库里的孤儿行一次清掉(db):
    n = db.create_note("u", "甲", "据 [u-1-A] 所述")
    with db.connect() as c:
        c.execute("INSERT INTO note_citations (user_id, note_id, fact_id) VALUES ('u', 'gone000000', 'u-2-C')")
        c.execute("DELETE FROM meta WHERE key='drop-orphans-v1'")
        c.commit()
    with db.connect() as c:                    # 重新 connect 会再跑一次迁移
        assert c.execute("SELECT COUNT(*) FROM note_citations WHERE note_id='gone000000'").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM note_citations WHERE note_id=?", (n["id"],)).fetchone()[0] == 1


def test_老库里的运行记录一次修剪到每key50条(db):
    with db.connect() as c:
        for i in range(70):
            c.execute("INSERT INTO harness_runs (id,key,status,rounds,final_scores,weak_dimensions,created_at)"
                      " VALUES (?,?,?,?,?,?,?)", (f"r{i}", "note:z", "complete", i, "{}", "[]", f"2026-01-01T00:00:{i % 60:02d}+00:00"))
        c.execute("DELETE FROM meta WHERE key='prune-runs-v1'")
        c.commit()
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM harness_runs WHERE key='note:z'").fetchone()[0] == 50
