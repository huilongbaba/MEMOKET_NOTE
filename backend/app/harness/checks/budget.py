"""分段写作的「只开了个头就收尾」判据（计划 7.3 / [LONG] 建议四，AgentWrite）。

## 它治的是哪一次实拍

`modes._SECTION_COVERAGE` 上面那段注释记着第 605 轮：用户说「把硬件、APP、
市场三条线**各写成一篇**」，三节各跑**一轮**就五个维度全 2 分判 `complete`，
交出来 **620 / 434 / 429 字**——不是一篇，是一段半。而同一次跑里
`material_used_up` 是 false，硬件那一档知识库里有 **412 条事实，这一节用上了
四条**。

> **短、干净、扣题、有引用、不重复的残篇是这个闭环的最优解，因为没人问它够不够。**

`section_coverage` 那一维在问，但它**全靠模型判**（[LONG] 建议四实测 11 次里
4 次不达标）。AgentWrite 的做法是把「够不够长」这一半交给代码，模型只判
「写到的东西够不够具体」——这一份就是那一半。

## 它**不是**一个目标，是一条下限

[LONG] §6 写得很明白：**不要为「写得更长」优化**。LongWriter 那条线解决的是
「模型写不出 4000 词」，我们的问题恰好相反（写得太长、而且越长越差）。所以：

* 诊断里**一个字都不提「还差多少」**——没有「你还差 200 字」这种逼它凑的措辞
  （批 13 那条「覆盖率是诊断不是指标」同源）；
* 说的是**内容**：分段主题里还有没落地的面、手上还有没写进去的材料；
* 只在「明显没写够」的那一档开火，见下面两个条件。

## 两个条件必须同时成立（这是它窄的地方）

**① 正文还只有一轮的量。** `MAGIC_TAP_SYSTEM` / `section_write` 给每一轮的
分寸是「一个小节，或 1-2 个自然段，通常 200-400 字」。

**② 手上的材料还剩一大半没写进去。** 只有长度那一半的话，一节写得短但材料
用完了，是**写完了**，不是没写够——那时候再拦一轮就是逼它凑。这一条也正是
605 那次真正的形状（412 条里用了 4 条）。`material_used` 拦不住它：那一条只在
**一条都没用上**的时候开火（`grounding_gap` 第一行），用了四条就放行。

**所以这一条真正说话的区间是「用了一点点，远不够」那一档**：材料一条都没用上
的时候，排在它前面的 `material_used` 会先短路（判据链第一条命中的赢），
用户听到的是那条更具体的诊断。这不是缺陷，是先后顺序的设计——**但它意味着
拿「一条都没用上」当素材去测这条判据，测到的其实是 `material_used`**
（`test_section_budget` 里那条走真 middleware 的用例第一版就是这么错的）。

## 门槛怎么来的（以及**它没能接住 605 那三节里的一节**）

**分段模式自己没有一行数据可量**：`harness_rounds` 里 447 轮，分段模式
**0 轮**；`writing_sections` 里 `origin=user` 的 48 条正文**全是 0 字**
（都还是 `pending`）。唯一有正文的 13 条全是 `script` 血缘（soak / 取样脚本
跑出来的），按 `corpus_lineage` 的规矩**只能看形状、不能算比例**：

    411 · 667 · 789 · 886 · 1027 · 1125 · 1182 · 1255 · 1316 · 1795 · 1923 · 1946 · 2862

600 字落在 411 和 667 之间：13 条里只有 411 那条在门槛以下，而那一条
（《协作原则与工作心态》）读起来正是要抓的东西——四个小标题、全是
「信任而非监视」「在线不等于随时在线」这种任何人都能写的通用常识。

**照实说：605 那三节（620 / 434 / 429）这条判据只接得住两节。** 把门槛抬到
700 能把 620 也接住，代价是把 667 那条一起卷进来——而那一条读起来是写完了的。
**宁可漏报一节，不为凑一个实拍把门槛抬到观测分布里面去。**
"""

from __future__ import annotations

import re

from ..state import State
from ..types import Verdict
from .grounding_rules import fact_usage
from .pick import pick_dimension

# 一节的正文少于这么多字（不含空白），就还只有一轮的量。
# 数怎么来的见模块开头——它落在 13 条真实分段正文的最低两条之间。
MIN_SECTION_CHARS = 600

# 手上的材料用掉的比例低于这个数才算「还剩一大半」。1/2 是最钝的那一刀：
# 用一半以上还嫌不够，就变成「材料必须用完」了——而**查回来的材料用不完是
# 正常的**（`material_thin` 的诊断里逐字写着这句），那条线不能越。
USED_RATIO = 0.5

# 材料少于这么多条时不判：两三条材料写进去也撑不出一节，那时候「用了几条」
# 是个噪声比例。跟 `material_exhausted(min_facts=2)` 同一个理由。
MIN_FACTS = 4


def section_budget(st: State) -> Verdict | None:
    """这一节还只有一轮的量，而手上的材料还剩一大半没写进去。"""
    if st.bag.get("outline_mode") or st.bag.get("polish"):
        # 跟 `material_thin` / `material_used` 同一条理由：用户自己列的小节可能
        # 本来就只值几句话，打磨模式更是无权新增内容。
        return None
    if st.round >= st.mode.max_rounds:
        # **最后一轮不拦。** 判据短路会让这一轮没有分数（`rank()` 返回
        # `(-1, -1.0)`），而最后一轮之后没有下一轮去改善它——拦住只会把一轮
        # 产出从候选里摘掉，换不来任何东西。
        return None
    if len(st.facts) < MIN_FACTS:
        return None
    body = re.sub(r"\s", "", st.content or "")
    if len(body) >= MIN_SECTION_CHARS:
        return None
    used, _hit = fact_usage(st.content, st.facts)
    if used >= len(st.facts) * USED_RATIO:
        return None
    return Verdict(
        pick_dimension(st, "section_coverage", "beat_coverage", "material_use"),
        f"这一节到现在还只有一轮的量，而手上 {len(st.facts)} 条材料里只有 "
        f"{used} 条落进了正文。**接着写还没写到的那一面**："
        "分段主题里已经写过的那一点不要再展开一遍，挑一条还没用上的材料——"
        "具体的项目、时间、数字、决定——把它写成正文里的一段。",
    )
