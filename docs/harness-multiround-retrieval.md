# 多轮的 memory 查询

> 第 760 轮。**调研 + 现状勘查，没改代码。**
>
> 跟 `harness-context-engineering.md` 第 7 节是同一个问题的两端：
> 那边说「别把东西截掉」，这边说「别把同一个东西反复取回来」。

---

## 1. 现状：每一轮都从零开始规划检索

一轮的检索发生在 `hooks/note.py:110` 的 `prepare`：

```python
async def prepare(self, st: State) -> tuple[list[str], ToolTrace]:
    trace = ToolTrace()          # ← 每轮新建
```

**`ToolTrace` 每轮新建，跨轮既不记「查过什么」，也不记「查到过什么」。**

检索规划那次调用（`prompts/note.py:71` `retrieval_plan_user`）拿到的是：

| 给了 | 没给 |
|---|---|
| 笔记标题 | **已经攒下的那些事实** |
| spine / beats | **上几轮发过哪些查询** |
| 当前正文 | **哪些查询查空了** |
| `steer`（上一轮最弱维度的诊断） | |
| 主题树（`list_topics`，40 条） | |
| 这一轮要写哪一节 | |

而同一份 prompt 里**写着这么一句**（`prompts/note.py:87`）：

> 查的材料要针对这一节，**不要再取上几轮已经写过的那些**。

**要求写在文字里，清单没给。**

### 这个坑这个文件自己已经踩过一次

往下十几行就记着（`prompts/note.py:91`）：

> 实测的问题：prompt 里明明写了「不确定就先 `list_topics`」，
> 但**六次检索全是 `search_memory`，一次都没用过主题树**——
> 引导写在文字里，模型还是走最短路径。

他们当时的修法是**把主题树直接摆进 prompt**。
**结论早就得出来了：不要求，要供给。** 只是这条结论没有推广到「已取事实」上。

### 去重发生在付完钱之后

`middleware/facts.py:41` 确实在去重：

```python
fresh = [f for f in st.facts_new if f not in st.facts]
st.facts = (st.facts + fresh)[-st.mode.fact_budget:]      # fact_budget = 40
```

但这是**结果级**去重——查询已经发出去了、工具调用已经花掉了、
结果已经进过一次上下文了，才在这里把重复的丢掉。

### 跟截断叠在一起，会产生「换进换出」

`[-40:]` 从头部丢旧的。于是：

```
第 3 轮：事实 A 被挤出去
第 5 轮：规划器（不知道 A 曾经在过）又查了一次 → A 回来
       → 又挤掉另一条
第 7 轮：……
```

**同一条事实可以被反复换进换出**，每一次都花一次工具调用、
每一次都让缓存前缀断一次（`harness-context-engineering.md` 第 2 节 ①）。

*这不是两个 bug，是同一个缺口的两个症状：**回路没有「我已经有什么」这份状态**。*

---

## 2. 行业把这件事拆成三个独立的问题

我们现在是「每轮无条件查一次、固定几个来回、查完就忘」。
文献里这是三个各自有解的问题。

### ① 何时查

- **FLARE**：生成置信度掉到阈值以下才触发检索。
- **Self-RAG**：训练模型自己发 `retrieve` / `critique` 特殊 token。
- **Adaptive-RAG**：用一个分类器预测**要不要查、要查几轮**。

→ 我们：**每轮无条件查一次**（只有 `cleanup_only` 轮跳过）。

### ② 查什么：从「该查什么」改成「还缺什么」

**`S2G-RAG`（Structured Sufficiency and Gap Judging）** 是这条线上形状最贴我们的：
每一轮判两件事——**够不够**、**还缺什么**；
并且**显式维护一份「已取文档」清单，据此避免重复检索**，
新一轮只针对识别出来的 gap 去查。

**这正是我们缺的那块状态。** 我们的规划 prompt 问的是
「这一轮该查什么」，而它该问的是「**已经有这些了，还缺什么**」。

同一条线上的其它形状：`FAIR-RAG`（faithful adaptive iterative refinement）、
`DualRAG`（推理与检索双过程）、`A-RAG`（分层检索接口）。

### ③ 何时停

`TASR`（training-free adaptive stopping）、`Adaptive Stopping for Multi-Turn
LLM Reasoning`：**不用固定轮数**，按状态决定停不停。

→ 我们：固定 `tool_iters`（1–4），由策略器按「上一轮用没用工具」加减
（`policy.py`）——**而「上一轮没用工具」既可能是"不需要查"，
也可能是"它懒得查"**，两者被当成同一个信号。

---

## 3. 改法（都不引框架，都是小改）

按依赖排：

1. **把「已取事实」做成索引，摆进检索规划 prompt。**
   不是全文，是 **id + 一行**。跟当年把主题树直接摆进去是同一个动作，
   而且跟 `harness-context-engineering.md` 第 7 节那个「索引 + 按需读取」
   **是同一份索引**——做一次，两处用。
2. **把「已发查询」记进 `st.bag` 并跨轮累积，也摆进 prompt。**
   `trace.calls` 里本来就有 `(工具名, 参数, 结果)`，
   现在只是每轮丢掉。攒起来，附上「这条查回来几条 / 查空了」。
3. **把规划的问题改写成 gap judging 的形状**（S2G-RAG）：
   「下面是已经取到的材料摘要 + 已经查过的查询；
   **这一节还缺什么？只查缺的那部分。**」
4. **工具层加一层查询级短路**：同一次跑里参数**完全相同**的
   `search_memory` / `filter_facts`，直接返回上次结果，
   不打后端、也不再往上下文里塞一遍。
   **这一条是确定性的、零风险的**，而且不依赖前三条，可以最先做。
5. **取消 `[-40:]`**（第 7 节已经说了）。它跟 1–3 是一套：
   有了索引就不需要靠丢弃来控长度，「换进换出」也就消失了。

**第 4 条最先做**（纯代码、可单测、立刻能量出重复查询率），
**第 1 条跟第 7 节的索引方案合并做**。

---

## 4. 明确不建议

- **不要引入 Mem0 / Zep / Letta / A-Mem 这类记忆框架。**
  它们解决的是「**把对话历史变成记忆**」那一步——抽取、合并、消解时序冲突。
  **我们没有那一步**：`memoket_kite` 已经把材料结构化成带 id 的事实了。
  我们缺的不是记忆系统，是**一次跑之内的检索状态**。
- **不要拿 LoCoMo 那类基准来选型。** 2026 年的评估里它已经饱和到
  「直接把上下文塞满就能拿不错的分」，作为架构指标已经失效；
  而且各家在同一个基准上的复现结果互相打架
  （Zep 复现自己的分是 75.14%，Mem0 论文里给它记的是 65.99%）。
- **不要上 Self-RAG 那种需要训练特殊 token 的方案。** 我们走的是外部 API。
- **不要因为「每轮都查」浪费就干脆少查。** FLARE / Adaptive-RAG 说的是
  **按信号决定**，不是**减少**。我们现在恰恰相反——
  策略器已经在按「上一轮没用工具」扣预算了，而那个信号是脏的
  （`policy.py` 自己的注释就记着：把"它诚实回答这段不用查"当成了"不需要检索能力"）。

---

## 5. 判据（现在一个都测不出来，这本身就是第一个问题）

| 判据 | 现在 | 目标 |
|---|---|---|
| 一次跑里参数完全相同的重复查询占比 | **未测** | 0 |
| 第 2 轮起 `fresh / facts_new`（这一轮查回来的里有多少是新的） | **未测** | 有数，并随轮次可解释地下降 |
| 同一条事实被换出后又换回的次数 | **未测** | 0 |
| 查空的查询被重复发出的次数 | **未测** | 0 |

前三条都能从 `trace.calls` 直接算出来——**只要别每轮把它丢掉。**

---

## 来源

**多轮 / 迭代检索**
- [S2G-RAG: Structured Sufficiency and Gap Judging for Iterative Retrieval-Augmented QA](https://arxiv.org/pdf/2604.23783)
- [FAIR-RAG: Faithful Adaptive Iterative Refinement for RAG](https://arxiv.org/pdf/2510.22344)
- [TASR: Training-Free Adaptive Stopping for Iterative Retrieval](https://arxiv.org/pdf/2606.13814)
- [Adaptive Stopping for Multi-Turn LLM Reasoning](https://arxiv.org/pdf/2604.01413)
- [DualRAG: A Dual-Process Approach to Integrate Reasoning and Retrieval](https://arxiv.org/pdf/2504.18243)
- [A-RAG: Scaling Agentic RAG via Hierarchical Retrieval Interfaces](https://arxiv.org/html/2602.03442v1)
- [RAG and Beyond: A Comprehensive Survey on How to Make your LLMs use External Data More Wisely](https://arxiv.org/pdf/2409.14924)

**记忆系统（我们明确不走这条，列出来是为了说明为什么）**
- [Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory](https://arxiv.org/pdf/2504.19413)
- [Is Mem0 Really SOTA in Agent Memory?（Zep 的复现反驳）](https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/)
- [State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- [AMA-Bench: Evaluating Long-Horizon Memory for Agentic Applications](https://arxiv.org/pdf/2602.22769)
