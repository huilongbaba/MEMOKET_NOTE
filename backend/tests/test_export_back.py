"""导回（docs/import-sync-plan.md §2）：Obsidian 目录写入按 memoket_id 覆盖、对方改过先提示；
Notion / 飞书走假客户端，第二次导回是覆盖不是新建。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import exporters, store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app

    with TestClient(app, headers={"X-User-Id": "t-back"}) as c:
        yield c


def test_render_tree_与_zip_同一套路径(client):
    p = client.post("/api/notes", json={"title": "项目", "content": "# 项目\n总览"}).json()
    client.post("/api/notes", json={"title": "会议 A", "content": "正文 A", "parent_note_id": p["id"]})
    files = exporters.render_tree("t-back")
    paths = sorted(f.path for f in files)
    assert paths == ["项目/会议 A.md", "项目/项目.md"]
    assert all("memoket_id:" in f.content for f in files)
    only = exporters.render_tree("t-back", {p["id"]})
    assert [f.path for f in only] == ["项目/项目.md"]


def test_markdown_转块_两家(client):
    md = "---\nid: x\n---\n\n# 标题\n\n一段话\n第二行\n\n- 甲\n- 乙\n\n1. 一\n\n```py\nprint(1)\n```\n\n> 引用\n"
    nb = exporters.md_to_notion_blocks(md)
    kinds = [b["type"] for b in nb]
    assert kinds == ["heading_1", "paragraph", "bulleted_list_item", "bulleted_list_item",
                     "numbered_list_item", "code", "quote"]
    assert nb[1]["paragraph"]["rich_text"][0]["text"]["content"] == "一段话 第二行"
    fb = exporters.md_to_feishu_children(md)
    assert [b["block_type"] for b in fb] == [3, 2, 12, 12, 13, 14, 15]
    # 长段落切 2000 字
    long = exporters.md_to_notion_blocks("x" * 4500)
    assert len(long[0]["paragraph"]["rich_text"]) == 3


def test_obsidian_写入_覆盖_对方改过就跳过(client, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    n = client.post("/api/notes", json={"title": "笔记一", "content": "v1"}).json()
    r = client.post("/api/export/obsidian", json={"vault_dir": str(vault)})
    assert r.status_code == 200 and r.json()["written"] == 1
    f = vault / "笔记一.md"
    assert f.exists() and "v1" in f.read_text()
    # 什么都没变：跳过
    assert client.post("/api/export/obsidian", json={"vault_dir": str(vault)}).json()["skipped"] == 1
    # 本地改了：覆盖
    client.put(f"/api/notes/{n['id']}", json={"title": "笔记一", "content": "v2"})
    assert client.post("/api/export/obsidian", json={"vault_dir": str(vault)}).json()["written"] == 1
    assert "v2" in f.read_text()
    # 对方改了（内容不是我们写出去的那份）→ 冲突，不覆盖；force 才覆盖
    f.write_text("对方在 Obsidian 里改的")
    client.put(f"/api/notes/{n['id']}", json={"title": "笔记一", "content": "v3"})
    j = client.post("/api/export/obsidian", json={"vault_dir": str(vault)}).json()
    assert j["conflicts"] == ["笔记一.md"] and "对方" in f.read_text()
    j = client.post("/api/export/obsidian", json={"vault_dir": str(vault), "force": True}).json()
    assert j["written"] == 1 and "v3" in f.read_text()
    remotes = client.get(f"/api/export/remotes/{n['id']}").json()
    assert remotes[0]["platform"] == "obsidian" and remotes[0]["remote_path"] == "笔记一.md"
    assert client.post("/api/export/obsidian", json={"vault_dir": str(tmp_path / "nope")}).status_code == 400


class _FakeNotion:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.pages: dict[str, list] = {}

    def __call__(self, method, path, json):
        self.calls.append((method, path))
        if method == "POST" and path == "/pages":
            pid = f"page{len(self.pages) + 1}"
            self.pages[pid] = list(json["children"])
            return {"id": pid}
        if method == "GET" and path.startswith("/blocks/"):
            pid = path.split("/")[2].split("?")[0]
            return {"results": [{"id": f"{pid}-b{i}"} for i in range(len(self.pages[pid]))], "has_more": False}
        if method == "DELETE":
            return {}
        if method == "PATCH" and path.startswith("/blocks/"):
            pid = path.split("/")[2]
            self.pages[pid] = list(json["children"])
            return {}
        return {}


def test_notion_第二次是覆盖(client, monkeypatch):
    fake = _FakeNotion()
    monkeypatch.setattr(exporters.NotionWriter, "_req", lambda self, m, p, j=None: fake(m, p, j))
    n = client.post("/api/notes", json={"title": "N", "content": "# N\n\n一段"}).json()
    j = client.post("/api/export/notion", json={"token": "secret", "parent_page_id": "root-page"}).json()
    assert j == {"created": 1, "updated": 0, "failed": []}
    assert store.get_remote("t-back", n["id"], "notion")["remote_id"] == "page1"
    client.put(f"/api/notes/{n['id']}", json={"title": "N", "content": "# N\n\n两段\n\n三段"})
    j = client.post("/api/export/notion", json={"token": "secret", "parent_page_id": "root-page"}).json()
    assert j["created"] == 0 and j["updated"] == 1
    assert len(fake.pages) == 1 and len(fake.pages["page1"]) == 3
    assert ("DELETE", "/blocks/page1-b0") in fake.calls


class _FakeFeishu:
    def __init__(self):
        self.calls = []
        self.docs: dict[str, list] = {}

    def __call__(self, method, path, json):
        self.calls.append((method, path))
        if path.endswith("/documents") and method == "POST":
            did = f"doc{len(self.docs) + 1}"
            self.docs[did] = []
            return {"data": {"document": {"document_id": did}}}
        did = path.split("/documents/")[1].split("/")[0]
        if method == "GET" and "/children" in path:
            return {"data": {"items": [{}] * len(self.docs[did])}}
        if path.endswith("batch_delete"):
            self.docs[did] = []
            return {}
        if method == "POST" and path.endswith("/children"):
            self.docs[did].extend(json["children"])
            return {}
        return {}


def test_飞书_第二次是覆盖_凭据不落库(client, monkeypatch):
    fake = _FakeFeishu()
    monkeypatch.setattr(exporters.FeishuWriter, "_req", lambda self, m, p, j=None, auth=True: fake(m, p, j))
    n = client.post("/api/notes", json={"title": "F", "content": "一段\n\n- 点"}).json()
    body = {"app_id": "cli_x", "app_secret": "s3", "folder_token": "fld"}
    assert client.post("/api/export/feishu", json=body).json() == {"created": 1, "updated": 0, "failed": []}
    assert fake.docs["doc1"] and len(fake.docs["doc1"]) == 2
    client.put(f"/api/notes/{n['id']}", json={"title": "F", "content": "改了"})
    j = client.post("/api/export/feishu", json=body).json()
    assert j["updated"] == 1 and len(fake.docs) == 1 and len(fake.docs["doc1"]) == 1
    assert any(p.endswith("batch_delete") for _, p in fake.calls)
    with store.connect() as c:
        rows = c.execute("SELECT * FROM provider_config").fetchall()
    assert all("s3" not in str(dict(r)) for r in rows)
