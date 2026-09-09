"""文档第 3 节那张目录图，必须跟代码对得上。

**这条测试的来历**：仓库的主人拿着这张图去对代码，对不上——图里没有
`app/scoring/`、没有 `app/kb/`、没有 `harness/hooks/`，而图里写着的
`middleware/policy.py` 早就拆成了 `repair.py` + `runtime.py`。

一张对不上的地图比没有地图更糟：没有地图你会去读代码，有一张错的你会
先信它，然后花时间怀疑自己。所以图和代码之间要有一条断言。

只查**目录**和 `harness/` 下的文件名，不查每一个文件——图的用处是「这块
代码归哪一节管」，细到每个纯函数模块就成了维护负担，而那些本来就写在
「不动的」那一段里。
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = ROOT.parent / "docs" / "harness-framework.md"


def _map_section() -> str:
    text = DOC.read_text(encoding="utf-8")
    start = text.index("## 3. 目录")
    return text[start:text.index("## 4. ")]


def _listed(section: str) -> set[str]:
    """图里出现过的名字。缩进和注释都无所谓，只认名字本身。"""
    return set(re.findall(r"[\w/]+\.py|\b[a-z_]+/", section))


def test_app_下的每个包都在图上():
    """一个目录不在图上 = 这块代码没有归属，读文档的人不知道它归哪一节管。"""
    listed = _listed(_map_section())
    packages = {f"{d.name}/" for d in (ROOT / "app").iterdir()
                if d.is_dir() and (d / "__init__.py").exists()}
    missing = sorted(packages - listed)
    assert not missing, f"这些包不在第 3 节的图上：{missing}"


def test_harness_下的每个文件都在图上():
    """循环本体是这份文档的正题，它的每个文件都该能在图上找到。"""
    listed = _listed(_map_section())
    files = {p.name for p in (ROOT / "app" / "harness").rglob("*.py")
             if p.name != "__init__.py"}
    missing = sorted(files - listed)
    assert not missing, f"这些文件不在第 3 节的图上：{missing}"


def _tree_paths(section: str) -> list[tuple[str, int]]:
    """把图按缩进解析成真实路径。

    只按文件名找是不够的——第一版就是这么写的，反向验证时往图里塞了一个
    已经删掉的 `middleware/policy.py`，测试没抓到：`policy.py` 在
    `app/sandbox/` 下真的存在，同名把它放过去了。
    """
    paths: list[tuple[str, int]] = []
    stack: list[tuple[int, str]] = []
    for line in section.splitlines():
        m = re.match(r"^(\s*)([\w./-]+/?)(\s|$)", line)
        if not m or line.lstrip().startswith(("↑", "…")):
            continue
        indent, name = len(m.group(1)), m.group(2)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        prefix = stack[-1][1] if stack else ""
        full = prefix + name
        if name.endswith("/"):
            stack.append((indent, full))
        elif name.endswith(".py"):
            paths.append((full, indent))
    return paths


def test_图上没有已经不存在的文件():
    """反过来也要查。图里留着一个删掉的文件，读的人会去找它。

    实测漂过：图上的 `middleware/policy.py` 早就拆成 `repair.py` +
    `runtime.py` 了，图没跟着改。
    """
    section = _map_section()
    ghosts = [rel for rel, _ in _tree_paths(section)
              if not (ROOT.parent / rel).exists() and not (ROOT / rel).exists()]
    assert not ghosts, f"图上有代码里不存在的文件：{ghosts}"


def test_打分引擎不依赖这个产品():
    """`rubric.py` 和它的三个零 LLM 邻居不许认识这个产品。

    这曾经靠目录边界维持（它是个独立安装的包），现在只剩这条断言。它值得
    留着的理由不是「将来要开源」，是**换个领域就能复用**——知识库判抽取
    质量用的就是同一个 evaluate()，一行新机制都没加。一旦它开始 import
    store / kite_memory，那个属性就没了。
    """
    import ast

    engine = ["rubric.py", "dedup.py", "compaction.py", "citations.py"]
    for path in [(ROOT / "app" / "harness" / n) for n in engine]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                # 相对 import 只允许 scoring 包内部（level 1）
                assert node.level <= 1, f"{path.name} 伸到了 harness 外面"
                if node.module and node.module.startswith("app"):
                    raise AssertionError(f"{path.name} imports {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("app"), \
                        f"{path.name} imports {alias.name}"
