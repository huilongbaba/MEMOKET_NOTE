"""P12（产品就绪计划 §2 C2，`docs/TRACELOG-product.md` P12 节）：后端管得着的一小块。

  完成标准可检查（agent-native-editor §3.1）：用户勾过的条目记在 `notes.intent.checked`——
      `editor/intent.normalize` 收它（只认字符串、去重、封顶 CHECKED_MAX、每条封顶 FIELD_MAX），
      `PUT /api/notes/{id}/intent` 落库、`GET /api/notes` 带回；`as_text()` / `block()` 不带它（prompt 一个字不多）。

    cd backend && python -m pytest tests/test_p12_plan.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.editor import intent  # noqa: E402


def test_normalize_收_checked_只认字符串_去重_封顶():
    d = intent.normalize({"goal": "g", "done": "a；b", "source": "user",
                          "checked": ["b", "b", 3, None, "  a  ", "x" * 500]})
    assert d["checked"] == ["b", "a", "x" * intent.FIELD_MAX]
    assert intent.normalize({"checked": "b"})["checked"] == []          # 不是 list 当空
    assert intent.normalize({})["checked"] == []
    many = intent.normalize({"checked": [f"c{i}" for i in range(50)]})["checked"]
    assert len(many) == intent.CHECKED_MAX


def test_checked_不进_prompt():
    d = {"goal": "g", "reader": "r", "done": "a；b", "source": "user", "checked": ["b"]}
    assert intent.as_text(d) == "目标：g；读者：r；完成标准：a；b"
    assert "checked" not in intent.block(intent.as_text(d))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # 跟 test_p9_agent_native._client 一个做法：库指到 tmp，真库不碰
    from app.database import store
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app
    return TestClient(app)


def test_intent_checked_落库_带回(client):
    h = {"X-User-Id": "p12"}
    n = client.post("/api/notes", json={"title": "第 37 周周报", "content": "- 一条"}, headers=h).json()
    body = {"goal": "g", "reader": "r", "done": "每条进展有日期；卡住的说清要什么", "source": "user",
            "checked": ["卡住的说清要什么", "卡住的说清要什么"]}
    r = client.put(f"/api/notes/{n['id']}/intent", json=body, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["intent"]["checked"] == ["卡住的说清要什么"]
    got = next(x for x in client.get("/api/notes", headers=h).json() if x["id"] == n["id"])
    assert got["intent"]["checked"] == ["卡住的说清要什么"]
    # 老数据（P9 存的、没有 checked 字段）读出来是空列表，不 500
    r2 = client.put(f"/api/notes/{n['id']}/intent", json={"goal": "g", "source": "user"}, headers=h)
    assert r2.status_code == 200 and r2.json()["intent"]["checked"] == []
