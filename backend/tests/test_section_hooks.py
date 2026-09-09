"""分段 harness 的取材料和写这两步。

54 行里 36 行没被执行过。这里每条分支同样对着一次事故：撞到 token 上限
被拦腰切断时要把句子写完（删掉重写是唯一会丢工作量的处理）、已经写过的
段落要在拼接前丢掉（文件夹那条路的第一次 bench 就抓到一句话内部逐字
重复）、清理轮一个字都不许写。
"""

from __future__ import annotations

import asyncio

import pytest

from app.harness.hooks.section import SectionHooks
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import Dimension, Mode


def _st(content: str = "", **bag) -> State:
    mode = Mode(key="section", label="分段", skill_scope="test_scope",
                dims=(Dimension("coherence", "..."),))
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n", note_title="这一节"))
    st.content = content
    st.round = 1
    st.bag.update(bag)
    return st


def _hooks(**kw):
    kw.setdefault("goal", "写清楚这件事")
    kw.setdefault("other_summaries", [])
    return SectionHooks(**kw)


def _stream(monkeypatch, chunks, *, finish_reason="stop", tail=()):
    """打桩 llm.stream。第一次调用吐 chunks，之后吐 tail（补句子那一次）。"""
    from app.harness.hooks import section as mod

    calls = []

    async def fake(messages, *, max_tokens=None, stats=None, **kw):
        calls.append(messages)
        pieces = chunks if len(calls) == 1 else tail
        for p in pieces:
            yield p
        if stats is not None:
            stats["finish_reason"] = finish_reason

    monkeypatch.setattr(mod.llm, "stream", fake)
    return calls


def _produce(hooks, st) -> str:
    async def go():
        return "".join([p async for p in hooks.produce(st)])
    return asyncio.run(go())


def test_清理轮一个字都不写(monkeypatch):
    """修订已经在 Revise 的 before_produce 里做完了。这一轮存在的意义
    就是「别再往上加」。"""
    from app.harness.hooks import section as mod

    async def boom(*a, **kw):
        pytest.fail("清理轮不该调模型写东西")
        yield ""

    monkeypatch.setattr(mod.llm, "stream", boom)
    assert _produce(_hooks(), _st("已有正文", cleanup_only=True)) == ""


def test_撞到token上限要把那半句写完(monkeypatch):
    """删掉被切断的半句是唯一会丢工作量的处理。"""
    calls = _stream(monkeypatch, ["写到一半就被切断了，这句话还没"],
                    finish_reason="length", tail=["说完。"])
    st = _st("")
    out = _produce(_hooks(), st)
    assert out.endswith("说完。")
    assert len(calls) == 2, "撞上限了却没去补那半句"
    assert calls[1][-1]["content"].startswith("上面这段在句子中间被长度限制切断")


def test_正常收尾就不多花一次调用(monkeypatch):
    calls = _stream(monkeypatch, ["一段写完了。"], finish_reason="stop")
    _produce(_hooks(), _st(""))
    assert len(calls) == 1


def test_已经写过的段落在拼接前丢掉(monkeypatch):
    """这道防线一度只装在单篇那条 harness 上，文件夹那条路的第一次 bench
    就抓到一句话内部的逐字重复。"""
    # 至少 40 字：短于这个长度的段落不参与判重（太短的句子撞车太常见，
    # 按重复处理会误删）。
    重复段 = ("这是一段已经写过的话，写得足够长，长到能越过判重的长度门槛，"
              "于是模型再写一遍时会被认出来是同一段内容。")
    _stream(monkeypatch, [重复段 + "\n\n新写的一段。"])
    st = _st(重复段)
    _produce(_hooks(), st)
    assert st.content.count(重复段) == 1, "重复的段落没被丢掉"
    assert "新写的一段。" in st.content


def test_元话语在存下来之前被清掉(monkeypatch):
    _stream(monkeypatch, ["正文一句话。现有材料不足以说明这一点。另一句。"])
    st = _st("")
    _produce(_hooks(), st)
    assert "不足以说明" not in st.content


# ------------------------------------------------------------ 取材料 ---

def test_工具挂了退回关键词检索(monkeypatch):
    from app.harness.hooks import section as mod

    class T:
        calls: list = []
        error = True
        truncated = False
        used = False

        def as_facts(self):
            return []

    async def fake_gather(msgs, ctx, *, groups, **kw):
        return [], T()

    monkeypatch.setattr(mod.agent_loop, "gather_context", fake_gather)
    monkeypatch.setattr(mod.agent_loop, "is_scoped_question", lambda p: False)
    monkeypatch.setattr(mod.tools, "dispatch", lambda *a, **kw: "（没有）")
    monkeypatch.setattr(mod, "_retrieve", lambda *a, **kw: (["退路查到的"], [], 0.0))

    facts, _trace = asyncio.run(_hooks().prepare(_st("正文")))
    assert facts == ["退路查到的"]


def test_锚在某个具体场合的问题会多跑一次跨会话查找(monkeypatch):
    """「那次」「上周」这类分段标题需要多跳查找，普通工具循环自己够不到。"""
    from app.harness.hooks import section as mod

    class T:
        calls: list = []
        error = False
        truncated = False
        used = True

        def as_facts(self):
            return ["普通检索到的"]

    async def fake_gather(msgs, ctx, *, groups, **kw):
        return [], T()

    monkeypatch.setattr(mod.agent_loop, "gather_context", fake_gather)
    monkeypatch.setattr(mod.agent_loop, "is_scoped_question", lambda p: True)
    monkeypatch.setattr(mod.tools, "dispatch",
                        lambda name, args, ctx: ("多跳查到的\n（这行是提示，不算）"
                                                 if name == "search_session_context"
                                                 else "（没有）"))
    facts, _trace = asyncio.run(_hooks().prepare(_st("正文")))
    assert facts == ["多跳查到的", "普通检索到的"], "多跳的结果要排在前面"
