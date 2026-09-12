"""magic tap 撞 token 上限：done 事件要带 truncated=true，已写内容一字不删。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import store  # noqa: E402
from app.routers import compose  # noqa: E402


def _events(text: str) -> list[tuple[str, dict]]:
    out = []
    ev = None
    for line in text.splitlines():
        if line.startswith("event: "):
            ev = line[7:]
        elif line.startswith("data: ") and ev:
            out.append((ev, json.loads(line[6:])))
    return out


def _run(monkeypatch, tmp_path, finish_reason: str, tail_reason: str = "stop"):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    calls: list[list[dict]] = []

    async def fake_stream(messages, *, max_tokens=0, temperature=0.0, effort="low", stats=None):
        calls.append(messages)
        if len(calls) == 1:
            for piece in ("团队建设部分", "先不按静态分工"):
                yield piece
            stats["finish_reason"] = finish_reason
        else:
            # 补尾那一次：最后一条 user 是补尾指令，倒数第二条是已写的半段
            assert "切断" in messages[-1]["content"] and messages[-2]["role"] == "assistant"
            yield "，而按变更顺序回写。"
            stats["finish_reason"] = tail_reason

    monkeypatch.setattr(compose.llm, "stream", fake_stream)
    monkeypatch.setattr(compose, "_retrieve", lambda *a, **k: ([], [], 0.0))
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        r = c.post("/api/magic-tap", json={"content": "# 标题\n\n正文。", "spine": "", "beats": []})
    assert r.status_code == 200
    return _events(r.text)


def test_length_gets_a_finishing_tail(monkeypatch, tmp_path):
    """撞上限：已写的不能少，后面接一次补尾；补尾写完了就不算截断。"""
    evs = _run(monkeypatch, tmp_path, "length")
    deltas = "".join(p["text"] for e, p in evs if e == "delta")
    assert deltas == "团队建设部分先不按静态分工，而按变更顺序回写。"
    assert [p for e, p in evs if e == "done"] == [{"truncated": False}]


def test_tail_also_truncated_is_reported(monkeypatch, tmp_path):
    evs = _run(monkeypatch, tmp_path, "length", tail_reason="length")
    assert [p for e, p in evs if e == "done"] == [{"truncated": True}]


def test_done_not_truncated_when_stop(monkeypatch, tmp_path):
    evs = _run(monkeypatch, tmp_path, "stop")
    assert [p for e, p in evs if e == "done"] == [{"truncated": False}]
