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


def test_a_run_cannot_spend_its_whole_life_running_scripts(tmp_path, monkeypatch):
    """单轮 3 次的预算乘上十几轮就是三四十次执行，每次墙钟上限 30 秒。

    limits.MAX_RUNS_PER_HARNESS_RUN 写着整轮 run 的上限，但在这次自查之前
    没有代码读它。这里既测上限生效，也测**失败的执行照样记账**——否则一个
    一调用就报错的脚本可以无限重试。
    """
    import asyncio

    from app.harness.sandbox import limits
    from app.harness.tools import registry, sandbox_tools

    ran: list[str] = []

    async def fake_run(skill_dir, script, args, level):
        ran.append(script)
        raise sandbox_tools.sandbox.SandboxError("boom")

    monkeypatch.setattr(sandbox_tools.sandbox, "run", fake_run)
    monkeypatch.setattr(sandbox_tools.store, "skill_configs",
                        lambda user: {"demo": {"sandbox": "compute"}})
    root = tmp_path / "demo"
    (root / "scripts").mkdir(parents=True)
    monkeypatch.setattr(sandbox_tools.skills, "skills_root", lambda user: tmp_path)

    ctx = registry.ToolContext(user="u")
    out = [asyncio.run(sandbox_tools.run_skill_script(ctx, "demo", "s.py"))
           for _ in range(limits.MAX_RUNS_PER_HARNESS_RUN + 2)]

    assert len(ran) == limits.MAX_RUNS_PER_HARNESS_RUN
    assert "budget" in out[-1] and "budget" not in out[0]


def test_空知识库和这次没查到要说成两件事(monkeypatch):
    """第 676 轮：新用户跑续写，工具回「（没有匹配的事实）」——模型和策略器
    都把它读成「换个说法再试」，于是白烧一轮换检索路径。**空库要当场说死。**"""
    from app.harness.tools import memory_tools as mt

    class St:
        def __init__(self, facts): self.facts = facts

    monkeypatch.setattr(mt.UserMemory, "_index", lambda self: (St({}), None))
    assert mt.kb_is_empty("u")
    out = mt._fmt_facts([], user="u")
    assert "知识库是空的" in out and "不要再换检索词" in out
    assert "没有匹配的事实" not in out

    monkeypatch.setattr(mt.UserMemory, "_index", lambda self: (St({"f1": object()}), None))
    assert not mt.kb_is_empty("u")
    assert mt._fmt_facts([], user="u") == "（没有匹配的事实）"

    # 读不出索引时不猜：按原来那句走，别把「读失败」说成「库是空的」
    def boom(self): raise RuntimeError("坏了")
    monkeypatch.setattr(mt.UserMemory, "_index", boom)
    assert not mt.kb_is_empty("u")
    assert mt._fmt_facts([], user="u") == "（没有匹配的事实）"


def test_没有材料时占位符不再被判成谎话(monkeypatch):
    """第 676 轮实跑：空库 + 用户只写了一句话，模型给出一张
    `负责人 / 时间节点 / 衡量结果` 的表、格子里是 `[待填]`。原来这会判
    factual_grounding=0，要求「要么写出来，要么删掉」——**两条路都是死的**
    （写出来就是编，删掉表就没了）。占位符是谎话的前提是真话本来拿得到。"""
    from app.harness.checks import grounding
    from app.harness.tools import memory_tools as mt

    class Ctx:
        user = "u"

    class Dim:
        def __init__(self, n): self.name = n

    class Mode:
        dims = (Dim("factual_grounding"),)

    class St:
        content = "| P0 | [待填] | [待填] |\n\n这一节的负责人待定。"
        facts: list = []
        ctx = Ctx()
        bag: dict = {}
        mode = Mode()

    class Store:
        def __init__(self, facts): self.facts = facts

    monkeypatch.setattr(mt.UserMemory, "_index", lambda self: (Store({}), None))
    assert grounding.no_placeholder(St()) is None, "空库时占位符不该再被判"

    # 库里有材料：照旧要报——那时候「待填」才是真的在假装写完了
    monkeypatch.setattr(mt.UserMemory, "_index", lambda self: (Store({"f": 1}), None))
    v = grounding.no_placeholder(St())
    assert v is not None and "占位句" in v.message

    # 库是空的但这一轮手上有材料（用户贴进来的、上游传下来的）：也照旧要报
    st = St(); st.facts = ["某条材料"]
    monkeypatch.setattr(mt.UserMemory, "_index", lambda self: (Store({}), None))
    assert grounding.no_placeholder(st) is not None


def test_recall_接口把空库和没查到分开告诉前端(monkeypatch):
    """第 677 轮：`@` 引用那条路上说的是「知识库里没找到跟"样机"相关的记录」，
    对一个还没导过任何东西的人是误导——他会换词再试，试多少次都是空。
    判据放在 `UserMemory.is_empty()`（关于记忆库的事实归数据层），
    `/api/memory/recall` 把它带给前端。"""
    from app.database.kite.kite_memory import UserMemory

    class Store:
        def __init__(self, facts): self.facts = facts

    monkeypatch.setattr(UserMemory, "_index", lambda self: (Store({}), None))
    assert UserMemory("u").is_empty()

    monkeypatch.setattr(UserMemory, "_index", lambda self: (Store({"f": 1}), None))
    assert not UserMemory("u").is_empty()

    def boom(self): raise RuntimeError("索引读不出来")
    monkeypatch.setattr(UserMemory, "_index", boom)
    assert not UserMemory("u").is_empty(), "读失败不能说成「你没有材料」"


# --------------------------------------------- 覆盖率驱动停机（计划 2.5）

def _fact_rows(*ids: str) -> str:
    return "\n".join(f"[{i}] 某条事实\n    （2026-03-11 · Speaker A · 决定）"
                     for i in ids)


@pytest.mark.asyncio
async def test_连着两次没带回新id_工具循环自己停(clean_registry, monkeypatch):
    """计划 2.5。停机以前只由 `policy.tool_iters` 决定，而策略器加减它靠的是
    「上一轮用没用工具」——`policy.py` 自己的注释记着那个信号是脏的。

    换成确定性判据：连着两次调用一条新 id 都没带回来就停。
    """

    @registry.register(name="filter_facts", description="",
                       params={"topic": {"type": "string"}}, required=["topic"])
    def filter_facts(ctx, topic):
        return _fact_rows("f1", "f2")          # 每次都是同样那两条

    fake = FakeLLM([
        {"role": "assistant", "content": "",
         "tool_calls": [_call("filter_facts", {"topic": "定价"}, cid=f"c{i}")]}
        for i in range(10)
    ])
    monkeypatch.setattr(agent_loop.llm, "complete_raw", fake.complete_raw)

    _extra, trace = await agent_loop.gather_context(
        [{"role": "user", "content": "写"}], _ctx(), max_iters=4)
    assert trace.stopped_barren is True
    assert len(trace.calls) == 3, "第一发算新的，第二、三发空手 → 停"
    assert trace.barren_calls == 2
    assert trace.truncated is False, \
        "「查到头了」跟「还想查、被预算拦住」是两件事，落库和 SSE 分两栏记"


@pytest.mark.asyncio
async def test_跨轮已经有的id_算不上新的(clean_registry, monkeypatch):
    """`known_ids` 是账本那份。**批 10 真跑里第 2 轮 4 次调用、`facts_new = 0`**
    ——`prepare` 每轮新建 `ToolTrace`，循环自己看到的永远是空的，不把账本
    喂进来，那一轮在停机判据眼里每一发都是「新的」。"""

    @registry.register(name="filter_facts", description="",
                       params={"topic": {"type": "string"}}, required=["topic"])
    def filter_facts(ctx, topic):
        return _fact_rows("f1")

    fake = FakeLLM([
        {"role": "assistant", "content": "",
         "tool_calls": [_call("filter_facts", {"topic": f"t{i}"}, cid=f"c{i}")]}
        for i in range(10)
    ])
    monkeypatch.setattr(agent_loop.llm, "complete_raw", fake.complete_raw)

    _extra, trace = await agent_loop.gather_context(
        [{"role": "user", "content": "写"}], _ctx(), max_iters=4,
        known_ids={"f1"})
    assert trace.stopped_barren is True
    assert len(trace.calls) == 2, "第一发就是旧的了，所以两发就到头"


@pytest.mark.asyncio
async def test_元信息工具不算空手(clean_registry, monkeypatch):
    """`list_topics` / `list_entities` 返回的是主题名和条数，本来就不带事实 id。
    把它们算进「空手」的话，「先 list_topics 看有什么 → 再 filter_facts 精确取」
    这条两级路径会在第一步就被判走到头——**那是误伤，而误伤比漏报贵。**"""

    @registry.register(name="list_topics", description="", params={})
    def list_topics(ctx):
        return "- 定价（18 条）\n- 众筹（41 条）"

    @registry.register(name="list_entities", description="", params={})
    def list_entities(ctx):
        return "- Speaker A（12 条）"

    @registry.register(name="filter_facts", description="",
                       params={"topic": {"type": "string"}}, required=["topic"])
    def filter_facts(ctx, topic):
        return _fact_rows("f9")

    fake = FakeLLM([
        {"role": "assistant", "content": "",
         "tool_calls": [_call("list_topics", {}, cid="c1"),
                        _call("list_entities", {}, cid="c2")]},
        {"role": "assistant", "content": "",
         "tool_calls": [_call("filter_facts", {"topic": "定价"}, cid="c3")]},
        {"role": "assistant", "content": "好了"},
    ])
    monkeypatch.setattr(agent_loop.llm, "complete_raw", fake.complete_raw)

    _extra, trace = await agent_loop.gather_context(
        [{"role": "user", "content": "写"}], _ctx(), max_iters=4)
    assert trace.stopped_barren is False
    assert [c[0] for c in trace.calls] == ["list_topics", "list_entities", "filter_facts"]


@pytest.mark.asyncio
async def test_停机那一发不能把同一条消息里剩下的工具调用丢掉(clean_registry, monkeypatch):
    """**这是批 13 审查补的闸，钉住的是一条真的会 400 的路径。**

    第一版 2.5 的 `break` 打在「遍历这一条 assistant 消息里的若干个 tool_calls」
    那层循环上。于是停机那一发之后，同一条 assistant 消息里**剩下的
    tool_call 再也不会有对应的 tool 结果消息**——而 `extra` 里那条 assistant
    消息是带着全部 `tool_calls` 一起返回的。

    这不是洁癖：`hooks/block.prepare` 会把 `msgs + extra` 原样喂给第二次
    `gather_context`（EDA / ANALYSIS 的 `focus_groups` 那一轮），而
    OpenAI 兼容接口对「带 tool_calls 的 assistant 消息后面必须跟着每个
    tool_call_id 的 tool 消息」是**硬校验**，缺一个直接 400。
    EDA / ANALYSIS 的 groups 里有 `memory`（= FACT_TOOLS），
    `MAX_CALLS_PER_ITER` 又允许一条消息里发 5 个——触发条件齐全。

    所以停机判据只管**不再发起下一轮**，当前这条消息里已经发出去的调用
    照常执行完。**判据宁可窄一点，误伤比漏报贵。**
    """

    @registry.register(name="filter_facts", description="",
                       params={"topic": {"type": "string"}}, required=["topic"])
    def filter_facts(ctx, topic):
        return _fact_rows("f1")            # 永远是同一条，第二发起就算空手

    fake = FakeLLM([
        {"role": "assistant", "content": "",
         "tool_calls": [_call("filter_facts", {"topic": "a"}, cid="c1"),
                        _call("filter_facts", {"topic": "b"}, cid="c2"),
                        _call("filter_facts", {"topic": "c"}, cid="c3")]},
        {"role": "assistant", "content": "好了"},
    ])
    monkeypatch.setattr(agent_loop.llm, "complete_raw", fake.complete_raw)

    extra, trace = await agent_loop.gather_context(
        [{"role": "user", "content": "写"}], _ctx(), max_iters=4,
        known_ids={"f1"})
    assert trace.stopped_barren is True

    asked = [c["id"] for m in extra if m.get("role") == "assistant"
             for c in (m.get("tool_calls") or [])]
    answered = [m["tool_call_id"] for m in extra if m.get("role") == "tool"]
    assert asked == ["c1", "c2", "c3"]
    assert answered == asked, (
        "assistant 消息里的每一个 tool_call 都必须有对应的 tool 结果消息，"
        "否则 hooks/block 把 msgs+extra 喂给下一次调用时接口直接 400")


# --------------------------------------------------- 批 22：工具循环的两处半挡


@pytest.mark.asyncio
async def test_深度门把整轮丢光时不许留一条空的tool_calls(clean_registry, monkeypatch):
    """跟批 13 那条是同一个形状的另一个入口。

    第 2 轮起深度门（`_cap_calls` 的 `iteration >= 1`）丢掉纯广度的调用。
    模型这一轮**只发广度工具**时 `kept == []`，而原来的代码照样把
    `{"tool_calls": []}` 这条 assistant 消息 append 进 `convo` 和 `extra`
    ——接口对空数组是硬校验（`empty array. Expected ... minimum length 1`），
    下一次调用当场 400；要是它落在最后一轮，还会原样返回给
    `hooks/block.prepare`，把补图那一轮一起打死。

    「第 2 轮只发广度工具」不是边角料：`DEPTH_TOOLS` 上面那段注释记着的实测
    是「4 次真实采样全部撞上限，模型每轮都在广度上把预算花光」。
    """

    @registry.register(name="search_memory", description="",
                       params={"q": {"type": "string"}}, required=["q"])
    def search_memory(ctx, q):
        return "[f-1] 查到了"

    fake = FakeLLM([
        {"role": "assistant", "content": "",
         "tool_calls": [_call("search_memory", {"q": "第一轮"}, cid="c1")]},
        # 第 2 轮：全是广度工具，深度门会整批丢掉
        {"role": "assistant", "content": "",
         "tool_calls": [_call("search_memory", {"q": "第二轮"}, cid="c2")]},
        {"role": "assistant", "content": "好了"},
    ])
    monkeypatch.setattr(agent_loop.llm, "complete_raw", fake.complete_raw)

    extra, trace = await agent_loop.gather_context(
        [{"role": "user", "content": "写"}], _ctx(), max_iters=3)

    empty = [m for m in extra
             if m.get("role") == "assistant" and m.get("tool_calls") == []]
    assert not empty, f"交出去的消息列表里有一条空 tool_calls：{empty}"
    # 每一条 assistant 宣称的 tool_call 都得有对应的 tool 回复（批 13 那条性质）
    asked = {c["id"] for m in extra if m.get("role") == "assistant"
             for c in (m.get("tool_calls") or [])}
    answered = {m["tool_call_id"] for m in extra if m.get("role") == "tool"}
    assert asked == answered
    # 而且不该再问模型一次：convo 和 spec 都没变，只会拿回同一批广度调用
    assert len(fake.seen) == 2, "全被深度门丢掉之后应该直接收工，别再烧一次调用"
    assert trace.calls, "第 1 轮查到的东西要留着"


@pytest.mark.asyncio
async def test_中途调用挂了已经配平的那几条照样交出去(clean_registry, monkeypatch):
    """原来写的是 `return [], trace`，而那一半跟 `trace` 对不上：
    `trace.calls` 非空、`trace.used` 为真，消息列表却是空的。
    `hooks/note` / `hooks/section` 用 `trace.as_facts()` 所以没露馅，
    **`hooks/block` 用的正是 `extra`**——补图那一轮的「上面已经查到的数据里」
    会指向一个空的「上面」。"""

    @registry.register(name="fact_sources", description="",
                       params={"q": {"type": "string"}}, required=["q"])
    def fact_sources(ctx, q):
        return "[f-1] 查到了"

    class Boom(FakeLLM):
        async def complete_raw(self, messages, **kw):
            self.seen.append(list(messages))
            if len(self.seen) >= 2:
                raise RuntimeError("timeout")
            return {"role": "assistant", "content": "",
                    "tool_calls": [_call("fact_sources", {"q": "a"}, cid="c1")]}

    fake = Boom([])
    monkeypatch.setattr(agent_loop.llm, "complete_raw", fake.complete_raw)

    extra, trace = await agent_loop.gather_context(
        [{"role": "user", "content": "写"}], _ctx(), max_iters=3)

    assert trace.error, "前提：第二次调用真的挂了"
    assert [m["role"] for m in extra] == ["assistant", "tool"], \
        "第 1 轮那一对配平的消息不该跟着一起扔"
    asked = {c["id"] for m in extra if m.get("role") == "assistant"
             for c in (m.get("tool_calls") or [])}
    assert asked == {m["tool_call_id"] for m in extra if m.get("role") == "tool"}


def test_ToolTrace_merge_每个字段都合并了():
    """`hooks/block` 补图那一轮原来是手抄两个字段，漏了四个。

    逐字段过一遍而不是读实现的源码：**一条跟着被测实现一起写的断言，没有在
    断言任何东西**（台账 §21）。做法是每次只把 `other` 的一个字段设成非默认，
    合并之后 `base` 必须跟着变。
    """
    import dataclasses

    fields = [f.name for f in dataclasses.fields(al.ToolTrace)]
    assert set(fields) == {"calls", "iters", "truncated", "error",
                           "barren_calls", "stopped_barren"}, \
        "ToolTrace 加了新字段：merge 和这条闸都要跟着改"

    nondefault = {
        "calls": [("t", {}, "r")], "iters": 1, "truncated": True,
        "error": "boom", "barren_calls": 1, "stopped_barren": True,
    }
    for name in fields:
        base = al.ToolTrace()
        other = al.ToolTrace(**{name: nondefault[name]})
        base.merge(other)
        assert getattr(base, name) == nondefault[name], \
            f"merge 漏掉了 {name}——第二次工具循环的这个信号会静默消失"
