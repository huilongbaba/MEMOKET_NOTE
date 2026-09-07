"""文件夹：store.py 的文件夹 CRUD + 笔记归属，单层不支持嵌套。

    cd backend && python -m pytest tests/test_folders.py -v
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


def test_create_and_list_folders(isolated_store):
    isolated_store.create_folder("u1", "项目A")
    isolated_store.create_folder("u1", "项目B")
    names = [f["name"] for f in isolated_store.list_folders("u1")]
    assert names == ["项目A", "项目B"]


def test_folders_are_scoped_per_user(isolated_store):
    isolated_store.create_folder("u1", "只属于u1")
    assert isolated_store.list_folders("u2") == []


def test_rename_folder(isolated_store):
    folder = isolated_store.create_folder("u1", "旧名字")
    updated = isolated_store.rename_folder("u1", folder["id"], "新名字")
    assert updated["name"] == "新名字"
    assert isolated_store.list_folders("u1")[0]["name"] == "新名字"


def test_rename_missing_folder_returns_none(isolated_store):
    assert isolated_store.rename_folder("u1", "does-not-exist", "x") is None


def test_new_note_defaults_to_no_folder(isolated_store):
    note = isolated_store.create_note("u1", "标题", "正文")
    assert note["folder_id"] is None


def test_create_note_directly_in_a_folder(isolated_store):
    folder = isolated_store.create_folder("u1", "项目A")
    note = isolated_store.create_note("u1", "标题", "正文", folder_id=folder["id"])
    assert note["folder_id"] == folder["id"]


def test_set_note_folder_moves_note(isolated_store):
    folder = isolated_store.create_folder("u1", "项目A")
    note = isolated_store.create_note("u1", "标题", "正文")
    updated = isolated_store.set_note_folder("u1", note["id"], folder["id"])
    assert updated["folder_id"] == folder["id"]


def test_set_note_folder_to_none_uncategorizes(isolated_store):
    folder = isolated_store.create_folder("u1", "项目A")
    note = isolated_store.create_note("u1", "标题", "正文", folder_id=folder["id"])
    updated = isolated_store.set_note_folder("u1", note["id"], None)
    assert updated["folder_id"] is None


def test_delete_folder_uncategorizes_its_notes_instead_of_deleting_them(isolated_store):
    folder = isolated_store.create_folder("u1", "项目A")
    note = isolated_store.create_note("u1", "标题", "正文", folder_id=folder["id"])
    assert isolated_store.delete_folder("u1", folder["id"]) is True
    survivor = isolated_store.get_note("u1", note["id"])
    assert survivor is not None
    assert survivor["folder_id"] is None


def test_delete_missing_folder_returns_false(isolated_store):
    assert isolated_store.delete_folder("u1", "does-not-exist") is False


def test_notes_in_folder_excludes_given_note_and_other_folders(isolated_store):
    folder = isolated_store.create_folder("u1", "项目A")
    other_folder = isolated_store.create_folder("u1", "项目B")
    current = isolated_store.create_note("u1", "当前笔记", "正文", folder_id=folder["id"])
    sibling = isolated_store.create_note("u1", "同文件夹笔记", "正文", folder_id=folder["id"])
    isolated_store.create_note("u1", "别的文件夹笔记", "正文", folder_id=other_folder["id"])

    siblings = isolated_store.notes_in_folder("u1", folder["id"], exclude_id=current["id"])
    ids = [n["id"] for n in siblings]
    assert ids == [sibling["id"]]


def test_notes_in_folder_respects_limit(isolated_store):
    folder = isolated_store.create_folder("u1", "项目A")
    for i in range(8):
        isolated_store.create_note("u1", f"笔记{i}", "正文", folder_id=folder["id"])
    siblings = isolated_store.notes_in_folder("u1", folder["id"], limit=3)
    assert len(siblings) == 3
