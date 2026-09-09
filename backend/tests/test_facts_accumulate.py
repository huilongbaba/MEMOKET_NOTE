"""打分拿到的材料必须是**跨轮累积**的，不能每轮清零。

这个 bug 在这个仓库里犯过三次：
  · note_harness —— round_facts 每轮重置，打分拿本轮材料审判累积的正文
  · compose_block —— 同一个坑，第 3 轮写出「无法调用 chart_from_text」
  · writing_plan —— 一直没人发现，直到实测数据显示它相邻轮次平均掉 0.278，
    而同期 compose_block 是 +0.222

三次都是同一个形状：「跨轮的东西」和「每轮的东西」都是同一个函数里的局部
变量，差别只在缩进。这个测试原来用 AST 去查「传给打分的那个变量是不是在
循环体里初始化成 []」——那是在三份拷贝的前提下能做的最好防御。

现在只有一份循环，材料是 ``State`` 上的字段，写入方只有 ``Facts``。所以
钉的东西也变了：**打分只有一个调用点，它读累积字段；累积字段只有一个写入
方。** 满足这两条，那个 bug 就不再是能写出来的形状。
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
HARNESS = ROOT / "app" / "harness"


def _sources() -> dict[str, str]:
    return {str(f.relative_to(ROOT)): f.read_text(encoding="utf-8")
            for f in HARNESS.rglob("*.py")}


def test_打分只有一个调用点():
    """三份拷贝时，「哪一份传错了材料」是个要逐份检查的问题。"""
    sites = [(name, src.count("await evaluate("))
             for name, src in _sources().items() if "await evaluate(" in src]
    assert sites == [("app/harness/loop.py", 1)], f"打分调用点不止一处：{sites}"


def test_打分拿到的是累积正文和这个mode的维度(monkeypatch):
    """打分不能只拿本轮的材料——正文是累积的，只按本轮材料判，会对着写作者
    上一轮刚用过的一句话报「知识库里没有」（实测撞过）。

    以前这条查的是「loop.py 里那段源码字符串包不包含 facts_new」。那种
    断言两头都不对：换个参数名它就红，真传错了、只要字符串还在它照样绿。
    现在直接看 evaluate() 收到了什么。
    """
    import asyncio

    from app.harness import loop as loop_mod
    from app.harness.state import State
    from app.harness.tools import ToolContext
    from app.harness.types import Dimension, DimensionScore, Evaluation, Mode

    seen = {}

    async def fake_evaluate(client, *, content, dimensions, **kw):
        seen.update(content=content, dimensions=dimensions, kw=kw)
        return Evaluation(scores={"d0": DimensionScore(level=2, note="")},
                          status="complete", weakest=None)

    monkeypatch.setattr(loop_mod, "evaluate", fake_evaluate)

    mode = Mode(key="t", label="t", skill_scope="test_scope",
                dims=(Dimension("d0", "..."), Dimension("d1", "...")))
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n"))
    st.content = "累积到现在的全部正文"
    st.facts = ["第一轮查到的", "第二轮查到的"]
    st.facts_new = ["只有第二轮的"]
    st.bag["score_context"] = {"核心张力": "张力"}

    asyncio.run(loop_mod._score(st))
    assert seen["content"] == "累积到现在的全部正文"
    assert [d.name for d in seen["dimensions"]] == ["d0", "d1"], \
        "维度要按这个 Mode 实际配的来"
    assert seen["kw"]["context"] == {"核心张力": "张力"}


def test_累积规则只有一个写入方():
    """恢复快照也写这个字段，但那不是累积——它是把上次累积的结果放回去。
    白名单里多一个就要在这里写明为什么，不能默默多出来。"""
    allowed = {
        "app/harness/middleware/facts.py",   # 累积规则本身
        "app/harness/snapshot.py",           # 轮末暂停后把上次的结果放回去
    }
    writers = {name for name, src in _sources().items() if "st.facts = " in src}
    assert writers == allowed, f"st.facts 的写入方变了：{sorted(writers)}"


def test_没有任何地方在循环体里把材料清零():
    """原来那条 AST 检查的等价形态：轮循环在 loop.py 里，材料不许在里面重置。"""
    tree = ast.parse((HARNESS / "loop.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Assign) or len(inner.targets) != 1:
                continue
            tgt = inner.targets[0]
            if (isinstance(tgt, ast.Attribute) and tgt.attr == "facts"
                    and isinstance(inner.value, ast.List)):
                raise AssertionError("轮循环里把 st.facts 清零了")
