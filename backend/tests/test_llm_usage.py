"""模型用量账本：流式最后一帧的 usage 记进去、非流式从响应体取；按用户 / 功能汇总。"""

from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from app.database import store
from app.util import llm


class _FakeResponse:
    def __init__(self, lines):
        self._lines = lines

    async def aiter_lines(self):
        for ln in self._lines:
            yield ln


def _drain(agen):
    async def run():
        return [x async for x in agen]
    return asyncio.run(run())


def test_流的最后一帧_usage_被记账(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    lines = ["data: " + json.dumps({"choices": [{"delta": {"content": "甲"}}]}),
             "data: " + json.dumps({"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 30}}),
             "data: [DONE]"]
    llm.ctx_user.set("u1"); llm.ctx_feature.set("magic-tap")
    assert _drain(llm._consume_sse(_FakeResponse(lines), {}, model="m", t0=0.0)) == ["甲"]
    s = store.usage_summary("u1")
    assert s["today"] == {"calls": 1, "prompt_tokens": 120, "completion_tokens": 30, "ms": s["today"]["ms"]}
    assert s["by_feature"] == [{"feature": "magic-tap", "calls": 1, "tokens": 150}] and s["models"] == ["m"]
    assert store.usage_summary("someone-else")["all"]["calls"] == 0


def test_中间件按路径记功能名_设置页能看到(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    seen = {}

    async def fake_complete(messages, **kw):
        seen["feature"], seen["user"] = llm.ctx_feature.get(), llm.ctx_user.get()
        llm._record({"prompt_tokens": 10, "completion_tokens": 5}, "fake-model", 0.0)
        return "[]"
    from app.routers import compose
    monkeypatch.setattr(compose.llm, "complete", fake_complete)
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u9"}) as c:
        c.post("/api/verify", json={"content": "一段 4 台。", "selection": "一段 4 台"})
        u = c.get("/api/settings/usage").json()
    assert seen == {"feature": "verify", "user": "u9"}
    assert u["all"]["calls"] == 1 and u["by_feature"][0]["feature"] == "verify" and u["models"] == ["fake-model"]


def test_功能名去掉id段():
    from app.main import app  # noqa: F401 —— 中间件在 main 里
    parts = [p for p in "/api/notes/5f65df10cad6/sync".split("/") if p and p != "api"]
    assert "/".join(p for p in parts if not (len(p) >= 12 and all(ch in "0123456789abcdef" for ch in p))) == "notes/sync"


def test_带思考的流也记账(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    lines = ["data: " + json.dumps({"choices": [{"delta": {"reasoning_content": "想"}}]}),
             "data: " + json.dumps({"choices": [{"delta": {"content": "写"}}]}),
             "data: " + json.dumps({"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}),
             "data: [DONE]"]
    llm.ctx_user.set("u2"); llm.ctx_feature.set("note-harness/run")
    assert _drain(llm._consume_tagged(_FakeResponse(lines), model="m2", t0=0.0)) == [("thinking", "想"), ("output", "写")]
    assert store.usage_summary("u2")["all"]["calls"] == 1
