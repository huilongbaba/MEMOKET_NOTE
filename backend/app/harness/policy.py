"""Runtime 策略控制器：把每一轮的反馈变成下一轮的运行参数。

在这个之前，harness 的 runtime 是开环的——工具预算、暴露哪些工具、续写
temperature、每轮采纳几条修订，全是常数。上一轮 ``factual_grounding``
拿 0 分，下一轮的检索预算和策略跟拿 2 分时一模一样。反馈信号一直在产生
（每个维度的分数和自然语言诊断、工具查了几次、结果是不是空的、连续几轮
没进展），但只有两条被用上：最弱维度名字进修订 prompt，内在质量两项决定
要不要跳过续写。其余全部丢掉。

这个模块补上闭环：``adjust(policy, feedback) -> (policy, reasons)``。

**为什么控制器是确定性代码而不是再叫一次模型**：整个项目反复验证的结论
就是模型的自我判断不可靠——它会把缺陷读成修辞、会在该查的时候不查、会给
"没用完检索结果"扣分。控制器要是也交给模型，出问题时既不可复现也无法归因。
写成纯函数，每条规则对应一个观测到的真实失败，能单测、能在 SSE 里原样
暴露给用户看"这一轮为什么这么跑"。

每条规则下面都注明它是被哪个真实失败逼出来的。没有观测支撑的规则不要加——
凭空调参数只会让行为更难解释。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

# 各个旋钮的边界。上界防止某一轮把单轮时间拖爆（工具每多一轮 = 一次模型
# 调用 = 本地 20-90 秒），下界保证退化之后还能干活。
# 下界是 1 不是 0：0 意味着工具循环根本不跑，agent 从此再也没法查知识库。
# 彻底关掉检索是配置决定（MEMOKET_AGENT_TOOLS=0），不该是反馈能自己走进去
# 的状态。
#
# **这个下界当初是为了兜住一个脏信号，而那个脏信号批 13（计划 2.5）已经换掉了。**
# 原话留在这儿当账：扣预算的判据曾经是「上一轮没用工具」（`tool_calls == 0`），
# 而那件事**包含 agent 正当判断「这段不用查」的情况**——于是它诚实回答一句
# 「不需要检索」就要被扣一格，连着两轮扣到下界。真实 A/B 日志里预算被一路扣到了 0。
# 现在的判据是 `tool_stopped_barren`（工具循环连着两次调用一条新 id 都没带回来，
# 确定性的、代码算出来的），一轮都没查的不再扣预算，见下面「一切正常就把预算
# 收回来」那一段。
#
# **下界照旧留着**，两条理由：① 它挡的是「任何一条规则加起来把预算扣光」，
# 不只是那一个脏信号；② 脏信号那一版的代价是量过的——`harness_rounds` 的 447 轮
# 里 `tool_calls == 0` 的有 76 轮（17.0%），其中**事实达标**的 48 轮（10.7%）
# 正是旧判据真会扣预算的那一格；158 次跑里有 12 次连着 ≥2 轮没用工具（最长 3 轮），
# 也就是说「一路扣到下界」在真实数据里是走得到的。
# **读到这里想「原来这条注释记着个 bug」的下一个人：那个 bug 已经修了，别再修一次。**
TOOL_ITERS_MIN, TOOL_ITERS_MAX = 1, 4
REVISIONS_MIN, REVISIONS_MAX = 4, 10
TEMP_MIN, TEMP_MAX = 0.3, 0.8

# **只有这几个维度的诊断有资格进检索规划 prompt。**
#
# `steer` 唯一的去处是 `prompts/note.retrieval_plan_user`，那个 prompt 回答
# 的问题只有一个：**这一轮该去知识库查哪些事实。** 而检索能改善的维度就
# 这四个——事实站不站得住、查到的材料有没有写进去、节拍/分段覆盖到没有。
#
# 之前这里漏过一条真实的噪声：下面「连续 N 轮没达标 → 升级提示」那条规则
# 对所有维度一视同仁，于是 `non_repetition` 卡住两轮之后，
# 「你把同一件事说了两遍，换个思路」这句话被原样塞进了**决定去查什么**的
# prompt。查什么都修不了重复（`harness-mechanism-rethink.md` §1 错配一），
# 它在那儿只能起两个作用：占 token、把模型的注意力从「这一节缺哪些材料」
# 上引开。
#
# 内在质量那一族（non_repetition / coherence / topic_fidelity）走的是另一条
# 线：`loop.py` 的 `focus` / `focus_note` → `middleware/revise.py` → 修订
# prompt。那条线是对的，也是唯一能让已经写坏的文字变对的那条——**这里少说
# 一句，那边一个字都不少。**
#
# 名单跟 `middleware/repair.INNER_QUALITY` / `loop.COVERAGE_DIMS` 必须互不
# 重叠、互相补齐，`tests/test_runtime_policy.py` 有一条断言钉着
# （policy.py 在分层测试的 PURE 名单里，只能依赖标准库，所以不能 import
# 那两个常量，只能各写一份 + 一条测试对账）。
MATERIAL_DIMS = ("factual_grounding", "material_use",
                 "beat_coverage", "section_coverage")


@dataclass
class RoundFeedback:
    """一轮结束时能拿到的全部信号。构造它的地方在 note_harness 的轮循环里，
    这里只描述形状——保持这个模块不认识 FastAPI、不认识 SSE。"""

    scores: dict[str, int] = field(default_factory=dict)
    # 维度 -> 打分模型写的自然语言诊断。这是此前完全被丢掉的信号，
    # 也是最有价值的一个：它具体说了哪里不对，比一个分数能指导的多得多。
    notes: dict[str, str] = field(default_factory=dict)
    weakest: str = ""
    status: str = "continue"
    tool_calls: int = 0
    tool_facts: int = 0          # 工具实际带回来几条事实
    tools_used: tuple[str, ...] = ()   # 这一轮用到的工具名
    tool_truncated: bool = False
    # 工具循环**自己停了**：连着两次调用一条新 id 都没带回来（计划 2.5，
    # `agent_loop.BARREN_STOP`）。这是「这次跑已经查到头了」的确定性证据，
    # 跟下面那个被它换掉的脏信号不是一回事——见「一切正常就把预算收回来」。
    tool_stopped_barren: bool = False
    # 知识库整个是空的。**这跟「这一轮没查到」是两件事**：没查到值得换条路
    # 再试，空库换什么路都是空。第 676 轮拿全新用户实跑，策略器对着一个空库
    # 发「先 list_topics 看有哪些主题」，白烧一轮。
    kb_empty: bool = False
    revisions_applied: int = 0
    stall_rounds: int = 0

    def level(self, dim: str) -> int:
        """没打到的维度按达标处理——缺信号不该触发降级动作。"""
        return self.scores.get(dim, 2)


@dataclass
class RuntimePolicy:
    """下一轮的运行参数。默认值就是接策略控制器之前的那套常数，所以
    「一轮都不调整」时行为跟改动前完全一致。"""

    tool_iters: int = 2
    # **Extra** groups for this round, not the whole list. Which groups a
    # feature gets is Mode configuration; a runtime policy that replaced it
    # silently dropped every group the Mode declared -- measured: the skill
    # tools were registered, listed in the prompt, and never reachable,
    # because this defaulted to ["memory"] and won.
    extra_tool_groups: list[str] = field(default_factory=list)
    # 注入下一轮检索规划 prompt 的自然语言指令。这是把打分诊断喂回去的
    # 通道——控制器决定"要不要提、提什么方向"，具体措辞用打分模型自己
    # 写的那句话，因为它比我们更清楚哪里不对。
    steer: str = ""
    continue_temperature: float = 0.7
    max_revisions: int = 6
    # 要求写具体数字前先用 fact_sources 回溯原话核对
    require_verification: bool = False
    # 连续几轮同一个维度没改善——升级动作看这个，不是看单轮分数
    stuck_dims: dict[str, int] = field(default_factory=dict)

    def snapshot(self) -> dict:
        """发给前端的可观测快照。用户要能看到"这一轮为什么这么跑"，
        跟 tool-calls 事件是同一个诉求：runtime 的决策不能是黑箱。"""
        return {
            "tool_iters": self.tool_iters,
            "continue_temperature": round(self.continue_temperature, 2),
            "max_revisions": self.max_revisions,
            "require_verification": self.require_verification,
            "steer": self.steer[:300],
            "stuck": {k: v for k, v in self.stuck_dims.items() if v >= 2},
        }


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _track_stuck(policy: RuntimePolicy, fb: RoundFeedback) -> dict[str, int]:
    """维护「这个维度连续几轮没达标」。达标就清零——升级动作只该给
    真的卡住的维度，不该给偶尔抖动一次的。"""
    out = dict(policy.stuck_dims)
    for dim, level in fb.scores.items():
        if level < 2:
            out[dim] = out.get(dim, 0) + 1
        else:
            out.pop(dim, None)
    return out


def adjust(policy: RuntimePolicy, fb: RoundFeedback) -> tuple[RuntimePolicy, list[str]]:
    """根据这一轮的反馈算出下一轮的运行参数。

    纯函数：不读全局状态、不做 I/O、同样的输入永远给同样的输出。返回的
    ``reasons`` 是给人看的解释，每条对应一次实际调整——直接进 SSE。
    """
    reasons: list[str] = []
    stuck = _track_stuck(policy, fb)
    tool_iters = policy.tool_iters
    revisions = policy.max_revisions
    temperature = policy.continue_temperature
    verify = False
    steer_parts: list[str] = []

    # ---- 事实站不住：加检索预算 + 把打分的原话喂回检索规划 ----
    # 真实失败：正文写出「4月10号硬件就位」「Speaker E 5月1号测 APP」这类
    # 具体日期人物，打分判"知识库中查无此事"。此前下一轮的检索预算和策略
    # 一点没变，等于让它拿同样的信息再赌一次。
    if fb.level("factual_grounding") < 2:
        tool_iters += 1
        verify = True
        note = fb.notes.get("factual_grounding", "").strip()
        steer_parts.append(
            "上一轮打分认为正文的事实依据有问题"
            + (f"：{note}" if note else "")
            + ("。知识库是空的，查不到任何东西："
               "把那句改写成不含具体人名/日期/数字的说法，或者直接删掉，不要保留编造的细节。"
               if fb.kb_empty else
               "。这一轮先把这些点查实——查得到就用查到的原话，"
               "查不到就把那句改写成不含具体人名/日期/数字的说法，不要保留编造的细节。")
        )
        reasons.append(f"factual_grounding={fb.level('factual_grounding')} → 工具预算 +1、要求溯源核对")

    # ---- 只会用关键词检索、结果还不顶用：点名要求换精确路径 ----
    # 实测：六次检索全是 search_memory，其中四次召回的是知识库里完全不相关
    # 的内容（中英混合长查询让关键词匹配串味）。原来的规则只判"零召回"，
    # 抓不到"召回了但召回的是垃圾"这种更常见的情况——那种情况下 tool_facts
    # 不是 0，只是那些事实跟正文要写的东西没关系，最后体现为 grounding 低。
    if (fb.level("factual_grounding") < 2 and fb.tools_used and not fb.kb_empty
            and set(fb.tools_used) <= {"search_memory"}):
        steer_parts.append(
            "上一轮只用了 search_memory，而它是关键词匹配，中英混合的长查询很容易"
            "召回完全不相关的内容。这一轮改用 filter_facts 按主题精确取"
            "（主题清单已经给你了），关键词检索最多作为补充。"
        )
        reasons.append("只用了 search_memory 且事实不达标 → 要求改走 filter_facts")

    # ---- 查到了材料却没写进正文：这是最严重的一条 ----
    # 评分的其他维度都在查"有没有毛病"，只有这一条在查"有没有价值"。
    # 一篇零知识库内容的通用文章可以六维全 2、判定 complete——这个产品的
    # 全部价值恰恰在于"写你自己的东西"，所以这条不达标时优先级高于一切。
    if fb.level("material_use") < 2:
        note = fb.notes.get("material_use", "").strip()
        steer_parts.append(
            (note or "上一轮检索到了材料却没写进正文。")
            + " 这一轮**必须**把查到的具体内容落到正文里——用户自己的项目、"
              "数字、决定。通用常识写得再干净也等于没写，宁可只写两句实的，"
              "也不要写满一屏虚的。")
        reasons.append("material_use 不达标 → 要求把查到的材料写进正文")

    # ---- 查了但没查到：换检索路径，别原地重试同一条 ----
    # 真实失败：search_memory("Speaker E 5月1号 APP体验") 召回了知识库里的
    # 英语学习材料。关键词召回在长查询上会串味，这时重试同样的路径没意义。
    if fb.tool_calls and fb.tool_facts == 0 and not fb.kb_empty:
        steer_parts.append(
            "上一轮的关键词检索一条都没召回。这一轮换路径："
            "先 list_topics 看知识库实际有哪些主题，再用 filter_facts 按主题精确取，"
            "不要继续换措辞重试 search_memory。"
        )
        reasons.append("工具查了但零召回 → 改走 list_topics → filter_facts")

    # ---- 知识库整个是空的：**停止检索，也不要再拿"缺材料"当每轮的结论** ----
    # 第 676 轮全新用户实跑：两轮下来正文全是「这里需要补上……」，第二轮打分
    # 自己写「多次重复"需要补上实际内容"」。库空不是这一轮的失败，是这次写作
    # 的前提——说一次就够，剩下的轮次该用在把用户已经写下的东西写好。
    if fb.kb_empty:
        steer_parts.append(
            "这个用户的知识库是空的（一条事实都没有），所以别再调检索工具了。"
            "**缺材料这件事整篇只说一次**，不要每一节都写「这里需要补上……」——"
            "把力气花在用户已经写下的那点内容上：把它的判断、结构和取舍写清楚。"
        )
        reasons.append("知识库是空的 → 停止检索、缺材料只说一次")

    # ---- 结构乱：降温度求确定性 + 给更多修订额度去清理 ----
    # 真实失败：同一小节标题出现两次、标题层级混乱、两个收束板块。
    # 这类问题靠"再写一段"好不了，靠的是更确定的输出和更多的清理额度。
    if fb.level("coherence") < 2:
        temperature = round(_clamp(temperature - 0.2, TEMP_MIN, TEMP_MAX), 2)
        revisions += 2
        reasons.append(f"coherence={fb.level('coherence')} → 续写温度降到 {temperature:.1f}、修订额度 +2")

    if fb.level("non_repetition") == 0:
        revisions += 2
        reasons.append("non_repetition=0 → 修订额度 +2")

    # ---- 卡住了就升级，不是重复同样的动作 ----
    # 真实失败：清理↔续写震荡五轮撞 max_rounds。单轮分数看不出这个，
    # 只有"连续几轮同一维度不达标"看得出来。
    # 一次只升级最要紧的一个，堆一堆提示反而稀释注意力。
    # **挑的时候材料类优先**：`steer` 只对它们有效，要是先撞上一个卡住的
    # `non_repetition` 就 break，同样卡住的 `beat_coverage` 会一句话都得不到。
    escalating = [d for d, n in stuck.items() if n >= 2]
    if escalating:
        dim = next((d for d in escalating if d in MATERIAL_DIMS), escalating[0])
        reasons.append(f"{dim} 连续 {stuck[dim]} 轮未达标 → 升级提示")
        # **卡住的是内在质量时，升级提示不进 steer。** 见 MATERIAL_DIMS 那段：
        # steer 的落点是「这一轮去查什么」，而重复 / 不连贯 / 跑题再查十条事实
        # 也不会好。这一档照旧记 reason（SSE 里用户看得到「non_repetition
        # 连续 3 轮未达标」），但不再往检索 prompt 里塞一句它用不上的话——
        # 修它的力气全在修订那条线上，`Repair` 已经为这三维排了「只修不写」。
        if dim in MATERIAL_DIMS:
            steer_parts.append(
                f"「{dim}」这一项已经连续 {stuck[dim]} 轮没达标，说明上一轮的做法没效果，"
                "换一个思路，不要重复上一轮的动作。"
            )

    # ---- 一切正常就把预算收回来，别白花时间 ----
    # 工具每多跑一轮就是一次本地模型调用（20-90 秒）。事实这一维稳了、
    # 上一轮又查到头了，就没理由继续付这个钱。
    #
    # **判据从 `tool_calls == 0` 换成了 `tool_stopped_barren`（计划 2.5）。**
    # 上面 TOOL_ITERS_MIN 那段注释里记着换掉的理由，那是从真实 A/B 日志里
    # 看出来的：「上一轮没用工具」既可能是 agent 正当判断「这段不用查」，
    # 也可能是它懒得查，两者被当成了同一个信号——于是**它诚实回答一句
    # 「不需要检索」就要被扣一格预算**，连着几轮扣到下界。
    # 新判据没有这个歧义：`stopped_barren` 是工具循环里连着两次调用一条新 id
    # 都没带回来，**确定性的、代码算出来的**，它说的就是「这条线查到头了」。
    # 一轮都没查的（`tool_calls == 0`）从此不再扣预算。
    if (fb.level("factual_grounding") == 2 and fb.tool_stopped_barren
            and tool_iters == policy.tool_iters):
        tool_iters -= 1
        reasons.append("事实达标且工具循环连着两次没带回新材料 → 工具预算 -1")

    new = RuntimePolicy(
        tool_iters=_clamp(tool_iters, TOOL_ITERS_MIN, TOOL_ITERS_MAX),
        extra_tool_groups=list(policy.extra_tool_groups),
        steer="\n".join(steer_parts),
        continue_temperature=_clamp(temperature, TEMP_MIN, TEMP_MAX),
        max_revisions=_clamp(revisions, REVISIONS_MIN, REVISIONS_MAX),
        require_verification=verify,
        stuck_dims=stuck,
    )
    return new, reasons


def from_history(runs: list, base: RuntimePolicy | None = None) -> tuple[RuntimePolicy, list[str]]:
    """用这篇笔记过去几次 run 的结果给第一轮定初始参数。

    ``RunHistoryStore`` 一直在记录每次 run 的终态和未达标维度，但
    ``recent()`` 从来没被调用过——跨 run 的经验完全没被用上。同一篇笔记
    如果前几次都栽在同一个维度上，第一轮就该带着对应策略开跑，而不是
    每次重新踩一遍。

    ``runs`` 是 ``RunRecord`` 列表（最近的在前），只读 ``weak_dimensions``。
    """
    policy = base or RuntimePolicy()
    if not runs:
        return policy, []

    counts: dict[str, int] = {}
    for run in runs:
        for dim in (getattr(run, "weak_dimensions", None) or []):
            counts[dim] = counts.get(dim, 0) + 1

    # 只认"多数次都不达标"的维度——偶尔一次不算经验，那是噪声
    threshold = max(2, (len(runs) + 1) // 2)
    chronic = sorted(d for d, n in counts.items() if n >= threshold)
    if not chronic:
        return policy, []

    reasons = [f"这篇笔记最近 {len(runs)} 次运行里，{'、'.join(chronic)} 反复不达标 → 第一轮就带上对应策略"]
    fb = RoundFeedback(scores={d: 1 for d in chronic},
                       notes={}, weakest=chronic[0])
    tuned, more = adjust(policy, fb)
    # 历史推出来的 stuck 不该直接算作"已经连续卡了两轮"——那是这次运行内
    # 的计数。清空，让本次运行自己重新数。
    tuned = replace(tuned, stuck_dims={})
    return tuned, reasons + more
