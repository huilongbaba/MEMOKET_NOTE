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


# 账本摘要要不要进检索规划的 prompt（计划 2.4）。
#
# **这是账本唯一会改 prompt 的那一步，所以它必须能单独关掉。**
# 理由不是谨慎，是有实测证据的反向风险（docs/harness-fact-ledger.md §10⑤）：
# 注入的上下文会把 agent 锚定到特定解法上、缩小它的搜索空间。摘要写成
# 「缺口」形式是为了让这个效应反过来用，但**效应本身是真的**——真跑下来
# 要是检索反而变窄，得能只撤这一步，而不是连账本（2.1/2.2/2.3 都靠它）
# 一起撤。关掉之后 `retrieval_plan_user` 收到的是空串，跟批 12 之前一字不差。
LEDGER_IN_PROMPT = os.getenv("MEMOKET_LEDGER_PROMPT", "1").lower() not in (
    "0", "false", "no")


# 续写 prompt 里的正文用不用「小节索引 + 当前小节逐字」（计划 3.1 / [CE] §7）。
#
# 关掉 = 退回 `Compact`（更早的部分折成摘要）。**这条开关存在的理由跟
# `LEDGER_IN_PROMPT` 一样**：[CE] §7 自己写明了这一改有一个真实风险
# ——**模型不去调 `read_section` 那个工具**（`policy.py` 里就记着「上一轮没用
# 工具」这种情况）。两条缓解（索引行里明写怎么调 + 当前小节永远逐字给）
# 都上了，但**效应本身要真跑才知道**；真跑要是发现产出变差，得能只撤这一条，
# 而不是连事实索引一起撤。
SECTION_INDEX = os.getenv("MEMOKET_SECTION_INDEX", "1").lower() not in (
    "0", "false", "no")


# 事实块用不用「事实索引 + 本轮逐字」（计划 3.2 / [CE] §7 / [MR] §3.5）。
#
# 关掉 = 退回 `(st.facts + fresh)[-fact_budget:]` 那个写法，也就是**攒满
# 40 条之后从头丢**。那是「截断」那一档：既丢信息，又让整块事实每加一条就
# 整体平移（断缓存前缀），还造成「同一条事实被反复换进换出，每次花一次
# 工具调用」（[MR] §1）。
#
# 跟 `SECTION_INDEX` **分成两个开关**，不合并：真跑要是退步了，得能分清
# 是正文那一半还是事实那一半——批 13 的头条数就是靠隔离实验（只开 2.5 那一臂）
# 才说得清「2.5 单独值多少」。
FACT_INDEX = os.getenv("MEMOKET_FACT_INDEX", "1").lower() not in (
    "0", "false", "no")


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


# `prompt` / `custom` 跑之前要不要从用户那条指令现场生成 checklist（计划 6.1/6.2）。
#
# **这是会改产品行为的一批，所以它必须能单独关掉**——形状照 `LEDGER_IN_PROMPT`
# （批 13）和 `SECTION_INDEX`（批 15）。关掉之后这两个模式退回 `PROMPT_DIMS` /
# `CUSTOM_DIMS` 那三条固定维度，不生成清单、不抽约束、不多花那一次调用，
# 跟批 16 之前一字不差。
#
# 反向风险是实打实的（`harness-evaluator-industry.md` §4 的 RaR 消融里，
# rubric 质量本身就是核心变量）：生成出来的条目要是抓错了重点，模型会被一条
# **用户没提过的要求**牵着改。代码这一侧的三道闸（依据逐字核对 / 不跟程序判的
# 重复 / 生成不出来就退回）挡的是能挡的那部分，挡不住"条目本身跑偏"——
# 那一档只能靠这个开关。
PROMPT_CHECKLIST = os.getenv("MEMOKET_PROMPT_CHECKLIST", "1").lower() not in (
    "0", "false", "no")


# 「这一节的材料够不够」那条判据要不要上（计划 7.2 / [LED] §10③）。
#
# **它会改产品行为**——材料不够时它要求模型弃答（「这里需要补上 XX 的实际
# 记录」）而不是照写，所以按批 13 `LEDGER_IN_PROMPT` / 批 15 `SECTION_INDEX` /
# 批 17 `PROMPT_CHECKLIST` 同一个形状配一个单独的开关。
#
# 反向风险是实打实的：判据要是在材料其实够的时候开火，就会往一篇好好的正文里
# 塞一句多余的「这里需要补上…」，而那正是 [LED] §4 那条边界的镜像——
# 覆盖率是诊断不是指标，判据也不能反过来**逼着弃答**。代码这一侧窄了三道
# （手上有材料就不判 / 没问过就不判 / 已经弃答过就不判），挡不住的那一档
# 只能靠这个开关。关掉之后 `note` / `section` 跟批 17 之前一字不差。
#
# 7.1 那条（`claims.unsupported_specifics`）**故意没有开关**：它跟批 16 的
# 数字比对同一类，是纯粹的缺陷检测器——报出来的是"这几个字面查无出处"，
# 不改写作方向。没有需要单独回退的行为变化。
SUFFICIENT_CONTEXT = os.getenv("MEMOKET_SUFFICIENT_CONTEXT", "1").lower() not in (
    "0", "false", "no")


# 打分器读的正文用不用「小节目录 + 后面几节逐字」（计划 4.2 / [LONG] §3）。
#
# 关掉 = 每一轮整篇逐字给打分器，跟批 18 之前一字不差。
#
# **这条开关存在的理由跟 `SECTION_INDEX` 不完全一样。** 那一条的风险是「模型
# 不去调 `read_section`」——还有工具循环兜着；这一条**没有兜底**：打分那一步
# 没有工具循环，目录行取不回全文，它是一次**有损**的替换（[CE] §7 的第二档）。
# 换句话说，这一改是拿「中间那几节的逐字正文」去换「打分器真的看得见开头和
# 结尾」，而 lost-in-the-middle 那 30% 是文献里的数、不是我们自己量的。
#
# 所以它必须能单独关掉：真跑或 bench 上要是发现某一维的召回掉了
# （最可能是 `factual_grounding`——它判的是具体字面），得能只撤这一条，
# 而不是连 3.1 / 3.2 那两条索引一起撤。
SECTION_SCORING = os.getenv("MEMOKET_SECTION_SCORING", "1").lower() not in (
    "0", "false", "no")
