"""The scoring engine: one LLM call, a fixed JSON contract, a small amount
of programmatic post-processing. This is the package's answer to "there's
no execution oracle for writing" -- see README."""

from __future__ import annotations

import json

from ..types import Dimension, DimensionScore, DupHint, Evaluation, LLMClient

DEFAULT_SYSTEM_PROMPT = """You are a rigorous editor. You will be given a \
piece of writing and a fixed set of dimensions to score it against. Score \
each dimension independently:

0 = insufficient: this dimension's bar is clearly not met
1 = partial: some progress, but not there yet
2 = meets the bar: no further work needed on this dimension

Then decide, across all dimensions together, whether the piece is:
- "blocked": stuck for a reason that another round of writing or editing \
cannot fix on its own (for example, the content written so far \
structurally contradicts the stated goal, or two required things are \
mutually exclusive as currently written) -- this is different from "not \
finished yet", and should be rare; only use it when more rounds genuinely \
would not help
- otherwise: not blocked

Do not soften a low score because the piece is long or because a lot of \
effort clearly went into it -- score strictly against each dimension's own \
description of what "meets the bar" means.

Return JSON only, no other text:
{
  "scores": {"<dimension name>": {"level": 0|1|2, "note": "one sentence"}, ...},
  "blocked": true|false,
  "blocked_reason": "one sentence, only if blocked is true, else empty string"
}"""


class ScoreParseError(Exception):
    """**这一轮没打上分**，跟「打了分，分很低」是两回事。

    第 766 轮之前，`_extract_json` 返回 None 时 `raw_scores` 就是个空 dict，
    于是每一个维度都拿到 `level=0`——而那份"全 0 分"跟模型真的判「每一项都
    远不达标」在下游**一个字节都分不出来**：

    * `middleware/repair.py`：`non_repetition` / `coherence` / `topic_fidelity`
      三维全 0 → 下一轮 `cleanup_only`，`produce()` 直接返回不写字。
      一次解析失败就白扔一轮。
    * `BestOf` 的 `rank()`：全 0 分是 `(0, 0.0)`，比「没打上分」的
      `(-1, -1.0)` **高**——一次解析失败会把这一轮排到真正没判过的轮次前面。
    * `_regressed`：接近合格的时候遇上一次解析失败就读成「质量跌到谷底」。
    * `database/kb/extract_judge.py` 的汇总：全 0 分会被算进 `below_bar`
      的均值里，**把一次接口抖动记成抽取质量差**。

    而 `loop._score()` 只挡得住**抛异常**那条路（超时、连接断）——这条静默
    路径从它底下穿过去了。所以解析失败现在也走抛异常：两条路合并成一条，
    上层拿到的都是 `st.ev is None`＝「这一轮没判」，`rank()` 自然垫底、
    `Repair` 的循环开头 `if not st.ev: break` 自然跳过。

    **判据窄一条**：只有「一个维度都没解析出可用的 level」才算解析失败。
    模型正常返回、真的给某一维打了 0 分，那是判断结果，照旧当分数用。
    """


def _extract_json(text: str) -> dict | None:
    """Minimal JSON-object extraction: strips ``` fences, then finds the
    first balanced {...}. Kept deliberately small and dependency-free --
    this package doesn't try to recover from every malformed-output shape a
    model might produce, callers needing that should validate/retry around
    evaluate() themselves."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _render_dup_hints(dup_hints: tuple[DupHint, ...]) -> str:
    if not dup_hints:
        return ""
    lines = [
        f"- ({hint.similarity:.0%} similar) “{hint.a[:80]}…” vs “{hint.b[:80]}…”"
        for hint in dup_hints
    ]
    return "Mechanically detected candidate near-duplicate passages (verify, don't assume):\n" + "\n".join(lines)


def _render_context(context: dict[str, str] | None) -> list[str]:
    return [f"[{title}]\n{text}" for title, text in (context or {}).items() if text]


# 二元维度那一行前面的话。**两侧一起管**：这里告诉模型别给中间档，
# `evaluate()` 里再把漏网的 1 压成 0——只靠 prompt 说一句是「靠自报保证的性质」，
# 而那种性质迟早会被报错一次。
_BINARY_PREFIX = "【只判满足 / 不满足：满足给 2，不满足给 0，**不要给 1**】"


def _guidance(dim: Dimension) -> str:
    return f"{_BINARY_PREFIX}{dim.guidance}" if dim.binary else dim.guidance


def _build_prompt(
    content: str,
    dimensions: list[Dimension],
    context: dict[str, str] | None,
    dup_hints: tuple[DupHint, ...],
    tail_context: dict[str, str] | None = None,
) -> str:
    parts = _render_context(context)
    dim_lines = "\n".join(f"- {d.name}: {_guidance(d)}" for d in dimensions)
    parts.append(f"[Dimensions to score]\n{dim_lines}")
    parts.append(f"[Content]\n{content}")
    # **`tail_context` 是「每一轮都在变的那几块」，排在 `[Content]` 之后。**
    # 规则跟下面 dup_hints 那一条是同一条，只是晚了十四批才被发现还有第二处：
    # 材料块（`score_context.MATERIAL_KEY`）每轮都在长（批 15 真跑实测
    # `facts_new` 每轮 41~46 条），而它原来是 `context` 的一项、排在正文
    # **之前**——于是断点落在正文前，**judge 那一路的缓存命中率恒为 0.0%**
    # （批 15：38 次真跑 / 24 次 judge 调用，命中 0 token；同一次跑里检索规划
    # 60.3%、续写 30.7%）。
    #
    # 顺手纠正 `with_material` 原来那句注释：它写着材料排在 context 末尾
    # 「也就是紧挨着 `[Content]`」——**并不是**，中间隔着整块
    # `[Dimensions to score]`（八组维度里最长的那组 1000+ 字）。挪到这里之后
    # 材料才第一次真的跟正文相邻。
    parts += _render_context(tail_context)
    # **dup_hints 排在 content 之后，不是之前。** 它每一轮都变（这一轮查出来的
    # 候选对），而 content 在不被修订改动时是追加式的。放在前面的时候，
    # 前缀缓存的断点落在大约 1300–2000 token 处，**正文那几千 token 从来
    # 没有被缓存过一次**；放到后面，前缀变成 system + context + dimensions +
    # content，那才是这段 prompt 里最大的一块（docs/harness-context-engineering.md §2②）。
    # 语义上也说得通：它本来就是"辅助证据，自己核对别假设"。
    dup_block = _render_dup_hints(dup_hints)
    if dup_block:
        parts.append(dup_block)
    return "\n\n".join(parts)


async def evaluate(
    llm: LLMClient,
    *,
    content: str,
    dimensions: list[Dimension],
    context: dict[str, str] | None = None,
    dup_hints: list[DupHint] = (),
    tail_context: dict[str, str] | None = None,
    system_prompt: str | None = None,
    max_tokens: int = 900,
    temperature: float = 0.1,
) -> Evaluation:
    """Score ``content`` against ``dimensions`` in one LLM call, return the
    per-dimension scores plus an overall continue/complete/blocked verdict.

    ``complete`` is decided programmatically (every dimension at level 2) --
    the model can't be trusted to reliably self-report "I'm done" (that's
    the whole reason this package exists), so it only has to make the
    narrower, harder-to-fake judgment of "is this specific dimension at
    level 2", not "is everything finished". ``blocked`` is the one signal
    that genuinely needs the model's own judgment (a low score alone can't
    tell you whether another round would help), so it's asked for directly
    and trusted as reported.

    Raises ``ScoreParseError`` when the reply yields no usable level for any
    dimension -- "this round was not scored" must stay distinguishable from
    "this round scored zero everywhere". Both callers already treat a raised
    exception as "no judgement this round" (``loop._score`` returns ``None``,
    ``extract_judge.judge_meeting`` drops the meeting from the aggregate).
    """
    if not dimensions:
        raise ValueError("evaluate() needs at least one dimension")

    prompt = _build_prompt(content, dimensions, context, tuple(dup_hints),
                           tail_context)
    raw = await llm.complete(
        [
            {"role": "system", "content": system_prompt or DEFAULT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    parsed = _extract_json(raw) or {}
    raw_scores = parsed.get("scores") if isinstance(parsed.get("scores"), dict) else {}

    scores: dict[str, DimensionScore] = {}
    judged = 0                   # 真正解析出 level 的维度个数，见 ScoreParseError
    for dim in dimensions:
        entry = raw_scores.get(dim.name)
        level, note = 0, ""
        if isinstance(entry, dict):
            level_raw = entry.get("level")
            if isinstance(level_raw, (int, float)) and int(level_raw) in (0, 1, 2):
                level = int(level_raw)
                judged += 1
                # **二元维度上「一半」算没做到**（计划 6.1 / [IND] §6②）。
                # 往上圆会让这一维永远达标（判词里写着二元，模型还是给了 1，
                # 说明它自己也觉得没完全做到）；往下圆最多多跑一轮，而一轮的
                # 代价是有限的、可见的。checklist 条目本来就是「用户明确要求
                # 的一件事」，做到一半就是没做到。
                if dim.binary and level == 1:
                    level = 0
            note = str(entry.get("note") or "")
        scores[dim.name] = DimensionScore(level=level, note=note)

    blocked = bool(parsed.get("blocked"))
    blocked_reason = str(parsed.get("blocked_reason") or "") or None

    # **一个维度都没判上 = 这一轮没打上分**（`ScoreParseError` 的 docstring 写了
    # 下游四处把"全 0 分"当真分数用的地方）。
    #
    # `blocked` 是唯一的例外，而且是**有意留窄的**：`blocked` 为真说明 JSON
    # 本身解析成功了（解析不出来时 `parsed` 是空 dict，`blocked` 只能是 False），
    # 模型是明确说了「再跑也没用」——那是一份真裁决，不是接口抖动。它会让
    # `_blocked` 当轮停机，全 0 分也不会流进下一轮的 `Repair` / `BestOf`。
    # 把它一起抛掉是拿真信号换整齐，误伤比漏报贵。
    if judged == 0 and not blocked:
        raise ScoreParseError(
            f"打分返回体里一个维度都没解析出 level（维度 {len(dimensions)} 个，"
            f"返回体 {len(raw)} 字）")

    if blocked:
        return Evaluation(scores=scores, status="blocked", blocked_reason=blocked_reason)

    weakest_name, weakest_level = None, 3
    for dim in dimensions:
        level = scores[dim.name].level
        if level < weakest_level:
            weakest_name, weakest_level = dim.name, level

    if weakest_level >= 2:
        return Evaluation(scores=scores, status="complete")
    return Evaluation(scores=scores, status="continue", weakest=weakest_name)


# ------------------------------------------------ 打分器点名的「原文」正文里有没有（P11 #5）
#
# 实拍四次（P5 da080 第 1 轮「末尾出现“अ”这一明显残留字符」；P8 da080 第 3 / 4 / 6 轮「من」「م...」
# 「մե...」）：打分器的判词点名一个正文里**根本没有**的字符串，然后据此扣分。`no_foreign_script`
# 只认正文里真有的字（那是另一条线）；这里做的是**判据命中但正文没有 → 那一维不计入分数**。
# 判法是代码：判词里 「」『』“” "" 引起来的每一段，去掉空白 / markdown 记号 / 标点之后，
# 在「正文 + 开跑前正文 + 材料 + 打分上下文」里找不到 → 这一维的分数丢掉，`evaluate` 事件记
# `judge_hallucinated`。**只认引号里的**：判词里不带引号的复述不算。

import re as _re

_QUOTED = _re.compile(r"[「『“\"‘]([^」』”\"’]{1,120})[」』”\"’]")
_STRIP = _re.compile(r"[\s*_`#>~\[\]，。、；：！？,.;:!?()（）【】\-—–…·|]+")
_MEANINGFUL = _re.compile(r"[0-9A-Za-z-￿]")


def quoted_spans(note: str) -> list[str]:
    """判词里引号引起来的那几段（保序去重）。"""
    out: list[str] = []
    for m in _QUOTED.finditer(note or ""):
        q = m.group(1).strip()
        if q and q not in out:
            out.append(q)
    return out


def _norm(text: str) -> str:
    return _STRIP.sub("", (text or "")).lower()


def unfound_quotes(note: str, haystack: str) -> list[str]:
    """判词里引着、`haystack` 里却找不到的那几段。「…」/「...」切开各查一段；
    切完没有一个字母 / 数字 / 汉字的片段（纯标点）不算。"""
    hay = _norm(haystack)
    bad: list[str] = []
    for q in quoted_spans(note):
        for piece in _re.split(r"…|\.{3,}", q):
            np = _norm(piece)
            if not _MEANINGFUL.search(np):
                continue
            if np not in hay:
                bad.append(piece.strip() or q)
                break
    return bad


def drop_hallucinated(ev: Evaluation, haystack: str) -> tuple[Evaluation | None, list[dict]]:
    """把「判词点名的原文正文里没有」的那几维从分数里拿掉。

    返回 ``(新的 Evaluation 或 None, [{dimension, quotes, note}])``。一维都不剩 → None
    （跟 `loop._score` 的「这一轮没打上分」是同一种表示法）；`blocked` 照旧带过去——那是
    模型对整篇的裁决，不是对某一段的点名。状态按 `evaluate()` 同一条规则重算。
    """
    bad: list[dict] = []
    keep: dict[str, DimensionScore] = {}
    for dim, sc in ev.scores.items():
        missing = unfound_quotes(sc.note, haystack)
        if missing:
            bad.append({"dimension": dim, "quotes": missing[:3], "note": sc.note[:200]})
        else:
            keep[dim] = sc
    if not bad:
        return ev, []
    if not keep:
        return None, bad
    if ev.status == "blocked":
        return Evaluation(scores=keep, status="blocked", blocked_reason=ev.blocked_reason), bad
    weakest_name, weakest_level = None, 3
    for dim, sc in keep.items():
        if sc.level < weakest_level:
            weakest_name, weakest_level = dim, sc.level
    if weakest_level >= 2:
        return Evaluation(scores=keep, status="complete"), bad
    return Evaluation(scores=keep, status="continue", weakest=weakest_name), bad
