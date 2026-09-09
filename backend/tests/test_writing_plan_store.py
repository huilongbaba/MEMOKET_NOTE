"""无限续写 harness 的状态层：store.py 的 writing_plans/writing_sections。

    cd backend && python -m pytest tests/test_writing_plan_store.py -v
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


def test_create_plan_and_get_active_plan(isolated_store):
    plan = isolated_store.create_plan("u1", "f1", "写一份产品规划")
    active = isolated_store.get_active_plan("u1", "f1")
    assert active["id"] == plan["id"]
    assert active["status"] == "active"


def test_no_active_plan_returns_none(isolated_store):
    assert isolated_store.get_active_plan("u1", "no-such-folder") is None


def test_creating_a_new_plan_abandons_the_old_active_one(isolated_store):
    old = isolated_store.create_plan("u1", "f1", "旧目标")
    new = isolated_store.create_plan("u1", "f1", "新目标")

    active = isolated_store.get_active_plan("u1", "f1")
    assert active["id"] == new["id"]

    old_reloaded = isolated_store.get_plan("u1", old["id"])
    assert old_reloaded["status"] == "abandoned"


def test_plans_are_scoped_per_folder(isolated_store):
    isolated_store.create_plan("u1", "f1", "目标A")
    assert isolated_store.get_active_plan("u1", "f2") is None


def test_add_sections_assigns_sequential_idx(isolated_store):
    plan = isolated_store.create_plan("u1", "f1", "目标")
    sections = isolated_store.add_sections(plan["id"], ["第一段", "第二段", "第三段"])
    assert [s["idx"] for s in sections] == [0, 1, 2]
    assert [s["title"] for s in sections] == ["第一段", "第二段", "第三段"]
    assert all(s["status"] == "pending" for s in sections)


def test_add_sections_continues_idx_from_existing(isolated_store):
    plan = isolated_store.create_plan("u1", "f1", "目标")
    isolated_store.add_sections(plan["id"], ["第一段", "第二段"])
    more = isolated_store.add_sections(plan["id"], ["追加段"])
    assert more[0]["idx"] == 2


def test_list_sections_returns_them_in_order(isolated_store):
    plan = isolated_store.create_plan("u1", "f1", "目标")
    isolated_store.add_sections(plan["id"], ["C", "A", "B"])
    titles = [s["title"] for s in isolated_store.list_sections(plan["id"])]
    assert titles == ["C", "A", "B"]  # 插入顺序，不是字母序


def test_update_section_status_and_note_id(isolated_store):
    plan = isolated_store.create_plan("u1", "f1", "目标")
    section = isolated_store.add_sections(plan["id"], ["第一段"])[0]
    isolated_store.update_section(plan["id"], section["id"], status="in_progress", note_id="note-1")
    updated = isolated_store.list_sections(plan["id"])[0]
    assert updated["status"] == "in_progress"
    assert updated["note_id"] == "note-1"


def test_update_section_only_touches_given_fields(isolated_store):
    plan = isolated_store.create_plan("u1", "f1", "目标")
    section = isolated_store.add_sections(plan["id"], ["第一段"])[0]
    isolated_store.update_section(plan["id"], section["id"], note_id="note-1")
    isolated_store.update_section(plan["id"], section["id"], status="done")
    updated = isolated_store.list_sections(plan["id"])[0]
    assert updated["note_id"] == "note-1"  # 没被第二次调用覆盖掉
    assert updated["status"] == "done"


def test_update_section_rejects_unknown_column(isolated_store):
    plan = isolated_store.create_plan("u1", "f1", "目标")
    section = isolated_store.add_sections(plan["id"], ["第一段"])[0]
    with pytest.raises(ValueError):
        isolated_store.update_section(plan["id"], section["id"], user_id="hacked")


def test_set_plan_status(isolated_store):
    plan = isolated_store.create_plan("u1", "f1", "目标")
    isolated_store.set_plan_status("u1", plan["id"], "done")
    assert isolated_store.get_plan("u1", plan["id"])["status"] == "done"
    assert isolated_store.get_active_plan("u1", "f1") is None


def test_set_plan_doc_note(isolated_store):
    plan = isolated_store.create_plan("u1", "f1", "目标")
    isolated_store.set_plan_doc_note("u1", plan["id"], "note-abc")
    assert isolated_store.get_plan("u1", plan["id"])["doc_note_id"] == "note-abc"
