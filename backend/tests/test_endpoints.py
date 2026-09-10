"""端点这一层：路由挂没挂上、状态转移对不对、权限隔离在不在。

**这是仓库里第一批端点级测试。** 之前只有 store 层和纯函数层有测试，
于是「store 函数是对的、端点是对的、但两者没接上」和「端点是对的、界面
上点不到」这两类缺陷，没有任何东西挡得住。这一轮就撞到三次：

  · `/api/harness/{id}/resume` 有后端有封装，没有组件调用——轮末暂停
    用户点不到；
  · `/api/writing-plan/{id}/abandon` 没人调，于是 `abandoned` 这个状态
    永远不会出现，而面板上「没有计划就显示表单」那个分支一直在等它；
  · 文件夹改名没人调，名字打错了只能删掉重建（现在文件夹就是笔记，改标题即可）。

所以这里测的是**从 HTTP 进去**：路由挂上了、参数对得上、状态真的变了。
不测模型相关的那些端点，它们要花真实调用，是 bench 的事。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import store# noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app

    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        yield c


def _parent(client, title="一棵子树"):
    """建一个「文件夹」= 建一篇笔记。

    树上没有文件夹这种东西了——有子节点的笔记就是文件夹，所以「新建文件夹」
    退化成「新建笔记」，「改文件夹名」退化成「改笔记标题」。
    """
    return client.post("/api/notes", json={"title": title}).json()


def _plan(parent_note_id, goal="目标", user="u1"):
    """直接建计划，**不走 /start**。

    `/api/writing-plan/start` 要打模型才能拆出分段——端点测试依赖真实模型
    就成了「模型在线时全绿、离线时全红」，而它想验的根本不是模型。第一版
    就是这么写的，跑出来 26 秒、而且换台机器就挂。
    """
    return store.create_plan(user, parent_note_id, goal)


# ---------------------------------------------------------------- 文件夹 ---


def test_子树的名字能改(client):
    """从前这是「文件夹改名」。树上它就是改笔记标题——少一套 CRUD。"""
    f = _parent(client, "打错的名字")
    r = client.put(f"/api/notes/{f['id']}", json={"title": "改好的名字",
                                                  "content": ""})
    assert r.status_code == 200
    assert client.get(f"/api/notes/{f['id']}").json()["title"] == "改好的名字"


def test_改不了别人的子树(client):
    f = _parent(client, "自己的")
    assert client.put(f"/api/notes/{f['id']}", json={"title": "自己改",
                                                     "content": ""}).status_code == 200
    r = client.put(f"/api/notes/{f['id']}", json={"title": "偷改", "content": ""},
                   headers={"X-User-Id": "someone-else"})
    assert r.status_code == 404
    assert client.get(f"/api/notes/{f['id']}").json()["title"] == "自己改"


def test_删掉一个节点连子树一起删(client):
    """**这条行为是有意改掉的。**

    从前删文件夹会把里面的笔记「取消归类」留下来。树上不能这么做：只删自己
    的话，孩子的 branch 指向一个不存在的父节点——它既不在树根也不在任何看得
    见的地方，是一篇用户再也找不到、却还在库里占着的笔记。
    """
    f = _parent(client)
    n = client.post("/api/notes", json={"title": "夹里的", "content": "正文",
                                        "parent_note_id": f["id"]}).json()
    r = client.delete(f"/api/notes/{f['id']}")
    assert r.status_code == 200
    assert set(r.json()["deleted"]) == {f["id"], n["id"]}
    assert client.get(f"/api/notes/{n['id']}").status_code == 404


def test_放弃计划之后能换个目标重开(client):
    """没有这条路的话，一个文件夹起过计划就再也换不掉——面板会一直显示那个
    旧目标。`abandoned` 这个状态只有这个端点能产生。"""
    f = _parent(client)
    _plan(f["id"], "第一个目标")
    assert client.get(f"/api/writing-plan?parent_note_id={f['id']}").json()["plan"]["status"] \
        == "active"

    assert client.post(f"/api/writing-plan/{f['id']}/abandon").status_code == 200
    # 放弃之后没有活跃计划了，前端那个「显示表单」的分支才走得到
    assert client.get(f"/api/writing-plan?parent_note_id={f['id']}").json()["plan"] is None

    _plan(f["id"], "换的第二个目标")
    assert client.get(f"/api/writing-plan?parent_note_id={f['id']}").json()["plan"]["goal"] \
        == "换的第二个目标"


def test_放弃计划不动已经写出来的笔记(client):
    """放弃的是这份计划，不是它的产出。"""
    f = _parent(client)
    _plan(f["id"])
    n = client.post("/api/notes", json={"title": "已经写好的一段", "content": "正文",
                                        "folder_id": f["id"]}).json()
    client.post(f"/api/writing-plan/{f['id']}/abandon")
    assert client.get(f"/api/notes/{n['id']}").json()["content"] == "正文"


def test_没有计划时放弃是404不是静默成功(client):
    f = _parent(client)
    assert client.post(f"/api/writing-plan/{f['id']}/abandon").status_code == 404


def test_放弃不了别人的计划(client):
    f = _parent(client)
    _plan(f["id"])
    # 先确认这条路径对**自己**是通的——不然下面那个 404 可能只是路径写错了，
    # 测出来的是「URL 不存在」而不是「不是你的东西」。
    mine = client.post(f"/api/writing-plan/{f['id']}/abandon")
    assert mine.status_code == 200

    _plan(f["id"], "再来一个")
    r = client.post(f"/api/writing-plan/{f['id']}/abandon",
                    headers={"X-User-Id": "u2"})
    assert r.status_code == 404
    # 而且真的没被放弃掉
    assert client.get(f"/api/writing-plan?parent_note_id={f['id']}").json()["plan"] is not None


# ------------------------------------------------------------------ 路由 ---


def test_删掉的端点真的不在了(client):
    """`/api/edit` 是一次性的修订建议机，已被「打磨」（同一套循环但有终点）
    和「逐轮我来定」（人在环内逐条挑）取代，整个删掉了。"""
    assert client.post("/api/edit", json={"content": "正文"}).status_code == 404


def test_每个路由前缀都挂上了(client):
    """挂路由是手写的一行，漏一行就是整块功能 404，而单测全绿。"""
    for path in ("/api/notes", "/api/tree", "/api/skills", "/api/profile",
                 "/api/memory/stats", "/api/kb/coverage", "/api/harness/paused",
                 "/api/ingest/jobs"):
        assert client.get(path).status_code == 200, f"{path} 没挂上"
