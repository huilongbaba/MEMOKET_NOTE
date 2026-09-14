"""幻灯片判据（痛点 6，docs/slides-plan.md）。

这几条判的不是好不好看，是**这份幻灯片还是不是这篇笔记的幻灯片**：
每一页有没有依据、数字有没有在总结的路上被改掉、有没有整节漏掉。
通用 PPT 工具做不到这几件事，因为它手上没有原文和引用。
"""

from __future__ import annotations

from app.harness.checks.slides import MAX_BULLETS, check_slides, split_pages

SRC = """# 创业一年回顾

## 时间线与里程碑

EVT 节点从 6 月挪到 8 月，因为结构件改了 [terrence-1-A1]。

## 配件

配件那条线上收了 3 笔款 [terrence-2-B2]。
"""


def test_按横线分页_front_matter不算一页():
    md = "---\nmarp: true\n---\n\n# 标题\n\n---\n\n## 第二页\n"
    assert len(split_pages(md)) == 2


def test_代码块里的横线不算分页符():
    """跟 `editor/outline.section_end` 同一个坑：mermaid / yaml 块里横线很常见，
    切错一次整份就乱了。"""
    md = "# 一\n\n```yaml\na: 1\n---\nb: 2\n```\n\n---\n\n## 二\n"
    assert len(split_pages(md)) == 2


def test_一页没有依据的幻灯片跟通用工具做出来的没区别():
    good = "# 创业一年回顾\n\n一句话\n\n---\n\n## EVT 从 6 月挪到 8 月\n\n- 结构件改了 [terrence-1-A1]\n"
    assert check_slides(good, SRC).cite_coverage == 0.5
    bare = "# 创业一年回顾\n\n---\n\n## EVT 从 6 月挪到 8 月\n\n- 结构件改了\n"
    assert "只有 0 页带着引用编号" in "".join(check_slides(bare, SRC).notes())


def test_名词短语标题要点出来_但首末两页不算():
    """首页是标题页（本来就该是笔记的名字），末页是提示词规定的「还缺什么」。
    要求它们是判断句等于要求它们改名。"""
    md = ("# 创业一年回顾\n\n一句话结论\n\n---\n\n## 配件\n\n- 一条\n"
          "\n---\n\n## 还缺什么\n\n- 一条\n")
    assert check_slides(md, SRC).weak_titles == [2]


def test_完整的判断句不能因为用词不在表上就被判不合格():
    """第一版反过来做——枚举谓词、没命中就判不合格——拿真产出一对就露馅：
    24 页里点了 6 页，其中 5 页是「APP目前只能确认存在实际使用」
    「硬件节点必须同时记录计划与结果」这种完完整整的判断句，
    只是「必须」「经历了」不在我列的那张表上。**枚举语言现象的表永远补不全。**
    """
    heads = ["APP目前只能确认存在实际使用", "硬件节点必须同时记录计划与结果",
             "硬件方案经历了连续调整", "样机批次必须先确认前置条件"]
    md = "# 标题页\n\n---\n\n" + "\n\n---\n\n".join(f"## {h}\n\n- 一条" for h in heads) \
        + "\n\n---\n\n## 还缺什么\n\n- 一条\n"
    assert check_slides(md, SRC).weak_titles == []


def test_一页塞一屏字要被点出来():
    dense = "# 标\n\n---\n\n## 从 6 月到 8 月\n\n" + "很长的一句话。" * 40
    assert check_slides(dense, SRC).over_dense == [2]
    many = "# 标\n\n---\n\n## 从 6 月到 8 月\n\n" + "".join(f"- 第 {i} 条\n" for i in range(MAX_BULLETS + 2))
    assert check_slides(many, SRC).over_dense == [2]


def test_总结时把数字改掉是最隐蔽的错():
    """读者没法从幻灯片本身看出来——只有拿原文对账才看得出。"""
    md = "# 标\n\n---\n\n## EVT 从 6 月挪到 9 月\n\n- 收了 5 笔款 [terrence-2-B2]\n"
    c = check_slides(md, SRC)
    assert "9" not in c.stray_numbers, "一位数不算：页码、序号太容易误伤"
    md2 = "# 标\n\n---\n\n## 收款从 3 笔涨到 17 笔\n\n- [terrence-2-B2]\n"
    assert "17" in check_slides(md2, SRC).stray_numbers


def test_整节漏掉要报出来():
    md = "# 创业一年回顾\n\n---\n\n## 时间线与里程碑\n\n- 一条 [terrence-1-A1]\n"
    assert check_slides(md, SRC).missed_sections == ["配件"]


def test_内容进去了就不算漏掉_哪怕小节标题没出现():
    """**不能只比标题**：原文「时间线与里程碑」这种结构性标题，内容被拆进了
    好几页各自的判断句里。真产出实拍：24 页那次按标题比误报了 3 节，
    而那 3 节的引用编号 6/6、4/5、18/21 都进了幻灯片。"""
    md = ("# 创业一年回顾\n\n---\n\n## EVT 从 6 月挪到 8 月\n\n- 结构件改了 [terrence-1-A1]\n"
          "\n---\n\n## 配件线上已经收到 3 笔款\n\n- [terrence-2-B2]\n")
    assert check_slides(md, SRC).missed_sections == []


def test_空产出不炸():
    c = check_slides("", SRC)
    assert c.pages == 0 and c.cite_coverage == 0.0


def test_派生出来的子笔记不当参考上下文(tmp_path, monkeypatch):
    """幻灯片是这篇的**另一种形态**，屏幕活动回顾是那一天的汇总——
    拿它们当「同一批内容里的另一篇」喂回去是循环：模型读到的是自己刚写过的话的
    浓缩版，只会把重复写得更重（而 `non_repetition` 本来就是最难达标的那一维，
    第 647 轮真跑连续四轮判 0）。
    """
    from app.database import store

    parent = store.create_note("u_derived", "父笔记", "正文")["id"]
    store.create_note("u_derived", "同伴一篇", "正文", parent)
    store.create_note("u_derived", "父笔记 · 幻灯片", "# 页\n", parent, source="slides")
    store.create_note("u_derived", "屏幕活动回顾", "## 推进了什么\n", parent, source="journey")

    got = [n["title"] for n in store.child_notes("u_derived", parent, limit=10)]
    assert got == ["同伴一篇"], got
