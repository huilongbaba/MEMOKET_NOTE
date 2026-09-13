"""笔记搜索：store.list_notes() 的 q 参数。

    cd backend && python -m pytest tests/test_notes_search.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import store# noqa: E402


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    return store


def test_list_notes_without_query_returns_all(isolated_store):
    isolated_store.create_note("u1", "项链方案", "记一下项链加工的进度")
    isolated_store.create_note("u1", "周会纪要", "今天讨论了发布计划")
    assert len(isolated_store.list_notes("u1")) == 2


def test_list_notes_query_matches_title(isolated_store):
    isolated_store.create_note("u1", "项链方案", "正文无关")
    isolated_store.create_note("u1", "周会纪要", "正文无关")
    titles = [n["title"] for n in isolated_store.list_notes("u1", "项链")]
    assert titles == ["项链方案"]


def test_list_notes_query_matches_content(isolated_store):
    isolated_store.create_note("u1", "笔记A", "里面提到了供应商交付")
    isolated_store.create_note("u1", "笔记B", "跟这个话题无关")
    titles = [n["title"] for n in isolated_store.list_notes("u1", "供应商")]
    assert titles == ["笔记A"]


def test_list_notes_query_no_match_returns_empty(isolated_store):
    isolated_store.create_note("u1", "笔记A", "正文")
    assert isolated_store.list_notes("u1", "找不到的词") == []


def test_list_notes_query_scoped_per_user(isolated_store):
    isolated_store.create_note("u1", "项链方案", "正文")
    isolated_store.create_note("u2", "项链设计", "正文")
    titles = [n["title"] for n in isolated_store.list_notes("u1", "项链")]
    assert titles == ["项链方案"]


# ---------------------------------------------------------------- pin

def test_new_note_is_not_pinned(isolated_store):
    n = isolated_store.create_note("u1", "笔记A", "正文")
    assert n["pinned"] == 0


def test_set_pinned_persists(isolated_store):
    n = isolated_store.create_note("u1", "笔记A", "正文")
    updated = isolated_store.set_pinned("u1", n["id"], True)
    assert updated["pinned"] == 1
    assert isolated_store.get_note("u1", n["id"])["pinned"] == 1


def test_pinned_notes_list_first_regardless_of_updated_at(isolated_store):
    isolated_store.create_note("u1", "旧的但置顶", "正文")
    older = isolated_store.list_notes("u1")[0]
    isolated_store.create_note("u1", "新的但没置顶", "正文")
    isolated_store.set_pinned("u1", older["id"], True)
    titles = [n["title"] for n in isolated_store.list_notes("u1")]
    assert titles[0] == "旧的但置顶"


def test_set_pinned_wrong_user_is_noop(isolated_store):
    n = isolated_store.create_note("u1", "笔记A", "正文")
    assert isolated_store.set_pinned("u2", n["id"], True) is None
    assert isolated_store.get_note("u1", n["id"])["pinned"] == 0


def test_搜索里的百分号和下划线不是通配符(tmp_path, monkeypatch):
    """第 255 轮实测：搜「_」「%」全库都命中。"""
    from app.database import store
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    store.create_note("u", "有百分号", "涨了 50%")
    store.create_note("u", "没有", "纯文字")
    store.create_note("u", "下划线_x", "a_b")
    assert [n["title"] for n in store.list_notes("u", "%")] == ["有百分号"]
    assert [n["title"] for n in store.list_notes("u", "_")] == ["下划线_x"]
    assert [n["title"] for n in store.list_notes("u", "a_b")] == ["下划线_x"]
    assert [n["title"] for n in store.list_notes("u", "\\")] == []


def test_轻量列表_不带全文_正文命中带片段(tmp_path, monkeypatch):
    """第 257 轮：⌘K / [[ 每敲一个字拉一次列表，带全文的在 413 篇库上一次 580KB。"""
    from fastapi.testclient import TestClient
    from app.database import store
    from app.main import app
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        c.post("/api/notes", json={"title": "创业一年回顾", "content": "# 创业一年回顾\n\n" + "正文" * 500})
        c.post("/api/notes", json={"title": "harness 测试", "content": "前面很长" * 30 + "矩阵不能只保留4月16日EVT" + "后面" * 20})
        c.post("/api/notes", json={"title": "空壳", "content": ""})
        page = c.get("/api/notes/brief").json(); rows = page["notes"]
        assert page["total"] == 3 and all("content" not in r for r in rows) and max(len(r["preview"]) for r in rows) <= 80
        assert {r["title"]: r["has_body"] for r in rows} == {"创业一年回顾": True, "harness 测试": True, "空壳": False}
        hits = c.get("/api/notes/brief", params={"q": "EVT"}).json()["notes"]
        assert [r["title"] for r in hits] == ["harness 测试"] and hits[0]["snippet"]["hit"] == "EVT"
        assert len(hits[0]["snippet"]["before"].lstrip("…")) <= 18
        by_title = c.get("/api/notes/brief", params={"q": "创业"}).json()["notes"]
        assert by_title[0]["snippet"] is None, "标题命中的不用给片段"
