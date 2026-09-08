"""打分拿到的材料必须是**跨轮累积**的，不能每轮清零。

这个 bug 在这个仓库里犯过三次：
  · note_harness —— round_facts 每轮重置，打分拿本轮材料审判累积的正文（已修）
  · compose_block —— 同一个坑，第 3 轮写出「无法调用 chart_from_text」（已修）
  · writing_plan —— 一直没人发现，直到实测数据显示它相邻轮次平均掉 0.278，
    而同期 compose_block 是 +0.222（已修）

三次都是"跨轮的东西"和"每轮的东西"都是同一个函数里的局部变量，差别只在缩进。
所以这里不测行为测**结构**：传给打分的那个变量，它的初始化不能在循环体内。
"""

import ast
import pathlib

# (文件, 打分函数名, 材料参数名)
TARGETS = [
    ("app/routers/writing_plan.py", "_evaluate_section", "facts_used"),
    ("app/routers/note_harness.py", "_evaluate_round", "facts_used"),
]


def _loop_bodies(tree: ast.AST) -> list[ast.AST]:
    out = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.While, ast.For, ast.AsyncFor)):
            out += list(n.body) + list(n.orelse)
    return out


def _names_assigned_in(nodes: list[ast.AST]) -> set[str]:
    """这些节点（含嵌套）里，哪些变量被**初始化**成空列表。"""
    out: set[str] = set()
    for node in nodes:
        for n in ast.walk(node):
            tgt = val = None
            if isinstance(n, ast.AnnAssign) and n.value is not None:
                tgt, val = n.target, n.value
            elif isinstance(n, ast.Assign) and len(n.targets) == 1:
                tgt, val = n.targets[0], n.value
            if isinstance(tgt, ast.Name) and isinstance(val, ast.List) and not val.elts:
                out.add(tgt.id)
    return out


def _arg_names(tree: ast.AST, func: str, kw: str) -> list[str]:
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        name = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
        if name != func:
            continue
        for k in n.keywords:
            if k.arg == kw and isinstance(k.value, ast.Name):
                out.append(k.value.id)
    return out


def test_打分拿到的材料是跨轮累积的():
    root = pathlib.Path(__file__).resolve().parents[1]
    checked = 0
    for rel, func, kw in TARGETS:
        tree = ast.parse((root / rel).read_text())
        per_round = _names_assigned_in(_loop_bodies(tree))
        for var in _arg_names(tree, func, kw):
            checked += 1
            assert var not in per_round, (
                f"{rel}：传给 {func}({kw}=) 的 `{var}` 在循环体内被初始化成 []，"
                f"就是每轮清零。正文是累积的，材料也必须是——"
                f"把累积的那份传进去（见本文件顶部注释里的三次前科）。"
            )
    assert checked >= 2, "没扫到打分调用，TARGETS 可能过期了"
