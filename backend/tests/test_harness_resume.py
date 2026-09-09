"""轮末暂停 + 恢复。

原来的行为：harness 连续跑完再让用户处置。编辑器里 385 行的逐条
accept/reject 全是编辑器内的 StateEffect，**一个字都不回传后端**——而
后端每轮自己 update_note()。结果是 harness 还在跑的时候，用户的处置会被
下一轮覆盖；八轮的 run 里「接受这一段」被决定了七次、生效零次。

做法是 LangGraph 那套 interrupt + checkpointer + resume 的最小形态：
**一条停止条件 + 一个恢复端点**，循环本身不知道「暂停」这回事。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from app.harness.types import DimensionScore, Evaluation

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import runtime_policy, store  # noqa: E402
from app.harness import loop, modes, snapshot  # noqa: E402
from app.harness.state import State  # noqa: E402
from app.tools import ToolContext  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    return store


def _state(mode=modes.NOTE, **kw):
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n", note_title="标题"),
               **kw)
    return st


# ---------------------------------------------------------------- 停止条件 ---


def test_开了逐轮处置就每轮停一次():
    st = _state()
    assert modes.pause_for_review(st) is None
    import dataclasses
    st.mode = dataclasses.replace(modes.NOTE, review_each_round=True)
    assert modes.pause_for_review(st) == "awaiting_review"


def test_暂停是普通停止条件循环不认识它():
    """加这条不用动循环——这正是当初把停止条件做成可组合的理由。"""
    src = (Path(__file__).resolve().parent.parent / "app" / "harness"
           / "loop.py").read_text(encoding="utf-8")
    assert "review_each_round" not in src
    assert modes.pause_for_review in modes.NOTE.stop_when


# ------------------------------------------------------------------ 快照 ---


def test_跑到一半的记忆完整存下来():
    """材料、图表、改过哪些地方、上一轮打了多少分——丢一样，恢复之后就会
    把已经做过的事再做一遍，而重新检索是一次模型调用。"""
    st = _state(content="已经写了的正文")
    st.round = 3
    st.facts = ["事实一", "事实二"]
    st.charts = ["mermaid-1"]
    st.steer = "non_repetition: 有重复"
    st.best = ((2, 1.5), "上一轮最好的产出")
    st.ev = Evaluation(scores={"coherence": DimensionScore(level=1, note="乱")},
                       status="continue", weakest="coherence")
    st.bag = {"policy": runtime_policy.RuntimePolicy(tool_iters=4),
              "edited_spans": {"甲", "乙"}, "dry_rounds": 2, "polish": False}

    back = snapshot.loads(snapshot.dumps(st), modes.NOTE)
    assert back.round == 3 and back.content == "已经写了的正文"
    assert back.facts == st.facts and back.charts == st.charts
    assert back.steer == st.steer and back.best == st.best
    assert back.ev.weakest == "coherence" and back.ev.scores["coherence"].level == 1
    assert back.bag["edited_spans"] == {"甲", "乙"}, "集合不能变成 list"
    assert back.bag["policy"].tool_iters == 4, "策略不能变成 dict"


def test_编不动的东西如实报出来():
    """默默丢掉的话，恢复之后少了一个能力，没人知道为什么。"""
    st = _state()
    st.bag = {"fine": 1, "weird": object()}
    text = snapshot.dumps(st)
    assert snapshot.dropped_keys(text) == ["weird"]
    assert snapshot.loads(text, modes.NOTE).bag["fine"] == 1


def test_恢复后工具写进的还是同一个列表():
    """load_skill 往 ctx.scratch 里的那个列表 append。恢复时不重新挂上，
    模型加载的技能就写进了一个没人读的列表。"""
    st = _state()
    st.skill_bodies = ["已经加载的"]
    back = snapshot.loads(snapshot.dumps(st), modes.NOTE)
    back.ctx.scratch["skill_bodies"].append("新加载的")
    assert back.skill_bodies == ["已经加载的", "新加载的"]


def test_mode来自代码不来自快照():
    """上周暂停、这周恢复，应该用今天的判据和检查，不是冻在快照里的那份。"""
    text = snapshot.dumps(_state())
    import json
    assert "checks" not in json.loads(text) and "dims" not in json.loads(text)


# ------------------------------------------------------------------ 端到端 ---


class _Hooks:
    def __init__(self):
        self.committed = 0

    async def prepare(self, st):
        from app.agent_loop import ToolTrace
        return [f"第{st.round}轮的材料"], ToolTrace()

    async def produce(self, st):
        st.content = (st.content + f"\n第{st.round}轮写的").strip()
        yield f"第{st.round}轮写的"

    async def commit(self, st):
        self.committed += 1


def _passing(st):
    return Evaluation(
        scores={"a": DimensionScore(level=1, note="还差点")},
        status="continue", weakest="a")


def test_一轮之后停下来并把run_id给前端(db, monkeypatch):
    import dataclasses

    monkeypatch.setattr(loop, "_score", lambda st: _done(_passing(st)))
    st = _state(mode=dataclasses.replace(modes.NOTE, review_each_round=True,
                                         extra_mw=(), max_rounds=5))
    events = asyncio.run(_collect(loop.run(st, _Hooks(), mw=())))
    finished = [e for e in events if e.type.value == "RUN_FINISHED"][0]
    assert finished.data["reason"] == "awaiting_review"
    assert st.round == 1, "开了逐轮处置就不该一口气跑到底"

    run_id = finished.data["run_id"]
    assert store.get_snapshot("u", run_id)["round"] == 1


def test_恢复时用用户处置后的正文而不是我们写的(db, monkeypatch):
    import dataclasses

    monkeypatch.setattr(loop, "_score", lambda st: _done(_passing(st)))
    mode = dataclasses.replace(modes.NOTE, review_each_round=True,
                               extra_mw=(), max_rounds=5)
    st = _state(mode=mode)
    events = asyncio.run(_collect(loop.run(st, _Hooks(), mw=())))
    run_id = [e for e in events if e.type.value == "RUN_FINISHED"][0].data["run_id"]

    row = store.get_snapshot("u", run_id)
    resumed = snapshot.loads(row["state"], mode)
    resumed.content = "用户只留下了这一句"          # 编辑器里逐条处置的结果
    asyncio.run(_collect(loop.run(resumed, _Hooks(), mw=())))
    assert resumed.content.startswith("用户只留下了这一句"), "不能拿我们那版覆盖用户的"
    assert "第2轮写的" in resumed.content, "要接着往下写，不是从头再来"


def test_快照只能被自己的用户恢复(db):
    run_id = store.save_snapshot("u", "n", "note", 1, "{}")
    assert store.get_snapshot("u", run_id) is not None
    assert store.get_snapshot("别人", run_id) is None


def test_暂停的run不进历史(db, monkeypatch):
    """记进去等于告诉下一次「这篇跑到第 2 轮就停了」——那是用户走开了，
    不是写作的问题。"""
    import dataclasses

    from app.harness.middleware.history import History

    st = _state(mode=dataclasses.replace(modes.NOTE, review_each_round=True))
    st.ev = _passing(st)
    st.stopped = "awaiting_review"
    recorded = []
    monkeypatch.setattr("app.harness_adapter.SqliteRunHistoryStore",
                        lambda: type("S", (), {"record": lambda self, r: recorded.append(r)})())
    asyncio.run(History().after_run(st))
    assert recorded == []

    st.stopped = "complete"
    asyncio.run(History().after_run(st))
    assert len(recorded) == 1


async def _collect(gen):
    return [e async for e in gen]


async def _done(value):
    return value


def test_轮数接着数不从头再来(db, monkeypatch):
    """恢复后从 1 重新数的话，每一条「第一轮不做」的护栏都会重新生效——
    Revise 因为「还没写东西」跳过第一轮，而恢复的 run 显然写过了。
    """
    import dataclasses

    monkeypatch.setattr(loop, "_score", lambda st: _done(_passing(st)))
    mode = dataclasses.replace(modes.NOTE, review_each_round=True,
                               extra_mw=(), max_rounds=5)
    st = _state(mode=mode)
    st.round = 3                                # 已经跑过三轮
    asyncio.run(_collect(loop.run(st, _Hooks(), mw=())))
    assert st.round == 4 and "第4轮写的" in st.content


def test_轮数预算是整个run的不是每次恢复重新给(db, monkeypatch):
    """否则每恢复一次就多送几轮，`max_rounds` 这条安全网等于没有。"""
    import dataclasses

    monkeypatch.setattr(loop, "_score", lambda st: _done(_passing(st)))
    mode = dataclasses.replace(modes.NOTE, extra_mw=(), max_rounds=3)
    st = _state(mode=mode)
    st.round = 3
    asyncio.run(_collect(loop.run(st, _Hooks(), mw=())))
    assert st.round == 3, "预算已经用完，不该再跑"
