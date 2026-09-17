# 续写整篇：context engineering 与缓存命中

> 第 759 轮。**调研 + 现状勘查文档，没改代码。**
>
> 数据背景：`note-harness/run` **417 次调用、2881 秒**，
> 中位**入 10537 token / 出 184 token（57:1）**。
> 两条长文 harness 合计占全部模型调用的 **91%**。
> 这是整个应用里唯一一处「输入侧优化」值得认真做的地方。

---

## 0. 先说一件难堪的事：我们连命中率都不知道

`util/llm.py:75` 的 `_record` 只落三个数——`prompt_tokens`、
`completion_tokens`、`ms`。**`cached_tokens` 一个字都没记。**

所以本文后面所有「能省多少」都是**上界**，不是实测。
**第一步只能是把它记下来。**

---

## 1. 规则（gpt-5.6 档，正是我们现在用的 `gpt-5.6-luna`）

| 项 | 值 |
|---|---|
| 起步门槛 | 前缀 **≥1024 token** 才进缓存 |
| 粒度 | GPT-5.6+ 是**精确边界**；更早的模型按 128 向下取整 |
| TTL | GPT-5.6+ **只有 30 分钟这一个值，也是默认** |
| 折扣 | 命中的输入 token **打五折**；同时省掉 prefill 的时间 |
| 用量字段 | Responses API 是 `usage.input_tokens_details.cached_tokens`（还有 `cache_write_tokens`）。**我们走的是 `/chat/completions`，那边是 `usage.prompt_tokens_details.cached_tokens` —— 落地时按实际返回体确认，别照抄文档** |
| 路由/分账 | 可传 `prompt_cache_key` |

**会让缓存断掉的**（官方列举）：模型、**工具定义与顺序**、
`parallel_tool_calls`、输出 schema、`reasoning.effort`、`text.verbosity`、
以及**上下文压缩**。
> 「若在断点之前内容或相关设置发生变化，该变化之后的前缀就无法匹配到已有缓存。」

**官方唯一的排布建议**：稳定的放前面，变化的放后面。

**两条排除掉的担心**（查过了，不是问题）：
- `temperature` 每轮由策略器在 0.3–0.8 之间调（`hooks/note.py:252`）——
  **采样参数不在会断缓存的清单里**，前缀缓存缓的是 KV 不是采样。
- `policy.extra_tool_groups` 看着像会每轮改工具表
  （Manus 那边明确说「动态增删工具会让 KV 缓存失效，要用 token masking」），
  但**实测它从来没被填过**（`policy.py:234` 原样传递，全仓没有第二处赋值），
  工具表按 Mode 固定。**这一条我们侥幸是对的。**

**TTL 30 分钟这个数对我们很关键**：一次跑最多 8 轮、每轮几十秒，
**同一次跑里的所有调用几乎一定落在同一个缓存窗口内**。
也就是说命中率低的话，不是窗口的问题，**是前缀自己不稳。**

---

## 2. 逐个查我们四种调用的前缀稳定性

### ① 续写（produce）—— 断点太靠前

`prompts/writing.py:459` 的拼接顺序：

```
system（MAGIC_TAP_SYSTEM，4947 字，常量）
  → 【笔记标题】      稳定
  → 风格档案          稳定
  → spine / beats     稳定
  → 文件夹上下文      稳定
  → 【知识库事实】    ★ 每轮变
  → 光标后面的内容    稳定
  → 【正文】          ★ 每轮变（而且是最大的一块）
  → 标题格式提醒 / 「请接着往下写。」
```

好消息：**system 是常量而且在最前面**，4947 字（中文，约 3000–3900 token），
占中位 prompt 的三到四成——这一段现在多半已经在命中了。

坏消息：**第一处变化点是事实块，而正文在它后面。**
正文是最大的一块，于是它永远算不上缓存。

更糟的是**事实块自己也不是追加式的**：

```python
# middleware/facts.py:42
st.facts = (st.facts + fresh)[-st.mode.fact_budget:]     # fact_budget = 40
```

`[-40:]` 是**从头部丢**。一旦攒满 40 条，之后每加一条新事实，
**整个事实块就整体平移**——前缀从这里开始逐字都不一样了。
（对比：`[:40]` 保留最早的就是追加式，前缀稳定。这是行为取舍，不是纯优化，见第 4 节。）

### ② 打分（judge）—— 一处两行的改动，收益最大

`checks/rubric.py:_build_prompt` 的顺序是：

```
system（1188 字英文，约 300 token，常量）
  → context（spine/beats，一次跑内稳定）
  → dimensions（约 1552 字中文，约 1000 token，常量）
  → dup_hints  ★ 每轮变
  → content    最大的一块
```

**`content` 已经放在最后了，这一点本来就是对的。**
但 `dup_hints` 每轮变、且卡在 content 前面——
于是断点落在大约 **1300–2000 token** 处，
**正文那几千 token 从来没有被缓存过一次。**

**把 `dup_hints` 挪到 `content` 之后**，前缀立刻变成
`system + context + dimensions + content`，
而 content 在不被 revise 改动时是追加式的。**这是全文最划算的一处。**

### ③ 修订（revise）—— 跟缓存天然相冲，但不该为缓存让步

它读全文，而且**就地改正文**。Anthropic / Manus 那条原则是：

> 尽量让上下文不可变，**每一步追加而不是替换**，
> 保持结构格式稳定——这能把成本降一个数量级，同时更快。

`revise` 正好反着来。**但它是我们唯一能让文本变短、变对的执行器**
（`harness-mechanism-rethink.md` 第一节），不能为了缓存少修。

**化解办法不是少修，是别把修改摊到每一轮。**
把改动集中进 cleanup 轮——`Repair` 其实已经在这么分了
（内在质量差 → 下一轮 `cleanup_only`）。
这条设计本来是为写作质量做的，**顺带也是缓存友好的**：
突变集中在一轮里，其余轮次的正文保持追加式。

### ④ 检索规划（retrieval plan）

`steer` 每轮变（`hooks/note.py:147`），拼在 user 消息里。
这一路的 prompt 本来就短，优先级最低。

---

## 3. `Compact` 这一层要重新想

`middleware/compact.py` 只作用于续写 prompt：正文超过 `context_keep_last`
（**4000 字**）之后，把更早的部分折成摘要。

问题是**摘要是每轮重算的**，而正文每轮都在长——
于是折叠出来的那段文字每轮都不一样，**前缀每轮都断**。
官方把「上下文压缩」明确列进了会断缓存的变化里，不是巧合。

**建议的形状**：摘要按**小节**切，**一个小节写完就生成一次并固化**，
之后只往后追加新小节的摘要。这样压缩后的上下文本身也变成追加式的。

（顺带：这跟 `harness-longform-deepdive.md` 第 3 节「打分不该每轮读整篇、
改成按小节判」是同一个方向——**把长文切成小节，对质量和对缓存是同一件事**。）

---

## 4. 建议（按「省得多 × 改得小」排）

1. **记 `cached_tokens`。** `llm_usage` 加一列、`_record` 多读一个字段。
   **没有它，下面每一条都是在盲改。** 落地时先打印一次真实返回体确认字段名。
2. **打分 prompt 把 `dup_hints` 挪到 `content` 之后**（`rubric.py:_build_prompt`）。
   两行，风险极低——它本来就是"辅助证据"，放在正文后面语义上也说得通。
3. **续写 prompt 的事实块挪到正文之后。**
   **但有一条实拍规矩要守**：模型永远接着它最后看到的东西写
   （`writing.py:478` 记着这次实拍——把下文放最后，模型就从下文接着写了）。
   所以事实块只能放到「正文之后、最后那句指令之前」，并且落地后要**截图核对
   模型没有从事实接着写**。**这一条不像第 2 条那样安全，要实测。**
4. **`facts` 的 `[-40:]` 改成追加式。** 这是**行为取舍不是纯优化**：
   丢旧的还是丢新的，影响的是"这一轮拿到的材料"。
   更稳的折中是拆成两段：**固定的前 N 条（追加式，进缓存前缀）
   + 本轮新增的若干条（放后面）**。
5. **固化 `Compact` 的摘要**（第 3 节）。
6. **传 `prompt_cache_key`**，按 `note_id + mode + 调用类型` 拼。
   对同一次跑的多轮调用做缓存路由/分账，顺带让第 1 条的统计能按调用类型分开。

---

## 5. 明确不建议

- **不要为了缓存牺牲那条实拍规矩**（「模型接着最后看到的东西写」）。
  第 3 条如果实测发现模型开始从事实块接着写，**就退回去**——
  写作质量优先于省钱。
- **不要把 system 里的内容搬去 user 消息凑前缀长度。** system 已经 4947 字，
  远超 1024 门槛，不缺长度。
- **不要自己做一层"语义缓存"**（相似 prompt 复用结果）。
  那是另一类东西，会引入正确性风险，而我们这里要的只是**前缀稳定**。
- **不要因为 `revise` 破坏缓存就少改。** 见第 2 节 ③。
- **不要动工具表的顺序**去做别的优化——它现在恰好是稳定的，
  而工具定义与顺序在官方的断缓存清单里。

---

## 6. 怎么算做到了

| 判据 | 现在 | 目标 |
|---|---|---|
| 能不能报出命中率 | **不能** | 按调用类型（produce / judge / revise / plan）分别可报 |
| 同一次跑第 2 轮起，judge 调用的 `cached_tokens / prompt_tokens` | **未知** | > 0.7 |
| 同一次跑第 2 轮起，produce 调用的同一比值 | **未知** | > 0.5 |
| 中位 `prompt_tokens` | 10537 | **不变**（这不是压缩输入的优化，是让同样的输入更便宜更快） |
| 续写产出的质量 | — | **不许退**：第 3 条落地后按 `harness-longform-deepdive.md` 的判据复核 |

最后一行是这份文档的底线：**这是一次成本和延迟的优化，
不是一次质量取舍。任何一条改动让产出变差，就退回去。**

---

## 来源

- [Prompt caching | OpenAI API（规则、字段、`prompt_cache_key`）](https://developers.openai.com/api/docs/guides/prompt-caching)
- [Prompt Caching 201（OpenAI Cookbook）](https://developers.openai.com/cookbook/examples/prompt_caching_201)
- [Prompt Caching in the API | OpenAI](https://openai.com/index/api-prompt-caching/)
- [Effective context engineering for AI agents（Anthropic）](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Context Engineering for AI Agents: Part 2（Phil Schmid）](https://www.philschmid.de/context-engineering-part-2)
- [KV cache routing: optimizing agentic AI infrastructure](https://www.ability.ai/blog/kv-cache-routing-agent-infrastructure)
- [Leyline: KV Cache Directives for Agentic Inference](https://arxiv.org/pdf/2606.01065)
