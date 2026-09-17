"""查询级短路（`harness/query_cache.py`，计划 2.1）。

要钉的是三件事，每一件都对应一种"改坏了也没有症状"的失败：

1. **同参数的第二次不打后端。** 这是这条改动的全部收益，而收益是看不见的
   ——后端被多查一次，产出一模一样。
2. **跨轮的重复必须原样返回全文。** 退化成一句「已经查过」时，这一轮的
   上下文里凭空少一批材料，而且**没有任何报错**：正文会照常写出来，只是
   写得更空。这是这个文件里最贵的一条用例。
3. **只短路那些「同参数就该同结果」的工具。** `data` 组读的是当前正文，
   正文每轮都在变；短路它等于让第三轮的分析对着第一轮的表说话。
"""

from __future__ import annotations

import pytest

from app.harness import query_cache, tools


@pytest.fixture
def ctx():
    return tools.ToolContext(user="u", note_id="n")


@pytest.fixture
def counting(monkeypatch):
    """把真正的派发换成一个计数器，工具池本身不参与。"""
    calls: list[tuple[str, dict]] = []

    def fake(name, args, _ctx):
        import json
        parsed = json.loads(args) if isinstance(args, str) else dict(args or {})
        calls.append((name, parsed))
        return f"结果#{len(calls)}\n[f1] 甲\n    （2026-03-11 · A · 决定）"

    monkeypatch.setattr(query_cache.tools, "dispatch", fake)
    return calls


def test_同一轮里同参数的第二次不打后端(ctx, counting):
    query_cache.begin_round(ctx, 1)
    first = query_cache.dispatch("search_memory", {"query": "众筹"}, ctx)
    second = query_cache.dispatch("search_memory", {"query": "众筹"}, ctx)
    assert len(counting) == 1
    assert "结果#1" in first
    assert second.startswith("（这次已经查过")


def test_参数顺序不同但内容相同_也算同一个查询(ctx, counting):
    query_cache.begin_round(ctx, 1)
    query_cache.dispatch("search_memory", {"query": "众筹", "limit": 8}, ctx)
    query_cache.dispatch("search_memory", {"limit": 8, "query": "众筹"}, ctx)
    assert len(counting) == 1


def test_换了参数就是另一个查询_照样打后端(ctx, counting):
    query_cache.begin_round(ctx, 1)
    query_cache.dispatch("search_memory", {"query": "众筹"}, ctx)
    query_cache.dispatch("search_memory", {"query": "定价"}, ctx)
    assert len(counting) == 2


def test_跨轮的重复原样返回全文(ctx, counting):
    """**这一条最要紧。** 第 2 轮的 convo 是新拼的，上一轮的工具消息不在
    里面——返回一句「已经查过」等于让这一轮少掉一批材料，而且不报错。"""
    query_cache.begin_round(ctx, 1)
    first = query_cache.dispatch("list_topics", {"limit": 40}, ctx)
    query_cache.begin_round(ctx, 2)
    again = query_cache.dispatch("list_topics", {"limit": 40}, ctx)
    assert again == first                      # 一个字都不能少
    assert len(counting) == 1                  # 后端还是只查了一次


def test_跨轮拿回全文之后_同一轮内再来一次才退化成提示(ctx, counting):
    query_cache.begin_round(ctx, 1)
    query_cache.dispatch("list_topics", {"limit": 40}, ctx)
    query_cache.begin_round(ctx, 2)
    query_cache.dispatch("list_topics", {"limit": 40}, ctx)           # 全文
    third = query_cache.dispatch("list_topics", {"limit": 40}, ctx)   # 这一轮贴过了
    assert third.startswith("（这次已经查过")


def test_读当前正文的工具一律不短路(ctx, counting):
    """`data` 组读 `ctx.content` / `ctx.cursor`，正文每轮都在变——
    同参数同结果这个前提在它们身上不成立。"""
    query_cache.begin_round(ctx, 1)
    query_cache.dispatch("list_tables", {}, ctx)
    query_cache.dispatch("list_tables", {}, ctx)
    assert len(counting) == 2


def test_白名单里没有任何会写东西或读正文的工具():
    """名单是手写的，就得有东西盯着它别长歪。"""
    import app.harness.tools  # noqa: F401  （触发注册）
    from app.harness.tools import registry

    for name in query_cache.CACHEABLE:
        tool = registry.get(name)
        assert tool is not None, f"白名单里的 {name} 不是一个真工具"
        assert tool.group == "memory", f"{name} 不在 memory 组，它凭什么同参数同结果"


def test_查空的结果要缓存(ctx, monkeypatch):
    """同一个查空的查询被发第二次，正是判据表里要压到 0 的一条
    （`docs/harness-multiround-retrieval.md` §5）。"""
    n = []
    monkeypatch.setattr(query_cache.tools, "dispatch",
                        lambda *a: (n.append(1), "（没有匹配的事实）")[1])
    query_cache.begin_round(ctx, 1)
    query_cache.dispatch("search_memory", {"query": "不存在"}, ctx)
    query_cache.dispatch("search_memory", {"query": "不存在"}, ctx)
    assert len(n) == 1


def test_出错的结果不缓存(ctx, monkeypatch):
    """瞬时故障缓存下来，等于把一次网络抖动钉死到整次跑上。"""
    n = []
    monkeypatch.setattr(query_cache.tools, "dispatch",
                        lambda *a: (n.append(1), "（search_memory 执行出错：Timeout）")[1])
    query_cache.begin_round(ctx, 1)
    query_cache.dispatch("search_memory", {"query": "a"}, ctx)
    query_cache.dispatch("search_memory", {"query": "a"}, ctx)
    assert len(n) == 2


def test_不同用户的缓存不串(counting):
    """串了就是把别人的材料取回来——这种错一旦发生是数据事故。"""
    a = tools.ToolContext(user="a")
    b = tools.ToolContext(user="b")
    query_cache.begin_round(a, 1)
    query_cache.begin_round(b, 1)
    query_cache.dispatch("search_memory", {"query": "x"}, a)
    query_cache.dispatch("search_memory", {"query": "x"}, b)
    assert len(counting) == 2


def test_重复查询占比能算出来(ctx, counting):
    """短路要能被观测到，否则"做了"和"没做"在数据上长得一模一样。"""
    query_cache.begin_round(ctx, 1)
    query_cache.dispatch("search_memory", {"query": "a"}, ctx)
    query_cache.dispatch("search_memory", {"query": "a"}, ctx)
    query_cache.dispatch("search_memory", {"query": "b"}, ctx)
    assert query_cache.repeat_rate(ctx) == pytest.approx(1 / 3)
    assert query_cache.stats(ctx)["run"] == {"calls": 3, "hits": 1, "skipped": 1}


def test_轮内计数每轮清零(ctx, counting):
    query_cache.begin_round(ctx, 1)
    query_cache.dispatch("search_memory", {"query": "a"}, ctx)
    query_cache.begin_round(ctx, 2)
    assert query_cache.stats(ctx)["this_round"]["calls"] == 0
    assert query_cache.stats(ctx)["run"]["calls"] == 1


def test_没短路的那些派发也要进分母(ctx, counting):
    """**台账批 11 M2：这条闸是反推补上的，补之前把 `calls += 1` 挪到
    「不在白名单就直接走」那一句之后，1380 条用例全绿。**

    而「重复查询率 33.3% / 40%」这个批 10 的头条数就是这个分母算出来的：
    分母只数可短路的工具时，`list_tables` / `render_image` 这些照样发出去的
    调用凭空消失，率会虚高——省下的次数一次没变，数字却好看了。
    """
    query_cache.begin_round(ctx, 1)
    query_cache.dispatch("list_tables", {}, ctx)          # 不在白名单
    query_cache.dispatch("search_memory", {"query": "a"}, ctx)
    query_cache.dispatch("search_memory", {"query": "a"}, ctx)   # 这一次才是省下来的
    assert query_cache.stats(ctx)["run"] == {"calls": 3, "hits": 1, "skipped": 1}
    assert query_cache.repeat_rate(ctx) == pytest.approx(1 / 3), \
        "分母是「这次跑一共派发了多少次」，不是「可短路的工具被叫了多少次」"
    assert query_cache.stats(ctx)["this_round"]["calls"] == 3


def test_参数不合法的那次也进分母(ctx, counting):
    """另一条早退的路：参数不是 dict 时直接交给 `tools.dispatch` 去报错。
    它确确实实是一次派发，漏数它同样会把率抬高。"""
    query_cache.begin_round(ctx, 1)
    query_cache.dispatch("search_memory", "[1, 2]", ctx)     # 合法 json，但不是 dict
    assert query_cache.stats(ctx)["run"]["calls"] == 1
