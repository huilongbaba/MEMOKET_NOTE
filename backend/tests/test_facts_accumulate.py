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


def test_打分读的是累积字段():
    src = (HARNESS / "loop.py").read_text(encoding="utf-8")
    i = src.index("await evaluate(")
    call = src[i:i + 400]
    assert "dimensions=list(st.mode.dims)" in call
    assert "facts_new" not in call, "打分不能只拿本轮材料——正文是累积的"


def test_累积字段只有一个写入方():
    writers = sorted(name for name, src in _sources().items()
                     if "st.facts = " in src)
    assert writers == ["app/harness/middleware/facts.py"], \
        f"st.facts 有多个写入方，累积规则又要分叉了：{writers}"


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
