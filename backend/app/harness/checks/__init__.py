"""Deterministic checks: what code can decide, code decides.

This is not fastidiousness. The scorer and the thing being scored are the
same local model, so its blind spots line up exactly with the writer's. Real
examples it waved through:

* a block whose "charts" were sentences like ``[bar chart: clicks by
  channel ...]`` -- scored ``has_charts = 2``
* mermaid the model had hand-written by copying a tool's output and adding a
  y-axis range, which makes the chart fail to render -- scored as valid

Every check here is a pure function of ``State``. That makes them unit
testable against real failing output, and means a check can never be the
thing that breaks a run.
"""

from ..state import State


def pick_dimension(st: State, *candidates: str) -> str:
    """这条 check 该打翻哪一维——**按当前 Mode 实际有的那些维度挑**。

    以前是写死的，而一条 check 被多个 Mode 共用：``no_fake_charts`` 写死打
    ``has_charts``，在数据可视化模式下对（那个模式的维度就叫这个），在智能
    插图模式下就打了一个**这个模式根本没有的维度**——它那一维叫
    ``chart_validity``。24 个「check × mode」组合里有 8 个是这样。

    后果不大但很别扭：Evaluation 里会出现一个模型从来不会打的维度名，
    喂回下一轮的诊断也顶着一个模型没见过的标签。

    两个维度名不是命名不统一——``has_charts`` 判的是「图有没有信息量」，
    ``chart_validity`` 判的是「图是不是工具产出的」，是不同的轴。所以修法
    不是统一命名，是让 check 在候选里挑这个 Mode 认识的那个。

    一个都没匹配上就退回第一个候选（不炸），而 ``test_harness_modes`` 里
    有一条断言保证这种情况在配置阶段就被发现。
    """
    have = {d.name for d in st.mode.dims}
    return next((c for c in candidates if c in have), candidates[0])


from .charts import charts_from_tools, no_fake_charts
from .grounding import (citations_hold, material_used, no_audit_voice,
                        no_placeholder)
from .structure import heading_fits, outline_intact, tail_clashes

__all__ = [
    "pick_dimension",
    "charts_from_tools",
    "citations_hold",
    "heading_fits",
    "material_used",
    "no_audit_voice",
    "no_fake_charts",
    "no_placeholder",
    "outline_intact",
    "tail_clashes",
]
