# Agent / 写作 harness 框架调研（工作笔记）

每个框架问同样六个问题，才能横向比较：

1. **循环**：写死还是可配置？
2. **扩展点**：钩子名 + 签名，能不能改流程（不只是观察）？
3. **状态**：怎么组织，谁能改？
4. **能力打包**：一个能力（比如摘要压缩）怎么表达？
5. **防漏**：必需能力怎么保证不被移除？
6. **质量闭环**：有没有「不达标就重来」的机制？判据怎么表达？

---
## LangChain 1.0 AgentMiddleware（最匹配）

1. **循环**：写死。middleware 只在固定钩子点插入。
2. **扩展点**：两类，分得很清楚——
   - 生命周期：`before_agent` / `before_model` / `after_model` / `after_agent`
     返回 `dict` 更新状态 · `None` 不变 · `Command` 流程控制（`jump_to`）
   - 拦截：`wrap_model_call(request, handler)` / `wrap_tool_call`
     可多次调 handler（重试）、跳过（短路）、改请求改响应
3. **状态**：`AgentState` TypedDict；**middleware 自带 `state_schema` 声明自己要的字段**
4. **能力打包**：一个 middleware = 钩子实现 + 自己的 `tools` + 自己的 `state_schema`
5. **防漏**：deepagents 的 `excluded_middleware` **明确拒绝移除 FilesystemMiddleware**
   （"required scaffolding"）——必需能力框架层拒绝移除
6. **质量闭环**：无内置。middleware 可以自己实现（after_model 拦截）
7. 组合：洋葱。进来顺序、回去逆序

## OpenAI Agents SDK

1. **循环**：写死（调模型 → 有 tool call 就执行 → 再调；出 final output 就停）
2. **扩展点**：`RunHooks`（整个 run）/ `AgentHooks`（单个 agent）——
   `on_llm_start/end` `on_agent_start/end` `on_tool_start/end` `on_handoff`
   **全部返回 None，只读观察，不能改流程**
3. **改流程走另一条路**：guardrails（input guardrail 在调模型前、output guardrail 在出结果前）
4. **要点**：把「观察」和「干预」**做成两种不同的东西**，不混在一起

## Claude Agent SDK

- 钩子能改：`PreToolUse` 可返回 `permissionDecision`(allow/deny/ask/defer) + `updatedInput`；
  `PostToolUse` 可返回 `updatedToolOutput`（替换工具输出）+ `additionalContext`
- **权限评估有固定优先级**：hooks → deny 规则 → ask 规则 → 权限模式 → allow 规则 → callback
  「hooks 先于一切」+「allow 不能放宽 deny」= 安全兜底不可被绕过

## smolagents（HuggingFace，极简）

1. **循环**：写死。`while not final and step <= max_steps:` 规划步（按 interval）→ 动作步 → 收尾
2. **扩展点**：
   - `step_callbacks`：按 step 类型注册，**观察**
   - `final_answer_checks`：**一组校验函数，验证最终答案**——就是「判据」
   - 子类覆盖 `_step_stream()`：换掉动作步本身
3. **状态**：`AgentMemory.steps` 累积 + `ActionStep`（输入/输出/观察/token/耗时）+ `self.state` dict
4. **要点**：`write_memory_to_messages()` 每次从累积的 step 重建上下文

---

## 横向发现（持续更新）

- **「观察」和「干预」是两类不同的扩展点**，OpenAI 分成 hooks/guardrails，
  LangChain 分成 lifecycle/wrap。混成一个是设计错误。
- **循环一律写死**。四个框架无一例外，没有人做「可配置的步骤列表」。
  → 我之前那版流水线（步骤列表可配）不是 best practice。
- **能力打包成 middleware/中间件，自带状态字段和工具**。
- **必需能力靠框架拒绝移除**，不靠约定。

## DSPy Refine（质量闭环的标准实现）

```python
Refine(module, N, reward_fn: Callable[[dict, Prediction], float], threshold, fail_count=None)
```
- 循环：`for idx, rid in enumerate(rollout_ids)` —— 每次换 rollout_id，temperature=1.0
- **跟踪最好的**：`if reward > best_reward: best_reward, best_pred, best_trace = ...`
- **早停**：`if threshold is not None and reward >= threshold: break`
- **反馈**：不达标时 `dspy.Predict(OfferFeedback)(...)` 生成 advice，
  下一次由 `WrapperAdapter` 把 `inputs['hint_'] = advice[...]` 注进去
- **容错**：`if idx > self.fail_count: raise e`，默认 fail_count = N
- 要点：**判据是单个 float + 阈值**，换来的是「可比较、能取最好的一次」

## Vercel AI SDK v5（停止条件可组合）

- `stopWhen`: **一组可组合的停止条件**，默认 `stepCountIs(20)`；
  `stopWhen: [stepCountIs(20), yourCustomCondition()]`
- `prepareStep`: 每次调模型前动态改 model / tools / messages / toolChoice
- 要点：**「什么时候停」被抽成一等公民且可组合**，不是循环里的 if

## Reflection / evaluator-optimizer 系（学术 + LangGraph 实现）

- 基本型：generator 起草 → reflector 批评 → generator 修订
- MIRROR：内部评分过阈值就放行，否则迭代修订
- MAR：把「行动 / 评估 / 批评」拆给不同 persona，避免单模型自评的盲区
  → 对应我们的痛点：**打分器和被打分的是同一个模型**

---

## 横向发现（第二轮更新）

7. **停止条件应该是可组合的一等公民**（AI SDK 的 `stopWhen`），
   不是循环里的 `if status == ...`。我们有 complete/blocked/max_rounds/
   材料用完/连续无新事实 五种停法，现在全散在循环里。
8. **best-of 是标配**（DSPy），我们完全没有。
9. **单模型自评是公认弱点**，学术方案是多 persona 批评；
   我们的工程方案是确定性检查——方向一致，代价更低。

## Vercel AI SDK v5 —— stopWhen / prepareStep 细节

```typescript
stopWhen?: StopCondition | StopCondition[]        // 数组 = OR，任一满足就停
// 内置：isStepCount(n) · hasToolCall(...names) · isLoopFinished()
const custom: StopCondition = ({ steps }) => boolean   // 纯函数、只读、无副作用

prepareStep?: async ({model, stepNumber, steps, messages}) => {
  model?, temperature?, activeTools?, toolChoice?, messages?, ...   // 全可选
}
```
→ `prepareStep` 正是我们的 `runtime_policy`（每轮调参数）的标准形态。

## OpenHands（coding harness，有 oracle）

- **agent = 从事件历史到下一个事件的函数**，stateless、event-driven
- **三层：Controller / Agent / Runtime**
  - Controller：监督者，管**约束**（迭代数、预算）和**生命周期**（start/stop/pause）
  - Agent：只做决策（读 history → 产出下一个 action）
  - Runtime：执行 action
- 状态 = event stream（action-observation 对的时序集合）
- **condensers** 专门管上下文压缩
→ 要点：**「管预算和生命周期的」跟「做决策的」分开**。我们的循环两件事混在一起。

## PydanticAI

- **两阶段验证**：Pydantic 语法验证（类型/必填/约束，零成本）
  → `output_validator` 语义验证（业务对不对，可能要 I/O）
  任一失败都 `ModelRetry(msg)`，msg 回给模型
- retry 预算分层：agent 级 / run 级 / per-tool
→ 要点：**便宜的判据先跑，贵的后跑**。我们现在反了——先打分（一次 LLM 调用）
  再跑确定性检查；检查命中的话那次打分就白花了。

---

## 最终横向结论（10 个框架）

| # | 结论 | 谁这么做 | 我们现状 |
|---|---|---|---|
| 1 | **循环写死，不可配置** | 全部 10 个 | 三份手抄的循环 |
| 2 | **观察型和干预型扩展点分开** | OpenAI(hooks/guardrails)、LangChain(lifecycle/wrap) | 混在一起 |
| 3 | **能力打包成 middleware，自带状态字段和工具** | LangChain、deepagents | 散在循环里 |
| 4 | **停止条件是可组合的一等公民** | AI SDK `stopWhen` | 5 种停法散在循环里 |
| 5 | **best-of：留最好的一次，不是最后一次** | DSPy `Refine` | 无 |
| 6 | **便宜的判据先跑，贵的后跑** | PydanticAI 两阶段 | 反了 |
| 7 | **管约束的和做决策的分层** | OpenHands Controller/Agent | 混在一起 |
| 8 | **必需能力框架拒绝移除** | deepagents | 靠人记得接 |
| 9 | **每步前可改配置（prepareStep）** | AI SDK | 有（runtime_policy），只 note_harness 用 |
| 10 | **失败要有退路** | DSPy `fail_count` | 有（退回关键词检索），只两条用 |

## fendouai/writing-harness（唯一的写作专用 harness，最直接的对标）

骨架七步：`Baseline → Architecture → Modules → CTA → Draft → Sensors → Rollback`

- **Sensors** = 机械质量检查：写作 lint（套话、弱开头、弱结尾）· K/P/A 校验 ·
  体裁契约 · trace-aware QA · **失败分类法**（`generic_abstraction`、
  `overexplained`、`false_balance`——给缺陷起名字）
- **Rollback by failed dimension（按失败维度定点回滚）** ← **我们完全没有**
  - K（知识）失败 → 只回 M-01/M-02
  - P（方法）失败 → 只回 M-03
  - A（行动）失败 → 只回 M-04/M-05
  - **只重启失败的那一层，避免盲目整体重来**
- 判据分两类：`evals/` 确定性检查 + judge workflow（pairwise 比较）

→ **这条解释了我们实测到的怪现象**：某次第 2 轮画出两张干净的图，第 3 轮
为了满足打分器又加了张单值图，交付的是第 3 轮。整轮重来会把已经好的部分
一起重做。best-of 只是补丁，**定点回滚才是根治**。

## LLM-as-judge 的公认实践（对我们是硬伤）

- **self-preference bias**：judge 给自己模型家族的输出打分会虚高
- **明确建议：never use the same model family as both generator and judge**
  → 我们正是这样：`muse-glimmer-30b` 既写又判
- 其它已知偏差：position bias、**verbosity bias（奖励长答案）**
- 缓解：**把复杂 rubric 拆成离散检查**（← 我们做确定性检查的方向被验证了）·
  pairwise 双向比较 · 对齐人工基线到相关系数 > 0.85

## LangChain middleware 的精确语义（照抄这套规则）

- 顺序：`before_*` 列表正序，`after_*` **逆序**，`wrap_*` 第一个包住其余
- 状态合并：reducer 字段（如 messages）additive；**非 reducer 字段外层胜**
- **wrap 重试时，早先 handler 调用产生的状态更新会被丢弃**
- 自定义状态：继承 `AgentState` 声明 `NotRequired` 字段；
  装饰器版（单钩子）和类版（多钩子）都支持

## 用我们自己的数据验证闭环有没有在起作用

`scripts/harness_stress_log.jsonl`，200 条记录（2026-09-02）：

| 指标 | 结果 |
|---|---|
| 分数随轮次 | 1.679 → 1.676 → 1.681 → 1.647 → 1.500 —— **平的，后期在跌** |
| 同一次 run 内相邻轮次 | 上升 3 · 下降 8 · 持平 7，**平均 −0.120** |
| 最后一轮是不是这次 run 的最高分 | 8 次多轮 run 里 **5 次不是（62%）** |
| 最常拖后腿的维度 | `non_repetition` 145 次（绝对多数） |

**样本量小**（18 对相邻轮次、8 次多轮 run），且是旧数据，只能当假设。
但它跟两个独立观察一致：① writing-harness 的「整轮重来会毁掉已经好的部分」；
② 本次会话实测——某次第 2 轮画出两张干净的图，第 3 轮加了张单值图，交付第 3 轮。

**要立刻验证**：跑一批新 soak，记录每轮的分数**和产出**，看
「多跑一轮平均掉分」还在不在。按已有教训，先读原文再看表。
