

def test_围栏里的待确认不是占位句():
    """第 663 轮真跑抓到的：模型画了一张 mermaid，节点写着
    `B[EVT样品实际时间待确认]`，判据当成占位句拦下来、连拦两轮。

    可那句话不是「我还没写」，是**这个项目的状态就是「实际时间待确认」**——
    而这篇笔记的目标恰恰是「计划时间、决策状态、验证证据、实际结果，
    缺哪一项就写待核实」。图里的节点名是内容，不是占位。
    跟第 607 轮「手写最简流程图放行」同一个道理：
    **判据不能把自己看不懂的东西一律当成毛病。**
    """
    from app.harness.checks.grounding_rules import placeholder_lines

    md = ("一段正常的话。\n\n```mermaid\ngraph TD\n"
          "A[4月10日 UVD制作取消] --> B[EVT样品实际时间待确认]\n```\n\n"
          "| 麦克 | 待确认 |\n")
    got = placeholder_lines(md)
    assert got == ["| 麦克 | 待确认 |"], got


def test_围栏外的占位照样抓():
    from app.harness.checks.grounding_rules import placeholder_lines

    assert placeholder_lines("交付时间：待定\n") == ["交付时间：待定"]
    assert placeholder_lines("```\n交付时间：待定\n```\n") == []


def test_引号里的占位词是在提到它_不是在用它():
    """真跑产出里有这么一句：「缺失项明确标为「待补」，而不是用阶段名称代替事实。」
    ——那是在陈述一条规矩，不是留了个坑。

    原来这件事是**碰运气**的：`“待补”` 不报（后面跟的 `”` 不在终止符表里），
    `「待补」` 就报（`」` 在表里）——同一个意思、两种引号、两种结果。
    """
    from app.harness.checks.grounding_rules import placeholder_lines

    for q in ('“待补”', '「待补」', '『待确认』', '"待定"'):
        line = f"缺失项明确标为{q}，而不是用阶段名称代替事实。"
        assert placeholder_lines(line) == [], line

    # 引号长到装得下一句话时，里面的占位照样算——那不是在提一个词
    assert placeholder_lines("结论：「这一批的交付时间和验收标准都待确认」")
    # 没引号的照旧
    assert placeholder_lines("交付时间：待补")
