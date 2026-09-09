"""两个会自己动手改正文的判据。

`Verdict.fix` 是判据里唯一**会重写用户内容**的东西，而全仓只有两个：
``heading_fits`` 把标题层级压下去，``tail_clashes`` 删掉自己写的收尾小节。
跑覆盖率之前，这两个函数一行都没被测过——`middleware/checks.py` 里那条
fix 路径是被一个合成的 Verdict 覆盖的，产品里真正的两个 fix 从没执行过。

这里测的不只是「改成什么样」，还有 `checks.py` 整个原子性设计压着的那条
性质：**修完之后判据不能再触发**。修了却修不好，那段内容会被原样留下、
下一轮在一个被改过又依然错的东西上继续写（原型里撞出来的，纸上读三遍
设计都没发现）。
"""

from __future__ import annotations

import dataclasses

from app.harness.checks import structure
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import Dimension, Mode


def _st(before: str = "", content: str = "", after: str = "") -> State:
    mode = Mode(key="t", label="t", skill_scope="test_scope",
                dims=(Dimension("fits_context", "..."),))
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n"))
    st.before, st.content, st.after = before, content, after
    return st


def _fix_until_clean(check, st) -> State:
    """按 middleware/checks.py 的做法应用一次 fix，并要求判据不再触发。"""
    verdict = check(st)
    assert verdict is not None, "这段素材本来就没触发判据，测的不是 fix"
    assert verdict.fix is not None, "这条判据没有 fix"
    probe = dataclasses.replace(st, content=verdict.fix(st.content))
    assert check(probe) is None, (
        "fix 跑完判据还在触发——checks.py 会因此把这次修改整个丢掉，"
        f"内容原样留下。修出来的是：\n{probe.content}")
    return probe


def test_标题被压到上文标题的下一级():
    st = _st(before="# 一级标题\n## 二级标题\n正文\n",
             content="## 我自己起的标题\n内容\n### 更深一层\n内容\n")
    fixed = _fix_until_clean(structure.heading_fits, st)
    # 上文最近的标题是 ##，所以我写的最浅那个要变成 ###，深的跟着同幅下沉
    assert fixed.content.startswith("### 我自己起的标题")
    assert "#### 更深一层" in fixed.content


def test_压标题只动井号不动别的():
    st = _st(before="## 上文\n", content="## 标题\n正文里有 # 号不能动\n")
    fixed = _fix_until_clean(structure.heading_fits, st)
    assert "正文里有 # 号不能动" in fixed.content


def test_已经够深的标题不动():
    """delta <= 0 的分支：我的标题本来就比上文深，什么都不该改。"""
    st = _st(before="# 上文\n", content="### 已经很深了\n内容\n")
    assert structure.heading_fits(st) is None


def test_自己写的收尾小节被删掉():
    st = _st(content="## 正文一节\n内容\n\n## Summary\n我自己的收尾\n",
             after="## Next steps\n下面已经有收尾了\n")
    fixed = _fix_until_clean(structure.tail_clashes, st)
    assert "Summary" not in fixed.content
    assert "## 正文一节" in fixed.content and "内容" in fixed.content


def test_下面没有收尾小节时不算冲突():
    st = _st(content="## Summary\n收个尾\n", after="## 别的小节\n内容\n")
    assert structure.tail_clashes(st) is None


def test_没有下文时收尾冲突这条不判():
    """块生成之外的场景没有 ``after``，这条判据整个不适用。"""
    assert structure.tail_clashes(_st(content="## Summary\n收个尾\n")) is None


def test_大纲判据只在上文真是大纲时才管():
    普通正文 = "# 一节\n这里写满了内容，足够长，不像是等着被填的大纲。\n"
    assert structure.outline_intact(_st(before=普通正文, content="随便写点")) is None


def test_大纲层级没被压平就放行():
    大纲 = "## 一\n\n## 二\n\n## 三\n\n## 四\n\n"
    st = _st(before=大纲, content=大纲 + "在标题下面补的内容\n")
    assert structure.outline_intact(st) is None


def test_块里没有标题时压标题是空操作():
    from app.harness.checks.structure import _sink_headings

    assert _sink_headings("## 上文\n", "一段没有标题的正文\n") == "一段没有标题的正文\n"
