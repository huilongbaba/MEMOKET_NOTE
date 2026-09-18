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

from . import query_cache
from . import tools
from ..util import llm

# 工具循环最多来回几次。每一次 = 一次模型调用，本地模型 20-90 秒——
# 这是整个 harness 里最贵的东西，宁可让模型少查一轮也不能让单轮变成五分钟。
# 实测 2 次足够走完「先 list_topics 看有什么 → 再 filter_facts 精确查」
# 这个最有价值的两级路径。
MAX_TOOL_ITERS = 2

# 一次循环里总共最多执行几个工具调用（跨工具名累计），防止模型一次发十个。
MAX_CALLS_PER_ITER = 5

# **覆盖率驱动停机**（计划 2.5 / [MR] §2③ / [LED] §3）：一轮工具循环里，
# **连续这么多次调用没有带回新的事实 id 就停**。
#
# 换掉的是什么：停机原来只由 `policy.tool_iters`（1–4）决定，而策略器加减它
# 靠的是「上一轮用没用工具」——`policy.py` 自己的注释就记着**那个信号是脏的**
# （把「它诚实回答这段不用查」当成了「不需要检索能力」，真实 A/B 日志里预算
# 被一路扣到 0）。这一条是**确定性判断，不用模型**：覆盖率不再上升就停。
#
# 为什么是 2 不是 1：一发空手很常见（换个轴、换个工具就回来了），
# 1 会把正常的两级路径（`list_topics` 看有什么 → `filter_facts` 精确取）
# 当成走到头。**判据宁可窄一点，误伤比漏报贵。**
BARREN_STOP = 2

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
    # 覆盖率驱动停机（计划 2.5）留下的两个数。**`stopped_barren` 跟
    # `truncated` 是反义的**：前者是「查到头了，主动停」，后者是「还想查，
    # 被预算拦住」。合成一个字段就再也分不开这两件事——而 `adjust()` 只在
    # 前者为真时收预算，落库和 SSE 也是分开两栏给人看的。
    # （**`truncated` 今天没有任何策略在读**，见下面 break 那里的注释。）
    barren_calls: int = 0            # 这一轮有几次调用一条新 id 都没带回来
    stopped_barren: bool = False     # 是不是因为连着空手而提前停的

    @property
    def used(self) -> bool:
        return bool(self.calls)

    def merge(self, other: "ToolTrace") -> None:
        """把第二次工具循环的轨迹折进这一份。

        **为什么是一个方法而不是在调用点手写几行**（批 22）：`hooks/block.py`
        的补图那一轮原来写的是三行手抄——
        `trace.calls += …` / `trace.iters += …` / 就没了。
        `stopped_barren` / `error` / `truncated` / `barren_calls` **四个字段
        一个都没合并回来**，而它们各自有明确的读者：
        `middleware/runtime` 把 `stopped_barren` 喂给 `policy.adjust`，那是
        「工具预算 -1」唯一的判据（计划 2.5）——补图那一轮查到头了，策略器
        永远看不见；`error` 更直接，`hooks/block` 本来就没有
        `note` / `section` 那种 `trace.error and not facts` 的降级，
        第二次调用整个失败会**一点痕迹都没有**。
        写成方法之后「漏一个字段」这件事至少有一个地方可以钉住，
        `tests/test_tools.py` 里有一条逐字段的闸。
        """
        self.calls += other.calls
        self.iters += other.iters
        self.barren_calls += other.barren_calls
        self.truncated = self.truncated or other.truncated
        self.stopped_barren = self.stopped_barren or other.stopped_barren
        # 先出的那个错更接近根因；两次都挂的话第二条只是它的后果。
        self.error = self.error or other.error

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
    known_ids: set[str] | None = None,
) -> tuple[list[dict], ToolTrace]:
    """跑工具循环，返回 (要追加到 messages 后面的消息, 记录)。

    返回的追加消息包含每一轮的 assistant（带 tool_calls）和对应的 tool
    结果消息，顺序符合 OpenAI 工具协议。调用方把它们拼在原 messages 后面，
    再去做真正的流式续写——模型这时已经看得到自己查到的东西了。

    模型不调工具就返回空列表，行为跟没有工具时完全一致：这条路径必须是
    无损的，不能因为接了工具就让「不需要查」的场景变慢或变差。

    ``known_ids``：**进这次循环之前就已经有的事实 id**（计划 2.5）。
    传进来的是账本里那一份——这个函数自己只看得见本次循环，而重复检索是
    **跨轮**的（批 10 真跑：第 2 轮四次调用、`facts_new = 0`）。不给它这份
    清单，那一轮在停机判据眼里每一发都算「带回了新东西」。
    """
    trace = ToolTrace()
    spec = tools.specs(groups)
    if not spec:
        return [], trace

    convo = list(messages)
    extra: list[dict] = []
    seen_ids: set[str] = set(known_ids or ())
    barren = 0          # 连着几次调用一条新 id 都没带回来

    for _ in range(max_iters):
        try:
            msg = await llm.complete_raw(convo, max_tokens=max_tokens,
                                         temperature=temperature, tools=spec)
        except Exception as exc:  # noqa: BLE001
            # 工具阶段失败不该让续写跑不起来——退回「没查」，让续写照常进行。
            # 这跟修订调用失败的处理是同一个原则：不是关键路径就不许炸掉主流程。
            trace.error = f"{type(exc).__name__}: {exc}"
            # **已经配平的那几条照样交出去**（批 22）。原来写的是 `return [], trace`，
            # 而那一半跟 `trace` 对不上：`trace.calls` 里明明有第 1 轮查到的东西、
            # `trace.used` 是 True，消息列表却是空的。`hooks/note` / `hooks/section`
            # 用的是 `trace.as_facts()`，所以从来没露馅；**`hooks/block` 用的正是
            # `extra`**，于是补图那一轮的「上面已经查到的数据里，挑最值得看的画成图」
            # 指向一个空的「上面」，模型手上零数据被要求画图。
            # 交出去是安全的：异常发生在把这一轮的 assistant 消息 append 进去**之前**，
            # 此刻 `extra` 里每一条 `tool_call` 都已经有对应的 tool 回复。
            return extra, trace

        calls = msg.get("tool_calls") or []
        if not calls:
            # 模型不再要工具了。它这一轮可能顺手写了正文，但那是非流式产出，
            # 不能当续写用——真正的续写要走流式给前端 delta。这里只保留
            # 工具结果，把正文丢掉，让下游重新流式生成。
            break

        kept, truncated = _cap_calls(calls, iteration=trace.iters)
        trace.truncated = trace.truncated or truncated
        # **一条都没留下就当这一轮没发生，不许把空的 `tool_calls` 摆进消息列表。**
        # 批 22 查出来的，跟批 13 那条是同一个形状的另一个入口：那次是
        # 「assistant 宣称了 3 个 tool_call，后面只跟了 2 条 tool 回复」，这次是
        # 「assistant 宣称了 0 个」——接口对空数组同样是硬校验
        # （`Invalid 'messages[N].tool_calls': empty array`），一样直接 400。
        #
        # 走得到吗：第 2 轮起深度门（`_cap_calls` 的 `iteration >= 1`）会把
        # 纯广度的调用整批丢掉，而 `DEPTH_TOOLS` 上面那段注释记着的实测正是
        # **「4 次真实采样的工具循环全部撞上限，模型每轮都在广度上把预算花光
        # ——并行发 3-5 个 `search_memory`」**。也就是说「第 2 轮只发广度工具」
        # 恰恰是观测到的常态，而不是边角料。
        #
        # 后果有两档：① 这条消息进 `convo`，下一次 `complete_raw` 当场 400，
        # 被下面那个 `except` 吞成 `return [], trace`，第 1 轮查到的全丢；
        # ② 要是它落在最后一轮，就原样返回给调用方，`hooks/block.prepare`
        # 把 `msgs + extra` 喂给补图那一轮，同样 400、同样被吞——**画不出图
        # 而且没有任何痕迹**。
        #
        # 为什么是 `break` 不是 `continue`：`convo` 没变、`spec` 也没变，再问
        # 一次模型只会再发同一批广度调用，白烧一次 20-90 秒的调用。
        if not kept:
            break
        msg = dict(msg)
        msg["tool_calls"] = kept
        convo.append(msg)
        extra.append(msg)

        for call in kept:
            cid, name, raw_args = _parse_call(call)
            # 走短路层而不是 `tools.dispatch`：同一次跑里参数完全相同的查询
            # 不再打后端（计划 2.1）。同一轮内的重复连上下文都不再塞第二遍——
            # 那一份就在这个 convo 上面（`query_cache` 的模块文档有对照表）。
            result = query_cache.dispatch(name, raw_args, ctx)
            try:
                args = json.loads(raw_args or "{}")
            except json.JSONDecodeError:
                args = {"_raw": raw_args[:200]}
            trace.calls.append((name, args if isinstance(args, dict) else {}, result))
            tool_msg = {"role": "tool", "tool_call_id": cid, "name": name, "content": result}
            convo.append(tool_msg)
            extra.append(tool_msg)

            # ---- 覆盖率驱动停机（计划 2.5）----
            # **只有 FACT_TOOLS 参与计数。** `list_topics` / `list_entities`
            # 返回的是元信息，本来就不带事实 id，把它们算进「空手」的话，
            # 「先 list_topics 看有什么 → 再 filter_facts 精确取」这条两级
            # 路径会在第一步就被判定走到头——那是误伤，而误伤比漏报贵。
            if name in FACT_TOOLS:
                ids = set(fact_ids_in(result))
                if ids - seen_ids:
                    barren = 0
                else:
                    barren += 1
                    trace.barren_calls += 1
                seen_ids |= ids
                if barren >= BARREN_STOP:
                    # **只标记，不 break。** 这一条 assistant 消息里剩下的
                    # tool_call 照常执行完——第一版在这儿 break，于是那条
                    # assistant 消息带着 3 个 `tool_calls` 进了 `extra`，
                    # 而后面只跟着 2 条 tool 结果。`hooks/block.prepare` 会把
                    # `msgs + extra` 原样喂给第二次调用（EDA / ANALYSIS 的
                    # `focus_groups` 那一轮），而「带 tool_calls 的 assistant
                    # 消息后面必须跟齐每个 tool_call_id」是接口的硬校验，
                    # 缺一个直接 400。停机判据只该管「不再发起下一轮」。
                    trace.stopped_barren = True

        trace.iters += 1
        if trace.stopped_barren:
            # 这里 break 掉，下面那个 `else`（= 撞满 `max_iters`）就不会跑，
            # 于是 `truncated` 不会被这条路径置真。**「查到头了」跟「还想查、
            # 被预算拦住」是两件事**，落库和 SSE 都分开记。
            # （批 13 审查纠正：原注释写「策略器拿 `truncated` 去判要不要加
            # 预算」是**假的**——`RoundFeedback.tool_truncated` 全仓只有
            # `runtime.py` 写、没有一处读。`adjust()` 读的是
            # `tool_stopped_barren`。不要再拿一个没人读的字段当理由。）
            break
    else:
        # for 正常跑完 = 撞到 max_iters 时模型还想继续查
        trace.truncated = True

    return extra, trace
