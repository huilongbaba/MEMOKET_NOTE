"""叠加 / 合并两种关系 + 冲突收件箱（docs/agent-native-editor.md §3.3.1）。"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import store  # noqa: E402
from app.database.kb import inbox, relations  # noqa: E402
from app.database.kite import kite_memory  # noqa: E402
from app.database.kite.kite_memory import UserMemory  # noqa: E402


def _f(i, text, date):
    return {"id": f"u-{i}-A1", "text": text, "date": date}


def test_accumulation_lists_conditions_you_did_not_write():
    facts = [_f(1, "众筹订金定为 199 元，7 月 1 日前可全额退，只限首批 500 台。", "2026-05-08")]
    rels = relations.detect("众筹订金 199 元。", facts)
    kinds = [r["relation"] for r in rels]
    assert "accumulation" in kinds and "corroborated" in kinds and "conflict" not in kinds
    a = next(r for r in rels if r["relation"] == "accumulation")
    assert "500台" in a["values"] and "7-1" in a["values"] and a["fact_ids"] == ["u-1-A1"]
    # 正文把条件都写了 → 没有叠加
    full = relations.detect("众筹订金 199 元，7 月 1 日前可退，只限首批 500 台。", facts)
    assert "accumulation" not in [r["relation"] for r in full]


def test_merge_when_two_facts_say_the_same_thing_even_without_numbers():
    facts = [
        _f(1, "王工负责补通信模块的测试报告。", "2026-05-08"),
        _f(2, "王工负责补通信模块测试报告，下周三给。", "2026-05-12"),
        _f(3, "周五团建去爬山。", "2026-05-09"),
    ]
    rels = relations.detect("王工负责通信模块的测试报告。", facts)
    assert [r["relation"] for r in rels] == ["merge"]
    assert rels[0]["fact_ids"] == ["u-1-A1", "u-2-A1"] and "2026-05-08 和 2026-05-12 这两条" in rels[0]["say"]
    # 同一天的两条不说「X 和 X」
    same_day = [_f(1, "王工负责补通信模块的测试报告。", "2026-05-08"), _f(2, "王工负责补通信模块测试报告，下周三给。", "2026-05-08")]
    assert "2026-05-08 有两条" in relations.detect("王工负责通信模块的测试报告。", same_day)[0]["say"]
    # 不沾边的两条不会被凑成一对
    assert relations.detect("这个方向可以再想想。", facts) == []


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    fake = SimpleNamespace(kite_data_dir=tmp_path, kite_extract_model="fake", whisper_base_url="http://x")
    monkeypatch.setattr(kite_memory, "get_settings", lambda: fake)
    return UserMemory("u1")


def test_inbox_scan_records_conflicts_and_resolve(env):
    mem = env
    old = mem.add_manual_fact("obsidian-doc1-0", "电池容量从 300mAh 改到 380mAh。", date="2026-05-08", title="A")
    same_note = mem.add_manual_fact("note-n1-0", "电池容量 380mAh 的结构评审。", date="2026-05-09", title="B")
    new = mem.add_manual_fact("note-n1-1", "电池容量定在 420mAh。", date="2026-06-01", title="B")
    assert inbox.scan_session(mem, "u1", "note-n1-1", source="note") == 1
    # 再扫一次不重复
    assert inbox.scan_session(mem, "u1", "note-n1-1", source="note") == 0
    rows = store.list_conflicts("u1")
    assert len(rows) == 1 and rows[0]["new_fact_id"] == new["id"] and rows[0]["old_fact_id"] == old["id"]
    assert same_note["id"] not in (rows[0]["old_fact_id"],)     # 同一篇的别的块不算旧记录

    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        d = c.get("/api/kb/dashboard").json()
        assert d["conflicts_open"] == 1
        j = c.get("/api/kb/conflicts").json()
        assert j["open"] == 1 and j["conflicts"][0]["new"]["text"].startswith("电池容量定在") and j["conflicts"][0]["old"]["when"] == "2026-05-08"
        assert j["conflicts"][0]["new"]["note_id"] == "n1"
        cid = j["conflicts"][0]["id"]
        assert c.post(f"/api/kb/conflicts/{cid}/resolve", json={"action": "nope"}).status_code == 400
        r = c.post(f"/api/kb/conflicts/{cid}/resolve", json={"action": "new_wins"}).json()
        assert r["status"] == "resolved" and r["resolution"] == "new_wins"
        assert mem.fact_attrs("superseded_by") == {old["id"]: new["id"]}
        assert c.get("/api/kb/conflicts").json()["open"] == 0
        assert c.post(f"/api/kb/conflicts/{cid}/resolve", json={"action": "keep_both"}).status_code == 404
        # 被取代的记录不再参与关系判断
        rel = c.post("/api/memory/relations", json={"passage": "电池容量定在 500mAh。", "confirm": False}).json()
        assert old["id"] not in [i for r in rel["relations"] for i in r["fact_ids"]]


def test_merge_route_marks_drop_superseded_and_forgets_conflicts(env):
    mem = env
    a = mem.add_manual_fact("s-1-0", "王工负责补通信模块的测试报告。", date="2026-05-08", title="A")
    b = mem.add_manual_fact("s-2-0", "王工负责补通信模块测试报告，下周三给。", date="2026-05-12", title="B")
    store.add_conflict("u1", b["id"], a["id"], "x", "假冲突")
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        rel = c.post("/api/memory/relations", json={"passage": "王工负责通信模块的测试报告。", "confirm": False}).json()
        assert rel["relations"][0]["relation"] == "merge"
        assert c.post("/api/kb/fact/merge", json={"keep": a["id"], "drop": a["id"]}).status_code == 400
        r = c.post("/api/kb/fact/merge", json={"keep": b["id"], "drop": a["id"], "text": "王工负责补通信模块测试报告，下周三给（合并）。"}).json()
        assert r["merged_from"] == a["id"] and r["text"].endswith("（合并）。")
        assert mem.fact_attrs("superseded_by") == {a["id"]: b["id"]} and mem.fact_attrs("merged") == {a["id"]: "1"}
        assert store.count_open_conflicts("u1") == 0
        # 记住了：不再提这一对
        rel = c.post("/api/memory/relations", json={"passage": "王工负责通信模块的测试报告。", "confirm": False}).json()
        assert "merge" not in [r["relation"] for r in rel["relations"]]


def test_ingest_sync_scans_conflicts(env, monkeypatch):
    """走真正的摄入路径：remember 打桩成「把正文当一条事实」，摄入后收件箱里有一条。"""
    mem = env
    mem.add_manual_fact("obsidian-doc1-0", "DVT 节点定在 8 月 5 日。", date="2026-05-08", title="A")
    n = store.create_note("u1", title="T", content="DVT 节点定在 9 月 1 日。")

    def fake_remember(self, messages, *, session_id, date=None, title="", profile=None):
        self.add_manual_fact(session_id, messages[0]["content"], date=date or "2026-06-01", title=title)
        return 1
    monkeypatch.setattr(UserMemory, "remember", fake_remember)
    from app.routers import ingest
    ingest._ingest_job("job1", "u1", n["content"], "T", "note", source_id=n["id"])
    assert store.count_open_conflicts("u1") == 1
    # 同步（重抽）：旧 session 的事实没了，指着它的待办一起收掉，然后重新检出
    ingest._ingest_job("job2", "u1", n["content"], "T", "note", source_id=n["id"], replace=True)
    rows = store.list_conflicts("u1")
    assert len(rows) == 1 and rows[0]["new_fact_id"].startswith(f"note-{n['id']}-0")
