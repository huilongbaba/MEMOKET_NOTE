"""按 id 的引用：材料带 id → 模型照抄 → 树上 ◆N / 行内 peek / 反向链接 / 判据
四处认的是同一个东西（docs/kb-fusion-design.md）。"""

from __future__ import annotations

from app.database import store
from app.database.retrieval import format_fact
from app.harness.checks import citations as c
from app.harness.checks.grounding_rules import fact_usage
from app.harness.prompts.fragments import facts_block


def test_检索结果_id_在最前面():
    assert format_fact({"id": "u-12-AB", "date": "2026-06-01", "text": "定在 6 月 30 日"}) \
        == "[u-12-AB] [2026-06-01] 定在 6 月 30 日"
    assert format_fact({"date": "2026-06-01", "text": "x"}) == "[2026-06-01] x"
    assert format_fact({"id": "u-1-F", "text": "x"}) == "[u-1-F] x"


def test_材料里的_id_跟后端和前端认的是同一种():
    line = format_fact({"id": "terrence-1872-5F8", "date": "2026-06", "text": "y"})
    assert c.supplied_ids([line]) == {"terrence-1872-5F8"}
    assert store.cited_fact_ids("据 [terrence-1872-5F8] 所述") == ["terrence-1872-5F8"]
    assert c.cited_ids("据 [terrence-1872-5F8] 所述") == ["terrence-1872-5F8"]


def test_facts_block_只在材料带_id_时讲引用规则():
    with_id = facts_block(["[u-1-A] [2026-01-01] 甲", "[u-2-B] 乙"])
    assert "引用规则" in with_id and "[编号]" in with_id
    plain = facts_block(["[2026-01-01] 甲"])
    assert "引用规则" not in plain
    assert facts_block([]) == ""


def test_两个前缀都剥掉_用上了才算用上():
    facts = ["[u-1-A] [2026-03-12] 手板厂之前打的那架外观结构样 2300 块钱一套。"]
    n, used = fact_usage("外观结构样 2300 块钱一套，摊到首批就是 46 元。", facts)
    assert n == 1 and used


def test_引用了不存在的事实_被抓到_并能自动摘掉():
    text = "先定 6 月 30 日 [u-1-A]，众筹延到 7 月 [u-9-FF]。"
    bad = c.dangling_citations(text, ["[u-1-A] [2026-06] 定在 6 月 30 日"], exists=lambda fid: False)
    assert bad == ["u-9-FF"]
    assert c.strip_citations(text, bad) == "先定 6 月 30 日 [u-1-A]，众筹延到 7 月。"


def test_不在材料里但知识库里有的_不算编造():
    text = "参考 [u-7-C]。"
    assert c.dangling_citations(text, [], exists=lambda fid: fid == "u-7-C") == []


def test_没有引用就什么都不查():
    calls = []
    assert c.dangling_citations("没有引用的正文", [], exists=lambda fid: calls.append(fid) or True) == []
    assert calls == []


def test_判据接进了单篇和分段两条_harness():
    from app.harness import modes
    from app.harness.checks import citations_exist
    wired = [m.key for m in modes.ALL if citations_exist in m.checks]
    assert "note" in wired and "section" in wired


def test_方括号里的日期不是引用():
    """[2026-01-01] 的 01 是合法十六进制——旧正则把它当成了事实 id。"""
    assert store.cited_fact_ids("[2026-01-01] 开会") == []
    assert c.cited_ids("[2026-01-01] 开会") == []
    assert c.supplied_ids(["[2026-01-01] 甲"]) == set()
    assert "引用规则" not in facts_block(["[2026-01-01] 甲"])


def test_格式就不对的引用也算编造():
    text = "样机安排 [terrence-23F3-4F3]，另见 [u-1-A]、[2026-06-01]、[[wiki-link-x]] 和 [link-a-b](http://x)。"
    assert c.malformed_citations(text) == ["terrence-23F3-4F3"]
    bad = c.fake_citations(text, [], exists=lambda fid: fid == "u-1-A")
    assert bad == ["terrence-23F3-4F3"]
    assert "[terrence-23F3-4F3]" not in c.strip_citations(text, bad) and "[u-1-A]" in c.strip_citations(text, bad)
