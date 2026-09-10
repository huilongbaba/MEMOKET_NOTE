"""Grounding checks: is the text actually standing on the material.

These three used to be **silent rewrites** -- ``scrub_meta_sentences`` simply
deleted the offending sentences and the user never knew. Two harnesses did
that, a third reported the problem back and let the model fix it. Same defect,
opposite handling, decided by which was written first.

They are checks now. The user sees why the round was rejected, and can
disagree; a deletion nobody was told about offers neither.
"""

from __future__ import annotations

from .citations import check_citations

from . import grounding_rules as grounding_check
from ..state import State
from ..types import Verdict
from .pick import pick_dimension


def no_placeholder(st: State) -> Verdict | None:
    """Text that promises content instead of containing it.

    "(details to be added later)" in a finished draft is worse than a shorter
    draft: it reads as done and isn't.
    """
    lines = grounding_check.placeholder_lines(st.content)
    if not lines:
        return None
    return Verdict(
        pick_dimension(st, "factual_grounding", "no_fabrication", "data_grounding"),
        "There are placeholders standing in for content: "
        + "; ".join(lines[:3])
        + ". Either write the thing, or leave it out -- a promise of content "
          "reads as finished and isn't.",
    )


def no_audit_voice(st: State) -> Verdict | None:
    """Prose about whether the evidence is sufficient, instead of prose about
    the subject.

    "It should be noted that the available records do not fully support..."
    is a sentence about the knowledge base, not about the user's project.
    """
    lines = grounding_check.audit_voice_lines(st.content)
    if not lines:
        return None
    return Verdict(
        pick_dimension(st, "style_fit", "coherence", "fits_context"),
        "Some sentences are about the evidence rather than about the subject: "
        + "; ".join(lines[:3])
        + ". If a fact isn't there, leave the claim out; don't narrate the gap.",
    )


def citations_hold(st: State) -> Verdict | None:
    """Every cited fact marker must correspond to material actually supplied.

    ``check_citations`` has existed, with tests, since the package was written
    -- and was never wired into anything. Wiring it is most of the value:
    citing a fact that wasn't in the input is a different and more serious
    failure than paraphrasing loosely, and until now nothing looked for it.
    """
    claimed = st.bag.get("claimed_sources") or []
    if not claimed or not st.facts:
        return None
    results = check_citations(list(claimed), st.facts)
    missing = [c.claimed for c in results if not c.verified]
    if not missing:
        return None
    return Verdict(
        pick_dimension(st, "factual_grounding", "no_fabrication", "data_grounding"),
        f"{len(missing)} cited source(s) don't match anything in the material "
        f"you were given ({'; '.join(m[:40] for m in missing[:2])}). Cite only "
        "what you actually retrieved.",
    )


def citations_exist(st: State) -> Verdict | None:
    """正文里 ``[事实 id]`` 形式的引用，每一个都得真的存在。

    跟 citations_hold 的区别：那条是模糊文本匹配（模型自报），这条是确定性的
    ——id 要么在这轮的材料里、要么在知识库里查得到，否则就是编的。可自动修：
    摘掉那个编造的 ``[id]``，正文其他部分不动。
    """
    from ...database.kite.kite_memory import UserMemory
    from .citations import cited_ids, dangling_citations, strip_citations
    if not cited_ids(st.content):
        return None
    user = getattr(st.ctx, "user", "")
    mem = UserMemory(user) if user else None
    exists = (lambda fid: mem.fact_by_id(fid) is not None) if mem else (lambda _fid: False)
    bad = dangling_citations(st.content, st.facts, exists)
    if not bad:
        return None
    return Verdict(
        pick_dimension(st, "factual_grounding", "no_fabrication", "data_grounding"),
        f"引用了 {len(bad)} 条不存在的事实（{', '.join(bad[:3])}）。只引用材料里列出的编号，"
        "不要自己编——一个像真的一样的引用比不引用更糟。",
        fix=lambda text: strip_citations(text, bad),
    )


def material_used(st: State) -> Verdict | None:
    """Facts were retrieved and none of them made it into the text.

    A deterministic backstop for a judgement the scorer gets wrong in one
    direction: it will happily rate ``material_use`` as met while the round
    used nothing. Whether a fact's characteristic terms appear in the text is
    countable, so it is counted -- same class of thing as the mechanical
    duplicate check.

    **Off in outline mode.** The user's own sections ("design", "market") may
    have nothing at all behind them in the knowledge base; forcing "you must
    use the material" leaves the model no move except to write "the available
    material cannot establish..." -- which is exactly where the audit-report
    voice came from. What that section needs is one line saying the record is
    missing, and then to move on.
    """
    if st.bag.get("outline_mode"):
        return None
    gap = grounding_check.grounding_gap(st.content, st.facts)
    if not gap:
        return None
    return Verdict(pick_dimension(st, "material_use", "factual_grounding"), gap)
