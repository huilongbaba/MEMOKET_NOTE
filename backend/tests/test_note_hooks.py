"""单篇 harness 的骨架这一步。

这里每个分支背后都写着一次真实事故——打磨模式为什么要关掉大纲保护、
用户自己的目录为什么不能被重新生成、骨架生成挂了为什么不能连累整场——
可跑覆盖率之前 `hooks/note.py` 114 行里 87 行没被执行过，这些结论一条
断言都没有。

除了那次模型调用全是确定性的。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.harness.hooks.note import NoteHooks
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import Dimension, Mode

# 一份「标题搭好了、内容还没填」的大纲：outline.is_outline() 认这个。
大纲 = ("## 一、背景\n\n## 二、硬件\n\n## 三、众筹\n\n"
        "## 四、时间线\n\n## 五、反思与展望\n\n")


def _st(content: str) -> State:
    mode = Mode(key="t", label="t", skill_scope="skeleton",
                dims=(Dimension("coherence", "..."),))
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n", note_title="标题"))
    st.content = content
    return st


def _stub(monkeypatch, payload):
    from app.harness.hooks import note as mod

    async def fake(messages, **kw):
        if payload is None:
            raise RuntimeError("模型挂了")
        return json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(mod.llm, "complete", fake)


def _drive(hooks, st):
    async def go():
        return [e async for e in hooks.skeleton(st)]
    return asyncio.run(go())


def test_用户自己写的目录直接当节拍不再生成一份(monkeypatch):
    """真实代价：用户写了九节的大纲等 AI 填，骨架这一步无视它、自己另造了
    一份节拍，写到最后「硬件」跑到了最底下、三个子标题没了、「反思与展望」
    整节消失。"""
    _stub(monkeypatch, {"spine": "模型自己想的", "beats": ["模型自己的节拍"]})
    hooks = NoteHooks(polish=False, spine="", beats=[], profile=[])
    st = _st(大纲)
    _drive(hooks, st)
    assert st.bag["outline_mode"] is True
    assert st.bag["beats"][:2] == ["一、背景", "二、硬件"], "用的不是用户的目录"
    assert "模型自己的节拍" not in st.bag["beats"]
    assert "按用户已有的目录逐节填充" in st.bag["spine"]


def test_打磨模式下大纲保护要关掉(monkeypatch):
    """两件事是直接对立的：打磨就是来修结构缺陷（重复标题、脚手架标题、
    编号错乱）的，而大纲保护是来冻结结构的。打磨的种子恰恰是「每节一句话」
    的短笔记——正好被 is_outline() 认成大纲，于是结构冻死，每一条想删掉
    重复标题的修订都被拒，non_repetition 连着二十轮 0 分。"""
    _stub(monkeypatch, {"spine": "打磨时该由模型给骨架", "beats": ["甲", "乙"]})
    hooks = NoteHooks(polish=True, spine="", beats=[], profile=[])
    st = _st(大纲)
    _drive(hooks, st)
    assert st.bag["outline_mode"] is False
    assert st.bag["beats"] == ["甲", "乙"]


def test_骨架生成挂了退回空骨架继续跑(monkeypatch):
    """没有骨架，spine_fidelity 和 beat_coverage 是靠更弱的证据判，不是没法
    判。为这个丢掉整场才是更糟的交易。"""
    _stub(monkeypatch, None)
    hooks = NoteHooks(polish=False, spine="", beats=[], profile=[])
    st = _st("一段普通正文，写得够长，不像大纲。" * 4)
    events = _drive(hooks, st)
    assert st.bag["spine"] == "" and st.bag["beats"] == []
    assert any(e.type.value == "RUN_ERROR" for e in events)
    assert any(e.data.get("name") == "skeleton" for e in events), \
        "失败也要把骨架事件发出去，前端面板才不会一直空着"


def test_已经有骨架就不再花一次模型调用(monkeypatch):
    from app.harness.hooks import note as mod

    async def boom(messages, **kw):
        pytest.fail("已经给了骨架，不该再调模型")

    monkeypatch.setattr(mod.llm, "complete", boom)
    hooks = NoteHooks(polish=False, spine="给定的张力", beats=["给定的节拍"],
                      profile=[])
    st = _st("一段普通正文。" * 20)
    _drive(hooks, st)
    assert st.bag["spine"] == "给定的张力"


def test_模型返回的节拍最多留六条(monkeypatch):
    _stub(monkeypatch, {"spine": "张力", "beats": [f"节拍{i}" for i in range(10)]})
    hooks = NoteHooks(polish=False, spine="", beats=[], profile=[])
    st = _st("一段普通正文，写得够长，不像大纲。" * 4)
    _drive(hooks, st)
    assert len(st.bag["beats"]) == 6


def test_模型返回垃圾时不会把骨架弄成半截(monkeypatch):
    _stub(monkeypatch, ["这不是个对象"])
    hooks = NoteHooks(polish=False, spine="", beats=[], profile=[])
    st = _st("一段普通正文，写得够长，不像大纲。" * 4)
    _drive(hooks, st)
    assert st.bag["spine"] == "" and st.bag["beats"] == []


# ------------------------------------------------------ 取材料这一步 ---
#
# 这几条同样是「每个分支背后一次事故」：先定这轮写哪一节再检索、策略只能
# 往工具组里加不能替换、工具挂了要退回零 LLM 的关键词检索。

def _prep(monkeypatch, *, facts=(), error=False, used=True, groups_seen=None,
          iters_seen=None):
    """把 agent_loop.gather_context 打桩，返回它拿到的 groups/max_iters。"""
    from app.harness.hooks import note as mod

    class T:
        def __init__(self):
            self.calls = [("recall", {}, "x")] if facts else []
            self.error = error
            self.truncated = False
            self.used = used

        def as_facts(self):
            return list(facts)

    async def fake_gather(msgs, ctx, *, groups, max_iters):
        if groups_seen is not None:
            groups_seen.extend(groups)
        if iters_seen is not None:
            iters_seen.append(max_iters)
        return [], T()

    monkeypatch.setattr(mod.agent_loop, "gather_context", fake_gather)
    monkeypatch.setattr(mod.agent_loop, "is_scoped_question", lambda p: False)
    monkeypatch.setattr(mod.tools, "dispatch", lambda name, args, ctx: "（没有）")
    return mod


def _run_prepare(hooks, st):
    return asyncio.run(hooks.prepare(st))


def test_打磨轮和清理轮不取材料(monkeypatch):
    """这两种轮次一个字都不写，新材料没有地方可去。"""
    mod = _prep(monkeypatch)

    async def boom(*a, **kw):
        pytest.fail("不该去取材料")

    monkeypatch.setattr(mod.agent_loop, "gather_context", boom)

    polish_facts, polish_trace = _run_prepare(NoteHooks(polish=True), _st("正文"))
    assert polish_facts == [] and polish_trace.calls == []

    cleanup = _st("正文")
    cleanup.bag["cleanup_only"] = True
    cleanup_facts, cleanup_trace = _run_prepare(NoteHooks(polish=False), cleanup)
    assert cleanup_facts == [] and cleanup_trace.calls == []


def test_先定这轮写哪一节再去检索(monkeypatch):
    """顺序一度是反的：检索时还不知道目标，于是每轮拿回同一批材料——模型
    手里全是众筹的料、却被要求写「团队」那节，只能换个标题把同样的话再说
    一遍。"""
    _prep(monkeypatch)
    st = _st(大纲)
    st.bag["outline_mode"] = True
    _run_prepare(NoteHooks(), st)
    assert st.bag["outline_target"] is not None, "检索之前就该定好写哪一节"


def test_策略只能往工具组里加不能替换(monkeypatch):
    """替换掉 Mode 给的工具组，正是 skill 工具当初变得不可达的原因。"""
    groups, iters = [], []
    _prep(monkeypatch, groups_seen=groups, iters_seen=iters)

    class P:
        extra_tool_groups = ("verify",)
        tool_iters = 5
        steer = ""
        require_verification = False

    st = _st("正文")
    st.bag["policy"] = P()
    _run_prepare(NoteHooks(), st)
    assert set(st.mode.groups) <= set(groups), "Mode 给的工具组被盖掉了"
    assert "verify" in groups
    assert iters == [5]


def test_工具挂了退回零LLM的关键词检索(monkeypatch):
    """一次偶发 500 会把这一轮推进最坏的状态——没材料，于是自己编——而
    一个两毫秒的退路就在旁边没人用。"""
    mod = _prep(monkeypatch, error=True, facts=())
    monkeypatch.setattr(mod, "_retrieve",
                        lambda *a, **kw: (["退路查到的"], [], 0.0))
    facts, _trace = _run_prepare(NoteHooks(), _st("正文"))
    assert facts == ["退路查到的"]


# ---------------------------------------------------------- 写这一步 ---

def _stream(monkeypatch, chunks, *, finish_reason="stop", tail=()):
    from app.harness.hooks import note as mod

    calls = []

    async def fake(messages, *, max_tokens=None, temperature=None, stats=None, **kw):
        calls.append(messages)
        for p in (chunks if len(calls) == 1 else tail):
            yield p
        if stats is not None:
            stats["finish_reason"] = finish_reason

    monkeypatch.setattr(mod.llm, "stream", fake)
    return calls


def _produce(hooks, st) -> str:
    async def go():
        return "".join([p async for p in hooks.produce(st)])
    return asyncio.run(go())


def test_打磨轮和清理轮都不写新内容(monkeypatch):
    from app.harness.hooks import note as mod

    async def boom(*a, **kw):
        pytest.fail("这两种轮次不该写新内容")
        yield ""

    monkeypatch.setattr(mod.llm, "stream", boom)
    assert _produce(NoteHooks(polish=True), _st("已有正文")) == ""
    st = _st("已有正文")
    st.bag["cleanup_only"] = True
    assert _produce(NoteHooks(polish=False), st) == ""


def test_被切断时补完那半句并且提醒补上没闭合的代码块(monkeypatch):
    """真实产出停在「这意味着」。删掉半句会把模型已经做的工作扔掉；而如果
    切在一个没闭合的 ``` 里，整段渲染都会坏。"""
    calls = _stream(monkeypatch, ["前面一段\n```python\nprint(1)"],
                    finish_reason="length", tail=["\n```\n收尾。"])
    _produce(NoteHooks(), _st(""))
    assert len(calls) == 2
    assert "还没闭合" in calls[1][-1]["content"]


def test_代码块闭合了就不多提醒(monkeypatch):
    calls = _stream(monkeypatch, ["```python\nprint(1)\n```\n还没写完"],
                    finish_reason="length", tail=["，补完。"])
    _produce(NoteHooks(), _st(""))
    assert "还没闭合" not in calls[1][-1]["content"]


def test_大纲模式把内容插进目标小节而不是追加到末尾(monkeypatch):
    """追加会让模型在下面另造一个同名标题，目录里「市场」出现两次。
    它自己写的标题要剥掉——提示词说了别写，它照写，还把用户的 ### 压平成 ##。"""
    _stream(monkeypatch, ["## 模型自己加的标题\n这一节的正文内容。"])
    st = _st(大纲)
    st.bag["outline_mode"] = True
    st.bag["outline_target"] = ("二、硬件", st.content.index("## 三、众筹"))
    _produce(NoteHooks(), st)
    assert "模型自己加的标题" not in st.content, "它写的标题没被剥掉"
    assert st.content.index("这一节的正文内容") < st.content.index("## 三、众筹"), \
        "内容被追加到末尾了，没插进目标小节"


def test_写出来是空的就什么都不改(monkeypatch):
    _stream(monkeypatch, ["   \n  "])
    st = _st("原有正文")
    _produce(NoteHooks(), st)
    assert st.content == "原有正文"


def test_追加时也丢掉已经写过的段落并清元话语(monkeypatch):
    重复段 = ("这是一段已经写过的话，写得足够长，长到能越过判重的长度门槛，"
              "于是模型再写一遍时会被认出来是同一段内容。")
    _stream(monkeypatch, [重复段 + "\n\n新的一段。现有材料不足以说明这一点。"])
    st = _st(重复段)
    _produce(NoteHooks(), st)
    assert st.content.count(重复段) == 1
    assert "新的一段。" in st.content and "不足以说明" not in st.content


def test_定向续写按第一行指令插进那一节(monkeypatch):
    """大纲填完之后所有新内容都堆在最后一节底下（实拍：讲硬件延期的段落离
    「硬件」隔了两千字）。模型第一行说放哪，位置由代码算，指令行不进正文。"""
    正文 = ("# 复盘\n\n## 时间线\n\n### APP\n\nAPP 那节已有的正文，足够长足够长足够长足够长足够长足够长。\n\n"
            "### 硬件\n\n硬件那节已有的正文，足够长足够长足够长足够长足够长足够长足够长。\n\n"
            "## 团队\n\n团队那节已有的正文，足够长足够长足够长足够长足够长足够长足够长足够长。\n")
    calls = _stream(monkeypatch, ["【放到：", "硬件】\n\n", "硬件延期的新段落。"])
    st = _st(正文)
    out = _produce(NoteHooks(), st)
    assert "放到" in calls[0][-1]["content"], "提示词里没让它先说放哪"
    assert out == "硬件延期的新段落。", "指令行不该流到前端"
    assert st.bag["insert_at"]["section"] == "硬件"
    assert st.content.index("硬件延期的新段落") < st.content.index("## 团队"), "没插进「硬件」那节"


def test_定向续写说文末或没写指令就追加(monkeypatch):
    正文 = "## 甲\n\n甲的正文足够长足够长足够长足够长足够长足够长足够长。\n\n## 乙\n\n乙的正文足够长足够长足够长足够长足够长足够长。\n"
    _stream(monkeypatch, ["【放到：文末】\n新段落在末尾。"])
    st = _st(正文)
    assert _produce(NoteHooks(), st) == "新段落在末尾。"
    assert st.bag["insert_at"] is None and st.content.rstrip().endswith("新段落在末尾。")
    _stream(monkeypatch, ["没有指令行直接写。\n第二行。"])
    st = _st(正文)
    assert _produce(NoteHooks(), st) == "没有指令行直接写。\n第二行。"
    assert st.content.rstrip().endswith("第二行。")
