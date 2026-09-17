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

## 阶段 0：先能看见（不改行为）

| # | 做什么 | 出自 | 验收 |
|---|---|---|---|
| 0.1 | `llm_usage` 记 `cached_tokens` / `cache_write_tokens` | context-eng §0 | 能按调用类型报命中率 |
| 0.2 | 每轮分数落库（新表 `harness_rounds`） | effect-plan P3 | 能回答「第 N+1 轮比第 N 轮好吗」 |
| 0.3 | `harness_runs` 加 `stopped` 列（停机原因 ≠ 打分裁决） | effect-plan P4 | 54% 的 `continue` 能拆开 |
| 0.4 | `ToolTrace` 跨轮累积进 `st.bag`（**只记不改**） | multiround §3.1 | 能算重复查询率 / 覆盖率 / 新事实占比 |
| 0.5 | `ctx_feature` 按步骤细分（produce/judge/tools/revise） | effect-plan P7 | 能回答「打分占多少预算」 |

## 阶段 1：确定性判据（不依赖模型，收益最确定）

| # | 做什么 | 出自 | 验收 |
|---|---|---|---|
| 1.1 | 打分 prompt 把 `dup_hints` 挪到 `content` 之后 | context-eng §2② | judge 调用命中率↑，行为不变 |
| 1.2 | **句级查重**（段内重复，实测 42.9%）+ 新判据 | mechanism §1.1 / longform §2 | 18 篇真产出上阈值有分布；突变验红 |
| 1.3 | `drop_already_written` 插入前按句再剔一遍 | 同上 | 单测 + 真语料不误伤 |
| 1.4 | `topic_fidelity` 归进 `INNER_QUALITY` | mechanism §4 | 它能触发 cleanup 轮 |
| 1.5 | `steer` 分流：内在质量的诊断不进检索规划 | mechanism §1 | 检索 prompt 里不再出现「重复」类诊断 |
| 1.6 | **植入缺陷测 25 个维度的灵敏度**（CriticGPT 式） | industry §8④ | 每一维有一个「抓不抓得到」的数 |
| 1.7 | 打分解析失败要能认出来（现在=全 0 分） | evaluators 问题二 | 解析失败不再触发 cleanup / 不参与 best_of |

## 阶段 2：材料账本（准 + 全）

| # | 做什么 | 出自 | 验收 |
|---|---|---|---|
| 2.1 | 账本数据结构 + 查询级短路（同参数直接返上次） | ledger §7.3 | 重复查询率 → 0 |
| 2.2 | **`kb_conflicts` 接进取材**（`superseded_by`） | ledger §10② | 被取代的事实会带上取代它的那条 |
| 2.3 | 账本摘要进 `prepare` prompt，**以「缺口」形式** | ledger §10⑤ | 空白轴被优先查 |
| 2.4 | 覆盖率驱动停机（连续两次没带回新 id 就停） | ledger §3 | 工具调用数↓而覆盖率不降 |
| 2.5 | `material_use` 改成可计算（已取 M 条里用了几条） | ledger §6 | 那一维不再 25/24 满分 |
| 2.6 | `citations_hold` 升级成 id 级确定性比对 | ledger §10④ | `factual_grounding` 重新量 |

## 阶段 3：上下文（取消截断）

| # | 做什么 | 出自 | 验收 |
|---|---|---|---|
| 3.1 | 正文换成「小节索引 + 当前小节逐字 + `read_section`」 | context-eng §7 | `Compact` 退休；产出不退步 |
| 3.2 | 事实换成「索引 + 本轮逐字 + 按需取全文」 | 同上 | `[-40:]` 取消 |
| 3.3 | `prompt_cache_key` | context-eng §4.6 | 按 note+mode 分账 |

## 阶段 4：评判形态

| # | 做什么 | 出自 | 验收 |
|---|---|---|---|
| 4.1 | 六个 block 模式补 `score_context` | evaluators 问题一 | `fits_context` 不再 4/4 满分 |
| 4.2 | 判据从整篇改成按小节 | longform §3 | 打分输入长度不随轮次增长 |
| 4.3 | `skeleton` 配确定性判据（照 `slides` 形态，不拦落库） | longform §5 建议二 | spine/beats 有判据 |
| 4.4 | `coherence` 拆出兜底桶 | mechanism §3 | 它的分数有可操作含义 |

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
