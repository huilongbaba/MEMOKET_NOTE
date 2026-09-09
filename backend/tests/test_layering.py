"""Dependency rules, enforced by reading imports.

Every boundary this file protects was crossed at some point, and each time
there was a perfectly reasonable "it's just this one small function" argument
for it. Written down as a test, that argument has to be made in a pull
request instead of in passing.

Layers, top to bottom:

    L1  app/routers/         thin shells
    L2  app/harness/         the loop, State, middleware, checks, modes
    L3  app/database/kb/     knowledge-base capabilities above KITE
    L3  app/database/        store · retrieval · kite adapters
    L4  pure functions       tabular, blocks, outline, textshape, restructure
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Only the standard library. These are where every deterministic judgement
# lives, and keeping them dependency-free is what makes them testable by
# constructing a string -- which in turn is why the regression suite for real
# failing output exists at all.
# 名单就是目录本身——之前是手写的，跟代码分开维护，搬一次文件就对不上了。
# 这九个模块的**性质**是「只依赖标准库、给个字符串就能测」，跟它们放在
# 哪个包无关——按职责重排之后它们散在 harness/checks、harness/tools 和
# editor/ 三处。名单只能显式写，但每一条都有具体理由：它们承载了全部
# 确定性判据，那是这个产品对抗「模型自己判自己」的唯一手段。
PURE = ["harness/checks/blockcheck", "harness/checks/grounding_rules",
        "harness/tools/tabular", "harness/tools/blocks",
        "harness/policy", "harness/replan_rules",
        "editor/outline", "editor/restructure", "editor/textshape"]


def _files(*parts: str, deep: bool = False) -> list[pathlib.Path]:
    """一层里的所有 .py，**并且断言这一层不是空的**。

    这条断言是被三条静默失效的测试逼出来的：`scoring/src`、`app/tools`、
    `app/kb` 三个目录在重构里全搬了家，而三条分层测试还在对着旧路径
    glob。空集合上跑 for 循环不报错——三条架构不变量green 了不知道多久，
    实际上一个字节都没检查。

    发现型的集合必须自证非空，否则「测试通过」只说明没找到文件。
    """
    base = ROOT.joinpath(*parts)
    found = sorted(base.rglob("*.py") if deep else base.glob("*.py"))
    assert found, f"{base} 下一个 .py 都没有——这一层搬走了还是改名了？"
    return found


def _imports(path: pathlib.Path) -> set[str]:
    """Top-level module names this file imports, relative imports resolved to
    the package they land in."""
    tree = ast.parse(path.read_text())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = path.relative_to(ROOT).with_suffix("").parts
                base = parts[:max(0, len(parts) - node.level)]
                target = ".".join(base + tuple(
                    x for x in (node.module or "").split(".") if x))
                # `from ..x import y`：y 如果自己就是个模块，解析成 x.y。
                # 不这么做的话，`from ...harness import adapter` 和
                # `from ...harness import loop` 在这里长得一模一样（都只是
                # `app.harness`），要放行前者就只能连后者一起放行。
                for alias in node.names:
                    sub = ROOT.joinpath(*target.split("."), alias.name)
                    if sub.with_suffix(".py").exists() or sub.is_dir():
                        out.add(f"{target}.{alias.name}")
                    else:
                        out.add(target)
            elif node.module:
                out.add(node.module.split(".")[0])
    return out


def test_pure_layer_imports_only_the_standard_library():
    stdlib_ok = {"re", "math", "difflib", "json", "dataclasses", "typing",
                 "collections", "itertools", "functools", "enum", "datetime",
                 "__future__"}
    for name in PURE:
        path = ROOT / "app" / f"{name}.py"
        assert path.exists(), f"PURE 名单里的 {name} 不在了——搬走了还是删了？"
        external = {m for m in _imports(path)
                    if m not in stdlib_ok and not m.startswith("_")}
        assert not external, f"app/{name}.py grew a dependency: {external}"


def test_routers_do_not_import_each_other():
    """A router reaching into another router means something belongs one layer
    down. Six of these existed; all six moved (``profile``, ``retrieval``,
    ``chunking``, ``harness/events``, ``harness/params``, ``harness/revision``)."""
    violations: list[str] = []
    for path in _files("app", "routers"):
        # deps（所有 router 共用的依赖）和 schemas（API 契约）不是 router，
        # 是这一层里共享的东西——它们没有自己的端点，也不该有。
        if path.name in {"__init__.py", "deps.py", "schemas.py"}:
            continue
        for module in _imports(path):
            if module.startswith("app.routers.") \
                    and not module.endswith((".deps", ".schemas")):
                other = module.split(".")[-1]
                if other != path.stem:
                    violations.append(f"{path.name} -> {other}")
    assert not violations, f"routers importing routers: {violations}"


def test_harness_does_not_import_routers():
    """The loop must not know which endpoint is driving it."""
    for path in _files("app", "harness", deep=True):
        offending = {m for m in _imports(path) if "routers" in m}
        assert not offending, f"{path} imports {offending}"


def test_tools_do_not_import_the_harness_runtime():
    """工具池不认识循环。

    原话是「工具池在下面一层」——那时它在 `app/tools/`。按职责重排之后它
    进了 `app/harness/tools/`，**这条测试却还在对 `app/tools/` glob，空集
    上静默绿了整段重构**。位置变了，可这条边界本身没变，只是要说得更准：
    工具可以用 harness 的能力（`skills`、`sandbox`），但不许认识运行时——
    loop / state / modes / types / agent_loop / middleware / hooks / checks。
    它跟驱动方之间只有 `ToolContext.scratch` 这一个 dict，正是为了不用知道
    有没有 harness 在跑。
    """
    runtime = {"loop", "state", "modes", "types", "agent_loop",
               "middleware", "hooks", "checks", "adapter", "snapshot"}
    for path in _files("app", "harness", "tools"):
        offending = {m for m in _imports(path)
                     if m.startswith("app.harness.")
                     and m.split(".")[2] in runtime}
        assert not offending, f"{path.name} imports {offending}"


def test_the_knowledge_base_layer_knows_nothing_above_it():
    """``app/database/kb`` sits above KITE and below everything that writes.

    It has no business knowing that a harness or an endpoint exists: the same
    clustering and the same extraction judgement should be runnable from a
    script, and one import upward is all it takes for that to stop being
    true.
    """
    for path in _files("app", "database", "kb"):
        # 注意匹配的是 app 自己的那个 harness 包，不是 scoring——
        # 后者是它下面一层的、可独立开源的包，kb 用它的 evaluate() 正是设计。
        # kb 用 harness 的打分引擎（rubric）和它的类型是**设计**——抽取判据
        # 复用同一个 evaluate()，换一组 dimensions 就换个领域。不许碰的是
        # 循环本身：State / loop / middleware / hooks。
        # adapter 也在名单里：kb 要打分就要一个 LLMClient 实现，而 adapter
        # 就是「把协议接到 util/llm 和 database/store 上」的那条缝。它不是
        # 循环——放行它跟这条测试要守的东西（kb 不认识 loop、不认识端点）
        # 不冲突。
        allowed = {"app.harness.checks.rubric", "app.harness.types",
                   "app.harness.adapter"}
        offending = {m for m in _imports(path)
                     if ("app.routers" in m
                         or (m.startswith("app.harness") and m not in allowed))}
        assert not offending, f"{path.name} imports {offending}"


def test_the_pure_layer_list_points_at_real_files():
    """名单是手写的，就必须有东西盯着它别过期——一个不存在的条目会让
    整条纯度检查静默地少查一个模块。"""
    missing = [n for n in PURE if not (ROOT / "app" / f"{n}.py").exists()]
    assert not missing, f"名单里这些文件不在了：{missing}"


def test_editor这一层不认识harness也不认识端点():
    """文件夹/正文这类编辑操作跟 agent 无关。

    它反过来被 harness 用（`outline` 那几个纯函数四处都在调），所以方向
    一旦反过来就是环：改一次大纲判据要同时想 harness 和 editor 两边。
    """
    for path in _files("app", "editor"):
        offending = {m for m in _imports(path)
                     if m.startswith(("app.harness", "app.routers"))}
        assert not offending, f"{path.name} imports {offending}"


def test_util和database之间只有那一条窄依赖():
    """这两个包**互相**依赖，是有意的，但只许这么窄。

    实情：``database/*`` 要 ``util.config`` 拿设置，而 ``util/llm`` 要
    ``database.store`` 拿「用户当前选的是哪个供应商」——那个选择存在库里，
    这条依赖本身是对的，LLM 客户端不知道用户选了谁就没法工作。

    问题不在有这条边，在于它是**悄悄长出来的**：`util` 在文档里被写成
    「公共 utilities」，读的人会当它是最底层。所以这里把它钉死成一条窄边，
    再宽一点就红——比如哪天 `util` 开始 import `database.kb`，或者
    `database` 开始 import `util.llm`，那才是真的绕成一团。
    """
    for path in _files("app", "util"):
        upward = {m for m in _imports(path) if m.startswith("app.")
                  and not m.startswith("app.util")}
        assert upward <= {"app.database.store"}, \
            f"{path.name} 越界了：{sorted(upward - {'app.database.store'})}"

    for path in _files("app", "database", deep=True):
        into_util = {m for m in _imports(path) if m.startswith("app.util")}
        assert into_util <= {"app.util.config"}, \
            f"{path.name} 从 util 里拿了不该拿的：{sorted(into_util)}"
