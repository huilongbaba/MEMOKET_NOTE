"""Chart checks.

The design line these enforce: **the model decides what to draw, code
produces the numbers and the mermaid**. Left to itself the model invents
averages and writes mermaid that doesn't render -- both observed.
"""

from __future__ import annotations

from . import blockcheck
from ..state import State
from ..types import Verdict
from . import pick_dimension


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
        pick_dimension(st, "has_charts", "chart_validity"),
        "This round did not actually draw anything -- it described charts in "
        f"prose: {'; '.join(hits)}. Call chart_column / render_chart / "
        "chart_from_text and paste the ```mermaid block they return verbatim; "
        "that code is verified to render. Also, mermaid has no scatter plot: "
        "express a two-column relationship as a correlation coefficient, or "
        "as two series on a bar/line chart.",
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
        pick_dimension(st, "has_charts", "chart_validity"),
        f"{len(bad)} mermaid chart(s) here were not produced by a tool "
        f"({'; '.join(bad)}) -- they were hand-written to imitate tool output. "
        "Hand-written mermaid is unverified; syntax that fails to render "
        "(a y-axis range, say) turns the whole chart into an error. You decide "
        "what to draw; **the code must be exactly what the tool returned**. "
        "If a tool didn't draw what you wanted, call it again -- don't patch "
        "the output by hand.",
    )
