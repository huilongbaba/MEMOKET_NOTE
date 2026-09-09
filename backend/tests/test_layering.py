"""Dependency rules, enforced by reading imports.

Every boundary this file protects was crossed at some point, and each time
there was a perfectly reasonable "it's just this one small function" argument
for it. Written down as a test, that argument has to be made in a pull
request instead of in passing.

Layers, top to bottom:

    L1  app/routers/     thin shells
    L2  app/harness/     the loop, State, middleware, checks, modes
    L3  app/kb/          knowledge-base capabilities above KITE
    L3  app/            capabilities: agent_loop, llm, store, kite_memory, tools
    L4  pure functions   tabular, blocks, outline, textshape, restructure, ...
    L5  scoring/  the package
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Only the standard library. These are where every deterministic judgement
# lives, and keeping them dependency-free is what makes them testable by
# constructing a string -- which in turn is why the regression suite for real
# failing output exists at all.
PURE = ["tabular", "blocks", "blockcheck", "textshape", "outline",
        "restructure", "grounding_check", "runtime_policy", "replan"]


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
                target = ".".join(base + tuple((node.module or "").split(".")))
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
        if not path.exists():
            continue
        external = {m for m in _imports(path)
                    if m not in stdlib_ok and not m.startswith("_")}
        assert not external, f"app/{name}.py grew a dependency: {external}"


def test_the_package_does_not_know_about_this_app():
    """The single condition for scoring being extractable. One import
    of ``app`` and the only way to open-source it is to untangle it again."""
    for path in (ROOT / "scoring" / "src").rglob("*.py"):
        offending = {m for m in _imports(path) if m == "app" or m.startswith("app.")}
        assert not offending, f"{path.name} imports {offending}"


def test_routers_do_not_import_each_other():
    """A router reaching into another router means something belongs one layer
    down. Six of these existed; all six moved (``profile``, ``retrieval``,
    ``chunking``, ``harness/events``, ``harness/params``, ``harness/revision``)."""
    violations: list[str] = []
    for path in (ROOT / "app" / "routers").glob("*.py"):
        if path.name in {"__init__.py", "deps.py"}:
            continue
        for module in _imports(path):
            if module.startswith("app.routers.") and not module.endswith(".deps"):
                other = module.split(".")[-1]
                if other != path.stem:
                    violations.append(f"{path.name} -> {other}")
    assert not violations, f"routers importing routers: {violations}"


def test_harness_does_not_import_routers():
    """The loop must not know which endpoint is driving it."""
    for path in (ROOT / "app" / "harness").rglob("*.py"):
        offending = {m for m in _imports(path) if "routers" in m}
        assert not offending, f"{path} imports {offending}"


def test_tools_do_not_import_the_harness():
    """The tool pool is a layer below. It shares mutable state with whatever
    drives it through ``ToolContext.scratch`` -- a plain dict -- precisely so
    it never has to know a harness exists."""
    for path in (ROOT / "app" / "tools").glob("*.py"):
        offending = {m for m in _imports(path) if "harness" in m}
        assert not offending, f"{path.name} imports {offending}"


def test_the_knowledge_base_layer_knows_nothing_above_it():
    """``app/kb`` sits above KITE and below everything that writes.

    It has no business knowing that a harness or an endpoint exists: the same
    clustering and the same extraction judgement should be runnable from a
    script, and one import upward is all it takes for that to stop being
    true.
    """
    for path in (ROOT / "app" / "kb").glob("*.py"):
        # 注意匹配的是 app 自己的那个 harness 包，不是 scoring——
        # 后者是它下面一层的、可独立开源的包，kb 用它的 evaluate() 正是设计。
        # kb 用 harness 的打分引擎（rubric）和它的类型是**设计**——抽取判据
        # 复用同一个 evaluate()，换一组 dimensions 就换个领域。不许碰的是
        # 循环本身：State / loop / middleware / hooks。
        allowed = {"app.harness.rubric", "app.harness.types"}
        offending = {m for m in _imports(path)
                     if ("app.routers" in m
                         or (m.startswith("app.harness") and m not in allowed))}
        assert not offending, f"{path.name} imports {offending}"


def test_the_pure_layer_list_is_still_accurate():
    """A module that quietly grows a dependency stops being testable by
    constructing a string -- and the list above is what says which modules
    are supposed to stay that way, so an entry that no longer exists makes
    the whole check silently weaker."""
    missing = [n for n in PURE if not (ROOT / "app" / f"{n}.py").exists()]
    assert not missing, f"PURE lists modules that are gone: {missing}"
