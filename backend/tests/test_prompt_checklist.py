"""指令类两个模式：现场生成 checklist + 可程序验证的约束（计划 6.1 / 6.2）。

**验收以这份单测为主**（台账批 17）：`prompt` / `custom` 的真实语料在库里只有
零星几条，n=1 一律不下跨篇结论（批 11/13 定的硬约束）。所以这里的路子跟批 16
一样——构造各种指令，看抽出来的约束和生成出来的条目对不对。

每一条断言都对着一种**具体会误伤的写法**，不是"覆盖一下这个函数"。
"""

from __future__ import annotations

import asyncio

import pytest

from app.harness import checklist as synth
from app.harness import modes, params, snapshot
from app.harness.checks import instructions as I
from app.harness.checks import rubric
from app.harness.middleware.checklist import Checklist
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import Dimension


def _st(mode=modes.PROMPT, **bag) -> State:
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n"))
    st.bag.update(bag)
    return st


def _kinds(instruction: str) -> dict[str, str]:
    return {c.kind: c.value for c in I.extract(instruction)}


# ============================================== 6.2 抽约束：抽得对 ===

def test_字数上下限阿拉伯数字和中文数字都认():
    assert _kinds("整体不超过 200 字")["max_chars"] == "200"
    assert _kinds("200字以内写完")["max_chars"] == "200"
    assert _kinds("至少写 300 字")["min_chars"] == "300"
    assert _kinds("写三段就行")["min_paragraphs"] == "3"
    assert _kinds("分三点讲清楚")["min_bullets"] == "3"


def test_每段多少字不算整块多少字():
    """**第一版在自己的冒烟用例上当场撞到的误伤。**

    「写三段，每段不超过 100 字」抽成「整块不超过 100 字」，三段写下来必然
    超标——完全照做的产出被判不合格，下一轮还会被逼着去删。
    """
    got = _kinds("写三段，每段不超过 100 字")
    assert "max_chars" not in got
    assert got["min_paragraphs"] == "3"


def test_别用表格不许被抽成必须用表格():
    assert "table" not in _kinds("这段别用表格，用大白话讲")
    assert "table" not in _kinds("不要用表格")
    assert _kinds("用表格整理一下")["table"] == "1"
    assert _kinds("整理成表格形式")["table"] == "1"


def test_不要提到某个词抽成禁止而不是必须():
    cs = I.extract("写一段，不要提到「内部代号」")
    assert [(c.kind, c.value) for c in cs] == [("must_not_mention", "内部代号")]


def test_同一个词不会既必须出现又必须不出现():
    """`_MENTION` 的正则是 `_NOT_MENTION` 的子串，两条都留下的话产出怎么写
    都不合格——这是一条**结构性**的误伤，不是措辞问题。"""
    kinds = [c.kind for c in I.extract("别提到「甲方」")]
    assert kinds == ["must_not_mention"]


def test_不带引号的必须提到一律不抽():
    """「提到北京和上海的差异」里 X 到底是「北京」还是整个短语，抽不准。
    猜错就是拿一个用户没说过的词去卡产出。"""
    assert I.extract("必须提到北京和上海的差异") == ()


def test_抽出两个矛盾的数就整类作废():
    got = _kinds("先写 3 段，然后再分 5 段")
    assert "min_paragraphs" not in got
    got2 = _kinds("至少 500 字，但不超过 100 字")
    assert "min_chars" not in got2 and "max_chars" not in got2


def test_范围外的数不当成对产出的要求():
    assert "max_chars" not in _kinds("不超过 3 字")          # 不像是在说产出
    assert "min_bullets" not in _kinds("分 100 点")
    assert "min_chars" not in _kinds("至少 99999 字")


def test_抽不准的说法一条都不抽():
    for text in ("简明扼要地总结一下", "写得更专业一点", "帮我润色这段",
                 "参考上面那张表格写一段分析"):
        assert I.extract(text) == (), text


def test_一条指令抽出来的约束有上限():
    text = ("不超过 200 字，分三点，写三段，用表格，必须提到「甲」，"
            "必须提到「乙」，必须提到「丙」")
    assert len(I.extract(text)) <= I.MAX_CONSTRAINTS


def test_抽出来的约束带着指令原文():
    """报错时要把用户的原话念回去。重新措辞的话用户对不上自己写过什么。"""
    c = I.extract("整体不超过 200 字")[0]
    assert c.source == "不超过 200 字"


# ============================================== 6.2 验证：判得准 ===

def test_字数带容差():
    c = I.Constraint("max_chars", "100", "不超过 100 字")
    assert I.verify(c, "字" * 108) is True        # 超了 8%，不该开火
    assert I.verify(c, "字" * 150) is False


def test_代码围栏里的东西不算字数():
    """工具画的那张 mermaid 是判据自己要求必须原样搬进来的，
    算进字数会让「不超过 100 字」在一张图上当场开火。"""
    c = I.Constraint("max_chars", "100", "不超过 100 字")
    body = "结论在这里。\n\n```mermaid\n" + "xychart-beta\n" * 60 + "```\n"
    assert I.verify(c, body) is True


def test_英文产出按词算不按字母算():
    c = I.Constraint("max_chars", "10", "不超过 10 字")
    assert I.verify(c, "internationalization pipeline") is True
    assert I.verify(c, " ".join(["word"] * 30)) is False


def test_分三点认列表项也认三段():
    c = I.Constraint("min_bullets", "3", "分三点")
    assert I.verify(c, "- 甲\n- 乙\n- 丙\n") is True
    assert I.verify(c, "甲的事。\n\n乙的事。\n\n丙的事。\n") is True
    assert I.verify(c, "只说了一件事。") is False


def test_表格要真的是一张markdown表():
    c = I.Constraint("table", "1", "用表格")
    assert I.verify(c, "| 渠道 | 点击 |\n|---|---|\n| 甲 | 12 |\n") is True
    assert I.verify(c, "渠道：甲，点击 12。") is False


def test_必须提到忽略空白():
    c = I.Constraint("must_mention", "郑州航空港", "必须提到「郑州航空港」")
    assert I.verify(c, "落在 郑州 航空港 的那批货") is True
    assert I.verify(c, "落在别处的那批货") is False


def test_正文还没写出来时不判():
    """「没达标」和「无从判断」分不开的时候一律不开火——
    跟批 16 那条「没有工具输出就不判」是同一条纪律。"""
    for kind, value in (("max_chars", "100"), ("min_bullets", "3"),
                        ("table", "1"), ("must_mention", "甲")):
        assert I.verify(I.Constraint(kind, value, "x"), "") is None
        assert I.verify(I.Constraint(kind, value, "x"), "   \n ") is None


def test_不认识的类型不判成不合格():
    assert I.verify(I.Constraint("未来新加的", "1", "x"), "随便写点什么") is None


# ============================================== 6.2 判据接线 ===

def test_没有约束时判据一声不吭():
    assert I.instruction_constraints(_st()) is None


def test_判据打的是这个模式真有的维度():
    st = _st(prompt_constraints=[I.Constraint("table", "1", "用表格")])
    st.content = "一段没有表的正文。"
    v = I.instruction_constraints(st)
    assert v is not None
    assert v.dimension in {d.name for d in modes.PROMPT.dims}


def test_判据报错时先念用户的原话():
    st = _st(prompt_constraints=[I.Constraint("max_chars", "100", "不超过 100 字")])
    st.content = "字" * 400
    v = I.instruction_constraints(st)
    assert "不超过 100 字" in v.message and "400" in v.message


def test_第一条不合格的就返回不再往下数():
    st = _st(prompt_constraints=[
        I.Constraint("table", "1", "用表格"),
        I.Constraint("must_mention", "甲", "必须提到「甲」")])
    st.content = "没有表，也没有那个词。"
    assert "表格" in I.instruction_constraints(st).message


def test_无从判断的那一档不许被读成不合格():
    """**突变验第一轮漏掉的一条**（第 ㉗ 号：把 `is False` 写成 `is not True`）。

    `verify` 有三种返回值，而判据只认其中一种：`False` 才开火。`None`
    （正文还没写出来、数字数不出来、不认识的约束类型）被读成不合格的话，
    每一次跑的第一轮都会挨一记"没照做"——而那一轮正文都还没生成。
    """
    st = _st(prompt_constraints=[I.Constraint("max_chars", "100", "不超过 100 字")])
    st.content = ""
    assert I.instruction_constraints(st) is None
    st.content = "   \n  "
    assert I.instruction_constraints(st) is None
    st2 = _st(prompt_constraints=[I.Constraint("将来新加的", "1", "x")])
    st2.content = "随便写点什么。"
    assert I.instruction_constraints(st2) is None


def test_快照复原不出类时不判():
    """`snapshot._rebuild_dataclass` 复原失败会退化成 dict。
    那时候**宁可不判**——拿一个形状不明的东西去判不合格是最坏的一档。"""
    st = _st(prompt_constraints=[{"kind": "table", "value": "1", "source": "用表格"}])
    st.content = "没有表。"
    assert I.instruction_constraints(st) is None


def test_约束和条目都能过一遍快照():
    """暂停-恢复之后判的必须是同一张清单（否则恢复的跑会重新花一次调用，
    而且判据在暂停前后不一样，跨轮排名当场失效）。"""
    st = _st(prompt_constraints=[I.Constraint("table", "1", "用表格")],
             checklist=[synth.Item(text="要给出结论", quote="给出结论")])
    back = snapshot.loads(snapshot.dumps(st), modes.PROMPT)
    assert back.bag["prompt_constraints"][0] == I.Constraint("table", "1", "用表格")
    assert back.bag["checklist"][0] == synth.Item("要给出结论", "给出结论")


# ============================================== 6.1 生成清单 ===

_INSTRUCTION = "按会议纪要写一段，必须写清楚谁负责，并且给出下一步动作"


def test_解析带围栏的返回体():
    raw = ('```json\n{"items": [{"check": "写清楚谁负责", "quote": "谁负责"}]}\n```')
    assert synth.parse_items(raw) == (synth.Item("写清楚谁负责", "谁负责"),)


def test_解析不出来就是空的不抛():
    for raw in ("", "对不起我做不到", "{不是 json", '{"items": "不是数组"}'):
        assert synth.parse_items(raw) == ()


def test_依据对不上指令的条目丢掉():
    """**这是三道闸里最要紧的一道。** 模型很容易补上「语言流畅」这类通用条目，
    而通用条目对每一次产出判的都一样——正是 RaR 消融里效果更差的那一档。
    不是"请模型只写指令里有的"，是拿指令原文逐字核对它交上来的依据。
    """
    items = (synth.Item("写清楚谁负责", "谁负责"),
             synth.Item("语言要流畅自然", "行文流畅"))
    kept = synth.keep(items, _INSTRUCTION)
    assert kept == (synth.Item("写清楚谁负责", "谁负责"),)


def test_依据必须逐字对上_对上开头不算():
    """**突变验第一轮漏掉的一条**（第 ㉖ 号：`q in 指令` 改成 `q[:2] in 指令`）。

    「谁负责的排期」开头两个字确实在指令里，整句却是模型自己加的——
    模糊核对等于把这道闸换成「模型说它有依据」，而那正是它要挡的东西。
    """
    items = (synth.Item("写清楚谁负责的排期", "谁负责的排期"),)
    assert synth.keep(items, _INSTRUCTION) == ()


def test_程序已经判了的条目不再交给模型():
    cs = (I.Constraint("table", "1", "用表格"),)
    items = (synth.Item("要用表格呈现", "用表格"),
             synth.Item("写清楚谁负责", "谁负责"))
    kept = synth.keep(items, "用表格整理，必须写清楚谁负责", cs)
    assert [i.text for i in kept] == ["写清楚谁负责"]


def test_条目去重并且有条数上限():
    items = tuple(synth.Item(f"第 {i} 条要求", "下一步动作") for i in range(10))
    assert len(synth.keep(items, _INSTRUCTION)) == synth.MAX_ITEMS
    same = (synth.Item("写清楚谁负责", "谁负责"),
            synth.Item("写清楚谁负责", "谁负责"))
    assert len(synth.keep(same, _INSTRUCTION)) == 1


def test_条目太长要截断():
    """**突变验第一轮漏掉的一条**（第 ㉘ 号）。判词是每一轮都要重发的，
    一条 300 字的条目会把这两个模式的判词整块撑大三倍。"""
    long_text = "要" * 300
    items = synth.parse_items(
        '{"items": [{"check": "%s", "quote": "谁负责"}]}' % long_text)
    assert len(items[0].text) == synth.MAX_ITEM_CHARS


def test_太长的指令不生成():
    async def boom(*a, **kw):
        raise AssertionError("不该发这次调用")

    class LLM:
        complete = staticmethod(boom)

    out = asyncio.run(synth.synthesize(LLM(), "长" * (synth.MAX_INSTRUCTION_CHARS + 1)))
    assert out == ()


def test_生成出来的条目变成二元维度并且带着原文():
    dims = synth.to_dimensions((synth.Item("写清楚谁负责", "谁负责"),))
    assert dims[0].name == "checklist_1"
    assert dims[0].binary is True
    assert "写清楚谁负责" in dims[0].guidance and "谁负责" in dims[0].guidance


def test_端到端生成一次():
    class LLM:
        async def complete(self, messages, **kw):
            assert "谁负责" in messages[-1]["content"]
            return ('{"items": [{"check": "写清楚谁负责", "quote": "谁负责"},'
                    ' {"check": "结构清晰", "quote": "结构清晰"}]}')

    out = asyncio.run(synth.synthesize(LLM(), _INSTRUCTION))
    assert [i.text for i in out] == ["写清楚谁负责"]


# ============================================== 二元那一档 ===

def test_二元维度的判词里写明了不要给中间档():
    dims = [Dimension("checklist_1", "要给出结论。", binary=True),
            Dimension("follows_prompt", "照指令做了没有。")]
    prompt = rubric._build_prompt("正文", dims, None, ())
    lines = [ln for ln in prompt.splitlines() if ln.startswith("- ")]
    assert rubric._BINARY_PREFIX in lines[0]
    assert rubric._BINARY_PREFIX not in lines[1]


def _fake_llm(payload: str):
    class LLM:
        async def complete(self, messages, **kw):
            return payload
    return LLM()


def test_二元维度上的一分压成零分_普通维度不动():
    """判词里已经写了「不要给 1」，模型还是给了 1 —— 那说明它自己也觉得
    没完全做到。**只靠 prompt 说一句是靠自报保证的性质**，所以解析这一侧再压一次。
    """
    ev = asyncio.run(rubric.evaluate(
        _fake_llm('{"scores": {"checklist_1": {"level": 1, "note": "只做到一半"},'
                  ' "follows_prompt": {"level": 1, "note": "一般"}},'
                  ' "blocked": false}'),
        content="正文",
        dimensions=[Dimension("checklist_1", "要给出结论。", binary=True),
                    Dimension("follows_prompt", "照指令做了没有。")]))
    assert ev.scores["checklist_1"].level == 0
    assert ev.scores["follows_prompt"].level == 1


def test_二元维度判满足时照旧是满分():
    ev = asyncio.run(rubric.evaluate(
        _fake_llm('{"scores": {"checklist_1": {"level": 2, "note": "做到了"}},'
                  ' "blocked": false}'),
        content="正文",
        dimensions=[Dimension("checklist_1", "要给出结论。", binary=True)]))
    assert ev.scores["checklist_1"].level == 2 and ev.status == "complete"


# ============================================== middleware 接线 ===

class _Recorder:
    """记下发了几次调用——「多花一次调用」这件事要能被断言，不能靠读代码。"""

    def __init__(self, payload: str = '{"items": []}'):
        self.calls = 0
        self.payload = payload

    async def complete(self, messages, **kw):
        self.calls += 1
        return self.payload


@pytest.fixture
def fake_llm(monkeypatch):
    rec = _Recorder()
    from app.harness import adapter
    monkeypatch.setattr(adapter, "AppLLMClient", lambda *a, **kw: rec)
    return rec


def _before_run(st) -> None:
    asyncio.run(Checklist().before_run(st))


def test_跑前把条目挂成维度_把约束挂成判据(fake_llm, monkeypatch):
    fake_llm.payload = ('{"items": [{"check": "写清楚谁负责", "quote": "谁负责"}]}')
    st = _st(prompt="用表格整理，必须写清楚谁负责")
    _before_run(st)
    names = [d.name for d in st.mode.dims]
    assert names[:3] == [d.name for d in modes.PROMPT_DIMS]   # 原来那三条一个不动
    assert names[3:] == ["checklist_1"]
    assert I.instruction_constraints in st.mode.checks
    assert fake_llm.calls == 1


def test_生成不出来就退回原来那三条维度(fake_llm):
    fake_llm.payload = "模型今天不高兴"
    st = _st(prompt="帮我润色这段")             # 也抽不出任何确定性约束
    _before_run(st)
    assert st.mode is modes.PROMPT              # 一个字都没改
    assert st.bag["checklist"] == []


def test_模型抛异常也不许让这次跑崩(monkeypatch):
    class Boom:
        async def complete(self, *a, **kw):
            raise RuntimeError("接口断了")

    from app.harness import adapter
    monkeypatch.setattr(adapter, "AppLLMClient", lambda *a, **kw: Boom())
    st = _st(prompt="必须写清楚谁负责")
    _before_run(st)
    assert [d.name for d in st.mode.dims] == [d.name for d in modes.PROMPT_DIMS]


def test_只抽到约束没生成出条目时判据照样挂上(fake_llm):
    fake_llm.payload = '{"items": []}'
    st = _st(prompt="用表格整理一下")
    _before_run(st)
    assert I.instruction_constraints in st.mode.checks
    assert [d.name for d in st.mode.dims] == [d.name for d in modes.PROMPT_DIMS]


def test_开关关掉之后一次调用都不花(fake_llm, monkeypatch):
    monkeypatch.setattr(params, "PROMPT_CHECKLIST", False)
    st = _st(prompt="用表格整理，必须写清楚谁负责")
    _before_run(st)
    assert fake_llm.calls == 0
    assert st.mode is modes.PROMPT
    assert "prompt_constraints" not in st.bag


def test_用户什么都没打时不花调用(fake_llm):
    st = _st(prompt="   ")
    _before_run(st)
    assert fake_llm.calls == 0 and st.mode is modes.PROMPT


def test_恢复的跑不再花第二次调用(fake_llm):
    st = _st(prompt="必须写清楚谁负责",
             checklist=[synth.Item("写清楚谁负责", "谁负责")],
             prompt_constraints=[])
    _before_run(st)
    assert fake_llm.calls == 0
    assert [d.name for d in st.mode.dims][-1] == "checklist_1"


def test_custom生成时能看到被替换掉的那一段(fake_llm):
    seen = {}

    async def complete(messages, **kw):
        seen["user"] = messages[-1]["content"]
        return '{"items": []}'

    fake_llm.complete = complete
    st = _st(modes.CUSTOM, prompt="把这段改得更口语", selection="兹就前述事宜函告如下")
    _before_run(st)
    assert "兹就前述事宜函告如下" in seen["user"]


def test_只有指令类两个模式挂了这个middleware():
    """别的模式挂上去，生成出来的只会是通用条目——RaR 消融里更差的那一档。"""
    attached = {m.key for m in modes.ALL
                if any(type(x).__name__ == "Checklist" for x in m.extra_mw)}
    assert attached == {"prompt", "custom"}


# ============================================== 走一整趟循环 ===
#
# **建了判据不等于用了判据。** 上面那些都在单独构造 State，只能证明零件对；
# 下面两条把整趟跑起来——判据要真的到了打分器手上、真的能短路掉打分调用。

def _run_block(prompt: str, produced: str, monkeypatch, checklist_payload: str):
    from app.harness import adapter, agent_loop, loop
    from app.harness.agent_loop import ToolTrace
    from app.harness.hooks.block import BlockHooks
    from app.util import llm

    seen: dict = {"dims": None, "scored": 0, "rounds": []}

    async def gather(messages, ctx, *, groups=None, max_iters=3, **kw):
        return [], ToolTrace()

    async def stream(messages, **kw):
        yield produced

    async def score(st):
        seen["dims"] = [d.name for d in st.mode.dims]
        seen["scored"] += 1
        seen["rounds"].append(st.round)
        from app.harness.types import DimensionScore, Evaluation
        return Evaluation(
            scores={d.name: DimensionScore(level=2, note="ok") for d in st.mode.dims},
            status="complete")

    class LLM:
        async def complete(self, messages, **kw):
            return checklist_payload

    monkeypatch.setattr(adapter, "AppLLMClient", lambda *a, **kw: LLM())
    monkeypatch.setattr(agent_loop, "gather_context", gather)
    monkeypatch.setattr(llm, "stream", stream)
    monkeypatch.setattr(loop, "_score", score)

    st = State(mode=modes.PROMPT,
               ctx=ToolContext(user="u", note_id="n", content="", cursor=0))
    st.bag["prompt"] = prompt

    async def go():
        return [e async for e in loop.run(st, BlockHooks(prompt=prompt))], st

    events, st = asyncio.run(go())
    return events, st, seen


def test_一整趟跑下来生成的条目真的到了打分器手上(monkeypatch):
    events, st, seen = _run_block(
        "写一段，必须写清楚谁负责", "张三负责这件事，下周三前给结果。",
        monkeypatch,
        '{"items": [{"check": "写清楚谁负责", "quote": "谁负责"}]}')
    assert seen["dims"] == ["follows_prompt", "fits_context", "no_fabrication",
                            "checklist_1"]
    assert events[-1].data["reason"] == "complete"


def test_指令里的约束没做到时当场短路掉打分调用(monkeypatch):
    """一次打分调用是几十秒。约束是代码数出来的，数完就知道答案，
    没有任何理由再花这次钱（`middleware/checks` 的老规矩）。"""
    from app.harness.events import CUSTOM_CHECK_HIT

    events, st, seen = _run_block(
        "用表格整理一下这几个渠道", "渠道甲不错，渠道乙一般。",
        monkeypatch, '{"items": []}')
    hits = [e.data for e in events
            if e.data.get("name") == CUSTOM_CHECK_HIT or
            (isinstance(e.data.get("value"), dict) and "dimension" in e.data.get("value", {}))]
    notes = [str(h) for h in hits]
    assert any("表格" in n for n in notes), notes
    assert 1 not in seen["rounds"], "判据已经知道答案了，这一轮不该再花打分调用"
