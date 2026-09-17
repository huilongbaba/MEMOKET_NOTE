# TRACELOG · Harness 升级

> 计划见 `docs/harness-upgrade-plan.md`。
> 每一批记三件事：**改了什么 / 测出什么 / 下一步改什么**。
> 架构变化同步进 `docs/harness-framework.md`。

## 批 1 · 阶段 0：先能看见（2026-09-17）

**一行行为都没改。** 这一批的全部意义是把「未测」变成「有数」。

### 改了什么

| # | 改动 | 落在哪 |
|---|---|---|
| 0.1 | `llm_usage` 加 `cached_tokens` / `cache_write_tokens` 两列，`_record` 读返回体 | `store.py` `_ADDED_COLUMNS`、`util/llm.py:_cached_of` |
| 0.2 | 新表 `harness_rounds`：**每一轮**的分数 + 正文长度 + 工具计数 | `store.py` `_SCHEMA` / `record_harness_round` / `rounds_of_run` |
| 0.3 | `harness_runs` 加 `stopped` 列（停机原因 ≠ 打分裁决） | `store.py`、`types.RunRecord`、`adapter.py`、`middleware/history.py` |
| 0.4 | 新 middleware `Ledger`：`ToolTrace` 跨轮折进一份账本 | `middleware/ledger.py`（新） |
| 0.5 | `ctx_feature` 按步骤细分（`…:tools` / `…:judge`） | `loop.py` 新增 `_step()` 上下文管理器 |

### 两个当时没想到、写代码时才露出来的点

**① `_cached_of` 必须认两种返回体形状。** `/chat/completions` 给的是
`usage.prompt_tokens_details.cached_tokens`，Responses API 给的是
`usage.input_tokens_details.cached_tokens`（还多一个 `cache_write_tokens`）。
照着文档只写一个，换条路就**静默变成 0**——而 0 跟「没命中」长得一模一样，
是最难发现的一种记账错。四种形状都补了单测。

**② 查询身份必须按键排序。** `{query, limit}` 和 `{limit, query}` 直接 `json.dumps`
出来是两个字符串，那样**重复查询永远统计不出来**。这条有单测钉着。

### 测出什么

- 后端 **1119 → 1128**（账本 9 条单测），前端 254 不变。
- **仓库的闸当场抓到两处文档没跟上**：`test_doc_counts`
  （「文档里写着 13 个 middleware，实际是 14」）和 `test_directory_map`
  （harness 下每个文件都要在目录图上）。
  `docs/harness-framework.md` 已同步：middleware 13 → 14，加了 Ledger 一行。
  *这正是「改动要更新架构文档」这条要求在这个仓里的落地方式——不是靠自觉，是靠闸。*

### 一条刻意的克制

`Ledger` **只记不改**，一个 prompt 都没碰。接进 prompt 是单独一步——
有实测证据说明「把已经有什么摆给模型看」会**缩小模型的搜索空间**
（`harness-fact-ledger.md` §10⑤），所以那一步必须能单独回退、单独验。

### 下一步

阶段 1，从**收益最确定、风险最低**的两条开始：
1.1 打分 prompt 把 `dup_hints` 挪到 `content` 之后（两行，纯排布）；
1.2 句级查重（段内重复实测 42.9%，阈值要在 18 篇真产出上量）。
