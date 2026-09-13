"""前端日志上报：error / warn / info 三档都收，打成 `[client:<level>]` 一行；stack 截 4000 字。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "t-clog"}) as c:
        yield c


def test_三档都打成一行(client, capsys):
    for level in ("error", "warn", "info"):
        r = client.post("/api/client-log", json={"level": level, "message": f"hello {level}", "where": "probe"})
        assert r.status_code == 200
    out = capsys.readouterr().out
    for level in ("error", "warn", "info"):
        assert f"[client:{level}] user=t-clog probe hello {level}" in out


def test_栈截断(client, capsys):
    r = client.post("/api/client-log", json={"level": "error", "message": "boom", "stack": "x" * 10000})
    assert r.status_code == 200
    out = capsys.readouterr().out
    assert "boom" in out and out.count("x") <= 4100
