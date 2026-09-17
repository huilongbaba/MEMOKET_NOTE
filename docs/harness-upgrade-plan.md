# Harness 升级：执行 - 测试 - 迭代计划

> 第 762 轮定。**这是执行计划，不是方案**——方案在
> `harness-effect-plan` / `harness-mechanism-rethink` / `harness-evaluators` /
> `harness-evaluator-industry` / `harness-longform-deepdive` /
> `harness-context-engineering` / `harness-multiround-retrieval` /
> `harness-fact-ledger` 八份里，这一份只管**怎么落、怎么验、按什么顺序**。
>
> 台账：`docs/TRACELOG-harness.md`（每批改了什么、测出什么、下一步改什么）。
> 架构文档 `docs/harness-framework.md` 随改随更新。

## 铁律（每一批都适用）

1. **先能看见，再动手。** 阶段 0 不改任何行为，只把数记下来。
   没有数的改动无法证明有效，也无法回退判断。
2. **能用代码判准的，不交给模型。**（`checks/__init__.py` 的老规矩）
3. **判据宁可窄一点**，误伤比漏报贵；阈值一律在**真实产出**上量，不拍脑袋。
4. **闸跑绿不等于闸有用**——每条新判据都要**突变验**（把修复撤掉必须变红）。
5. **不改 `loop.py`。** 全部落在 middleware / checks / tools / prompts / 落库。
6. **每一批都跑全量闸**：`npm test`（tsc + eslint + vitest + check 脚本）、
   后端 `pytest`。红了就先修红的。
7. **质量优先于省钱。** 任何一条让产出变差，退回去。

## 全量清单（第 763 轮重排：原计划漏了约一半）

第 762 轮那版只列了 20 条，把八份调研逐条比对之后**漏了 19 条**，
其中包括行业调研里我自己排在**第一位**的那条（图表 / 表格确定性化）。
下面是全量，**漏的那些标了 `[补]`**。

### 阶段 0 · 先能看见（不改行为）—— ✅ 5/5 完成

| # | 做什么 | 出自 |
|---|---|---|
| 0.1 | `llm_usage` 记 `cached_tokens` / `cache_write_tokens` | context-eng §0 |
| 0.2 | 新表 `harness_rounds`（每轮分数 + 正文长度 + 工具计数） | effect-plan P3 |
| 0.3 | `harness_runs` 加 `stopped` 列 | effect-plan P4 |
| 0.4 | `Ledger`：`ToolTrace` 跨轮累积（只记不改） | multiround §3.1 |
| 0.5 | `ctx_feature` 按步骤细分 | effect-plan P7 |

### 阶段 1 · 确定性判据 —— 2/7

| # | 做什么 | 出自 |
|---|---|---|
| 1.1 | ✅ 打分 prompt 挪 `dup_hints` | context-eng §2② |
| 1.2 | ✅ 段内句级查重 + `no_restated_paragraph` | mechanism §1.1 |
| 1.3 | `drop_already_written` 插入前按句再剔一遍 | 同上 |
| 1.4 | `topic_fidelity` 归进 `INNER_QUALITY` | mechanism §4 |
| 1.5 | `steer` 分流：内在质量诊断不进检索规划 | mechanism §1 |
| 1.6 | 植入缺陷测 25 个维度的灵敏度 | industry §8④ |
| 1.7 | 打分解析失败要能认出来（现在 = 全 0 分） | evaluators 问题二 |

### 阶段 2 · 材料账本 —— 0/7

| # | 做什么 | 出自 |
|---|---|---|
| 2.1 | 查询级短路（同参数直接返上次） | multiround §3.4 |
| 2.2 | **`kb_conflicts` 接进取材**（`superseded_by`） | ledger §10② |
| 2.3 | `[补]` **事实日期进账本**（temporal validity） | ledger §10② |
| 2.4 | 账本摘要进 prompt，**以「缺口」形式** | ledger §10⑤ |
| 2.5 | 覆盖率驱动停机 | ledger §3 |
| 2.6 | `material_use` 改成可计算 | ledger §6 |
| 2.7 | `citations_hold` 升级成 id 级确定性比对 | ledger §10④ |

### 阶段 3 · 取消截断 —— 0/3

| # | 做什么 | 出自 |
|---|---|---|
| 3.1 | 小节索引 + `read_section`，`Compact` 退休 | context-eng §7 |
| 3.2 | 事实索引取代 `[-40:]` | 同上 |
| 3.3 | `prompt_cache_key` | context-eng §4.6 |

### 阶段 4 · 评判形态 —— 0/7

| # | 做什么 | 出自 |
|---|---|---|
| 4.1 | 六个 block 模式补 `score_context` | evaluators 问题一 |
| 4.2 | 判据从整篇改成按小节 | longform §3 |
| 4.3 | `skeleton` 配确定性判据 | longform 建议二 |
| 4.4 | `coherence` 拆出兜底桶 | mechanism §3 |
| 4.5 | `[补]` **给 `coherence` 补位置级探测器**，或写明它只能停机不能驱动修复 | mechanism 第 2 层 5 |
| 4.6 | `[补]` block 模式的 `stop_when`（现在 6 个模式 0 条） | evaluators 问题三 |
| 4.7 | `[补]` 清掉 `last_scores` 死状态，并写注释钉住「别把上一轮分数喂给打分器」 | ledger §10⑥ |

### 阶段 5 · `[补]` 有 oracle 的那几个模式 —— 0/3

**行业调研里我自己排在第 1 位的一条，原计划一条都没有。**
图表 / 表格 / 分析这三个模式**本来有执行 oracle**——
数字能不能对上源表是**算出来的**，不是判出来的。

| # | 做什么 | 出自 |
|---|---|---|
| 5.1 | `data_grounding` 确定性化：图 / 表里的数字跟工具返回逐个 diff（chart · table · analysis 三个模式） | industry §2–3 |
| 5.2 | `numbers_from_tools` 同上（eda · analysis） | industry §2 |
| 5.3 | readability 档：图例有没有、类别数是不是多到读不出来 | industry §2（VisEval） |

### 阶段 6 · `[补]` 指令类：从用户那条指令现场生成 checklist —— 0/2

`RaR` 的消融：**固定通用 rubric 明显更差**，而我们八个功能全是那一档。
`prompt` / `custom` 的指令天然短而具体，是最容易见效的入口。

| # | 做什么 | 出自 |
|---|---|---|
| 6.1 | `prompt` / `custom` 跑前从用户指令生成 instance-specific checklist（TICK 形态，二元判） | industry §4 |
| 6.2 | 可程序验证的约束单独走代码（字数、段数、必须提到 X） | industry §4（IFEval） |

### 阶段 7 · `[补]` 长文专项 —— 0/4

| # | 做什么 | 出自 |
|---|---|---|
| 7.1 | `factual_grounding` 改成 **decompose-then-verify**（拆原子命题 → 逐条对账本） | industry §8① |
| 7.2 | 新增「这一节材料够不够」（sufficient context），不够就触发既有的弃答形态「这里需要补上 XX 的实际记录」 | ledger §10③ |
| 7.3 | `section_coverage` 加字数预算（AgentWrite） | longform 建议四 |
| 7.4 | 三档 → 二元 checklist（**先按维度量一致率再决定改哪几维**） | longform §4（HelloEval） |

### 阶段 8 · `[补]` 没有 evaluator 的那几个功能 —— 0/2

15 个产出文字的功能，只有 8 个有 evaluator。

| # | 做什么 | 出自 |
|---|---|---|
| 8.1 | `magic-tap`（单次续写）配判据，照 `slides` 形态：**判了不拦，结果跟产物一起显示** | evaluators 问题四 |
| 8.2 | `journey/report` 同上 | 同上 |

### 阶段 9 · `[补]` ground truth —— 0/4（长周期，先开始采集）

**这是最深的一条：整个回路没有 ground truth。**

| # | 做什么 | 出自 |
|---|---|---|
| 9.1 | **采集用户编辑**：跑完落一份正文，用户下次保存再落一份，跟 `harness_runs` 关联 | mechanism §5 / industry §8⑥ |
| 9.2 | 按维度报 judge-vs-人 一致率（门槛 75–90%） | industry §6③ |
| 9.3 | `[补]` 跨「跑」的护栏：这次跑完比上次差就**提示**（不自动回滚） | effect-plan P2 |
| 9.4 | `[补]` judge 模型槽（`provider_config` 加一组可选配置，留空 = 同一个） | effect-plan P6 / industry §6④ |

### 阶段 10 · `[补]` 横向：把方法固化下来 —— 0/3

| # | 做什么 | 出自 |
|---|---|---|
| 10.1 | 六条「维度怎么建立」的方法写成 `harness-framework.md` 正式一节 | evaluators §3 |
| 10.2 | check 脚本钉住两条可机械验的：判据落在本模式真有的维度上（现在 0 落空，要保持）、每个模式至少一维是这次跑有权改善的 | evaluators §5.3 |
| 10.3 | criteria drift 的重新校准机制（判据会随产出失效，要有再校准的入口） | industry §8③ |

---

## 200 轮里做什么、不做什么

**做**（约 34 条）：阶段 0 ✅ → 1 → 2 → 3 → 5 → 4 → 6 → 7 → 8 → 10。

**明确推到 200 轮之后**：

- **9.2 一致率**、**9.4 judge 模型槽**、**10.3 重新校准**——
  它们都依赖 **9.1 采集用户编辑**攒出数据，而那要跑一段时间。
  **9.1 本身要尽早做**（采集没有风险），但**别急着用它调参**：
  样本不够时按它调，比不调更糟。
- **Re3 的「同位置多候选重排」**（longform 建议六）：会让每轮写作调用翻 N 倍，
  等阶段 0 的每轮数据攒够，拿数据判断「一轮值不值得花 2–3 倍」再说。
- **`Weaver` 式按验证器准确率加权**：依赖 9.2。

## 不做

- 不换 memory engine（就用 kite）。
- 不引入 DSPy / GEPA / Mem0 / Letta 任何一个当依赖。
- 不加新评分维度（已有 25 个，问题在执行器和上下文，不在指标）。
- 不做自动删重复、不做跨跑自动回滚（只报，不替用户决定）。
- 不上 token 级控制器（走 HTTP 接口，没有解码控制权）。
- 不为「写得更长」优化。

## 总验收（打包前要能报出来的数）

| 判据 | 现在 | 目标 |
|---|---|---|
| 段内重复字占比（18 篇真产出） | 最差 **42.9%** | 最差 < 10% |
| 反复跑同一篇分数单调下滑 | **3/6** | 0/6 |
| 收尾时仍 `continue` 的比例 | **54%** | 能拆成 stall / max_rounds / regressed |
| 一次跑内重复查询占比 | **未测** | 0 |
| judge 调用缓存命中率（第 2 轮起） | **未测** | > 0.7 |
| 没有位置级探测器的内在质量维度 | **2** | 0 |
| `material_use` / `fits_context` 满分率 | 24/25、4/4 | 不再是「无从判断默认给过」 |
