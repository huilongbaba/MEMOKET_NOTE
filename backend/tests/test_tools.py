"""工具池与 tool loop 的单测。

工具池的价值在于「加一个工具 = 写一个带装饰器的函数」，所以测的重点是
注册/渲染/派发这套机制本身是否稳，以及**失败路径**——工具执行出问题
绝不能让整轮 harness 炸掉，这是它和普通业务代码最不一样的要求。
"""

from __future__ import annotations

import json

import pytest

from app.harness import agent_loop
from app.harness import agent_loop as al
from app.harness.tools import registry


@pytest.fixture
def clean_registry():
    """每个测试从干净的注册表开始，测完还原——不然装饰器的副作用会跨测试
    泄漏，也会污染真实的内置工具。"""
    snap = registry._snapshot()
    registry._reset_for_tests()
    yield registry
    registry._restore(snap)


def _ctx() -> registry.ToolContext:
    return registry.ToolContext(user="tester", note_id="n1", note_title="标题")


# ------------------------------------------------------------------ 注册与渲染

def test_register_and_spec_shape(clean_registry):
    @registry.register(name="echo", description="回显",
                       params={"text": {"type": "string"}}, required=["text"])
    def echo(ctx, text):
        return f"收到：{text}"

    specs = registry.specs()
    assert len(specs) == 1
    fn = specs[0]["function"]
    assert specs[0]["type"] == "function"
    assert fn["name"] == "echo"
    assert fn["parameters"]["required"] == ["text"]
    assert fn["parameters"]["properties"]["text"]["type"] == "string"


def test_groups_filter_which_tools_are_exposed(clean_registry):
    """分组是以后接 web browsing / 代码执行时的授权边界：harness 按 group
    决定暴露哪些，不用改注册表机制。"""

    @registry.register(name="mem", description="", params={}, group="memory")
    def mem(ctx):
        return ""

    @registry.register(name="web", description="", params={}, group="web")
    def web(ctx):
        return ""

    assert registry.names(["memory"]) == ["mem"]
    assert registry.names(["web"]) == ["web"]
    assert registry.names() == ["mem", "web"]
    assert len(registry.specs(["memory"])) == 1


def test_duplicate_name_is_rejected(clean_registry):
    @registry.register(name="dup", description="", params={})
    def a(ctx):
        return ""

    with pytest.raises(ValueError):
        @registry.register(name="dup", description="", params={})
        def b(ctx):
            return ""


# ------------------------------------------------------------------ 派发与容错

def test_dispatch_passes_parsed_arguments(clean_registry):
    @registry.register(name="add", description="",
                       params={"a": {"type": "integer"}, "b": {"type": "integer"}},
                       required=["a", "b"])
    def add(ctx, a, b):
        return str(a + b)

    assert registry.dispatch("add", json.dumps({"a": 1, "b": 2}), _ctx()) == "3"
    assert registry.dispatch("add", {"a": 4, "b": 5}, _ctx()) == "9"


def test_dispatch_never_raises(clean_registry):
    """工具的每一种失败都必须变成给模型看的文本，不能抛出去——模型看到
    「参数不对」是能自己纠正的，抛出去只会让整轮 harness 中断。"""

    @registry.register(name="boom", description="", params={})
    def boom(ctx):
        raise RuntimeError("炸了")

    @registry.register(name="need", description="",
                       params={"q": {"type": "string"}}, required=["q"])
    def need(ctx, q):
        return q

    assert "执行出错" in registry.dispatch("boom", "{}", _ctx())
    assert "没有名为" in registry.dispatch("nonexistent", "{}", _ctx())
    assert "不是合法 JSON" in registry.dispatch("need", "{不是json", _ctx())
    assert "缺少必填参数" in registry.dispatch("need", "{}", _ctx())


def test_dispatch_ignores_extra_arguments(clean_registry):
    """模型偶尔会多塞字段，直接 **args 会 TypeError。"""

    @registry.register(name="only_a", description="",
                       params={"a": {"type": "string"}}, required=["a"])
    def only_a(ctx, a):
        return a

    assert registry.dispatch("only_a", {"a": "x", "多余": 1}, _ctx()) == "x"


# ------------------------------------------------------------------ tool loop


class FakeLLM:
    """按脚本依次返回 assistant 消息，记录每次收到的 messages。"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen: list[list[dict]] = []

    async def complete_raw(self, messages, **kw):
        self.seen.append(list(messages))
        return self.replies.pop(0) if self.replies else {"role": "assistant", "content": ""}


def _call(name, args, cid="c1"):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


@pytest.mark.asyncio
async def test_loop_returns_nothing_when_model_does_not_call_tools(clean_registry, monkeypatch):
    """不调工具这条路径必须无损——接了工具不能让「不需要查」的场景变差。"""

    @registry.register(name="t", description="", params={})
    def t(ctx):
        return "x"

    fake = FakeLLM([{"role": "assistant", "content": "我直接写"}])
    monkeypatch.setattr(agent_loop.llm, "complete_raw", fake.complete_raw)

    extra, trace = await agent_loop.gather_context([{"role": "user", "content": "写"}], _ctx())
    assert extra == []
    assert not trace.used


@pytest.mark.asyncio
async def test_loop_appends_protocol_shaped_messages(clean_registry, monkeypatch):
    """tool 结果消息必须紧跟在发起调用的 assistant 消息之后，这是 OpenAI
    工具协议的硬要求，顺序错了下一次调用会 400。"""

    @registry.register(name="look", description="",
                       params={"q": {"type": "string"}}, required=["q"])
    def look(ctx, q):
        return f"查到 {q}"

    fake = FakeLLM([
        {"role": "assistant", "content": "", "tool_calls": [_call("look", {"q": "定价"})]},
        {"role": "assistant", "content": "好了"},
    ])
    monkeypatch.setattr(agent_loop.llm, "complete_raw", fake.complete_raw)

    extra, trace = await agent_loop.gather_context([{"role": "user", "content": "写"}], _ctx())
    assert [m["role"] for m in extra] == ["assistant", "tool"]
    assert extra[1]["tool_call_id"] == "c1"
    assert extra[1]["content"] == "查到 定价"
    assert trace.used and trace.iters == 1
    assert trace.calls[0][0] == "look"


@pytest.mark.asyncio
async def test_loop_caps_parallel_duplicate_calls(clean_registry, monkeypatch):
    """实测本地模型会对同一个问题一口气发三个同义查询。全放行只是浪费
    往返，按工具的 max_calls_per_round 截断。"""

    @registry.register(name="look", description="",
                       params={"q": {"type": "string"}}, required=["q"],
                       max_calls_per_round=2)
    def look(ctx, q):
        return f"查到 {q}"

    calls = [_call("look", {"q": f"查询{i}"}, cid=f"c{i}") for i in range(5)]
    fake = FakeLLM([
        {"role": "assistant", "content": "", "tool_calls": calls},
        {"role": "assistant", "content": "好了"},
    ])
    monkeypatch.setattr(agent_loop.llm, "complete_raw", fake.complete_raw)

    _extra, trace = await agent_loop.gather_context([{"role": "user", "content": "写"}], _ctx())
    assert len(trace.calls) == 2
    assert trace.truncated


@pytest.mark.asyncio
async def test_loop_stops_at_max_iters(clean_registry, monkeypatch):
    """每一次循环 = 一次模型调用（本地 20-90 秒），必须有硬上限。"""

    @registry.register(name="look", description="", params={})
    def look(ctx):
        return "x"

    fake = FakeLLM([
        {"role": "assistant", "content": "", "tool_calls": [_call("look", {}, cid=f"c{i}")]}
        for i in range(10)
    ])
    monkeypatch.setattr(agent_loop.llm, "complete_raw", fake.complete_raw)

    _extra, trace = await agent_loop.gather_context(
        [{"role": "user", "content": "写"}], _ctx(), max_iters=2)
    assert trace.iters == 2
    assert trace.truncated


@pytest.mark.asyncio
async def test_loop_degrades_to_no_tools_when_model_call_fails(clean_registry, monkeypatch):
    """工具阶段失败退回「没查」，续写照常进行——跟修订调用失败同一个原则：
    不是关键路径就不许炸掉主流程。"""

    @registry.register(name="look", description="", params={})
    def look(ctx):
        return "x"

    async def boom(messages, **kw):
        raise TimeoutError("端点超时")

    monkeypatch.setattr(agent_loop.llm, "complete_raw", boom)
    extra, trace = await agent_loop.gather_context([{"role": "user", "content": "写"}], _ctx())
    assert extra == []
    assert "TimeoutError" in trace.error


# ------------------------------------------------------------------ 内置工具

def test_builtin_memory_tools_are_registered():
    """内置工具跑在真实注册表上（不用 clean_registry），确认 import 即注册。"""
    from app.harness import tools

    for name in ("search_memory", "list_topics", "list_entities",
                 "filter_facts", "facts_in_range", "fact_sources"):
        assert tools.get(name) is not None, name
        assert tools.get(name).group == "memory"


def test_memory_tools_on_empty_codebook_return_text_not_errors(tmp_path, monkeypatch):
    """空知识库是新用户的常态，每个工具都必须给出可读的空结果而不是报错。"""
    from app.harness import tools
    from app.util.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "kite_data_dir", str(tmp_path), raising=False)
    ctx = tools.ToolContext(user="brand-new-user")

    assert "没有" in tools.dispatch("search_memory", {"query": "定价"}, ctx)
    assert "没有" in tools.dispatch("list_topics", {}, ctx)
    assert "没有" in tools.dispatch("list_entities", {}, ctx)
    assert "至少要给一个过滤条件" in tools.dispatch("filter_facts", {}, ctx)
    assert "找不到" in tools.dispatch("fact_sources", {"fact_id": "nope"}, ctx)


def test_as_facts_ignores_metadata_only_tools():
    """list_topics / list_entities 返回的是元信息（主题名 + 条数），不是事实。

    实测踩过：agent 只调了 list_topics 就收手，那份主题列表被原样当成
    「知识库事实」喂给续写——模型手里一条真事实都没有，整段正文全是编的。
    """
    from app.harness.agent_loop import ToolTrace

    t = ToolTrace()
    t.calls = [
        ("list_topics", {}, "- work_product_design（3155 条）\n- work（2862 条）"),
        ("list_entities", {}, "- memo_cat｜memo_cat — 93 条"),
    ]
    assert t.as_facts() == []          # 只有元信息 = 什么事实都没查到

    t.calls.append(("search_memory", {"query": "x"},
                    "[id1] Speaker B 说硬件设计没问题。\n    （2026-03-12 · speaker b）"))
    facts = t.as_facts()
    assert facts and any("硬件设计没问题" in f for f in facts)
    assert not any("work_product_design" in f for f in facts)


def test_scoped_question_detection():
    """把范围锚定到某个场合的说法，必须由代码识别——实测提示词层面的
    工具选择指令在本地模型上无效，模型会拿另一次会议的真实内容张冠李戴。"""
    from app.harness.agent_loop import is_scoped_question

    for yes in ["上次专门聊众筹定价的会上，除了价格本身还定了几件事",
                "在讨论 APP 装不上的那次会议里还提到了什么",
                "当时是怎么决定的", "那天会上说的排期", "聊定价的时候还提到哪些"]:
        assert is_scoped_question(yes), yes

    for no in ["硬件量产前的未决项", "定价要覆盖哪些成本",
               "样机阶段暴露的问题还没收敛完", ""]:
        assert not is_scoped_question(no), no


@pytest.mark.asyncio
async def test_second_iteration_reserves_budget_for_depth(clean_registry, monkeypatch):
    """第二轮起只放行深挖类工具，广度撒网不再占名额。

    实测逼出来的：4 次真实采样的工具循环全部撞上限，模型每轮都在广度上把
    预算花光（并行 3-5 个 search_memory），需要两级的 fact_sources
    （先拿 id、再回溯原话）永远轮不到——哪怕策略控制器已经触发了
    require_verification、prompt 里也明确要求用它。
    """

    @registry.register(name="search_memory", description="", params={},
                       max_calls_per_round=3)
    def sm(ctx):
        return "[id1] 某条事实"

    @registry.register(name="fact_sources", description="",
                       params={"fact_id": {"type": "string"}}, required=["fact_id"])
    def fs(ctx, fact_id):
        return f"- 2026-03-12｜speaker b：原话 {fact_id}"

    fake = FakeLLM([
        {"role": "assistant", "content": "",
         "tool_calls": [_call("search_memory", {}, "a1"), _call("search_memory", {}, "a2")]},
        # 第二轮模型既想继续撒网、又想回溯——只有回溯应该被放行
        {"role": "assistant", "content": "",
         "tool_calls": [_call("search_memory", {}, "b1"),
                        _call("fact_sources", {"fact_id": "id1"}, "b2")]},
        {"role": "assistant", "content": "好了"},
    ])
    monkeypatch.setattr(al.llm, "complete_raw", fake.complete_raw)

    _extra, trace = await al.gather_context(
        [{"role": "user", "content": "写"}], _ctx(), max_iters=3)
    used = [c[0] for c in trace.calls]
    assert used.count("search_memory") == 2      # 只有第一轮那两次
    assert "fact_sources" in used                # 深挖被放行了


def test_fact_ids_extracted_from_tool_output():
    """工具输出里的事实 id 要能被代码抽出来——自动回溯原话靠它。"""
    from app.harness.agent_loop import ToolTrace, fact_ids_in

    t = ToolTrace()
    t.calls = [("search_memory", {}, "[terrence-2046-2F3] 甲\n    （2026-03-31）\n"
                                     "[terrence-2046-2F5] 乙\n    （2026-05-01）"),
               ("filter_facts", {}, "共 390 条，返回 1 条：\n[terrence-2392-4F7] 丙")]
    assert fact_ids_in(t) == ["terrence-2046-2F3", "terrence-2046-2F5", "terrence-2392-4F7"]
    assert fact_ids_in("没有 id 的文本") == []


@pytest.mark.asyncio
async def test_retrieval_failure_falls_back_instead_of_writing_blind(monkeypatch):
    """检索规划失败时必须退回预装配检索，不能空手续写。

    实测遇到过本地模型服务端偶发 500（同样 payload 串行/并发/各种尺寸都
    复现不出来）。之前的处理是 facts=[] 直接往下写——等于因为一次偶发错误
    就把这一轮推进"没材料只能编造"那个已知最差状态，而手上有一条 2 毫秒、
    零模型调用的兜底路径没用。
    """

    async def boom(messages, **kw):
        raise RuntimeError("Server error '500 Internal Server Error'")

    monkeypatch.setattr(al.llm, "complete_raw", boom)
    extra, trace = await al.gather_context([{"role": "user", "content": "写"}], _ctx())
    # gather_context 本身只负责如实报告失败；降级由调用方做（见
    # note_harness / writing_plan 里 trace.error and not facts 那段）
    assert extra == [] and "500" in trace.error and not trace.as_facts()
