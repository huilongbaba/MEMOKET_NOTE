"""笔记 × 知识库的双向链接。

设计见 `docs/kb-fusion-design.md`。核心是一句话：**笔记是事实的来源，事实是
笔记的依据**——这个关系是双向的，而反查（哪些笔记用了这条事实）回答的是一个
真问题：这条事实还活着吗、改了它会影响谁。没有反查，知识库就是个只进不出的
仓库。
"""

from __future__ import annotations

import pytest

from app.database import store


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    return store


# ---------------------------------------------------------------- 识别 ---

def test_从正文里认出引用(db):
    ids = db.cited_fact_ids("据 [terrence-1872-5F8] 和 [terrence-99-AB] 所述")
    assert ids == ["terrence-1872-5F8", "terrence-99-AB"]


def test_同一条引用多次只算一次(db):
    assert db.cited_fact_ids("[a-1-A] 又 [a-1-A]") == ["a-1-A"]


def test_普通方括号不算引用(db):
    """认多了的代价：反查结果里混进一堆不存在的「事实」，整张表不可信。"""
    assert db.cited_fact_ids("[TODO] [注释] [2026-06] [标题](http://x)") == []


# ------------------------------------------------------------ 双向链接 ---

def test_保存笔记时自动重建引用(db):
    n = db.create_note("u", "标题", "起草中")
    db.update_note("u", n["id"], "标题", "据 [terrence-1872-5F8] 所述。")
    assert [x["id"] for x in db.notes_citing("u", "terrence-1872-5F8")] == [n["id"]]


def test_删掉引用之后反查就没有它了(db):
    """**整篇替换而不是增量。** 用户删掉一句话就等于撤销了那条引用；增量更新
    会把删掉的引用永远留在表里，那种「幽灵引用」会让反查越来越不可信。"""
    n = db.create_note("u", "标题", "")
    db.update_note("u", n["id"], "标题", "据 [a-1-A] 和 [b-2-B] 所述。")
    assert len(db.notes_citing("u", "a-1-A")) == 1
    db.update_note("u", n["id"], "标题", "只剩 [b-2-B] 了。")
    assert db.notes_citing("u", "a-1-A") == []
    assert len(db.notes_citing("u", "b-2-B")) == 1


def test_反查能拿到多篇笔记(db):
    """一条事实被好几篇引用，正是「改了它会影响谁」要回答的情况。"""
    a = db.create_note("u", "甲", "见 [f-1-A]")
    b = db.create_note("u", "乙", "也见 [f-1-A]")
    db.update_note("u", a["id"], "甲", "见 [f-1-A]")
    db.update_note("u", b["id"], "乙", "也见 [f-1-A]")
    got = {x["id"] for x in db.notes_citing("u", "f-1-A")}
    assert got == {a["id"], b["id"]}


def test_反查按用户隔离(db):
    a = db.create_note("u1", "甲", "")
    db.update_note("u1", a["id"], "甲", "见 [f-1-A]")
    b = db.create_note("u2", "乙", "")
    db.update_note("u2", b["id"], "乙", "见 [f-1-A]")
    assert [x["id"] for x in db.notes_citing("u1", "f-1-A")] == [a["id"]]


# ------------------------------------------------------------ 树上可见 ---

def test_树上带出引用数(db):
    """一眼看出哪些笔记「有据可依」、哪些还只是草稿。"""
    n = db.create_note("u", "标题", "")
    db.update_note("u", n["id"], "标题", "[a-1-A] [b-2-B] [c-3-C]")
    (row,) = [r for r in db.tree("u") if r["note_id"] == n["id"]]
    assert row["cite_count"] == 3


def test_树上带出摄入标记(db):
    n = db.create_note("u", "标题", "正文")
    assert [r for r in db.tree("u") if r["note_id"] == n["id"]][0]["ingested_at"] == ""
    db.mark_ingested("u", n["id"])
    assert [r for r in db.tree("u") if r["note_id"] == n["id"]][0]["ingested_at"] != ""


def test_引用计数一次查完(db):
    """树上每个节点问一次的话，几百个节点就是几百次查询。"""
    a = db.create_note("u", "甲", "")
    b = db.create_note("u", "乙", "")
    db.update_note("u", a["id"], "甲", "[f-1-A]")
    db.update_note("u", b["id"], "乙", "[f-1-A] [g-2-B]")
    counts = db.citation_counts("u")
    assert counts == {a["id"]: 1, b["id"]: 2}


def test_删掉笔记之后反查不该再返回它(db):
    """引用表是靠 JOIN notes 出结果的，笔记没了这条引用自然就不该出现——
    否则反查会指向一篇打不开的笔记。"""
    n = db.create_note("u", "标题", "")
    db.update_note("u", n["id"], "标题", "[f-1-A]")
    db.delete_note("u", n["id"])
    assert db.notes_citing("u", "f-1-A") == []
