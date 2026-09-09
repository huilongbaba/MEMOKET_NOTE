"""两条长循环 harness 该有的能力必须都有。

「同一个能力，一条 harness 有、另一条没有」在这个仓库里发生过四次，
每次都不是决定，是遗漏：

  · find_repeats —— compose_block 没有
  · compact_context —— 只有 note_harness 有
  · record_harness_run —— compose_block 没有
  · material_exhausted「材料用完就停」—— writing_plan 没有

最后一条造成了可测量的损失：实测 writing_plan 逐轮 non_repetition
2.00 → 1.25 → 1.00（掉的是"重复"），而 factual_grounding 持平；
同期有这条防线的 note_harness 只有 −0.042，compose_block 是 +0.222。

这个测试原来比对两个 router 的源码字符串，因为那时每条 harness 各写一份
循环。现在能力是 middleware 和停机条件，一份实现，按 Mode 挂上——所以这里
钉的是**挂没挂上**，以及默认全开的那批谁都关不掉。
"""

from app.harness import modes
from app.harness.middleware import BASE

# 长循环 harness：写一篇会越写越长的东西。compose_block 是单块生成、最多
# 3 轮，材料耗尽和逐轮落盘那套对它没意义，所以不在名单里——**缺席要么在
# 名单里，要么写在这段注释里，不能是沉默的。**
LONG_FORM = (modes.NOTE, modes.SECTION)

# (middleware 名, 这个能力是干什么的)
REQUIRED_MW = [
    ("repeats", "机械查重，结果喂给修订和打分当 non_repetition 的证据"),
    ("history", "记 run 历史，供跨轮经验复用"),
    ("facts", "材料跨轮累积并封顶"),
    ("revise", "回头修已经写坏的，不然正文只能越长越歪"),
    ("repair", "内在质量维度弱时只理顺、不续写"),
    ("compact", "续写 prompt 的上下文压缩"),
    ("save", "逐轮落盘，关掉标签页不丢已写的"),
]


def _chain(mode) -> list[str]:
    return [getattr(m, "name", type(m).__name__) for m in (*BASE, *mode.extra_mw)]


def test_长循环harness的能力对等():
    missing = []
    for mode in LONG_FORM:
        names = _chain(mode)
        for name, why in REQUIRED_MW:
            if name not in names:
                missing.append(f"{mode.key} 缺 {name}——{why}")
        if modes.material_used_up not in mode.stop_when:
            missing.append(f"{mode.key} 缺「材料用完就停」，不然只能把同一批事实换措辞重说")
    assert not missing, "长循环 harness 能力不对等：\n  " + "\n  ".join(missing)


def test_默认全开的能力没有被谁悄悄关掉():
    """``rails_off`` 是显式的关闭清单。关一个可以，但要写下来，不能是遗漏。"""
    for mode in modes.ALL:
        assert not mode.rails_off, (
            f"{mode.key} 关掉了 {mode.rails_off}——关是可以的，但这条断言就是逼你在"
            "关的时候顺手把理由写进 modes.py 的注释里，然后改这个测试")


def test_累积的材料按section分开():
    """writing_plan 是分段写作：A 段的材料拿去审判 B 段，是另一个方向的
    同一个错误。

    以前靠一个按 section id 分桶的字典。现在靠的是**一个 section 一次 run，
    一次 run 一个 State**——材料是 State 上的字段，跨不过去。所以这里测的是
    两次 run 之间不串。
    """
    import asyncio

    from app.harness.agent_loop import ToolTrace
    from app.harness.middleware.facts import Facts
    from app.harness.state import State
    from app.harness.tools import ToolContext

    ctx = ToolContext(user="u", note_id="n")
    a = State(mode=modes.SECTION, ctx=ctx)
    b = State(mode=modes.SECTION, ctx=ctx)
    for st, fact in ((a, "A 段的材料"), (b, "B 段的材料")):
        st.trace = ToolTrace()
        st.facts_new = [fact]
        asyncio.run(Facts().after_prepare(st))
    assert a.facts == ["A 段的材料"] and b.facts == ["B 段的材料"]


def test_一个section一次run():
    """上一条测的前提：plan 循环确实是每个 section 建一个新 State。"""
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1]
           / "app" / "routers" / "writing_plan.py").read_text(encoding="utf-8")
    assert src.count("st = State(") == 1, "State 应该在 plan 循环体内建一次"
    body = src[src.index("while steps < PLAN_SAFETY_CAP"):]
    assert "st = State(" in body, "State 建在循环外，两个 section 就会共用材料"
