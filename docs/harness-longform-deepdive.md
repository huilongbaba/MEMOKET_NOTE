# 深入：续写整篇 / 分段写作

> 第 758 轮。**调研文档，没改代码。**
>
> 前三份（`harness-effect-plan` / `harness-mechanism-rethink` /
> `harness-evaluator-industry`）把八个功能一起看。这一份只看长文那两个。
>
> 单独拿出来的理由是数据给的：**它们占了 91% 的模型调用**
> （`note-harness/run` 417 次 + `writing-plan/run` 471 次 / 共 980），
> 而且**它们是唯一会「越跑越差」的两个**（三篇笔记分数单调下滑）。

---

## 0. 一句话

长文这条线上，文献把写作拆成**四段**，我们缺了**其中一段**；
而我们**唯一具备的那个执行器（追加）恰好会触发一个已知的自我强化效应**；
**评判那一端跟「长」有关的三个偏差，全都对我们不利。**

---

## 1. 生成这一端：四段式，我们缺第三段

`Re3`（Berkeley，EMNLP 2022）把长文生成拆成四个模块，后续工作基本沿用：

| Re3 | 做什么 | 我们对应的 |
|---|---|---|
| **Plan** | 把前提扩成设定 + 大纲 | `compose/skeleton`（spine + beats） |
| **Draft** | 递归重提示，每步动态重建 prompt，选择性带入计划和已写内容 | `hooks/note.produce` + `Compact` |
| **Rewrite** | **对同一个位置生成多个续写候选，重排选一个** | **没有** |
| **Edit** | 对选中的那个候选做事实一致性编辑 | `middleware/revise` |

**缺的是 Rewrite。** 而这一段正是 Re3 拿到收益的地方：
情节连贯性最高 **+14%**、与前提的相关性 **+20%**。

### 这跟我们的 `best_of` 不是一回事

`middleware/best_of.py` 挑的是**第几轮**。而长文模式下 `produce` 是追加
（`types.py:68`），所以**第 N+1 轮的正文包含第 N 轮的正文**——
轮与轮之间是**前缀嵌套**，挑一轮等于「决定在哪儿停」，
只能扔掉工作，不可能在同一位置比较两种写法。

Re3 的 Rewrite 是**同一位置的平行候选 + 重排**，那才是真正的 best-of-N。

*（这一条跟 `harness-mechanism-rethink.md` 第六节是同一件事，
但那边是我自己推的，这边是文献里已经做过并量过收益的。）*

### 其余三项，各有一条可搬的

- **DOC**（Berkeley）在 Re3 之上把大纲**细化成层级**，并且用一个
  **token 级控制器**（FUDGE 的改造）全程控制，而不是只靠开头的 prompt
  或者事后拒绝采样。人工标注上情节连贯、大纲相关度、甚至趣味性都**大幅**高于 Re3。
  → 对我们：`beats` 现在是**扁平的一串**，没有层级，也没有任何全程控制。
- **AgentWrite / LongWriter**：计划里**给每一段定字数预算**，再逐段写。
  → 对我们：`section_coverage`（「只开了个头就收尾」）现在全靠模型判断，
  而**字数预算是可以确定性检查的**。
- **STORM**（Stanford）把力气花在**预写作**：多视角提问建大纲。
  拿 FreshWiki 和资深维基编辑评，**organized +25%、coverage +10%**。

### 由此引出这两个 harness 上最容易被忽略的一件事

**`skeleton`（生成 spine/beats）没有任何 evaluator**（`harness-evaluators.md` 问题四）。

而 `spine_fidelity` 恰恰是**最不容易失败的维度**——实测 13 次里只有 2 次不达标，
一次 0 分都没有。放在 STORM 的结论旁边，这个数字的读法变了：

> 不是「我们扣题扣得好」，而是**「对着一个从没被验过的计划打分，太容易满足」**。

计划错了，`spine_fidelity` 和 `beat_coverage` 可以双双满分，而笔记是坏的。
**整个闭环最上游的那一步，是唯一一个没有闭环的。**

---

## 2. 退化这一端：追加会触发一个已知的自我强化效应

我们测到的现象（`harness-effect-plan.md` ③④）：三篇笔记分数单调下滑，
而正文里段内重复占到 **42.9%**。

文献对这个现象有名字和机制——**self-reinforcement effect**：

> **重复一句话的概率，随着历史中已出现的重复次数而上升**；
> 初始概率越高的句子，自我强化越明显。

（Apple / *Learning to Break the Loop*；`Penalty Decoding` 等后续工作同源。）

### 两个直接的推论

**推论一：没删掉的重复不是中性的，它会让下一轮更可能重复。**

我们的回路每轮把**不断变长的正文自己**喂回去当上下文。
一处重复留在里面 → 下一轮更可能再重复 → 复利。
这把「段内查重」从「页面读起来好一点」升级成
**「切断一个正反馈回路」**，优先级完全不同。

**推论二：句级查重的阈值，有一个现成的校准基线。**

同一篇论文给了这个数：**人类语料里连续的句级重复只有 0.02%**
（Wikitext-103）。

这对我们那条「误伤比漏报更贵」的规矩是个重要修正：
**真人几乎不重复句子，所以句级近似重复检测的误伤空间比想象中小得多。**
（注意边界：这说的是**连续**重复；我们要抓的段内重复也是近距离的，适用。）

---

## 3. 评判这一端：三个跟「长」有关的偏差，全都对我们不利

我们的打分器**每一轮读整篇**（`loop.py:238` `content=st.content`），
而这篇东西在一轮轮变长。

### ① lost in the middle

长上下文里模型对**开头和结尾**注意得好，**中间**明显更差，
实测准确率掉 **30%+**（注意力稀释 + 位置偏置）。

而我们的正文结构恰好是：第 1 轮写的开头、第 N 轮写的结尾、
**中间夹着第 2–3 轮累积的重复**——
**判据最该看的地方，正是打分器最看不清的地方。**

### ② length bias

LLM 当评委时**偏好更长的回答**。

我们每一轮都在变长。所以：**我们测到的分数下降，很可能低估了真实的退化**
——分数是在一个偏向「更长 = 更好」的尺子上量出来的，
而它仍然在掉。这条不是坏消息里的坏消息，是**让已有证据更强的一条**。

### ③ 长文生成本身就有已知的退化模式

`HelloBench` 的实测结论：多数 LLM 写不过 4000 词，
而能写长的那些「存在**严重重复和质量退化**」。
我们不是撞上了一个特例。

### 由此得到一条设计判断

> **打分不该每一轮都读整篇。**

至少三种可选形态（都不是我拍的，都是上面三条推出来的）：
- 按**小节**判，而不是整篇判——把长上下文切短，避开 lost-in-the-middle；
- 判**增量**（这一轮写的），整篇只在**收尾**判一次；
- 内在质量那几维交给**位置级探测器**（`harness-mechanism-rethink.md` 第二节），
  打分模型只判它擅长的语义部分。

**现状是最坏的一种**：每轮全文、单次调用、三档分数。

---

## 4. 长文的评测该长什么样：HelloEval

`HelloBench` 配套的评测方法 `HelloEval` 是**两阶段、人对齐**的：
LLM-as-a-judge **加上一套 checklist——每个样本配 4–6 条二元（yes/no）问题**，
在他们的比较里**与人的相关性最高**。

这一条很要紧，因为它让前面三条独立的线在**长文这个具体任务上合流了**：

| 线 | 主张 | 出处 |
|---|---|---|
| checklist 线 | **二元**比多档可靠 | `Checklists Are Better Than Reward Models`、业界实践 |
| instance-specific 线 | 判据要**按这一条输入现场生成** | `RaR` / `TICK` / `WritingBench` |
| 长文评测线 | 长文上**二元 checklist + LLM judge** 与人相关性最高 | **`HelloEval`** |

我们两个长文 harness 现在是：**固定判据 + 三档分数 + 每轮全文**。
**三条都在对面。**

*（第 8 节②记过的那个不一致——WritingBench 用 10 分制——
在长文这个任务上，HelloEval 这条证据是站在二元一边的。）*

---

## 5. 对这两个 harness 的具体建议

按「证据强度 × 改动小」排。**都不改 `loop.py`。**

### 建议一：句级查重，并且把它的理由改写

已经在 `harness-mechanism-rethink.md` 第 1.1 条里了，这次调研给它加了两样：
- **理由升级**：不是「读起来好一点」，是**切断自我强化的正反馈**（第 2 节）。
- **阈值有基线了**：人类语料连续句级重复 **0.02%**——
  先在我们 18 篇真产出上量分布，拿这个数当「正常写作应该是什么样」的参照。

### 建议二：给 `skeleton` 配一个 evaluator（第 1 节）

这是**最上游、也是唯一没有闭环的一步**，而 STORM 的实测说预写作阶段
直接决定 organized / coverage。

形态建议照 `slides` 那种：**确定性判据、不拦着落库、结果跟产物一起显示**
（`harness-evaluator-industry.md` 第 5 节）。能机械判的比想象的多：
beats 之间有没有重复主题、beats 覆不覆盖标题点到的面、条数是否合理、
spine 是不是一个真的张力（有对立面）而不是一个话题名。

### 建议三：判据产物从「整篇一个分」改成「小节一个分」

第 3 节那三条偏差的共同解法。对 `section` harness 尤其自然——
**它本来就是按分段跑的**，却仍然对整篇打分。

### 建议四：`section_coverage` 加一个字数预算（AgentWrite）

「只开了个头就收尾」现在全靠模型判断，实测 11 次里 4 次不达标。
计划那一步给每个分段一个目标区间，就能先做一次确定性判断，
模型只判「写到的东西够不够具体」。

### 建议五：把 `beat_coverage` / `non_repetition` / `section_coverage`
### 从三档改成二元 checklist（HelloEval）

**但要先按维度量一致率**（`harness-evaluator-industry.md` 第 6 节③），
不要因为这一条证据就全改。
`_NON_REPETITION` 那个「九批 2160 次稳在 1.3」的历史，是最强的候选。

### 建议六（大，放最后）：同位置多候选 + 重排（Re3 的 Rewrite）

这是真正补上缺的那一段，但**它会让每轮的写作调用翻 N 倍**。
建议：**先不做**，等建议一到五落地、每轮分数落库之后，
拿数据判断「一轮的写作值不值得花 2–3 倍」。

---

## 6. 明确不建议

- **不要上 DOC 那种 token 级控制器。** 那是解码期的干预，
  需要对解码过程的控制权——我们走的是 OpenAI 兼容的 HTTP 接口，做不到；
  硬做只会变成又一层拒绝采样。
- **不要为了「写得更长」优化。** LongWriter 那条线解决的是
  「模型写不出 4000 词」，而我们的问题**恰好相反**：
  写得太长、而且越长越差。**同一条线上的工作，目标跟我们是反的。**
- **不要把 `skeleton` 也做成多轮闭环。** 它一次调用、输出很短，
  配确定性判据就够；给它上闭环是在一个没有证据的地方加复杂度。
- **不要因为 length bias 就给短的加分。** 那是拿一个偏差去抵另一个偏差，
  结果不可归因。正确的做法是**别让打分器每轮吞整篇**（第 3 节）。

---

## 7. 改完怎么算有效

| 判据 | 现在 | 目标 |
|---|---|---|
| 段内重复字占比（18 篇真产出） | 最差 **42.9%** | 接近人类语料基线（连续句级重复 0.02%）的量级 |
| 反复跑同一篇，分数单调下滑 | **3/6** | 0/6 |
| `spine_fidelity` 不达标率 | 2/13（**太低，说明判得太松**） | 先给 skeleton 配判据，再看这个数会不会变正常 |
| 打分调用的输入长度 | 整篇，随轮次增长 | 按小节，**不随轮次增长** |
| 二元化的维度与人的一致率 | **没测过** | 先能按维度报出来 |

---

## 来源（本篇新增）

**长文生成架构**
- [Re3: Generating Longer Stories With Recursive Reprompting and Revision](https://arxiv.org/abs/2210.06774)
- [DOC: Improving Long Story Coherence With Detailed Outline Control](https://arxiv.org/html/2212.10077v1)
- [LongWriter / AgentWrite: Unleashing 10,000+ Word Generation](https://arxiv.org/pdf/2408.07055)
- [STORM: Assisting in Writing Wikipedia-like Articles From Scratch](https://storm-project.stanford.edu/research/storm/)

**长文评测**
- [HelloBench / HelloEval: Evaluating Long Text Generation Capabilities](https://arxiv.org/abs/2409.16191) · [仓库](https://github.com/Quehry/HelloBench)
- [ProxyQA: An Alternative Framework for Evaluating Long-Form Text Generation](https://www.semanticscholar.org/paper/d891face4565ef3970c1a0965d8126456651f81e)
- [Suri: Multi-constraint Instruction Following for Long-form Text Generation](https://arxiv.org/pdf/2406.19371)

**重复与退化**
- [Learning to Break the Loop: Analyzing and Mitigating Repetitions（Apple）](https://machinelearning.apple.com/research/analyzing-mitigating-repetitions)
- [Penalty Decoding: Well Suppress the Self-Reinforcement Effect](https://arxiv.org/pdf/2310.14971)
- [Rethinking Repetition Problems of LLMs in Code Generation (ACL 2025)](https://aclanthology.org/2025.acl-long.48/)

**长上下文对评判的影响**
- [How Does Response Length Affect Long-Form Factuality](https://arxiv.org/pdf/2505.23295)
- [Context Discipline and Performance Correlation](https://arxiv.org/html/2601.11564v1)
- [LooGLE v2: Are LLMs Ready for Real World Long Dependency Challenges?](https://arxiv.org/pdf/2510.22548)
