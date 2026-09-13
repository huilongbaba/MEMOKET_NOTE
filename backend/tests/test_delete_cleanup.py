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


def test_运行记录孤儿不止note前缀一种(db):
    """第 187 轮：section:/prompt:/裸 id 的 key 指向已删笔记也要清；删笔记时也要一起带走。"""
    n = db.create_note("u", "甲", "x")
    with db.connect() as c:
        for i, key in enumerate(("gone000000", "section:gone000000", "prompt:gone000000",
                                 n["id"], f"section:{n['id']}", f"note:{n['id']}")):
            c.execute("INSERT INTO harness_runs (id,key,status,rounds,final_scores,weak_dimensions,created_at)"
                      " VALUES (?,?,?,?,?,?,?)", (f"o{i}", key, "complete", 1, "{}", "[]", "2026-01-01T00:00:00+00:00"))
        c.execute("DELETE FROM meta WHERE key='drop-orphan-runs-v2'")
        c.commit()
    with db.connect() as c:
        assert sorted(r[0] for r in c.execute("SELECT key FROM harness_runs")) == sorted([n["id"], f"section:{n['id']}", f"note:{n['id']}"])
    db.delete_note("u", n["id"])
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM harness_runs").fetchone()[0] == 0


def test_过期流水启动时清掉_新的留着(db):
    """第 264 轮：用量账本 / 跑完的入库任务 / 非活跃写作计划只增不减。"""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    old, fresh = (now - timedelta(days=100)).isoformat(), now.isoformat()
    with db.connect() as c:
        c.execute("INSERT INTO llm_usage (user_id, feature, model, prompt_tokens, completion_tokens, ms, created_at) VALUES ('u','x','m',1,1,1,?)", (old,))
        c.execute("INSERT INTO llm_usage (user_id, feature, model, prompt_tokens, completion_tokens, ms, created_at) VALUES ('u','x','m',1,1,1,?)", (fresh,))
        for jid, st, at in (("j-old", "done", old), ("j-run", "running", old), ("j-new", "done", fresh)):
            c.execute("INSERT INTO ingest_jobs (id, user_id, status, facts, detail, created_at) VALUES (?,?,?,0,'',?)", (jid, "u", st, at))
            c.execute("INSERT INTO ingest_items (id, job_id, idx, filename, kind, status, facts, detail, updated_at) VALUES (?,?,0,'f','doc',?,0,'',?)", ("i-" + jid, jid, st, at))
        for pid, st, at in (("p-old", "abandoned", old), ("p-act", "active", old), ("p-new", "done", fresh)):
            c.execute("INSERT INTO writing_plans (id, user_id, parent_note_id, goal, status, doc_note_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)", (pid, "u", "root", "g", st, "", at, at))
            c.execute("INSERT INTO writing_sections (id, plan_id, idx, title, status, note_id, summary, created_at) VALUES (?,?,0,'t','pending','','',?)", ("s-" + pid, pid, at))
        c.commit()
    out = db.sweep_old_rows()
    assert out == {"usage": 1, "jobs": 1, "plans": 1}
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM llm_usage").fetchone()[0] == 1
        assert {r[0] for r in c.execute("SELECT id FROM ingest_jobs")} == {"j-run", "j-new"}
        assert {r[0] for r in c.execute("SELECT job_id FROM ingest_items")} == {"j-run", "j-new"}
        assert {r[0] for r in c.execute("SELECT id FROM writing_plans")} == {"p-act", "p-new"}
        assert {r[0] for r in c.execute("SELECT plan_id FROM writing_sections")} == {"p-act", "p-new"}


def test_引用表跟正文对不上时启动重建_源侧同步也重建(db):
    """第 284 轮：两篇正文没引用、表里各挂三条（树上 ◆6）；update_note_from_source 那条路没重建引用。"""
    n = db.create_note("u", "甲", "据 [u-1-A] 所述")
    with db.connect() as c:
        c.execute("INSERT OR IGNORE INTO note_citations (note_id, fact_id, user_id) VALUES (?,?,?)", (n["id"], "u-9-Z", "u"))
        c.commit()
    assert db.reindex_citations() == 1
    assert [x["id"] for x in db.notes_citing("u", "u-9-Z")] == [] and [x["id"] for x in db.notes_citing("u", "u-1-A")] == [n["id"]]
    db.update_note_from_source("u", n["id"], "甲", "换成 [u-2-B] 了", "sha")
    assert [x["id"] for x in db.notes_citing("u", "u-1-A")] == [] and [x["id"] for x in db.notes_citing("u", "u-2-B")] == [n["id"]]
