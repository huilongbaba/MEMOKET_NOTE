"""本地接口不接受别的网站发来的写请求（CORS 挡不住不预检的 form / multipart POST）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import store


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app
    return TestClient(app, headers={"X-User-Id": "t-xs"})


def test_跨站的写请求被拒_本机的放行(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as c:
        evil = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
        r = c.post("/api/notes", json={"title": "x", "content": "y"}, headers=evil)
        assert r.status_code == 403
        r = c.post("/api/import/notion", data={"token": "t", "to": "kb"}, headers={"Origin": "https://evil.example"})
        assert r.status_code == 403
        # 跨站 GET 照旧（响应本来就读不到）；本机来源和不带 Origin 的照旧
        assert c.get("/api/notes", headers=evil).status_code == 200
        assert c.post("/api/notes", json={"title": "a", "content": "b"}, headers={"Origin": "http://127.0.0.1:47231"}).status_code == 200
        assert c.post("/api/notes", json={"title": "a", "content": "b"}, headers={"Origin": "http://localhost:5173"}).status_code == 200
        assert c.post("/api/notes", json={"title": "a", "content": "b"}).status_code == 200


def test_user_id_不能带路径(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app
    with TestClient(app) as c:
        for bad in ("../x", "a/b", "..", "a b", "x" * 65):
            assert c.get("/api/notes", headers={"X-User-Id": bad}).status_code == 400, bad
        for ok in ("terrence", "shot-demo", "user_1.a"):
            assert c.get("/api/notes", headers={"X-User-Id": ok}).status_code == 200, ok
