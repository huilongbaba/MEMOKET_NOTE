"""材料账本（`harness/middleware/ledger.py`）。

这一版**只记不改**，所以测的全是「记得对不对」：
重复查询认不认得出、分母抓不抓得到、新事实算不算得准。

为什么这几个数要紧：见 docs/harness-fact-ledger.md。一句话——
`prepare` 每轮新建 `ToolTrace` 再丢掉，于是检索规划每轮从零开始，
而 prompt 里写着「不要再取上几轮已经写过的那些」，**清单却没给**。
"""

from __future__ import annotations

from app.harness.middleware.ledger import blank, fold, mark_used


def _facts(*pairs) -> str:
    return "\n".join(f"[{i}] {t}\n    （2026-03-11 · Speaker A · 决定）" for i, t in pairs)


def test_同一个查询发两次_第二次算重复():
    led = blank()
    call = ("search_memory", {"query": "众筹", "limit": 8}, _facts(("f1", "甲")))
    fold(led, [call])
    stat = fold(led, [call])
    assert stat["repeat_calls"] == 1
    assert stat["facts_new"] == 0          # 同一条事实不重复计新


def test_参数顺序不同但内容相同_也算同一个查询():
    """不按键排序的话，`{a,b}` 和 `{b,a}` 会被当成两个查询，
    重复率就永远统计不出来。"""
    led = blank()
    fold(led, [("search_memory", {"query": "众筹", "limit": 8}, "")])
    stat = fold(led, [("search_memory", {"limit": 8, "query": "众筹"}, "")])
    assert stat["repeat_calls"] == 1


def test_分母从_filter_facts_的返回体里抓出来():
    """「共 41 条，返回 2 条」这句话工具本来就在返回——我们以前每轮扔一次。"""
    led = blank()
    fold(led, [("filter_facts", {"topic": "众筹"},
                "共 41 条，返回 2 条：\n" + _facts(("f1", "甲"), ("f2", "乙")))])
    assert led["axes"]["topic:众筹"] == {"total": 41, "taken": 2}


def test_主题树的条数也进分母():
    led = blank()
    fold(led, [("list_topics", {}, "- 众筹（41 条，别名：crowdfunding）\n- 定价（18 条）")])
    assert led["axes"]["topic:众筹"]["total"] == 41
    assert led["axes"]["topic:定价"]["total"] == 18
    assert led["axes"]["topic:定价"]["taken"] == 0          # 一条都没取，正是要看的空白


def test_取到过的不算新_没取到过的算新():
    led = blank()
    s1 = fold(led, [("search_memory", {"query": "a"}, _facts(("f1", "甲"), ("f2", "乙")))])
    s2 = fold(led, [("search_memory", {"query": "b"}, _facts(("f2", "乙"), ("f3", "丙")))])
    assert s1["facts_new"] == 2 and s2["facts_new"] == 1
    assert len(led["facts"]) == 3


def test_正文引了哪几条就标成_used():
    led = blank()
    fold(led, [("search_memory", {"query": "a"}, _facts(("f1", "甲"), ("f2", "乙")))])
    assert mark_used(led, "正文里提到了 [f1] 这件事。") == 1
    assert led["facts"]["f1"]["state"] == "used"
    assert led["facts"]["f2"]["state"] == "taken"      # 取了没用——它就是修订的现成候选


def test_查空的记下来():
    """查空值得单独记：同一个查空的查询不该被发第二次。"""
    led = blank()
    fold(led, [("search_memory", {"query": "不存在的东西"}, "（没有匹配的事实）")])
    assert led["queries"][0]["empty"] is True


def test_账本只存一行摘要_不存全文():
    """存全文就要维护一致性，那是自找的第二个真相来源。"""
    led = blank()
    long = "甲" * 500
    fold(led, [("search_memory", {"query": "a"}, _facts(("f1", long)))])
    assert len(led["facts"]["f1"]["line"]) <= 60


def test_空调用不炸():
    led = blank()
    assert fold(led, [])["tool_calls"] == 0
    assert fold(led, None)["tool_calls"] == 0
