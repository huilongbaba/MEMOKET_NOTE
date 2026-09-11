"""Chart checks.

The design line these enforce: **the model decides what to draw, code
produces the numbers and the mermaid**. Left to itself the model invents
averages and writes mermaid that doesn't render -- both observed.
"""

from __future__ import annotations

from . import blockcheck
from ..state import State
from ..types import Verdict
from .pick import pick_dimension


def no_fake_charts(st: State) -> Verdict | None:
    """Charts described in prose instead of drawn.

    Real output: ``[bar chart: clicks by channel  Kickstarter: 12700 ...]``
    and ``[scatter: impressions vs orders, n=6, r=0.9902]``. The second is
    worse -- mermaid has no scatter plot, so that chart could never exist.
    The scorer gave this ``has_charts = 2``.
    """
    hits = blockcheck.fake_charts(st.content)
    if not hits:
        return None
    return Verdict(
        pick_dimension(st, "has_charts", "chart_validity", "coherence"),
        f"这一轮没有真的画图，只是用文字描述了图：{'; '.join(hits)}。"
        "要画就调 chart_column / render_chart / chart_from_text，把它们返回的 ```mermaid 块"
        "原样贴进来——那段代码是验证过能渲染的。另外 mermaid 没有散点图：两列的关系"
        "写成相关系数，或者画成柱/折线图的两个系列。",
    )


def charts_from_tools(st: State) -> Verdict | None:
    """Mermaid that a tool did not produce.

    The model learned to route around ``no_fake_charts`` by hand-writing
    mermaid that mimics tool output -- the numbers were even correct, but the
    syntax was its own invention (``y-axis "impressions" 0 --> 260000``,
    a range ``render_chart`` never emits because getting it wrong turns the
    whole chart into an error message).

    So the test is not "does it look right" but **"is it byte-for-byte what a
    tool returned"**. Correct numbers don't make a chart render, and don't
    guarantee the next one won't quietly change a digit.
    """
    bad = blockcheck.unauthorized_charts(st.content, st.charts)
    if not bad:
        return None
    return Verdict(
        pick_dimension(st, "has_charts", "chart_validity", "coherence"),
        f"这里有 {len(bad)} 张 mermaid 图不是工具画的（{'; '.join(bad)}），是手写的、模仿工具"
        "输出。手写的 mermaid 没验证过，一处语法不对（比如 y 轴范围）整张图就变成一段"
        "报错。画什么由你定，**代码必须是工具原样返回的**；工具没画出你要的，就再调一次，"
        "别手改它的输出。",
    )
