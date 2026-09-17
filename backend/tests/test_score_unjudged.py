"""打分解析失败 = 这一轮没打上分，不是「所有维度 0 分」。

计划 1.7（`docs/harness-upgrade-plan.md` 阶段 1，reference [EVAL] 问题二）。

`tests/test_rubric.py` 那几条判的是**打分器自己**抛不抛。这里判的是**后果**：
解析失败之后，回路上那四处读分数的地方各自表现对不对。分开写是因为
「抛异常」是实现，「下游读到的是没判过」才是要求——换个实现（比如改成返回
`None`）这些断言应该照样绿。

老行为（第 766 轮之前）在每一条断言上都会翻车：
`_extract_json` 返回 None → `raw_scores = {}` → 每个维度 `DimensionScore(0)`
→ 一份看起来完全正常的 `Evaluation` 流进下游。
"""

from __future__ import annotations


import json

import pytest

from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import Dimension, Mode


DIMS = (Dimension("non_repetition", "..."),
        Dimension("coherence", "..."),
        Dimension("topic_fidelity", "..."))


class _FakeLLM:
    """模型返回什么由用例说了算，一个网络调用都不发。"""

    def __init__(self, reply: str):
        self.reply = reply

    async def complete(self, messages, **kwargs):
        return self.reply


def _st(max_rounds: int = 3) -> State:
    mode = Mode(key="t", label="t", skill_scope="test_scope", dims=DIMS,
                max_rounds=max_rounds)
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n"), request=None)
    st.content = "正文" * 50
    return st


async def _score_with(monkeypatch, reply: str):
    """走 `loop._score()` 那条真路径，只把底下的模型换掉。"""
    import app.harness.adapter as adapter_mod
    from app.harness.loop import _score

    monkeypatch.setattr(adapter_mod, "AppLLMClient", lambda: _FakeLLM(reply))
    return await _score(_st())


_GOOD = json.dumps({
    "scores": {"non_repetition": {"level": 0, "note": "说了两遍"},
               "coherence": {"level": 0, "note": "散"},
               "topic_fidelity": {"level": 0, "note": "跑题"}},
    "blocked": False, "blocked_reason": "",
})


@pytest.mark.anyio
async def test_解析失败在回路里就是没打上分(monkeypatch):
    """`loop._score()` 原本只挡得住**抛异常**那条路（实测：本地模型过载时
    一次调用超了 300s 超时，异常从 SSE 生成器里逃出去，客户端直接断连）。
    解析失败是从它底下穿过去的第二条路——静默、而且看起来像正常结果。
    """
    assert await _score_with(monkeypatch, "抱歉，我无法完成这个请求。") is None


@pytest.mark.anyio
async def test_真判了全0分还是一份分数(monkeypatch):
    """反面那一半：**误伤比漏报贵。** 写得极差的一轮必须还能被判成 0 分，
    否则它连一轮修复都排不上（见下面 `Repair` 那条）。
    """
    ev = await _score_with(monkeypatch, _GOOD)
    assert ev is not None and all(s.level == 0 for s in ev.scores.values())


@pytest.mark.anyio
async def test_解析失败那一轮的排名要比真判过的低(monkeypatch):
    """`BestOf` 靠 `rank()` 选交哪一轮。老行为下解析失败是 `(0, 0.0)`，
    **比真正没判过的 `(-1, -1.0)` 高**——一次接口抖动就能把一轮什么都没
    判过的正文推到前面去交卷。

    这条**从模型返回体一路走到 `rank()`**，不是直接摆一个 `st.ev = None`：
    摆好的那种写法钉的是 `rank()` 自己（它本来就对），钉不住「解析失败要
    走到 `st.ev is None`」这件事——撤掉 1.7 的修复它照样绿。
    """
    import app.harness.adapter as adapter_mod
    from app.harness.loop import _score

    broken, judged = _st(), _st()
    monkeypatch.setattr(adapter_mod, "AppLLMClient", lambda: _FakeLLM("服务暂时不可用"))
    broken.ev = await _score(broken)
    monkeypatch.setattr(adapter_mod, "AppLLMClient", lambda: _FakeLLM(_GOOD))
    judged.ev = await _score(judged)       # 真判了全 0 分

    assert broken.rank() == (-1, -1.0)
    assert broken.rank() < judged.rank(), \
        "「没判上分」必须排在「判了 0 分」后面——两者混成一个数就是这条 bug 本身"


@pytest.mark.anyio
async def test_解析失败的那一轮不排只修不写(monkeypatch):
    """`Repair` 读的是整份分数向量。一份假的全 0 分会让三个内在质量维度
    同时"不达标" → 下一轮 `cleanup_only` → `produce()` 直接返回不写字。
    **一次解析失败白扔一轮**，而且它还会往 `repair_pending` 里记一笔，
    下一轮真判出来的分一比就成了「修完没动分」，把这三维一起判进
    `repair_failed`——**一次接口抖动能让三个维度从此再也排不上修复。**

    同样走真路径：摆好的 `st.ev = None` 撤掉修复也绿。
    """
    import app.harness.adapter as adapter_mod
    from app.harness.loop import _score
    from app.harness.middleware.repair import Repair

    monkeypatch.setattr(adapter_mod, "AppLLMClient", lambda: _FakeLLM("服务暂时不可用"))
    st = _st()
    st.skip_judge = False
    st.ev = await _score(st)
    evs = [e async for e in Repair().after_judge(st)]
    assert not st.bag.get("cleanup_only"), "没判过就不知道哪里坏了，修什么？"
    assert evs == [], "没判过也不该对用户宣称『下一轮只修不写』"
    assert not st.bag.get("repair_pending"), \
        "更要紧的是别记账：记了这一笔，下一轮真分数一比就被读成「修了没用」"


@pytest.mark.anyio
async def test_没打上分要计进停机安全网(monkeypatch):
    """一次解析失败下一轮就恢复了；连着失败跟"卡住了"在外部表现上没区别，
    所以共用 `no_change_rounds` 这一张网，不另发明一套策略。
    这条钉的是「解析失败也要进这张网」——它以前根本到不了这里。
    """
    import app.harness.adapter as adapter_mod
    from app.harness.loop import _score

    monkeypatch.setattr(adapter_mod, "AppLLMClient", lambda: _FakeLLM("{"))
    st = _st()
    for _ in range(3):
        st.ev = await _score(st)
        if st.ev is None:
            st.bag["no_change_rounds"] = st.bag.get("no_change_rounds", 0) + 1
    assert st.bag["no_change_rounds"] == 3


@pytest.mark.anyio
async def test_抽取判据的汇总不把解析失败算成质量差(monkeypatch):
    """第二个调用方：`database/kb/extract_judge.py`。它已经写着
    `except Exception → None`、并且只把 `evaluation` 非空的算进均值
    （`scored = [r for r in results if r.evaluation]`）——**接口早就是对的，
    只是打分器从来没走过那条路**，于是全 0 分被算进 `below_bar`，
    一次接口抖动被记成「抽取质量差」。1.7 顺手把这个也修了。
    """
    from app.harness.checks.rubric import ScoreParseError, evaluate

    llm = _FakeLLM("模型这次只回了一句话")
    with pytest.raises(ScoreParseError):
        await evaluate(llm, content="- [主题] 一条事实",
                       dimensions=[Dimension("self_contained", "...")])


def test_没打上分和判了0分在事件里也分得开():
    """用户那一端看到的也得是两种东西。`_ev_payload` 对没判过的一轮报
    `status="unknown"`，对真判过的报模型的裁决。
    """
    from app.harness.loop import _ev_payload
    from app.harness.types import DimensionScore, Evaluation

    unjudged = _st()
    assert _ev_payload(unjudged)["status"] == "unknown"
    assert _ev_payload(unjudged)["scores"] == {}

    judged = _st()
    judged.ev = Evaluation(scores={"coherence": DimensionScore(0, "散")},
                           status="continue", weakest="coherence")
    assert _ev_payload(judged)["status"] == "continue"
    assert _ev_payload(judged)["scores"]["coherence"]["level"] == 0


def test_不要通过给Evaluation加字段来表示没判上():
    """**钉住形态，不只是行为。** 「没判上分」在这个回路里已经有一种表示法
    了：`st.ev is None`（`rank()` 垫底、`Repair` 开头 `if not st.ev: break`、
    `_complete`/`_blocked` 全不触发、`_ev_payload` 报 unknown）。

    再给 `Evaluation` 加一个 `parse_failed` / `ok` 之类的字段，等于让下游
    每一处读分数的地方各判一次——漏掉任何一处，这条 bug 就原样回来了。
    `Evaluation` 还会走 `snapshot.py` 的落盘/还原，多一个字段就是多一份
    版本兼容。这条断言在有人加字段时会红，届时请先读完这段再决定。
    """
    import dataclasses

    from app.harness.types import Evaluation

    assert {f.name for f in dataclasses.fields(Evaluation)} == {
        "scores", "status", "weakest", "blocked_reason"}


def test_打分状态只有三种():
    """同上：也不要新造一个 `status="unscored"`。`Status` 这个字面量类型
    被 `RunRecord` / `snapshot` / 前端 SSE 一起认着。
    """
    import typing

    from app.harness.types import Status

    assert set(typing.get_args(Status)) == {"continue", "complete", "blocked"}


@pytest.mark.anyio
async def test_没打上分的一轮不许被判成质量退步(monkeypatch):
    """`_score()` 的 docstring 写着「返回 None 意味着这一轮只是没判：
    **没有停机条件会触发**」——第 766 轮实测这句话是假的。

    `_regressed` 只挡了 `skip_judge`（判据短路那种没判），漏了打分**调用
    失败**那种：`st.ev is None` → `rank()` 是 `(-1, -1.0)` → 一比就比最好
    那轮低 → 当场 `regressed` 收工。而它的武装条件是「最好那轮只差一个维度
    没达标」，正是**最不该这时候收工**的时刻：一次接口抖动把剩下的轮数全
    省掉，交的还是那份差一维的正文。
    """
    import app.harness.adapter as adapter_mod
    from app.harness.loop import _regressed, _score

    # **`max_rounds` 必须比 `st.round` 大。** 第一版没写这个参数，用的是默认
    # 的 3，而 `_regressed` 上面有一行 `st.round >= max_rounds → None`
    # （最后一轮本来就要交最好的，不用另起一个理由）——于是这条用例根本走不
    # 到要测的那行，把守卫改坏它照样绿。**突变没抓住，先怀疑用例不够。**
    monkeypatch.setattr(adapter_mod, "AppLLMClient", lambda: _FakeLLM("上游 502"))
    st = _st(max_rounds=5)
    st.round = 3
    st.best = ((2, 1.67), "最好那一轮的正文")      # 三维里两维达标 = 只差一个
    st.ev = await _score(st)

    assert st.ev is None, "前提：这一轮没打上分"
    assert st.rank() < st.best[0], "前提：垫底的排名确实比最好那轮低"
    assert _regressed(st) is None, "没判过 ≠ 变差了；这时候收工正好收在最不该收的地方"


def test_判据短路那种没判也一样不算退步():
    """同一条性质的另一半，本来就有，一起钉住：两种「没判过」不能只挡一种。"""
    from app.harness.loop import _regressed

    st = _st(max_rounds=5)
    st.round, st.best, st.skip_judge = 3, ((2, 1.67), "x"), True
    assert _regressed(st) is None
