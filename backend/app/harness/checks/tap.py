"""magic tap（单次续写）的判据：全是确定性的，零模型调用（计划 8.1）。

## 为什么这一步值得配判据

[EVAL] 问题四数过一次：**会产出文字的功能有 15 个，有 evaluator 的只有 8 个**。
剩下那一档里 `magic-tap` 是**用户直接看得见产出**的两个之一——点一下、几秒钟、
一段字直接落进正文，而在这之前**没有任何东西在事后看一眼它写成什么样**。

现有的两条不算体检：`fact_usage` 问的是「检索到的材料用上没有」，
`fake_citations` 问的是「引用编号真不真」。`MAGIC_TAP_SYSTEM` 里逐条写着的
另外那些规矩（不要复述已有内容、不要停在半句上、标题必须自带信息、
**例子里的字面内容绝对不要抄进正文**）**一条都没人在看**。

## 形态照 `checks/slides.py`（`checks/skeleton.py` 是同一档的第二遍）

**判了不拦着落库**：magic tap 的定位是「点一下几秒出一段」，套完整闭环就变成
智能续写了，两个功能没区别。所以这几条**不返回 `Verdict`、不进 `Mode.checks`、
不短路任何东西**——结果跟着产物一起发给前端（`grounding` 那个 SSE 事件多一个
`notes`），用户自己决定要不要重来一次。全部是纯函数，毫秒级。

## 四条做、三条量完不做

阈值和取舍都在**真实产出**上量过（`scripts/tap_report_denominator.py`）。
两份语料：
  · `origin=user` 的 **18 篇**非空真实笔记（走 `corpus_lineage`，只有这一类
    能用来量误伤）；
  · **34 份单次续写**（`harness_quality_samples` 的 14 段「本轮续写增量」+
    `writing_bench_results` 的 20 份「最终正文减去种子」）。后者是 `script`
    血缘——形态是真的，比例不能当生产值，所以它只用来**找真阳性**。

| 判据 | 18 篇真实笔记 | 34 份续写 | 结论 |
|---|---:|---:|---|
| 停在半句上 | 5（**不算数**，见下） | **0** | 做 |
| 复述了光标前已有的段落 | **0** | — | 做 |
| 脚手架标题（`## 收束`） | **0** | 1（真阳性） | 做 |
| 提示词里的例子被抄进正文 | **0** | 2（**全是真阳性**） | 做 |
| 审计腔 / 机制泄漏 | 5（**4 篇是业务词**） | 2 | **不做** |
| 占位符 | 0 | 1（**误伤**） | **不做** |
| 元评论（「本文将」…） | 0 | 0 | **不做** |

*「停在半句」那 5 篇不算数*：判的是**这一次写的那一段**，用户自己的笔记停在
哪里跟它无关。真正的分母是 34 份续写，开火 0。

**不做的三条，每一条都对着一个实测**：

1. **审计腔 / 机制泄漏不做。** `AUDIT_PHRASES` / `LEAK_PHRASES` 那两张表在
   18 篇真实笔记上命中 5 篇，其中 **4 篇命中的是「知识库」这个业务词**——
   「该智能体还将整合全区政务知识库…」「知识库同时记录 EVT 为 4 月 10 号启动」
   都是用户在谈一个**产品对象**，不是模型把工作机制写漏了。34 份续写上命中的
   2 次也全出自同一份讲 grounding 的样本。**词表分不开「机制」和「业务词」**，
   而 magic tap 的文字已经流给用户了，报错一次只会让他困惑。
   （顺带查出来一件事，见台账批 20 计划外发现：harness 里的 `no_audit_voice`
   用的是同一张表，它**会短路打分并要求改写**，而那 5 篇是用户自己的笔记。）
2. **占位符不做。** `placeholder_lines` 在 34 份续写上命中 1 次，那一次是
   误伤：`- 所有时间类表述带状态标签：已确认 / 计划中 / 待定`——「待定」
   在这里是**内容**（一个状态标签的名字），不是「我还没写」。这跟
   `placeholder_lines` 自己注释里记的那次（mermaid 节点 `EVT样品实际时间待确认`）
   是同一种形状：**判据不能把自己看不懂的东西一律当成毛病**。
3. **元评论不做。** 两份语料上各 0 次，`MAGIC_TAP_SYSTEM` 里也没有这条规矩
   ——它是写作 bench 从长文产出里读出来的。分母是零的判据校准不出来。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..middleware import repeats
from ..tailing import needs_tail

# 段落级查重的门槛和最短段长**直接用查重那一份**，不在这里另立一个数：
# 0.6 是 `find_repeats` 在真实产出上定下来的，两处各拍一个数就是下一次漂移。
RESTATE_RATIO = repeats.DEFAULT_THRESHOLD
MIN_PARAGRAPH = repeats.MIN_PARAGRAPH_LEN

# 只说明「这一节在文章里干什么」、完全不说「这一节讲了什么」的标题。
# `MAGIC_TAP_SYSTEM` 里逐字写着这条规矩，还专门点了「功能名：真标题」这种
# 前缀形式同样不行——那是结构节拍的内部措辞漏进了读者看得见的正文。
# 实拍（`writing_bench_results/0903-131801-复盘.md`）：`## 收束：从个案到复盘框架`。
SCAFFOLD_TITLES = ("收束", "总结", "小结", "结语", "展开", "过渡", "补充",
                   "结论", "呼应", "承接", "铺垫")

# 提示词里用来举例说明规则的**字面内容**。这些话只该出现在
# `app/harness/prompts/` 里；一旦出现在产出正文里，说明模型把「规则的示例」
# 当成了「要写的内容」。
#
# **这类污染肉眼几乎发现不了**——读起来完全合理，只有认得出自己写过的提示词
# 才能察觉。实拍：规则里写「不要写 `## 收束`，而要写 `## 混合形态：…`」，
# 模型给一篇定价笔记原样起了后面那个标题，因为例子恰好跟笔记主题撞了。
# 34 份续写上抓到 2 次，**两次全是真的**（`A10 GPU` / `从个案到复盘框架`），
# 18 篇真实笔记上 0 次。（搬过来之前是 3 次，第三次命中的是下面说的那条
# 已经退休的例子——**删掉它当场少了一条"真阳性"，而那条本来就不成立**。）
#
# **名单原来在 `scripts/writing_quality_bench.py` 里**，那边的维护约定是
# 「往 prompts.py 里加带具体内容的例子时，同步往这里加一条」——搬过来是因为
# 它现在有两个消费者（bench 和 magic tap），而 `LEAK_PHRASES` 那次的教训是
# **同一张表放两处一定会漂**。搬的时候当场发现它已经漂了一条：
# `混合形态：买断覆盖硬件，订阅覆盖运营` 在现在的提示词里**一个字都找不到**
# （那一版提示词被重写过）。留着它等于把「模型自己想出来的一个标题」报成
# 「提示词泄漏」，所以删掉了；`test_tap_checks.py` 里有一条闸钉着
# **名单里的每一条都必须逐字出现在 `app/harness/prompts/` 里**，
# 下一次漂移会在闸上停下来，而不是在某个 agent 读代码的时候。
PROMPT_EXAMPLES = (
    "订阅分层与用量计费的落地细节",
    "订阅制的具体设计",
    "从个案到复盘框架",
    "唯一重要的就是速度",
    "速度只有在验证充分的前提下才算数",
    "A10 GPU",
    "缺少……的洞察的不是",
    "以编号错位呈现",
    "统一排序与重编号",
    "决策、冲突与升级机制",
    "决策与冲突处理规范",
    "工时、在线状态与可预期性",
    "可预期工作时段与在线状态管理",
    "统一编号与体例",
)

_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.M)


def scaffold_headings(text: str) -> list[str]:
    """正文里只有脚手架功能、不带信息的标题（原样返回，带前缀的也算）。

    **报完整标题而不是只报那个功能词**：`## 收束` 和 `## 收束：从个案到复盘框架`
    都是问题（功能名前缀是模板漏进了读者能看到的正文），但严重程度差很多，
    人读判据结果的时候得看得见区别。
    """
    out: list[str] = []
    for m in _HEADING.finditer(text or ""):
        title = m.group(1).strip()
        head = re.sub(r"[：:].*$", "", title).strip()
        if head in SCAFFOLD_TITLES:
            out.append(title)
    return out


def leaked_prompt_examples(text: str) -> list[str]:
    """提示词里的例子被原样抄进了正文的那几条。"""
    return [e for e in PROMPT_EXAMPLES if e in (text or "")]


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in (text or "").split("\n\n")
            if len(p.strip()) >= MIN_PARAGRAPH]


def restated_paragraphs(written: str, before: str) -> list[tuple[str, str, float]]:
    """这一段里有没有把**光标前已经写过的**某一段换个说法再写一遍。

    比的是 `before`（提示词里那份「已写正文」）而不是整篇：模型被要求接着它
    往下写，复述它才是这条规矩说的事。一段只报它最像的那一对。
    """
    mine, theirs = _paragraphs(written), _paragraphs(before)
    out: list[tuple[str, str, float]] = []
    for a in mine:
        best = max(((SequenceMatcher(None, a, b).ratio(), b) for b in theirs),
                   default=(0.0, ""))
        if best[0] >= RESTATE_RATIO:
            out.append((a, best[1], round(best[0], 2)))
    return out


@dataclass(frozen=True)
class TapCheck:
    """一次续写的体检。`notes()` 是给界面显示的人话，全合格就是空列表。"""

    """这一段停在半句话上（不是撞 token 上限那一种，那一种另有报法）。"""
    unfinished: bool = False
    """把光标前已有的段落换个说法又写了一遍：(这一段, 原来那一段, 相似度)。"""
    restated: list[tuple[str, str, float]] = field(default_factory=list)
    """只有脚手架功能、不带信息的标题。"""
    scaffold_titles: list[str] = field(default_factory=list)
    """提示词里的例子被原样抄进了正文。"""
    leaked_examples: list[str] = field(default_factory=list)

    def notes(self) -> list[str]:
        out: list[str] = []
        if self.unfinished:
            out.append("这段停在半句话上——句子没说完就收笔了。"
                       "把光标放到末尾再点一次接着写，或者撤回重来。")
        for mine, theirs, ratio in self.restated[:2]:
            out.append(f"这一段把前面已经写过的内容又说了一遍"
                       f"（相似度 {ratio:.0%}）：「{mine[:32]}…」"
                       f"对着的是「{theirs[:32]}…」。")
        if self.scaffold_titles:
            out.append("这几个标题只说明「这一节在文章里干什么」，没说它讲了什么："
                       + "、".join(f"「{t}」" for t in self.scaffold_titles[:3])
                       + "。标题该写成能单独看懂的那句结论。")
        if self.leaked_examples:
            out.append("正文里出现了提示词里用来举例的原话："
                       + "、".join(f"「{e}」" for e in self.leaked_examples[:3])
                       + "——那是写作规则里的示范，不是这篇笔记的内容，"
                         "读起来合理但跟你这篇没关系。")
        return out


def check_tap(written: str, before: str = "") -> TapCheck:
    """一次 magic tap 产出的体检。**纯函数**：给两个字符串就能测。

    `written` 只是**这一次写出来的那一段**，不是整篇——用户自己的正文里有什么
    毛病不归这里管（那是修订和智能续写那条路的事）。
    """
    text = (written or "").strip()
    if not text:
        return TapCheck()
    return TapCheck(
        unfinished=needs_tail(text),
        restated=restated_paragraphs(text, before),
        scaffold_titles=scaffold_headings(text),
        leaked_examples=leaked_prompt_examples(text),
    )
