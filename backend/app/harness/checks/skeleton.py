"""骨架（spine / beats）的判据：全是确定性的，零模型调用（计划 4.3）。

## 为什么这一步值得配判据

`skeleton` 是整个写作闭环**最上游、也是唯一没有闭环的一步**
（[EVAL] 问题四 / [LONG] 建议二）。而 `spine_fidelity` 恰恰是**最不容易失败的
维度**——实测 1.88–1.96 封顶，13 次里只有 2 次不达标、一次 0 分都没有。

> 这个数字的读法不是「我们扣题扣得好」，而是**「对着一个从没被验过的计划
> 打分，太容易满足」**。计划错了，`spine_fidelity` 和 `beat_coverage` 可以
> 双双满分，而笔记是坏的。

STORM 的实测支持这个判断：预写作阶段直接决定 organized(+25%) / coverage(+10%)。

## 形态照 `checks/slides.py`：**判了不拦着落库**

骨架是一次成型的产物，不进多轮闭环。所以这几条**不返回 `Verdict`、不进
`Mode.checks`、不短路任何东西**——结果跟骨架一起发给前端，用户自己决定要不要
重新生成。这跟 `slides` 是同一档，也是这一批被明确要求的形态。

## 五条判据，每一条的阈值都是在 20 份真实骨架上量出来的

语料：`notes` 表里 `spine`/`beats` 非空的 **20 篇**（12 篇 `user`、3 篇
`script`、5 篇 `fixture`，走 `corpus_lineage` 分的类）。

| 判据 | 量到的分布 | 门槛 | 真实语料上开火 |
|---|---|---|---|
| 节拍太少 | 3–6 条，从没出过界 | `< 3` | 0 |
| 两条节拍撞车 | 两两最像的一对 **0.13–0.29** | `≥ 0.55` | 0 |
| spine 太薄 | 32–143 字 | `< 15` 字或空 | 0 |
| 一条节拍都不带锚点 | 每份至少 **2** 条带 | `== 0` | 0 |
| 把正文的毛病写成写作意图 | — | 词表命中 | 0 |

**五条在真实语料上全部开火 0**，这是有意的：它们是**回归探测器**，盯的是
`SKELETON_SYSTEM` 那段提示词里逐字记着的几次代价很大的实拍
（缺陷被固化成需求、节拍全是修辞功能位）。提示词治好了它们，而**提示词是会被
改的**；这几条是那几段文字的机械副本。反向那一半（植入式用例）在
`tests/test_skeleton_checks.py` 里逐条钉着。

## 两条**量过之后决定不做**的

* **「spine 是不是一个真的张力」不做。** 拿词表判（「不是…而是」「之间」
  「取舍」「如何」…）在 20 份上**误伤 5 份（25%）**，而那 5 份里至少 3 份是
  货真价实的张力，只是措辞不在表上——「拆穿自己用…掩盖…的习惯」、
  「从『被记录的聊天内容』推进成…决策材料」。这正是 `slides.py` 里
  `NOUN_PHRASE_MAX` 那一次的同一课：**枚举语言现象的表永远补不全**。
  能留下的只有量的判断（spine 太薄），那一条在下面。
* **「beats 覆不覆盖标题点到的面」不做。** 20 份里**能从标题拆出两个面的
  一份都没有**——11 份标题是「未命名」，其余是「创业反思」「hi」这类单短语。
  分母是零，判据无从校准。语料里真出现带并列面的标题时再说。
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

# 提示词要 3–6 条。上限有人管（`store.clamp_skeleton` 截到 6），**下限没有**
# ——一条两条的骨架在 prompt 里就是一句空话，续写那一步照样会被
# `beat_coverage` 判达标（节拍都写到了，因为本来就没几条）。
MIN_BEATS = 3

# 两条节拍像到这个份上就是撞车。**量出来的**：20 份真实骨架里，每一份
# 内部两两最像的那一对落在 **0.13–0.29**，没有一份越过 0.30。门槛放到 0.55，
# 中间留了将近一倍的空当——`no_restated_paragraph` 的 3% 是同样的定法
# （15 篇精确 0.0%、三篇 5.7/27.4/42.9，中间没有连续带）。
DUP_BEAT_RATIO = 0.55

# spine 短到这个份上就不可能是一句「捕捉核心张力」的话，只能是个话题名。
# 实测 20 份的 spine 是 **32–143 字**，最短那份（32 字）是一篇 53 字的链接
# 测试笔记。15 字是「量的判断」那一档（照 `slides.NOUN_PHRASE_MAX` 的做法），
# 不是词法判断。
MIN_SPINE_CHARS = 15

# 节拍里的「锚点」：数字 / 拉丁词 / 引号引起来的一段。
# **为什么只认这三样**：`SKELETON_SYSTEM` 里那条规矩是「至少有一半的节拍要落在
# 具体内容上——这一篇要用到用户哪段经历、哪个项目、哪次决定、哪组数字」，而
# 「落在具体内容上」唯一不需要读懂中文就能判的痕迹就是这三种。实测每一份骨架
# 至少有 **2** 条节拍带锚点（最少的两份是 2/5 和 2/4），所以门槛取
# 「**一条都没有**」——跟观测下界之间隔着整整 2 条。
_ANCHOR = re.compile(r"\d|[A-Za-z]{2,}|[“\"「][^”\"」]{2,}[”\"」]")

# 把正文的**毛病**写成了写作**意图**。
#
# `SKELETON_SYSTEM` 里这一段是全篇最长的一段，因为它记着两次代价很大的实拍：
#
# * 一篇编号 1、2、4、3 的笔记，骨架把它读成刻意手法，生成了「以编号错位呈现
#   形式与内容的脱节」这条 beat；之后每一轮都在服务这个伪目标——修订先正确地
#   把编号改对了，下一条修订又以「结构节拍要求呈现 1-2-4-3 的错位」为由改了回去。
# * 一篇通篇反思「唯速度论」、结尾却写「唯一重要的就是速度」的笔记，骨架把这句
#   矛盾读成了「用自相矛盾制造自我拆台的反转张力」，后面新增了整整一节替它辩解。
#
# **骨架一旦把缺陷固化成需求，后面所有环节都会一起把这篇东西往错的方向修，
# 而且理由充分、无法自我纠正。** 提示词现在挡着它——而提示词是会被改的。
# 词表窄到只收那两次实拍里逐字出现过的说法 + 同族的几个，20 份真实骨架上
# 命中 0。
_DEFECT_AS_INTENT = re.compile(
    r"编号(错位|错序|跳号|混乱|错乱)|标题层级(混乱|不统一|错乱)"
    r"|自相矛盾|自我拆台|反转张力|形式与内容的脱节|错位呈现"
    r"|病句|空壳标题|重复出现的结论")


@dataclass(frozen=True)
class SkeletonCheck:
    """一份骨架体检的结果。`notes()` 是给界面显示的人话，全合格就是空列表。"""

    beats: int
    """spine 空或短得不像一句话。"""
    thin_spine: bool
    """两条讲的是同一件事的节拍（下标从 1 起，相似度）。"""
    duplicate_beats: list[tuple[int, int, float]] = field(default_factory=list)
    """一条带具体锚点（数字 / 拉丁词 / 引语）的节拍都没有。"""
    all_rhetoric: bool = False
    """把正文的毛病写成了写作意图的那几条（原文）。"""
    defect_as_intent: list[str] = field(default_factory=list)

    @property
    def too_few_beats(self) -> bool:
        return self.beats < MIN_BEATS

    def notes(self) -> list[str]:
        out: list[str] = []
        if self.thin_spine:
            out.append("核心张力只有一个话题名那么长——spine 要说的是"
                       "「这篇东西真正在处理的那个问题/转变」，"
                       "去掉它剩下的内容就会散成流水账的那句话。")
        if self.too_few_beats:
            out.append(f"只有 {self.beats} 条结构节拍（一般 3–6 条）——"
                       "节拍太少，续写那一步就没有可对照的结构，"
                       "「写够了没有」这件事会没人判。")
        for i, j, ratio in self.duplicate_beats[:2]:
            out.append(f"第 {i} 条和第 {j} 条节拍讲的是同一件事"
                       f"（相似度 {ratio:.0%}）——两条节拍撞车，"
                       "正文照着写就会把同一段内容写两遍。")
        if self.all_rhetoric:
            out.append("每一条节拍都只是个修辞功能位（「建立处境」「预判追问」"
                       "「收束呼应」），没有一条落到具体的项目、时间、数字或决定上"
                       "——这样的骨架放在任何一篇文章上都成立，"
                       "续写会写成任何人问一句通用助手都能得到的常识。")
        if self.defect_as_intent:
            out.append("骨架把正文里的毛病当成了写作意图："
                       + "；".join(x[:40] for x in self.defect_as_intent[:2])
                       + "。编号错序、标题层级混乱、自相矛盾这些是草稿没整理干净的"
                         "痕迹，不是刻意的修辞设计——骨架服务它们，后面每一轮都会"
                         "跟着把这篇东西往错的方向修。")
        return out


def check_skeleton(spine: str, beats: list[str]) -> SkeletonCheck:
    """一份骨架的体检。**纯函数**：给两个字符串就能测，不碰 State、不碰 DB。"""
    clean = [str(b).strip() for b in (beats or []) if str(b).strip()]

    dups: list[tuple[int, int, float]] = []
    for i in range(len(clean)):
        for j in range(i + 1, len(clean)):
            ratio = difflib.SequenceMatcher(None, clean[i], clean[j]).ratio()
            if ratio >= DUP_BEAT_RATIO:
                dups.append((i + 1, j + 1, round(ratio, 2)))

    blob = "\n".join([spine or ""] + clean)
    offenders = [line for line in ([spine or ""] + clean)
                 if line and _DEFECT_AS_INTENT.search(line)]

    return SkeletonCheck(
        beats=len(clean),
        # 空骨架不算「太薄」：生成失败已经有自己的报错路径
        # （`hooks/note.skeleton` 的 `run_error`、router 的 400），
        # 在这儿再报一次只会变成两处说同一件事。
        thin_spine=bool((spine or "").strip()) and len((spine or "").strip()) < MIN_SPINE_CHARS,
        duplicate_beats=dups,
        all_rhetoric=bool(clean) and not any(_ANCHOR.search(b) for b in clean),
        defect_as_intent=offenders if _DEFECT_AS_INTENT.search(blob) else [],
    )
