"""第 251 轮：供应商设置的入参要像个地址 / 模型名。"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_地址要有scheme_模型名不能空_空白key不覆盖(tmp_path, monkeypatch):
    from app.database import store
    from app.main import app
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        assert c.post("/api/settings/provider", json={"provider": "gpt", "gpt_base_url": "not a url"}).status_code == 400
        assert c.post("/api/settings/provider", json={"provider": "local", "asr_base_url": "192.168.1.1:8081"}).status_code == 400
        assert c.post("/api/settings/provider", json={"provider": "gpt", "gpt_model": "   "}).status_code == 400
        out = c.post("/api/settings/provider", json={"provider": "gpt", "gpt_base_url": "https://api.openai.com/v1/", "gpt_api_key": "sk-real"}).json()
        assert out["gpt_base_url"] == "https://api.openai.com/v1" and out["gpt_api_key_set"]
        out = c.post("/api/settings/provider", json={"provider": "gpt", "gpt_api_key": "   "}).json()
        assert out["gpt_api_key_set"], "空白 key 不该把原来的 key 覆盖掉"
        out = c.post("/api/settings/provider", json={"provider": "local", "asr_base_url": ""}).json()
        assert out["asr_base_url"] == ""
