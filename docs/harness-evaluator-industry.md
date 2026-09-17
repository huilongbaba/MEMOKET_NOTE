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

## 8. 第二批（再查一轮，四条比第一批更直接）

### ① 长文那两个：`factual_grounding` 有成熟解法，而且我们的条件比论文里还好

这是我们**第一大阻塞项**（41% 不达标、11 次 0 分），而这条线已经很成熟，
统称 **decompose-then-verify**：把长文拆成**原子命题**，逐条去对来源。

| 工作 | 做法 |
|---|---|
| **FActScore** | 最早提出按原子命题查长文；拆成「每条只含一个信息」的短句，逐条对 Wikipedia，**被支持的比例**就是分数 |
| **SAFE** | 三步：抽命题 → **改写以消解指代不清** → **相关性检查：这条值不值得查** |
| **VeriScore** | 只抽**可验证**的命题；滑动窗口给抽取带上下文 |
| **Claimify / DnDScore** | 从三个维度评拆解本身：蕴含、去语境化、覆盖 |

**我们的条件比这些论文好**：它们要去 Google 搜证据，
而我们的来源是**一个封闭的本地知识库**，就在手边、一次跑里已经检索过了。

更妙的是 SAFE 的第三步「相关性检查」，跟我们**吃过亏才写进 guidance 的那条规矩
是同一件事**——`_FACTUAL_GROUNDING` 里写着「检索到的事实没被全部用上，
明确不算不足」，因为为此扣过分之后，下一轮正文里就「引入了大量未在知识库中
出现的具体日期与人物」。**论文把它作为流水线的一个显式步骤，我们把它塞在
一段 guidance 文字里指望模型自觉。**

**反面证据要一起记**：`Decomposition Dilemmas` 这篇专门在问
拆解到底是帮忙还是添乱——拆得太碎会丢语境、制造无法验证的碎片。
所以**拆解粒度本身是个要量的参数**，不是拿来就用。

### ② WritingBench：跟我们任务最接近的一个，而它两条都跟我们相反

`WritingBench`（X-PLUG，2025，已开源）是**生成式写作**的综合基准——
6 个大领域、100 个子领域、1239 条写作查询。它的评测框架：

> **query-dependent evaluation framework**：给定一条查询，
> **让 LLM 现场生成 5 条 instance-specific 评判标准**，
> 每条由「简名 + 展开描述 + 详细评分细则」三段组成；
> 再配一个**微调过的 critic 模型**做 criteria-aware 打分（10 分制，附理由）。

对着我们看：

| | WritingBench | 我们 |
|---|---|---|
| 判据 | **每条查询现场生成 5 条** | 每个模式 3–7 条，**写死** |
| 打分者 | **专门微调的 critic 模型** | **跟写作同一个模型** |

**两条都相反。** 而这是离我们任务最近的一个基准。

一处**field 内部并不一致**的地方要如实记下来：
WritingBench 用 10 分制 + 理由，而第 6 节 ② 那条线（Checklists / 业界实践）
主张二元 pass/fail。**这不是我漏看，是这两条线还没打通。**
我们该按自己的数据选（第 6 节 ③ 的按维度一致率），不要照抄任何一边。

### ③ 「谁来验证验证者」：criteria drift —— 对我们是一条**警告**，不是方法

`EvalGen` / *Who Validates the Validators?*（UIST 2024）提出一个现象叫
**criteria drift**：

> 用户需要判据才能给产出打分，**而给产出打分这件事又反过来帮他定义判据**。
> 有些判据是**依赖于具体看到的那些产出**的，不是先验可定义的——
> 这对「假设评测独立于观察模型产出」的做法提出了严重质疑。

我们这套 evaluator **正是这么长出来的**（`harness-evaluators.md` 第三节第 1 条：
每一个维度都是读产出读出来的）。所以这篇不是在教我们新方法，
**是在指出我们方法的固有风险**：判据一旦冻结，它就只对当初那批产出有效。

对应到我们身上很具体：`_NON_REPETITION` 改过一次、`_COHERENCE` 后加的、
`_SECTION_COVERAGE` 更后加——**每一次都是因为旧判据对新产出失效了**。
而现在这 25 条又冻在那里，没有任何机制告诉我们它们什么时候会再次失效。

### ④ CriticGPT：一个我们**已经会、但没用在这儿**的方法

OpenAI 的 *LLM Critics Help Catch LLM Bugs*：训练一个专门的 critic 模型
挑代码里的错。关键在**训练数据怎么来的**——

> 让 ChatGPT 写代码，**再让人往里塞一个 bug 并写下对这个 bug 的批评**。

结果：critic 挑出的植入 bug 比付费的人类评审还多，
critique 被偏好的比例 **>80%**，人配合 CriticGPT 评审比单干**好 60%**。

**「植入已知缺陷，看检测器抓不抓得到」——这正是我们验闸的规矩**
（第 750 / 752 轮那几次突变测试）。我们把它用在了 28 个门禁脚本上，
**却从来没用在 25 个评分维度上。**

这给了一条不需要人工标注、**这周就能做**的路子：
拿过去的真实产出，机械地植入缺陷——复制一段、改掉一个日期、删掉一条节拍、
把两节的主题换成同一个——**看对应那一维会不会掉分**。
一维抓不住自己该抓的东西，就是那一维不合格。
（这也正好能回答 `harness-evaluators.md` 里「≥5 个维度从不区分好坏」
到底是判据没用、还是条件太少见。）

### ⑤ Weaver：弱验证器要**按各自的准确率加权**，不是先到先得

Stanford 的 `Weaver`：把多个弱的、不完美的验证器组合成一个强的，
**加权组合显著优于不加权**（因为各验证器准确率本来就不一样），
把 generation–verification gap 平均缩小 **14.5%**。

我们现在是两套都不加权：
- `Checks` 是 **first failing check wins**（谁先命中谁说了算，顺序即权重，
  而那个顺序是写代码时排出来的）；
- `rank()` 把多维分数**不加权**折叠成一个标量。

**而我们没法加权，因为从没测过任何一个验证器的准确率。** 又绕回第 6 节 ③。

### ⑥ 用户的编辑：把「采集人的信号」这条做实

`harness-mechanism-rethink.md` 第五节提的那件事，学界有现成的名字和方法：

- **PRELUDE**（NeurIPS 2024，*Aligning LLM Agents by Learning Latent Preference
  from User Edits*）：写作助手里用户对产出的编辑是**自然产生的**反馈，
  学他编辑背后的潜在偏好，目标是**让他以后越编越少**。
- **Coactive Learning**：它的假设弱到几乎白送——
  *「只要求编辑后的文本比提出的文本更好」*。**我们这儿天然成立。**
- 生产实践那边把这类叫**隐式反馈**（复制、重试、编辑、放弃、停留时长），
  覆盖率能到 20–60% 的交互。

### 第二批对每个 harness 分别意味着什么

| 功能 | 第二批新增的着力点 |
|---|---|
| 续写整篇 / 分段写作 | **①** 原子命题逐条对知识库（我们的来源是封闭的，比论文条件好）；**②** spine/beats 就是现成的「query」，可以据此现场生成本篇专属判据；**③** 判据会随产出漂移，要有重新校准的机制 |
| 数据可视化 / 智能插图 / 生成表格 | **⑤** 这三个模式的判据最多、最确定性，正是最该**按准确率加权**而不是先到先得的地方；**④** 植入缺陷测判据在这里最容易（改一个数、删一个图例） |
| 按指令生成 / 改写选区 | **②** 与第 4 节的 TICK 指向同一件事：用户的指令就是 query，据此现场生成判据 |
| 幻灯片 | **④** 五条判据可以用植入缺陷的办法各测一遍灵敏度 |
| **magic-tap / journey 日报 / digest**（现在没有 evaluator） | **⑥** 恰恰是这几个——**用户拿到就直接编辑**，隐式反馈最密集。与其先给它们造判据，不如**先开始采集编辑信号** |

最后一条值得单独说：**没有 evaluator 的那几个功能，反而是人的信号最容易拿到的地方。**
先采集、后立判据，比反过来省力得多。

### 第二批之后，我对顺序的修正

第 7 节那四步不变，但**插一步、并把第 4 步的做法换掉**：

- **在第 1 步之前**插入：**植入缺陷测一遍现有 25 个维度的灵敏度**（④）。
  不要人工标注、不要等数据，**这周就能做**，而且它会直接告诉你
  哪几维该删、哪几维只是条件太少见。
- **第 4 步「攒 judge-vs-人 的一致率」改用用户编辑**（⑥）而不是专门标注：
  coactive learning 的假设在我们这儿天然成立，**采集成本接近零**。

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

**长文事实性：拆成原子命题再逐条核**
- [FActScore: Fine-grained Atomic Evaluation of Factual Precision](https://arxiv.org/abs/2305.14251)
- [VeriScore: Evaluating the factuality of verifiable claims in long-form text generation (EMNLP 2024 Findings)](https://aclanthology.org/2024.findings-emnlp.552/)
- [DnDScore: Decontextualization and Decomposition for Factuality Verification](https://arxiv.org/html/2412.13175)
- [Decomposition Dilemmas: Does Claim Decomposition Boost or Burden Fact-Checking?（反面证据）](https://arxiv.org/html/2411.02400v1)
- [VeriFastScore: Speeding up long-form factuality evaluation](https://arxiv.org/pdf/2505.16973)

**生成式写作基准（跟我们任务最接近的一个）**
- [WritingBench: A Comprehensive Benchmark for Generative Writing](https://arxiv.org/abs/2503.05244) · [仓库](https://github.com/X-PLUG/WritingBench)
- [EQ-bench / longform-writing-bench](https://github.com/EQ-bench/longform-writing-bench)

**判据怎么立、以及它会漂**
- [Who Validates the Validators? Aligning LLM-Assisted Evaluation with Human Preferences (EvalGen, UIST 2024)](https://arxiv.org/abs/2404.12272)

**专门的 critic 模型 / 植入缺陷造训练与测试数据**
- [LLM Critics Help Catch LLM Bugs (CriticGPT, OpenAI)](https://arxiv.org/html/2407.00215v1) · [PDF](https://cdn.openai.com/llm-critics-help-catch-llm-bugs-paper.pdf)

**多个弱验证器怎么合并**
- [Shrinking the Generation-Verification Gap with Weak Verifiers (Weaver, Stanford)](https://arxiv.org/abs/2506.18203)
- [Trust but Verify! A Survey on Verification Design for Test-time Scaling](https://arxiv.org/html/2508.16665v3)
- [Multi-Agent Verification: Scaling Test-Time Compute with Multiple Verifiers](https://arxiv.org/pdf/2502.20379)

**从用户的编辑里学**
- [Aligning LLM Agents by Learning Latent Preference from User Edits (PRELUDE, NeurIPS 2024)](https://arxiv.org/html/2404.15269v1)
- [Coactive Learning for Large Language Models Using Implicit User Feedback (ICML 2024)](https://mlanthology.org/icml/2024/tucker2024icml-coactive/)
- [Principled Fine-tuning of LLMs from User-Edits](https://arxiv.org/html/2601.19055)

**优化器 / 多目标**
- [GEPA: Reflective Prompt Evolution](https://github.com/gepa-ai/gepa)
- [DSPy](https://github.com/stanfordnlp/dspy)
