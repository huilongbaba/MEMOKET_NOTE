"""Tool loop：让写作 agent 自己决定要不要查知识库、查什么。

放在 app 层而不是 harness 里，是刻意的边界选择：包的 ``LLMClient``
Protocol 只有 ``complete(messages) -> str``，把 tools 塞进去会破坏「包不做
任何 I/O、不认识具体能力」这条边界。工具执行本身就是 I/O，属于宿主应用。
包继续只做打分，这里做「装配上下文」。

**为什么工具阶段必须非流式**：续写是流式的，增量直接推给前端当 SSE
``delta``。如果把工具调用混进流式，前端会先收到一堆工具参数的碎片才等到
正文。所以分两段：先非流式地把工具循环跑完，模型不再要工具了，再把带着
工具结果的完整 messages 交给流式续写。代价是工具阶段每一轮多一次模型调用
（本地模型 20-90 秒），所以 ``MAX_TOOL_ITERS`` 要小。

**为什么每次调用都有预算**：模型会一次并行发好几个同义查询（实测本地模型
对一个问题一口气发了三个 recall，query 只是换了语序）。全部放行只是浪费
往返，所以按工具名做每轮上限截断。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import tools
from ..util import llm

# 工具循环最多来回几次。每一次 = 一次模型调用，本地模型 20-90 秒——
# 这是整个 harness 里最贵的东西，宁可让模型少查一轮也不能让单轮变成五分钟。
# 实测 2 次足够走完「先 list_topics 看有什么 → 再 filter_facts 精确查」
# 这个最有价值的两级路径。
MAX_TOOL_ITERS = 2

# 一次循环里总共最多执行几个工具调用（跨工具名累计），防止模型一次发十个。
MAX_CALLS_PER_ITER = 5

# **第二轮起只允许"基于上一轮结果"的后续查询**，广度查询（关键词撒网）不再放行。
#
# 实测数据逼出来的：4 次真实采样的工具循环**全部撞上限**（截断=True），模型
# 每轮都在广度上把预算花光——并行发 3-5 个 search_memory，第二轮预算就没了。
# 结果是需要两级的用法永远走不到：fact_sources 要「先查到事实拿 id、再用 id
# 回溯原话」，而策略控制器明明触发过 require_verification、检索规划 prompt 里
# 也明确写了要用它，它一次都没被调用过。
#
# 把预算从"按总数"改成"按深度"：第一轮随便撒网，第二轮的名额留给深挖。
DEPTH_TOOLS = frozenset({"fact_sources", "filter_facts", "search_session_context"})
BREADTH_TOOLS = frozenset({"search_memory", "list_topics", "list_entities"})

# 真正返回「知识库事实」的工具。其余（list_topics / list_entities）返回的是
# 元信息，只用来帮 agent 决定下一步查什么，不能当事实喂给写作。
FACT_TOOLS = frozenset({
    "search_memory", "filter_facts", "facts_in_range",
    "fact_sources", "search_session_context",
})


# 把检索范围锚定在「某个场合」上的说法。命中这些，问题就不是"找关于 X 的
# 事实"，而是"先定位到那一次，再看那一次里还有什么"——后者只有多跳做得到。
_SCOPED_PATTERNS = [
    r"那次", r"上次", r"上一次", r"当时", r"那场", r"那天", r"之前那",
    r"除了.{0,12}还", r"会上", r"讨论.{0,6}的时候", r"聊.{0,6}的时候",
]
_SCOPED_RE = re.compile("|".join(_SCOPED_PATTERNS))


def is_scoped_question(text: str) -> bool:
    """这段文字是不是在把范围锚定到某个具体场合上。

    为什么要用代码判、而不是写进提示词让模型自己选工具：实测在这个本地模型
    上，**关于"该用哪个工具"的提示词指令一直无效**。检索规划 prompt 里已经
    明确写了「问题里有『那次』『上次』『除了…还』就用 search_session_context」，
    模型照样只调 search_memory，然后把**另一次会议**的真实内容写在了
    「上次聊众筹定价的会上定了这些」标题下——张冠李戴，比明显编造更危险，
    因为每一条都是真的、看起来完全可信。

    这一晚上有效的两次改动都不是提示词，是结构改动（把检索决策拆成独立
    调用、把主题树预置进 prompt）。这里沿用同一个思路：形态由代码判定，
    命中就直接把多跳结果摆到模型面前，不指望它自己想到要去查。
    """
    return bool(_SCOPED_RE.search(text or ""))


@dataclass
class ToolTrace:
    """一次工具循环的完整记录，给 SSE 事件和溯源用。

    ``calls`` 里每项是 (工具名, 参数, 结果文本)——前端可以照着展示「这一轮
    agent 查了什么、查到了什么」，这跟已有的 TapProvenance 是同一个诉求：
    grounding 不能只是模型的一句自称，用户要能验证。
    """

    calls: list[tuple[str, dict, str]] = field(default_factory=list)
    iters: int = 0
    truncated: bool = False          # 是否因为撞上限而没让模型继续查
    error: str = ""

    @property
    def used(self) -> bool:
        return bool(self.calls)

    def summary(self) -> list[dict]:
        return [{"tool": n, "args": a, "result": r[:400]} for n, a, r in self.calls]

    def as_facts(self, limit: int = 12) -> list[str]:
        """把工具结果摊成【知识库事实】块要的字符串列表。

        续写那一步是流式的，不走工具协议——把这一阶段查到的东西转成续写
        prompt 本来就认识的事实块喂进去，比把 role=tool 消息塞进流式调用
        干净得多（流式 + 工具协议混用会让前端收到工具参数碎片）。

        工具返回的是给模型读的多行文本，这里按行拆开、丢掉空结果提示，
        每行当一条事实。保留工具名前缀，让模型知道这条是怎么查到的。
        """
        out: list[str] = []
        for name, _args, result in self.calls:
            if name not in FACT_TOOLS:
                # list_topics / list_entities 返回的是**元信息**（主题名、
                # 实体名 + 条数），不是事实。实测 agent 只调了 list_topics
                # 就停手，那份主题列表被原样当作「知识库事实」喂给续写，
                # 模型手里一条真事实都没有，整段正文全是编的。
                continue
            if not result or result.startswith("（"):
                continue        # 空结果/错误提示，不当事实喂给写作
            for line in result.splitlines():
                line = line.strip()
                if not line or line.startswith("共 "):
                    continue
                out.append(line.lstrip("- ").strip())
                if len(out) >= limit:
                    return out
        return out


# 工具输出里事实 id 的形态：``[terrence-2046-2F3] 正文……``
_FACT_ID_RE = re.compile(r"^\[([\w.-]+)\]", re.M)


def fact_ids_in(trace_or_text) -> list[str]:
    """从工具结果里抽出事实 id，供「回溯原话核对」这一步用。

    ``fact_sources`` 是两级用法（先查到事实拿 id、再用 id 回溯），实测模型
    从来不会自己走到第二级——预算在第一轮的广度撒网里就花光了。所以由代码
    抽 id、代码去回溯，跟多跳自动触发同一个套路。
    """
    text = trace_or_text
    if hasattr(trace_or_text, "calls"):
        text = "\n".join(r for _n, _a, r in trace_or_text.calls)
    seen: list[str] = []
    for m in _FACT_ID_RE.finditer(text or ""):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def _parse_call(call: dict) -> tuple[str, str, str]:
    """从一条 tool_call 里取出 (id, 名字, 原始参数字符串)。不同端点在
    嵌套层级上略有差异，这里一并容错。"""
    fn = call.get("function") or {}
    return (
        str(call.get("id") or ""),
        str(fn.get("name") or call.get("name") or ""),
        fn.get("arguments") if isinstance(fn.get("arguments"), str) else json.dumps(
            fn.get("arguments") or call.get("arguments") or {}, ensure_ascii=False),
    )


def _cap_calls(calls: list[dict], iteration: int = 0) -> tuple[list[dict], bool]:
    """按「每个工具每轮最多调几次」+ 总数上限 + **深度优先**截断。

    ``iteration`` 是第几轮（从 0 开始）。第二轮起丢掉纯广度的关键词撒网，
    只放行 DEPTH_TOOLS——理由见上面 DEPTH_TOOLS 的注释：实测模型会在第一轮
    就把预算全花在广度上，导致 fact_sources 这类两级用法永远轮不到。
    """
    per_tool: dict[str, int] = {}
    kept: list[dict] = []
    dropped_breadth = 0
    for call in calls:
        _cid, name, _args = _parse_call(call)
        if iteration >= 1 and name in BREADTH_TOOLS:
            dropped_breadth += 1
            continue
        tool = tools.get(name)
        cap = tool.max_calls_per_round if tool else 1
        if per_tool.get(name, 0) >= cap or len(kept) >= MAX_CALLS_PER_ITER:
            continue
        per_tool[name] = per_tool.get(name, 0) + 1
        kept.append(call)
    # 只因为深度优先被丢掉的，不算"撞预算上限"——那是刻意的取舍，不是资源不够
    truncated = len(kept) < (len(calls) - dropped_breadth)
    return kept, truncated


async def gather_context(
    messages: list[dict],
    ctx: tools.ToolContext,
    *,
    groups: list[str] | None = None,
    max_iters: int = MAX_TOOL_ITERS,
    max_tokens: int = 700,
    temperature: float = 0.3,
) -> tuple[list[dict], ToolTrace]:
    """跑工具循环，返回 (要追加到 messages 后面的消息, 记录)。

    返回的追加消息包含每一轮的 assistant（带 tool_calls）和对应的 tool
    结果消息，顺序符合 OpenAI 工具协议。调用方把它们拼在原 messages 后面，
    再去做真正的流式续写——模型这时已经看得到自己查到的东西了。

    模型不调工具就返回空列表，行为跟没有工具时完全一致：这条路径必须是
    无损的，不能因为接了工具就让「不需要查」的场景变慢或变差。
    """
    trace = ToolTrace()
    spec = tools.specs(groups)
    if not spec:
        return [], trace

    convo = list(messages)
    extra: list[dict] = []

    for _ in range(max_iters):
        try:
            msg = await llm.complete_raw(convo, max_tokens=max_tokens,
                                         temperature=temperature, tools=spec)
        except Exception as exc:  # noqa: BLE001
            # 工具阶段失败不该让续写跑不起来——退回「没查」，让续写照常进行。
            # 这跟修订调用失败的处理是同一个原则：不是关键路径就不许炸掉主流程。
            trace.error = f"{type(exc).__name__}: {exc}"
            return [], trace

        calls = msg.get("tool_calls") or []
        if not calls:
            # 模型不再要工具了。它这一轮可能顺手写了正文，但那是非流式产出，
            # 不能当续写用——真正的续写要走流式给前端 delta。这里只保留
            # 工具结果，把正文丢掉，让下游重新流式生成。
            break

        kept, truncated = _cap_calls(calls, iteration=trace.iters)
        trace.truncated = trace.truncated or truncated
        msg = dict(msg)
        msg["tool_calls"] = kept
        convo.append(msg)
        extra.append(msg)

        for call in kept:
            cid, name, raw_args = _parse_call(call)
            result = tools.dispatch(name, raw_args, ctx)
            try:
                args = json.loads(raw_args or "{}")
            except json.JSONDecodeError:
                args = {"_raw": raw_args[:200]}
            trace.calls.append((name, args if isinstance(args, dict) else {}, result))
            tool_msg = {"role": "tool", "tool_call_id": cid, "name": name, "content": result}
            convo.append(tool_msg)
            extra.append(tool_msg)

        trace.iters += 1
    else:
        # for 正常跑完 = 撞到 max_iters 时模型还想继续查
        trace.truncated = True

    return extra, trace
