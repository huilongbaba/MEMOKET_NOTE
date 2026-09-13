"""今天的日记：年 / 月 / 日一路建出来，第二次是同一篇。"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.database import store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "t-today"}) as c:
        yield c


def test_今天的日记_幂等_树的层级对(client):
    a = store.today_note("t-today", date(2026, 9, 13))
    b = store.today_note("t-today", date(2026, 9, 13))
    assert a["id"] == b["id"] and a["title"] == "09-13 周日" and a["content"].startswith("# 9 月 13 日 周日")
    paths = client.get(f"/api/tree/paths/{a['id']}").json()
    titles = [client.get(f"/api/notes/{nid}").json()["title"] for nid in paths[0][:-1]]
    assert titles == ["日记", "2026", "09 月"]
    # 同月另一天挂在同一个「09 月」下
    c2 = store.today_note("t-today", date(2026, 9, 14))
    assert client.get(f"/api/tree/paths/{c2['id']}").json()[0][:-1] == paths[0][:-1]
    r = client.post("/api/notes/today")
    assert r.status_code == 200 and r.json()["title"].endswith(("周一", "周二", "周三", "周四", "周五", "周六", "周日"))
