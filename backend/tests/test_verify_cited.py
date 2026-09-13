"""校验：选区那一段里已经引用的事实先按 id 取，再补词法召回（第 154 轮实拍：召回没捞到，
模型答「知识库没有记录」，其实用户就引在旁边）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import store
from app.routers import compose


def test_cited_near_takes_the_paragraph_of_the_selection():
    content = "开头 [u-1-A1]。\n\n4月16日的EVT准备4台主机 [u-2-B2] [u-2-B3]。后半句。\n\n结尾 [u-3-C3]。"
    assert compose._cited_near(content, "4月16日的EVT准备4台主机") == ["u-2-B2", "u-2-B3"]
    assert compose._cited_near(content, "不在正文里的选区 [u-9-F9]") == ["u-9-F9"]


def test_verify_feeds_cited_facts_first(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    facts = {"u-2-B2": {"id": "u-2-B2", "text": "EVT 准备 4 台主机，15 套 PCBA", "when": "2026-04-16"}}

    class FakeMem:
        def __init__(self, user): pass
        def fact_by_id(self, fid): return facts.get(fid)
        def recall(self, q, limit=8): return ([{"id": "u-7-X1", "text": "无关的一条", "date": ""}], [], 0.1)
        def source_lines(self, row): return ["原话"]
    monkeypatch.setattr(compose, "UserMemory", FakeMem)
    seen = {}

    async def fake_complete(messages, **kw):
        seen["user"] = messages[-1]["content"]
        return '[{"verdict":"支持","reason":"知识库 4 月 16 日记了同样的数","fact_index":0}]'
    monkeypatch.setattr(compose.llm, "complete", fake_complete)
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        content = "前文。\n\n4月16日的EVT准备4台主机和15套PCBA [u-2-B2]。\n\n后文。"
        r = c.post("/api/verify", json={"content": content, "selection": "4月16日的EVT准备4台主机和15套PCBA"}).json()
    assert "[0] EVT 准备 4 台主机" in seen["user"] and "[1] 无关的一条" in seen["user"]
    assert r["findings"][0]["fact_id"] == "u-2-B2" and r["findings"][0]["sources"] == ["原话"]
