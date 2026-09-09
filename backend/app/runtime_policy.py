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
# 「上一轮没用工具」包含 agent 正当判断「不需要检索」的情况，连续两轮不需要
# 查就把预算扣到 0，等于因为它诚实回答了"这段不用查"而永久剥夺它的检索能力。
# 彻底关掉检索是配置决定（MEMOKET_AGENT_TOOLS=0），不该是反馈能自己走进去
# 的状态。这是从真实 A/B 日志里看出来的——预算被一路扣到了 0。
TOOL_ITERS_MIN, TOOL_ITERS_MAX = 1, 4
REVISIONS_MIN, REVISIONS_MAX = 4, 10
TEMP_MIN, TEMP_MAX = 0.3, 0.8


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
            + "。这一轮先把这些点查实——查得到就用查到的原话，"
              "查不到就把那句改写成不含具体人名/日期/数字的说法，不要保留编造的细节。"
        )
        reasons.append(f"factual_grounding={fb.level('factual_grounding')} → 工具预算 +1、要求溯源核对")

    # ---- 只会用关键词检索、结果还不顶用：点名要求换精确路径 ----
    # 实测：六次检索全是 search_memory，其中四次召回的是知识库里完全不相关
    # 的内容（中英混合长查询让关键词匹配串味）。原来的规则只判"零召回"，
    # 抓不到"召回了但召回的是垃圾"这种更常见的情况——那种情况下 tool_facts
    # 不是 0，只是那些事实跟正文要写的东西没关系，最后体现为 grounding 低。
    if (fb.level("factual_grounding") < 2 and fb.tools_used
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
    if fb.tool_calls and fb.tool_facts == 0:
        steer_parts.append(
            "上一轮的关键词检索一条都没召回。这一轮换路径："
            "先 list_topics 看知识库实际有哪些主题，再用 filter_facts 按主题精确取，"
            "不要继续换措辞重试 search_memory。"
        )
        reasons.append("工具查了但零召回 → 改走 list_topics → filter_facts")

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
    for dim, n in stuck.items():
        if n >= 2:
            steer_parts.append(
                f"「{dim}」这一项已经连续 {n} 轮没达标，说明上一轮的做法没效果，"
                "换一个思路，不要重复上一轮的动作。"
            )
            reasons.append(f"{dim} 连续 {n} 轮未达标 → 升级提示")
            break       # 一次只升级最要紧的一个，堆一堆提示反而稀释注意力

    # ---- 一切正常就把预算收回来，别白花时间 ----
    # 工具每多跑一轮就是一次本地模型调用（20-90 秒）。事实这一维稳了、
    # 上一轮也没真用上工具，就没理由继续付这个钱。
    if (fb.level("factual_grounding") == 2 and fb.tool_calls == 0
            and tool_iters == policy.tool_iters):
        tool_iters -= 1
        reasons.append("事实达标且上一轮没用工具 → 工具预算 -1")

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
