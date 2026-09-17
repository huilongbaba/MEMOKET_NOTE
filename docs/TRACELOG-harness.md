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

## 批 2 · 阶段 1.1 + 1.2：段内查重（2026-09-17）

### 改了什么

**1.1** `rubric.py:_build_prompt` 把 `dup_hints` 挪到 `content` **之后**。
它每轮变而 content 追加式，放前面时缓存断点落在约 1300–2000 token 处，
**正文那几千 token 从来没被缓存过一次**。两行。

**1.2** 段内句级查重：`repeats.py` 新增 `find_restated` / `restated_ratio`，
产出并进 `find_repeats`（**修订那一步的候选就来自这里**），
新判据 `no_restated_paragraph` 挂上两个长文模式。

### 阈值是量出来的，不是拍的

18 篇真产出、**777 个段内句对**，相似度分布是**双峰**的：

```
P50 0.14   P75 0.20   P90 0.63   P95 0.89   P99 1.00
```

P75 到 P90 之间是一道很宽的谷。取 **0.62**（跟 `drop_already_written` 已有的
阈值同一个数，同一种缺陷只是粒度不同）。占比门槛取 **3%**：
按比例看 **15 篇精确等于 0.0%**，另外三篇 5.9% / 34.6% / 42.9%——中间没有连续带。

### 写代码过程中改了三次，每次都是**量**出来的

**① 切法错了一次。** 第一版按 `\n` 切"段"。突变验时发现：A、B 在同一自然段
但**分两行**时，按行切会把它们分到两段里各自比较（比不着），
而段落级又把整段揉成一块（相似度被稀释）——**两边都漏**。
改成「按 `\n\n` 分段、按**标点和换行**切句」。

**② 改完当场多抓了两篇，一看全是误伤。**
`| P1 | [第二事项] | … |` 和 `| P1 | [第三事项] | … |`——**markdown 表格行**，
按设计就该长得一样。加了「表格行和围栏代码不参与」，回到 15/18 精确为 0。
*判据宁可窄一点，误伤比漏报更贵。*

**③ 测试的 fixture 自己写错过两次**，都记在测试的 docstring 里：
第一版拿 `C * 12` 当"大量新内容"（那本身就是十二遍重复）；
第二版用「第 N 项进展跟上一项完全不同：XX」这个**模板**，十二句彼此相似度 **0.918**。
**「看起来不一样」和「量出来不一样」是两回事。**

### 突变验：五个突变，第一轮只抓住四个

| 突变 | 结果 |
|---|---|
| `find_restated` 直接返回空 | ✗ 5 条红 |
| 阈值调到 0.95 | ✗ 1 条红（**第一轮没抓住**——样例 A/B 相似度 0.96，钉不住阈值；补了一对真实边界样例 0.69） |
| 句子只按标点切、不按换行 | ✗ 1 条红（**第一轮没抓住**——补了「句尾没有标点」的用例：标题、清单项都是这样） |
| 表格行不再排除 | ✗ 1 条红 |
| 围栏不再剥离 | ✗ 1 条红 |

*两次「突变没被抓住」都是**用例不够**，不是实现对。这条规矩又验证了一次。*

### 测出什么

- 后端 **1128 → 1142**，前端 254 不变。
- 真产出上：`1da5a3c9767b` **42.9%** / `06647b9c2031` **34.6%** /
  `47b046adafcb` **5.9%**，**其余 15 篇精确 0.0%**。
- **闸又抓到文档没跟上**（判据 14 → 15），`harness-framework.md` 已同步四处。

### 下一步

1.4 `topic_fidelity` 归进 `INNER_QUALITY`（一个元组加一个词，但它把 7/16 的不达标
从「只能让回路停下来」变成「能触发一次只修不写」）；
1.5 `steer` 分流；1.7 打分解析失败要能认出来。

## 批 3 · 阶段 1.3 + 1.4 + 1.5 + 1.7 + 4.7：把分数接到能动手的那条线上（2026-09-17）

这一批五条改动是同一件事的五个面：**一个维度的分数，得有一条能让它变好的路。**
`topic_fidelity` 之前哪条路都没有；内在质量的诊断之前走错了路；
`last_scores` 是一条通向没有的路；而 1.7 管的是这条路的**入口**——
分数本身是不是真的打上了。

### 改了什么

**1.4 `topic_fidelity` 归进 `INNER_QUALITY`**（`middleware/repair.py`，一个词）。
它之前既不在 `INNER_QUALITY` 也不在 `loop.COVERAGE_DIMS`，是个孤儿——
分段模式实测 **16 次里 7 次判它不达标**，而两条执行器选择规则一条都不看它：
既不排「只修不写」，也不算「还没写够」。它唯一的作用是把 `status` 钉在
`continue` 上，看着回路把轮数跑满。归内在质量的理由很硬：
**已经跑题的那段文字，不会因为后面补了几段切题的就不跑题了。**

**4.7 删掉 `last_scores` 死状态**（`loop.py`，删两行、加一段注释）。
全仓没有任何一处读它。删之前先把「为什么不该把它接回去」写在原地：
LLM 评委有实测的 anchoring bias（*Anchoring Bias in LLM-as-a-Judge Systems:
Prior Scores Compromise Evaluation Independence*），先给参考分会让评委跟着
那个数走。而这个回路有三处依赖**两轮之间独立打出来的分**：`_no_progress`、
`_regressed`、以及 `Repair` 判「修完动没动分」。
**现在打分器看不到上一轮分数这件事是碰巧对的，不是设计出来的**——
`_evaluate` 只递 content / dimensions / dup_hints / score_context 四样，
而 `score_context` 由 router 组装（`note_harness._score_context` /
`writing_plan._score_context`），里面确实一个分数都没有。碰巧对的事必须写下来。

**1.5 `steer` 分流**（`policy.py` 新增 `MATERIAL_DIMS`）。
`steer` 唯一的去处是「这一轮该去知识库查哪些事实」那个 prompt，
而「你把同一件事说了两遍，换个思路」在那儿查什么都修不了。
现在只有检索能改善的四维才往 `steer` 里写；内在质量卡住照旧记 `reason`
（SSE 里用户看得见），但走 `focus_note` → `revise` 那条线。
挑升级对象时**材料类优先**，否则先撞上一个卡住的 `non_repetition` 就 break，
同样卡住的 `beat_coverage` 一句话都得不到。

**1.3 插入前按句再剔一遍**（`editor/outline.drop_restated_sentences`）。
三层查重（段落级 / 插入前句级 / 段内句级）的切句、阈值、排除规则收进
`editor/outline.py` 一份——分层测试把 `editor/outline` 放在 PURE 名单里，
harness 可以用它、它不许反过来 import harness，所以公共部分只能落在那边。

**1.7 打分解析失败要能认出来**（`checks/rubric.py` 新增 `ScoreParseError`，
`loop._regressed` 加一行守卫，`kb/extract_judge.py` 加一段注释）。
在这之前，`_extract_json` 解析不出来时 `raw_scores` 是个空 dict，于是**每个
维度都拿到 `level=0`**，一份看起来完全正常的 `Evaluation` 照常流进下游——
而那份"全 0 分"跟模型真判「每一项都远不达标」**在四处地方一个字节都分不出来**：
`Repair`（三个内在质量维度同时不达标 → 下一轮 `cleanup_only`）、
`BestOf` 的 `rank()`（`(0, 0.0)`，比真正没判过的 `(-1, -1.0)` **还高**）、
`_regressed`、以及 `kb/extract_judge` 的汇总。而 `loop._score()` 只挡得住
**抛异常**那条路（超时、断连），这条静默路径从它底下穿过去了。

**改法是把两条路合并成一条**，不是给 `Evaluation` 加字段：解析失败改成抛
`ScoreParseError`，被 `_score()` 已有的 `except` 接住变成 `None`。
「这一轮没打上分」在这个回路里本来就有一种表示法（`st.ev is None`），
再加一个字段等于让下游每一处读分数的地方各判一次，漏掉任何一处这条 bug
就原样回来——而且 `Evaluation` 还要走 `snapshot.py` 的落盘/还原。
这条形态有专门的用例钉着（`test_不要通过给Evaluation加字段来表示没判上`）。

**判据窄一条**：只有「一个维度都没解析出可用的 `level`」才算没判上。
模型正常返回、真判了某一维 0 分，那是判断结果，照旧当分数用——
误伤这一档的代价是写得极差的那一轮连一轮修复都排不上。
唯一的例外是 `blocked`：它为真说明 JSON 本身解析成功了（解析不出来时
`blocked` 只能是 False），模型是明确说了「再跑也没用」，那是真裁决；
而且 `_blocked` 会当轮停机，全 0 分不会流进下一轮。

### 突变验：十四个突变，五个第一轮没抓住

| 突变 | 结果 |
|---|---|
| `topic_fidelity` 从 `INNER_QUALITY` 拿掉 | ✗ 2 条红 |
| 同上，**再把用例里那句元组成员断言删掉** | ✗ 行为断言（`st.bag["cleanup_only"]`）红——证明这条用例判的是行为，不是在照抄元组 |
| `last_scores` 那两行原样接回去 | ✗ 1 条红 |
| 只删钉住它的注释、代码不动 | ✗ 1 条红 |
| **把 `focus_note` 塞进打分器的 `score_context`（换了个名字）** | **第一轮没抓住**——原来那条用例是**词法**的（全仓 grep `last_scores`），换个名字它照样绿。补了 `test_打分器手上拿不到上一轮的任何东西`：给上一轮的评语埋哨兵串，再把 `_evaluate` 真正递出去的四样渲染成 prompt，看哨兵在不在 |
| 给 `evaluate` 多递一个 `prior_levels` 参数 | 同上一条，新用例红（它断言打分器收到的键集合精确等于四个） |
| `topic_fidelity` 拿掉，**只看分类闸** | **第一轮没抓住**——`test_三族维度的名单互不重叠` 对孤儿完全免疫：孤儿的毛病不是重叠，是哪个名单都没有它。补了 `test_长文的每一个维度都得有人管`，逐个查长文维度落没落进三个名单 |
| `policy` 取消分流（内在质量照旧进 `steer`） | ✗ 1 条红 |
| `cites_conflict` 永远返回 False | ✗ 1 条红 |
| `template_rows` 永远返回空集 | ✗ 2 条红 |
| 架构图里 `Middleware ×14` 改回 `×13` | **第一轮没抓住**——见下面第三条 |
| **1.7** 撤掉 `raise ScoreParseError`（回到全 0 分） | ✗ 8 条红 |
| 1.7 `judged` 不校验 `level` 值，只要键在就算判过 | ✗ 1 条红（`{"level": "high"}` 那种） |
| 1.7 去掉 `blocked` 那个例外（判据变宽） | ✗ 1 条红 |
| 1.7 判据放宽成「少判一维就算失败」（误伤那一侧） | ✗ 1 条红 |
| 1.7 `_score()` 不再接住 `ScoreParseError`（往上抛） | ✗ 4 条红 |
| 1.7 给 `Evaluation` 加一个 `parse_failed` 字段 | ✗ 1 条红（形态那条） |
| **1.7 撤掉 `_regressed` 的 `st.ev is None` 守卫** | **第一轮没抓住**——见下面第八条 |

*五次「突变没被抓住」：两次是**用例的形态不对**（词法的用例挡不住换名字，
重叠的用例挡不住孤儿），一次是**闸只认一种写法**，一次是**用例摆好了结果
在测实现**（见第六条），一次是**用例根本没走到要测的那行**（见第八条）。
这条规矩这一批又验证了三次。*

### 九个计划里没写到的问题

**① `topic_fidelity` 不是唯一的孤儿。** 把它归位之后，长文两个模式里
**还剩两个**：`spine_fidelity`（note）和 `style_fit`（note · section）。
两个都**明知故留**，理由写在 `test_长文的每一个维度都得有人管` 里：
`spine_fidelity` 实测 1.88–1.96 封顶、几乎从不是最弱那一维（`mechanism-rethink` §1），
真要动它得先解决「计划本身没被验过」；`style_fit` 形状上是内在质量，
但没有实测失败逼出来——**判据宁可窄一点**。名单写死在测试里，
下一个孤儿必须先改那行、先说清楚理由。

**② 4.7 只写「删掉 + 注释」是不够的，因为用例只能是词法的。**
「全仓 grep 不到 `last_scores`」这条用例挡得住原样写回，挡不住
「把上一轮的诊断换个名字塞进 `score_context`」——而后者恰恰是更可能发生的那种
好心。所以补了一条性质级的：**上一轮的评判结果，一个字都不该出现在这一轮的
打分 prompt 里。** 两条留着，一条挡名字，一条挡性质。

**③ 文档闸只认「N 个 X」，认不出架构图里的 `×N`。**
批 1 加 `Ledger` 时把第 7 节的「13 个 middleware」改成了 14，而第 2 节架构图里
那个 `Middleware ×13` 原样留着（连 Ledger 都没进去），`test_doc_counts` 一声不吭
地绿了两批。**闸跑绿不等于闸有用——这次漏的不是数，是一种写法。**
图已补，正则也加了 `×N` 这一种（`tools/ ×21`、`checks/ ×10` 数的是文件不是条目，
词不一样，不会被误伤）。

**④ 三个维度名单分在三个文件里，是分层测试逼的，只能靠对账。**
`repair.INNER_QUALITY` / `loop.COVERAGE_DIMS` / `policy.MATERIAL_DIMS`——
`policy.py` 在 `test_layering` 的 PURE 名单里，不能 import 另外两个，
所以只能各写一份。两条断言钉着它们互不重叠、且不漏人。
`docs/_research/harness-architecture.md` 里仍写着 `last_scores`，
**刻意没改**：那是 2026-09-07 的技术报告快照，开头自己挂着
「结构以 `harness-framework.md` 为准」的免责声明，改它等于伪造一份带日期的报告。

**⑤ 1.4 让 `topic_fidelity` 能排「只修不写」，但它仍然没有位置级探测器。**
`mechanism-rethink` §2 那条断口——「修理工到了现场，但没人告诉他哪里坏了」
——现在多了一个入口：`non_repetition` 的清理轮至少有 `dup_hints` 当候选，
`topic_fidelity` 的清理轮手上只有打分模型写的那句诊断（`focus_note` 进
`revise.edit_user`），没有任何一行代码能指出跑题跑在哪一段。
**这不是不做的理由**（不归位它连一轮修复都排不上），但要记在这儿：
兜底靠的是 `Repair` 已有的 `repair_failed`——修一轮没动分就不再为这一档
花轮次，所以最坏情况是一轮空转，不是 `mechanism-rethink` 里那种打满上限。
真正的修法是 4.5 那一条，而 4.5 现在要覆盖**两**个维度，不是一个。

**⑥ 1.7 不止 `_extract_json` 返回 None 那一条路。** 计划写的是「`_extract_json`
失败 → 每维 level 0」，但同一份全 0 分还有另外两条更阴的来路：**① JSON 解析得
好好的、`scores` 也是个 dict，只是键全换了名**（模型自己发明维度名，或者上游
传错了 `dimensions`）；**② 键对得上、值用不了**（`{"level": "high"}`、
`{"level": 7}`）。两条在老代码里都是静默落回 0。所以判据不能写成「JSON 没解析
出来」，只能写成「**一个维度都没解析出可用的 level**」——三条路一网打尽，
而且对「真判了 0 分」零误伤。

**⑦ `evaluate()` 有第二个调用方，而计划只提了 `loop._score`。**
`database/kb/extract_judge.py` 也直接调它（`test_layering.py:160` 明文允许 kb
用 harness 的打分引擎）。那个文件本来就写着 `except Exception → None`、
汇总时也只算 `evaluation` 非空的——**接口早就是对的，只是打分器从来没走过
那条路**。于是解析失败的全 0 分被算进 `below_bar` 和均值里，
**一次接口抖动被记成「抽取质量差」**，而那个数的全部用途就是拿去调抽取
prompt。1.7 顺手把这个也修了，一行代码没改，只加了注释说明。

**⑧ `_score()` 的 docstring 撒了两批的谎，是突变验逼出来的。**
它写着「返回 `None` 意味着这一轮只是没判：**没有停机条件会触发**」——假的。
`_regressed` 只挡了 `skip_judge`（判据短路那种没判），漏了打分**调用失败**
那种：`st.ev is None` → `rank()` 是 `(-1, -1.0)` → 一比就比最好那轮低 →
当场 `regressed` 收工。而它的武装条件恰恰是「最好那轮只差一个维度没达标」，
**正是最不该因为一次接口抖动收工的时刻**。这跟 1.7 是同一件事的另一半
（上层得把「没打上分」认成没打上分，而不是认成「变差了」），所以一起补了
一行守卫。*注意这条不是 1.7 引进的*：老行为下解析失败是 `(0, 0.0)`，
同样低于武装条件要求的 `best_rank[0] ≥ 2`，同样会 `regressed`——
是 1.7 把它从"看不见"变成"看得见"。剩下的错误路径归计划 11.4。

**⑨ 这一批两次「突变没抓住」都出在用例的写法上，而且是两种不同的写法病。**
第六条：`test_没打上分的一轮排名垫底` 第一版是直接 `st.ev = None` 再断言
`rank() == (-1, -1.0)`——**那钉的是 `rank()` 自己（它本来就对）**，钉不住
「解析失败要走到 `st.ev is None`」，撤掉 1.7 的修复它照样绿。改成从模型返回体
一路走 `_score()` 下来才抓得住。同一个毛病在 `Repair` 那条用例上犯了第二次。
第八条：`test_没打上分的一轮不许被判成质量退步` 第一版用了 `Mode` 默认的
`max_rounds=3` 配 `st.round=3`，而 `_regressed` 上面就有一行
`st.round >= max_rounds → None`——**用例根本没走到要测的那行**，把守卫改坏
它一声不吭地绿。两条都记在用例的 docstring 里了。

### 测出什么

- 后端 **1142 → 1177**（批 3 共 +35：1.3/1.4/1.5/4.7 十九条，1.7 十六条），
  前端 254 / 51 不变。
- 架构文档 `harness-framework.md` 同步四处：架构图 middleware 13 → 14（补 Ledger）、
  Repair 那一行写明两族维度的名单和「孤儿驱动不了修复」这条规则、
  第 8 节补「『没打上分』不是第四种状态而是 `st.ev is None`」、
  第 6 节 `regressed` 那条补「两种没判过都不算变差」、
  第 17 节错误表把打分单列一级。
- **数量闸这次没响**（1.7 没加 middleware / check / 工具），文档是主动补的。
  这正是 `test_doc_counts` 管不到的那一半：它查的是**数**，查不了**行为描述**。

### 下一步

1.6 植入缺陷测 25 个维度的灵敏度（**这一批的五次「突变没抓住」正是它要量的东西**）；
4.5 位置级探测器——`INNER_QUALITY` 三个维度里**有两个**（`coherence` 和
刚归位的 `topic_fidelity`）还是「只能停机、不能驱动修复」，这一条现在要覆盖两个；
11.4 错误路径成体系过一遍——第⑧条挖出来的那种「同一件事只挡住一半」大概率不止这一处
（`trace.error` 回退 / 取消恢复的快照保真两条还没查过）。

## 批 4 · 审查驳回 1.3（2026-09-17）

「审查 agent」对着批 3 的 diff 做对抗性复核，结论是**这批不能过**，主因是 1.3。
我逐条自验之后同意，**把 1.3 从删除路径上摘掉，其余四项（1.4 / 1.5 / 1.7 / 4.7）保留**。

### 为什么只驳回 1.3

它是这一批里**唯一会直接删掉用户看得见的文字**的改动，而三处保护都不成立。

**① 阈值依据是假的（我亲手复现了）**

注释写着「31 篇真实笔记，30.6% 的句子有孪生句，这就是它们现在的样子」。
那 31 篇里有一篇 **47k 字的合成性能探针**（`shot-perf` 的「超长笔记」，
100 个逐字相同、只有周数不同的自动生成小节）。排掉四个夹具用户（`shot-perf` /
`shot-demo` / `harness-test-2` / `cancel-test3`）之后：

| 阈值 | 全部 31 篇 | 排掉夹具（26 篇） |
|---|---|---|
| ≥0.55 | 33.30% | **8.30%** |
| ≥0.62 | 32.35% | **6.58%** |
| ≥0.70 | 31.71% | **5.55%** |
| ≥0.90 | 30.03% | **2.63%** |

两件事：数字差一个数量级；而且**真实笔记上阈值确实有影响**
（0.55 → 0.70 命中掉 33%），不是注释里写的「谷很宽，取哪儿都一样」。
连注释里举的那条「唯一一条真误伤」`[shot-perf-299-A1]` **也出自同一篇夹具**。

**② 破坏 dedup 镜像协议（读代码坐实）**

`hooks/mirror._record_dropped` 只按**段 / 行**两级比较。句子从**一行内部**被剔掉时，
这一段不在 `kept_paras`、它那一行也不在 `kept_lines` → **报整段** →
客户端 `onDedup` 把整段从编辑器里抹掉，而服务端留着修剪后的版本。
用户看到文字消失、到轮末 `STEP_FINISHED` 才跳回来——
正是 `mirror.py` 自己 docstring 里写着要消灭的那类漂移。

**③ 清单兄弟项只盖住一半**

`template_rows` 按前 8 个字分组、一组 ≥3 才豁免。于是 `1. …` / `2. …`
这种编号清单**第 0 个字就分道**，永远凑不成一组；真实笔记里 538 条会参与判重的
清单行只有 **58.4%** 拿得到保护，已经实际删掉过一条。

### 处理

- `outline.py` 的 `drop_already_written` 末尾**不再调**
  `drop_restated_sentences`，原地留了一段注释把三条硬伤逐条记下来。
- **函数本身、它的单测、以及 `repeats.py` 那边只读不删的用法全部保留**——
  它的诊断是对的（段落级看不见段内重复），**接法不对**。
  判据和修订候选那条线不动，因为它不删东西。
- `test_outline.py` 里那条「两遍串起来跑」的断言按这个仓的规矩**故意推翻**，
  并写明重接的前提。

### 审查还查出来的（未阻塞，进待办）

| 级别 | 问题 | 归到 |
|---|---|---|
| P4 | `near_duplicate` 没有**数字守卫**：「第2周…」vs「第1周…」相似度 0.950 判重复；`cites_conflict` 那条只是碰巧带了引文编号才接住 | 重接 1.3 的前提之一 |
| P5 | `_SENT_SPLIT` 的「拼回去等于原文」不变量**没有闸**——把它改回吃掉分隔符的写法，1177 条一条没红 | 同上；补一行 `"".join(pieces)==p` |
| P6 | `_judgeable` 在逐段循环里重算整篇的 `template_rows`，47k 那篇实测占 `restated_ratio` 耗时的 92% | 性能，随手修 |

### 这次验证了什么

**「闸跑绿不等于闸有用」这条，这次是从另一个方向验证的**：批 3 的 14 个突变全做了、
1177 条测试全绿、台账写得很详细——而阈值的**语料**本身是脏的。
**突变测试保证「判据能抓住实现被改坏」，保证不了「判据的依据是真的」。**
从此加一条规矩：**在真实数据上量阈值时，先把夹具 / 探针用户排掉**。

### 下一步

1.6（植入缺陷测 25 个维度的灵敏度）——它正好也是「判据够不够有效」这条线上的。
然后 2.1 / 2.2 / 2.3（账本，不碰 prompt）。
1.3 重接放在补齐 ①②③ + P4 + P5 之后。

## 批 5 · 阶段 1.6：植入缺陷，量 25 个维度的灵敏度（2026-09-17）

**一行产品代码都没改。** 这一批交的是一台评测台 + 一张表：
`backend/scripts/dimension_sensitivity_bench.py`（照 `writing_quality_bench.py` /
`editing_quality_bench.py` 的形状写，跟它们同一个目录、同一套 jsonl 续跑路子）。

方法出自 [IND] §8④（CriticGPT：训练数据就是「人往代码里塞 bug 再写批评」）：
**拿真实产出，机械植入一个已知缺陷，看负责抓它的那一维掉不掉分。**

### 改了什么

| # | 改动 | 落在哪 |
|---|---|---|
| 1.6 | 灵敏度评测台：语料筛选 + 27 个植入器 + 38 条 probe（覆盖全部 25 维）+ 六档结论 | `scripts/dimension_sensitivity_bench.py`（新，约 900 行） |
| — | 它自己的 44 条单测 | `tests/test_dimension_sensitivity_bench.py`（新） |
| — | `test_脚本导得进来` 先把模块挂进 `sys.modules` 再 exec | `tests/test_scripts_import.py` |
| — | 产出目录进 `.gitignore` + 进「bench 产物不许进库」那条闸的名单 | `.gitignore` · `tests/test_scripts_import.py` |
| — | 架构文档补「打分器能看见什么」+ 第 18 节加一行 | `docs/harness-framework.md` |

**语料**（批 4 的新规矩落地）：`select distinct key from harness_runs` 拿到 23 个 key、
对上 19 篇笔记，**排掉 6 篇**——4 篇夹具用户（`shot-demo` 1 篇、`fresh673` 3 篇）、
2 篇真实用户名下标题自标注 `（可删）` 的自测笔记（`harness 测试` 9613 字、`链接测试` 53 字）。
剩 13 篇，本次实际用了 **6 篇**（`terrence` 3 + `terrence-rewrite` 3，810–3072 字）。
夹具名单 15 个用户写死在脚本里、有单测钉着批 4 点名的那 4 个。

**不碰真实笔记**：全程 `sqlite3 ... mode=ro` 只读，植入只在内存里的字符串副本上做，
脚本连 `update_note` 都没 import。

### 测出什么（**852 次真实 `evaluate()` 调用，0 次失败，平均 8.1s/次**）

六篇真实产出 × 38 条 probe × 3 次重复。每一维取它最好的那条 probe：

| 结论 | 维度 | 数（干净 → 植入） |
|---|---|---|
| **抓住**（15 维） | `table_validity` 2.0→0.0 · `no_duplicate_charts` 1.67→0.0 · `no_fabrication` 1.53→0.27 · `factual_grounding` 1.72→0.5 · `honest_caveats` 1.67→0.44 · `spine_fidelity` 2.0→0.83 · `replaces_cleanly` 1.07→0.0 · `non_repetition` 1.0→0.0 · `beat_coverage` 2.0→1.0 · `data_grounding` 1.0→0.0 · `states_limits` 1.67→0.67 · `has_charts` 1.67→0.78 · `fits_context` 1.17→0.42 · `topic_fidelity` 1.07→0.47 · `actionable` 1.78→1.22 | 掉 ≥ 半档 |
| **只动了一点**（5 维） | `follows_prompt` 1.47→1.13（−0.33）· `section_coverage` 1.33→1.08（−0.25）· `answers_the_question` 1.25→1.08（−0.17）· `style_fit` 1.33→1.17（−0.17）· **`material_use` 2.0→1.92（−0.08）** | |
| **基线偏低判不出**（2 维） | `coherence` 0.73→0.40 · `chart_validity` 0.33→0.67 | 干净版本身 < 1.0 |
| **条件从不出现**（1 维） | `numbers_from_tools` **干净版恒为 0.0** | |
| **没抓住**（1 维） | `covers_the_data` **2.0→2.0** | |
| **反着来了**（1 维） | `right_kind` **0.11→2.0** | 植入缺陷之后**涨**了 1.89 |

**三条最硬的**：

**① `material_use` 是真的废了，不是"条件很少出现"。**
`harness-evaluators.md` 留的那个问题（25 次 24 次满分）现在有答案了。
植入器把正文里**每一句带数字或外文名的句子全部剔掉**（剩下的是「谁都能写的通用内容」，
正是判词说的不足），5 篇上 2.0 → **1.93**；把干净正文里的日期/数字摘成一个
【知识库事实】块塞进 context 再判（`with-evidence`），4 篇上 2.0 → **1.92**。
**两种条件下都等于没反应。** 同一次植入里 `beat_coverage` 掉了 0.67——
打分器看得出内容变薄了，只是不往「材料没落进正文」上算。

**② 一整组维度判的是打分器根本看不见的东西。**
`loop._evaluate` 只传正文 + 维度 + `score_context` + `dup_hints`：
**检索到的事实、个人偏好、用户那条指令、工具返回值，一样都没传。**
后果是量得出来的：`numbers_from_tools` 干净版**恒为 0**（追不到工具结果就一律判不达标，
6 篇 12 格没有一格例外）；`chart_validity` 对一张工具画的合法 mermaid 打 0.33；
`style_fit` 在补上偏好档案之后基线反而从 1.33 掉到 0.5（它按我给的档案判，
而真实产出确实不合那份档案）。**这三维的「满分率」以前说明不了任何事，
因为它们从来没拿到判据要求的证据。**

**③ `right_kind` 是反的，而且 6/6 可复现。**
把一张工具画的 `graph LR` 换成**一个根本不存在的图片引用**
`![节点关系示意图](/img/gen/timeline-7f3a.png)`：
`chart_validity` / `data_grounding` / `right_kind` 三维**齐刷刷从 0 涨到 2**，
三篇六次全部一致。判词写着「Insufficient: … a reference to an image that doesn't exist」——
**打分器没有任何办法知道那张图存不存在**，于是「看起来像 render_image 的产物」就给满分，
而真的 mermaid 因为「不知道是不是 render_chart 画的」反被判 0。
这是 5.1/5.2「有 oracle 的模式要确定性化」最直接的一份证据。

**④ `covers_the_data` 一分不掉。** 把 mermaid 里第一条边删掉（正文还在讲那个节点），
3 篇上 2.0 → 2.0。判词说的「the subject of the sentence is missing」正是这个形状。

**⑤ 顺带掉分说明维度之间根本不独立**（这关系到 `rank()` 的不加权折叠，[IND] §5）：
`invent_statistic` 把 `honest_caveats` 打掉 1.33（比它自己的目标维度还狠）；
`off_spine_graft` 顺手把 `style_fit` 打掉 1.33、`non_repetition` 打掉 1.0；
`drop_table_column` 把 `data_grounding` 打掉 1.0。

### 实施中发现的、计划里没写到的

**⑥ `table_validity` 的达标线是一句纯粹能用代码判准的话，而没有一行代码在判它。**
原话「a complete markdown table whose header and rows have matching column counts」——
仓里 `table_present` 只查"有没有表"，`blockcheck.has_table` 只查"表头下面有没有分隔行"，
**两者都不数列**。bench 侧先实现了 `table_column_mismatch` 用来自验植入器，
它可以直接搬进 `checks/`（归 5.x）。

**⑦ 语料本身决定结论，这一点比预想的严重。** 第一版按长度取前 2 篇，量出
`beat_coverage` 2.0→2.0「没抓住」。查下去发现**那两篇的 `beats` 是空的**——
这一维是在"没有节拍可对照"的条件下被打分的。换成"只用真有 spine/beats 的笔记"之后
同一个植入器量到 2.0→1.0 **抓住**。所以脚本里 `spine_fidelity` / `beat_coverage`
用专门的取材器（`whole-with-spine` / `whole-with-beats`），有单测钉着。
**这跟批 4 的教训是同一条**：语料不对，量出来的是语料不是判据。

**⑧ 「没抓住」和「判不出来」必须分成不同的档。** 干净版就已经 0 分时"植入后没掉"
说明不了任何事；干净版 0.5 分时也说明不了。所以结论分六档而不是"抓住/没抓住"两档，
`无从判断`（clean ≤ 0）和 `基线偏低`（clean < 1.0）各自成档——**否则这张表会把
"条件没出现"报成"判据废了"，而这两件事的处理方式正好相反。**

**⑨ `test_脚本导得进来` 加载脚本的方式是错的。** 它 `module_from_spec` 之后直接
`exec_module`，**没先挂进 `sys.modules`**。脚本里只要有一个 `@dataclass` 配
`from __future__ import annotations`，dataclasses 解 `Callable[...] | None` 这类注解时
就会去 `sys.modules[cls.__module__]` 取命名空间，拿到 `None` 当场炸。
这个脚本正常 `import` 得进来，只有那条测试的加载方式炸——**是测试的加载方式不对**。
补了两行（挂上、finally 摘掉）。

### 突变验（18 个，全部变红）

| # | 把什么改坏 | 结果 |
|---|---|---|
| ① | 夹具用户名单退化成空 | ✅ |
| ② | 不再排标题自标注的自测笔记 | ✅ |
| ③ | 取材器没人满足时不再补语料 | ✅ |
| ④ | `mutate` 不再自验"植入成没成形" | ✅ |
| ⑤ | `mutate` 不再检查"干净版本身有没有这个缺陷" | ✅ |
| ⑥ | 复制一段改成只挪位置（不复制） | ✅ |
| ⑦ | 删整节改成只删标题 | ✅ |
| ⑧ | 表格列数判据永远返回 False | ✅ |
| ⑨ | 干净版垫底时报成"没抓住" | ✅ |
| ⑩ | 取消"基线偏低"那一档 | ✅ |
| ⑪ | "反着来了"不再单独报 | ✅ |
| ⑫ | 打分失败那一格被当成真分数 | ✅（**第一版用例没抓住**，见下） |
| ⑬ | 断点续跑不再跳过已完成的格子 | ✅ |
| ⑭ | `spine_fidelity` 改回用没有核心张力的语料 | ✅ |
| ⑮ | "顺带掉分"把目标维度也算进去 | ✅ |
| ⑯ | `roll_up` 取第一条而不是最好的一条 | ✅ |
| ⑰ | `roll_up` 同档不再取掉分更大的 | ✅ |
| ⑱ | "反着来了"排到最前面（当成最好的结论） | ✅ |

**突变验本身踩了一个坑，值得单独记**：第一遍跑完 18 个之后全量 `pytest -q` 红了一条，
而单跑那个文件是绿的。原因是 **`scripts/__pycache__` 里的 `.pyc` 是最后一个突变体的**——
⑱ 那个突变只是把 `VERDICT_RANK` 的元素**换了个顺序**，源文件**字节数一模一样**，
还原又发生在同一秒内，于是 `mtime + size` 这套 pyc 失效判定认不出文件变过。
**"把修复撤掉再撤回来"这个动作本身可能不生效**，而症状是下一次运行才出现。
第二遍跑的时候每个突变体前后都 `rm -rf __pycache__`，18/18 重新确认全部变红。

**⑫ 又犯了批 3 记下的那个毛病：用例不够，不是实现对。**
第一版 `test_打分失败那一格不进统计` 给的错误行**身上没有 scores**——统计本来就会
因为"没有 scores"跳过它，所以把 `r.get("error")` 这道守卫整个删掉，用例照样全绿。
改成"带 error **也带 scores**"的行才钉得住「带 error 的行一律不是一次测量」。

### 闸

后端 **1177 → 1222**（+45：bench 自己的 44 条，外加 `test_脚本导得进来`
按 `scripts/*.py` 参数化自动多出来的 1 条），前端 254 / 51 文件不变。
`test_doc_counts` / `test_directory_map` 没响（没加 Mode / check / middleware / 工具），
架构文档是主动补的两处。

### 这一批**没做**什么

- **一个维度的判词都没改。** 这一批只负责"量出来"，改判词是各自对应的条目
  （`material_use` → 2.6；`numbers_from_tools` / `data_grounding` → 5.1/5.2；
  `fits_context` → 4.1；`follows_prompt` / `answers_the_question` → 6.1）。
- **没有删维度。** 计划第 4 节写着"不加新评分维度"，删也同理要单独决定——
  `covers_the_data` 和 `right_kind` 现在有证据了，但那是下一步的事。

### 还没量到的

- `table_validity` / `data_grounding`(table) / `beat_coverage` / `numbers_from_tools`(改数字)
  这几行 **n=1 篇**：13 篇真实语料里带 markdown 表的只有 1 篇、带 beats 的只有几篇。
  结论方向可信（掉 2.0 / 1.0 这种幅度不是噪声），但**样本量要如实记着**。
- `eda` / `analysis` 两个模式在真实语料里**没有产出可取**，用的是真实笔记里的
  数字密集小节当"块"。内容是真的，形态是近似的。
- 每格只重复 3 次。`chart/handwrite_mermaid` 那条方差明显（同一篇 0/2/0 vs 2/0/2），
  单看它不能下结论。

### 下一步

2.6（`material_use` 改成可计算）现在有了最硬的证据，应当**排在 2.1–2.3 前面**：
它不是"满分说明不了什么"，是"把材料全剔光也给满分"。
接着 5.1 / 5.2（`data_grounding` / `numbers_from_tools` 确定性化）——③④⑥ 三条
指的是同一件事：**图表这一组的判词全在问打分器看不见的东西**，
而这三个模式恰恰有执行 oracle。`table_column_mismatch` 可以直接搬进 `checks/`。
然后 4.1（`score_context` 补给 block 模式）——`fits_context` 在补上前后文之后
从"基线偏低判不出"变成"抓住（1.17→0.42）"，这条的收益已经量出来了。

## 批 6 · 审查驳回批 5 的结论（台子留着）（2026-09-17）

审查 agent 复核批 5，结论**不能原样过**：台子本身值得留（形状对、断点续跑对、
852 次调用能跟 `llm_usage` 表逐行对账），**但那张灵敏度表里至少 5 条结论不能当依据**
——其中 2 条正是下一批要动 `material_use` / `data_grounding` 的依据。
三条最重的我逐条自验，全部属实。

### ① 语料污染，第二次，而且这次躲在真实 user_id 底下

批 5 的「13 篇干净语料」里有 6 篇出自**同一次 `soak.py` 压测**；本次用的 6 篇里有 3 篇是。

自验：`47b046adafcb` / `12e024b55823` 的 `writing_sections` → plan
`0e1480636763` → `parent_note_id` 的标题是 **`soak-整理一份众筹前后`**，
正是 `soak.py:123` 的 `f"soak-{goal[:8]}"` 配上 `PLAN_GOALS` 里那条 goal。
`1da5a3c9767b` 同签名（同 goal、parent 已删）。

**去掉这 3 篇重算，4 条结论翻转**：`actionable` 抓住 → 没抓住；
`chart_validity` 基线偏低 → 无从判断；`answers_the_question` / `follows_prompt`
只动了一点 → 抓住。

**这条连带影响批 2**：我量到段内重复 42.9% / 34.6% 的那两篇
（`1da5a3c9767b` / `06647b9c2031`）里，至少 `1da5a3c9767b` 是 soak 产出。
*严格说它仍是「harness 在真实知识库上的真实产出」，不是 `shot-perf` 那种合成夹具；
但三篇最坏的出自同一个 goal，说明那个数反映的是**某一个种子**，不是 harness 的普遍表现。*
批 2 的阈值本身不受影响（0.62 落在双峰之间的宽谷，15/18 精确为 0），
受影响的是**严重程度那个数**。

### ② `material_use` 的头条证据不成立（两半都不成立）

- **as-deployed 那一半**：`modes.py:186` 的判词原文是
  「**没给材料就算达标**」——不传事实块时打 2/2 是**判词规定的正确行为**，
  不能当「判据废了」的证据。
- **with-evidence 那一半**：植入器 `inj_strip_specifics` **跳过所有以 `#` / `|`
  开头、或含 ``` 的段落**。真实笔记里标题和正文常常不隔空行，于是整节带日期的
  正文被当成「标题段」留下——实测残留率 11–14%，一篇的 dirty 版里
  **整张带 5 个日期的 mermaid 时间线原封不动**。
  「把材料全剔光」这句话不成立，真正干净的证据只剩 1 篇 × 3 次。

### ③ `covers_the_data`「没抓住」是空的

判词要的是「**句子里提到的分组要画全，the subject of the sentence is missing**」。
而植入器删的那条边，**三篇正文里没有一篇提到过那个节点**——打分器判 2.0 是对的，
没东西可抓。

### ④ `right_kind` 那条「三维齐刷刷 0→2」只有一维成立

读判词原文：`chart_validity` 明写「…**or render_image (a markdown image
reference)**」，`data_grounding` 明写「**Not applicable when the image is
illustrative**」——判 2 **都是判词允许的**。只有 `right_kind`
（"using text-to-image for what should be exact"）是真的反了，9/9 一致。

另外两维该归到另一类问题：**判词写了打分器验不了的条件**
（「a reference to an image that doesn't exist」——打分器手里只有正文，
它无从知道那个文件在不在）。处理方式跟「判据反了」完全不同。

### ⑤ 27 个植入器里有 13 个没有任何闸

审查把 `inj_drop_chart_series` 换成**恒等函数**（什么都不植入），
**44 条单测全绿存活**。植入器是整个 bench 的承重墙——它要是没植入声称的缺陷，
整张表都是空的。

### ⑥ 「掉 ≥ 半档算抓住」这条线是拍的

审查拿 852 条日志做 permutation（打乱 clean/dirty 标签重算）：
**|掉分| ≥ 0.5 的概率就有 10.1%**；38 条 probe 里按纯噪声就该有约 4 行越线。
同一格 3 次重复有 **26.5% 不一致、3.8% 跨满量程 0↔2**。
逐行 p 值算完，`p ≥ 0.05` 的有 20 行——包括全部三条 n=1 行和全部 5 条「只动了一点」。

---

### 这次定下来的规矩（比上次那条更进一步）

批 4 定的是「量阈值先排掉夹具用户」。这次证明**那条不够**：

> **「真实产出」不等于「用户写的」。** 这个仓里三类东西长得一样：
> ① 用户真的写的；② `soak` / `suite` / bench 这些脚本**用真实 user_id 跑出来的**；
> ③ `shot-perf` 那种纯合成夹具。
> 量任何东西之前必须三类分开，而**按 user_id 和标题筛只能挡住 ①③ 之间**。
>
> **结构性修法**：抽一个共用的语料筛选器（按 `writing_sections` → plan →
> parent 标题 `soak-*` / `suite-*` 这类血缘判），所有测量脚本共用一份、有单测钉着，
> 不要每个脚本各写一份 `FIXTURE_USERS`。

### 能当依据的 / 不能当依据的（下一批要照着办）

**可以当依据**：`right_kind` 反了（9/9，判词明文禁止）；
`numbers_from_tools` 干净版恒 0（24/24）；以及掉分 ≥0.9 且 p<0.01 的 7 条
（`no_duplicate_charts` / `no_fabrication` / `factual_grounding`(fabricate) /
`honest_caveats` / `replaces_cleanly` / `non_repetition` / `states_limits`）。

**不能当依据**：`material_use` 两半（判词规定 + 植入没成形）、
`covers_the_data` 没抓住（植入的不是那个缺陷）、
`data_grounding`(table) 抓住（n=1、干净版 [0,2,1]、p=0.40）、
`chart_validity`/`data_grounding` 在图片引用上的 0→2（判词明文允许）、
`actionable` 抓住（去掉 soak 残留后翻转）。

### 下一步

批 7 做整改（不是重写脚本）：
① 抽共用语料筛选器（带血缘判）并重算；② 修 `inj_strip_specifics` 的 `#`/`|` 直通，
单测夹具换成「标题正文不隔空行」的真实形状；③ 换一个真能造出 `covers_the_data`
缺陷的植入器；④ 13 个没闸的植入器补自验；⑤ 台账那张表补上被 `roll_up` 洗掉的
4 条「没抓住」和逐行 p 值。
**2.6 / 5.1 / 5.2 要等整改完再动**——现在的依据不牢。

## 批 7 · 整改批 4 / 批 6 两次驳回（2026-09-17）

**一行产品代码都没改**（跟批 5 一样，这一批交的是台子和一张表）。
批 6 判的是「台子留着、那张表里至少 5 条结论不能当依据」，五件事逐条落地。

### 改了什么

| # | 改动 | 落在哪 |
|---|---|---|
| ① | **带血缘判的共用语料筛选器**：把笔记分成 `user` / `script` / `fixture` 三类并说明理由 | `scripts/corpus_lineage.py`（新，238 行）+ `tests/test_corpus_lineage.py`（新，21 条） |
| ① | bench 改成调它，自己那份 `FIXTURE_USERS` 删掉 | `scripts/dimension_sensitivity_bench.py` |
| ② | `inj_strip_specifics` 改成**按行走**，围栏块 / 表格块整块处理；单测夹具换成「标题正文不隔空行 + 带日期的 mermaid + 带数字的表」的真实形状 | 同上 + `tests/` |
| ② | `inj_strip_caveats` / `inj_strip_next_steps` 同一个毛病，一起改 | 同上 |
| ③ | `drop_chart_series` → **`drop_mentioned_node`**：只删「标签在正文里逐字出现过」的节点，配套新取材器 `chart-block-narrated` | 同上 |
| ④ | 27 个植入器**每个都有自验闸**（单边 `gate` 或成对 `verify`），没闸的**构造时直接抛** | 同上 |
| ⑤ | 逐行 permutation p 值 + 按实测噪声标定「算抓住」那条线 + `washed_out()` 把被 `roll_up` 洗掉的失败行单列 + `VERDICT_RANK` 把「未跑」挪到最后 | 同上 |
| — | 格子的身份里加正文指纹（实施中撞出来的，见下） | 同上 |
| — | 架构文档第 4 节和第 18 节按重算后的结论改写，第 18 节加「语料血缘」一行 | `docs/harness-framework.md` |

### ① 筛选器怎么判血缘

判据只认**具体的生成器签名**，不做任何「看起来像测试」的推断；判不出来的一律留在 `user`。

```
fixture  user_id ∈ 15 个夹具用户（shot-perf / shot-demo / cancel-test3 / fresh67x …）
script   user_id ∈ 5 个脚本用户（writing-bench / editing-bench / quality-sample …）
script   标题前缀逐字来自脚本里的那个 f-string（soak- / suite- / writing- / editing- / 质量采样- / 📋 写作追踪）
script   标题自标注（（可删）/ ^harness 测试 / ^链接测试）
script   血缘：writing_sections.note_id → plan_id → writing_plans.parent_note_id → 那篇笔记的标题以 `soak-` 开头
script   血缘：writing_plans.goal 逐字等于 soak.PLAN_GOALS 之一（parent 被 soak 清理掉时唯一的线索）
user     以上都不命中
```

**`user` / `script` / `fixture` 不是三个好听的名字，是三种不同的用法**：
`fixture` 连模型都没过（批 4 那篇 47k 探针是 100 个逐字相同的小节），拿它量任何跟
文字质量有关的数都是纯噪声；`script` 的**形态**是真的、**分布**不是（三篇最坏的可以
出自同一个 goal）；只有 `user` 能用来量判据和阈值。

`test_corpus_lineage.py` 里两条线索**各自单独钉一条**（parent 标题那条、goal 那条），
外加一条「`SOAK_PLAN_GOALS` 必须逐字等于 `soak.PLAN_GOALS`」，和一条在真库上跑的
端到端（库是 gitignore 的，没库自动跳过）。

**筛出来的结果**：跑过 harness 的 19 篇里，`user` 只剩 **5 篇**（全是 `terrence` 自己的），
排掉 14 篇 = `script` 10 + `fixture` 4。批 5 用的 6 篇里有 3 篇（`47b046adafcb` /
`12e024b55823` / `1da5a3c9767b`）这次被判成 `script`，852 次调用里的 **462 次因此作废**。

### 重算：日志怎么用的

**没有重跑那 852 次。** 老日志按格子逐条迁移：`clean` 臂的正文只由取材器决定，
取材器没动的一律留着；`dirty` 臂只有改过的那几个植入器要作废。
最后 **318 行沿用、264 格新跑**（本批真实 `evaluate()` 调用 **264 次，0 次失败**），
现在这张表建立在 **582 次调用**上。

### 重算后的结论，哪几条变了

| 维度 | 批 5 说 | 批 6 驳回 | 批 7 重算 |
|---|---|---|---|
| `material_use` | 判据废了（2.0→1.93）| 两半都不成立 | **抓住**（with-evidence 2.0→0.89，n=3，p=0.003）——植入器修好之后它是灵敏的 |
| `covers_the_data` | 没抓住（2.0→2.0）| 植入的不是那个缺陷 | 换植入器后 2.0→0.67，但**只剩 1 篇真实语料带图**，p=0.10，报「掉了但不显著」 |
| `actionable` | 抓住 | 去掉 soak 后翻转成没抓住 | 0.56，p=0.053，**「只动了一点」** |
| `right_kind` | 反了（0.11→2.0）| 可以当依据（9/9）| 方向还在（0.33→2.0，6/6 一致），但 n=1 篇、p=0.10，**降级成不能当硬依据** |
| `no_fabrication` | 抓住（1.53→0.27）| — | **基线偏低**（干净版 0.89 < 1.0），这一档说明不了判据灵不灵 |
| `factual_grounding` | 抓住 | — | 仍抓住，而且是全表最硬的两条之一（fabricate n=5 p=0.0005） |
| `chart_validity` | 基线偏低 / 反了 | 判词允许图片引用 | **无从判断**（干净版恒 0）+ 手写 mermaid 那条**未跑** |
| `follows_prompt`(with-evidence) | 只动了一点 | — | **没抓住**（0.0，n=3，p=1.0）——原来被 `roll_up` 洗掉了，现在单列 |
| `numbers_from_tools` | 干净版恒 0 | 可以当依据 | 不变：3 篇 18 次一格没有例外 |

**一句话**：批 6 点名「不能当依据」的 5 条里，`material_use` 是**植入器的错不是判据的错**
（修好后翻转成抓住）、`covers_the_data` 同理（换植入器后掉了 1.33），
`actionable` / `data_grounding`(table) / `chart_validity` 三条确认不能当依据。
**批 5 说的「25 维里 15 维抓住」在真实用户语料上只剩 9 维**，
其余 16 维分布在「掉了但不显著 5 / 只动了一点 6 / 基线偏低 3 / 无从判断 2」四档里。

### ⑤ 那条线是怎么标定的

拿现在这份日志的 37 行，每行把 clean/dirty 标签**在同一篇之内**打乱重算 400 次
（共 14800 个纯噪声掉分）：

* **纯噪声下 |掉分| ≥ 0.5 的比例 = 12.5%**（批 6 在老日志上量到 10.1%，同量级）——
  「掉 ≥ 半档算抓住」那条线本身就有八分之一的概率被噪声越过。
* 95% 分位数 = **0.89**，`CAUGHT` 从 0.5 改成 0.89。
* 逐行还要过 **p < 0.05**（permutation，4000 次重排，固定种子 20260917）。
  过不了的单独报「掉了但不显著」，**不许报成「没抓住」**——那是两件事，处理方式相反。
* 一条硬事实：**n=1 篇 × 3 次重复时排列总数只有 C(6,3)=20，两侧 p 最小就是 0.10**。
  所以全部 5 条「掉了但不显著」都是 n=1 行，它们**在数学上不可能显著**，
  要么补语料、要么加重复次数，光看掉分没有意义。

### 重算后的灵敏度全表（**逐条 probe，n 和 p 都在**）

### 灵敏度（逐条 probe，**这张表才是原始结论**）

| 维度 | probe | 条件 | 干净 | 植入 | 掉分 | 篇 | 次 | p | 结论 |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| `beat_coverage` | note/drop_last_section | as-deployed | 1.5 | 0.5 | 1.0 | 2 | 12 | 0.006 | 抓住 |
| `factual_grounding` | note/shift_dates | with-evidence | 1.33 | 0.0 | 1.33 | 3 | 18 | 0.006 | 抓住 |
| `factual_grounding` | note/fabricate_specifics | as-deployed | 1.67 | 0.47 | 1.2 | 5 | 30 | 0.0005 | 抓住 |
| `honest_caveats` | eda/strip_caveats | as-deployed | 2.0 | 1.0 | 1.0 | 2 | 12 | 0.006 | 抓住 |
| `material_use` | note/strip_specifics | with-evidence | 2.0 | 0.89 | 1.11 | 3 | 18 | 0.0032 | 抓住 |
| `non_repetition` | note/duplicate_paragraph | as-deployed | 1.27 | 0.0 | 1.27 | 5 | 30 | 0.0002 | 抓住 |
| `replaces_cleanly` | custom/lead_in | as-deployed | 1.78 | 0.0 | 1.78 | 3 | 18 | 0.0005 | 抓住 |
| `spine_fidelity` | note/off_spine_graft | as-deployed | 2.0 | 1.0 | 1.0 | 2 | 12 | 0.006 | 抓住 |
| `states_limits` | analysis/strip_caveats | as-deployed | 2.0 | 0.67 | 1.33 | 2 | 12 | 0.006 | 抓住 |
| `topic_fidelity` | section/off_spine_graft | as-deployed | 1.25 | 0.0 | 1.25 | 4 | 24 | 0.0002 | 抓住 |
| `covers_the_data` | eda/drop_mentioned_node | as-deployed | 2.0 | 0.67 | 1.33 | 1 | 6 | 0.1025 | 掉了但不显著 |
| `has_charts` | eda/chart_to_prose | as-deployed | 1.33 | 0.33 | 1.0 | 1 | 6 | 0.3042 | 掉了但不显著 |
| `no_duplicate_charts` | eda/duplicate_chart | as-deployed | 1.0 | 0.0 | 1.0 | 1 | 6 | 0.4154 | 掉了但不显著 |
| `right_kind` | chart/chart_to_image | as-deployed | 0.33 | 2.0 | -1.67 | 1 | 6 | 0.1025 | 掉了但不显著 |
| `table_validity` | table/drop_table_column | as-deployed | 1.33 | 0.0 | 1.33 | 1 | 6 | 0.4041 | 掉了但不显著 |
| `actionable` | eda/strip_next_steps | as-deployed | 2.0 | 1.44 | 0.56 | 3 | 18 | 0.053 | 只动了一点 |
| `answers_the_question` | analysis/answer_swap | as-deployed | 1.0 | 0.44 | 0.56 | 3 | 18 | 0.1685 | 只动了一点 |
| `answers_the_question` | analysis/answer_swap | with-evidence | 1.33 | 1.0 | 0.33 | 3 | 18 | 0.3079 | 只动了一点 |
| `factual_grounding` | note/shift_dates | as-deployed | 1.44 | 0.56 | 0.89 | 3 | 18 | 0.0095 | 只动了一点 |
| `factual_grounding` | note/placeholder | as-deployed | 1.6 | 1.53 | 0.07 | 5 | 30 | 1.0 | 只动了一点 |
| `fits_context` | eda/heading_flood | with-evidence | 1.11 | 0.33 | 0.78 | 3 | 18 | 0.0035 | 只动了一点 |
| `follows_prompt` | prompt/answer_swap | as-deployed | 1.67 | 1.11 | 0.56 | 3 | 18 | 0.0687 | 只动了一点 |
| `material_use` | note/strip_specifics | as-deployed | 2.0 | 1.58 | 0.42 | 4 | 24 | 0.0482 | 只动了一点 |
| `section_coverage` | section/truncate_bodies | as-deployed | 1.33 | 1.08 | 0.25 | 4 | 24 | 0.3457 | 只动了一点 |
| `style_fit` | note/audit_voice | as-deployed | 2.0 | 1.83 | 0.17 | 2 | 12 | 1.0 | 只动了一点 |
| `style_fit` | note/audit_voice | with-evidence | 1.17 | 1.0 | 0.17 | 2 | 12 | 1.0 | 只动了一点 |
| `topic_fidelity` | section/swap_section_bodies | as-deployed | 1.22 | 1.22 | 0.0 | 3 | 18 | 1.0 | 只动了一点 |
| `coherence` | note/double_ending | as-deployed | 0.8 | 0.47 | 0.33 | 5 | 30 | 0.021 | 基线偏低 |
| `data_grounding` | table/invent_table_cells | as-deployed | 0.67 | 0.0 | 0.67 | 1 | 6 | 0.3854 | 基线偏低 |
| `fits_context` | eda/heading_flood | as-deployed | 0.56 | 0.33 | 0.22 | 3 | 18 | 0.3952 | 基线偏低 |
| `no_fabrication` | prompt/fabricate_specifics | as-deployed | 0.89 | 0.22 | 0.67 | 3 | 18 | 0.2984 | 基线偏低 |
| `chart_validity` | chart/break_mermaid_fence | as-deployed | 0.0 | 0.0 | 0.0 | 1 | 6 | 1.0 | 无从判断 |
| `coherence` | note/heading_levels | as-deployed | 0.0 | 0.17 | -0.17 | 2 | 12 | 1.0 | 无从判断 |
| `data_grounding` | chart/shift_dates | as-deployed | 0.0 | 0.0 | 0.0 | 1 | 6 | 1.0 | 无从判断 |
| `numbers_from_tools` | eda/invent_statistic | as-deployed | 0.0 | 0.0 | 0.0 | 3 | 18 | 1.0 | 无从判断 |
| `numbers_from_tools` | eda/scramble_numbers | as-deployed | 0.0 | 0.0 | 0.0 | 1 | 6 | 1.0 | 无从判断 |
| `follows_prompt` | prompt/answer_swap | with-evidence | 1.67 | 1.67 | 0.0 | 3 | 18 | 1.0 | 没抓住 |
| `chart_validity` | chart/handwrite_mermaid | as-deployed |  |  |  | 0 | 0 |  | 未跑 |

### 每一维的最终结论（取它最好的那条 probe）

| 维度 | 最好的 probe | 干净 | 植入 | 掉分 | 篇 | 次 | p | 结论 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `beat_coverage` | note/drop_last_section·as-deployed | 1.5 | 0.5 | 1.0 | 2 | 12 | 0.006 | 抓住 |
| `factual_grounding` | note/shift_dates·with-evidence | 1.33 | 0.0 | 1.33 | 3 | 18 | 0.006 | 抓住 |
| `honest_caveats` | eda/strip_caveats·as-deployed | 2.0 | 1.0 | 1.0 | 2 | 12 | 0.006 | 抓住 |
| `material_use` | note/strip_specifics·with-evidence | 2.0 | 0.89 | 1.11 | 3 | 18 | 0.0032 | 抓住 |
| `non_repetition` | note/duplicate_paragraph·as-deployed | 1.27 | 0.0 | 1.27 | 5 | 30 | 0.0002 | 抓住 |
| `replaces_cleanly` | custom/lead_in·as-deployed | 1.78 | 0.0 | 1.78 | 3 | 18 | 0.0005 | 抓住 |
| `spine_fidelity` | note/off_spine_graft·as-deployed | 2.0 | 1.0 | 1.0 | 2 | 12 | 0.006 | 抓住 |
| `states_limits` | analysis/strip_caveats·as-deployed | 2.0 | 0.67 | 1.33 | 2 | 12 | 0.006 | 抓住 |
| `topic_fidelity` | section/off_spine_graft·as-deployed | 1.25 | 0.0 | 1.25 | 4 | 24 | 0.0002 | 抓住 |
| `covers_the_data` | eda/drop_mentioned_node·as-deployed | 2.0 | 0.67 | 1.33 | 1 | 6 | 0.1025 | 掉了但不显著 |
| `has_charts` | eda/chart_to_prose·as-deployed | 1.33 | 0.33 | 1.0 | 1 | 6 | 0.3042 | 掉了但不显著 |
| `no_duplicate_charts` | eda/duplicate_chart·as-deployed | 1.0 | 0.0 | 1.0 | 1 | 6 | 0.4154 | 掉了但不显著 |
| `right_kind` | chart/chart_to_image·as-deployed | 0.33 | 2.0 | -1.67 | 1 | 6 | 0.1025 | 掉了但不显著 |
| `table_validity` | table/drop_table_column·as-deployed | 1.33 | 0.0 | 1.33 | 1 | 6 | 0.4041 | 掉了但不显著 |
| `actionable` | eda/strip_next_steps·as-deployed | 2.0 | 1.44 | 0.56 | 3 | 18 | 0.053 | 只动了一点 |
| `answers_the_question` | analysis/answer_swap·as-deployed | 1.0 | 0.44 | 0.56 | 3 | 18 | 0.1685 | 只动了一点 |
| `fits_context` | eda/heading_flood·with-evidence | 1.11 | 0.33 | 0.78 | 3 | 18 | 0.0035 | 只动了一点 |
| `follows_prompt` | prompt/answer_swap·as-deployed | 1.67 | 1.11 | 0.56 | 3 | 18 | 0.0687 | 只动了一点 |
| `section_coverage` | section/truncate_bodies·as-deployed | 1.33 | 1.08 | 0.25 | 4 | 24 | 0.3457 | 只动了一点 |
| `style_fit` | note/audit_voice·as-deployed | 2.0 | 1.83 | 0.17 | 2 | 12 | 1.0 | 只动了一点 |
| `coherence` | note/double_ending·as-deployed | 0.8 | 0.47 | 0.33 | 5 | 30 | 0.021 | 基线偏低 |
| `data_grounding` | table/invent_table_cells·as-deployed | 0.67 | 0.0 | 0.67 | 1 | 6 | 0.3854 | 基线偏低 |
| `no_fabrication` | prompt/fabricate_specifics·as-deployed | 0.89 | 0.22 | 0.67 | 3 | 18 | 0.2984 | 基线偏低 |
| `chart_validity` | chart/break_mermaid_fence·as-deployed | 0.0 | 0.0 | 0.0 | 1 | 6 | 1.0 | 无从判断 |
| `numbers_from_tools` | eda/invent_statistic·as-deployed | 0.0 | 0.0 | 0.0 | 3 | 18 | 1.0 | 无从判断 |

### 被上面那张表洗掉的失败行（**必须跟着一起读**）

| 维度 | probe | 干净 | 植入 | 掉分 | 篇 | 次 | p | 结论 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `follows_prompt` | prompt/answer_swap·with-evidence | 1.67 | 1.67 | 0.0 | 3 | 18 | 1.0 | 没抓住 |

### 顺带掉分（误伤 / 维度之间不独立）

| probe | 被顺带打低的维度 | 干净 | 植入 | 掉分 |
|---|---|---:|---:|---:|
| custom/paragraph/lead_in/as-deployed | `no_fabrication` | 1.78 | 0.0 | 1.78 |
| eda/numeric-block/invent_statistic/as-deployed | `honest_caveats` | 1.44 | 0.11 | 1.33 |
| note/whole-with-spine/off_spine_graft/as-deployed | `non_repetition` | 1.83 | 0.5 | 1.33 |
| custom/paragraph/lead_in/as-deployed | `follows_prompt` | 1.67 | 0.44 | 1.22 |
| note/whole/double_ending/as-deployed | `non_repetition` | 1.47 | 0.4 | 1.07 |
| note/whole-with-spine/off_spine_graft/as-deployed | `style_fit` | 1.5 | 0.5 | 1.0 |
| eda/chart-block-narrated/drop_mentioned_node/as-deployed | `honest_caveats` | 2.0 | 1.0 | 1.0 |
| eda/chart-block-narrated/drop_mentioned_node/as-deployed | `has_charts` | 2.0 | 1.0 | 1.0 |
| table/table-block/invent_table_cells/as-deployed | `fits_context` | 2.0 | 1.0 | 1.0 |
| note/whole/strip_specifics/as-deployed | `beat_coverage` | 1.67 | 0.75 | 0.92 |

### 实施中发现的、计划里没写到的

**⑥ 改了植入器之后断点续跑会拿旧数据当新数据。** 老的格子 key 是
`笔记|probe|arm|重复次数`——`strip_specifics` 修完之后同一个 key 指向的已经是
**完全不同的一段正文**，而续跑只看 key。于是「修好的植入器」和「没修的旧分数」
会被拼进同一张表，**毫无症状**。现在 key 里带正文 + 上下文的 sha1 指纹，
正文或 context 一变那一格自动重跑，没变的一格钱也不白花；
统计也只认「现在这套取材 + 植入能重现出来的格子」，作废多少行会打印出来。

**⑦ `_TABLE_BLOCK` 漏掉表格的最后一行。** 正则写死了行尾 `\n`，而
`603dca25403a` 那张真实的表**就在正文结尾、最后一行没有换行**——于是
`drop_table_column` / `invent_table_cells` 都只改到了半张表，
bench 侧那个 `table_column_mismatch`（5.x 要搬进 `checks/` 的那个）也只数了半张。
**是批 7 新加的成对自验把它顶出来的**：`invent_table_cells` 的闸报「植入没成形」，
查下去才发现是取材就取错了。这条直接影响「`table_validity` 抓住」那一行的可信度。

**⑧ `inj_duplicate_paragraph` 把复制品插错了地方。** 它用
`text.replace(tail, src + "\n\n" + tail, 1)`，换的是 `tail` 的**第一次**出现；
`06647b9c2031` 那篇（段内重复本来就严重）里最后一段的文字在正文中段也出现过，
于是复制品被塞进别人的段落中间，拼成一段四不像——「逐字复制了一整段」这句话不成立。
改成按最后一次出现插。

**⑨ 「判据宁可窄一点」在这一批是有代价的，而且代价要说出来。**
只留 `user` 之后语料从 13 篇掉到 5 篇，其中**只有 1 篇带 mermaid、1 篇带 markdown 表**。
后果是图表那一组（`chart_validity` / `right_kind` / `has_charts` /
`no_duplicate_charts` / `covers_the_data` / `table_validity` / `data_grounding`）
**全部 n=1**，数学上做不出显著。这不是判据的问题，是**没有真实用户的图表产出可用**——
要量准这一组，得先有一批真实语料，不能靠 soak 凑。

### 突变验（24 个，全部变红）

每个突变体前后都 `rm -rf __pycache__`（批 5 踩过：只换元素顺序的突变体字节数一样、
`mtime + size` 认不出文件变过，症状在下一次运行才出现）。

| # | 把什么改坏 | 结果 |
|---|---|---|
| ① | 夹具用户名单退化成空 | ✅ |
| ② | 不再看 plan parent 标题（`soak-` 前缀）| ✅（**第一版用例没抓住**，见下） |
| ③ | 不再看 soak 的 goal 常量（parent 已删那条线索）| ✅ |
| ④ | `SOAK_PLAN_GOALS` 跟 `soak.py` 脱钩 | ✅ |
| ⑤ | 脚本写死的标题前缀不认了 | ✅ |
| ⑥ | bench 里又长出自己一份夹具名单 | ✅ |
| ⑦ | `strip_specifics` 撤回上一版（按段落走、`#` / `\|` / 围栏整段直通）| ✅（**第一版突变体没改到真东西**，见下） |
| ⑧ | 围栏块（mermaid）原样留下 | ✅ |
| ⑨ | 「还剩不剩具体材料」恒说干净了 | ✅ |
| ⑩ | 删图里第一条边（不看正文点没点名）| ✅ |
| ⑪ | `mentioned_nodes` 不再要求正文提过 | ✅ |
| ⑫ | `Injector` 允许没有闸 | ✅ |
| ⑬ | `mutate` 不再跑成对自验 | ✅（22 条红） |
| ⑭ | 某个 `verify` 恒为真（等于没闸）| ✅ |
| ⑮ | `duplicate_paragraph` 改回插在第一次出现处 | ✅（**第一版用例没抓住**，见下） |
| ⑯ | `_TABLE_BLOCK` 改回写死行尾换行 | ✅ |
| ⑰ | 「未跑」排回「没抓住」前面 | ✅ |
| ⑱ | 被 `roll_up` 洗掉的失败行不再报 | ✅ |
| ⑲ | p 值不再影响结论 | ✅ |
| ⑳ | p 值可以是 0 | ✅ |
| ㉑ | 噪声标定恒返回 0 | ✅ |
| ㉒ | 格子身份里不带正文指纹 | ✅ |
| ㉓ | 打分失败那一格被当成真分数 | ✅ |
| ㉔ | 排列检验跨篇打乱 | ✅（**第一版用例没抓住**，见下） |

**四个漏网，全部是「用例不够」，不是「实现对」**（批 3 / 批 5 记下的同一条）：

* **②**：钉 soak 的那条用例给的血缘**两条线索同时成立**（parent 标题是 `soak-…`、
  goal 也在名单里），砍掉任一条另一条都兜得住。补了一条**只有 parent 标题成立**的
  （soak 以后换了 goal 就是这种）。
* **⑦**：第一版突变体把标题行和表格行改成无条件直通——但表格分支在循环里排在标题
  分支**前面**，那半句代码根本执行不到；而夹具里的标题又都不带数字，改了等于没改。
  换成**把 `inj_strip_specifics` 整个函数体撤回上一版**才是真的撤回修复。
* **⑮**：夹具里「重复出现的那句话」正好在段首，插在它前面复制品照样自成一段。
  改成让它出现在**段落中间**。
* **㉔**：第一版用「跨篇打乱之后 p 变大还是变小」去判，而跨篇打乱在那份数据上
  正好也给出同一个结论。换成钉**不变性**：把某一篇的两臂同时加一个常数
  （它的掉分一点没变），p 必须一点不变——跨篇打乱做不到这件事。

### 闸

后端 **1222 → 1319**（+97：`test_corpus_lineage.py` 新增 21 条；
`test_dimension_sensitivity_bench.py` 44 → 119 条（+75，主要是植入器按 27 个
参数化、正反各一轮 = 54 条）；`test_脚本导得进来` 按 `scripts/*.py` 参数化
自动多出 1 条）。
前端 51 文件 / 254 条不变。`test_doc_counts` / `test_directory_map` /
`test_architecture_claims` 没响（没加 Mode / check / middleware / 工具）。

### 这一批**没做**什么

- **一个维度的判词还是一个字都没改。** 2.6 / 5.1 / 5.2 的依据现在才算立住。
- **没有删维度。**
- **没有回头改批 2 的那个「严重程度」数。** 它受同一条血缘污染影响
  （`1da5a3c9767b` 是 soak 产出），阈值本身不受影响，但那个数该在共用筛选器上重算一遍。

### 下一步

1. **2.6 现在的依据反过来了**：`material_use` 不是废了，是**生产从不把事实块传给
   打分器**（`as-deployed` 判 2.0 是判词规定的）。所以这一条应当并进 4.1/5.x
   那条线——**先把证据传给打分器**，而不是改判词。
2. **5.1 / 5.2 的依据最硬的一条还在**：`numbers_from_tools` 干净版恒 0（3 篇 18 次）。
   `chart_validity` 干净版也恒 0。`table_column_mismatch` 可以搬进 `checks/`
   （⑦ 修好之后它才是对的）。
3. **补语料**：图表那一组全部 n=1，现在做不出任何显著结论。要么等真实用户产出，
   要么把每格重复次数提到 5 次以上（C(10,5)=252，两侧 p 最低 0.008）。
   **这是下一批动 5.1/5.2 之前的前置**。
4. 批 2 的「段内重复严重程度」按共用筛选器重算一遍。
