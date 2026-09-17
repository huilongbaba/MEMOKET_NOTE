"""材料账本（`harness/middleware/ledger.py`）。

这一版**只记不改**，所以测的全是「记得对不对」：
重复查询认不认得出、分母抓不抓得到、新事实算不算得准。

为什么这几个数要紧：见 docs/harness-fact-ledger.md。一句话——
`prepare` 每轮新建 `ToolTrace` 再丢掉，于是检索规划每轮从零开始，
而 prompt 里写着「不要再取上几轮已经写过的那些」，**清单却没给**。
"""

from __future__ import annotations

import json

from app.harness.middleware.ledger import blank, fold, gap_summary, mark_used


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


# ---------------------------------------------------- 批 10：日期 + 短路 ---

def test_事实的日期进账本():
    """`_fmt_facts` 一直在输出 `when`/`date`，账本以前每轮读一遍、每轮扔一遍。
    LedgerRAG 四个信号里的 temporal validity 就是这一个
    （docs/harness-fact-ledger.md §10②，计划 2.3）。"""
    led = blank()
    fold(led, [("search_memory", {"query": "dvt"},
                "[f1] DVT 推到 8 月 5 日\n    （2026-08-05 · Speaker A · 决定）")])
    assert led["facts"]["f1"]["when"] == "2026-08-05"


def test_日期对的是上面那一条事实_不是下一条():
    """两个正则各扫各的时，账本里每条事实的日期都是下一条的——
    而且**看起来完全正常**：字段有值、格式对、只有内容错。"""
    led = blank()
    fold(led, [("search_memory", {"query": "a"},
                "[f1] 甲\n    （2026-01-01 · A · 决定）\n"
                "[f2] 乙\n    （2026-02-02 · B · 决定）")])
    assert led["facts"]["f1"]["when"] == "2026-01-01"
    assert led["facts"]["f2"]["when"] == "2026-02-02"


def test_无日期不当成日期存():
    """`_fmt_facts` 没有日期时填的是「无日期」。把那三个字存进账本，
    比不存更糟——它长得像有数据。"""
    led = blank()
    fold(led, [("search_memory", {"query": "a"},
                "[f1] 甲\n    （无日期 · Speaker A）")])
    assert led["facts"]["f1"]["when"] == ""


def test_同一条事实换个工具取回来时补上日期():
    """`recall()` 走 `date`、`facts_page()` 走 `when`，两条路径键名本来就不同。"""
    led = blank()
    fold(led, [("search_memory", {"query": "a"}, "[f1] 甲\n    （无日期）")])
    fold(led, [("filter_facts", {"topic": "x"}, "[f1] 甲\n    （2026-05-05 · A）")])
    assert led["facts"]["f1"]["when"] == "2026-05-05"


def test_重复查询占比算得出来():
    """**短路要能被观测到**（计划 2.1）：做了和没做，产出一模一样。"""
    from app.harness.middleware.ledger import repeat_rate
    led = blank()
    call = ("search_memory", {"query": "众筹"}, "")
    fold(led, [call])
    fold(led, [call, ("list_topics", {}, "")])
    assert repeat_rate(led) == 1 / 3


def test_账本每轮给短路层报一次轮次():
    """**这是短路正确性的承重钉，不是记账。**

    没人报轮次的话，`query_cache` 里那个「这一轮贴过了吗」永远停在初值，
    于是**跨轮的重复也会被当成同一轮**，只回一句「结果在上面」——而上一轮的
    工具消息根本不在这一轮的 convo 里。症状是这一轮凭空少一批材料，
    没有任何报错，正文照常写出来、只是写得更空。
    """
    import asyncio

    from app.harness import query_cache
    from app.harness.middleware.ledger import Ledger
    from app.harness.modes import NOTE
    from app.harness.state import State
    from app.harness.tools import ToolContext

    assert "before_round" in Ledger.hooks
    st = State(mode=NOTE, ctx=ToolContext(user="u", note_id="n"))
    st.round = 3
    asyncio.run(Ledger().before_round(st))
    assert query_cache._cache(st.ctx)["round"] == 3


# ------------------------------------------- 缺口摘要（计划 2.4）

def _led(axes=None, queries=None):
    led = blank()
    led["axes"] = dict(axes or {})
    led["queries"] = [
        {"key": f"{t}\t" + json.dumps(a, sort_keys=True, ensure_ascii=False),
         "tool": t, "hit": h, "empty": not h}
        for t, a, h in (queries or [])]
    return led


def test_摘要是缺口形式_没取的摆最前():
    """[LED] §10⑤ 那条反面证据：注入的上下文会把 agent 锚定到特定解法上、
    **缩小搜索空间**。同一份账本两种写法效果相反——

      ❌ 库存：「已经取到 40 条，覆盖众筹、硬件节点」→ 邀请它见好就收
      ✅ 缺口：「定价：18 条，一条都没取」          → 邀请它去补

    所以「一条都没取」的那些必须排在最前面，而且按库里条数从多到少。
    """
    led = _led({"topic:定价": {"total": 18, "taken": 0},
                "topic:产品验证": {"total": 23, "taken": 2},
                "topic:硬件": {"total": 50, "taken": 0}})
    out = gap_summary(led)
    lines = [l for l in out.splitlines() if l.startswith("- ")]
    assert lines[0].startswith("- 硬件：库里 50 条，一条都没取")
    assert lines[1].startswith("- 定价：库里 18 条，一条都没取")
    assert "产品验证" in lines[2] and "只取了 2 条" in lines[2]


def test_已取的压成一句话_不列清单():
    """「把已取压到最小」是同一条依据的另一半。取满了的方向只留一个计数，
    一个名字都不报——报出来就是库存清单。"""
    led = _led({"topic:众筹": {"total": 41, "taken": 41},
                "topic:团队": {"total": 9, "taken": 9},
                "topic:定价": {"total": 18, "taken": 0}})
    out = gap_summary(led)
    assert "另有 2 个方向这次已经取过" in out
    assert "众筹" not in out and "团队" not in out


def test_摘要里不许出现用了几条():
    """**覆盖率是诊断，不是指标。**`checks/rubric._FACTUAL_GROUNDING` 的
    guidance 里写着「检索到的事实没有被全部用上，明确不算不足」——那句话是
    吃过亏才写进去的：为这个扣过一次分，下一轮正文里就「引入了大量未在
    知识库中出现的具体日期与人物」。

    所以这段话里一个「用了 / 没用 / 还剩」的数都不许有：
    「定价 18 条一条没取」值得追问，「众筹 41 条只用了 12 条」完全正常。
    """
    led = _led({"topic:众筹": {"total": 41, "taken": 12},
                "topic:定价": {"total": 18, "taken": 0}},
               [("filter_facts", {"topic": "众筹"}, 12)])
    led["facts"] = {f"f{i}": {"line": "x", "state": "used" if i < 3 else "taken",
                              "tool": "filter_facts", "when": ""} for i in range(12)}
    out = gap_summary(led)
    for banned in ("没用", "用上", "已用", "还剩", "已经取到"):
        assert banned not in out, f"「{banned}」会把覆盖率读成指标，逼它去凑"


def test_查空的那条要写明别换措辞重试():
    led = _led(queries=[("search_memory", {"query": "APP 安装 测试"}, 0),
                        ("filter_facts", {"topic": "定价", "limit": 8}, 5)])
    out = gap_summary(led)
    assert "别再原样发一遍" in out
    assert "search_memory query=APP 安装 测试 → 0 条" in out
    # limit 这类分页参数不进显示：它不改变「查的是哪个方向」，摆出来只会让
    # 两条本质相同的查询看着不一样，而这段话就是让模型认出「这条我发过了」。
    assert "limit" not in out


def test_同一个查询只列一次():
    q = ("filter_facts", {"topic": "定价"}, 5)
    out = gap_summary(_led(queries=[q, q, q]))
    assert out.count("filter_facts topic=定价") == 1


def test_没有分母的轴不进摘要():
    """`filter_facts` 的返回体里没有「共 N 条」时 `total` 是 0。
    没有分母就没有缺口可言——**不编一个出来**。"""
    out = gap_summary(_led({"topic:未知": {"total": 0, "taken": 0}}))
    assert out == ""


def test_空账本返回空串():
    assert gap_summary(blank()) == ""


def test_会生成东西的工具不进已发查询清单():
    """真跑（批 13）渲染出来的那段话里出现过这一行：

        - render_chart kind=flow labels=[…] → 0 条，换个方向，不要换措辞重试

    `render_chart` 根本不返回事实，「0 条」是把「没有事实行」读成了「查空了」，
    而那句话会劝模型别再画图。**清单只列读知识库的那几个**（`query_cache`
    的白名单），误伤比漏报贵。
    """
    led = _led(queries=[("render_chart", {"kind": "flow"}, 0),
                        ("run_skill_script", {"code": "x"}, 0),
                        ("filter_facts", {"topic": "定价"}, 3)])
    out = gap_summary(led)
    assert "render_chart" not in out and "run_skill_script" not in out
    assert "filter_facts topic=定价" in out


def test_主题树的分母折进账本_缺口才有一条都没取的():
    """主题树是 `hooks/note.prepare` **直接**调的，不进 `trace.calls`，
    `fold` 永远看不到它。第一版 2.4 就栽在这儿：真跑渲染出来的缺口摘要里
    **一条「一条都没取」都没有**，只剩三条已经查过的轴——而 [LED] §10⑤
    那个例子（「定价：18 条，一条都没取」）正是靠主题树才知道这个方向存在。
    """
    from app.harness.middleware.ledger import note_topics
    led = blank()
    fold(led, [("filter_facts", {"topic": "众筹"},
                "共 41 条，返回 2 条：\n" + _facts(("f1", "甲"), ("f2", "乙")))])
    assert "一条都没取" not in gap_summary(led)

    n = note_topics(led, "- 众筹（41 条，别名：x）\n- 定价（18 条）\n")
    assert n == 2
    out = gap_summary(led)
    assert "定价：库里 18 条，一条都没取" in out
    # **只补分母，不记一条查询**：模型没发过 `list_topics` 这一条。
    assert "list_topics" not in out
    assert len(led["queries"]) == 1


def test_缺口那段话里要有相关性护栏():
    """缺口按库里条数从多到少排，而真实用户的大桶（`work` 2862 条、
    `learning` 1097 条、`personal` 995 条）跟这一篇常常毫无关系——批 13 真跑
    渲染出来的第一版就把这三个摆在了最前面。缺口形式是用来**打开**搜索空间
    的（[LED] §10⑤），但打开不等于放任跑题。

    同时这句话**不许**写成「把它们取满」：覆盖率是诊断，不是指标。
    """
    out = gap_summary(_led({"topic:learning": {"total": 1097, "taken": 0}}))
    assert "只查跟这一节真的相关的那些" in out
    assert "不是要求你取满" in out
    for banned in ("取满它们", "全部取回", "必须取"):
        assert banned not in out
