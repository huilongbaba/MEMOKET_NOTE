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

## 7. 更正：第 4 节的三条改法是错的——**截断是最差的一档**

用户第 759 轮的原话：「截断是最差的方法」。这条批评比我第一版意识到的更大：
**第 4 节的第 3、4、5 条全都在挑「从哪一头截」，没有一条在问「为什么要截」。**

### 把上下文管理的手段按信息损失排一下

| 档 | 手段 | 损失 | 我们在哪 |
|---|---|---|---|
| 最差 | **截断**：按**位置**丢，完全不看重要性 | 最大、最不可控 | `facts.py:42` `[-40:]`、`_cut_at_boundary(…, 600)`、`content_for_continue` |
| 次差 | **摘要 / 抽取**：按理解压缩，**回不去** | 有损 | `middleware/compact.py` 折叠更早的小节 |
| 好 | **分页**：不丢，只是不常驻，要用再换进来 | 无损 | — |
| 最好 | **索引 + 按需读取**：上下文里放指针 | 无损，而且天然 append-only | — |

我们现在全部落在最差和次差两档。

而且第二档还有一篇新的对照实验直接打脸：**《Verbatim Chunks Beat Extracted
Artifacts》** 做的就是「逐字片段 vs 抽取出来的摘要」这一组消融，结论是
**「Fidelity Before Structure」——抽取造成的信息损失，比结构化带来的好处更大**，
多跳推理上差距尤其明显。`Compact` 做的正是被它否掉的那件事。

### 我们的处境比论文里好得多

MemGPT / Letta 那套「虚拟内存分页」是为**没有外部存储**的场景设计的：
主上下文当 RAM、外部存档当磁盘，靠函数调用在两者之间换页，
就是为了**避免走到截断那一档**——
> 截断这类方法能延长有效上下文，**但压缩越狠，性能退化越明显**。

而我们根本不需要自己造一套内存管理：
- **笔记正文就在 sqlite 里**，任何一节随时读得到；
- **事实有 id**，`fact_sources` 这个工具**已经存在**；
- 工具循环本来就在跑（`tool_iters` 1–4）。

**换句话说：那些被我们截掉、折叠掉的东西，根本不需要"留在上下文里才不丢"。**
Manus 之所以要「拿文件系统当上下文」，是因为他们没有别的存储；
我们有，而且更结构化。

### 正确的形状：把三处截断换成索引 + 按需读

| 现在（截断 / 压缩） | 改成（索引 + 取） |
|---|---|
| `content_for_continue`：留最后 4000 字，更早的折成摘要 | **小节索引**（每节标题 + 一行）+ **当前小节逐字** + 一个「读第 N 节」的工具 |
| `facts[-40:]`：攒满 40 条从头丢 | **事实索引**（id + 一行）+ **本轮要用的那几条逐字** + `fact_sources` 按需取全文 |
| `_cut_at_boundary(following, 600)` | 同理：给下一节的标题和首句，需要时再读 |

**这一改一次解决四件事**（而且这四件事我们是分四轮各自发现的）：

1. **不再丢信息**——用户这条批评的正面回答；
2. **索引是 append-only** → 前缀稳 → 缓存命中（本文第 1–3 节）；
3. **上下文短** → 避开 lost-in-the-middle（`harness-longform-deepdive.md` 第 3 节）；
4. **判据可以按小节判**（同上第 3 节、建议三）。

四个从不同方向推出来的结论指向同一个改法，这本身是它对的一个信号。

### 代价和风险，老实说

**代价：多一到两次工具往返。** 但我们现在是每轮把 **10537 token** 整个塞进去；
换成索引之后基线会低一大截，多一两次 round-trip 换的是「不丢信息 + 缓存命中」。

**风险：模型不去调那个工具。** 这不是假想——`policy.py` 里就记着
「上一轮没用工具」这种情况，而且它还被写成了一条降预算的规则。
两条缓解，都必须一起上：
- 索引行里**明写**「要看全文调 `read_section(n)`」，不指望它自己想到；
- **当前小节永远逐字给**——保证即使一次工具都不调，这一轮也写得下去。
  **绝不能让"能不能写"取决于"它想不想查"。**

### 我撤回哪几条

- ~~建议三：事实块挪到正文之后~~ → **作废**。挪位置不解决「攒满 40 条从头丢」。
- ~~建议四：`[-40:]` 改成追加式~~ → **作废**。`[:40]` 和 `[-40:]` 是同一档的两头，
  都在丢东西。
- ~~建议五：固化 `Compact` 的摘要~~ → **作废**。那是在优化一个**本来就不该存在的
  压缩**。（区别要说清楚：索引行也是一行短文字，但它是**指针**——全文随时取得回来；
  `Compact` 的摘要是**替换**，取不回来。这是「无损」和「有损」的区别，不是长度的区别。）

**保留第 1、2、6 条**（记 `cached_tokens`、把 `dup_hints` 挪到 `content` 之后、
传 `prompt_cache_key`）——这三条跟截断无关，是纯粹的排布和记账。

### 修正后的顺序

```
1. 记 cached_tokens（不变，仍是第一步）
2. 打分 prompt 挪 dup_hints（不变，两行、最安全）
3. 【新】正文换成「小节索引 + 当前小节逐字 + read_section 工具」
4. 【新】事实换成「事实索引 + 本轮逐字 + fact_sources 按需取」
5. Compact 随 3 一起退休
6. prompt_cache_key（不变）
```

第 3 条是这一轮真正的主菜，也是最大的一处改动。
**它要等第 1 条落地之后再做**——否则改完连「命中率有没有上去」都答不出来。

## 来源

- [Prompt caching | OpenAI API（规则、字段、`prompt_cache_key`）](https://developers.openai.com/api/docs/guides/prompt-caching)
- [Prompt Caching 201（OpenAI Cookbook）](https://developers.openai.com/cookbook/examples/prompt_caching_201)
- [Prompt Caching in the API | OpenAI](https://openai.com/index/api-prompt-caching/)
- [Effective context engineering for AI agents（Anthropic）](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Context Engineering for AI Agents: Part 2（Phil Schmid）](https://www.philschmid.de/context-engineering-part-2)
- [KV cache routing: optimizing agentic AI infrastructure](https://www.ability.ai/blog/kv-cache-routing-agent-infrastructure)
- [Leyline: KV Cache Directives for Agentic Inference](https://arxiv.org/pdf/2606.01065)

**不截断：分页与外部化（第 7 节）**
- [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/pdf/2310.08560) / [Letta](https://www.leoniemonigatti.com/blog/memgpt.html)
- [Context Engineering for AI Agents: Lessons from Building Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
- [Verbatim Chunks Beat Extracted Artifacts: A Controlled Ablation of Memory Representations](https://arxiv.org/pdf/2601.00821)
- [Cooperative Memory Paging with Keyword Bookmarks for Long-Horizon LLM Conversations](https://arxiv.org/pdf/2604.12376)
