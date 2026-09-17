# 行业解法：每一个 harness 的 evaluator 分别属于哪条线

> 第 757 轮。**调研文档，没改代码。**
>
> 前一份（`harness-evaluators.md`）是把我们自己的八个 evaluator 拆开看。
> 这一份跳出去：**八个功能在文献里分属四条完全不同的线**，各有各的成熟解法。
> 把它们当成同一种东西来做，是我们现在最大的一处浪费。

---

## 0. 一句话结论

| 我们的功能 | 文献里属于 | 那条线的解法核心 | 我们现在 |
|---|---|---|---|
| 续写整篇 / 分段写作 | 长文·细粒度评测 | **错误 span + 严重度**，不是整篇一个分 | 整篇一个分，没有定位 |
| 数据可视化 / 智能插图 | NL2VIS | **执行 + 一组异构 checker**，几乎不用打分模型 | 一半判据 + 一半打分模型 |
| 生成表格 | 结构化产出对账 | **跟源数据逐格 diff** | 交给看不见源表的打分模型 |
| 按指令生成 / 改写选区 | 指令遵循 | **从这条指令现场生成 checklist** | 3 条固定维度 |
| 幻灯片 | 结构 checklist | 确定性、不拦落库 | **已经是对的形态** |

**最刺眼的一条**：图表和表格这两类**本来有执行 oracle**
（图能不能渲染、数字能不能对上源表），而我们把它们交给了一个
连源表都没给它看的打分模型（见 `harness-evaluators.md` 问题一）。

---

## 1. 长文那两个（续写整篇 · 分段写作）

### 文献线：从「一个分数」走向「错误 span + 严重度」

机器翻译这条线走得最远，已经完成了这次迁移：**MQM** 框架把质量评测定义成
「标出错误片段 + 标严重度（minor / major / critical）」，
`xCOMET`（TACL 2024）把**句级打分和错误 span 检测合成一个模型**，
在三种评测上都是 SOTA。`AutoMQM` 则是直接提示 LLM 按 MQM 标错误。

摘要这条线上，**FineSurE**（ACL 2024）做的是同一件事：
逐句判有没有事实错误，**零样本**就能做到与人的句级判断
balanced accuracy **86.4%**，*「outperforms strong baselines fine-tuned for
error localization, despite not being trained on any error localization data」*。

**`LLMRefine`** 把这一步接到改写上：细粒度可执行反馈 → 定点修改。

### 这条线最该被我们听进去的一句

自我纠错的综述和 Huang et al. 那篇负面结果指向同一个结论：

> LLM 在**错误被明确指出**时修得很好，
> 但**自主的错误检测和定位**做不到。

这正是 `harness-mechanism-rethink.md` 第二节那条因果链的理论解释——
`Repair` 决定「只修不写」是对的，但没人告诉修订工哪里坏了，于是空转到停机。

### 可以直接搬的

1. **判据的产物从「维度 + 一句诊断」升级成「span + 严重度」。**
   `revise` 这一步本来就是按锚点改的（`apply_revision` 的 op 是
   insert / delete / replace + anchor），**执行器早就是 span 级的**，
   只有评判还停在整篇级。两头对齐，中间那条断口就没了。
2. **FineSurE 的三分法可以照搬**：faithfulness（每句有没有事实错）/
   completeness（关键事实有没有覆盖）/ conciseness（有没有冗余）——
   跟我们的 `factual_grounding` / `beat_coverage` / `non_repetition` 一一对应，
   区别只在**它们是逐句判的**。

### 明确不能照搬的

`AutoMQM` 的已知问题是 *「tend to over-predict errors and have overall low
span precision」*——**LLM 标 span 会过度预测**。
这跟我们自己的规矩正好撞上（「误伤比漏报更贵」）。
所以 span 要么由**确定性探测器**给（查重、数字核对），
要么给出来之后必须再过一道机械验证，不能直接拿去删。

---

## 2. 图表那两个（数据可视化 · 智能插图）

### 文献线：NL2VIS，**有执行 oracle**

`VisEval`（IEEE VIS 2024 / Microsoft Research）是这条线的代表。
它的评测方法不是打分模型，是
*「systematically scanning for potential issues with a number of
heterogeneous checkers」*，分三档：**validity / legality / readability**。

它实测查出来的问题类型很说明问题：代码跑不起来、
**把「sum of Tonnage」错映射到 y 轴（应该是 count）**、
图例缺失、没按要求排序、图例跑到画布外、溢出。

**这些全都是可以算出来的，一条都不需要模型打分。**

### 我们的位置

我们已经有一半了：`charts_from_tools` / `no_fake_charts` 是 validity 档，
`check-mermaid-grammar.mts` 那个门禁脚本是 legality 档的一部分。

**缺的是 readability 档，和最要命的 data 档**：
`data_grounding` 的判据原文是「每个数字都能追到笔记里的表或工具结果」——
**这是一次精确比对，不是一次判断**。而现在它交给了一个
**连那张表都没给它看**的打分模型，实测 2/2 满分。

### 可以直接搬的

- `render_chart` 的输入就是工具算出来的数据。
  **把那份数据跟图里出现的数字做一次精确 diff**，对不上直接判据打回。
  `numbers_from_tools` 这一维可以整条从打分模型手里拿走。
- readability 档挑几条能算的：图例有没有、类别数是不是多到读不出来、
  轴标签有没有。`chart_column` 已经会拒绝没信息量的图，是同一个路子。

---

## 3. 表格（生成表格）

同属「结构化产出对账」。`table_validity`（列数对不对）已经是确定性的，
但 `data_grounding`（每个格子能不能追到源）同样是**逐格 diff**，
现在也交给了看不见源表的打分模型。

**这个模式的三条维度里有两条可以完全确定性化**，
剩下 `fits_context` 才真的需要模型——而那一条现在恰恰缺上下文。

---

## 4. 指令那两个（按指令生成 · 改写选区）

### 文献线：可验证指令 + 现场生成 checklist

`IFEval`（Google）把指令拆成**可程序验证的约束**（格式、长度、关键词），
25 类、约 500 条 prompt，区分 instruction-level 和 prompt-level 准确率、
strict 和 loose 两档。

`TICK` / `RLCF`（Apple + CMU，NeurIPS 2025，
*Checklists Are Better Than Reward Models*）再往前一步：
**从用户这条指令本身自动生成一份 instruction-specific checklist**，
逐条判是否满足（AI judge + 专用验证程序两路），
`STICK` 用它做自我改写和 Best-of-N。

### 我们的位置，以及这条线上最硬的一个实测

`prompt` 和 `custom` 两个模式现在用的是 **3 条固定维度**
（`follows_prompt` / `fits_context` / `no_fabrication`）——
而**用户明明刚刚打了一条具体指令进来**。

`Rubrics as Rewards`（ICLR 2026）的消融正好打在这里：

> **RaR-Predefined**（对所有 prompt 用同一份通用 rubric）**明显更差**，
> 因为通用判据抓不住这一条 prompt 特有的要求和典型失败方式；
> 有效的做法是 **instance-specific rubric synthesis**。

我们八个功能**全部**是 `RaR-Predefined` 那一档。

### 可以直接搬的

对 `prompt` / `custom` 这两个模式：**跑之前先从用户那条指令生成一份
本次专属的 checklist**（「他要求写三段」「他点名要提到 X」），
逐条二元判。这两个模式的指令天然短、天然具体，是最容易见效的入口。

---

## 5. 幻灯片

`slides` 已经是这条线的正确形态：全确定性、零模型调用、**不拦着落库**、
结果跟产物一起显示给用户。文献里对应的是 structural checklist 那一类。
**不建议改，建议反过来当模板**——
`magic-tap` / `journey/report` 这两个现在没有 evaluator 的，
最可能适合的就是这个形态。

---

## 6. 横跨所有 harness 的四条

这四条不分功能，哪个 harness 都成立。

### ① 固定 rubric 不如每次合成（RaR / TICK）

见第 4 节。我们 25 个维度全是写死的。
**但不要一刀切**：长文那两个模式有 spine/beats，本来就带着这篇笔记自己的
结构，合成 rubric 的原料是现成的；block 那六个更适合从用户指令合成。

### ② 二元 pass/fail 比多档分数更可靠（Checklists / 业界实践）

我们用的是 0/1/2 三档。而这条线上的实测和实践都指向二元：
Hamel Husain 跨 30+ 家公司的经验是
*「domain expert pass/fail judgments correlate better with actual quality
than granular numeric scores」*，建议**先二元再考虑分档**——
因为 pass/fail 逼你先定义清楚「什么叫可以接受」。

我们踩过的坑正好是这个的镜像：`_NON_REPETITION` 九批 2160 次实测
**稳在 1.3 下不来**——中间那档「1 分」吸收了所有说不清的情况，
既不推动修改也不放行。

### ③ judge 必须先跟人对齐，而且要**按维度**看一致率

业界的门槛很具体：**75–90%** 与专家标注一致才能放到无标注数据上跑；
低于 75% 引入的噪声比消除的多，高于 90% 要怀疑 rubric 太粗。
而且——

> 整体一致率会掩盖真正要紧的方差：一个 judge 可能整体 80% 一致，
> 在**某一个维度上只有 40%**。

我们**从来没做过这一步**。这就是 `harness-mechanism-rethink.md` 第五节
「这个回路没有 ground truth」的行业版本，而且它给了一个明确的数值门槛。

### ④ 自评偏见：写作和打分同一个模型，是最坏的那种配置

2026 年的实测把这件事钉死了：**即使 rubric 完全客观、可程序验证**（IFEval），
judge 在评自己的输出时，把**实际不满足**的条目错判成「满足」的概率
**高出最多 50%**；HealthBench 那种主观 rubric 上偏差最多 **10 分**。

缓解办法是**多 judge 集成**，但*「without fully eliminating it」*。

我们 `checks/__init__.py` 开头那句自白（*「the scorer and the thing being
scored are the same local model」*）说的就是这件事——
而且我们只有**一个模型槽**，连换一个 judge 的配置位都没有。

### ⑤ 多目标不要折叠成标量（GEPA）

`GEPA` 维持一条 **Pareto 前沿**（在不同任务子集上各自最优的候选），
而不是把多维分数压成一个数，理由是避免过早收敛。

我们的 `State.rank()` 正是那个折叠，而它的失败已经实拍过：
第 602 轮四轮全被判据打回，`rank()` 一律 `(0, 0.0)`，
**best 从头到尾钉在第 1 轮**，后三轮的修订全丢。

### 顺带：我们其实已经在手动跑 GEPA

GEPA 的循环是「读执行轨迹 → LLM 诊断失败 → 改写 prompt → Pareto 选择」，
它把自然语言反馈叫作 *「the text-optimization analogue of a gradient」*。

而我们改 `_NON_REPETITION` 那一次：读产出 → 发现判据在罚正常写法 →
改写 guidance → 九批 2160 次实测验证——**这就是 GEPA，只是由人执行，
一轮要花几天。** 这不是说该换成自动的（判据的措辞涉及产品判断），
但它说明：**我们缺的不是方法，是把这条循环的数据留下来。**

---

## 7. 建议的落地顺序（不改代码，供拍板）

按「有 oracle 的先做」排——这是这次调研最强的一条启发：

1. **图表 / 表格的 `data_grounding` 和 `numbers_from_tools` 确定性化**。
   数据就在工具返回里，做一次精确 diff。**三个模式、四条维度**
   从打分模型手里拿走，立刻不再有「看不见源表却给 2 分」这种事。
2. **`prompt` / `custom` 改成从用户指令现场生成 checklist**（TICK 形态）。
   这两个模式的指令短而具体，是 instance-specific rubric 最容易见效的入口。
3. **长文那两个补 span 级探测器**（`harness-mechanism-rethink.md` 第 1.1 条），
   与 `revise` 的锚点级执行器对齐。span 必须过机械验证——
   AutoMQM 的教训是 LLM 标 span 会过度预测。
4. **开始攒 judge-vs-人 的一致率数据**，目标先做到能按维度报一致率。
   门槛 75–90%。这一条最慢，所以最早开始。

**不建议现在做的**：
- 不要急着上多 judge 集成（成本翻倍，而我们连单 judge 的一致率都没测过）。
- 不要把三档改成二元——**先按维度量一致率**，用数据决定哪几维该二元化
  （`non_repetition` 那个「稳在 1.3」的历史强烈提示它该二元，但别凭这一条就全改）。
- 不要引入任何一个上面提到的框架当依赖。这里要的是**它们的判据形态**，
  不是它们的运行时。

---

## 来源

**长文 / 细粒度评测**
- [xCOMET: Transparent Machine Translation Evaluation through Fine-grained Error Detection (TACL 2024)](https://aclanthology.org/2024.tacl-1.54/)
- [FineSurE: Fine-grained Summarization Evaluation using LLMs (ACL 2024)](https://arxiv.org/pdf/2407.00908)
- [The Devil is in the Errors: Leveraging LLMs for Fine-grained MT Evaluation (AutoMQM)](https://arxiv.org/pdf/2308.07286)
- [LLMRefine: Pinpointing and Refining LLMs via Fine-Grained Actionable Feedback](https://arxiv.org/pdf/2311.09336)
- [WMT25 Fine-grained error span detection](https://www2.statmt.org/wmt25/mteval-subtask2.html)

**自我纠错的边界**
- [Large Language Models Cannot Self-Correct Reasoning Yet (Huang et al.)](https://arxiv.org/abs/2310.01798)
- [When Can LLMs Actually Correct Their Own Mistakes? A Critical Survey](https://arxiv.org/html/2406.01297v3)

**图表 / 可视化**
- [VisEval: A Benchmark for Data Visualization in the Era of LLMs (IEEE VIS 2024)](https://arxiv.org/abs/2407.00981)

**指令遵循 / checklist / rubric**
- [IFEval: Instruction-Following Evaluation for LLMs](https://arxiv.org/abs/2311.07911)
- [Checklists Are Better Than Reward Models For Aligning Language Models (TICK/RLCF, NeurIPS 2025)](https://arxiv.org/abs/2507.18624)
- [Rubrics as Rewards: RL Beyond Verifiable Domains (ICLR 2026)](https://arxiv.org/abs/2507.17746)
- [OpenRubrics: Scalable Synthetic Rubric Generation](https://arxiv.org/pdf/2510.07743)
- [Rubrics Survey（RUC-NLPIR 整理的综述仓）](https://github.com/RUC-NLPIR/Rubrics_Survey)

**judge 的偏见与对齐**
- [Self-Preference Bias in Rubric-Based Evaluation of LLMs](https://arxiv.org/abs/2604.06996)
- [Quantifying and Mitigating Self-Preference Bias of LLM Judges](https://arxiv.org/html/2604.22891v4)
- [Using LLM-as-a-Judge For Evaluation: A Complete Guide（Hamel Husain）](https://hamel.dev/blog/posts/llm-judge/)
- [How to align LLM judge with human labels（Evidently AI）](https://www.evidentlyai.com/blog/how-to-align-llm-judge-with-human-labels)

**优化器 / 多目标**
- [GEPA: Reflective Prompt Evolution](https://github.com/gepa-ai/gepa)
- [DSPy](https://github.com/stanfordnlp/dspy)
