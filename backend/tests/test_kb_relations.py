"""记忆的关系：冲突 / 延续 / 印证 / 缺依据（纯代码，零 LLM）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.kb import relations  # noqa: E402


def _f(i, text, date):
    return {"id": f"u-{i}-A1", "text": text, "date": date}


def test_extract_values():
    v = relations.extract_values("DVT 从 6 月 3 日推迟到 2026-08-05，电池 380mAh，订金 199 元，占比 12%")
    assert v["dates"] == ["2026-8-5", "6-3"]
    assert v["nums"] == [(380.0, "mAh"), (199.0, "元"), (12.0, "%")]


def test_conflict_on_same_unit_different_value():
    facts = [_f(1, "Speaker B 提出电池容量从 300mAh 改到 380mAh。", "2026-05-08")]
    rels = relations.detect("电池容量定在 420mAh，结构要增厚。", facts)
    kinds = [r["relation"] for r in rels]
    assert "conflict" in kinds
    c = next(r for r in rels if r["relation"] == "conflict")
    assert c["fact_ids"] == ["u-1-A1"] and "420mAh" in c["say"]


def test_continuation_chain_when_value_changed_over_time():
    facts = [
        _f(1, "电池容量从 150mAh 提到 200mAh。", "2026-03-10"),
        _f(2, "电池容量从 200mAh 改到 300mAh。", "2026-04-10"),
    ]
    rels = relations.detect("电池容量改到 380mAh。", facts)
    c = next(r for r in rels if r["relation"] == "continuation")
    assert c["values"][-1] == "380mAh（你写的）"
    assert c["values"][0] == "150mAh"
    assert set(c["fact_ids"]) == {"u-1-A1", "u-2-A1"}


def test_corroborated_and_date_conflict():
    facts = [_f(1, "DVT 从 6 月 3 日调整到 8 月 5 日。", "2026-05-08")]
    same = relations.detect("DVT 定在 8 月 5 日。", facts)
    assert any(r["relation"] == "corroborated" and r["unit"] == "date" for r in same)
    diff = relations.detect("DVT 定在 9 月 1 日。", facts)
    c = next(r for r in diff if r["relation"] == "conflict")
    assert "9-1" in c["say"] and "8-5" in c["say"]


def test_number_and_date_on_same_fact_report_once():
    facts = [_f(1, "预售订金定为 199 元，7 月 1 日前可全额退。", "2026-09-12")]
    rels = relations.detect("众筹订金 199 元不变，退款期到 7 月 1 日。", facts)
    assert [r["relation"] for r in rels] == ["corroborated"]


def test_unsupported_when_nothing_related_and_nothing_when_no_values():
    facts = [_f(1, "周五团建去爬山。", "2026-05-08")]
    rels = relations.detect("用户反馈续航不够一天，8 台里有 6 台。", facts)
    assert [r["relation"] for r in rels] == ["unsupported"]
    assert relations.detect("这个方向我觉得可以再想想。", facts) == []


def test_relations_route_and_supersede(tmp_path, monkeypatch):
    """路由：召回 → 代码判候选 → （有冲突才）模型确认一句；取代：PATCH superseded_by。"""
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from app.database import store
    from app.database.kite import kite_memory
    from app.database.kite.kite_memory import UserMemory
    from app.routers import memory as memory_router

    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    fake = SimpleNamespace(kite_data_dir=tmp_path, kite_extract_model="fake", whisper_base_url="http://x")
    monkeypatch.setattr(kite_memory, "get_settings", lambda: fake)
    mem = UserMemory("u1")
    a = mem.add_manual_fact("note-n1-0", "电池容量从 300mAh 改到 380mAh。", date="2026-05-08", title="T")
    b = mem.add_manual_fact("note-n1-0", "电池容量再改到 420mAh。", date="2026-06-01", title="T")
    rows = [{"id": a["id"], "text": a["text"], "date": "2026-05-08"}]
    monkeypatch.setattr(UserMemory, "recall", lambda self, q, limit=8: (rows, [], 0.1))
    seen = {}

    async def fake_json(messages, **kw):
        seen["prompt"] = messages[-1]["content"]
        return [{"index": 0, "keep": True, "say": "5 月 8 日记的是 380mAh，你写的 420mAh 是新值。"}]
    monkeypatch.setattr(memory_router.llm, "complete_json", fake_json)
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        r = c.post("/api/memory/relations", json={"passage": "电池容量定在 420mAh。"}).json()
        assert r["relations"][0]["relation"] == "conflict"
        assert r["relations"][0]["say"].startswith("5 月 8 日")
        assert r["relations"][0]["facts"][0]["id"] == a["id"]
        assert "候选关系" in seen["prompt"]
        # 取代
        r2 = c.patch(f"/api/kb/fact/{a['id']}", json={"superseded_by": b["id"]}).json()
        assert r2["superseded_by"] == b["id"]
        assert mem.fact_attrs("superseded_by") == {a["id"]: b["id"]}
        assert c.patch(f"/api/kb/fact/{a['id']}", json={"superseded_by": "nope"}).status_code == 404
        r3 = c.patch(f"/api/kb/fact/{a['id']}", json={"superseded_by": ""}).json()
        assert r3["superseded_by"] == ""


def test_evolution_chains():
    from types import SimpleNamespace
    from app.database.kb import pages
    F = lambda i, when, obj: SimpleNamespace(id=f"f{i}", text=f"t{i}", when=when, kind="", who="", conf="", topics=(), entities=(), unit="s", obj=obj)  # noqa: E731
    facts = [F(1, "2026-03-10", ("battery",)), F(2, "2026-04-10", ("battery",)), F(3, "", ("battery",)), F(4, "2026-01-01", ("app",))]
    chains = pages.evolution_chains(facts)
    assert len(chains) == 1 and chains[0]["obj"] == "battery"
    assert [f["id"] for f in chains[0]["facts"]] == ["f1", "f2"]


def test_relations_batch_route(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from app.database import store
    from app.database.kite import kite_memory
    from app.database.kite.kite_memory import UserMemory

    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    fake = SimpleNamespace(kite_data_dir=tmp_path, kite_extract_model="fake", whisper_base_url="http://x")
    monkeypatch.setattr(kite_memory, "get_settings", lambda: fake)
    rows = [{"id": "u-1-A1", "text": "电池容量从 300mAh 改到 380mAh。", "date": "2026-05-08"}]
    monkeypatch.setattr(UserMemory, "recall", lambda self, q, limit=8: (rows, [], 0.1))
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        r = c.post("/api/memory/relations/batch", json={"passages": ["电池容量定在 420mAh。", "没有数字的一段", "短"]}).json()
    assert r["marks"][0]["relation"] == "conflict" and r["marks"][1] is None and r["marks"][2] is None
