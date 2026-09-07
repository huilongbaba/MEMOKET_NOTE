"""KITE 知识库工具——agent 自己决定要不要查、查什么。

跟原来那套预装配检索的区别不只是「谁发起」：预装配只有一条路径
（`recall()` 关键词召回 top-N），而 KITE 本身的能力面宽得多——主题树、
实体、结构化过滤、时间范围、以及**把一条事实回溯到原始对话行**。这些
能力此前只有前端用得到，写作 agent 一条都碰不到。工具化之后 agent 可以
先看知识库里有哪些主题，再决定往哪个方向查，查到可疑的事实还能拉出原文
核对——这是关键词召回做不到的。

每个工具都是零 LLM、亚毫秒级的本地读操作，可以放心让模型多调几次。
唯一的成本是 tool call 的往返（一次模型调用），所以工具的粒度要够粗：
宁可一次返回一屏信息，也不要让模型分五次问同一件事。
"""

from __future__ import annotations

from ..kite_memory import UserMemory
from .registry import ToolContext, register

# 单条事实在工具输出里的截断长度。事实本身通常一两句话，200 字足够完整，
# 又不会让一次返回 20 条时把 prompt 撑爆。
FACT_CHARS = 200
SOURCE_CHARS = 300


def _fmt_facts(rows: list[dict], *, with_id: bool = True) -> str:
    if not rows:
        return "（没有匹配的事实）"
    out = []
    for r in rows:
        head = f"[{r.get('id','')}] " if with_id and r.get("id") else ""
        # recall() 走 execute_plan，返回行的日期键是 ``date``；facts_page() /
        # facts_between() 走 _fact_dict()，键是 ``when``。两条路径键名不同，
        # 只读一个就会让 search_memory 的每一条都显示「无日期」——实测就是
        # 这样，agent 因此全程看不到任何时间信息。
        when = r.get("when") or r.get("date") or "无日期"
        who = r.get("who") or ""
        meta = " · ".join(x for x in (when, who, r.get("kind") or "") if x)
        out.append(f"{head}{r.get('text','')[:FACT_CHARS]}\n    （{meta}）")
    return "\n".join(out)


@register(
    name="search_memory",
    description=(
        "按关键词检索用户的个人知识库，返回最相关的若干条事实（带事实 id）。"
        "写到需要引用用户过往记录的地方时用这个。检索是关键词匹配，"
        "查不到就换个说法再试一次，或者改用 list_topics 先看知识库里有什么。"
    ),
    params={
        "query": {"type": "string", "description": "检索词，可以是一句话或几个关键词"},
        "limit": {"type": "integer", "description": "最多返回几条，默认 8"},
    },
    required=["query"],
)
def search_memory(ctx: ToolContext, query: str, limit: int = 8) -> str:
    rows, _terms, _took = UserMemory(ctx.user).recall(query, limit=max(1, min(int(limit or 8), 20)))
    hits = [r for r in rows if r.get("text")]
    return _fmt_facts(hits)


@register(
    name="list_topics",
    description=(
        "列出知识库里的主题及各自的事实条数。不知道该查什么、或者关键词"
        "检索没结果时先调这个，看看用户的记录实际覆盖了哪些方向，再决定"
        "往哪查。返回的 code 可以直接喂给 filter_facts 的 topic 参数。"
    ),
    params={
        "limit": {"type": "integer", "description": "最多返回几个主题，默认 40，按事实条数从多到少"},
    },
)
def list_topics(ctx: ToolContext, limit: int = 40) -> str:
    rows = UserMemory(ctx.user).topics()
    rows = [t for t in rows if t.get("fact_count")]
    rows.sort(key=lambda t: t["fact_count"], reverse=True)
    rows = rows[: max(1, min(int(limit or 40), 200))]
    if not rows:
        return "（知识库里还没有任何主题）"
    return "\n".join(
        f"- {t['code']}（{t['fact_count']} 条"
        + (f"，别名：{'、'.join(t['aliases'][:3])}" if t.get("aliases") else "")
        + "）"
        for t in rows
    )


@register(
    name="list_entities",
    description=(
        "列出知识库里的实体（人、组织、产品等）及各自的事实条数。"
        "要写跟某个人或某个产品有关的内容、但不确定用户记录里怎么称呼它时用这个。"
        "返回的 code 可以直接喂给 filter_facts 的 entity 参数。"
    ),
    params={
        "type": {"type": "string", "description": "只看某一类实体，比如 person / org / product；留空看全部"},
        "limit": {"type": "integer", "description": "最多返回几个，默认 40，按事实条数从多到少"},
    },
)
def list_entities(ctx: ToolContext, type: str = "", limit: int = 40) -> str:  # noqa: A002
    rows = UserMemory(ctx.user).entities()
    if type:
        rows = [e for e in rows if (e.get("type") or "").lower() == type.lower()]
    rows = [e for e in rows if e.get("fact_count")]
    rows.sort(key=lambda e: e["fact_count"], reverse=True)
    rows = rows[: max(1, min(int(limit or 40), 200))]
    if not rows:
        return "（没有匹配的实体）"
    return "\n".join(
        f"- {e['code']}｜{e.get('name') or e['code']}"
        + (f"（{e['type']}）" if e.get("type") else "")
        + f" — {e['fact_count']} 条"
        for e in rows
    )


@register(
    name="filter_facts",
    description=(
        "按主题 / 实体 / 类型精确过滤事实，不做关键词匹配。"
        "已经从 list_topics 或 list_entities 拿到确切的 code 之后用这个，"
        "比 search_memory 更准、不会漏。主题过滤含子主题。"
    ),
    params={
        "topic": {"type": "string", "description": "主题 code，含子主题"},
        "entity": {"type": "string", "description": "实体 code"},
        "kind": {"type": "string", "description": "事实类型"},
        "who": {"type": "string", "description": "说话人"},
        "limit": {"type": "integer", "description": "最多返回几条，默认 15"},
    },
)
def filter_facts(ctx: ToolContext, topic: str = "", entity: str = "",
                 kind: str = "", who: str = "", limit: int = 15) -> str:
    if not any((topic, entity, kind, who)):
        return "（filter_facts 至少要给一个过滤条件：topic / entity / kind / who）"
    rows, total = UserMemory(ctx.user).facts_page(
        topic=topic, entity=entity, kind=kind, who=who,
        limit=max(1, min(int(limit or 15), 50)))
    head = f"共 {total} 条，返回 {len(rows)} 条：\n" if total else ""
    return head + _fmt_facts(rows)


@register(
    name="facts_in_range",
    description=(
        "取某个日期区间内的所有事实，按时间正序。写复盘、周报、"
        "「上个月发生了什么」这类跟时间强相关的内容时用这个。日期是 YYYY-MM-DD。"
    ),
    params={
        "date_from": {"type": "string", "description": "起始日期，YYYY-MM-DD"},
        "date_to": {"type": "string", "description": "结束日期，YYYY-MM-DD"},
        "limit": {"type": "integer", "description": "最多返回几条，默认 30"},
    },
    required=["date_from", "date_to"],
)
def facts_in_range(ctx: ToolContext, date_from: str, date_to: str, limit: int = 30) -> str:
    rows = UserMemory(ctx.user).facts_between(date_from, date_to,
                                              limit=max(1, min(int(limit or 30), 100)))
    return _fmt_facts(rows)


@register(
    name="fact_sources",
    description=(
        "把一条事实回溯到它的原始对话行，返回说话人、日期和原话。"
        "拿不准某条事实到底是什么意思、或者要在正文里精确复述它时用这个——"
        "事实是被压缩过的转述，原话往往有更多上下文。事实 id 从 "
        "search_memory / filter_facts 的返回里取（方括号里那串）。"
    ),
    params={
        "fact_id": {"type": "string", "description": "事实 id"},
    },
    required=["fact_id"],
)
def fact_sources(ctx: ToolContext, fact_id: str) -> str:
    rows = UserMemory(ctx.user).fact_sources(fact_id)
    if not rows:
        return f"（找不到事实 {fact_id} 的原始出处，可能 id 不对）"
    return "\n".join(
        f"- {r.get('date') or '无日期'}｜{r.get('who') or '未知'}：{(r.get('text') or '')[:SOURCE_CHARS]}"
        for r in rows
    )


@register(
    name="search_session_context",
    description=(
        "多跳检索：先按内容定位到某次会话，再把那次会话里的其他内容一并取出。"
        "问题形如「在讨论 X 的那次会里还决定了什么」「聊 Y 的时候还提到哪些待办」"
        "——需要先找到某个场合、再看那个场合里还有什么——才用这个。"
        "**它要花约 10 秒**（需要一次查询编译），单纯找某个话题的事实用 "
        "search_memory 或 filter_facts，不要用这个。"
    ),
    params={
        "question": {"type": "string",
                     "description": "完整的一句话问题，说清楚「先定位什么、再要什么」"},
        "limit": {"type": "integer", "description": "最多返回几条，默认 10"},
    },
    required=["question"],
    group="memory",
    # 贵，一轮里最多一次
    max_calls_per_round=1,
)
def search_session_context(ctx: ToolContext, question: str, limit: int = 10) -> str:
    """词法检索做不到的那一类：跨跳定位。

    实测同一个问题「在讨论 APP 装不上的那次会议里，除了安装问题还提到了哪些
    待办」，search_memory 返回的是知识库里完全不相关的英语学习材料，这条路径
    返回的是同一次会议里的其他待办（手机端打开测试、多机型加载、图片适配、
    飞书群预览链接反馈）。

    模型判断问题不需要多跳时会编出单跳计划，那种情况下这条路径不比
    search_memory 好、只是更慢，所以结果里如实标出走没走多跳。
    """
    rows, multihop, took = UserMemory(ctx.user).recall_multihop(
        question, limit=max(1, min(int(limit or 10), 20)))
    head = (f"（{'走了多跳定位' if multihop else '这个问题被判定不需要多跳，退化成了普通检索'}"
            f"，耗时 {took / 1000:.1f}s）\n")
    return head + _fmt_facts(rows)
