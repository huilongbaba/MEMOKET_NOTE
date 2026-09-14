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
        "有占位句代替了内容："
        + "；".join(lines[:3])
        + "。要么把它写出来，要么删掉——一句「待补充」读起来像写完了，其实没有。",
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
        "有几句话在谈证据够不够，而不是在谈事情本身："
        + "；".join(lines[:3])
        + "。没有依据的说法就不写；不要旁白「材料不足以说明」。",
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
        f"有 {len(missing)} 条引用对不上给你的材料（{'; '.join(m[:40] for m in missing[:2])}）。"
        "只引用你真的查到的。",
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


# 这一轮写了这么多字还一条引用都没有，就不是"顺手补一句过渡"了
MIN_CITED_ROUND_CHARS = 300


def citations_present(st: State) -> Verdict | None:
    """手上有材料、这一轮写了整整一段，却一个 ``[事实编号]`` 都没有。

    第 593 轮真跑实证：一篇 1066 字的分段笔记零引用，而且写的是知识库里另一个项目的内容——
    整条链上没有一道判据拦得住它。`citations_exist` 只查「引用的 id 存不存在」，一个都没引
    时第一行就 ``return None``；`material_used` 数的是特征词，模型把材料改写进正文（不带编号）
    照样算用上了。**这个产品的承诺是每句判断都能点回它的依据**，零引用的产出等于通用 LLM 写的。

    只判**这一轮写的**（``st.fresh``），不判整篇：用户自己原来那些段落没有引用是正常的。
    大纲模式关掉，理由同 `material_used`——用户自己列的小节可能本来就没有材料。
    """
    if st.bag.get("outline_mode") or not st.facts:
        return None
    from .citations import cited_ids
    fresh = (st.fresh or "").strip()
    if len(fresh) < MIN_CITED_ROUND_CHARS or cited_ids(fresh):
        return None
    return Verdict(
        pick_dimension(st, "factual_grounding", "material_use", "no_fabrication"),
        f"这一轮写了 {len(fresh)} 字，手上有 {len(st.facts)} 条材料，正文里一个 [事实编号] 都没有。"
        "把真正用到的那几条的编号写在对应句子末尾——这篇笔记的价值在于每句判断都能点回它的依据；"
        "没有编号的判断读者无从核对，跟随便哪个模型写的没区别。编号只能从材料里抄，不要自己编。",
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
