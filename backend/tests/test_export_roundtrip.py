"""导出的 zip 再导回来，树要长回原样：文件夹笔记的正文不能变成一个同名子笔记，
多层目录要嵌套（不是一个叫 a/b 的文件夹）。"""
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

    with TestClient(app, headers={"X-User-Id": "t-rt"}) as c:
        yield c


def _tree(client, user):
    rows = client.get("/api/tree", headers={"X-User-Id": user}).json()
    by = {r["note_id"]: r for r in rows}
    def path(r):
        out, cur = [], r
        while cur:
            out.append(cur["title"])
            cur = by.get(cur["parent_note_id"])
        return "/".join(reversed(out))
    return sorted(path(r) for r in rows)


def test_导出再导入_树长回原样(client):
    p = client.post("/api/notes", json={"title": "项目", "content": "# 项目\n总览正文"}).json()
    client.post("/api/notes", json={"title": "会议 A", "content": "正文 A 足够长", "parent_note_id": p["id"]})
    sub = client.post("/api/notes", json={"title": "子目录", "content": "子目录说明", "parent_note_id": p["id"]}).json()
    client.post("/api/notes", json={"title": "深处", "content": "深处的正文足够长", "parent_note_id": sub["id"]})
    z = zipfile.ZipFile(io.BytesIO(client.get("/api/export/markdown").content))
    files = [("files", (name, z.read(name), "text/markdown")) for name in z.namelist() if name.endswith(".md")]

    # 导进另一个用户，只进笔记不进知识库（不花模型）
    r = client.post("/api/import/files", data={"source": "obsidian", "to": "notes", "min_chars": "1"},
                    files=files, headers={"X-User-Id": "t-rt2"})
    assert r.status_code == 200, r.text
    assert _tree(client, "t-rt2") == ["项目", "项目/会议 A", "项目/子目录", "项目/子目录/深处"]
    notes = {n["title"]: n for n in client.get("/api/notes", headers={"X-User-Id": "t-rt2"}).json()}
    assert notes["项目"]["content"].rstrip() == "# 项目\n总览正文"        # 文件夹笔记的正文回到它自己身上
    assert notes["子目录"]["content"].rstrip() == "子目录说明"
    assert "id:" not in notes["会议 A"]["content"]                       # front-matter 剥掉了
