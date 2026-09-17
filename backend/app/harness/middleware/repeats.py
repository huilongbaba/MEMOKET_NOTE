"""Mechanical near-duplicate detection, fed to scoring as evidence.

Asking the model to re-read the whole piece each round looking for repetition
doesn't work -- it stalls on that dimension for rounds at a time. Handing it
concrete candidate pairs does. The pairs are cheap (difflib, no model call)
and capped, so this is close to free.
"""

from __future__ import annotations


from difflib import SequenceMatcher
from ...editor import outline
from ..types import DupHint
from ..state import State


class Repeats:
    """Put candidate duplicate pairs in the bag for the scoring call.

    Writes to ``bag`` rather than calling anything: two different consumers
    want this (the revision prompt and the scoring call), and a middleware
    that reached into either would be coupling itself to both.
    """

    name = "repeats"
    # Twice per round, not once. Revise reads it before producing; the
    # scoring call reads it after. Between those two points ``st.content``
    # changes, and handing the scorer the pairs found in last round's text
    # would be reporting duplicates that may already be gone.
    hooks = ("before_produce", "before_judge")
    after: tuple[str, ...] = ()

    async def before_produce(self, st: State) -> None:
        st.bag["dup_hints"] = find_repeats(st.content)

    async def before_judge(self, st: State) -> None:
        st.bag["dup_hints"] = find_repeats(st.content)


# ---------------------------------------------------- 查重的实现 ---
#
# Deterministic, non-LLM near-duplicate detection.
#
# The mechanical-signal counterpart to evaluate(): cheap enough to run every
# round, and gives the model concrete candidate pairs to judge instead of
# asking it to re-read the whole document looking for repeats on its own --
# the same "rank, dedup, limit before injection" shape as a static analyzer's
# diagnostics, applied to prose instead of code.

DEFAULT_THRESHOLD = 0.6
DEFAULT_MAX_HINTS = 5
MIN_PARAGRAPH_LEN = 20  # shorter paragraphs (a lone heading, a short list
                        # item) produce noisy high-similarity matches that
                        # aren't meaningful repeats


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if len(p.strip()) >= MIN_PARAGRAPH_LEN]


# ——— 段内那一层 ————————————————————————————————————————————————
#
# **这个系统里每一处查重都是段落级的**，而真实产出里最严重的重复发生在
# **段落内部**：模型把整节重写了一遍，新旧逐句并排落在同一段里，
# 连空行都没有（实测一篇笔记 42.9% 的正文是段内重复）。
# `_paragraphs` 按 `\n\n` 切，`drop_already_written` 按段比，
# `repeated_lists` 按清单块——三条全都看不见它。
#
# 这不只是「读起来差」。文献里这叫 **self-reinforcement effect**：
# 重复一句话的概率随历史中已出现的重复次数而上升。我们每轮把不断变长的
# 正文自己喂回去，**留着的那处重复会让下一轮更可能重复**——所以查出来
# 不是锦上添花，是切断一个正反馈回路。
#
# 阈值 0.62 是量出来的（18 篇真产出、777 个段内句对）：
# 相似度分布是双峰的，**P75 只有 0.20、P90 就到 0.63**，中间一道很宽的谷；
# 0.60–0.72 区间里的句对人工核对**全是真重复**。取 0.62 命中 80 对、只落在
# 3 篇上，另外 15 篇一对都不命中——**误伤空间比担心的小**。
# （另一个旁证：人类语料里连续的句级重复只有 0.02%，真人几乎不重复句子。）
# 这个数跟 `editor/outline.drop_already_written` 的 0.62 是同一个，不是巧合：
# 同一种缺陷，只是切的粒度不同。
# **切句和「什么算一句」这两件事，实现在 `editor/outline.py`。**
# 那边有三层查重的公共部分：段落级（`drop_already_written`）、
# 插入前的句级（`drop_restated_sentences`）、和这里的段内句级。
# 同一种缺陷三个粒度，切法和阈值必须是同一套，分两份写必然分叉。
#
# 放在 editor 而不是这里，是分层测试（`tests/test_layering.py`）定的方向：
# `editor/outline` 在 PURE 名单里（只依赖标准库），harness 可以用它，
# 它不许反过来 import harness。
#
# 句子的边界是**句末标点或换行**。只按标点切会漏掉「重写的那一节换行另起」
# 的情况；只按换行切会把同一行里并排的两句当成一句。
# 这个缺口是突变验的时候露出来的：A、B 在同一自然段但分两行时，
# 按行切会把它们分到两"段"里各自比较（比不着），而段落级又把整段揉成一块
# （相似度被稀释）——**两边都漏**。
#
# **表格行、围栏代码、标题、纯引文编号行都不参与查重。** 它们按设计就长得
# 一样——一张表的两行除了第一格全同是正常的。标题和引文编号那两条是第 765
# 轮在 31 篇真实笔记上量出来的：标题 `## 获取首批 1,000 名 Beta 用户的回传
# 质量策略` 跟正文那句相似度 0.794，两行引文编号 `[terrence-1848-9F11] …` 和
# `[terrence-1564-0F3] …` 是 0.765——**编号不同、说的完全是两码事**。
# **判据宁可窄一点，误伤比漏报更贵。**
#
# **同一份清单的兄弟项也不参与**（第 765 轮补的，实测撞到的）：
# 一篇真实笔记的进度清单里六条 `- ✅ 已完成 **众筹前的…**` 彼此 0.62–0.70，
# 于是 `restated_ratio` 判了 9.4%（门槛 3%）——**判据对着一份完全正常的清单
# 报了缺陷**。见 `outline.template_rows`。
MIN_SENTENCE_LEN = outline.MIN_SENTENCE_LEN
_sentences = outline.sentences
_strip_fences = outline.strip_fences
_blocks = outline.sentence_blocks


def _judgeable(content: str, para: str) -> list[str]:
    """这一段里可以拿去判重的句子（模板清单行按整篇算，所以要 content）。"""
    template = outline.template_rows(content)
    return [s for s in _sentences(para) if s not in template]


def find_restated(content: str, *, threshold: float = DEFAULT_THRESHOLD,
                  max_hints: int = DEFAULT_MAX_HINTS) -> list[DupHint]:
    """同一段里被换个说法又说了一遍的句子。见上面那段注释。"""
    scored: list[DupHint] = []
    for para in _blocks(content):
        ss = _judgeable(content, para)
        for i, a in enumerate(ss):
            for b in ss[i + 1:]:
                ratio = SequenceMatcher(None, a, b).ratio()
                if ratio >= threshold:
                    scored.append(DupHint(a=a, b=b, similarity=ratio))
    scored.sort(key=lambda h: h.similarity, reverse=True)
    seen: set[str] = set()
    out: list[DupHint] = []
    for h in scored:
        if h.a in seen or h.b in seen:
            continue
        out.append(h)
        seen.add(h.a)
        seen.add(h.b)
        if len(out) >= max_hints:
            break
    return out


def restated_ratio(content: str, *, threshold: float = DEFAULT_THRESHOLD) -> float:
    """段内重复的字占正文的比例。判据用它，因为「有几对重复」说明不了严重程度
    ——一篇 3000 字里有两句重复，和一篇 1800 字里 782 字是重复，是两回事。"""
    total = dup = 0
    for para in _blocks(content):
        ss = _judgeable(content, para)
        seen: list[str] = []
        for s in ss:
            total += len(s)
            if any(SequenceMatcher(None, s, t).ratio() >= threshold for t in seen):
                dup += len(s)
            seen.append(s)
    return (dup / total) if total else 0.0


def find_repeats(
    content: str,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    max_hints: int = DEFAULT_MAX_HINTS,
) -> list[DupHint]:
    """Pairwise-compare paragraphs in ``content``, return the highest-
    similarity pairs above ``threshold``, ranked descending and capped at
    ``max_hints``. A paragraph appears in at most one returned pair (the
    one it matched best) so the same repeated passage doesn't crowd out
    every other hint."""
    paragraphs = _paragraphs(content)
    scored: list[DupHint] = []
    for i, a in enumerate(paragraphs):
        for b in paragraphs[i + 1 :]:
            ratio = SequenceMatcher(None, a, b).ratio()
            if ratio >= threshold:
                scored.append(DupHint(a=a, b=b, similarity=ratio))
    scored.sort(key=lambda hint: hint.similarity, reverse=True)

    seen: set[str] = set()
    deduped: list[DupHint] = []
    for hint in scored:
        if hint.a in seen or hint.b in seen:
            continue
        deduped.append(hint)
        seen.add(hint.a)
        seen.add(hint.b)
        if len(deduped) >= max_hints:
            break
    # **段内那一趟也要产出候选。** `Repair` 判断「内在质量差 → 下一轮只修不写」
    # 是对的，但修订那一步拿到的候选对来自这里；段内重复时这个列表是空的，
    # 于是 cleanup 轮无事可做 → `_no_progress` → **回路恰好在修复机制该起作用
    # 的那一刻停机**（docs/harness-mechanism-rethink.md §2）。
    if len(deduped) < max_hints:
        have = {h.a for h in deduped} | {h.b for h in deduped}
        for h in find_restated(content, threshold=threshold, max_hints=max_hints):
            if h.a in have or h.b in have:
                continue
            deduped.append(h)
            have.add(h.a)
            have.add(h.b)
            if len(deduped) >= max_hints:
                break
    return deduped
