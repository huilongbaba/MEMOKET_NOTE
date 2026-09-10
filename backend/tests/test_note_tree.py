"""笔记树：branches 表、克隆、成环防护，以及「文件夹变成笔记」那次迁移。

照 Trilium 的模型：**notes 表里没有父子关系**，树的边全在 branches。一个
笔记有多条 branch 就是「克隆」——同时长在树的多个位置，改一处处处都变。
「文件夹」不再是一种东西：任何有子节点的笔记就是文件夹。
"""

from __future__ import annotations

import sqlite3

import pytest

from app.database import store


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    return store


def _ids(rows):
    return [r["note_id"] for r in rows]


# -------------------------------------------------------------- 挂与摘 ---

def test_新建的笔记挂在树根(db):
    n = db.create_note("u", "标题", "正文")
    db.attach("u", n["id"])
    (row,) = [r for r in db.tree("u") if r["note_id"] == n["id"]]
    assert row["parent_note_id"] == store.ROOT_ID
    assert row["child_count"] == 0 and row["branch_count"] == 1


def test_有子节点的笔记就是文件夹(db):
    parent = db.create_note("u", "父", "")
    child = db.create_note("u", "子", "")
    db.attach("u", parent["id"])
    db.attach("u", child["id"], parent["id"])
    (p,) = [r for r in db.tree("u") if r["note_id"] == parent["id"]]
    assert p["child_count"] == 1, "没有单独的『文件夹』类型，有孩子就是文件夹"


def test_同一个位置不会挂两次(db):
    n = db.create_note("u", "标题", "")
    a = db.attach("u", n["id"])
    b = db.attach("u", n["id"])
    assert a["id"] == b["id"], "同一对 (笔记, 父节点) 只能有一条 branch"


def test_克隆之后同一篇笔记长在两个地方(db):
    a = db.create_note("u", "甲", "")
    b = db.create_note("u", "乙", "")
    n = db.create_note("u", "被克隆的", "共享的正文")
    for x in (a, b):
        db.attach("u", x["id"])
    db.attach("u", n["id"], a["id"])
    db.attach("u", n["id"], b["id"])

    rows = [r for r in db.tree("u") if r["note_id"] == n["id"]]
    assert len(rows) == 2
    assert {r["parent_note_id"] for r in rows} == {a["id"], b["id"]}
    assert all(r["branch_count"] == 2 for r in rows)

    # 改一处，两处都变——因为本来就是同一篇
    db.update_note("u", n["id"], "改过的标题", "改过的正文")
    assert all(r["title"] == "改过的标题"
               for r in db.tree("u") if r["note_id"] == n["id"])


def test_最后一条branch不给摘(db):
    """摘掉之后笔记就不在树上的任何位置了，用户再也找不到它，而它还在库里
    占着——那不是删除，是丢失。"""
    n = db.create_note("u", "标题", "")
    db.attach("u", n["id"])
    assert db.detach("u", n["id"], store.ROOT_ID) is False
    assert len(db.tree("u")) == 1


def test_克隆之后可以摘掉其中一条(db):
    a = db.create_note("u", "甲", "")
    db.attach("u", a["id"])
    n = db.create_note("u", "被克隆的", "")
    db.attach("u", n["id"])
    db.attach("u", n["id"], a["id"])
    assert db.detach("u", n["id"], a["id"]) is True
    assert len([r for r in db.tree("u") if r["note_id"] == n["id"]]) == 1


# ---------------------------------------------------------------- 移动 ---

def test_移动到另一个父节点下(db):
    a = db.create_note("u", "甲", "")
    b = db.create_note("u", "乙", "")
    n = db.create_note("u", "笔记", "")
    for x in (a, b):
        db.attach("u", x["id"])
    db.attach("u", n["id"], a["id"])
    assert db.move_branch("u", n["id"], a["id"], b["id"]) is True
    (row,) = [r for r in db.tree("u") if r["note_id"] == n["id"]]
    assert row["parent_note_id"] == b["id"]


def test_不许把节点移进自己的子树(db):
    """成环之后任何一次深度遍历（渲染树、算路径、删子树）都会无限转下去,
    症状是界面直接卡死，不是报错。"""
    top = db.create_note("u", "上", "")
    mid = db.create_note("u", "中", "")
    bottom = db.create_note("u", "下", "")
    db.attach("u", top["id"])
    db.attach("u", mid["id"], top["id"])
    db.attach("u", bottom["id"], mid["id"])
    assert db.move_branch("u", top["id"], store.ROOT_ID, bottom["id"]) is False
    assert db.move_branch("u", top["id"], store.ROOT_ID, top["id"]) is False
    # 树还是好的
    assert len(db.note_paths("u", bottom["id"])) == 1


def test_移到一个已经有它的父节点下就等于摘掉旧位置(db):
    a = db.create_note("u", "甲", "")
    b = db.create_note("u", "乙", "")
    n = db.create_note("u", "笔记", "")
    for x in (a, b):
        db.attach("u", x["id"])
    db.attach("u", n["id"], a["id"])
    db.attach("u", n["id"], b["id"])
    assert db.move_branch("u", n["id"], a["id"], b["id"]) is True
    rows = [r for r in db.tree("u") if r["note_id"] == n["id"]]
    assert len(rows) == 1 and rows[0]["parent_note_id"] == b["id"]


# ---------------------------------------------------------------- 路径 ---

def test_路径从根算到自己(db):
    a = db.create_note("u", "甲", "")
    b = db.create_note("u", "乙", "")
    db.attach("u", a["id"])
    db.attach("u", b["id"], a["id"])
    assert db.note_paths("u", b["id"]) == [[a["id"], b["id"]]]


def test_克隆之后路径不止一条(db):
    """「它在哪」没有唯一答案——面包屑要显示的是用户从哪条路径点进来的。"""
    a = db.create_note("u", "甲", "")
    b = db.create_note("u", "乙", "")
    n = db.create_note("u", "被克隆的", "")
    for x in (a, b):
        db.attach("u", x["id"])
    db.attach("u", n["id"], a["id"])
    db.attach("u", n["id"], b["id"])
    paths = db.note_paths("u", n["id"])
    assert len(paths) == 2
    assert sorted(p[0] for p in paths) == sorted([a["id"], b["id"]])
    assert all(p[-1] == n["id"] for p in paths)


# ---------------------------------------------------------------- 展开 ---

def test_展开状态存在库里(db):
    """刷新一次就全收起来的树，在几十个节点之后就没法用了。"""
    a = db.create_note("u", "甲", "")
    db.attach("u", a["id"])
    db.set_expanded("u", a["id"], store.ROOT_ID, True)
    (row,) = [r for r in db.tree("u") if r["note_id"] == a["id"]]
    assert row["is_expanded"] == 1


# ---------------------------------------------------------------- 迁移 ---

def test_老库的文件夹会变成笔记并挂好子节点(tmp_path, monkeypatch):
    """**旧文件夹的 id 直接当新笔记的 id。** writing_plans 的 folder_id、
    前端记着的「当前文件夹」全都还指向同一个 id，不用跟着改一遍。"""
    dbfile = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(dbfile)
    conn.executescript("""
        CREATE TABLE notes (id TEXT PRIMARY KEY, user_id TEXT, title TEXT,
            content TEXT, pinned INTEGER DEFAULT 0, folder_id TEXT,
            created_at TEXT, updated_at TEXT);
        CREATE TABLE folders (id TEXT PRIMARY KEY, user_id TEXT, name TEXT,
            created_at TEXT);
        INSERT INTO folders VALUES ('f1','u','项目 A','t');
        INSERT INTO notes VALUES ('n1','u','夹里的','正文',0,'f1','t','t');
        INSERT INTO notes VALUES ('n2','u','散着的','正文',0,NULL,'t','t');
    """)
    conn.commit(); conn.close()

    monkeypatch.setattr(store, "_db_path", lambda: dbfile)
    rows = {r["note_id"]: r for r in store.tree("u")}

    assert "f1" in rows, "文件夹没变成笔记"
    assert rows["f1"]["title"] == "项目 A"
    assert rows["f1"]["parent_note_id"] == store.ROOT_ID
    assert rows["f1"]["child_count"] == 1
    assert rows["n1"]["parent_note_id"] == "f1", "夹里的笔记没挂到它下面"
    assert rows["n2"]["parent_note_id"] == store.ROOT_ID


def test_迁移只跑一次(tmp_path, monkeypatch):
    """搬数据不是补列，跑第二遍会把已经搬好的再搬一次。"""
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    n = store.create_note("u", "标题", "")
    store.attach("u", n["id"])
    before = len(store.tree("u"))
    for _ in range(5):
        store.connect()          # 每次连接都会走一遍迁移入口
    assert len(store.tree("u")) == before
