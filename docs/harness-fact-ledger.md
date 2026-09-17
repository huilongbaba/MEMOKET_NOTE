# 材料账本：多轮检索与 context engineering 是同一件事

> 第 761 轮。**方案文档，不改代码。**
>
> 前提先说死：**不换 memory engine，就用 kite。**
> 这份回答的是——用 kite 的时候，怎么确保拿到的材料**够准、够全**；
> 需不需要多轮查询机制；那个机制怎么跟 context engineering 互相加强；
> 以及它在整个 harness 里起什么正向作用。

---

## 0. 「准」和「全」是两个问题，机制不同

| | 问的是 | 需要什么 |
|---|---|---|
| **准确** | 取回来的这条，跟正文里写的那句话对得上吗 | **可回溯到原话** |
| **全面** | 该取的都取到了吗 | **一个分母** |

我们现在两样都没有：准确靠模型自己判（`factual_grounding` **41% 不达标、11 次 0 分**），
全面**根本没被问过**——没有任何地方知道「这一节该有的材料一共有多少」。

---

## 1. 好消息：分母不用造，kite 已经给了，是我们每轮扔掉的

逐个看 `memory` 组的工具返回：

| 工具 | 返回里已经带着什么 |
|---|---|
| `list_topics` | `- 主题code（**N 条**，别名…）` —— **每个主题的事实总数** |
| `filter_facts` | 返回体第一行就是 **「共 N 条，返回 M 条」** |
| `list_entities` | 实体 + 各自条数（第二条轴） |
| `facts_in_range` | 时间轴（第三条轴） |
| `fact_sources` | 一条事实 → **原始对话的那几行**（准确那一半的凭据） |
| `gather_subject` | 「一次取全」；实测 60 条真实查询，命中目标主题的比例 **57% → 88%**，代价约多返回一条 |

**三条带计数的结构化轴（主题 / 实体 / 时间）+ 一条回溯通道，全都现成。**

而 `hooks/note.py:111` 每轮 `trace = ToolTrace()` 新建，
轮末丢掉——**「共 N 条，返回 M 条」这句话我们每轮读一次、每轮扔一次。**

---

## 2. 机制：一份跨轮的**材料账本**

不是新系统，是 `st.bag` 里的一个对象，活一次跑那么久，进 snapshot。
**它同时是五样东西**——这正是为什么多轮检索和 context engineering 不该分开做：

| 它是 | 解决的问题 | 出自哪一份文档 |
|---|---|---|
| **检索状态**（查过什么、哪次查空了） | 重复查询、换进换出 | `harness-multiround-retrieval.md` |
| **覆盖分母**（各主题 共 N / 已取 M） | 「全面」 | 本文 |
| **上下文索引**（id + 一行） | 截断 | `harness-context-engineering.md` §7 |
| **引用来源**（id → 原话） | 「准确」 | 本文 §4 |
| **append-only 的前缀** | 缓存命中 | `harness-context-engineering.md` §1–3 |

形状（示意，不是最终字段）：

```python
ledger = {
  "queries": [ {tool, args, hit, empty} ],           # 查过什么、有没有查空
  "axes":    { "topic:众筹": {"total": 41, "taken": 12}, ... },   # 分母
  "facts":   { "f_8a3c": {"line": "…一行摘要…",
                          "state": "taken|used|dropped",
                          "why": "跟这一节无关"} },
}
```

**只存 id + 一行 + 状态。全文永远回 kite 取**——
它是索引，不是第二份事实库。这条边界一旦破掉，账本自己就变成了一个要维护一致性的副本。

---

## 3. 多轮机制该是什么形状：从「该查什么」改成「还缺什么」

现在检索规划问的是「这一轮该查什么」，而且是每轮从零问一遍。
按 `S2G-RAG` 的 sufficiency + gap judging 形状，它该问：

```
【已经取到的材料】（账本摘要，不是全文）
  众筹：共 41 条，已取 12 条
  硬件节点：共 23 条，已取 23 条 ✓
  定价：共 18 条，已取 0 条
【已经查过、查空的】
  search_memory("APP 安装 测试") → 0 条
【这一轮要写】
  「定价与销售预测」这一节
【问题】
  还缺什么？只查缺的那部分。
```

**这一段的每一个数字都来自账本，一次额外的模型调用都不需要。**

### 何时停：覆盖率不再上升就停

现在是固定 `tool_iters`（1–4），由策略器按「上一轮用没用工具」加减——
而那个信号是脏的（`policy.py` 自己的注释就记着：把「它诚实回答这段不用查」
当成了「不需要检索能力」）。

改成 **adaptive stopping**（`TASR` 那条线）：一轮工具循环里，
**连续两次调用没有带回新 id 就停**。这是个确定性判断，不用模型。

---

## 4. 「准确」那一半：两道，都能做成确定性的

### ① 取的时候：让「用 filter_facts 而不是 search_memory」变得可核查

prompt 里已经写了「主题对得上就优先用 `filter_facts`，比 `search_memory`
的关键词匹配准得多」。而实测是**六次检索全是 `search_memory`**。

账本里记着每条事实**来自哪个工具**，于是这条从「一句劝告」变成**一个可以量的数**：
关键词检索占比。量得出来，才谈得上改。

### ② 用的时候：`citations_hold` 可以不再依赖模型

`checks/grounding.py` 的 `citations_hold` 已经在查「正文引的 id 在不在材料里」。
但真正的核对要走 `fact_sources`（id → 原话），而那个工具
**「模型从没被观察到自己走到第二步」**（`hooks/note.py` 的注释）。

有了账本，这一步**根本不需要模型**：正文里引了 `f_8a3c`，
账本里有它的 id 和一行，需要原话就直接 `fact_sources` 拿——
**代码去比，不是让模型去比。**

这一条直接打在 `factual_grounding` 上，而那是我们**第一大阻塞项**。

### 一条必须写死的边界：覆盖率**不是**目标

`_FACTUAL_GROUNDING` 的 guidance 里有一条吃过亏才写进去的规矩：

> **检索到的事实没有被全部用上，明确不算不足。**
> （因为这条扣过分，下一轮正文里就「引入了大量未在知识库中出现的具体日期与人物」。）

所以分母是**诊断**，不是**指标**。
「定价 18 条一条没取」值得追问；「众筹 41 条只用了 12 条」**完全正常**。
**账本用来发现空白，不用来逼着填满。**
（这跟 `SAFE` 流水线里那一步「relevance check：这条值不值得查」是同一件事——
论文把它做成显式一步，我们现在塞在一段 guidance 文字里指望模型自觉。）

---

## 5. 它怎么 benefit from context engineering —— 两者是同一个数据结构

这是这份文档的核心。三条互相加强，**缺一条另两条也立不住**：

```
账本只放 id + 一行
   ↓ 上下文短
   ├→ 避开 lost-in-the-middle（判据判得更准）
   └→ 全文按需 fact_sources 取 → 不需要 [-40:] 截断
账本 append-only
   ↓ 前缀逐字稳定
   └→ 缓存命中（TTL 30 分钟，一次跑的所有轮次都在窗口内）
不再截断
   ↓
   └→ 账本才能一直准确
```

最后那条反向依赖值得单独说：**如果还在 `[-40:]` 截断，账本就会跟实际上下文对不上**
——账本说「已取 40 条」，而 prompt 里只剩最近的那 40 条，早先的已经被挤掉了。
**账本要准，就必须先不截断。**

反过来，context engineering 那边的索引方案要落地，
**就必须有人维护「哪些取过、哪些用过」——那就是账本。**

**两件事不是先后关系，是同一个对象的两个用途。**

---

## 6. 在整个 harness 里的正向作用（逐个环节）

| 环节 | 现在 | 有账本之后 |
|---|---|---|
| `prepare` 检索 | 每轮从零规划，无重复查询记录 | 只查 gap；重复查询可短路 |
| `produce` 续写 | 事实块 `[-40:]` 截断，且每轮平移断缓存 | 索引在前（稳定）+ 这一节要用的逐字在后 |
| `judge` **`material_use`** | 模型判，**25 次里 24 次满分** | **可计算**：已取 M 条里正文用了几条 |
| `judge` **`factual_grounding`** | 模型判，**41% 不达标** | id 级比对 + `fact_sources` 回溯，**确定性** |
| `judge` `beat_coverage` | 只看正文有没有写 | 多一个材料侧问题：这条 beat 对应的主题**取了没有** |
| `revise` | cleanup 轮常常**没有候选**（`harness-mechanism-rethink.md` §2） | 账本里 `state=taken` 而没 `used` 的，就是现成的候选 |
| `best_of` / 停机 | `rank()` 把多维折叠成标量、经常打平 | 覆盖率是一个**客观、可比、不打平**的维度 |
| 缓存 | 前缀每轮断 | append-only |

**最有意思的一条是 `material_use`。** 我在 `harness-evaluators.md` 里写过：
它 25 次 24 次满分，**可能只是因为那些跑里根本没喂材料**，
所以「该不该删这个维度」得等每轮数据。
**有了账本，这个问题当场有答案，不用猜。**

---

## 7. 落地顺序（最小可用优先）

1. **只记不改。** `ToolTrace` 跨轮累积进 `st.bag`，**什么行为都不改**，
   先把三个数看出来：重复查询率、各轴覆盖率、`fresh / facts_new`。
   **一行行为都不改，却是后面全部的前提。**
2. **账本摘要摆进 `prepare` 的 prompt。**
   跟当年把主题树直接摆进去是同一个动作——**不要求，要供给。**
3. **查询级短路**（同一次跑里参数完全相同的调用直接返回上次结果）。
   确定性、零风险、不依赖前两条。
4. **规划的问题改成 gap 形状**（§3）。
5. **覆盖率驱动停机**，取代固定 `tool_iters`。
6. **`material_use` / `factual_grounding` 从模型判改成账本判**（§6）。
7. **索引取代截断**（`harness-context-engineering.md` §7）——
   跟第 2 步共用同一份索引，一起做。

---

## 8. 明确不建议

- **不换 memory engine。** kite 已经把材料结构化成带 id、带主题、带计数的事实了；
  我们缺的从来不是记忆系统，是**一次跑之内的检索状态**。
- **不要让账本变成第二份事实库。** 只存 id + 一行 + 状态。
  存全文就要维护一致性，那是自找的第二个真相来源。
- **不要把覆盖率当成要冲的指标**（§4 那条边界）。
  先看分布，再决定哪个轴、什么阈值值得追问。
- **不要一上来就改停机。** 第 5 步要等第 1 步的数据——
  「连续两次没带回新 id」这个判据听起来合理，但**没量过就是拍的**。
- **不要把账本全文喂给续写那一步。** 它是给**规划**和**判据**用的；
  续写要的是这一节真正要用的那几条的**原文**。

---

## 9. 判据

| 判据 | 现在 | 目标 |
|---|---|---|
| 一次跑里参数完全相同的重复查询占比 | **未测** | 0 |
| 各轴覆盖率（共 N / 已取 M） | **未测**（数就在工具返回里，被扔掉） | 可报，且能指出空白轴 |
| `filter_facts` vs `search_memory` 的使用占比 | **未测**（prompt 劝过，实测六次全走 `search_memory`） | 可报 |
| `factual_grounding` 不达标率 | **41%**（0 分 11 次） | 改成 id 级确定性比对后重新量 |
| `material_use` 满分率 | 25 次 24 次（**说明不了什么**） | 换成「已取 M 条里用了几条」这个可计算的数 |
| cleanup 轮修订候选为空的比例 | **未测** | 账本提供候选后应显著下降 |

---

## 10. 调研：这个机制在文献里叫什么，我漏了什么

第 761 轮的账本是我从原理推的。回头查了一遍，结论是**形状对了，但少了两个信号，
而那两个信号的数据我们库里已经有了**；另外「准」和「全」都有现成的可量定义。

### ① 它有名字：LedgerRAG

> **LedgerRAG**：维护一份**显式的 claim 级证据账本**，用
> **coverage（覆盖）/ temporal validity（时效）/ authority（权威）/ conflict（冲突）**
> 四个信号来控制**检索、刷新和停机**决策。

跟我提的那份对照：

| LedgerRAG 的信号 | 我提了吗 | 我们库里有数据吗 |
|---|---|---|
| coverage | ✅ | ✅ `list_topics` 带条数、`filter_facts` 返回「共 N 条」 |
| **temporal validity** | ❌ **漏了** | ✅ 每条事实都带日期（`_fmt_facts` 已经在显示 `when`/`date`） |
| authority | ❌ 漏了 | 部分（`fact_sources` 能回到来源，但没有权威分级） |
| **conflict** | ❌ **漏了** | ✅ **`kb_conflicts` 表就在库里** |

同一条线上还有 `Stateful Evidence-Driven RAG`（持久的对比式证据池）、
`Agent Memory: Characterization of Stateful Long-Horizon Workloads`。

### ② 我漏掉的那两个，在这个仓里不是假设

**`kb_conflicts` 这张表已经存在**（`store.py:217`），字段是
`new_fact_id` / `old_fact_id` / `status` / `resolution`——
**它记的正是「哪条事实取代了哪条」**。摄入时由 `harness/conflict_confirm.py`
写进去，由 `routers/kb.py` 的冲突收件箱读出来展示。

**而写作 harness 从来不问它。**（全仓 grep：`harness/` 下没有任何一处读 `kb_conflicts`。）

这不是个理论问题。这个项目自己的记忆里就记着那个例子：
**DVT 从 6 月 3 日推迟到 8 月 5 日。** 知识库知道后者取代了前者，
而续写的时候没人问，两条都可能被取出来、都可能被写进正文——
`factual_grounding` 判据要的正是「没有跟事实矛盾的说法」，
**而它自己判不出哪条是旧的。**

**账本该加的两列**：`superseded_by`（来自 `kb_conflicts`）和 `when`（事实日期）。
两者都是零成本的——数据已经在库里，只是没被接进来。

### ③ 「全」有现成的可量定义：sufficient context

`Sufficient Context: A New Lens on RAG`（ICLR 2025，Google）给了一个关键区分：

> **只看「相关性」是量错了东西**——要问的是这些材料**够不够回答这个问题**。

他们训了一个 **sufficient-context autorater** 判「够 / 不够」，
Gemini 1.5 Pro 一例 few-shot 到 **93% 准确率**。而实测发现：
**材料不够的时候，强模型不会弃答，而是直接答错**——
RAG 系统在材料不足时仍有 35–62% 的比例给出答案。

**这条对我们的意义**：`material_use` 判的是「有没有用上材料」（相关性那一档），
**没有任何一维在问「这一节的材料够不够写」。**

而更妙的是——**弃答这件事，这个仓已经有正确形态了**。
`grounding_rules.py:256` 写着：对冲句子该删，正确形态是
「**这里需要补上 XX 的实际记录**」。
**弃答的表达方式早就定好了，缺的是触发它的信号。**
账本的覆盖分母正好就是那个信号。

### ④ 「准」也有现成的可量定义：ALCE 的引用精确率 / 召回率

`ALCE`（*Enabling LLMs to Generate Text with Citations*）把引用质量拆成两个数：

- **Citation Recall**：这句话是不是**完全**被它引的那些材料支撑；
- **Citation Precision**：**每一条**引用是不是真的支撑这句话
  （做法是**留一法**：去掉其中一条，看是否还蕴含）。

人机一致性验证过：Cohen's kappa **0.698 / 0.525**。

对照我们的 `citations_hold`——它现在查的是「正文引的 id **在不在**材料里」，
**那既不是 precision 也不是 recall，只是「存在性」。**

有了账本（id → 原话），这两个数都变得可算。
**但要注意 ALCE 用的是一个专门的 NLI 模型（TRUE，T5-11B 微调）来判蕴含，不是生成器自己。**
——又一次撞上同一条规矩：**别让写的人自己判。**

### ⑤ 反面证据：把「已经有什么」摆给模型看，可能**减少探索**

这条直接打在我的提案上，必须记：

> **注入的上下文会把 agent 锚定到特定解法上**；
> 在它本来会自由探索的场合，这**缩小了搜索空间（有害）**。

锚定效应在 LLM 上被反复证实过（`Anchors in the Machine`、
`Understanding the Anchoring Effect of LLM`）。

**由此得出一条具体的设计决定**（不是加个警告了事）：

> **账本摘要要以「缺口」的形式呈现，不要以「库存」的形式呈现。**
>
> - ❌「已经取到 40 条，覆盖众筹、硬件节点、团队」→ 邀请它见好就收
> - ✅「**定价：18 条，一条都没取**；产品验证：23 条，取了 2 条」→ 邀请它去补

同一份数据，两种写法，效果相反。§3 里那段示例要按这条重写——
**把「已取」压到最小，把「没取」摆到最前。**

### ⑥ 顺带查到一处我们**碰巧做对了**，别改坏

`Anchoring Bias in LLM-as-a-Judge: Prior Scores Compromise Evaluation Independence`
指出：**把上一轮的分数喂给这一轮的打分器，会破坏评判的独立性。**

我们的打分器**看不到上一轮的分数**——`_build_prompt` 只吃 `score_context`，
而那份 context 由 router 组装（spine/beats/分段主题），不含分数。

`loop.py:155` 确实写了 `st.bag["last_scores"]`，
**但全仓没有任何一处读它——是一段死状态。**
（顺带：这行可以删，或者接上 §7 第 1 步的「只记不改」一起落库。）

**这一条要写进注释钉住**：将来谁想「让打分器知道上一轮的分数好做对比」，
这里有现成的反面证据。

### ⑦ 调研之后，§2 的账本形状修正为

```python
ledger = {
  "queries": [ {tool, args, hit, empty} ],
  "axes":    { "topic:定价": {"total": 18, "taken": 0} },        # coverage
  "facts":   { "f_8a3c": {"line": "…", "state": "taken|used|dropped",
                          "when": "2026-03-11",                  # ← 新增：时效
                          "superseded_by": "f_9d21",             # ← 新增：来自 kb_conflicts
                          "why": ""} },
}
```

两个新字段都是**接现成数据**，不是新造。

对应的落地顺序里加一步，插在原来的第 2 步之前：

> **1.5　把 `kb_conflicts` 接进取材那一步**——取到一条被取代的事实时，
> 在账本里标上 `superseded_by`，并把取代它的那条一起带回来。
> **这一步独立于账本的其它部分，可以单独做、单独验**，
> 而且它直接打在 `factual_grounding`（41% 不达标）上。

---

## 参考

本文的机制形状来自 `harness-multiround-retrieval.md` 和
`harness-context-engineering.md` 两份里的调研，来源不重复列。
最直接的三条：

- [S2G-RAG: Structured Sufficiency and Gap Judging for Iterative Retrieval-Augmented QA](https://arxiv.org/pdf/2604.23783) —— gap judging 的形状
- [TASR: Training-Free Adaptive Stopping for Iterative Retrieval](https://arxiv.org/pdf/2606.13814) —— 覆盖率驱动停机
- [SAFE / 长文事实性拆解-核对那条线](https://arxiv.org/abs/2305.14251) —— 「这条值不值得查」的 relevance check

第 10 节的调研来源：

**账本这个形状本身**
- [LedgerRAG: Governance-Driven Agentic Chain of Retrieval for Dynamic Knowledge Scenarios](https://doi.org/10.3390/electronics15071376)
- [Stateful Evidence-Driven Retrieval-Augmented Generation with Iterative Reasoning](https://arxiv.org/pdf/2604.14170)
- [Agent Memory: Characterization and System Implications of Stateful Long-Horizon Workloads](https://arxiv.org/html/2606.06448v1)

**「够不够」的可量定义**
- [Sufficient Context: A New Lens on Retrieval Augmented Generation Systems (ICLR 2025, Google)](https://arxiv.org/abs/2411.06037) · [仓库](https://github.com/hljoren/sufficientcontext) · [Google Research 博客](https://research.google/blog/deeper-insights-into-retrieval-augmented-generation-the-role-of-sufficient-context/)

**「准不准」的可量定义**
- [ALCE: Enabling Large Language Models to Generate Text with Citations](https://arxiv.org/pdf/2305.14627)
- [Learning Fine-Grained Grounded Citations for Attributed LLMs](https://arxiv.org/pdf/2408.04568)
- [Think&Cite: Improving Attributed Text Generation with Self-Guided Tree Search](https://arxiv.org/pdf/2412.14860)

**反面证据：锚定**
- [When Context Hurts: The Crossover Effect of Knowledge Transfer on Multi-Agent Design Exploration](https://arxiv.org/pdf/2605.04361)
- [Anchors in the Machine: Behavioral and Attributional Evidence of Anchoring Bias in LLMs](https://arxiv.org/pdf/2511.05766)
- [Understanding the Anchoring Effect of LLM with Synthetic Data](https://arxiv.org/html/2505.15392v2)
- [Anchoring Bias in LLM-as-a-Judge Systems: Prior Scores Compromise Evaluation Independence](https://arxiv.org/html/2608.25869)
