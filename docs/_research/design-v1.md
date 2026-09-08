# 设计 v1：照搬 middleware 模式，不造词

## 概念（6 个，全部是行业标准词汇）

| 概念 | 出处 | 我们的用法 |
|---|---|---|
| `Middleware` | LangChain 1.0 | 能力包：钩子实现 + 自带状态字段 |
| `StopCondition` | Vercel AI SDK | 可组合的停止条件，纯函数只读 |
| `Check` | PydanticAI output_validator / smolagents final_answer_checks | 代码判的判据 |
| `Dimension` | 我们自己（writer_harness 已有） | 模型判的判据 |
| `Mode` | 配置对象 | 一个功能：dims + checks + middleware + stop_when + groups |
| `State` | 全部框架 | 一次 run 的数据 |

## 循环（写死，三步）

```python
for round in 1..max_rounds:
    prepare()   # 取材料
    produce()   # 生成（改已有 + 写新的）
    judge()     # 判断：便宜的先跑（checks）→ 贵的后跑（evaluate）
    if stop := first_match(mode.stop_when, state): break
```

钩子点：`before_run`/`after_run` · `before_round`/`after_round` ·
`wrap_prepare` / `wrap_produce` / `wrap_judge`

## 自查：能不能表达三条 harness 的全部真实行为

| # | 真实行为（实扫得来） | 设计里怎么表达 | 结论 |
|---|---|---|---|
| 1 | edit pass（生成前先改一遍已有正文） | `before_produce` middleware —— 跟 LangChain 的 Summarization 同类 | ✓ |
| 2 | cleanup | 另一个 `before_produce` middleware | ✓ |
| 3 | 取材料三种方式 + 工具失败退回关键词检索 | `wrap_prepare`：调 handler，失败则走退路 | ✓ |
| 4 | `compact_context` | `before_produce` middleware（就是 Summarization） | ✓ |
| 5 | 往后写 | `produce` 本身 | ✓ |
| 6 | dedupe + scrub_meta | `after_produce` middleware | ✓ |
| 7 | 两次落盘 | `after_produce` / `after_round` middleware | ✓ |
| 8 | 打分 | `judge` 本身 | ✓ |
| 9 | `runtime_policy` 调下一轮参数 | `after_round` middleware（= AI SDK 的 prepareStep） | ✓ |
| 10 | **writing_plan 一上来先打分决定这节还写不写** | **`StopCondition`**——不是"一轮里的一步" | ✓✓ 之前怎么表达都别扭，现在自然了 |
| 11 | **compose_block 取材料后没图就再调一轮画图** | **`wrap_prepare`**——多次调 handler 正是 wrap 的标准用法 | ✓✓ 同上 |
| 12 | best-of | Controller 层写死 | ✓ |
| 13 | 材料累积 + 压缩 | middleware + 自带 state 字段 | ✓ |
| 14 | `find_repeats` | `before_judge` middleware，产出 dup_hints | ✓ |
| 15 | run 历史 | `after_run` middleware | ✓ |

**15/15 全部能表达，且每一个都落在标准模式上。** 第 10、11 两条是关键验证——
它们是我之前三版设计里怎么都别扭的地方（"先打分是第一个步骤？" "画图补一轮
写在循环里？"），套上标准模式之后自然了。这说明模式选对了。

## 消歧规则（防止"两个地方都能放"）

- **改内容的 → produce 侧**（before/after_produce）；**只读的 → judge 侧**
- **决定还跑不跑 → StopCondition**，不是 middleware
- **重试 / 多次调用 / 改请求 → wrap_**，不是 before/after
- **一次 run 只做一次 → before_run/after_run**，不是 before_round/after_round

## 待验证（下一轮调研）

- 多个 middleware 的顺序和状态冲突，别人怎么处理
- 有没有写作/内容生成专用的 harness（我们没有 oracle，场景特殊）
- LLM-as-judge 的最佳实践——我们的核心是打分，而打分器和被打分的是同一个模型
