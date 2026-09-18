"""批 23 / 计划 12.3：单次跑的成本上限。

在这之前**完全没有**：`judge` 只说 continue / complete / blocked，从不问
「再花十几秒值不值」（[MECH] §7），而一次跑能花多少没有任何约束。

上限的数字在 `params.RUN_TOKEN_CAP` 的注释里，连同它的分布依据
（`scripts/run_cost_probe.py` 量的 158 次跑）。这个文件盯的是**机制**：
账记得对吗、超了真会停吗、停的时候交的是哪一份、落库的那两列真写得进去吗。

**「落库加字段之后要问一句它的每个取值都真写得进去吗」**（批 22 的教训：
`stopped` 这一列从加进来那天起就记不到 `max_rounds`）——所以这里有一条
真跑到底、去库里把 `tokens` / `calls` / `stopped='cost_cap'` 读回来的用例。
"""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from app.database import store
from app.harness import loop, modes, params
from app.harness.events import CUSTOM_COST, CUSTOM_WARNING
from app.harness.middleware import BASE
from app.harness.middleware.cost import Cost, over_cap, spent
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import DimensionScore, Evaluation, Hooks
from app.util import llm

DIMS = ("beat_coverage", "non_repetition", "factual_grounding")


def _st(cap=1000, **bag):
    st = State(mode=dataclasses.replace(modes.NOTE, dims=DIMS),
               ctx=ToolContext(user="u", note_id="n", note_title="t"))
    st.round = 1
    st.bag.update(bag)
    asyncio.run(Cost().before_run(st))
    # `asyncio.run` 每次都在**复制出来的 context** 里跑，所以上面那次
    # `bind_usage_sink` 绑的是那个副本，回不到测试自己的 context。这里重新
    # 绑一次同一个 dict——绑的是 dict 本身不是快照，所以两边记的是同一份账。
    # **真跑那一路不会有这个问题**（`loop.run` 的 `before_run` 和后面的调用
    # 在同一个 task 里）——下面 `test_花超了停下来…` / `test_这次跑花了多少真
    # 写得进库里` 两条都是真跑 `loop.run`、**一次都没手动绑**，账照样记得上。
    llm.bind_usage_sink(st.bag["cost"])
    st.bag["token_cap"] = cap
    return st


def _fire(st) -> list:
    async def go():
        return [e async for e in Cost().after_round(st)]
    return asyncio.run(go())


# ------------------------------------------------------------ 账记得对吗

def test_每一笔用量都加进这次跑的账():
    """`util/llm._record` 是全仓唯一一处记用量的地方（所以只需要挂这一处）。"""
    st = _st()
    llm._record({"prompt_tokens": 100, "completion_tokens": 20,
                 "prompt_tokens_details": {"cached_tokens": 60}}, "m", 0.0)
    llm._record({"prompt_tokens": 7, "completion_tokens": 3}, "m", 0.0)
    assert st.bag["cost"] == {"calls": 2, "prompt_tokens": 107,
                              "completion_tokens": 23, "cached_tokens": 60}
    assert spent(st) == 130


def test_没绑账本的调用不记到任何人头上():
    """后台任务 / 摄入那些路径根本不属于任何一次跑。"""
    token = llm.ctx_usage_sink.set(None)
    try:
        llm._record({"prompt_tokens": 9, "completion_tokens": 1}, "m", 0.0)   # 不许炸
    finally:
        llm.ctx_usage_sink.reset(token)


def test_恢复一次暂停的跑接着记():
    """`bag` 进快照，所以上半场的账跟着回来——重新从 0 记的话，一次暂停
    等于把上限重置一遍。"""
    st = _st(cap=1000, cost={"calls": 5, "prompt_tokens": 400,
                             "completion_tokens": 100, "cached_tokens": 0})
    assert spent(st) == 500


def test_记账出错要出声而不是让成本偷偷变小():
    st = _st()
    llm._record({"prompt_tokens": "不是数字"}, "m", 0.0)
    assert st.bag["cost"]["tally_error"] == 1
    events = _fire(st)
    assert any(e.data["name"] == CUSTOM_WARNING for e in events)


# ------------------------------------------------------------ 超了会停吗

def test_没超不报也不停():
    st = _st(cap=1000)
    llm._record({"prompt_tokens": 500, "completion_tokens": 100}, "m", 0.0)
    assert _fire(st) == []
    assert loop._over_budget(st) is None


def test_超了报一条带数字的并且停机规则跟着开火():
    st = _st(cap=1000)
    llm._record({"prompt_tokens": 900, "completion_tokens": 200}, "m", 0.0)
    events = [e for e in _fire(st) if e.data["name"] == CUSTOM_COST]
    assert len(events) == 1
    v = events[0].data["value"]
    assert (v["tokens"], v["cap"], v["calls"]) == (1100, 1000, 1)
    assert "1,100" in v["detail"] and "1,000" in v["detail"], \
        "「停下来告诉用户」得把数字告诉他，不是只说一句停了"
    assert loop._over_budget(st) == "cost_cap"


@pytest.mark.parametrize("cap", [0, -1])
def test_上限关掉就永远不开火(cap):
    st = _st(cap=cap)
    llm._record({"prompt_tokens": 10 ** 9, "completion_tokens": 0}, "m", 0.0)
    assert not over_cap(st)
    assert loop._over_budget(st) is None
    assert _fire(st) == []


def test_上限在开跑时定死中途改环境变量不算(monkeypatch):
    """一次跑中途换判据，事后「这次为什么停了」就答不出来了。"""
    st = _st(cap=1000)
    monkeypatch.setattr(params, "RUN_TOKEN_CAP", 1)
    llm._record({"prompt_tokens": 500, "completion_tokens": 0}, "m", 0.0)
    assert not over_cap(st)


def test_默认上限高于已经量到的最大一次跑():
    """500,000 是 158 次跑里最大那次（248,160）的 2 倍。**它是安全网不是
    控制器**——一个会在正常使用里被撞到的"安全网"就不是安全网
    （`params.CONTINUE_MAX_TOKENS` 那条注释是拿同一件事换来的）。"""
    assert params.RUN_TOKEN_CAP >= 2 * 248_160


# ------------------------------------------------------------ 停的时候交哪一份

class _Hooks(Hooks):
    """每轮烧掉固定的 token，正文越写越长。"""

    def __init__(self, per_round: int):
        self.per_round = per_round

    async def prepare(self, st):
        return [], None

    async def produce(self, st):
        llm._record({"prompt_tokens": self.per_round, "completion_tokens": 0}, "m", 0.0)
        text = f"第 {st.round} 轮。"
        st.content = st.content + text          # 跟 hooks/note.produce 一样：产出即正文
        yield text

    async def commit(self, st):
        return None


def _score_by_round(monkeypatch, levels_by_round: dict[int, dict[str, int]]):
    async def fake(st):
        lv = levels_by_round[st.round]
        return Evaluation(scores={k: DimensionScore(level=v, note="") for k, v in lv.items()},
                          status="continue", weakest=min(lv, key=lv.get))
    monkeypatch.setattr(loop, "_evaluate", fake)


def _run(st, hooks, mw):
    async def go():
        return [e async for e in loop.run(st, hooks, mw)]
    return asyncio.run(go())


def test_花超了停下来并且交的是最好的那一轮(monkeypatch):
    """`cost_cap` 跟循环末尾那个 `else:`（跑满轮数）是同一个形状：**停机的
    理由跟这一轮写得好不好无关**，那正是「最后一轮最不可能是最好那轮」的
    时候。名单在 `loop.SHIP_BEST_ON`。"""
    _score_by_round(monkeypatch, {
        1: {"beat_coverage": 2, "non_repetition": 2, "factual_grounding": 1},
        2: {"beat_coverage": 1, "non_repetition": 1, "factual_grounding": 1},
    })
    mode = dataclasses.replace(modes.NOTE, dims=DIMS, max_rounds=5,
                               extra_mw=(), rails_off=("save", "edits"))
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n", note_title="t"))
    st.bag["token_cap"] = 900
    events = _run(st, _Hooks(500), [m for m in BASE
                                    if getattr(m, "name", "") in ("cost", "best_of")])
    done = [e for e in events if e.type.value == "RUN_FINISHED"][0]
    assert done.data["reason"] == "cost_cap"
    assert st.round == 2, "轮末判，所以最多超出一轮的开销"
    assert done.data["content"] == "第 1 轮。", "交的得是最好的那一轮"
    assert any(e.data.get("name") == CUSTOM_COST for e in events if e.data)


def test_能完成的跑不会被成本盖掉(monkeypatch):
    """`complete` / `blocked` 是这次跑真正的结局，钱花到上限只是「没能在预算
    内做完」，不该盖掉一个好结局。"""
    async def fake(st):
        lv = {k: 2 for k in DIMS}
        return Evaluation(scores={k: DimensionScore(level=v, note="") for k, v in lv.items()},
                          status="complete", weakest="")
    monkeypatch.setattr(loop, "_evaluate", fake)
    mode = dataclasses.replace(modes.NOTE, dims=DIMS, max_rounds=5,
                               extra_mw=(), rails_off=("save", "edits"))
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n", note_title="t"))
    st.bag["token_cap"] = 1
    events = _run(st, _Hooks(500), [m for m in BASE
                                    if getattr(m, "name", "") in ("cost", "best_of")])
    assert [e for e in events if e.type.value == "RUN_FINISHED"][0].data["reason"] == "complete"


# ------------------------------------------------------------ 落库那两列

def test_这次跑花了多少真写得进库里(monkeypatch):
    """批 22 的教训：`stopped` 这一列从加进来那天起就记不到 `max_rounds`。
    **落库加字段之后要问一句「它的每个取值都真写得进去吗」**——所以这里
    真跑一趟，再去库里把三样读回来。"""
    _score_by_round(monkeypatch, {
        1: {"beat_coverage": 2, "non_repetition": 2, "factual_grounding": 1},
        2: {"beat_coverage": 2, "non_repetition": 1, "factual_grounding": 1},
    })
    mode = dataclasses.replace(modes.NOTE, dims=DIMS, max_rounds=5,
                               extra_mw=(), rails_off=("save", "edits"))
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n", note_title="t"))
    st.bag["token_cap"] = 900
    _run(st, _Hooks(500), [m for m in BASE if getattr(m, "name", "")
                           in ("cost", "ledger", "best_of", "cross_run", "history")])

    rows = store.recent_harness_runs("note:n", limit=3)
    assert len(rows) == 1
    assert rows[0]["stopped"] == "cost_cap", "新的停机原因要真落得进那一列"
    with store.connect() as c:
        row = c.execute("SELECT id, tokens, calls FROM harness_runs").fetchone()
    assert row["tokens"] == 1000 and row["calls"] == 2
    assert row["id"] == st.bag["run_id"], \
        "harness_runs.id 要跟 harness_rounds.run_id 是同一个（三张表第一次有 join 键）"
    assert [r["run_id"] for r in store.rounds_of_run(st.bag["run_id"])] == \
        [st.bag["run_id"]] * 2
