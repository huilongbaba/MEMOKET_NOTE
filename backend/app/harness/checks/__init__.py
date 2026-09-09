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

from .charts import charts_from_tools, no_fake_charts
from .grounding import (citations_hold, material_used, no_audit_voice,
                        no_placeholder)
from .pick import pick_dimension
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
