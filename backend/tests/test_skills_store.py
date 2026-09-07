"""Skill 系统：store.py 的 CRUD/开关/排序/默认技能播种，以及
compose_system() 的拼接逻辑。

    cd backend && python -m pytest tests/test_skills_store.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import prompts, store  # noqa: E402


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    return store


def test_list_skills_seeds_defaults_on_first_access(isolated_store):
    skills = isolated_store.list_skills("u1")
    assert len(skills) == len(prompts.DEFAULT_SKILLS)
    assert all(s["builtin"] for s in skills)
    assert all(s["enabled"] for s in skills)


def test_seeded_defaults_are_scoped_per_user(isolated_store):
    isolated_store.list_skills("u1")
    assert isolated_store.list_skills("u2") != []  # 也会种一份，但互相独立
    isolated_store.create_skill("u1", "只属于u1", "", ["verify"], "内容")
    assert len(isolated_store.list_skills("u1")) == len(prompts.DEFAULT_SKILLS) + 1
    assert len(isolated_store.list_skills("u2")) == len(prompts.DEFAULT_SKILLS)


def test_seeded_defaults_preserve_scopes_from_prompts_module(isolated_store):
    skills = isolated_store.list_skills("u1")
    by_name = {s["name"]: s for s in skills}
    for expected in prompts.DEFAULT_SKILLS:
        assert by_name[expected["name"]]["scopes"] == expected["scopes"]


def test_every_skill_scope_has_at_least_one_default_skill():
    covered = {scope for sk in prompts.DEFAULT_SKILLS for scope in sk["scopes"]}
    assert set(prompts.SKILL_SCOPES) <= covered


def test_incremental_seeding_only_adds_missing_keys(isolated_store, monkeypatch):
    """核心行为：老用户已经种过一部分默认技能（比如软件升级前只有 5 条），
    DEFAULT_SKILLS 后来加了新条目——下次 list_skills() 要只补新增的那些，
    不能把已经种过的重新插一份（会重复），也不能因为已经有 skill 了就
    跳过全部新增。"""
    original = prompts.DEFAULT_SKILLS
    monkeypatch.setattr(prompts, "DEFAULT_SKILLS", original[:2])
    first = isolated_store.list_skills("u1")
    assert len(first) == 2

    monkeypatch.setattr(prompts, "DEFAULT_SKILLS", original)
    second = isolated_store.list_skills("u1")
    assert len(second) == len(original)
    # 前两条没有被重复插入——按 name 数量各只有一份
    names = [s["name"] for s in second]
    assert names.count(original[0]["name"]) == 1
    assert names.count(original[1]["name"]) == 1


def test_pre_default_key_rows_do_not_get_duplicated(isolated_store):
    """真实炸过的 bug：default_key 这一列是后加的，在它存在之前已经种过
    默认技能的账号（default_key 全是空字符串）第一次跑新代码时，如果不
    做 name 匹配回填，会把所有默认技能重新插一遍——因为"有没有 key"的
    判重查不到旧行。模拟这个场景：手工插入一条 builtin=1、default_key=''
    的行，name 精确匹配 DEFAULT_SKILLS 里的一条，list_skills() 之后不能
    出现两条同名的。"""
    victim = prompts.DEFAULT_SKILLS[0]
    with isolated_store.connect() as c:
        c.execute(
            "INSERT INTO skills (id,user_id,name,description,scopes,content,enabled,idx,builtin,default_key,created_at,updated_at) "
            "VALUES ('legacy-row','u1',?,?,?,?,1,0,1,'',?,?)",
            (victim["name"], victim["description"], "[]", victim["content"], "t", "t"))

    skills = isolated_store.list_skills("u1")
    names = [s["name"] for s in skills]
    assert names.count(victim["name"]) == 1
    # 旧行本身还在（用回填后的 key 找到的是同一条，不是新插的）
    assert any(s["id"] == "legacy-row" for s in skills)


def test_deleted_default_skill_gets_reseeded_on_next_access(isolated_store):
    """已知的取舍：删掉一条默认技能（不是关掉）之后，下次访问会被重新种
    回来——这是刻意的（跟"清空全部会重新播种"是同一个逻辑，用户想彻底
    不要应该用关闭而不是删除），不是 bug。"""
    skills = isolated_store.list_skills("u1")
    victim = skills[0]
    isolated_store.delete_skill("u1", victim["id"])
    reloaded = isolated_store.list_skills("u1")
    assert victim["name"] in [s["name"] for s in reloaded]


def test_create_skill_assigns_sequential_idx_after_seeded_defaults(isolated_store):
    isolated_store.list_skills("u1")  # 触发播种
    created = isolated_store.create_skill("u1", "自定义技能", "desc", ["rewrite"], "内容")
    assert created["idx"] == len(prompts.DEFAULT_SKILLS)
    assert created["builtin"] is False


def test_enabled_skills_for_scope_filters_by_scope_and_enabled(isolated_store):
    a = isolated_store.create_skill("u1", "A", "", ["verify"], "内容A")
    isolated_store.create_skill("u1", "B", "", ["rewrite"], "内容B")
    c = isolated_store.create_skill("u1", "C", "", ["verify"], "内容C", enabled=False)

    hits = isolated_store.enabled_skills_for_scope("u1", "verify")
    ids = [s["id"] for s in hits]
    assert a["id"] in ids
    assert c["id"] not in ids  # 关掉的不出现
    assert all("rewrite" not in s["scopes"] or "verify" in s["scopes"] for s in hits)


def test_enabled_skills_for_scope_respects_idx_order(isolated_store):
    isolated_store.create_skill("u1", "先建的", "", ["verify"], "内容1")
    isolated_store.create_skill("u1", "后建的", "", ["verify"], "内容2")
    names = [s["name"] for s in isolated_store.enabled_skills_for_scope("u1", "verify")]
    assert names.index("先建的") < names.index("后建的")


def test_toggle_via_update_skill(isolated_store):
    sk = isolated_store.create_skill("u1", "A", "", ["verify"], "内容")
    assert sk["enabled"] is True
    updated = isolated_store.update_skill("u1", sk["id"], enabled=0)
    assert updated["enabled"] is False
    # "verify" scope 现在也有默认技能，所以断言"这一条不再出现"，不是
    # "整个 scope 空了"（那要求先把默认技能也关掉，不是这个测试关心的）。
    ids = [s["id"] for s in isolated_store.enabled_skills_for_scope("u1", "verify")]
    assert sk["id"] not in ids


def test_update_skill_only_touches_given_fields(isolated_store):
    sk = isolated_store.create_skill("u1", "A", "原描述", ["verify"], "原内容")
    isolated_store.update_skill("u1", sk["id"], content="新内容")
    updated = isolated_store.get_skill("u1", sk["id"])
    assert updated["content"] == "新内容"
    assert updated["description"] == "原描述"  # 没被覆盖


def test_update_skill_rejects_unknown_column(isolated_store):
    sk = isolated_store.create_skill("u1", "A", "", ["verify"], "内容")
    with pytest.raises(ValueError):
        isolated_store.update_skill("u1", sk["id"], created_at="hacked")


def test_delete_skill(isolated_store):
    sk = isolated_store.create_skill("u1", "A", "", ["verify"], "内容")
    assert isolated_store.delete_skill("u1", sk["id"]) is True
    assert isolated_store.get_skill("u1", sk["id"]) is None


def test_delete_missing_skill_returns_false(isolated_store):
    assert isolated_store.delete_skill("u1", "does-not-exist") is False


def test_reorder_skills_updates_idx(isolated_store):
    a = isolated_store.create_skill("u1", "A", "", ["verify"], "内容")
    b = isolated_store.create_skill("u1", "B", "", ["verify"], "内容")
    # reorder_skills 只挪给定的这些 id，其他（比如默认技能）idx 不变——
    # 把 a/b 排到最前面，断言相对顺序，不假设 scope 里只有这两条。
    all_ids = [s["id"] for s in isolated_store.list_skills("u1")]
    other_ids = [i for i in all_ids if i not in (a["id"], b["id"])]
    isolated_store.reorder_skills("u1", [b["id"], a["id"], *other_ids])
    ordered_ids = [s["id"] for s in isolated_store.enabled_skills_for_scope("u1", "verify")]
    assert ordered_ids.index(b["id"]) < ordered_ids.index(a["id"])


# ---------------------------------------------------------------- compose_system

def test_compose_system_returns_base_unchanged_when_no_skills():
    assert prompts.compose_system("基础规则", []) == "基础规则"


def test_compose_system_appends_skill_content_in_order():
    skills = [
        {"name": "技能一", "content": "第一条指令"},
        {"name": "技能二", "content": "第二条指令"},
    ]
    text = prompts.compose_system("基础规则", skills)
    assert text.startswith("基础规则")
    assert text.index("第一条指令") < text.index("第二条指令")
    assert "技能一" in text
    assert "技能二" in text
