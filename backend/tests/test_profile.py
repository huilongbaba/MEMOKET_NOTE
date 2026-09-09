"""个人偏好：store.py 的 CRUD + prompts.py 怎么把它揉进三件套的 prompt。

    cd backend && python -m pytest tests/test_profile.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.harness import prompts
from app.database import store# noqa: E402


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    return store


# ---------------------------------------------------------------- store

def test_add_and_list_profile_entry(isolated_store):
    isolated_store.add_profile_entry("u1", "喜欢简洁的语言")
    entries = isolated_store.list_profile("u1")
    assert len(entries) == 1
    assert entries[0]["text"] == "喜欢简洁的语言"


def test_list_profile_is_scoped_per_user(isolated_store):
    isolated_store.add_profile_entry("u1", "u1 的偏好")
    isolated_store.add_profile_entry("u2", "u2 的偏好")
    assert [e["text"] for e in isolated_store.list_profile("u1")] == ["u1 的偏好"]
    assert [e["text"] for e in isolated_store.list_profile("u2")] == ["u2 的偏好"]


def test_list_profile_orders_newest_first(isolated_store):
    isolated_store.add_profile_entry("u1", "first")
    isolated_store.add_profile_entry("u1", "second")
    texts = [e["text"] for e in isolated_store.list_profile("u1")]
    assert texts == ["second", "first"]


def test_delete_profile_entry(isolated_store):
    entry = isolated_store.add_profile_entry("u1", "temp")
    assert isolated_store.delete_profile_entry("u1", entry["id"]) is True
    assert isolated_store.list_profile("u1") == []


def test_delete_profile_entry_wrong_user_is_noop(isolated_store):
    """一个用户不能删别人的偏好——just in case a client sends someone else's id."""
    entry = isolated_store.add_profile_entry("u1", "temp")
    assert isolated_store.delete_profile_entry("u2", entry["id"]) is False
    assert len(isolated_store.list_profile("u1")) == 1


def test_delete_unknown_entry_returns_false(isolated_store):
    assert isolated_store.delete_profile_entry("u1", "does-not-exist") is False


# ---------------------------------------------------------------- prompts

def test_skeleton_user_includes_profile_block_when_present():
    out = prompts.skeleton_user("标题", "正文", ["喜欢简洁"])
    assert "【个人偏好】" in out
    assert "- 喜欢简洁" in out


def test_skeleton_user_omits_profile_block_when_empty():
    out = prompts.skeleton_user("标题", "正文", [])
    assert "【个人偏好】" not in out


def test_edit_user_includes_profile_block_when_present():
    out = prompts.edit_user("", [], "正文", [], ["喜欢简洁"])
    assert "【个人偏好】" in out


def test_magic_tap_user_includes_profile_block_when_present():
    out = prompts.magic_tap_user("", [], "正文", [], ["喜欢简洁"])
    assert "【个人偏好】" in out


def test_magic_tap_user_omits_profile_block_when_empty():
    out = prompts.magic_tap_user("", [], "正文", [], [])
    assert "【个人偏好】" not in out


def test_edit_user_includes_spine_and_beats_block_when_present():
    out = prompts.edit_user("核心张力", ["建立处境"], "正文", [], [])
    assert "【核心张力】" in out
    assert "核心张力" in out
    assert "【结构节拍】" in out
    assert "- 建立处境" in out


def test_edit_user_omits_spine_beats_block_when_empty():
    out = prompts.edit_user("", [], "正文", [], [])
    assert "【核心张力】" not in out
    assert "【结构节拍】" not in out
