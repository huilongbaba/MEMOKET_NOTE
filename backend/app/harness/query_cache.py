"""查询级短路：一次跑里参数**完全相同**的知识库查询，只真的查一次。

**这一条是计划 2.1（[MR] §3.4），确定性、零风险、不依赖账本的任何别的部分。**

它治的是这个（`docs/harness-multiround-retrieval.md` §1）：

> `middleware/facts.py:41` 确实在去重：`fresh = [f for f in st.facts_new if f not in st.facts]`
> ——但这是**结果级**去重。查询已经发出去了、工具调用已经花掉了、
> **结果已经进过一次上下文了**，才在这里把重复的丢掉。

去重发生在付完钱之后。这里把它挪到付钱之前。

## 两种短路，分得很清楚，因为它们的代价完全不同

| 什么时候 | 返回什么 | 为什么 |
|---|---|---|
| **同一轮内**重复 | 一句「已经查过，结果在上面」 | 那一次的结果**就在这一轮的 convo 里**，再贴一遍是纯浪费 |
| **跨轮**重复 | 上次那份**完整结果** | 这一轮的 convo 是新拼的，上一轮的工具消息**不在里面**——退化成一句提示会让这一轮凭空少掉一批材料 |

**跨轮那一档必须原样返回全文**，这是实现里最容易写错、而且错了没有任何报错的
一处：省下的是后端那次查询（`search_session_context` 一次要 10 秒），
上下文一个字都不能少。

## 为什么是白名单，不是黑名单

「同参数 = 同结果」这个前提**不是所有工具都成立**：

* `data` 组（`list_tables` / `numbers_near_cursor` / `describe_table` …）读的是
  `ctx.content` 和 `ctx.cursor`——**正文每一轮都在变**，同参数的结果本来就该不同，
  短路它等于把第一轮的表冻住。
* `chart` / `image` 组会生成东西（`render_image` 要花钱、要等几十秒），
  它们是有副作用的，不是查询。
* `run_skill_script` 自己在 `ctx.scratch` 里记运行次数，短路会把配额算错。

所以只放行 `memory` 组里那些**纯读知识库**的：结果只由 `(user, scope, 参数)` 决定。
判据宁可窄一点——漏掉一个可短路的工具只是少省一次查询，多短路一个会让
同一轮的正文对着上一轮的表说话。

## 边界

* 缓存挂在 `ctx.scratch` 上（注册表那边明写「调用方自己的暂存区，工具池不解释它」），
  **不进 `st.bag`**：`snapshot.dumps` 会把 bag 整个序列化进快照，把几十 KB 的
  工具原文塞进去只是把快照撑大；跑恢复之后缓存重新攒是完全可以接受的。
* 出错的结果不缓存（`执行出错` / `执行失败`）——那是瞬时故障，缓存它等于把
  一次网络抖动钉死在整次跑上。**查空要缓存**：同一个查空的查询被发第二次，
  正是 `docs/harness-multiround-retrieval.md` §5 那张判据表里要压到 0 的一条。
"""

from __future__ import annotations

import json

from . import tools

# 能短路的工具：只读知识库，结果只由 (user, scope, 参数) 决定。
# **加一个名字进来之前先确认它不读 `ctx.content` / `ctx.cursor`、也没有副作用。**
CACHEABLE = frozenset({
    "search_memory", "list_topics", "list_entities", "filter_facts",
    "facts_in_range", "fact_sources", "search_session_context", "gather_subject",
})

# 同一轮里重复时返回这句。**它会被模型读到**，所以顺带告诉它下一步该干嘛——
# 只说「重复了」而不给出路，实测模型会原样再发一次。
SAME_ROUND = ("（这次已经查过参数完全相同的 {tool}，结果就在上面，不再贴第二遍。"
              "要新材料就换个查法、换个角度，或者换一个工具。）")

_KEY = "query_cache"
SEP = "\t"

# 瞬时故障的标志：`registry.dispatch` 把异常转成这两种文本。缓存它们会把一次
# 网络抖动钉死到整次跑上。
_TRANSIENT = ("执行出错", "执行失败")


def _cache(ctx) -> dict:
    cache = ctx.scratch.get(_KEY)
    if not isinstance(cache, dict):
        cache = {"entries": {}, "round": -1,
                 "run": {"calls": 0, "hits": 0, "skipped": 0},
                 "this_round": {"calls": 0, "hits": 0, "skipped": 0}}
        ctx.scratch[_KEY] = cache
    return cache


def key(tool: str, args: dict, ctx=None) -> str:
    """一次查询的身份。**参数按键排序**——同样的查询换个参数顺序写出来是两个
    字符串，那样重复查询永远统计不出来（跟 `middleware/ledger._key` 同一条理由）。

    `user` / `scope` 也进身份：缓存本身是跑级的，但一个 ToolContext 的这两项
    理论上能被改，混着算会取回**别人的**材料——这种错一旦发生是数据事故，
    多两个字段换绝不会发生，值。
    """
    try:
        body = json.dumps(args or {}, sort_keys=True, ensure_ascii=False)
    except TypeError:
        body = repr(sorted((args or {}).items()))
    who = f"{getattr(ctx, 'user', '')}/{getattr(ctx, 'scope', '')}" if ctx is not None else ""
    return who + SEP + tool + SEP + body


def begin_round(ctx, round_: int) -> None:
    """新的一轮开始了。跨轮的重复要原样返回全文，所以「这一轮」必须有人报。"""
    cache = _cache(ctx)
    cache["round"] = int(round_)
    cache["this_round"] = {"calls": 0, "hits": 0, "skipped": 0}


def stats(ctx) -> dict:
    """`{run: {...}, this_round: {...}}`。`hits` = 省掉的后端查询次数，
    `skipped` = 连上下文都没再塞一遍的次数（前者包含后者）。"""
    cache = _cache(ctx)
    return {"run": dict(cache["run"]), "this_round": dict(cache["this_round"])}


def repeat_rate(ctx) -> float:
    """这次跑里重复查询占比。**短路要能被观测到**，否则「做了」和「没做」长得一样。"""
    run = _cache(ctx)["run"]
    return (run["hits"] / run["calls"]) if run["calls"] else 0.0


def dispatch(name: str, args: dict | str, ctx) -> str:
    """跟 `tools.dispatch` 同签名同返回，中间多一层短路。

    调用方不需要知道自己是不是被短路了——这是刻意的：`hooks/note.py` 那三处
    直接调用（`list_topics` 进 prompt、`fact_sources` 回溯原话、
    `search_session_context` 多跳）各自把结果当文本用，任何一处要是拿到
    「已经查过」那句提示，prompt 里就会凭空少一块，而且**没有任何报错**。
    """
    cache = _cache(ctx)
    cache["run"]["calls"] += 1
    cache["this_round"]["calls"] += 1
    if name not in CACHEABLE:
        return tools.dispatch(name, args, ctx)

    parsed = args
    if isinstance(args, str):
        try:
            parsed = json.loads(args or "{}")
        except json.JSONDecodeError:
            parsed = None                       # 参数本身就不合法，交给 dispatch 去报错
    if not isinstance(parsed, dict):
        return tools.dispatch(name, args, ctx)

    k = key(name, parsed, ctx)
    hit = cache["entries"].get(k)
    if hit is not None:
        cache["run"]["hits"] += 1
        cache["this_round"]["hits"] += 1
        hit["n"] += 1
        if hit["round"] == cache["round"]:
            cache["run"]["skipped"] += 1
            cache["this_round"]["skipped"] += 1
            return SAME_ROUND.format(tool=name)
        # 跨轮：这一轮的上下文里没有它，**必须原样给全**。给完这一轮就算"贴过了"。
        hit["round"] = cache["round"]
        return hit["result"]

    result = tools.dispatch(name, args, ctx)
    if not any(flag in result[:40] for flag in _TRANSIENT):
        cache["entries"][k] = {"result": result, "round": cache["round"], "n": 1}
    return result
