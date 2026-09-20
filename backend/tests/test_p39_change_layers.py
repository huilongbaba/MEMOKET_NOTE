"""P39（`docs/TRACELOG-product.md` P39 节）：**待处置的改动层落库**——痛点 8 的最后一块。

P37 #5 在真库上量完的结论是「重建不出来」：九种改动层里八种在库里什么都不留
（`snapshot_content` 只有 `harness/round_snapshot.py` 一个调用方），`auto` 那一档被
`REVISION_INTERVAL_S = 600` 掐掉而且存的是「改之前」那一版，`harness_runs` 连 `note_id`
都没有，**层的处置状态根本没有载体**。所以这一批给层单开了一张 `note_change_layers`。

这里盯五件事：

* **四个处置状态每一个都真写真读**（`HUNK_STATES` 的 `pending` / `off` / `accepted` / `reverted`）
  ——批 22 的 `stopped` 从加进来那天起就记不到 `max_rounds`，那条规矩就是这么来的。
  整层的 `on` / `off` 两个取值同样各一条。
* **淘汰要吵闹**：超上限 / 过期 / 一层太多处，三条路各自把「少存了什么、为什么」回给调用方，
  不许静默少一层。
* **不许塞进 `note_revisions`**：这张表写多少行，那张一行都不许动（它有 `REVISION_KEEP=100`
  的淘汰闸，而且是 `db_guard` 指纹盯着的两张表之一）。
* **`db_guard` 没把新表收进 `WATCHED`**，而且注释里写明了为什么（跟 `harness_runs` 同一条理由）。
* **接得上**：两条路由真的挂在 app 上、删笔记真的把层带走——建了不接等于没建
  （P32 / P34 / P36 / P37 各栽过一次）。
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import store
from app.main import app

USER = "p39"


@pytest.fixture()
def client():
    with TestClient(app, headers={"X-User-Id": USER}) as c:
        yield c


def _note(content: str = "甲乙丙丁戊己庚辛") -> str:
    return store.create_note(USER, "P39", content)["id"]


def _hunk(state: str, **kw) -> dict:
    out = {"k": 0, "from": 1, "to": 3, "del": "乙丙", "ins": "XY", "state": state,
           "before": "甲", "after": "丁戊"}
    out.update(kw)
    return out


def _layer(label: str = "润色", **kw) -> dict:
    out = {
        "id": "layer-1", "label": label, "source": "polish", "run_id": "", "round_no": 0,
        "seq": 0, "state": "on", "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "content_tag": "8:abc", "hunks": [_hunk("pending")],
    }
    out.update(kw)
    return out


# ---------------------------------------------------------------- 取值表

@pytest.mark.parametrize("state", store.HUNK_STATES)
def test_每个处置状态都真写得进去也真读得出来(state):
    """**四个取值，四条**。一个值只要没有一条真写真读的测试，它就可能从加进来那天起
    就是个摆设（批 22 的 `stopped` 记不到 `max_rounds`）。"""
    nid = _note()
    r = store.save_change_layers(USER, nid, [_layer(hunks=[_hunk(state)])])
    assert r["saved"] == 1, f"{state} 这一档一层都没存下"
    assert r["evicted"] == [] and r["rejected"] == []
    back = store.list_change_layers(USER, nid)
    assert len(back) == 1
    assert [h["state"] for h in back[0]["hunks"]] == [state]
    # 读回来的那一处得是完整的，不是只剩个状态
    assert back[0]["hunks"][0]["del"] == "乙丙"
    assert back[0]["hunks"][0]["ins"] == "XY"
    assert back[0]["hunks"][0]["before"] == "甲"


@pytest.mark.parametrize("state", store.LAYER_STATES)
def test_整层开关两个取值都写得进去(state):
    nid = _note()
    store.save_change_layers(USER, nid, [_layer(state=state)])
    assert store.list_change_layers(USER, nid)[0]["state"] == state


def test_四个状态同时挂在一层上也各自读得回来():
    """验证 2 的那一幕：逐处接受两处、撤回一处，还剩一处待定 —— 四种状态一起落库。"""
    nid = _note()
    hunks = [_hunk("accepted", k=0), _hunk("accepted", k=1), _hunk("reverted", k=2), _hunk("pending", k=3)]
    store.save_change_layers(USER, nid, [_layer(hunks=hunks)])
    got = store.list_change_layers(USER, nid)[0]["hunks"]
    assert [h["state"] for h in got] == ["accepted", "accepted", "reverted", "pending"]
    assert [h["k"] for h in got] == [0, 1, 2, 3]


def test_不认识的来源落成other而不是被丢掉():
    nid = _note()
    store.save_change_layers(USER, nid, [_layer(source="没见过这个")])
    assert store.list_change_layers(USER, nid)[0]["source"] == "other"


@pytest.mark.parametrize("source", store.CHANGE_LAYER_SOURCES)
def test_来源表里每个码都存得进去(source):
    nid = _note()
    store.save_change_layers(USER, nid, [_layer(source=source)])
    assert store.list_change_layers(USER, nid)[0]["source"] == source


def test_状态不认识的一处不许静默吞掉():
    nid = _note()
    r = store.save_change_layers(USER, nid, [_layer(hunks=[_hunk("pending"), _hunk("随便写的")])])
    assert r["saved"] == 1
    assert len(store.list_change_layers(USER, nid)[0]["hunks"]) == 1
    assert r["rejected"] and "形状不对" in r["rejected"][0]["why"]


# ---------------------------------------------------------------- 淘汰

def test_一篇超过上限就淘汰最早的并且说出来():
    nid = _note()
    many = [_layer(f"第{i}层", id=f"l{i}", seq=i) for i in range(store.CHANGE_LAYER_KEEP + 3)]
    r = store.save_change_layers(USER, nid, many)
    assert r["saved"] == store.CHANGE_LAYER_KEEP
    assert len(r["evicted"]) == 3, "淘汰了三层却一声不吭 —— 那就是这一批要修的毛病本身"
    assert [e["label"] for e in r["evicted"]] == ["第0层", "第1层", "第2层"]
    assert str(store.CHANGE_LAYER_KEEP) in r["evicted"][0]["why"]
    assert [l["label"] for l in store.list_change_layers(USER, nid)][0] == "第3层"


def test_时间戳是个怪串不会把整条保存弄挂():
    """不带时区的串在 `naive < aware` 上抛的是 TypeError 不是 ValueError——
    漏接就是整条保存 500。这一条只是「这层多老了」，不该有本事弄挂保存。"""
    nid = _note()
    for bad in ("2026-09-20T10:00:00", "不是时间", ""):
        r = store.save_change_layers(USER, nid, [_layer(at=bad)])
        assert r["saved"] == 1, f"{bad!r} 这一档把保存弄挂了"


def test_太久没处置的层淘汰掉并且说出来():
    nid = _note()
    old = (datetime.now(timezone.utc) - timedelta(days=store.CHANGE_LAYER_MAX_AGE_DAYS + 1)).isoformat()
    r = store.save_change_layers(USER, nid, [_layer("陈年那层", at=old), _layer("今天这层", id="l2")])
    assert r["saved"] == 1
    assert [e["label"] for e in r["evicted"]] == ["陈年那层"]
    assert str(store.CHANGE_LAYER_MAX_AGE_DAYS) in r["evicted"][0]["why"]


def test_一层太多处就整层不存而不是截断着存():
    """截断着存更糟：用户看到「这层 500 处」，而真相是 3000 处里挑剩的 500 处。"""
    nid = _note()
    fat = _layer("格式化", hunks=[_hunk("pending", k=i) for i in range(store.CHANGE_LAYER_HUNKS + 1)])
    r = store.save_change_layers(USER, nid, [fat])
    assert r["saved"] == 0
    assert store.list_change_layers(USER, nid) == []
    assert r["rejected"] and str(store.CHANGE_LAYER_HUNKS) in r["rejected"][0]["why"]


def test_刚好卡在上限上的那一层存得下():
    nid = _note()
    ok = _layer("格式化", hunks=[_hunk("pending", k=i) for i in range(store.CHANGE_LAYER_HUNKS)])
    assert store.save_change_layers(USER, nid, [ok])["saved"] == 1


# ---------------------------------------------------------------- 边界

def test_写多少层note_revisions都一行不动():
    """**不许塞进 `note_revisions`**（P37 #5 下一步那句）：那张表有 100 版的淘汰闸，
    而且是 `db_guard` 指纹盯着的两张表之一。"""
    nid = _note()
    store.snapshot_note(USER, nid, "manual")
    before = len(store.list_revisions(USER, nid))
    for i in range(5):
        store.save_change_layers(USER, nid, [_layer(f"第{i}次", id=f"l{i}")])
    assert len(store.list_revisions(USER, nid)) == before


def test_整批替换不是增量():
    nid = _note()
    store.save_change_layers(USER, nid, [_layer("甲", id="a"), _layer("乙", id="b")])
    store.save_change_layers(USER, nid, [_layer("乙", id="b")])
    assert [l["label"] for l in store.list_change_layers(USER, nid)] == ["乙"]


def test_已经在库里的层保留原来的生日():
    nid = _note()
    store.save_change_layers(USER, nid, [_layer("甲", id="a")])
    born = store.list_change_layers(USER, nid)[0]["created_at"]
    store.save_change_layers(USER, nid, [_layer("甲", id="a", state="off")])
    again = store.list_change_layers(USER, nid)[0]
    assert again["created_at"] == born and again["state"] == "off"


def test_一处都不剩的层不落行():
    nid = _note()
    assert store.save_change_layers(USER, nid, [_layer(hunks=[])])["saved"] == 0


def test_删笔记把它的层一起带走():
    nid = _note()
    store.save_change_layers(USER, nid, [_layer()])
    store.delete_note(USER, nid)
    with store.connect() as c:
        left = c.execute("SELECT count(*) FROM note_change_layers WHERE note_id=?", (nid,)).fetchone()[0]
    assert left == 0, "笔记删了层还躺着 —— 又一批指向空气的孤儿行"


def test_层是按篇隔开的():
    a, b = _note(), _note()
    store.save_change_layers(USER, a, [_layer("A 的", id="la")])
    store.save_change_layers(USER, b, [_layer("B 的", id="lb")])
    assert [l["label"] for l in store.list_change_layers(USER, a)] == ["A 的"]
    assert [l["label"] for l in store.list_change_layers(USER, b)] == ["B 的"]


# ---------------------------------------------------------------- 接线

def test_接线_两条路由真的挂在app上(client):
    """**接线洞要单独一条**：函数对了但没接上，规则层单测抓不住（P32 / P34 / P36 / P37 各栽过）。"""
    nid = _note()
    r = client.put(f"/api/notes/{nid}/change-layers", json={"layers": [_layer()]})
    assert r.status_code == 200, r.text
    assert r.json()["saved"] == 1
    got = client.get(f"/api/notes/{nid}/change-layers")
    assert got.status_code == 200
    layers = got.json()["layers"]
    assert len(layers) == 1 and layers[0]["hunks"][0]["state"] == "pending"
    # 别名过一圈还在：`from` / `del` 是 Python 关键字，走的是 alias
    assert layers[0]["hunks"][0]["from"] == 1 and layers[0]["hunks"][0]["del"] == "乙丙"


def test_接线_淘汰的理由真的回到了接口上(client):
    nid = _note()
    many = [_layer(f"第{i}层", id=f"l{i}", seq=i) for i in range(store.CHANGE_LAYER_KEEP + 1)]
    body = client.put(f"/api/notes/{nid}/change-layers", json={"layers": many}).json()
    assert body["evicted"] and body["evicted"][0]["why"]


def test_接线_没这篇笔记是404不是静默成功(client):
    assert client.get("/api/notes/不存在的/change-layers").status_code == 404
    assert client.put("/api/notes/不存在的/change-layers", json={"layers": []}).status_code == 404


def test_接线_前端真的会调这两条(  ):
    """建了、测了、用户够不着 —— 这个仓反复出的一种 bug（`check-api-wired` 开头那句）。"""
    src = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "api.ts").read_text("utf-8")
    assert "/change-layers" in src
    app_src = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "App.tsx").read_text("utf-8")
    assert "api.listChangeLayers(" in app_src, "读出来的那一头没人调 —— 层存了也放不回去"
    assert "api.saveChangeLayers(" in app_src, "写进去的那一头没人调"
    assert "onLayersChanged={onLayersChanged}" in app_src, "编辑器报的「层动了」没接到 App 上"
    assert "restoreLayersEffect.of(" in app_src, "读回来的层没有真的塞进编辑器"


def test_接线_dbguard没把新表收进WATCHED而且写了为什么():
    """新表**不要**进 `WATCHED`（跑批本来就该往它写），但理由要写在那儿——
    下一个人看见这张表不在名单里，得能当场读到为什么。"""
    src = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "db_guard.py").read_text("utf-8")
    assert "WATCHED = (\"notes\", \"note_revisions\")" in src
    head = src.split("WATCHED = (")[0]
    assert "note_change_layers" in head, "新表没在 WATCHED 那段注释里交代为什么不进"
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
    import db_guard
    assert "note_change_layers" not in db_guard.WATCHED


def test_坏JSON读出来是空数组不是整个接口500():
    nid = _note()
    store.save_change_layers(USER, nid, [_layer()])
    with store.connect() as c:
        c.execute("UPDATE note_change_layers SET hunks='{坏的' WHERE note_id=?", (nid,))
        c.commit()
    assert store.list_change_layers(USER, nid)[0]["hunks"] == []


def test_存进去的hunks在库里是一列JSON不是第二张表():
    nid = _note()
    store.save_change_layers(USER, nid, [_layer()])
    with store.connect() as c:
        raw = c.execute("SELECT hunks FROM note_change_layers WHERE note_id=?", (nid,)).fetchone()[0]
    assert isinstance(json.loads(raw), list)
