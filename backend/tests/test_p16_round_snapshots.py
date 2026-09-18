"""P16（产品就绪计划 §2 C2，`docs/TRACELOG-product.md` P16 节）：改动的分层历史——「烧之前的快照」。

agent-native-editor §3.2：「历史版本保留每次烧之前的快照」。分层账本在前端已经能开关 / 接受 / 撤回，
但接受 = 烧进正文、层就没了；痛点 8「留第一轮、丢第三轮」在烧之后做不到。这里盯四件事：

* **每轮一行**：`reason='round'` 的行每轮恰好一行、`round_no` 就是那一轮、正文是那一轮**之前**的；
  收尾一行 `run_end`（最后一轮的「之后」）；`run_id` 非空且整次跑同一个；
* **不越界**：`rails_off=("save",)` 的跑、block 模式一行都不许落（`note_revisions` 是 `db_guard` 指纹盯着的表）；
* **接得上**：`GET /api/notes/{id}/revisions` 带 `run_id` / `round_no`，老数据是 '' / 0，不 500；
* **真接了**：两条跑 harness 的路由都套着它——建了不接等于没建。
"""
from __future__ import annotations

import asyncio
import dataclasses
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.database import store
from app.harness import modes
from app.harness.events import Event
from app.harness.round_snapshot import with_round_snapshots
from app.harness.state import State
from app.harness.tools import ToolContext

USER = "p16"


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")


def _st(note_id: str, mode=None, rails_off=()) -> State:
    mode = dataclasses.replace(mode or modes.NOTE, rails_off=tuple(rails_off))
    return State(mode=mode, ctx=ToolContext(user=USER, note_id=note_id, note_title="标题"), content="v0")


async def _three_rounds(st: State):
    """像 loop.run 一样：每轮开始前先 yield STEP_STARTED（此刻 st.content 还是上一轮落地的），然后这一轮改正文。"""
    for n in (1, 2, 3):
        yield Event.step_started(n, "智能续写")
        st.round = n
        st.content = f"v{n}"
    yield Event.run_finished(st.content, "complete")


def _collect(st: State, events) -> list:
    async def go():
        return [e async for e in with_round_snapshots(events, st)]
    return asyncio.run(go())


def _rows(note_id: str) -> list[dict]:
    with store.connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT reason, run_id, round_no, content FROM note_revisions WHERE note_id=? ORDER BY rowid", (note_id,))]


# ------------------------------------------------------------ 每轮一行

def test_每轮开始前存一版_收尾再存一版_run_id同一个():
    nid = store.create_note(USER, "标题", "v0")["id"]
    st = _st(nid)
    out = _collect(st, _three_rounds(st))
    assert [e.type.value for e in out] == ["STEP_STARTED"] * 3 + ["RUN_FINISHED"]   # 事件原样透传
    rows = _rows(nid)
    rounds = [r for r in rows if r["reason"] == "round"]
    assert [r["round_no"] for r in rounds] == [1, 2, 3], "reason='round' 的行每轮恰好一行"
    assert [r["content"] for r in rounds] == ["v0", "v1", "v2"], "存的是那一轮**之前**的正文"
    end = [r for r in rows if r["reason"] == "run_end"]
    assert len(end) == 1 and end[0]["round_no"] == 3 and end[0]["content"] == "v3"
    ids = {r["run_id"] for r in rows}
    assert len(ids) == 1 and "" not in ids, "run_id 非空且整次跑同一个"
    assert st.bag["run_id"] in ids, "Ledger 之后生成 run_id 时会沿用这一个（它只在没有时才生成）"


def test_已有run_id时沿用_恢复的跑接着数():
    nid = store.create_note(USER, "标题", "v0")["id"]
    st = _st(nid)
    st.bag["run_id"] = "run-abc"

    async def resumed(st: State):
        st.round = 2
        yield Event.step_started(3, "智能续写")
        st.content = "v3"
        yield Event.run_finished("v3", "complete")

    _collect(st, resumed(st))
    rows = _rows(nid)
    assert [(r["reason"], r["run_id"], r["round_no"]) for r in rows] == [("round", "run-abc", 3), ("run_end", "run-abc", 3)]


def test_一轮都没跑就没有收尾行():
    nid = store.create_note(USER, "标题", "v0")["id"]
    st = _st(nid)

    async def blocked(st: State):
        yield Event.run_finished("v0", "blocked", "先写点什么")

    _collect(st, blocked(st))
    assert _rows(nid) == []


# ------------------------------------------------------------ 不越界

def test_rails_off_save_的跑一行都不落():
    nid = store.create_note(USER, "标题", "v0")["id"]
    st = _st(nid, rails_off=("save",))
    _collect(st, _three_rounds(st))
    assert _rows(nid) == []


def test_block模式一行都不落():
    nid = store.create_note(USER, "标题", "v0")["id"]
    st = _st(nid, mode=next(iter(modes.BLOCK.values())))
    _collect(st, _three_rounds(st))
    assert _rows(nid) == []


def test_空正文不存_存不进去不影响事件流(monkeypatch):
    nid = store.create_note(USER, "标题", "v0")["id"]
    st = _st(nid)
    st.content = "   "

    async def one(st: State):
        yield Event.step_started(1, "智能续写")

    assert len(_collect(st, one(st))) == 1
    assert _rows(nid) == []
    st.content = "v0"
    monkeypatch.setattr(store, "snapshot_content", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk")))
    assert len(_collect(st, one(st))) == 1, "快照不承重：写不进去事件照发"


# ------------------------------------------------------------ 接得上

def test_列表和单版都带run_id和round_no_老数据是空的():
    from app.main import app

    with TestClient(app, headers={"X-User-Id": USER}) as c:
        n = c.post("/api/notes", json={"title": "甲", "content": "v0"}).json()
        c.post(f"/api/notes/{n['id']}/revisions")                       # 手动一版：跟跑无关
        st = _st(n["id"])
        _collect(st, _three_rounds(st))
        revs = c.get(f"/api/notes/{n['id']}/revisions").json()
        by = {(r["reason"], r["round_no"]): r for r in revs}
        assert ("manual", 0) in by and by[("manual", 0)]["run_id"] == ""
        assert {k for k in by if k[0] == "round"} == {("round", 1), ("round", 2), ("round", 3)}
        assert all(by[("round", i)]["run_id"] == st.bag["run_id"] for i in (1, 2, 3))
        one = c.get(f"/api/notes/{n['id']}/revisions/{by[('round', 2)]['id']}").json()
        assert (one["run_id"], one["round_no"], one["content"]) == (st.bag["run_id"], 2, "v1")


# ------------------------------------------------------------ 真接了

def test_两条跑harness的路由都套着它():
    routers = pathlib.Path(__file__).resolve().parent.parent / "app" / "routers"
    for name in ("note_harness.py", "harness.py"):
        src = (routers / name).read_text(encoding="utf-8")
        assert "with_round_snapshots(loop.run(st, hooks), st)" in src, f"{name} 没套 with_round_snapshots——建了不接等于没建"
