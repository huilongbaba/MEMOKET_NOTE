"""P59：P58 留下的三条（② 静默 `fix` 配措辞 / ③ `truncated_citations` 的射程 /
④ `STUCK_ROUNDS` 放行支写不写 `check_released`）。

**① advisory 真跑复测**那一条的结论在台账 P59 节，不在这儿：它是量出来的，不是钉出来的
（判据侧、中间件侧、接线洞三条闸在 `tests/test_p58.py`，这一批一个字没动）。
⑤ 逐轮材料清单记在**重放器**那一侧（`<scratch>/p59/p59_run.py`），不是产品，
自证在 `<scratch>/p59/ledger9.py`（四条不变量 + 按批那一条，5 篇全过）。

---

## ② 那 7 处静默 `fix`（P58 走查 #2）

P58 静态扫出来 **12 处 `Verdict(... fix=...)`，只有 5 处填了 `fix_note`**——
另外 7 处动了用户眼前的正文，对模型和用户都不说一个字
（全修那一支在 `middleware/checks.py` 里直接 `continue`，`message` 一个读者都到不了）。

**先量再改**（`<scratch>/p59/silent9.py`，15 批 / 61 份跑 / 284 轮的 run json）：
**这 7 条判据一次都没响过（0/284）**；唯一真开过火的 `fix` 是 `no_echoed_text`
（响 4 次、3 次走全修），而它本来就有 `fix_note`。所以这一改**在已量到的语料上
动不了任何一轮的产出**，补的是「哪天响了，用户和模型能知道正文被改了什么」那个洞。

逐处判过「说不说得清」，**7 处全都说得清**，于是 `SILENT_FIXES` 清空、
`tests/test_p26.py` 那条 AST 闸的三个数从 12/5/7 变成 12/12/0。
下面每一条各摆一处：措辞非空、说的是**做了什么**、而且 `fix` 真的改得动正文。

## ③ `truncated_citations` 的射程（P58 ④⑤）

P58 ⑤ 问「命名空间要不要算正文里已有的合法 id」。**读源码：它本来就算了**
（`citations.py` 里 `ns = id_prefixes(cited_ids(text)) | id_prefixes(supplied_ids(facts))`）。
量（`<scratch>/p59/reach9.py`，p53/p55/p57/p59 四批 75 轮）：
正文光靠自己就够得着 **65/75**；材料那一半（只有 p59 记了逐轮清单）**20/20 轮都有**；
两边都空 **0**。P53 那份唯一的残骸 `[terrence-8F6]` 活了 7 轮，**其中 3 轮光靠正文就够得着**。
所以**一个字没改**，下面那条闸把「正文那一半自己就够用」钉住——
`tests/test_p55.py` 只钉了「两边都空就一个都不报」，反过来那一半没人钉。

## ④ `STUCK_ROUNDS` 放行支（P58 走查 #5）

P58 说「没复现的局面不改」。P59 **把局面摆出来了**（`<scratch>/p59/stuck9.py`，
真 `loop.run` + 假打分器），结论**还是不加**，三条理由写在
`middleware/checks.Checks.after_judge` 的 docstring 里。下面两条闸钉住其中两条能钉的：
这一支今天确实不写那个键（免得下一批又从零复现一次），
以及「8 个模式里 6 个的 `stop_when` 没有 `check_stuck`」那个数。
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.harness import modes                                        # noqa: E402
from app.harness.checks import charts as C                           # noqa: E402
from app.harness.checks import citations as cit                      # noqa: E402
from app.harness.checks import grounding as G                        # noqa: E402
from app.harness.checks import language as L                         # noqa: E402
from app.harness.checks import structure as S                        # noqa: E402
from app.harness.state import State                                  # noqa: E402
from app.harness.tools import ToolContext                            # noqa: E402
from app.harness.types import Mode                                   # noqa: E402


def _st(content: str, *, facts=(), before="", after="", groups=("memory",)) -> State:
    """一份能让下面这几条判据看得见素材的 State。`before` / `after` 是光标两侧的正文
    （`heading_fits` / `tail_clashes` 读它们），`content_at_start` 是开跑前那一份
    （四条判据都只管「这次跑新写的」）。"""
    mode = modes.for_run(modes.NOTE, has_profile=False, polish=False)
    mode = Mode(**{**mode.__dict__, "groups": groups})
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n", note_title="t"))
    st.content = content
    st.fresh = content
    st.facts = list(facts)
    st.before = before
    st.after = after
    st.bag["content_at_start"] = ""
    return st


# =============================================== ② 7 处静默 fix 各配一句措辞 ===

def test_2_那7处一处不落地都说得出自己改了什么():
    """**「逐个数过来」得真的数**：AST 静态扫 `app/harness/checks/**`，
    12 处带 `fix=` 的 `Verdict` **处处都得有非空 `fix_note` 字面量**。

    跟 `tests/test_p26.py::test_3_仓里每一处fix_note都得是数出来的` 不是一条：
    那条数的是**有没有这个关键字**，这条查的是**给的值不是空串**
    （`fix_note=""` 能骗过前者，而它跟没填一模一样——`_fix_events` 对空串直接 return []）。

    量程：把任意一处的 `fix_note=` 删掉，或者改成 `fix_note=""`，这条红。
    """
    root = pathlib.Path(__file__).resolve().parents[1] / "app/harness/checks"
    sites, empty = [], []
    for f in sorted(root.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Call)
                        and getattr(node.func, "id", "") == "Verdict"):
                    continue
                kw = {k.arg: k.value for k in node.keywords}
                if "fix" not in kw:
                    continue
                sites.append((f.name, fn.name, node.lineno))
                v = kw.get("fix_note")
                if v is None:
                    empty.append((f.name, fn.name, node.lineno, "没有这个关键字"))
                elif isinstance(v, ast.Constant) and not str(v.value).strip():
                    empty.append((f.name, fn.name, node.lineno, "给的是空串"))
    assert len(sites) == 12, f"带 fix 的 Verdict 变成 {len(sites)} 处了：{sites}"
    assert empty == [], f"这几处动了正文却说不出改了什么：{empty}"
    # P59 ② 之前这 7 处是静默的——名单钉在这儿，免得哪天又悄悄退回去
    assert {(a, b) for a, b, _l in sites} >= {
        ("charts.py", "charts_from_tools"), ("charts.py", "chart_restates_list"),
        ("grounding.py", "citations_exist"), ("language.py", "no_junk_tail"),
        ("language.py", "no_foreign_script"), ("structure.py", "heading_fits"),
        ("structure.py", "tail_clashes"),
    }


def test_2_没授权的手写图_说了删掉几张():
    """素材得真的过得了门槛：`groups` 里没有 `chart` 才走这一支。"""
    block = "```mermaid\nxychart-beta\n  x-axis [a, b]\n  bar [1, 2]\n```"
    st = _st("先写一段话。\n\n" + block, groups=("memory",))
    v = C.charts_from_tools(st)
    assert v is not None and v.fix is not None
    assert "mermaid" not in v.fix(st.content), "fix 没真把图摘掉，下面测的就不是这一支"
    assert v.fix_note and "删掉了" in v.fix_note and "1 张" in v.fix_note, v.fix_note


def test_2_编出来的编号_说了摘掉哪几个():
    """`citations_exist` 主支（`dangling_citations` 那一档）。同一个函数的
    `_truncated_verdict` 早就有 `fix_note` 了，这一条是把另一条出口补齐。"""
    st = _st("这一句挂了一个编出来的编号 [terrence-9999-1F1]。",
             facts=("[terrence-2046-12F1] EVT 准备 4 台主机",))
    v = G.citations_exist(st)
    assert v is not None and v.fix is not None
    assert "[terrence-9999-1F1]" not in v.fix(st.content)
    assert v.fix_note and "摘掉了" in v.fix_note
    assert "terrence-9999-1F1" in v.fix_note, "得说出摘的是哪个，用户要能回正文里核"


def test_2_段末垃圾_说了删几段_但不许把那句话抄进措辞里():
    """**这一条的负向断言是它自己那一半**（理由写在 `language.py` 那处注释里）：
    `fix_note` 的读者之一是**下一轮写作的 prompt**，把刚摘掉的垃圾词抄回去，
    等于拿这条判据刚扔掉的东西去喂下一轮。

    量程：把 `fix_note` 改成带 `'、'.join(tails[:3])` 的写法，这条红。
    """
    junk = L.JUNK_WORDS[0]
    st = _st(f"这一段在说正经事，讲完了。{junk}")
    v = L.no_junk_tail(st)
    assert v is not None and v.fix is not None, "素材没过门槛，下面测的不是这一支"
    assert junk not in v.fix(st.content), "fix 没真摘掉"
    assert v.fix_note and "删掉了" in v.fix_note
    assert junk not in v.fix_note, f"垃圾词被抄进了给下一轮的措辞里：{v.fix_note}"
    assert junk in v.message, "`message` 那一份照旧抄——它的读者是打分器，不是写作"


def test_2_乱码字符_说了删几处_而且抄了出来():
    """跟上面那条相反：这一处**要**抄。摘掉的是别的书写系统的字符，
    抄回 prompt 带不回什么脏东西，而用户得看得出删的是哪几个字。"""
    st = _st("这一段是中文，后面混进来 મંત્રી 这几个字。")
    v = L.no_foreign_script(st)
    assert v is not None and v.fix is not None
    assert "મંત્રી" not in v.fix(st.content)
    assert v.fix_note and "删掉了" in v.fix_note and "મંત્રી" in v.fix_note


def test_2_标题下沉_说了下沉几级_而且那个数跟真改的一致():
    """**说的话和做的事读同一个数**：`fix_note` 里的级数来自 `_sink_delta`，
    `_sink_headings` 也读它。量程：把 `_sink_delta` 的 `needed` 改掉，
    这条红在「说 N 级、真改了 M 级」上，而不是只红在措辞里。"""
    before = "## 上面那个小节\n\n正文。"
    st = _st("# 我自己写的标题\n\n一段话。", before=before)
    v = S.heading_fits(st)
    assert v is not None and v.fix is not None
    fixed = v.fix(st.content)
    assert fixed.startswith("### "), fixed          # h1 → h3，下沉 2 级
    assert v.fix_note and "下沉了 2 级" in v.fix_note, v.fix_note
    # 真改了几级：把 fix 前后最浅的那个标题的井号数一减
    depth_before = min(len(h) for h in re.findall(r"^(#{1,6})\s", st.content, re.M))
    depth_after = min(len(h) for h in re.findall(r"^(#{1,6})\s", fixed, re.M))
    assert f"下沉了 {depth_after - depth_before} 级" in v.fix_note


def test_2_收尾小节_说了删的是整节不是一行标题():
    """这一处最该说清的是「删的是整节」——`_drop_tail_sections` 连标题底下的正文
    一起删，不说的话用户只会看见一段话凭空少了。"""
    st = _st("正文一段。\n\n## 下一步\n\n我自己写的收尾。",
             after="## Next steps\n\n笔记本来就有的收尾。")
    v = S.tail_clashes(st)
    assert v is not None and v.fix is not None
    fixed = v.fix(st.content)
    assert "我自己写的收尾" not in fixed and "下一步" not in fixed, "删的不是整节"
    assert v.fix_note and "整节删掉了" in v.fix_note and "下一步" in v.fix_note


# ====================================== ③ truncated_citations 的命名空间 ===

def test_3_命名空间光靠正文那一半就够得着():
    """P58 ⑤ 那个问题的答案：**本来就算了**。

    `tests/test_p55.py::test_2_宁可窄_这几种一条都不许报` 钉的是反面
    （两边都空 → 一个都不报）。正面这一半没人钉，而它正是 P58 ⑤ 要问的东西：
    **材料一条都没有**（`facts=[]`，假模型那种轮子）时，只要正文里有一个合法编号，
    命名空间就成立，残骸照报。

    量程：把 `ns` 那行里的 `id_prefixes(valid)` 去掉（只留材料那一半），这条红。
    """
    text = "这一句挂着合法编号 [terrence-1833-8F6]，那一句挂着残骸 [terrence-8F6]。"
    assert cit.truncated_citations(text, [], lambda _f: False) == ["terrence-8F6"]
    # 反面各钉一条，免得上面那条靠「什么都报」蒙过去
    assert cit.truncated_citations(
        "整篇一个合法编号都没有，只有 [terrence-8F6]。", [], lambda _f: False) == []
    assert cit.truncated_citations(text, [], lambda _f: True) == [], "查得到就是真的"


# ================================== ④ STUCK_ROUNDS 放行支（摆出来了，没改） ===

def test_4_卡死放行那一支今天确实不写check_released():
    """**把「今天是什么样」钉住**，免得下一批又从零复现一次（P59 ④ 摆过了，
    局面在 `<scratch>/p59/stuck9.py`：真 `loop.run` + 假打分器，
    第 3 轮 `streak = 3 > STUCK_ROUNDS` 走卡死放行、打分器回 `complete`
    → 今天停机是 `'complete'`，补上那一行就是 `'check_stuck'`）。

    这条查的是源码那一支：`streak > STUCK_ROUNDS` 那个分支体里**没有**
    `check_released`，而 `advisory` / `judge_floor` 两支里**有**。
    量程：给那一支加上 `st.bag["check_released"] = True`，这条红——
    **那正是它该红的时候**：行为变了就得有人来改这条闸和上面那段 docstring。
    """
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "app/harness/middleware/checks.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "before_judge")

    def _writes_released(node) -> bool:
        return any(
            isinstance(x, ast.Subscript) and getattr(x.value, "attr", "") == "bag"
            and isinstance(x.slice, ast.Constant) and x.slice.value == "check_released"
            for n2 in ast.walk(node) if isinstance(n2, ast.Assign)
            for x in n2.targets)

    branches = {}
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        t = node.test
        if isinstance(t, ast.Compare) and getattr(t.left, "id", "") == "streak":
            branches["stuck"] = _writes_released(node)
        elif isinstance(t, ast.Attribute) and t.attr == "advisory":
            branches["advisory"] = _writes_released(node)
        elif isinstance(t, ast.Compare) and getattr(t.left, "id", "") == "sc_streak":
            branches["judge_floor"] = _writes_released(node)
    assert set(branches) == {"stuck", "advisory", "judge_floor"}, branches
    assert branches["advisory"] is True
    assert branches["judge_floor"] is True
    assert branches["stuck"] is False, (
        "`STUCK_ROUNDS` 卡死放行那一支开始写 `check_released` 了——"
        "行为变了：这条闸、`Checks.after_judge` 的 docstring 和台账 P59 ④ 那一节"
        "得一起改，别只把这行断言翻过来。")


def test_4_有判据但不停check_stuck的模式有6个():
    """P59 ④ 不加那一行的第二条理由，**是个数出来的数**（不是「我觉得 block 模式没有」）。

    在这 6 个模式上把 `complete` 压回 `continue` 之后没有任何一条规则接得住，
    那一跑会一路跑到 `max_rounds`。

    量程：给任意一个 block 模式的 `stop_when` 加上 `check_stuck`，这条红。
    """
    have_checks, no_stuck = [], []
    for name in dir(modes):
        m = getattr(modes, name)
        if not isinstance(m, Mode) or not m.checks:
            continue
        have_checks.append(name)
        if "check_stuck" not in [getattr(f, "__name__", "") for f in m.stop_when]:
            no_stuck.append(name)
    assert len(have_checks) == 8, have_checks
    assert sorted(no_stuck) == ["ANALYSIS", "CHART", "CUSTOM", "EDA",
                                "PROMPT", "TABLE"], no_stuck
