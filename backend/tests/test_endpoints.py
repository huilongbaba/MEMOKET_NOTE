"""端点这一层：路由挂没挂上、状态转移对不对、权限隔离在不在。

**这是仓库里第一批端点级测试。** 之前只有 store 层和纯函数层有测试，
于是「store 函数是对的、端点是对的、但两者没接上」和「端点是对的、界面
上点不到」这两类缺陷，没有任何东西挡得住。这一轮就撞到三次：

  · `/api/harness/{id}/resume` 有后端有封装，没有组件调用——轮末暂停
    用户点不到；
  · `/api/writing-plan/{id}/abandon` 没人调，于是 `abandoned` 这个状态
    永远不会出现，而面板上「没有计划就显示表单」那个分支一直在等它；
  · `/api/folders/{id}` 的改名没人调，文件夹名字打错了只能删掉重建。

所以这里测的是**从 HTTP 进去**：路由挂上了、参数对得上、状态真的变了。
不测模型相关的那些端点，它们要花真实调用，是 bench 的事。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app

    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        yield c


def _folder(client, name="文件夹"):
    return client.post("/api/folders", json={"name": name}).json()


def _plan(folder_id, goal="目标", user="u1"):
    """直接建计划，**不走 /start**。

    `/api/writing-plan/start` 要打模型才能拆出分段——端点测试依赖真实模型
    就成了「模型在线时全绿、离线时全红」，而它想验的根本不是模型。第一版
    就是这么写的，跑出来 26 秒、而且换台机器就挂。
    """
    return store.create_plan(user, folder_id, goal)


# ---------------------------------------------------------------- 文件夹 ---


def test_文件夹能改名(client):
    f = _folder(client, "打错的名字")
    r = client.put(f"/api/folders/{f['id']}", json={"name": "改好的名字"})
    assert r.status_code == 200 and r.json()["name"] == "改好的名字"
    assert [x["name"] for x in client.get("/api/folders").json()] == ["改好的名字"]


def test_改名不能改成空的(client):
    f = _folder(client)
    assert client.put(f"/api/folders/{f['id']}", json={"name": "   "}).status_code == 400


def test_改不了别人的文件夹(client):
    """两头都要断言：只测「别人得 404」的话，一个「谁都改不了」的 bug 也
    满足它。第一版就是这么写的，反向验证时把 user 换成写死的别人，测试
    照样绿。"""
    f = _folder(client)
    assert client.put(f"/api/folders/{f['id']}", json={"name": "自己改"}).status_code == 200

    r = client.put(f"/api/folders/{f['id']}", json={"name": "偷改"},
                   headers={"X-User-Id": "u2"})
    assert r.status_code == 404
    assert client.get("/api/folders").json()[0]["name"] == "自己改"


def test_删掉文件夹笔记不跟着删(client):
    f = _folder(client)
    n = client.post("/api/notes", json={"title": "t", "content": "c",
                                        "folder_id": f["id"]}).json()
    client.delete(f"/api/folders/{f['id']}")
    assert client.get(f"/api/notes/{n['id']}").json()["folder_id"] is None


# ---------------------------------------------------------------- 写作计划 ---


def test_放弃计划之后能换个目标重开(client):
    """没有这条路的话，一个文件夹起过计划就再也换不掉——面板会一直显示那个
    旧目标。`abandoned` 这个状态只有这个端点能产生。"""
    f = _folder(client)
    _plan(f["id"], "第一个目标")
    assert client.get(f"/api/writing-plan?folder_id={f['id']}").json()["plan"]["status"] \
        == "active"

    assert client.post(f"/api/writing-plan/{f['id']}/abandon").status_code == 200
    # 放弃之后没有活跃计划了，前端那个「显示表单」的分支才走得到
    assert client.get(f"/api/writing-plan?folder_id={f['id']}").json()["plan"] is None

    _plan(f["id"], "换的第二个目标")
    assert client.get(f"/api/writing-plan?folder_id={f['id']}").json()["plan"]["goal"] \
        == "换的第二个目标"


def test_放弃计划不动已经写出来的笔记(client):
    """放弃的是这份计划，不是它的产出。"""
    f = _folder(client)
    _plan(f["id"])
    n = client.post("/api/notes", json={"title": "已经写好的一段", "content": "正文",
                                        "folder_id": f["id"]}).json()
    client.post(f"/api/writing-plan/{f['id']}/abandon")
    assert client.get(f"/api/notes/{n['id']}").json()["content"] == "正文"


def test_没有计划时放弃是404不是静默成功(client):
    f = _folder(client)
    assert client.post(f"/api/writing-plan/{f['id']}/abandon").status_code == 404


def test_放弃不了别人的计划(client):
    f = _folder(client)
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
    assert client.get(f"/api/writing-plan?folder_id={f['id']}").json()["plan"] is not None


# ------------------------------------------------------------------ 路由 ---


def test_删掉的端点真的不在了(client):
    """`/api/edit` 是一次性的修订建议机，已被「打磨」（同一套循环但有终点）
    和「逐轮我来定」（人在环内逐条挑）取代，整个删掉了。"""
    assert client.post("/api/edit", json={"content": "正文"}).status_code == 404


def test_每个路由前缀都挂上了(client):
    """挂路由是手写的一行，漏一行就是整块功能 404，而单测全绿。"""
    for path in ("/api/notes", "/api/folders", "/api/skills", "/api/profile",
                 "/api/memory/stats", "/api/kb/coverage", "/api/harness/paused",
                 "/api/ingest/jobs"):
        assert client.get(path).status_code == 200, f"{path} 没挂上"
