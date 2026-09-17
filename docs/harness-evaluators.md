# 调研：每个 harness 功能的 evaluator 到底怎么建立

> 第 756 轮。**调研文档，没改代码。**
>
> `harness-framework.md` 记的是「有哪些东西」，这一份回答的是
> **「evaluator 是怎么立起来的」**——结构、方法、以及调研过程中查出来的四个问题。
> 所有数字都是当场从代码和库里读出来的，不是复述注释。

---

## 一、一个 evaluator 由四层组成

```
      ┌─ 代码判据 checks（确定性、零成本、先跑、短路）
一轮 ─┼─ 维度 dims（模型打分 0/1/2，一次调用）
      ├─ 打分上下文 score_context（正文之外，评判者还需要知道什么）
      └─ 停机条件 stop_when（纯函数，OR 起来）
```

**引擎只有一个**（`checks/rubric.py:evaluate`），八个功能共用：
一次模型调用、固定 JSON 契约、`temperature 0.1` / `max_tokens 600`。

两件事分得很清楚，而且分法是对的：

- **`complete` 由代码判**：所有维度都到 2 才算完。
  模型只需要回答「这一维到 2 了吗」这个窄问题，
  不需要回答「整件事做完了吗」这个它答不准的问题。
- **`blocked` 信模型**：分数低说明不了「再跑一轮有没有用」，这个只能问它。

判据（check）在打分**之前**跑（`middleware/checks.py`）：
判据是免费的，打分调用要几十秒；第一条不过就短路，不付那笔钱。
**同一条判据卡满 2 轮之后不再短路**——否则打分器一次都跑不起来，
`complete` 结构上就到不了（第 601 轮死锁）。

---

## 二、八个功能的 evaluator 全表（当场跑出来的）

| 功能 | 维度 | 判据 | stop_when | 轮上限 | 维度名 |
|---|---:|---:|---:|---:|---|
| 续写整篇 note | 7 | 11 | 4 | 8 | spine_fidelity · beat_coverage · non_repetition · factual_grounding · coherence · material_use · style_fit |
| 分段写作 section | 7 | 10 | 2 | 4 | topic_fidelity · section_coverage · non_repetition · factual_grounding · material_use · coherence · style_fit |
| 数据可视化 eda | 7 | 4 | **0** | 3 | numbers_from_tools · honest_caveats · has_charts · no_duplicate_charts · covers_the_data · fits_context · actionable |
| 智能插图 chart | 4 | 3 | **0** | 3 | chart_validity · data_grounding · right_kind · fits_context |
| 生成表格 table | 3 | 2 | **0** | 3 | table_validity · data_grounding · fits_context |
| 数据分析 analysis | 5 | 3 | **0** | 3 | answers_the_question · numbers_from_tools · states_limits · chart_validity · fits_context |
| 按指令生成 prompt | 3 | 2 | **0** | 3 | follows_prompt · fits_context · no_fabrication |
| 改写选区 custom | 3 | 1 | **0** | 3 | follows_prompt · replaces_cleanly · no_fabrication |

*note / section 两行是 `for_run()` 按运行时条件算出来的（有没有风格档案、
是不是打磨模式），这里取「有档案 + 非打磨」。*

**25 个不重复维度**，其中 11 个被复用；`fits_context` 一个人被 **5 个模式**共用。

---

## 三、维度是怎么写出来的——六条方法（从代码里反推）

这六条现在**只活在注释里**。它们是这套 evaluator 真正的建立方式。

### 1. 先读产出，再加维度——不照着别处抄

`_COHERENCE` 的来历（`modes.py:154`）：真实质量采样里有两篇被四个维度
**全打 2 分、判定 complete**，而人一眼就看出问题——一篇正文中间夹了个完整
结尾，一篇小节编号是 1、2、4、3。
**原来的四个维度没有一条在管「这篇作为一个整体自不自洽」。**

同样的来历：`_SECTION_COVERAGE`（第 605 轮，三节各跑一轮就全 2 分判完成，
交出来 620/434/429 字——「短、干净、扣题、不重复的残篇是这个闭环的最优解，
因为没人问它够不够」）。

### 2. 代码能判准的，不许写成维度

`checks/__init__.py` 开头写着为什么：
> The scorer and the thing being scored are the same local model,
> so its blind spots line up exactly with the writer's.

举的是真例子：一段「图表」其实是 `[bar chart: clicks by channel …]` 这种句子，
`has_charts` 给了 2 分。所以「图是不是工具产出的」归 `charts_from_tools`（代码），
「图有没有信息量」才归 `has_charts`（模型）。

### 3. guidance 写成句子，不是标签

`modes.py:271`：
> The wording is what the scorer reads, so these read as sentences about
> what good and bad look like, not as labels.

`_COHERENCE` 是一张五条的检查清单（多个结尾 / 标题层级 / 编号 / 体例 / 自我拆台），
注释里明说「泛泛说『检查结构』实测没用」。

### 4. 放宽判据也要有据，而且放宽之后要有确定性兜底

`_NON_REPETITION` 改过一次，过程是这套方法最完整的一次示范：

- 原判据：「同一个结论换说法讲了不止一次 = 不足」。
- **九批 2160 次实测**，这一维稳在 1.3 下不来，判词永远是同一句。
- 同一批产出里**段落两两最高相似度只有 0.29**——一处字面重复都没有。
- 结论：**是判据在罚正常写法**（开头点题、结尾收束），不是文章差。
- 改法：把「小节之间主题撞车」留下，「重申核心结论」明确算达标。
- **兜底**：真正的字面重复交给确定性手段（`find_repeats` / `drop_already_written`），
  这一维只负责它们看不见的语义撞车。

> 放宽维度有「为了刷分而降标准」的风险。这里的做法是
> **同时把被放掉的那一半交给代码**，风险才不成立。

### 5. 永远不要用一个「这次跑无权改善」的维度去打分

`for_run()` 的两个真实代价：
- 没有风格档案时 `style_fit` 无从满足 → 每一轮都在追一个追不到的东西。
- 打磨模式禁止写作，而 `beat_coverage` / `material_use` 量的是「写了多少」
  → 判 0 → 永远到不了 complete → 撞 max_rounds，**每轮的诊断还在推它去写
  它不许写的东西**。

### 6. 每条判据必须落在这个模式真有的维度上

`pick_dimension` 的来历：`no_fake_charts` 原来写死打 `has_charts`，
在智能插图模式下打的是一个**这个模式根本没有的维度**（那儿叫 `chart_validity`）。
24 个「判据 × 模式」组合里有 8 个这样。

**现状我全量查过了：`0` 个落空。** 这条规则已经立住了。

---

## 四、调研中查出来的四个问题

### 问题一：六个 block 模式打分时，一点上下文都没有

> **已落地（批 8，计划 4.1）**：前后文 / 用户那条指令 / 选中的原文由
> `harness/score_context.for_block` 装进 `st.bag["score_context"]`，事实块由
> `loop._evaluate` 按 `st.facts` 现拼、**所有模式一视同仁**。下面这一节记的是
> 第 756 轮当时的现状，留着是因为它是这次改动的来由；**别照着它判断今天的代码**。
> 重测的数字见 `docs/TRACELOG-harness.md` 批 8。

`score_context` 只有两处设置（`routers/note_harness.py:93`、
`routers/writing_plan.py:253`）。**六个 block 模式一个都没有**——
打分器看到的只有新生成的那一块（`hooks/block.py:82`：`st.content = 新块`）。

而 `fits_context` 这一维，被 **8 个模式里的 5 个**共用，原话是：

> It should read like a passage that **was always in this note**…
> headings one level below **the nearest heading above**…
> tone and conventions match **the surrounding text**.

**周围的正文从来没给过它看。** 而 `st.before` / `st.after` 是存在的：
写作那一步拿得到（`hooks/block.py:120`），
确定性判据 `heading_fits` 也拿得到（`structure.py:49` 用 `st.before`）。

于是 `fits_context` 实际被拆成了两半：
**标题那一半有 `heading_fits` 兜底，语气 / 体例那一半是在看不见上下文的情况下打的分。**

数据对得上：`fits_context` 实测 **4/4 满分**，`data_grounding` **2/2 满分**
（它的判据是「每个格子都能追到笔记里的表或检索到的事实」——同样看不见笔记）。
**满分很可能不是「做得好」，是「无从判断，默认给过」。**

### 问题二：打分解析失败 = 全 0，和「写得极差」无法区分

`rubric.py` 里：`parsed = _extract_json(raw) or {}` →
`raw_scores = {}` → 循环里每个维度拿不到条目 → **`level = 0`**。

于是一次 JSON 没解析出来，产生的 Evaluation 是「所有维度 0 分」。这份分数会：
- 触发 `Repair` 的 `cleanup_only`（内在质量维度为 0）
- 参与 `best_of` 排名
- 参与 `_regressed` 判断

`loop.py:_score` 只挡**抛异常**，挡不住「解析失败」这条静默路径。

**可区分**：解析失败时每个维度的 `note` 都是空串，真打出来的 0 分带一句诊断。
现在没有任何地方看这个差别。

### 问题三：六个 block 模式没有任何 `stop_when`

note 有 4 条、section 有 2 条，**六个 block 模式是 0 条**。
它们唯一的提前收场方式是 `complete` / `blocked`，否则跑满 3 轮。

这不一定是问题（block 本来就短、上限只有 3），但它意味着
**「这一轮什么都没变」「材料用完了」这类信号在 block 模式里完全不起作用**。
列在这里供判断，不建议现在就加——加之前先看每轮数据。

### 问题四：会产出文字的功能有 15 个，有 evaluator 的只有 8 个

| 档 | 功能 |
|---|---|
| **闭环 evaluator**（维度 + 判据 + 停机） | note · section · eda · chart · table · analysis · prompt · custom |
| **只有确定性判据，不闭环** | `slides`（5 条，**不拦着落库**——一次成型的重构，判据结果跟产物一起显示，用户自己决定要不要重跑） |
| **没有质量判据**（只有长度截断这类硬约束） | `skeleton`（spine/beats）· `magic-tap`（单次续写）· `digest`（周报）· `rewrite` · `expand` · `verify` · `journey/report` · `journey/span` |

最后那一档里，`magic-tap` 和 `journey/report` 是用户直接看得见产出的两个，
**目前没有任何东西在事后看一眼它写成什么样**。

（顺带：`journey/report` 的提示词注释里写着「这跟写作 harness 里 `material_used`
那条判据是同一场仗」——方法是通的，只是没有落成判据。）

---

## 五、建议（供你拍板，不改代码）

按「改动小 / 因果清楚」排：

1. **把 `score_context` 补给 block 模式**（问题一）。
   `st.before` / `st.after` 现成，一个字典的事。
   改完要重新看 `fits_context` 和 `data_grounding` 还是不是 100% 满分——
   **如果分数开始掉，说明之前那些满分是假的**，这本身就是验证。
2. **解析失败要能认出来**（问题二）。
   最小做法：`evaluate` 在解析不出 JSON 时返回一个带标记的 Evaluation，
   `loop.py` 按「未打分」处理（跟异常那条路合并），而不是当成全 0。
3. **把上面第三节那六条方法写成 `docs` 的正式一节**，
   并加一个 check 脚本把能机械验的两条钉住：
   「每条判据落在本模式真有的维度上」（现在 0 落空，要保持）、
   「每个模式至少有一条维度是这次跑有权改善的」。
   *现在这六条只活在注释里，下一个加维度的人未必会读到。*
4. **`magic-tap` 和 `journey/report` 要不要有 evaluator**，这是产品判断不是技术判断，
   先想清楚「判出来给谁看、他能做什么」再决定。
   `slides` 那种「判了但不拦、结果跟产物一起显示」是现成的可借鉴形态。

**不建议**：
- 不要因为 block 模式没有 `stop_when` 就去补——先看数据（每轮分数落库之后）。
- 不要加新维度。25 个已经不少，而调研显示问题在**上下文缺失**和
  **信号失真**，不在指标不够。
