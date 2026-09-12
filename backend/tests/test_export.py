"""整库导出：树的层级变成文件夹，克隆只写一份，孤儿进 _未归类。"""
from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.database import store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app

    with TestClient(app, headers={"X-User-Id": "t-export"}) as c:
        yield c


def _names(data: bytes) -> list[str]:
    return sorted(zipfile.ZipFile(io.BytesIO(data)).namelist())


def test_层级_克隆_孤儿(client):
    p = client.post("/api/notes", json={"title": "项目", "content": "# 项目\n总览"}).json()
    a = client.post("/api/notes", json={"title": "会议 A", "content": "正文 A", "parent_note_id": p["id"]}).json()
    client.post("/api/notes", json={"title": "", "content": "# 首行当标题\n内容", "parent_note_id": p["id"]})
    # 克隆 A 到根
    client.post("/api/tree/branches", json={"note_id": a["id"], "parent_note_id": "root"})
    r = client.get("/api/export/markdown")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/zip")
    names = _names(r.content)
    assert "README.txt" in names
    assert "项目/项目.md" in names and "项目/会议 A.md" in names and "项目/首行当标题.md" in names
    # 克隆位置只留一个指路文件
    assert any(n.endswith("会议 A.link.txt") for n in names)
    assert sum(1 for n in names if n.endswith("会议 A.md")) == 1
    z = zipfile.ZipFile(io.BytesIO(r.content))
    body = z.read("项目/会议 A.md").decode()
    assert body.startswith("---\nid: " + a["id"]) and body.rstrip().endswith("正文 A")


def test_query_参数指定用户_文件名带时间(client):
    client.post("/api/notes", json={"title": "甲", "content": "x"})
    r = client.get("/api/export/markdown?user=someone-else", headers={})
    assert "甲.md" not in _names(r.content)          # 别人的库里没有这篇
    assert "memoket-note-" in r.headers["content-disposition"]
