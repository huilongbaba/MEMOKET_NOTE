"""笔记搜索：store.list_notes() 的 q 参数。

    cd backend && python -m pytest tests/test_notes_search.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store  # noqa: E402


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
