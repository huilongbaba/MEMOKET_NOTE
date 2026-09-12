

def test_手写的_mermaid_认得出来():
    from app.harness.tools import blocks
    from app.harness.checks import blockcheck
    real = blocks.mermaid_xy("各渠道曝光", ["官网", "Kickstarter"], [93000, 254000])
    allowed = blockcheck.mermaid_blocks(real)
    # 工具原样搬过来的：放行
    assert blockcheck.chart_gap(f"一句话\n\n{real}\n", allowed) == ""
    # 模型照着抄、顺手给 y 轴加了范围：抓出来
    forged = real.replace('y-axis "数值"', 'y-axis "曝光" 0 --> 260000')
    assert blockcheck.unauthorized_charts(forged, allowed)
    assert "不是工具生成的" in blockcheck.chart_gap(forged, allowed)
    # 改一个数字也算
    tampered = real.replace("93000", "94000")
    assert blockcheck.unauthorized_charts(tampered, allowed)
    # 没传 allowed 时这条检查不生效（其它模式没有工具图可比对）
    assert blockcheck.chart_gap(forged) == ""


def test_聚焦轮看产物不看行为():
    """`focus_groups` 那一轮该不该跑，判据是画图工具**产出了东西**，
    不是调过画图工具——chart_column 会主动拒绝没信息量的图，连拒三次按
    「调过了」算就会跳过补画轮，最后一张图都没有。"""
    from app.harness.tools import blocks
    from app.harness.hooks.block import _produced

    class T:
        def __init__(self, calls):
            self.calls = calls

    real = blocks.mermaid_xy("曝光", ["a", "b"], [1, 2])
    refused = "（点击 只有 6 个数据点，画直方图看不出分布，不值得画。）"
    assert not _produced(T([("chart_column", {}, refused)] * 3), ("chart",))
    assert _produced(T([("chart_column", {}, refused),
                        ("render_chart", {}, real)]), ("chart",))
    # 别的组产出了东西不算——聚焦轮问的是「这一组画出来没有」
    assert not _produced(T([("list_tables", {}, "| a | b |")]), ("chart",))


def test_远处的表不冒充就在旁边():
    """一篇笔记里唯一的一张表，哪怕在一万字外，nearest 也会返回它——
    实测因此分析了跟光标毫无关系的项目进度表。距离要如实报出来。"""
    import app.harness.tools as T

    table = "| 阶段 | 状态 |\n|---|---|\n| 启动 | 进行中 |\n"
    md = table + "隔着很远的一段。" * 900 + "\n\n效率提升 10 倍，成本降幅 75%。"
    ctx = T.ToolContext(user="u", note_id="n", content=md, cursor=len(md) - 5)
    out = T.dispatch("list_tables", "{}", ctx)
    assert "不在光标附近" in out
    assert "光标就在这张表旁边" not in out
    assert "光标附近没有表格" in out

    # 光标挪到表上，同一张表就该是"在旁边"
    ctx2 = T.ToolContext(user="u", note_id="n", content=md, cursor=5)
    assert "光标就在这张表旁边" in T.dispatch("list_tables", "{}", ctx2)


def test_光标附近的数字句子():
    import app.harness.tools as T

    md = ("很久以前的事，销量 100。" + "无关的话。" * 300
          + "AI FWI 将反演效率提升 10 倍、成本降幅 75%。"
            "使用 4 台服务器可实现与 576 台同等效率。")
    ctx = T.ToolContext(user="u", note_id="n", content=md, cursor=len(md))
    out = T.dispatch("numbers_near_cursor", "{}", ctx)
    lines = [ln for ln in out.split("\n") if ln[:2] in ("1.", "2.")]
    assert "576" in lines[0], "离光标最近的句子排最前"
    assert "10 倍" in out and "75%" in out
    # 返回原句而不是裸数值——单位在句子里
    assert "倍" in out


def test_混量纲的图被拒():
    import app.harness.tools as T

    md = "效率提升 10 倍、成本降幅 75%、机房空间降低 98%。"
    ctx = T.ToolContext(user="u", note_id="n", content=md, cursor=len(md))
    args = ('{"kind":"bar","title":"AI FWI 效果","labels":["效率提升","成本降幅","机房空间降低"],'
            '"values":[10,75,98],"unit":"百分比/倍数"}')
    out = T.dispatch("chart_from_text", args, ctx)
    assert "不是一个单位" in out
    assert "```mermaid" not in out

    # 单位统一就放行，而且单位要出现在 y 轴上
    ok = T.dispatch("chart_from_text",
                    '{"kind":"bar","title":"降幅","labels":["成本","机房空间"],'
                    '"values":[75,98],"unit":"%","series":"降幅"}', ctx)
    assert "```mermaid" in ok
    assert "降幅（%）" in ok


def test_量纲混了的图被原文判掉():
    """模型可以声明 unit="倍" 却把「576 台」画进来——声明没撒谎，混的是数据。
    单位要从原文取，而且只取离光标最近的那次出现：三万字里「10」出现几十次，
    后面跟着"倍""秒""%""月"什么都有，全收一遍等于没有判据。"""
    import app.harness.tools as T
    from app.harness.tools import tabular

    md = ("很久以前：等了 10 秒。" + "无关。" * 400
          + "AI FWI 将反演效率提升 10 倍、成本降幅 75%。"
            "使用 4 台服务器可实现与传统方案 576 台服务器同等效率，机房空间降低 98%。")
    cur = len(md)
    assert tabular.unit_near(md, 10, cur) == "倍", "取最近那次，不是开头的「10 秒」"
    assert tabular.mixed_units(md, [10, 576, 4], cur), "倍 和 台 混了"
    assert not tabular.mixed_units(md, [75, 98], cur), "都是 %，放行"

    ctx = T.ToolContext(user="u", note_id="n", content=md, cursor=cur)
    bad = T.dispatch("chart_from_text",
                     '{"kind":"bar","title":"对比","labels":["效率提升","传统 HPC","Atlas"],'
                     '"values":[10,576,4],"unit":"倍"}', ctx)
    assert "单位不是一个" in bad and "```mermaid" not in bad
    # render_chart 走同一条检查——实测它画出过 y 轴写「提升/降幅」的混量纲图
    assert "单位不是一个" in T.dispatch(
        "render_chart",
        '{"kind":"bar","title":"对比","labels":["a","b","c"],"values":[10,576,4]}', ctx)
    ok = T.dispatch("chart_from_text",
                    '{"kind":"bar","title":"降幅","labels":["成本","机房空间"],'
                    '"values":[75,98],"unit":"%"}', ctx)
    assert "```mermaid" in ok


def test_单值的图被拒():
    """一根柱子的柱状图，读者得到的信息跟直接读那句话一样。"""
    import app.harness.tools as T

    md = "反演效率提升 10 倍。三月 100，四月 120。"
    ctx = T.ToolContext(user="u", note_id="n", content=md, cursor=len(md))
    out = T.dispatch("chart_from_text",
                     '{"kind":"bar","title":"效率提升","labels":["反演效率提升"],'
                     '"values":[10],"unit":"倍"}', ctx)
    assert "只有一个数" in out and "```mermaid" not in out
    assert "只有一个数" in T.dispatch(
        "render_chart", '{"kind":"bar","title":"t","labels":["a"],"values":[10]}', ctx)
    # 有对照就放行
    ok = T.dispatch("chart_from_text",
                    '{"kind":"bar","title":"月度","labels":["三月","四月"],'
                    '"values":[100,120],"unit":"件"}', ctx)
    assert "```mermaid" in ok
    # 流程图不受影响
    assert "```mermaid" in T.dispatch(
        "render_chart", '{"kind":"flow","title":"t","labels":["采集","处理"]}', ctx)


def test_编造的对照值被抓住():
    """两条互相拉扯的要求都得挡住：编造的对照值要拒，省了单位的同组项要放行。
    区别在同不同句。"""
    from app.harness.tools import tabular

    near = ("其中，最新技术 AI FWI 将反演效率提升 10 倍、成本降幅 75%。"
            "计划后续在全国总部署 1 万公里。")
    # 「1」在正文里当然找得到（1 万公里），但没有「1 倍」
    assert tabular.without_unit(near, [10, 1], "倍") == [1]
    assert tabular.without_unit(near, [75], "%") == []
    # 同一句里省了百分号的那项要放行——拒掉它会让沐曦从图里消失
    one = "昇腾 38%（浪潮 22.4%、中科光 14.1%、寒武纪 43%、沐曦 1.79）"
    assert tabular.without_unit(one, [38, 22.4, 14.1, 43, 1.79], "%") == []
    # 一个值都没带这个单位时判据不生效——原文常常压根不写单位
    assert tabular.without_unit("三月 100，四月 120。", [100, 120], "件") == []

    import app.harness.tools as T
    ctx = T.ToolContext(user="u", note_id="n", content=near, cursor=len(near))
    out = T.dispatch("chart_from_text",
                     '{"kind":"bar","title":"t","labels":["AI FWI","传统"],'
                     '"values":[10,1],"unit":"倍"}', ctx)
    assert "找不到出处" in out and "```mermaid" not in out


def test_best_of_的排序规则():
    """跑满轮数时交付最好的一轮。折叠规则：先比达标维度数，再比平均分。
    这个规则必须是确定性的——用它做取舍，不能再打一次模型。"""
    def rank(levels):
        return (sum(1 for v in levels if v >= 2), sum(levels) / len(levels))

    # 达标维度多的赢，哪怕平均分一样
    assert rank([2, 2, 0]) > rank([2, 1, 1])
    # 达标数相同就比均分
    assert rank([2, 1, 1]) > rank([2, 1, 0])
    # complete（全达标）一定是最高的
    assert rank([2, 2, 2]) > rank([2, 2, 1])
    # 实测撞到的那次：第 2 轮两张干净的图 vs 第 3 轮多一张单值图
    assert rank([2, 2, 2, 1]) > rank([2, 2, 1, 1])


def test_检查命中时构造的评价是合法的():
    """确定性检查排在打分前面，命中就跳过那次 LLM 调用、直接构造一份不合格
    的评价。这份评价要能被下游正常用：算 best-of 的 rank、生成 steer。"""
    from app.harness.types import DimensionScore, Evaluation

    ev = Evaluation(scores={"has_charts": DimensionScore(level=0, note="没有真的画图")},
                    status="continue", weakest="has_charts")
    # 下游 ①：best-of 的 rank 算得出来，而且一定输给正常轮次
    def rank(e):
        return (sum(1 for s in e.scores.values() if s.level >= 2),
                sum(s.level for s in e.scores.values()) / max(1, len(e.scores)))
    ok = Evaluation(scores={f"d{i}": DimensionScore(level=2, note="") for i in range(5)},
                    status="complete")
    assert rank(ev) < rank(ok), "跳过打分的那一轮不该被选成 best"
    # 下游 ②：steer 拿得到诊断原文
    assert ev.scores[ev.weakest].note == "没有真的画图"
    # 下游 ③：状态是 continue，循环会继续
    assert ev.status == "continue"


def test_有没有表格():
    from app.harness.checks import blockcheck
    assert blockcheck.has_table("说明\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    assert blockcheck.has_table("| 阶段 | 内容 |\n|:---|---:|\n| x | y |")
    assert not blockcheck.has_table("### 记录回填矩阵\n\n下表按阶段整理。\n\n[tool call needed]")
    assert not blockcheck.has_table("---\n分隔线不是表\n")


def test_生成表格没有表就不打分():
    from types import SimpleNamespace
    from app.harness.checks import table_present
    from app.harness.modes import TABLE
    st = SimpleNamespace(mode=TABLE, content="### 矩阵\n\n[tool call needed]", before="", after="")
    v = table_present(st)
    assert v and v.dimension == "table_validity" and "render_table" in v.message
    st.content = "说明\n\n| a | b |\n|---|---|\n| 1 | 2 |"
    assert table_present(st) is None
