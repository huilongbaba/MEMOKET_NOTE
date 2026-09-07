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

# 这一维的判据改过一次，原因值得记下来。
#
# 原来写的是「同一个结论被换一种说法讲了不止一次 = 不足」，结果它把**结尾
# 重申核心结论**这种正常写法也当缺陷扣分。九批 2160 次实测，这一维稳在 1.3
# 左右下不来，判词永远是同一句「X 的结论在多个段落中反复出现」；而同一批
# 产出里段落两两最高相似度只有 **0.29**——一处字面重复都没有，通读下来结构
# 是完整的（引子→原因→方法→操作→价值）。**是判据在罚正常写法，不是文章差。**
#
# 所以把两件事分开：小节之间主题撞车（真缺陷，机械查重看不见，危害最大）
# 保留；开头点题、结尾收束时重申一次核心结论，明确算达标。
#
# 放宽判据有"为了刷分而降标准"的风险，这里的兜底是：真正的字面重复由确定性
# 手段拦（find_repeats 的 dup_hints、插入前的 drop_already_written），不依赖
# 这一维；这一维只负责它们看不见的语义撞车。
_NON_REPETITION = Dimension(
    "non_repetition",
    "**重点看小节之间有没有主题撞车**：两节标题不同、措辞也完全不同，但讲的"
    "是同一个主题（《订阅制的具体设计》与《订阅分层与用量计费的落地细节》），"
    "后一节只是把前一节展开重说——这算不足，而且是最难发现、危害最大的一种"
    "重复，机械查重查不出来，只能靠通读小节标题和各节实际覆盖的内容来判断。"
    "同一组事实、同一组边界条件在正文里被重复论证两遍，也算不足。"
    "\n**但下面这些是正常写法，不要扣分**：开头点题、结尾收束时重申一次核心"
    "结论（只要没有借机重新论证一遍）；同一个概念在不同小节里被当作前提引用；"
    "总述之后分述展开。判断标准是「这一段有没有推进」，不是「这个说法出现过"
    "几次」——一篇有引子、主体、收尾的文章，核心结论本来就会出现在两三处。"
    "\n达标：每一节都在推进，没有哪一节只是把另一节重说一遍。",
)

_FACTUAL_GROUNDING = Dimension(
    "factual_grounding",
    "只看「用到的地方对不对」，不看「用了多少」——"
    "达标：正文里凡是依赖知识库事实的陈述都跟事实一致，没有跟事实矛盾的"
    "说法，也没有编造知识库里根本没有的具体人名、日期、数字；"
    "不足：正文里有跟知识库事实明显矛盾的陈述，或者写了具体的人名/日期/"
    "数字但知识库里查无此事。"
    "**明确不算不足的情况**：检索到的事实没有被全部用上。检索是按关键词"
    "近似匹配的，命中的事实里经常有跟当前这段内容根本不相关的（真实例子："
    "写「硬件续航」命中了「Speaker E 问3月31号能否有APP可以对外」），"
    "不用它们是对的，不是缺口。续写那一步的指令本来就是「不相关的事实"
    "可以不用，不要为了显得有依据硬编牵强的类比」，这里不能反过来因为"
    "「没用完」而扣分——那会逼着往正文里塞不相关的内容，或者干脆编出"
    "知识库里没有的细节来凑数（真实踩过：因为这条扣分，下一轮正文里"
    "「引入了大量未在知识库中出现的具体日期与人物」）。",
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
_MATERIAL_USE = Dimension(
    "material_use",
    "只在【知识库事实】块里**确实给了材料**时才判这一项，没给材料就算达标。"
    "达标：正文里能看出用了这些材料——具体的项目、数字、人、决定被写进了"
    "正文，而不只是抽象地提了一下这个话题；"
    "不足：给了材料却写成了任何人都能写的通用内容（成本要考虑哪些项、"
    "远程协作要注意什么这类教科书分类），一条具体材料都没落到正文里。"
    "**这一条比其他所有维度都重要**：这是用户自己的笔记，通用常识写得"
    "再干净、再不重复、再自洽，价值也是零。",
)

_COHERENCE = Dimension(
    "coherence",
    "整篇作为一个成品是否自洽，逐条对着查，任意一条中招就是不足："
    "(1) 有没有出现不止一个结尾——某一段已经在做总结收束，后面却又接着"
    "展开新内容，读者会以为文章已经结束。"
    "**```mermaid 图不算新开的内容，接在收束附近不构成第二个结尾**——"
    "图是把正文已有关系换一种形式呈现，不是新展开一块内容，不要因为"
    "结尾附近有张图就判为二次收束（这是实测误判过的情况）；"
    "(2) 标题层级是否统一——有没有二级标题和三级标题混着乱用、同一层级"
    "的内容用了不同级别的标题；"
    "(3) 编号是否连贯——小节序号有没有跳号、错序（比如 1、2、4、3）；"
    "(4) 前后体例是否一致——有没有前半部分是纯段落、后半部分突然全是"
    "带标题的小节这种像两篇文章拼起来的痕迹；"
    "(5) 有没有自我拆台——正文某处的表述跟这篇东西自己主张的立场相互"
    "矛盾（比如通篇在批判某种说法，某一段自己又说了这种话）。",
)


def note_dimensions(has_profile: bool, polish: bool = False) -> list[Dimension]:
    """note_harness.py：单篇笔记续写，有 spine（核心张力）/beats（结构
    节拍）可以对着打分。

    ``polish``：打磨模式**只修不写**，不许新增内容。这时候
    ``beat_coverage``（有没有把每条结构节拍都写出来）和 ``material_use``
    （有没有把检索到的材料写进正文）这两条都不适用——它们衡量的是"写了
    多少"，而打磨这一模式被明确禁止写。

    实测代价：一篇有重复标题的短笔记跑打磨，``beat_coverage`` 判 0（节拍
    确实没写），于是永远到不了 complete，跑满三轮撞 max_rounds，每轮还被
    "最弱是节拍覆盖"这条诊断推着去写它不许写的东西。**拿一个它无权改善的
    维度去打分，闭环就不可能收敛。**
    """
    dims = [
        Dimension(
            "spine_fidelity",
            "达标：正文紧扣核心张力（spine）展开；不足：正文偏离核心张力，"
            "散成流水账或者跟核心张力无关的罗列。",
        ),
        _NON_REPETITION,
        _FACTUAL_GROUNDING,
        _COHERENCE,
    ]
    if not polish:
        dims.insert(1, Dimension(
            "beat_coverage",
            "达标：每条结构节拍（beats）都有对应内容实质存在，不要求写到"
            "极致，只要求这个功能真的在正文里起作用；不足：有结构节拍完全"
            "没有对应内容。",
        ))
        dims.append(_MATERIAL_USE)
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
        _MATERIAL_USE,
        _COHERENCE,
    ]
    if has_profile:
        dims.append(_STYLE_FIT)
    return dims
