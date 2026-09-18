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

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 标准库不算「认识这个产品」。列出来而不是 try-import，是为了让
# 名单本身可读——多一个名字要有人点头。
_STDLIB = {"__future__", "json", "re", "dataclasses", "difflib",
           "typing", "collections", "itertools", "math"}
DOC = ROOT.parent / "docs" / "harness-framework.md"


def _map_section() -> str:
    """第 3 节里**围栏中**的那张图，不含围栏外的说明文字。

    只取围栏是必须的：围栏外那句「agent 运行（harness）、知识库…」以
    `agent` 开头，按目录树去解析就成了一个叫 `agent.py` 的幽灵文件。
    """
    text = DOC.read_text(encoding="utf-8")
    section = text[text.index("## 3. 目录"):text.index("## 4. ")]
    return section[section.index("```") + 3:section.index("```", section.index("```") + 3)]


def _listed(section: str) -> set[str]:
    """图里出现过的名字。

    带不带 `.py` 都认——同一行列三四个模块时（`charts · structure ·
    grounding`）写全后缀会把一张给人看的图变成一张噪声表。
    """
    names = set(re.findall(r"[\w/]+\.py|\b[a-z_]+/", section))
    names |= {f"{w}.py" for w in re.findall(r"\b([a-z_][a-z0-9_]{2,})\b", section)}
    return names


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

    第二版又漏了一整类：一行上用 `·` 并排列几个模块（`outline ·
    restructure · textshape`、`skills · facts · provenance`）时，只有**第一个**
    名字被解析，后面的一概不查。图上 `main.py · schemas.py · prompts.py`
    里的 `schemas.py` 早就搬进 `routers/` 了，测试一声没吭。所以现在按
    `·` 切开整行，每一段取开头那个标识符；描述文字在两个以上空格之后，先
    截掉——不然「入口 · API 契约」也会被当成模块名。
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
        if name.endswith("/"):
            stack.append((indent, prefix + name))
            continue
        head = re.split(r"\s{2,}", line.strip())[0]
        for piece in head.split("·"):
            got = re.match(r"\s*([\w.-]+)", piece)
            if not got:
                continue
            word = got.group(1)
            if not re.fullmatch(r"[a-z_][\w.-]*", word):
                continue                      # 「API」这类描述词不是模块名
            paths.append((prefix + (word if word.endswith(".py") else word + ".py"),
                          indent))
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
    """`rubric.py` 和 `citations.py` 不许认识这个产品。

    这曾经靠目录边界维持（它是个独立安装的包），现在只剩这条断言。它值得
    留着的理由不是「将来要开源」，是**换个领域就能复用**——知识库判抽取
    质量用的就是同一个 evaluate()，一行新机制都没加。一旦它开始 import
    store / kite_memory，那个属性就没了。

    判据是**把相对 import 解析成绝对模块名**，不是数点的个数：文件从
    `harness/` 挪进 `harness/checks/` 时点数就变了，按点数写的断言当场
    误报（实测踩过）。
    """
    import ast

    for name in ("checks/rubric.py", "checks/citations.py"):
        path = ROOT / "app" / "harness" / name
        pkg = ["app", "harness"] + name.split("/")[:-1]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    base = pkg[:len(pkg) - node.level + 1]
                    target = ".".join(base + ([node.module] if node.module else []))
                else:
                    target = node.module or ""
                if not node.level and (target in _STDLIB or "." not in target):
                    continue                     # 标准库随便用
                assert target.startswith("app.harness"), \
                    f"{name} imports {target}——它就不再是能换领域复用的那一块了"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("app"), \
                        f"{name} imports {alias.name}"


# ------------------------------------------------------ 包自己的地图 ---


PACKAGES = ["harness", "database", "editor", "util", "routers",
            "harness/checks", "harness/hooks", "harness/middleware",
            "harness/tools", "harness/sandbox",
            "database/kite", "database/kb", "database/ingest"]


def test_每个包的入口都说清了自己是干什么的():
    """`__init__.py` 的开头是**打开这个目录时第一眼看到的东西**。

    这个仓库被问过一连串「X 是干嘛的」——kite 是 kb 的 utility 吗、ingest
    是不是 kb 的应用、这些不都是 tool 吗。每一次的答案都在代码里躺着，
    只是没写在会被看到的地方。
    """
    thin = []
    for name in PACKAGES:
        init = ROOT / "app" / name / "__init__.py"
        assert init.exists(), f"app/{name} 没有 __init__.py"
        doc = ast.get_docstring(ast.parse(init.read_text(encoding="utf-8"))) or ""
        if len(doc) < 60:
            thin.append(f"app/{name}（{len(doc)} 字）")
    assert not thin, "这些包没说清自己是干什么的：" + "、".join(thin)


def test_harness的地图列全了它自己的文件():
    """`harness/` 顶层 15 个文件，光看文件名分不出「哪个是循环本身、哪个是
    某个 middleware 背后的规则」——地图就在 `__init__.py` 里，得跟着代码走。
    """
    init = ROOT / "app" / "harness" / "__init__.py"
    doc = ast.get_docstring(ast.parse(init.read_text(encoding="utf-8"))) or ""
    files = {p.name for p in (ROOT / "app" / "harness").glob("*.py")
             if p.name != "__init__.py"}
    missing = sorted(f for f in files if f not in doc)
    assert not missing, f"harness/__init__.py 的地图漏了：{missing}"


def test_图上写的_checks_文件数跟目录里的对得上():
    """一页纸那张图上的 `checks/ ×14`。

    **`tests/test_doc_counts.py` 故意不查它**——那一条数的是「条目」
    （21 条 check、16 个 middleware），而这个 `×N` 数的是 `checks/` 下的
    **文件个数**（`__init__.py` 算在里面，批 16 / 批 18 两次都是这么加的）。
    于是它一直没有任何闸：批 19 反向验过一次，把图上的 `×14` 改回 `×13`，
    **全套 1693 条一条没红**。

    只查 `checks/` 这一个：同一张图上的 `tools/ ×22` 数的是**工具条数**
    （跟第 9 节那个 22 对齐），不是文件数——两种写法长得一样，混在一条
    断言里只会让它天天误报。
    """
    doc = DOC.read_text(encoding="utf-8")
    written = {int(n) for n in re.findall(r"checks/ ?[×x] ?(\d+)", doc)}
    real = len(list((ROOT / "app" / "harness" / "checks").glob("*.py")))
    assert written, "图上一次都没写 `checks/ ×N`——这条断言在查一个不存在的说法"
    assert written == {real}, f"图上写着 checks/ ×{sorted(written)}，实际 {real} 个文件"


def _block_under(section: str, head: str) -> str:
    """图里 `head` 那一行，加上它下面所有缩进更深的行。"""
    lines = section.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(head):
            base = len(line) - len(line.lstrip())
            out = [line]
            for nxt in lines[i + 1:]:
                if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= base:
                    break
                out.append(nxt)
            return "\n".join(out)
    raise AssertionError(f"图上找不到 {head}")


def test_checks_下的每个文件都列在图里_checks_那一块下面():
    """**比 `test_harness_下的每个文件都在图上` 严一档，而且严得有理由。**

    那一条是个词袋：只要那个词在整张图里**任何地方**出现过就算数。批 19 反向
    验过一次——把 `checks/` 那一块里的 `skeleton` 整条摘掉，**全套一条没红**，
    因为图上 `routers/compose.py` 那一行的「单点动作：skeleton · magic-tap …」
    里也有这个词。*一个判据被别处的同名词顺手满足了，它就没在判它要判的事。*

    这一条只管 `checks/`：把文件名限定在那一块的范围里找。别的目录暂时照旧
    ——那条词袋断言的宽度是它自己的事，这一批只把踩到的这一格收紧。
    """
    block = _block_under(_map_section(), "checks/")
    # **按「列表项」找，不按子串找**（批 20 补的）：第一版是 `stem not in block`，
    # 于是把 `· tap（magic tap 那四条…` 整条摘掉它照样绿——同一块里
    # 「magic tap」这几个字顺手把 `tap` 满足了。**词袋在这一格里又长回来了一次**
    # （批 19 ㉜ 刚为同一个病把这条断言从整张图收到这一块）。
    # 现在要求文件名出现在行首或者一个 `·` 后面，后面跟的是空白 /「（」/「·」。
    def listed(stem: str) -> bool:
        return bool(re.search(r"(?m)(?:^\s*|·\s*)" + re.escape(stem) + r"(?=[\s（(·]|$)",
                              block))

    missing = sorted(p.stem for p in (ROOT / "app" / "harness" / "checks").glob("*.py")
                     if p.name != "__init__.py" and not listed(p.stem))
    assert not missing, f"这些判据文件没列在图上 checks/ 那一块里：{missing}"
