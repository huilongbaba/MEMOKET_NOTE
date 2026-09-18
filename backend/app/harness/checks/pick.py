"""一条 check 该打翻哪一维。

单独成文件，不是放在 ``checks/__init__.py`` 里——放那儿会绕成一个环：
包的 ``__init__`` 要 import 三个 check 模块来再导出，而三个 check 模块
都要 ``from . import pick_dimension``。它能跑只是因为函数定义**恰好**写在
那几行 import 之前；谁把 import 挪到文件顶部（每个 linter 都会这么建议）
就当场 ImportError。

一个只在「行的顺序」上成立的结构，迟早会被一次无害的整理弄坏。
"""

from __future__ import annotations

from ..state import State

# ------------------------------------------------------------- 兜底桶 ---
#
# **一个维度不能既是优化目标又是垃圾桶**（计划 4.4 / [MECH] §3）。
#
# 在这之前，6 条判据把 `coherence` 写在第二或第三位当兜底——于是
# `coherence = 0` 可能意味着：审计腔、手写 mermaid、标题位置不对、表格列数
# 对不上……**也可能真的是文章不连贯**。而 `Repair` 一律读成「这一轮只修不写」。
#
# 代码里记着这么死过一次（`middleware/repair.py`，第 606 轮）：手写 mermaid 的
# 判据落在 `coherence` 上（分段模式没有 `has_charts` 这个维度），`coherence`
# 又在 `INNER_QUALITY` 里 → 下一轮 `cleanup_only` → `produce()` 直接返回 →
# **模型根本没机会去调画图工具**，而那正是这条判据要求的修法。判据说「调工具
# 画出来」，修复策略说「这一轮不许写」，两轮原地打转。
# 当时的修法是「判据命中那一轮不算数」（`Repair` 开头那个 `skip_judge` 分支）
# ——**治了那一次，没治病根**：病根是兜底落点本身选错了。
#
# 现在兜底落到这个**专门的桶**上。它不是一个评分维度：
#
#   · 打分器从来不会打它（`Mode.dims` 里没有它，`rubric.evaluate` 见不到它）；
#   · 它不在 `repair.INNER_QUALITY` 里，所以**排不了「只修不写」的修复轮**；
#   · 它不在 `loop.COVERAGE_DIMS` 里，所以也不会被读成「还没写够」。
#
# 它只表示一件事：**代码判据在这一轮抓到了一个机械缺陷**，诊断在
# `Verdict.message` 里逐字写着该怎么修。
#
# 实测这个兜底在生产里真的被走到过：`harness_rounds` 的 354 轮里有 222 轮是判据
# 短路的（62.7%），落点 `factual_grounding` 166 / `non_repetition` 55 /
# **`coherence` 1**——那 1 轮就是长文模式下图表判据落在兜底上的那个形状。
MECHANICS = "mechanics"


def pick_dimension(st: State, *candidates: str) -> str:
    """这条 check 该打翻哪一维——**按当前 Mode 实际有的那些维度挑**。

    以前是写死的，而一条 check 被多个 Mode 共用：``no_fake_charts`` 写死打
    ``has_charts``，在数据可视化模式下对（那个模式的维度就叫这个），在智能
    插图模式下就打了一个**这个模式根本没有的维度**——它那一维叫
    ``chart_validity``。24 个「check × mode」组合里有 8 个是这样。

    后果不大但很别扭：Evaluation 里会出现一个模型从来不会打的维度名，
    喂回下一轮的诊断也顶着一个模型没见过的标签。

    两个维度名不是命名不统一——``has_charts`` 判的是「图有没有信息量」，
    ``chart_validity`` 判的是「图是不是工具产出的」，是不同的轴。所以修法
    不是统一命名，是让 check 在候选里挑这个 Mode 认识的那个。

    一个都没匹配上就落到 ``MECHANICS`` 这个兜底桶（见上面那段），**不再退回
    第一个候选**：退回第一个候选的后果是 Evaluation 里出现一个这个模式根本没有
    的维度名，而那正是这个函数存在的理由。``test_harness_modes`` 里有一条断言
    保证「候选里至少有一个是这个模式真有的」这种情况在配置阶段就被发现。
    """
    have = {d.name for d in st.mode.dims}
    return next((c for c in candidates if c in have), MECHANICS)
