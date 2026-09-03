"""Wires the domain-agnostic writer_harness package into this app: an
LLMClient adapter over app.llm, a RunHistoryStore backed by the
harness_runs sqlite table, and memoket-note's own rubric (spine/beats
vocabulary lives here, not in the package -- see writer_harness/README.md
"Design notes").
"""

from __future__ import annotations

from writer_harness import Dimension, RunRecord

from . import llm as _llm
from . import store


class AppLLMClient:
    """Implements writer_harness.LLMClient by forwarding to app.llm.complete()."""

    async def complete(self, messages: list[dict], **kwargs) -> str:
        return await _llm.complete(messages, **kwargs)


class SqliteRunHistoryStore:
    """Implements writer_harness.RunHistoryStore over app/store.py's
    harness_runs table."""

    def record(self, run: RunRecord) -> None:
        store.record_harness_run(
            run.key, run.status, run.rounds, run.final_scores, run.weak_dimensions)

    def recent(self, key: str, limit: int = 3) -> list[RunRecord]:
        return [
            RunRecord(
                key=row["key"], status=row["status"], rounds=row["rounds"],
                final_scores=row["final_scores"], weak_dimensions=row["weak_dimensions"],
                timestamp=row["timestamp"],
            )
            for row in store.recent_harness_runs(key, limit)
        ]


# 从现有 EDIT_SYSTEM/BEATS_COVERAGE_SYSTEM/MAGIC_TAP_SYSTEM 里已经写好的
# 原则提炼出来的 guidance 文案，不是新想的标准——这几条本来就是这些
# prompt 里一直在检查的东西，只是之前从没被结构化打分过。note_harness
# （单篇笔记，有 spine/beats）和 writing_plan（文件夹级分段，只有"这个
# 分段的主题"）适用的"主题贴合度"维度不一样，其余三条共用。

_NON_REPETITION = Dimension(
    "non_repetition",
    "达标：没有跨段落/跨轮次的重复论点或结论；不足：同一个结论、同一组"
    "边界条件被换一种说法讲了不止一次。",
)

_FACTUAL_GROUNDING = Dimension(
    "factual_grounding",
    "达标：正文里依赖知识库事实的地方跟检索到的事实一致，没有矛盾；"
    "不足：正文与知识库事实明显矛盾，或者明显可以用知识库事实补实却"
    "含糊带过。",
)

_STYLE_FIT = Dimension(
    "style_fit",
    "达标：语气、结构、用词贴合用户的个人偏好；不足：明显违背个人偏好"
    "（比如偏好简洁但正文冗长啰嗦）。",
)

# 这一条是人工读真实产出读出来的缺口，不是照着别处抄的：真实质量采样里
# 有两篇被四个维度全打 2 分、判定 complete，但人一眼就能看出问题——
# 一篇正文中间夹了一个完整的结尾（读者以为文章结束了，下面又开始展开），
# 一篇小节编号是 1、2、4、3，还有二级标题夹在一堆三级标题中间。原来的
# 四个维度没有任何一条在管"这篇东西作为一个整体是不是自洽"，所以这些
# 一眼可见的硬伤全部被判满分。guidance 写成明确的检查清单，泛泛说
# "检查结构"实测没用。
_COHERENCE = Dimension(
    "coherence",
    "整篇作为一个成品是否自洽，逐条对着查，任意一条中招就是不足："
    "(1) 有没有出现不止一个结尾——某一段已经在做总结收束，后面却又接着"
    "展开新内容，读者会以为文章已经结束；"
    "(2) 标题层级是否统一——有没有二级标题和三级标题混着乱用、同一层级"
    "的内容用了不同级别的标题；"
    "(3) 编号是否连贯——小节序号有没有跳号、错序（比如 1、2、4、3）；"
    "(4) 前后体例是否一致——有没有前半部分是纯段落、后半部分突然全是"
    "带标题的小节这种像两篇文章拼起来的痕迹；"
    "(5) 有没有自我拆台——正文某处的表述跟这篇东西自己主张的立场相互"
    "矛盾（比如通篇在批判某种说法，某一段自己又说了这种话）。",
)


def note_dimensions(has_profile: bool) -> list[Dimension]:
    """note_harness.py：单篇笔记续写，有 spine（核心张力）/beats（结构
    节拍）可以对着打分。"""
    dims = [
        Dimension(
            "spine_fidelity",
            "达标：正文紧扣核心张力（spine）展开；不足：正文偏离核心张力，"
            "散成流水账或者跟核心张力无关的罗列。",
        ),
        Dimension(
            "beat_coverage",
            "达标：每条结构节拍（beats）都有对应内容实质存在，不要求写到"
            "极致，只要求这个功能真的在正文里起作用；不足：有结构节拍完全"
            "没有对应内容。",
        ),
        _NON_REPETITION,
        _FACTUAL_GROUNDING,
        _COHERENCE,
    ]
    if has_profile:
        dims.append(_STYLE_FIT)
    return dims


def section_dimensions(has_profile: bool) -> list[Dimension]:
    """writing_plan.py：文件夹级分段续写，没有 spine/beats，只有这个
    分段自己的主题——对应的贴合度维度换成"是否紧扣分段主题、没有跑去写
    该由别的分段写的内容"。"""
    dims = [
        Dimension(
            "topic_fidelity",
            "达标：正文紧扣这个分段自己的主题展开，没有写到该由计划里其他"
            "分段覆盖的内容；不足：正文偏题，或者跟其他分段的主题明显"
            "重叠。",
        ),
        _NON_REPETITION,
        _FACTUAL_GROUNDING,
        _COHERENCE,
    ]
    if has_profile:
        dims.append(_STYLE_FIT)
    return dims
