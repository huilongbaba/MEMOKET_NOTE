# P0 结论：KITE 中文可行性

**日期** 2026-08-26
**环境** `memoket-kite==0.1.0`，LLM = Muse-Glimmer-30B @ `http://192.168.77.8:8080/v1`
**复现** `python scripts/kite_zh_smoke.py zh`

要回答的问题：KITE 能不能扛中文笔记？（起因见 `kite-constraints.md` 约束 5）

> 英文对照组仍在跑，跑完后补进本文档的「对照组」一节。
> 没有对照组就无法区分「中文特有问题」和「KITE + 本地模型的通病」，
> 因此本文档的结论是**初步的**。

## 结论速览

| 指标 | 中文组 |
|---|---|
| 问答正确 | 3 / 4 |
| `remember` 耗时 | 平均 11.8 s/session |
| `recall` + `answer` 耗时 | **90 – 111 s/问** ⚠️ |

## 发现 1：KITE 把中文事实翻译成英文存了

输入全部是中文，但抽取出的 fact 大部分是英文：

| session | 输入（中文） | 抽出的 fact |
|---|---|---|
| s1 | 我搬到了深圳，住在南山区科技园附近。 | 用户搬到了深圳，住在南山区科技园附近。（**中文**） |
| s2 | Henderson 这个项目我交给马克负责了 | The user assigned the Henderson project to Mark…（英文） |
| s3 | 我开始学吉他了，每周三晚上七点上课 | User has guitar lessons every Wednesday at 7pm.（英文） |
| s4 | 新来的运营 VP 说，从现在开始 Henderson 由 Dana 负责 | From now on, Henderson is managed by Dana…（英文） |
| s5 | 我换工作了，加入 Memoket 做 AI 工程师 | The user changed jobs and joined Memoket as an AI engineer.（英文） |
| s6 | 吉他课改到周五晚上了 | The user's guitar class was changed to Friday evening.（英文） |

6 个 session 里 5 个被翻译成英文，1 个保留中文。**存储语言不一致。**

这其实歪打正着地绕开了 `keywords()` 只匹配 ASCII 的问题（约束 5），
但它是 LLM 的自发行为，不受控也不稳定。

**待决策**：把「事实存英文、中文原文留在 `<line>` 当证据」变成**显式设计**，
而不是依赖模型的偶然行为。这样做的额外好处是 `keywords()` 兜底路径也能工作。
代价是可视化展示 fact 时是英文，需要在前端做展示层翻译，或双语存储。

## 发现 2：4 题答对 3 题，失败的那题是检索问题

```
Q: 我现在的工作是什么？
   recall 召回: The user assigned the Henderson project to Mark...   ← 完全不相关
   answer:     No information
```

正确事实（`joined Memoket as an AI engineer`）确实在库里，但检索没捞到。
这是 plan 编译或检索排序的问题，不是抽取的问题。

另一个异常：

```
Q: 我什么时候上吉他课？
   recall 到 0 条事实
   answer:  根据2026-08-11的记录，吉他课已改到周五晚上了。之前为每周三晚上七点上课。  ← 正确
```

`recall()` 返回空但 `answer()` 答对了 —— 两条路径的召回不一致，
`answer` 走的是原始 line 证据。**做 magic tap 时不能只依赖 `recall()` 的返回**，
否则会误判成「知识库里没有相关内容」而退回自由续写。

值得肯定的是，时序推理是对的：s2（3月，马克）和 s4（6月，Dana）两条冲突事实
都召回了，答案正确选了 Dana，吉他课也正确选了改期后的周五。
这正是 KITE 相对向量检索的核心价值，在中文上成立。

## 发现 3：查询 90–110 秒 ⚠️ 最严重

`remember` 11.8 s/session 可以接受（批量导入本来就是后台任务），
但查询 100 秒意味着 **magic tap 这个交互功能做不了**。

三个待验证的缓解手段，按预期收益排序：

1. **少调一次** — 本测试每题调了 `recall()` **和** `answer()`，各自独立编译 plan。
   生产只需 `answer_with_evidence()` 一次拿到答案 + 证据，预期直接砍掉一半。
2. **降低推理强度** — Muse 实测 low→high 是 237→372 token。KITE 只发单条 user
   消息、不带 system prompt，需要试 llama-server 的 `--chat-template-kwargs
   '{"reasoning_strength":"low"}'` 从服务端设默认值。
3. **缓存 plan** — KITE README 明说 plan 可缓存复用
   （"the same plan walks the same steps"），高频查询可命中。

如果三条都用上仍然超过 10 秒，就得考虑 plan 编译换用更快的模型
（KITE 的 benchmark 用的是 gpt-4.1-mini），或者把 magic tap 改成异步触发的
建议流而非同步等待。

## 对照组（英文）

同一批事实、同一组问题，只换语言。

| 指标 | 中文 | 英文 |
|---|---|---|
| 问答正确 | 3 / 4 | **4 / 4** |
| `remember` 耗时 | 11.8 s/session | 11.8 s/session |
| 查询耗时 | 90 – 111 s | 99 – 130 s |
| `recall` 召回条数 | 0 – 2 条 | 1 – 8 条 |

### 中文召回确实更弱

同一道题的直接对比：

```
中文  Q: 我现在的工作是什么？
      recall → 1 条，且是无关的 Henderson 事实                        ✗
英文  Q: What is my current job?
      recall → 3 条，含正确的 "joined Memoket as an AI engineer"      ✓
```

召回宽度的系统性差异（0–2 条 vs 1–8 条）与「`keywords()` 对中文返回空、
兜底 grep 失效」的预期完全吻合。这不是单点巧合，是可测量的退化。

**决策**：把「事实存英文、中文原文留在 `<line>` 当证据」定为显式设计。
理由有两条 —— 它让 `keywords()` 兜底路径重新生效，而且模型本来就在自发这么做
（发现 1），显式化只是把不可控行为变成可控。

### 延迟与语言无关

英文查询反而更慢（99–130 s vs 90–111 s）。所以 100 秒查询是
**KITE + 本地 30B 模型的固有开销**，不是中文问题，必须单独优化。
换语言方案解决不了它。

### 综合结论

- 中文**可用但有损**，按上述方案补偿后可推进，不需要推翻架构。
- 时序推理在中英文上都正确（马克→Dana、周三→周五都选对了），
  KITE 的核心价值成立。
- **查询延迟是唯一的架构级风险**，直接决定 magic tap 能不能做成同步交互。
  这一条必须在 P3 之前有结论。
