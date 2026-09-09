"""导入器的洗内容层。样本是四个来源的真实形状，不是构造的理想输入。

各来源的坑与调研见 docs/import-from-other-note-apps.md。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.importers import (clean_obsidian, html_to_markdown, normalize_date,  # noqa: E402
                           parse_enex, parse_frontmatter)


def test_normalize_date_covers_every_source_format():
    assert normalize_date("2026-03-15T09:00:00.000Z") == "2026-03-15"   # Notion
    assert normalize_date("20260315T091500Z") == "2026-03-15"           # ENEX
    assert normalize_date("Sunday, 15 March 2026 at 09:15") == "2026-03-15"  # AppleScript
    # 认不出来必须返回空串，**不能瞎猜**：猜错的日期会以"看起来可信"的样子
    # 进知识库，比没有日期更糟。调用方拿到空串会退回 mtime。
    assert normalize_date("下周三") == ""
    assert normalize_date("") == "" and normalize_date(None) == ""


def test_parse_frontmatter():
    meta, body = parse_frontmatter("---\ncreated: 2026-03-15\ntags: a, b\n---\n正文。")
    assert meta == {"created": "2026-03-15", "tags": "a, b"}
    assert body == "正文。"
    assert parse_frontmatter("没有 frontmatter。") == ({}, "没有 frontmatter。")


def test_clean_obsidian_keeps_link_text_and_real_code():
    src = ("见 [[会议纪要|三月会议]] 和 [[产品#定价]]。![[排期图.png]]\n\n"
           "```dataview\nTABLE file.name\n```\n\n"
           "```python\nprint('keep me')\n```\n")
    got = clean_obsidian(src)
    assert "三月会议" in got and "产品" in got, "链接文字往往是实体名，要留下"
    assert "[[" not in got and "排期图" not in got
    assert "dataview" not in got, "dataview 是模板不是内容"
    assert "print('keep me')" in got, "真正的代码块不能误删"
    # 嵌入图片的正则不能吃掉换行，否则后面按行首匹配的清理会整个失效
    assert clean_obsidian("![[x.png]]\n\n```dataview\nA\n```\n") .strip() == ""


def test_html_to_markdown_structure():
    got = html_to_markdown(
        '<div><h2>标题</h2><p>正文<b>加粗</b>和<a href="http://x">链接</a></p>'
        '<ul><li>甲</li><li>乙<ul><li>丙</li></ul></li></ul></div>')
    assert "## 标题" in got
    assert "**加粗**" in got and "[链接](http://x)" in got
    assert "- 甲" in got and "- 乙" in got and "  - 丙" in got
    assert "乙丙" not in got, "嵌套子列表不能被压进父项"
    assert html_to_markdown("") == "" and html_to_markdown("   ") == ""


def test_parse_enex_drops_attachments_and_keeps_dates():
    enex = """<?xml version="1.0" encoding="UTF-8"?>
<en-export><note><title>选审计厂商</title>
<content><![CDATA[<en-note><div>Venta <b>vs</b> Delta。</div>
<en-media hash="ab12" type="image/png"/><ul><li>报价对比</li></ul></en-note>]]></content>
<created>20260313T091500Z</created><guid>abc-123</guid></note>
<note><title>空的</title><content><![CDATA[<en-note></en-note>]]></content>
<created>20260314T010101Z</created></note></en-export>""".encode("utf-8")
    notes = parse_enex(enex)
    assert len(notes) == 1, "整篇空的笔记不该被导入"
    n = notes[0]
    assert n.date == "2026-03-13" and n.source_id == "abc-123"
    assert "**vs**" in n.content and "- 报价对比" in n.content
    assert "en-media" not in n.content and "ab12" not in n.content, "附件占位不能留成垃圾"


def test_source_id_is_stable_so_reimport_is_incremental():
    """同样的输入必须给出同样的 source_id——它会拼进 KITE 的 session_id，
    KITE 靠它跳过已导入的内容且不花 LLM 调用。不稳定就等于每次导入翻倍。"""
    enex = ("""<?xml version="1.0"?><en-export><note><title>A</title>"""
            """<content><![CDATA[<en-note>够长的一段正文内容在这里。</en-note>]]></content>"""
            """<created>20260313T091500Z</created><guid>g-1</guid></note></en-export>"""
            ).encode("utf-8")
    assert parse_enex(enex)[0].source_id == parse_enex(enex)[0].source_id == "g-1"


def test_apple_applescript_walks_folders_not_container():
    """AppleScript 必须遍历 folders 再取 notes of f。

    直接 ``repeat with n in notes`` 再问 ``container of n``，实机上**每一条都
    抛异常**（"不能获得 name of container of…"），而外面套着 try —— 结果是
    静默返回零条：接口不报错、就是导不出东西。这种"成功地什么都没做"最难查，
    所以在这里钉住。
    """
    from app.routers.import_sources import _APPLESCRIPT

    assert "repeat with f in folders" in _APPLESCRIPT
    assert "notes of f" in _APPLESCRIPT
    assert "container of n" not in _APPLESCRIPT
    # CLI 那份是同一段脚本，同样不能退化
    cli = (Path(__file__).resolve().parent.parent
           / "scripts" / "import_notes.py").read_text(encoding="utf-8")
    assert "repeat with f in folders" in cli and "container of n" not in cli


def test_every_item_status_written_is_allowed_by_the_schema():
    """写进 DB 的每个 item 状态都必须在 IngestItemOut 的 Literal 里。

    真实 bug：导入路径写了 ``set_item(id, "running")``，而 Literal 里没有
    "running" —— 于是**任何读任务状态的接口全部 500**：前端轮询拿不到数据、
    进度条永远停在「处理中…」、点了取消也看不到变化。取消其实发出去了，
    是界面根本不更新。这种"写得进去、读不出来"的错，单测和类型检查都拦不住。
    """
    import re

    from app.schemas import ITEM_STATUSES, JOB_STATUSES

    root = Path(__file__).resolve().parent.parent
    files = [root / "app" / "routers" / "import_sources.py",
             root / "app" / "routers" / "ingest.py",
             root / "app" / "store.py"]
    for f in files:
        src = f.read_text(encoding="utf-8")
        for fn, allowed in (("set_item", set(ITEM_STATUSES)), ("set_job", set(JOB_STATUSES))):
            for m in re.finditer(fn + r'\([^,]+,\s*"([a-z_]+)"', src):
                assert m.group(1) in allowed, \
                    f"{f.name} 的 {fn} 写了不认的状态 {m.group(1)!r}（合法：{sorted(allowed)}）"
        # store.py 里状态是拼出来的，额外把字面量也扫一遍
        if f.name == "store.py":
            for m in re.finditer(r'status = "([a-z_]+)"', src):
                assert m.group(1) in set(JOB_STATUSES) | set(ITEM_STATUSES), \
                    f"store.py 生成了不认的状态 {m.group(1)!r}"


def test_tabular_stats_are_exact():
    """EDA 的数字必须是算出来的，不是估出来的——这是「智能 EDA 能不能信」的地基。

    对照值用 statistics 库独立算，跟 tabular 的实现完全无关。
    """
    import statistics as st

    from app import tabular

    text = ("| 渠道 | 曝光 | 下单 |\n|---|---|---|\n"
            "| 官网 | 42,000 | 88 |\n| KS | 156000 | 612 |\n"
            "| 小红书 | 23000 | 47 |\n| 其他 | 暂无 | 12 |\n")
    t = tabular.find_tables(text)[0]
    assert t.shape == (4, 3)
    d = tabular.describe_column("曝光", t.column("曝光"))
    exp = [42000.0, 156000.0, 23000.0]
    assert d["类型"] == "数值" and d["有效值"] == 3 and d["总行数"] == 4
    assert d["均值"] == round(sum(exp) / 3, 4)
    assert d["中位数"] == round(st.median(exp), 4)
    assert d["标准差"] == round(st.pstdev(exp), 4)
    # 「暂无」不能被当成 0 拉低统计量
    assert d["最小"] == 23000.0 and d["求和"] == sum(exp)
    # 千分位和百分号都要认，百分号保留原刻度
    assert tabular.to_number("1,234") == 1234.0
    assert tabular.to_number("12.5%") == 12.5
    assert tabular.to_number("暂无") is None
    # 相关必须带上实际参与计算的行数
    c = tabular.correlate(t, "曝光", "下单")
    assert c["n"] == 3 and c["r"] is not None


def test_generated_charts_never_contain_syntax_breakers():
    """图表语法由代码拼，不让模型写——引号/方括号/换行这些会让 mermaid 解析失败
    的字符必须在标签里被清掉。用户碰到过「mermaid 语法错误，自动修复也没成功」，
    那种错会在笔记里留下一块渲染不出来的死代码。"""
    from app import blocks

    nasty = '带"引号"和[方括号]\n还有换行(和括号);分号'
    for code in (blocks.mermaid_pie(nasty, [(nasty, 3)]),
                 blocks.mermaid_xy(nasty, [nasty], [1], nasty),
                 blocks.mermaid_flow(nasty, [nasty, nasty])):
        body = code.split("```mermaid\n")[1].rsplit("```", 1)[0]
        # 只看**引号里的标签内容**：方括号在 x-axis [...] 里是语法本身，
        # 不是脏字符（第一版测试没区分，把合法语法也判成了没洗干净）。
        import re as _re
        labels = _re.findall(r'"([^"]*)"', body)
        assert labels, f"没有可检查的标签：{body!r}"
        for lab in labels:
            assert not set(lab) & set('[]()<>;\n\r"\''), f"标签没洗干净：{lab!r}"
        # 引号必须成对，否则就是把字符串截断了
        assert body.count('"') % 2 == 0, f"引号不成对：{body!r}"
    # 空数据也要产出合法结构，不能拼出半截代码块
    assert blocks.mermaid_xy("空", [], [], "值").count("```") == 2


def test_table_from_image_detection_rule():
    """「有没有表格」的判定必须是确定性的，不能靠模型自己说有没有。

    判据：至少两行以 | 开头，且第二行是 |---|---| 这种分隔行。识别不出就
    如实返回 detected=False——比硬编一张空表塞进用户笔记好得多。
    """
    src = (Path(__file__).resolve().parent.parent
           / "app" / "routers" / "compose_block.py").read_text(encoding="utf-8")
    assert "detected" in src and "没有表格" in src

    def detect(text: str) -> bool:
        t = text.strip()
        if t.startswith("```"):
            t = t.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        rows = [ln for ln in t.splitlines() if ln.strip().startswith("|")]
        return len(rows) >= 2 and any(set(ln) <= set("|-: ") for ln in rows[1:2])

    assert detect("| 月份 | 销量 |\n|---|---|\n| 3月 | 1200 |")
    assert detect("```markdown\n| a | b |\n|---|---|\n| 1 | 2 |\n```")
    assert not detect("没有表格")
    assert not detect("这张图是一个流程示意图，从设计到测试。")
    # 只有一行竖线不算表格
    assert not detect("| 这只是一行 |")


def test_render_image_is_a_separate_tool_group():
    """文生图单独一组：它要花钱、要等几十秒，不该在「画个柱状图」的场合
    被顺手调用。"""
    import app.tools as T

    assert T.names(["image"]) == ["render_image"]
    assert "render_image" not in T.names(["chart"])
    # 图表工具必须仍然是零成本的本地拼装
    assert set(T.names(["chart"])) == {"chart_column", "chart_from_text",
                                       "render_chart"}
    # render_table **不在 chart 组**：做表不是画图。它待在 chart 组的时候，
    # 每个画图模式都被迫拿到一个做表工具、做表模式被迫拿到三个画图工具，
    # 每一个都占 prompt 空间、多一个选错的机会。
    assert T.names(["table"]) == ["render_table"]


def test_async_tools_are_awaited():
    """异步工具必须在 dispatch 里 await。

    不 await 的话返回的是协程对象，json.dumps 出来是 "<coroutine object …>"
    ——模型收到一句没有意义的字符串，却毫无报错。这种「能跑但结果是垃圾」
    最难查，所以钉住。
    """
    import app.tools as T
    from app.tools import registry

    snap = registry._snapshot()
    try:
        @registry.register(name="_t_async", description="测试用", params={}, group="_t")
        async def _t_async(ctx):                       # noqa: ANN001
            return "异步结果"

        out = T.dispatch("_t_async", "{}", T.ToolContext(user="u"))
        assert out == "异步结果", f"异步工具没被 await：{out!r}"
    finally:
        registry._restore(snap)


def test_restructure_never_touches_content():
    """智能排版**不可能改内容**——模型只出操作，原文由代码按行搬运。

    这是结构性保证，不是靠提示词说「不要改内容」。逐条验证每种操作只动行首
    的结构标记，正文一个字都不变。
    """
    from app import restructure, textshape

    md = ("众筹复盘\n三月上旬启动，四月底结束。\n启动前要做的事\n"
          "设计稿确认\n页面开发\n风险在排期\n如果设计稿晚一天，后面全都要顺延。")
    ops = [
        {"op": "heading", "line": 1, "level": 1},
        {"op": "heading", "line": 3, "level": 2},
        {"op": "list", "line": 4},
        {"op": "list", "line": 5},
        {"op": "quote", "line": 7},
    ]
    out, skipped = restructure.apply_ops(md, ops)
    assert not skipped
    assert out.startswith("# 众筹复盘")
    assert "\n- 设计稿确认\n- 页面开发\n" in out
    assert "\n> 如果设计稿晚一天，后面全都要顺延。" in out
    # **每一行的正文都必须原样还在**
    for line in md.splitlines():
        assert restructure.body(line) in out, f"这一行的内容丢了：{line!r}"
    assert textshape.content_drift(md, out) == ""


def test_restructure_refuses_dangerous_ops():
    """越界、代码块里、表格里、超长新标题——都要被跳过而不是照做。"""
    from app import restructure

    md = "正文一。\n```py\nx = 1\n```\n| a | b |\n|---|---|\n正文二。"
    out, skipped = restructure.apply_ops(md, [
        {"op": "heading", "line": 3, "level": 2},      # 代码块内
        {"op": "list", "line": 5},                      # 表格行
        {"op": "quote", "line": 99},                    # 越界
        {"op": "insert_heading", "before": 1, "level": 2, "text": "标" * 60},  # 超长
        {"op": "不存在的操作", "line": 1},
    ])
    assert out == md, "危险操作一条都不该生效"
    assert len(skipped) == 5
    assert any("代码块" in s for s in skipped)
    assert any("表格" in s for s in skipped)
    assert any("超出范围" in s for s in skipped)
    assert any("太长" in s for s in skipped)


def test_restructure_ops_are_idempotent():
    """同一组操作跑两次结果一样——换结构之前会先剥掉已有的标记。"""
    from app import restructure

    md = "标题行\n列表项一\n列表项二"
    ops = [{"op": "heading", "line": 1, "level": 2},
           {"op": "list", "line": 2}, {"op": "list", "line": 3}]
    once, _ = restructure.apply_ops(md, ops)
    twice, _ = restructure.apply_ops(once, ops)
    assert once == twice
    # 转换类型也要干净：标题改成列表，不能留下 `- ## 标题行`
    back, _ = restructure.apply_ops(once, [{"op": "list", "line": 1}])
    assert back.splitlines()[0] == "- 标题行"


def test_content_drift_tolerates_layout_but_catches_edits():
    """漂移校验：排版的合法产物放行，改词/删句一律抓住。"""
    from app.textshape import content_drift

    a = "三月上旬启动众筹。\n依赖：设计稿确认、页面开发。\n风险是排期太紧。"
    b = ("## 众筹节奏\n\n三月上旬启动众筹。\n\n依赖：\n\n- 设计稿确认\n- 页面开发\n\n"
         "**风险**是排期太紧。")
    assert content_drift(a, b) == "", "纯排版（含新加的短标题、顿号变列表）不该报"
    assert content_drift(a, b.replace("排期太紧", "排期非常紧张"))
    assert content_drift(a, b.replace("\n\n**风险**是排期太紧。", ""))
    assert content_drift(a, b + "\n\n另外补充一大段模型自己想出来的分析内容在这里。")


def test_restructure_refuses_paragraph_length_headings():
    """一百多字的东西不是标题。

    真实文档上抓到的：模型把「大民生：什么叫大民生？过去理解民生，就是看病、
    上学、养老这些具体需求。而大民生，是把整座城市的运行都看成民生…」这样
    一整段提升成了三级标题——目录里出现一段一百多字的"标题"，比不排版还糟。
    """
    from app import restructure

    long_line = "大民生：什么叫大民生？过去理解民生，就是看病、上学、养老这些具体需求。" \
                "而大民生，是把整座城市的运行都看成民生、市容环境、城市安全、交通出行。"
    md = f"短标题\n{long_line}\n正文。"
    out, skipped = restructure.apply_ops(md, [
        {"op": "heading", "line": 1, "level": 2},
        {"op": "heading", "line": 2, "level": 3},
    ])
    assert out.splitlines()[0] == "## 短标题", "短的照常提升"
    assert out.splitlines()[1] == long_line, "长段落保持原样"
    assert any("太长" in s for s in skipped)


def test_heading_vs_sentence_on_real_document_lines():
    """标题 / 句子的判据。**用例全部取自那篇 26714 字的真实公司汇报**。

    长度守卫拦得住 94 字那条，拦不住这条 49 字的：
      「接下来是能源行业，能源是经济社会运行的“血液”，华为解决方案目前主要
        应用在油气、电力和矿山。」
    它有主谓宾、有句号——是一句话，不是标题。标题是**命名**，句子是**叙述**。
    """
    from app.restructure import looks_like_sentence as sent

    headings = [
        "政府：", "智慧教育", "算力底座：", "宁夏大学具体教室功能：",
        "露天矿无人驾驶：", "井工矿：", "金融：", "风险主要在排期",
        # 编号 + 短名 + 括号补充：句号在中间，结尾是「）」
        "5.展厅布局图。（从算力底座到各行业实践成果）",
        "3、数字能源（低碳绿色）",
    ]
    sentences = [
        "接下来是能源行业，能源是经济社会运行的“血液”，华为解决方案目前主要应用在油气、电力和矿山。",
        "这是一段完整的话，它有停顿，也有结尾。",
        "华为现在21万员工，一半是研发工程师，其中大部分在做基础研究。",
    ]
    for h in headings:
        assert not sent(h), f"这是标题却被判成句子：{h!r}"
    for s in sentences:
        assert sent(s), f"这是句子却被判成标题：{s!r}"


def test_split_enumerated_list_from_one_line():
    """一行里塞着（1）（2）（3）时拆成列表——长文档里最值得改的一处。

    真实样本（26714 字的公司汇报）：四条并列步骤挤在一行，读不出并列关系。
    **拆点由代码按显式序号找，模型只说拆哪一行**——让模型报拆点等于让它重新
    输出正文，那正是这个设计要避免的事。
    """
    from app import restructure, textshape

    md = ("引子。\n"
          "比如针对特定事件，（1）智能体自动生成巡查任务。（2）它能主动识别风险。"
          "（3）事件一旦发生不等指令。（4）系统自主安排检查。\n"
          "后面。")
    out, skipped = restructure.apply_ops(md, [{"op": "split", "line": 2}])
    items = [l for l in out.splitlines() if l.startswith("- ")]
    assert len(items) == 4, f"该拆成 4 项（实际 {len(items)}）：{items}"
    assert "（1）" not in out, "序号本身要去掉——结构改由列表符号承担"
    assert "智能体自动生成巡查任务" in out and "系统自主安排检查" in out
    assert not skipped
    assert textshape.content_drift(md, out) == ""

    # 不该拆的：不足三项、序号不连续、年份、条款号
    for bad in ("只有（1）一项和（2）两项。",
                "提到（1）某事，又提到（5）另一事，还有（9）第三事。",
                "2020年营收（1）持平，2021年（2）增长。",
                "见第1、2、3条规定。"):
        assert restructure.split_enumerated(bad)[1] == [], f"不该拆：{bad!r}"


def test_data_tools_follow_the_cursor():
    """就近原则：用户在哪儿按的 `/`，就先看哪张表。

    没有位置信息的话，一篇有五张表的笔记，模型只能瞎猜一个编号——而它猜的
    多半是第一张，也就是离用户最远的那张。
    """
    import app.tools as T

    md = ("前面。\n\n| 月份 | 销量 |\n|---|---|\n| 3月 | 100 |\n\n"
          + "中间隔着一段话。" * 10
          + "\n\n| 渠道 | 曝光 |\n|---|---|\n| 官网 | 42000 |\n\n后面。")

    ctx = T.ToolContext(user="u", note_id="n", content=md, cursor=md.index("中间"))
    first = T.dispatch("list_tables", "{}", ctx)
    assert first.splitlines()[0].startswith("表 0"), "离光标最近的排最前"
    assert "光标就在这张表旁边" in first.splitlines()[0]
    assert "月份" in T.dispatch("describe_table", "{}", ctx), "不给编号时用最近那张"

    # 同一篇笔记、两个光标位置**同时存在**：各看各的，互不干扰。
    # 挂在 ctx 上而不是全局字典，为的就是这个——前端允许同一篇笔记里
    # 好几个 `/` 并发跑，全局字典会让后开始的把先开始的光标覆盖掉。
    ctx = T.ToolContext(user="u", note_id="n", content=md, cursor=len(md) - 3)
    second = T.dispatch("list_tables", "{}", ctx)
    assert second.splitlines()[0].startswith("表 1"), "光标挪到后面，最近的也跟着变"
    assert "渠道" in T.dispatch("describe_table", "{}", ctx)
    # 显式给编号时不受光标影响
    assert "月份" in T.dispatch("describe_table", '{"index":0}', ctx)


def test_histogram_bins_converge_on_small_samples():
    """分箱数按数据量收敛。6 个点分 8 箱，每箱一两个，看不出任何形状。"""
    from app.tabular import histogram

    labels, counts = histogram([str(v) for v in (42000, 156000, 23000, 51000, 98000, 61000)])
    assert 2 <= len(labels) <= 3, f"6 个点不该分成 {len(labels)} 箱"
    assert sum(counts) == 6, "每个点都要落进某个箱"
    big = histogram([str(i) for i in range(1, 101)])
    assert len(big[0]) == 8 and sum(big[1]) == 100
    assert histogram(["5", "5", "5"]) == (["5"], [3.0]), "全是同一个值"
    assert histogram(["5"]) == ([], []), "只有一个点画不出分布"
