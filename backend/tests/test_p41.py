"""P41（`docs/TRACELOG-product.md` P41 节）：P40 走查那几条里的后端两条 + P39 的遗留一条。

**#1 「来龙去脉」说假话。** P40 实拍（`p40-B-both-panels-light`）：同一屏上「校验」对**同一段话**
说「知识库里有 6 条相关记录」，而「来龙去脉」说「知识库里没有跟这段沾边的记录。」
——两块面板、同一个库、互相打架，而且前一句是假的。根因：`_no_info_to_chinese(text, has_facts)`
里的 `has_facts` 数的是 **KITE 自己那条 planning 检索**串出了几条，而那句话说的是「知识库里有没有」。
跟 P9 #26 / P37 #2 是同一个形状，只是换了一块面板。
照 `VerifyOut` 那条思路**多带一格**（`AskOut.recalled` = 同一段话的**词法召回**回了几条），
按三档说三句。后端真跑复现过：`<scratch>/p41/repro1.py` 在真库整拷上跑到两段
`recall=3 / ask_facts=0` 和 `recall=9 / ask_facts=0`，两段说的都是那句假话。

**#6 烧进正文之后不许还留着层**（P39「留给下一批」④）。P39 把「关掉 app 层还在」修好了，
于是反过来那个毛病就露出来了：「全部接受」把层烧进正文之后立刻关掉 app，那一次防抖冲库
（`CHANGE_LAYER_SAVE_MS`）根本没发出去，库里那几层原样留着——下次打开按旧坐标把高亮
标到**已经烧进正文**的字上（P17 那个「幻影删除标」的形状，只是这次来源是库不是消息）。
`store.burn_change_layers` 是那条闸：清完当场再数一遍，没清干净就抛。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import store
from app.main import app
from app.routers import memory as memrouter

USER = "p41"


@pytest.fixture()
def client():
    with TestClient(app, headers={"X-User-Id": USER}) as c:
        yield c


# ---------------------------------------------------------------- #1 来龙去脉那句话

NO_INFO = "No information"


def test_KITE串出东西时说的还是原来那句():
    said = memrouter._no_info_to_chinese(NO_INFO, True, 6)
    assert said == "知识库里的记录串不出这件事的来龙去脉——下面是最相关的几条，可能只是沾边。"


def test_一条都没查到才允许说知识库里没有():
    """**原来那句话在这一档才是对的**（跟 `VerifyPanel.emptyVerifyLine` 的 `checked <= 0` 同一档）。"""
    assert memrouter._no_info_to_chinese(NO_INFO, False, 0) == "知识库里没有跟这段沾边的记录。"


def test_查到了但这一步没串出来就不许说知识库里没有():
    """P40 实拍那一格：词法召回回了 6 条，而面板说「没有跟这段沾边的记录」。"""
    said = memrouter._no_info_to_chinese(NO_INFO, False, 6)
    assert "知识库里没有跟这段沾边的记录" not in said
    assert "6 条" in said
    assert "没能串出一条时间线" in said


def test_没量过那一格时退回原来那句话_老调用方对得上():
    """`recalled=None` = 这一趟没量。**不启用就是原样**（`kb/search` 那几档同一条规矩）。"""
    assert memrouter._no_info_to_chinese(NO_INFO, False) == "知识库里没有跟这段沾边的记录。"
    assert memrouter._no_info_to_chinese(NO_INFO, False, None) == "知识库里没有跟这段沾边的记录。"


def test_判据窄_模型正常答的一个字都不动():
    """只认 KITE 那句英文拒答。模型真答了东西就原样给，别的一律不碰。"""
    for text in ("3 月 12 日定稿，3 月 20 日上线。", "no idea", "", "Information: 有的"):
        assert memrouter._no_info_to_chinese(text, False, 6) == text


def test_AskOut多的那一格有缺省_老前端老后端都对得上():
    from app.routers.schemas import AskOut
    assert AskOut(answer="x", took_ms=1.0).recalled is None


def test_空库那一档明说是零而不是没量过(client, monkeypatch):
    """空库短路那条路也要填这一格：`None`（没量）和 `0`（真没有）不是一回事。"""
    monkeypatch.setattr(memrouter, "_has_facts", lambda mem: False)
    r = client.post("/api/memory/trace", json={"passage": "随便一段话，够长了吧。"})
    assert r.status_code == 200
    assert r.json()["recalled"] == 0


def test_串不出来时真的去问了一次词法召回(client, monkeypatch):
    """**接线洞**：多带的那一格要真的被填上，不能只是 schema 里有。"""
    calls = []

    class FakeMem:
        def ask(self, q, limit=10):
            return NO_INFO, []

        def recall(self, passage, limit=6, **kw):
            calls.append((passage, limit))
            return ([{"id": "f1"}] * 4, [], 0.0)

    monkeypatch.setattr(memrouter, "UserMemory", lambda user: FakeMem())
    monkeypatch.setattr(memrouter, "_has_facts", lambda mem: True)
    r = client.post("/api/memory/trace", json={"passage": "3月12号上线，众筹页面的文案定稿了。"})
    assert r.status_code == 200
    body = r.json()
    assert body["recalled"] == 4
    assert "4 条" in body["answer"]
    # 用的是跟「校验」同一个 limit——两块面板报的数出自同一把尺子
    assert calls and calls[0][1] == memrouter.TRACE_RECALL_LIMIT == 6


def test_串出东西的那一档不白花一次召回(client, monkeypatch):
    """**判据窄**：KITE 串出东西时没有第二块面板可以打架，那一次查询是白花的。"""
    calls = []

    class FakeMem:
        def ask(self, q, limit=10):
            return NO_INFO, [{"id": "a", "text": "t", "date": "", "kind": "", "sources": []}]

        def recall(self, passage, limit=6, **kw):
            calls.append(passage)
            return ([], [], 0.0)

    monkeypatch.setattr(memrouter, "UserMemory", lambda user: FakeMem())
    monkeypatch.setattr(memrouter, "_has_facts", lambda mem: True)
    r = client.post("/api/memory/trace", json={"passage": "一段够长的话，随便写点什么。"})
    assert r.status_code == 200
    assert r.json()["recalled"] is None
    assert calls == []


# ---------------------------------------------------------------- #6 烧了就不许还留着层


def _one_layer(note_id: str, lid: str = "L1") -> list[dict]:
    return [{
        "id": lid, "label": "智能续写", "source": "round", "seq": 0, "state": "on",
        "at": "2026-09-20T02:00:00+00:00", "content_tag": "12:abc",
        "hunks": [{"k": 0, "from": 0, "to": 3, "del": "旧", "ins": "新的一段",
                   "state": "pending", "before": "", "after": ""}],
    }]


def test_烧进正文之后一层都不许剩():
    n = store.create_note(USER, "烧", "正文")
    store.save_change_layers(USER, n["id"], _one_layer(n["id"]))
    assert len(store.list_change_layers(USER, n["id"])) == 1
    assert store.burn_change_layers(USER, n["id"]) == 1
    assert store.list_change_layers(USER, n["id"]) == []


def test_烧完没清干净就抛_不是静默放行(monkeypatch):
    """闸要**吵闹地失败**。清不掉的时候放行，就是把「层和正文对不上」这件事藏起来。"""
    n = store.create_note(USER, "烧不掉", "正文")
    store.save_change_layers(USER, n["id"], _one_layer(n["id"]))
    monkeypatch.setattr(store, "drop_change_layers", lambda u, nid: 0)   # 假装 DELETE 没删成
    with pytest.raises(store.LayersStillPending):
        store.burn_change_layers(USER, n["id"])


def test_烧只烧这一篇_别的笔记的层不许跟着没():
    a = store.create_note(USER, "A", "正文")
    b = store.create_note(USER, "B", "正文")
    # 层 id 是全表唯一的主键（跨笔记也唯一），两篇不能共用同一个 key
    store.save_change_layers(USER, a["id"], _one_layer(a["id"], "LA"))
    store.save_change_layers(USER, b["id"], _one_layer(b["id"], "LB"))
    store.burn_change_layers(USER, a["id"])
    assert store.list_change_layers(USER, a["id"]) == []
    assert len(store.list_change_layers(USER, b["id"])) == 1


def test_烧那条路由真的挂在app上(client):
    """**接线洞**（P32 / P34 / P36 / P37 / P40 各栽过一次）：写好了不接进去等于没写。"""
    n = store.create_note(USER, "路由", "正文")
    store.save_change_layers(USER, n["id"], _one_layer(n["id"]))
    r = client.delete(f"/api/notes/{n['id']}/change-layers")
    assert r.status_code == 200, r.text
    assert r.json()["dropped"] == 1
    assert client.get(f"/api/notes/{n['id']}/change-layers").json()["layers"] == []


def test_烧一篇不存在的笔记是404(client):
    assert client.delete("/api/notes/000000000000/change-layers").status_code == 404


def test_烧过之后还能再攒新的层():
    """闸守的是「烧的那一刻」，不是「这一篇以后不许有层」。"""
    n = store.create_note(USER, "再来", "正文")
    store.save_change_layers(USER, n["id"], _one_layer(n["id"]))
    store.burn_change_layers(USER, n["id"])
    store.save_change_layers(USER, n["id"], _one_layer(n["id"], "L2"))
    assert len(store.list_change_layers(USER, n["id"])) == 1


def test_烧不动note_revisions():
    """**这张表写多少行，那张一行都不许动**（P39 那条，烧这条路也得守）。"""
    n = store.create_note(USER, "两张表", "正文够长了吧，存一版。")
    store.snapshot_note(USER, n["id"])
    before = len(store.list_revisions(USER, n["id"]))
    store.save_change_layers(USER, n["id"], _one_layer(n["id"]))
    store.burn_change_layers(USER, n["id"])
    assert len(store.list_revisions(USER, n["id"])) == before
