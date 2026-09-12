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
    monkeypatch.setattr(compose, "_fact_exists", lambda user: (lambda fid: False))
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
    assert [p for e, p in evs if e == "done"] == [{"truncated": False, "fake_citations": []}]


def test_tail_also_truncated_is_reported(monkeypatch, tmp_path):
    evs = _run(monkeypatch, tmp_path, "length", tail_reason="length")
    assert [p for e, p in evs if e == "done"] == [{"truncated": True, "fake_citations": []}]


def test_done_not_truncated_when_stop(monkeypatch, tmp_path):
    evs = _run(monkeypatch, tmp_path, "stop")
    assert [p for e, p in evs if e == "done"] == [{"truncated": False, "fake_citations": []}]


def test_long_content_is_compacted_in_prompt(monkeypatch, tmp_path):
    """47k 字的正文只给最近一截 + 前面各节梗概，提示词别跟着整篇线性长。"""
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    seen: list[list[dict]] = []

    async def fake_stream(messages, *, max_tokens=0, temperature=0.0, effort="low", stats=None):
        seen.append(messages)
        yield "续。"
        stats["finish_reason"] = "stop"

    monkeypatch.setattr(compose.llm, "stream", fake_stream)
    monkeypatch.setattr(compose, "_retrieve", lambda *a, **k: ([], [], 0.0))
    monkeypatch.setattr(compose, "_fact_exists", lambda user: (lambda fid: False))
    content = "# 长文\n\n" + "\n\n".join(f"## 第{i}节\n\n这一节讨论第{i}周的排期与样机{i}。" for i in range(600))
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        r = c.post("/api/magic-tap", json={"content": content, "spine": "", "beats": []})
    assert r.status_code == 200
    user_msg = seen[0][-1]["content"]
    assert len(user_msg) < len(content) // 2
    assert "第599节" in user_msg           # 最近的原样在
    assert "更早的" in user_msg            # 再早的折成一句


def test_编造的引用在_done_里报出来(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")

    async def fake_stream(messages, *, max_tokens=0, temperature=0.0, effort="low", stats=None):
        yield "样机安排 [terrence-23F3-4F3]，另见 [u-1-A] 和 [u-9-FF]。"
        stats["finish_reason"] = "stop"
    monkeypatch.setattr(compose.llm, "stream", fake_stream)
    monkeypatch.setattr(compose, "_retrieve", lambda *a, **k: (["[u-1-A] [2026-06] 材料"], ["u-1-A"], 0.0))
    monkeypatch.setattr(compose, "_fact_exists", lambda user: (lambda fid: False))
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        r = c.post("/api/magic-tap", json={"content": "# 标题\n\n正文。", "spine": "", "beats": []})
    done = [p for e, p in _events(r.text) if e == "done"][0]
    assert done["fake_citations"] == ["u-9-FF", "terrence-23F3-4F3"]
