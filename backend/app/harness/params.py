"""Run parameters shared by the long-form harnesses.

These lived in ``routers/note_harness`` and were imported by
``routers/writing_plan`` -- the last case of one router reaching into
another.

``TOOL_GROUPS`` has already gone -- it is ``Mode.groups``. What is left is
here because it is genuinely not per-Mode: ``AGENT_TOOLS`` is an environment
switch for A/B measurement, and the two continuation budgets are safety nets
rather than configuration (see the comments below, which explain why).

The comments are the originals. They are worth keeping intact: each records
a number that was wrong once, and why.
"""

from __future__ import annotations

import os


# 单次跑最多这么多轮（修订+续写算一轮）——真正的停止条件是 evaluate() 判定
# complete/blocked，这个只是防失控的安全网，跟 openJiuwen Goal Mode 里
# "语义完成"和"硬限制"分开判断是同一个道理。
# 续写这一步是让 agent 自己拿工具查知识库，还是沿用预装配检索。默认走
# 工具——"要不要查、查什么"交给模型判断，能用上 KITE 里关键词召回够不到的
# 能力（主题树、结构化过滤、事实溯源）。留开关是为了能在质量 bench 上做
# 同材料 A/B：这个改动动的是 factual_grounding 这一维，不实测不能说它更好。
AGENT_TOOLS = os.getenv("MEMOKET_AGENT_TOOLS", "1").lower() not in ("0", "false", "no")


# 单轮续写的正文 token 上限。**这是安全网，不是控制器。**
#
# "一轮写多少"由 prompt 的语义约束管（MAGIC_TAP_SYSTEM 里的"写 1-3 段即可，
# 除非用了标题或图表让篇幅自然变长"）。token 上限只该在两种情况下起作用：
# 模型陷入重复循环失控，以及单轮延迟超出可接受范围。
#
# 原来是 900，中文一个字约 1-1.5 token，六七百字就撞顶——那个数在**塑造
# 产出**而不是兜底，模型经常正说到一半被切（实测正文以「这意味着」结尾）。
# 后来定到 2000（约 1300 汉字）仍然会被撞到——一张 mermaid 图就在这个水位
# 上被截断了。**一个会在正常使用里被撞到的"安全网"就不是安全网**，它还在
# 管"一轮写多少"，而那件事 prompt 里已经明确写了（一个小节或 1-2 段、
# 200-400 字）。
#
# 4000 约合 2600 汉字，是正常轮次的六到十倍。撞到它只可能意味着模型陷入了
# 重复循环，那正是断路器该拦的唯一情形。
CONTINUE_MAX_TOKENS = 4000

# 撞上限之后用来把话补完的额度。只补当前这一段的收尾，不该太大——大了
# 等于又续了一轮，会绕过打分环节。
CONTINUE_TAIL_TOKENS = 400
