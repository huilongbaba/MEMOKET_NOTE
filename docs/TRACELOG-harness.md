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

## 批 8 · 把证据传给打分器（计划 4.1）（2026-09-17）

**这一批改的是生产代码**（批 5 / 批 7 交的是台子和表）。做的事只有一句：
**把判词里点名要、而生产从来没传过的三样东西，真的递给打分器**——
六个 block 模式的前后文 / 用户那条指令 / 选中的原文，加上**所有模式**这次跑
累积的事实块。**一个维度的判词还是一个字都没改。**

依据是批 7 顶出来的那条反转：`material_use` 在生产里恒判 2.0 **不是判据废了**，
`modes.py:186` 的判词原文写着「没给材料就算达标」——不传材料时判 2 是**判词规定的
正确行为**。同一条空账下还站着 `fits_context`（4/4 满分）、`data_grounding`
（2/2 满分）、`numbers_from_tools`（干净版恒 0）、`follows_prompt`
（with-evidence 掉分 0.0，n=3，p=1.0——因为那一臂其实也没拿到指令）。

### 改了什么

| # | 改动 | 落在哪 |
|---|---|---|
| ① | 新模块：打分上下文由**一处**拼。`for_block`（前后文 / 指令 / 选区，纯函数）+ `material`（事实块渲染 + 截断 + 「没列全」尾注）+ `with_material` | `app/harness/score_context.py`（新，约 150 行） |
| ② | 六个 block 模式补 `score_context`（计划 4.1） | `app/routers/compose_block.py` |
| ③ | `loop._evaluate` 把 `st.facts` 拼进 context，**不分模式**（循环结构没动，只动了这一个 helper） | `app/harness/loop.py` |
| ④ | 写作和打分**共用同一组取量常量**（`BEFORE_CHARS=900` / `AFTER_CHARS=450` / `SELECTION_CHARS=2000`） | `app/harness/hooks/block.py` |
| ⑤ | **那句假 docstring 改成真话**（仓里第二处文档与实现不符，第一处是批 3 的 `_score()`） | `app/routers/note_harness.py` |
| ⑥ | bench 的 `as-deployed` 一档改成**由生产代码自己拼**（`production_context()` 调 `score_context`），不再是脚本里硬编一份跟着抄；三条已经接进生产的 `with-evidence` probe 删掉 | `scripts/dimension_sensitivity_bench.py` |
| ⑦ | 架构文档第 4 节「打分器能看见什么」整段重写；目录图 + `harness/__init__` 地图加新模块；计划 4.1 标 ✅；调研文档「问题一」加「已落地」 | `docs/` 四份 |

### 每个模式现在到底把什么交给打分器

| 模式 | 批 8 之前 | 现在 |
|---|---|---|
| `note` | 核心张力 · 结构节拍 · 标题结构 | 同左 **＋ 事实块** |
| `section` | 分段主题 · 总体目标 · 其他分段小结 | 同左 **＋ 事实块** |
| `eda` / `chart` / `table` | **什么都没有** | 前后文（900 / 450 字）**＋ 事实块** |
| `analysis` | **什么都没有** | 前后文 ＋ **用户那条指令** ＋ 事实块 |
| `prompt` | **什么都没有** | 前后文 ＋ **用户那条指令** ＋ 事实块 |
| `custom` | **什么都没有** | 前后文 ＋ **用户那条指令** ＋ **选中的原文** ＋ 事实块 |

三条定在实现里的规矩：

* **事实块必须是 `st.facts`（这次跑累积的那一份），不许在打分前重新检索。**
  `_score_context` 的 docstring 里记着这个真 bug：修订 / 写作 / 打分三步各自
  独立检索，打分器拿着第三批事实去判正文，报「知识库里查无此事」，而那一句
  正是写作那一步刚用过的材料。
* **材料排在 context 的最后一项**，紧挨着 `[Content]`。代价说清楚：材料每轮
  增长会把正文那段前缀缓存顶掉（`harness-context-engineering.md` §2② 里
  `dup_hints` 踩过同一件事）。这里选准确率，铁律 7。
* **截断必须说出来。** 材料超 6000 字时尾注一句「没列出来的不代表知识库里没有」
  ——不说的话 `factual_grounding` 会把**真有出处**的句子判成编造，下一轮的诊断
  还会逼着模型去改一段本来对的内容。

### 灵敏度对照：**没跑成，一个新数字都没有**

**打分那台模型不在当前这张网上。** `llm_base_url` 是 `http://192.168.77.8:8080/v1`，
本机现在挂在 `192.168.3.0/24` 上（外加一条 VPN 默认路由），`curl -m 10` 连 `/v1/models`
超时（exit 28），`ping` 100% 丢包，本机也没有任何本地模型在听端口。
**换一台模型去跑等于换了评委，跟批 7 的数字不可比，所以没换。**

改完之后的口径变化是确定的：`as-deployed` 现在带上了材料 / 前后文 / 指令，
**指纹一变，日志里 486 行对不上现在这套取材，不进统计，待跑 396 格**
（这正是批 7 那条「格子身份带正文＋上下文指纹」在按设计工作——**代价是这一批
的表要重跑**，不能拿旧分数拼进新表）。

**这一批因此没有任何灵敏度结论。** 批 7 那张表量的是**批 8 之前那条接线**，
它现在只能当**预测值**读：

| 维度 | 批 7 `as-deployed`（旧接线） | 批 7 `with-evidence`（等于批 8 的新接线） | 批 8 重测 |
|---|---|---|---|
| `material_use` | 2.0→1.58，掉 0.42，n=4，p=0.048，只动了一点 | 2.0→0.89，掉 1.11，n=3，p=0.0032，抓住 | **待跑 18 格** |
| `fits_context` | 0.56→0.33，掉 0.22，n=3，p=0.395，基线偏低 | 1.11→0.33，掉 0.78，n=3，p=0.0035 | **待跑 18 格** |
| `follows_prompt` | 1.67→1.11，掉 0.56，n=3，p=0.069，只动了一点 | 1.67→1.67，掉 **0.0**，n=3，p=1.0，**没抓住** | **待跑 18 格** |
| `data_grounding` | table 0.67→0.0（基线偏低，n=1）· chart 0.0→0.0（无从判断，n=1） | 没跑过 | **待跑 12 格**（两条 probe 各 6 格，都是 n=1） |
| `numbers_from_tools` | 干净版**恒 0**，3 篇 18 次一格没有例外 | 没跑过 | **待跑 24 格**（invent_statistic 18 + scramble_numbers 6） |

**`follows_prompt` 那一行要特别读**：批 7 的 with-evidence 臂掉分 0.0，
而那一臂是**把指令塞进 context** 的——所以「补了指令也没反应」这个结论
在批 8 之后仍然可能成立。**接线补上不等于判据灵敏**，这条得等重测。

回到这张网之后，逐条跑（每条都能单独收敛，`--report` 只读日志不发调用）：

```
cd backend
.venv/bin/python scripts/dimension_sensitivity_bench.py --only strip_specifics    --repeats 3   # material_use 18 格
.venv/bin/python scripts/dimension_sensitivity_bench.py --only heading_flood      --repeats 3   # fits_context 18 格
.venv/bin/python scripts/dimension_sensitivity_bench.py --only answer_swap        --repeats 3   # follows_prompt 18 + answers_the_question 18
.venv/bin/python scripts/dimension_sensitivity_bench.py --only invent_table_cells --repeats 5   # data_grounding（表）n=1，见下
.venv/bin/python scripts/dimension_sensitivity_bench.py --only shift_dates        --repeats 3   # data_grounding（图）6 + factual_grounding 18
.venv/bin/python scripts/dimension_sensitivity_bench.py --only invent_statistic   --repeats 3   # numbers_from_tools 18
.venv/bin/python scripts/dimension_sensitivity_bench.py --only scramble_numbers   --repeats 5   # numbers_from_tools，n=1 所以加重复
.venv/bin/python scripts/dimension_sensitivity_bench.py --report
```

**图表那一组的前置没有变**（批 7 ⑨）：5 篇真实语料里只有 1 篇带 mermaid、
1 篇带 markdown 表，所以 `data_grounding` / `chart_validity` / `right_kind` /
`has_charts` / `no_duplicate_charts` / `covers_the_data` / `table_validity`
**全部 n=1**。n=1 篇 × 3 次时排列总数只有 C(6,3)=20，**两侧 p 最小就是 0.10，
数学上不可能显著**。要么 `--repeats 5`（C(10,5)=252，两侧 p 最低 0.008），
要么这一组老实写「样本不足、不下结论」。**不许外推。**

### 确定性那一半量到了（不需要模型）

在 5 篇真实用户语料 × 全部 probe 的 82 个格子上，把新旧 context 各渲染一遍
（`rubric._build_prompt`）：

| 范围 | 打分 prompt 平均长度 | 变化 |
|---|---|---|
| 全部 82 格 | 2915 → 3628 字 | **+24%** |
| 六个 block 模式（34 格） | 2308 → 3530 字 | **+53%** |
| 长文两条（48 格） | 3345 → 3697 字 | **+11%** |

涨最多的一格是 `eda/chart-block-narrated/drop_mentioned_node`：2972 → 4661 字。
16 个格子一个字没变——那几篇那几块里摘不出带日期 / 数字的句子，材料块是空的
（生产里也有这种跑：检索什么都没回来）。

### 突变验（18 个）

每个突变体前后都 `rm -rf __pycache__`（批 5 踩过）。

| # | 把什么改坏 | 结果 |
|---|---|---|
| ① | router 不再装 `score_context` | ✅ |
| ② | `for_block` 不给前后文 | ✅（三条同时红） |
| ③ | 前后文不截断，整篇塞进去 | ✅ |
| ④ | 不给用户那条指令 | ✅ |
| ⑤ | 不给选中的原文 | ✅ |
| ⑥ | `loop._evaluate` 撤回：不拼材料 | ✅ |
| ⑦ | 传本轮的 `facts_new` 而不是累积的 `facts` | ✅ |
| ⑧ | 材料截断时不说「没列全」 | ✅ |
| ⑨ | 没有材料时给个空壳「（无相关记录）」 | ✅ |
| ⑩ | 材料块改个名字（不再叫「知识库事实」） | ✅ |
| ⑪ | 材料排到 context 最前面 | ✅ |
| ⑫ | 写作那一步撤回自己的取量（跟打分脱钩） | ✅ |
| ⑬ | bench 用回自己那份 as-deployed | ✅（**第一版用例没抓住**，见下） |
| ⑭ | bench 自己抄一份上下文形状 | ✅ |
| ⑮ | bench 的材料只给 block 模式 | ✅ |
| ⑯ | 删掉的 `with-evidence` probe 加回来 | ✅ |
| ⑰ | 往 `loop.py` 里塞字符串 `"facts"`（收窄那条闸之后它还认不认得出真泄漏） | ✅ |
| ⑱ | 往 `loop.py` 里塞 `chain.facts`（非 `st.` 的属性泄漏） | ✅ |

**⑬ 漏网，原因是「用例不够」不是「实现对」**（批 3 / 批 5 / 批 7 记的同一条）：
新加的四条 bench 用例全都直接调 `production_context()`，**没有一条管
`build_tasks` 用不用它**。把 `build_tasks` 里那一行改回 `dict(subject.context)`
——等于整批的测量口径悄悄退回批 7——**155 条全绿**。补了一条盯
「真正发出去的那一格 `Task.context` 里有没有前后文和材料」的用例才红。

### 实施中发现的、计划里没写到的

**① `test_循环不认识任何一个middleware` 误报了，判据太宽。**
循环要把材料递给打分器，写的是 `st.facts`——而累积材料那条 middleware 正好也叫
`facts`，那条闸按「词」匹配，当场红。读 State 的字段恰恰是循环**该**做的事
（它早就在读 `st.facts_new` / `st.content`），跟「循环知道链上有谁」是两回事。
判据收窄成「`st.<字段>` 不算」，**并当场验证真泄漏的两种形状仍然红**（⑰⑱）。
*这是一次「闸挡住了对的改动」，不是「改动错了」——但收窄闸必须配突变验，
不然就是把闸关了。*

**② bench 的 `as-deployed` 一改口径，日志里 486 行当场作废。**
这是批 7 那条「格子身份带正文 + 上下文指纹」按设计工作（旧分数混进新表是
**毫无症状**的错），但代价要写出来：**改接线 = 整张灵敏度表重跑**。
选择是明确的：让 `as-deployed` 名副其实，比省 396 次调用重要。

**③ `custom` 的选区不会跟后文重复。** 前端 `App.runBlock` 在发请求之前就
把选中那段从 doc 里删掉了（`changes: {from, to, insert: ''}` 之后才取
`doc.toString()`），所以 `after` 里没有它——选区单独给一份不构成重复。
*反过来说，bench 拼不出真实选区（合成一段等于凭空造变量），所以
`replaces_cleanly` 那一行的 as-deployed 比生产**保守**，这条差异记在
`production_context` 的 docstring 里。*

**④ `style_fit` 是同一种病，但这一批**没有**治它。** 个人偏好档案在 router
里现成（`_profile(user)`），判词也明写着「贴合用户的个人偏好」——按理该一起传。
**没传的依据**：批 7 实测补了偏好的那一臂只掉 0.17（n=2 篇 12 次，p=1.0），
**没有任何证据说明传了有用**。判据宁可窄一点，等它自己拿出数来。
于是 `with-evidence` 这一档现在只剩这一条，含义也更干净了：
**「生产至今仍然不给的证据」**。

**⑤ 一条要在重测时盯住的污染风险。** block 模式的 `st.facts` 里混着工具**原样
返回**的内容（`hooks/block.prepare` 把 raw 也塞进去），其中可能有整段 mermaid。
材料块因此可能带图，而 `has_charts` / `no_duplicate_charts` 判的是「正文里的图」。
重测时**先看这两行的干净臂有没有整体走高**——真走高就要在材料渲染时剥掉围栏块。
现在不动：没有数就改是拍脑袋。

### 闸

后端 **1319 → 1340**（+21：`test_score_context.py` 新增 15 条；
`test_dimension_sensitivity_bench.py` 119 → 125 条）。
前端 51 文件 / 254 条不变。`test_doc_counts` / `test_directory_map` /
`test_architecture_claims` 全绿（新模块已经进目录图和 `harness/__init__` 的地图；
Mode / check / middleware / 工具的数量一个都没变）。

### 这一批**没做**什么

- **判词一个字都没改。** 2.6 / 5.1 / 5.2 仍然等重测。
- **没有删维度，也没有加维度。**
- **block 模式的 `stop_when` 没补**（[EVAL] 问题三）——调研文档自己写的是
  「先看数据，不建议现在就加」，数据还没有。
- **个人偏好没传给打分器**（见上面④）。
- **批 2 的「段内重复严重程度」还是没按共用筛选器重算。**

### 下一步

1. **回到有模型的网上，先跑那 5 维 90 格**（`material_use` 18 + `fits_context` 18
   + `follows_prompt` 18 + `data_grounding` 12 + `numbers_from_tools` 24；
   上面那几条 `--only` 会顺带跑掉同名植入器的别的 probe，全表 396 格），把批 7 的
   `with-evidence` 行和批 8 的 `as-deployed` 行逐条对上。
   **对不上的比对得上的重要**：`follows_prompt` 如果仍然掉 0.0，
   那说明问题在判词或者在指令的写法上，不在接线。
2. 跑完再动 2.6 / 5.1 / 5.2。`numbers_from_tools` 现在真的能看到工具返回值了，
   它是否还「干净版恒 0」是 5.2 唯一的依据。
3. 图表那一组仍然 n=1，`--repeats 5` 之前不下任何结论。
4. 盯材料块里的 mermaid 污染（上面⑤）。

## 批 9 · 重测灵敏度：批 8 那条接线到底有没有让判据变灵敏（2026-09-17）

**这一批一行生产代码都没改。** 交的是 396 格真实调用和一张改前改后的对照表。

### 先纠正批 8 的一个错误判断

批 8 写「打分那台模型（`192.168.77.8:8080`）不在当前这张网上，所以重测没跑成」，
**这是读错了配置来源**。生产路径取的是 DB 里的 active config
（`app.database.store.get_active_llm_config()`），不是 settings 里的 `llm_base_url`；
`192.168.77.8:8080` 是**看图模型**，跟打分无关。

实测复验（跑真实 `evaluate()`，不是 ping）：`provider=gpt` / `model=gpt-5.6-luna` /
`base_url=https://api.openai.com/v1`，8.3 秒回，而且判分是对的——
同一段正文逐字复制一段之后 `non_repetition` 从 2 掉到 0。
**那 396 格一直是能跑的，白等了一批。**

*教训：「跑不了」这种结论必须用一次真实调用来下，不能靠读配置文件推。*

### 怎么跑的

```
.venv/bin/python scripts/dimension_sensitivity_bench.py --time-budget-seconds 700 --concurrency 6
.venv/bin/python scripts/dimension_sensitivity_bench.py --only chart-block --repeats 5 ...
.venv/bin/python scripts/dimension_sensitivity_bench.py --only table-block --repeats 5 ...
.venv/bin/python scripts/dimension_sensitivity_bench.py --report --repeats 5
```

396 格一次跑完、**0 个 error**；图表/表格那一组另加 32 格补到 `--repeats 5`。
语料照批 6/7 的规矩按 `corpus_lineage` 血缘只留 `user` 一类：留 5 篇、排掉 14 篇
（script 10、fixture 4）。**没有碰任何一篇用户真实笔记**（bench 只读，连
`update_note` 都没 import）。

### 改前改后对照（批 7 = 批 8 之前那条接线，批 9 = 批 8 之后）

**这五维是批 8 逐条写下预测的，先看它们。**

| 维度 · probe | 批 7 `as-deployed`（旧接线） | 批 7 `with-evidence`（当时的预测） | 批 9 `as-deployed`（实测新接线） | 兑现了吗 |
|---|---|---|---|---|
| `material_use` · note/strip_specifics | 2.0→1.58 掉 **0.42**，n=4 篇/24 次，p=0.048，只动了一点 | 2.0→0.89 掉 **1.11**，n=3/18，p=0.0032，抓住 | 2.0→1.33 掉 **0.67**，n=4/24，p=**0.027**，只动了一点 | 半兑现，拆开看才对（见下） |
| `fits_context` · eda/heading_flood | 0.56→0.33 掉 **0.22**，n=3/18，p=0.395，基线偏低 | 1.11→0.33 掉 **0.78**，n=3/18，p=0.0035，只动了一点 | 1.22→0.78 掉 **0.44**，n=3/18，p=**0.105**，只动了一点 | **没兑现**（基线抬了，掉分没有） |
| `follows_prompt` · prompt/answer_swap | 1.67→1.11 掉 **0.56**，n=3/18，p=0.069，只动了一点 | 1.67→1.67 掉 **0.0**，n=3/18，p=1.0，**没抓住** | 1.44→0.33 掉 **1.11**，n=3/18，p=**0.0005**，**抓住** | **预测被推翻**（见下） |
| `data_grounding` · chart/shift_dates | 0.0→0.0 掉 0.0，n=1/6，p=1.0，无从判断 | — | 2.0→0.0 掉 **2.0**，n=**1**/10，p=**0.006**，抓住 | 翻转，但 n=1 篇不外推 |
| `numbers_from_tools` · eda/invent_statistic | 0.0→0.0 掉 0.0，n=3/18，p=1.0，无从判断 | — | 1.11→0.0 掉 **1.11**，n=3/18，p=**0.006**，**抓住** | **最干净的一次翻转** |

**其余各维的改前改后**（同一条 probe、同一份语料）：

| 维度 · probe | 批 7 | 批 9 | 变化 |
|---|---|---|---|
| `no_fabrication` · prompt/fabricate_specifics | 0.89→0.22 掉 0.67，n=3/18，p=0.298，基线偏低 | 1.11→0.11 掉 1.00，n=3/18，p=0.009，**抓住** | ⬆ 基线抬起来之后显著了 |
| `factual_grounding` · note/shift_dates | 1.44→0.56 掉 0.89，n=3/18，p=0.010，只动了一点 | 1.11→0.00 掉 1.11，n=3/18，p=0.006，抓住 | ⬆ |
| `non_repetition` · note/duplicate_paragraph | 1.27→0.0 掉 1.27，n=5/30，p=0.0002，抓住 | 1.53→0.0 掉 1.53，n=5/30，p=0.0002，抓住 | ⬆ |
| `answers_the_question` · analysis/answer_swap | 1.00→0.44 掉 0.56，n=3/18，p=0.169 | 0.89→0.22 掉 0.67，n=3/18，p=**0.020** | ⬆ 显著了，但干净版跌破 1.0 转记「基线偏低」 |
| `coherence` · note/double_ending | 0.80→0.47 掉 0.33，n=5/30，p=0.021 | 0.93→0.47 掉 0.47，n=5/30，p=0.005 | ⬆ 但仍「基线偏低」 |
| `topic_fidelity` · section/off_spine_graft | 1.25→0.0 掉 1.25，n=4/24，p=0.0002，抓住 | 1.08→0.17 掉 0.92，n=4/24，p=0.002，抓住 | ↔ 略弱，仍抓住 |
| `states_limits` · analysis/strip_caveats | 2.0→0.67 掉 1.33，n=2/12，p=0.006，抓住 | 2.0→1.0 掉 1.00，n=2/12，p=0.006，抓住 | ↔ |
| `replaces_cleanly` · custom/lead_in | 1.78→0.0 掉 1.78，n=3/18，p=0.0005，抓住 | 1.44→0.0 掉 1.44，n=3/18，p=0.0005，抓住 | ↔ |
| `beat_coverage` · note/drop_last_section | 1.5→0.5 掉 1.0，n=2/12，p=0.006，抓住 | 同左，一字未变 | ↔ |
| `honest_caveats` · eda/strip_caveats | 2.0→1.0 掉 1.0，n=2/12，p=0.006，抓住 | 同左 | ↔ |
| `section_coverage` · section/truncate_bodies | 1.33→1.08 掉 0.25，n=4/24，p=0.346 | 1.33→1.08 掉 0.25，n=4/24，p=0.355 | ↔ 没动（这一维的接线没变） |
| `style_fit` · note/audit_voice | 2.0→1.83 掉 0.17，n=2/12，p=1.0 | 2.0→1.83 掉 0.17，n=2/12，p=1.0 | ↔ 没动（偏好档案批 8 故意没传） |
| `spine_fidelity` · note/off_spine_graft | 2.0→1.0 掉 1.00，n=2/12，p=0.006，**抓住** | 1.83→1.17 掉 0.67，n=2/12，p=0.094，**只动了一点** | **⬇ 退步了**（见下③） |
| `topic_fidelity` · section/swap_section_bodies | 1.22→1.22 掉 0.00，n=3/18，p=1.0 | 0.89→1.00 掉 −0.11，n=3/18，p=1.0 | ⬇ 两批都判不动 |
| `factual_grounding` · note/placeholder | 1.60→1.53 掉 0.07，n=5/30，p=1.0 | 1.33→1.40 掉 **−0.07**，n=5/30，p=1.0，**没抓住** | ↔ **两批一致失败** |

**图表 / 表格那一组（全部 n=1 篇，`--repeats 5`）——下面这些数不外推：**

| 维度 · probe | 批 7（n=1 篇/6 次） | 批 9（n=1 篇/10 次） |
|---|---|---|
| `data_grounding` · chart/shift_dates | 0.0→0.0 掉 0.00，p=1.0 | 2.0→0.0 掉 2.00，p=0.006 |
| `covers_the_data` · eda/drop_mentioned_node | 2.0→0.67 掉 1.33，p=0.103 | 1.0→0.4 掉 0.60，p=0.174 |
| `has_charts` · eda/chart_to_prose | 1.33→0.33 掉 1.00，p=0.304 | 1.0→0.4 掉 0.60，p=0.366 |
| `table_validity` · table/drop_table_column | 1.33→0.0 掉 1.33，p=0.404 | 0.8→0.0 掉 0.80，p=0.437 |
| `data_grounding` · table/invent_table_cells | 0.67→0.0 掉 0.67，p=0.385 | 0.4→0.0 掉 0.40，p=0.437 |
| `no_duplicate_charts` · eda/duplicate_chart | 1.0→0.0 掉 1.00，p=0.415 | 0.2→0.0 掉 0.20，p=1.0 |
| `right_kind` · chart/chart_to_image | 0.33→2.0 掉 **−1.67**（反着来） | 2.0→1.8 掉 0.20，p=1.0 |
| `chart_validity` · chart/break_mermaid_fence | 0.0→0.0，无从判断 | 0.0→0.2，无从判断 |

**这一组只有 `data_grounding`(chart) 一行做出了显著（p=0.006）**，而且那只是
「**在这一篇上**不是噪声」。跨篇一概不下结论：**5 篇真实用户语料里只有 1 篇带
mermaid、1 篇带 markdown 表**。`--repeats 5` 买到的是篇内的统计功效，
**买不到第二篇语料**。要量准这一组得先有真实语料，不能靠 soak 凑。

### 哪几维接线补上之后真的变灵敏了

**真的变灵敏（3 维）：**

1. **`numbers_from_tools`**——批 8 最直接的依据兑现了。批 7 干净版 3 篇 18 次恒 0
   （「追不到工具结果就一律不达标」），批 9 干净 1.11、植入 0.0，掉 1.11（p=0.006）。
   **这是「空账」被治好的教科书例子：不是判据废了，是证据没给。**
   逐篇看更清楚：两篇干净版判到 1.33 / 2.0，植入后 6 次全 0。
2. **`follows_prompt`**——见下面①，这是这一批最重要的一条。
3. **`no_fabrication`** / **`factual_grounding`(shift_dates)**——都是基线从「偏低」
   抬到 1.1 之后掉分才做出显著。前后文让打分器有了对照物。

**没变灵敏（照批 8 的预测该变而没变）：**

* **`fits_context`**——**接线补上了，判据还是不灵。** 基线确实抬起来了
  （0.56 → 1.22，说明打分器以前是在「看不见上下文」的条件下给分），
  但 `heading_flood`（往一块里灌一堆标题）只让它掉 0.44，p=0.105，**不显著**。
  批 7 `with-evidence` 预测的 0.78 没兑现。
* **`factual_grounding` 对占位符**——两批都没抓住（掉 0.07 / −0.07，n=5 篇 30 次，
  p=1.0）。**这是本表里样本量最大的一条失败行**，跟接线无关。

### ① `follows_prompt`：批 7 那条「没抓住」是坏测量，不是坏判据

批 8 把这一条当成最值得担心的一行写进了台账——「补了指令那一臂**仍然**掉 0.0
（n=3，p=1.0），接线补上 ≠ 判据灵敏」，并交代重测时要特别看。

**重测的结论是反的**：批 9 的 as-deployed 干净 1.44 / 植入 0.33，掉 **1.11**，
p=**0.0005**——是全表里 p 最小的两行之一，**抓住**。

原因批 8 自己其实已经写下来了：批 7 那条 `with-evidence` 臂「**其实也没拿到指令**」。
所以批 7 那个 0.0 从来不是「给了指令还判不动」，而是「根本没给」。
**一条坏测量写进台账，会以「重要负面结论」的身份活到下一批**——它比没有数据更贵，
因为它长得像证据。

*可推广的一条：**预测值来自哪一臂、那一臂自己验过没有**，要跟预测一起记下来。*
批 7 的 `with-evidence` 臂没有任何自验证明「指令确实进了 context」；
批 8 的 `production_context` 有（突变验⑬⑭）。这就是两者可信度的差别。

### ② `material_use`：整行 0.67 是被「条件没出现」的那一篇拖下来的

整行看是「只动了一点」（掉 0.67 < CAUGHT 0.89），像是没兑现批 7 预测的 1.11。
**按「这一篇的材料块到底空不空」拆开，真相相反**：

| 分组 | 篇 | 次 | 干净 | 植入 | 掉分 | p |
|---|---:|---:|---:|---:|---:|---:|
| 材料块非空 | 3 | 18 | 2.00 | 1.11 | **0.89** | **0.025** |
| 材料块为空 | 1 | 6 | 2.00 | 2.00 | 0.00 | 1.0 |

掉 0.89 正好压在 `CAUGHT` 线上，**抓住**，跟批 7 预测的 1.11 是同一量级。
而那 1 篇（`3a3a96354546`）的材料块是空的——`derived_facts` 在它上面摘不出带日期 /
数字的句子，于是打分器手里没有【知识库事实】块，判词明写着「**没给材料就算达标**」，
判 2.0 是**正确行为**。

**这正是 1.6 一开始就要分开的那两件事**（「判据废了」vs「条件没出现」），
而现在的统计把它们算进了同一个均值。批 7 的 with-evidence 臂 n=3 恰好只跑了
能拼出证据的那 3 篇，所以它反而更干净。
**这不是判据的问题，是 `summarize()` 的分组粒度不够**——记进下一步。

### ③ 计划外发现

**`spine_fidelity` 退步了，而且方向是「接线补上之后变钝」。** 批 7 掉 1.00
（p=0.006，抓住）→ 批 9 掉 0.67（p=0.094，只动了一点）。干净版 2.0→1.83、
植入版 1.0→1.17 两头同时往中间收。`off_spine_graft` 是把**另一篇**的两段接进来，
而批 8 新给的「这一块前面/后面的正文」和材料块都来自**本篇**——多给的上下文
按理该让离题更显眼才对。n=2 篇 12 次，p=0.094，**不能当硬结论**，但方向值得盯。
可能的解释（都没验）：context 变长稀释了注意力；或者材料块里那些本篇事实
让打分器觉得「还是在讲这篇的事」。

**「这一块后面的正文」在 eda / analysis 那几条 probe 上全是空占位符。**
`numeric-block` 取材器挑的是数字最密的那一节，而这 5 篇里它**每一篇都正好在文末**，
于是 `score_context.for_block` 全部填了「（这里是笔记结尾，下面没有正文）」（16 字）。
后果：`fits_context` / `actionable` / `numbers_from_tools` / `honest_caveats` /
`answers_the_question` / `states_limits` 这几维，**上下文只给了一半就被测了**。
`fits_context` 判词写的是「读起来要像本来就在这篇笔记里、标题比上方最近的标题低一级」
——上方那一半是有的，所以这一维受影响相对小，但这条限制必须写下来。

**批 8 ⑤ 那条污染风险确认存在，但症状跟预测的相反。** 用确定性判据数了一遍：
**102 个格子里有 10 格的 context 里带围栏图或 markdown 表**，全在
`06647b9c2031` 这一篇上，位置就在【知识库事实】块里（`derived_facts` 的 `[F1]`
直接吞掉了整段 mermaid，因为围栏里没有句号，切不开）。生产侧同一条路也在：
`hooks/block.prepare` 第 61 行 `return facts + raw`，raw 就是工具原样返回。

但批 8 预测的症状是「`has_charts` / `no_duplicate_charts` 的**干净臂整体走高**」，
**实测是走低**（has_charts 1.33→1.0、no_duplicate_charts 1.0→0.2）。n=1 篇，
这个方向本身也不可信。**所以不动**：污染是真的，「要剥掉围栏块」这个处方**没有数据支持**。
批 8 写的「没有数就改是拍脑袋」这条继续适用，只是现在知道了污染确实发生、发生在哪。

**`derived_facts` 会产出近似重复的事实条目。** `06647b9c2031` 的 `[F2]` 和 `[F3]`
都是「下一轮 10 台到货为 6 月 15 日」。这会让材料块虚长，也可能影响
`material_use` 的判分。记下，没改。

**复算「算抓住」那条线：** 12800 个纯噪声掉分，95% 分位数 = **0.67**，
纯噪声下 |掉分| ≥ 0.5 的比例 **8.7%**（批 6 量到 10.1%、批 7 之后 13.6%）。
本次表仍用 `CAUGHT = 0.89`，**比标定值保守**——判据宁可窄一点，没改。

### 突变验

这一批没改生产代码，所以突变验要验的是**「这些数字确实量的是批 8 那条接线」**，
而不是别的东西。都是确定性检查：

| # | 把什么改坏 | 结果 |
|---|---|---|
| ① | `score_context.material` 返回空 | ✅ 5 个 `strip_specifics` 格子里 **3 个指纹变了**（另 2 个本来材料就是空的，见②） |
| ② | `score_context.for_block` 不给用户那条指令 | ✅ 3 个 `prompt/answer_swap` 格子**全部**指纹变了 |

①里那「2 个没变」不是漏网，**它本身就是②节那个结论的确定性证据**：那两篇上材料块
本来就是空的，所以撤掉材料对它们没有任何影响——跟打分结果里「材料块为空的那篇掉 0.00」
完全对得上。**一条确定性检查和一条统计结论互相印证。**

另外，分析中途自己踩了一次批 7 ⑥ 那个坑：第一版拆 `material_use` 的脚本直接
`read_log()` 没按 `valid` key 过滤，把旧指纹的行混了进来（18 次算成 36 次）。
**症状只有「次数对不上」这一个**——如果没顺手核样本量就会拿混着旧接线的数下结论。
已按 `build_tasks(..., set())` 重算，上表是过滤后的。

### 闸

后端 **1340 passed**（跟批 8 基线一致，没有新增用例——这一批没改代码）。
前端 **51 文件 / 254 条**全绿。

### 下一步

1. **`summarize()` 要能按「这一格的条件到底成没成立」分组**。`material_use` 整行
   0.67 vs 材料块非空的 0.89 就差在这儿。不分组就是把「条件没出现」和「判据不灵」
   算同一个均值——而这两件事的处理方式完全相反，正是 1.6 立项要分开的那两件。
   最小做法：`Probe` 上加一个 `precondition(subject, note, ctx) -> bool`，
   summarize 按它拆两行，不成立的那一行只报计数不进掉分。
2. **`fits_context` 该动判词了，接线已经不是瓶颈。** 它是这一批唯一「证据给全了、
   基线也抬起来了、掉分仍不显著」的一维。动之前先补掉 ③ 里那条「after 恒为空」的
   取材偏差——换一个不总在文末的取材器，重跑这一维，再决定改不改判词。
3. **2.6 / 5.1 / 5.2 现在有依据了。** 5.2 的唯一依据是「`numbers_from_tools` 是否
   还干净版恒 0」——**答案是不再恒 0**（1.11，抓住），所以 5.2 原来的理由不成立，
   要重新论证。
4. **图表那一组仍然 n=1 篇，`--repeats 5` 改变不了这一点。** 需要的是真实语料，
   不是重复次数。在有第二篇带图的真实用户产出之前，这 7 维一律不下跨篇结论。
5. **`factual_grounding` 对占位符**是全表样本量最大的失败行（n=5 篇 30 次，两批一致）。
   接线跟它无关，下一步该看判词或者干脆交给确定性判据
   （`grounding_rules.placeholder_lines` 本来就已经能抓）。
6. `spine_fidelity` 退步那条盯住，下次重跑时看是否复现。

---

## 批 10 · 阶段 2 的账本三条 + 两条测量完整性修复（2026-09-17）

这一批既改生产（2.1 / 2.2 / 2.3），也改测量台（批 9 留下的两条）。
**没碰任何 prompt**——2.4「账本摘要进 prompt」是下一批的事，理由见
`harness-fact-ledger.md` §10⑤（把已经有什么摆给模型看会缩小搜索空间），
所以它必须能单独回退。

### 改了什么

| # | 改动 | 落在哪 |
|---|---|---|
| 2.1 | **查询级短路**：一次跑里参数完全相同的知识库查询只真查一次 | `harness/query_cache.py`（新）、`agent_loop.py`、`hooks/note.py`、`hooks/section.py` |
| 2.2 | **`kb_conflicts` 接进取材**：被取代的标进账本，**并把取代它的那条一起带回来** | `middleware/supersede.py`（新）、`middleware/__init__.py` |
| 2.3 | **事实日期进账本**（temporal validity） | `middleware/ledger.py` `parse_facts()` |
| — | 账本多两列落库：`cached_calls`（短路省了几次）/ `superseded`（这轮几条被取代） | `store.py` `_ADDED_COLUMNS` + `record_harness_round` |
| 批 9①| **`summarize()` 按「这一格的条件成没成立」分组**：`Probe.precondition` | `scripts/dimension_sensitivity_bench.py` |
| 批 9②| **修 `numeric-block` 取材器的偏差** | 同上 |

**2.1 的形状是两档，不是一档**，这是实现里最容易写错、错了又没有任何报错的地方：

| 什么时候 | 返回什么 | 为什么 |
|---|---|---|
| **同一轮内**重复 | 一句「已经查过，结果在上面」 | 那一份确实就在这一轮的 convo 里 |
| **跨轮**重复 | 上次那份**完整结果** | 这一轮的 convo 是新拼的，上一轮的工具消息**不在里面** |

实测这一条不是纸上谈兵：下面那次真跑里，**6 次短路全是跨轮的、同轮的 0 次**——
要是图省事一律回一句提示，第 2 轮手里的 45 条材料会**整批消失**，而正文照常写出来。

短路走白名单（只放行 `memory` 组八个纯读知识库的工具），不走黑名单：
`data` 组读的是 `ctx.content` / `ctx.cursor`，**正文每轮都在变**，同参数的结果
本来就该不同；`chart` / `image` 组会生成东西；`run_skill_script` 自己在 scratch 里
记配额。判据宁可窄一点。

### 2.1 实测：一次真跑的重复查询率

跑法：`terrence` 的真库（只读），`rails_off=("save",)`，**一篇笔记都没写**，
4 轮预算，真实跑到第 3 轮 `material_used_up` 停。

| 量的是什么 | 数 |
|---|---|
| 工具循环发出的查询（账本记的） | **12 次**，其中重复 4 次 = **33.3%** |
| 短路层看到的全部派发（另含 `prepare` 里直接调的主题树 3 次） | **15 次**，命中缓存 **6 次 = 40.0%** |
| 其中「连上下文都没再塞第二遍」 | **0 次**（6 次全是跨轮） |

逐条看更清楚——**第 2 轮把第 1 轮的三条 `filter_facts` 一字不差地又发了一遍**：

```
轮1  filter_facts topic=work_product_release   / work_go_to_market / work_product_strategy
轮2  filter_facts topic=work_product_release   / work_go_to_market / work_product_strategy   ← 三条全重复
轮3  filter_facts topic=work_product_release   / work_product_testing / work_product         ← 一条重复
```

`harness_rounds` 落库的三行（这张表批 1 建好之后**一直是空的**，这是它第一次有数）：

| 轮 | tool_calls | repeat_calls | cached_calls | facts_new | facts_total |
|---:|---:|---:|---:|---:|---:|
| 1 | 4 | 0 | 0 | 45 | 45 |
| 2 | 4 | 3 | 4 | **0** | 45 |
| 3 | 4 | 1 | 2 | 30 | 75 |

**第 2 轮 `facts_new = 0`** —— 它整轮没带回一条新事实，这正是
`harness-multiround-retrieval.md` §1 说的那件事：检索规划每轮从零开始，
prompt 里写着「不要再取上几轮已经写过的那些」，而清单没给。
短路省下的是这一轮 4 次后端查询；**它省不掉的是那次规划调用**——
2.4 / 2.5 才治得了「为什么又规划出同一批查询」。

另外，75 条事实**全部带日期**（2.3 落地，`when` 覆盖率 100%）。

### 2.2 实测：真的从 `kb_conflicts` 读到了东西

库里 4 行，全是 `status='open'`（一条都没人裁决过），分属 `shot-demo` /
`fresh678` ×2 / `fresh678b`；四对事实的两边**在知识库里都还在**。
拿 `fresh678` 那一对真跑了两条路径（**没有改动用户的知识库文件**，
已裁决那一档是把 `fact_attrs` 临时换掉模拟的）：

```
旧: [note-e16fdb6dab74-0F7] 这一版产品的定价定在199美元。      (2026-03-04)
新: [note-146d1628a7d0-0F1] 竞品 Plaud 的同档位价格是 159 美元，而我们的价格是 199 美元。 (2026-03-11)

① 未裁决（真·kb_conflicts）→ 账本标 conflict_with，材料里加一行
   「【注意】… 跟 … 的记录对不上，**知识库里这条冲突还没裁决，两条都别当定论**：…」
② 已裁决（fact_attrs）→ 账本标 superseded_by，材料里加一行
   「[新 id] 正文（2026-03-11）【这条取代了 [旧 id]，写的时候以这条为准】」
```

**两个来源必须分两种待遇，这不是洁癖**：上面那一对本身就是**误报**——
「竞品 Plaud 159」和「我们 199」根本不是同一个量，这正是
`harness/conflict_confirm.py` 开头记的那次实拍（新用户导入两篇真会议记录，
收件箱里两条全是误报）。库里现存 4 行 open 里有 3 行是这一类。
**拿未裁决的候选去把一条正确的事实标成「过时」，就是误伤**，
而铁律写着误伤比漏报贵。所以 open 那一档只挂提醒、不声称谁取代谁。

*顺带一个发现：`superseded_by` 这个属性全库一个都没有*——收件箱从上线到现在
没有一条冲突被裁决过。已裁决那条路径在生产里目前是**零流量**，
它的价值要等收件箱真的被用起来才兑现。

### 批 9 ① `material_use` 分组之后长什么样

`Probe` 上加了 `precondition(subject, note, ctx) -> bool`，**在
`production_context` 拼完之后算**——它判的是「这一格递给打分器的 context 里
有没有那块证据」，跟取材器判的「这篇笔记有没有这块东西」是两件事。
目前只声明了一条（`material_use` / 材料块非空），因为全仓只有
`_MATERIAL_USE` 一条判词明写着「**没给材料就算达标**」。判据宁可窄一点。

**前置条件是 `(语料, probe)` 的纯函数，所以报告时能重算**——批 9 那 396 格
不用重跑一次就按条件拆开了（`precondition_map` / `annotate_preconditions`）。

拆开之后（n 已经补到 `--repeats 5`）：

| 分组 | 篇 | 次 | 干净 | 植入 | 掉分 | p | 结论 |
|---|---:|---:|---:|---:|---:|---:|---|
| 材料块非空 | 3 | 30 | 2.00 | 1.13 | **0.87** | **0.0005** | 只动了一点（见下） |
| 材料块为空 | 1 | 10 | 2.00 | 2.00 | — | — | **条件没出现**，单独成表 |

**顺带纠正批 9 ② 自己的一处读数错**：那一批写「掉 0.89 正好压在 `CAUGHT` 线上，
**抓住**」——`0.89` 是四舍五入之后的显示值，原始值是 `0.888…`，
`_verdict` 比的是原始值，所以它当时就该报「只动了一点」。
**读四舍五入后的数去下结论，是这批台账自己踩的坑。**
按本次实测标定的线（0.60）它是抓住；按仍在用的保守线（0.89）它差 0.02。
两个数都贴出来，不选一个说。

### 批 9 ② `numeric-block` 的偏差：真因比台账写的深一层

台账批 9 ③ 记的是「密的那一节每篇都正好在文末」。**不是。**

真因是取材器把一节**重新拼**成 `标题 + "\n" + 正文`，而 `sections()` 切出来的
正文自带一个换行——拼出来的串跟原文差一个字符，于是 `surrounding()` 里那句
`content.find(subject.text[:40])` **一律返回 -1**，落进兜底 `at = len(content)//2`：

* `after` = `content[中点 + 块长:]` → 恒为空 → 「（这里是笔记结尾，下面没有正文）」；
* **`before` 也是错的**——不是这一块上面的正文，是整篇的前半截。

台账只记了 after，前文那一半**没人发现**。实测：`numeric-block` 三篇全中、
`chart-block` 也中一篇。修法是 `Subject` 自己带 `at` / `end`（`sections_at()` 给），
不再靠回头 `find`；定位不到时**宁可把前后文都记成空**，不编一个位置出来。
另加一条「同等条件下优先挑后面还有正文的那一节」，别再靠运气。

修完之后同一份语料上：`06647b9c2031` 后文 424 字、`ecfac1f3c0aa` 450 字、
`574f4ff29956` 仍是空的（那一篇整篇只有末节有数字——**这是关于那篇笔记的事实，
不是取材偏差**，照实取、照实报）。

### 上下文修对之后，那 6 个维度重测（1468 格，0 error）

> **批 12 按批 11 H3 拆过这张表：原来两列里混着两个变量**（上下文修复 +
> `--repeats` 3→5），下面这张是拆开之后的。**这一批的报告头从此记 `repeats`**
> ——两张 `repeats` 不同的表不能直接比「显著了没有」，那比的是统计功效。

因为格子身份带上下文指纹，这一改让 648 行旧数据自动掉出统计（**这正是要的**：
它们量的是半份上下文）。补跑 458 格之后：

| 维度 · probe | ① 批 9：坏上下文 · r3 | ② 修好上下文 · r3（同一份日志的 r3 子集） | ③ 批 10：修好上下文 · r5 | 上下文买到了什么 | repeats 买到了什么 |
|---|---|---|---|---|---|
| `fits_context` · eda/heading_flood | 掉 0.44，p=**0.105** | 掉 0.56，p=**0.0205** | 掉 0.53，p=**0.0015** | **方向站得住**：光修上下文就过了线 | 0.0205→0.0015 这一段全是它买的 |
| `spine_fidelity` · note/off_spine_graft | 掉 0.67，p=**0.094** | 掉 0.67，p=**0.0937** | 掉 0.60，p=**0.0232** | **0%**：跟批 9 一模一样 | **100%**：这一行「显著了」全是 r3→r5 |
| `answers_the_question` · analysis/answer_swap | 0.89→0.22 掉 0.67，p=0.020，**基线偏低** | — | 1.13→0.47 掉 0.67，p=0.0072 | 基线抬过 1.0，不再是「偏低」 | — |
| `numbers_from_tools` · eda/invent_statistic | 1.11→0.0 掉 1.11，抓住 | — | 1.20→0.0 掉 1.20，p=0.0002，抓住 | ↔ 更稳 | — |
| `honest_caveats` · eda/strip_caveats | 2.0→1.0 掉 1.0，抓住 | — | 同左，p=0.0005 | ↔ | — |
| `states_limits` · analysis/strip_caveats | 2.0→1.0 掉 1.0，抓住 | — | 2.0→0.9 掉 1.1，p=0.0005 | ↔ | — |
| `actionable` · eda/strip_next_steps | 2.0→1.44 掉 0.56，p=0.048 | — | 1.93→1.33 掉 0.60，p=0.0042 | ↔ 更稳 | — |

（② 那一列是审查 agent 在**同一份日志**上按 r3 子集重算出来的，不是重跑；
只算了争议最大的那两行。）

**批 9 下一步第 2 条可以结掉了，而且结论是反的**：那条写「`fits_context`
该动判词了，接线已经不是瓶颈」。**接线还真是瓶颈**——光把它少拿的那半份上下文
补上，同一条 probe 就从 p=0.105 过到 **p=0.0205**。**没动一个字的判词。**
但**「p=0.105→0.0015」这个幅度里一大半是 `--repeats` 3→5 买的**，
上一版台账把两个变量记成了一个，这里改过来。

*可推广的一条：一个维度"判据不灵"的结论，在证明它拿到的上下文完整之前都不算数。
而"完整"这件事必须用确定性检查去证，不能靠读代码——那半份上下文在代码里长得
完全正常。*

其余顺带的变化（都不是这一批动的东西，记下来备查）：
~~`spine_fidelity` 批 9 掉 0.67/p=0.094 → 批 10 掉 0.60/**p=0.0232**（显著了）~~
**这一句批 12 撤回**（批 11 H3 隔离实验）：同一份日志的 r3 子集上，修好上下文之后
`spine_fidelity` 是 p=**0.0937**——跟批 9 的 0.094 一模一样。
**它「显著了」100% 是 `--repeats` 3→5 的功劳，0% 是上下文修复的功劳**，
写在「上下文修对之后重测」这一节里本身就是误导；`right_kind` 从「只动了一点」变成
**没抓住**（1.2→1.2，n=1 篇）；`has_charts` 干净版从 1.0 掉到 0.6 转「基线偏低」。
后两条都是 n=1 篇，**不下跨篇结论**——批 9 ④ 那条仍然适用：图表那一组缺的是
真实语料，不是重复次数。

**噪声标定也跟着变好**：12800 个纯噪声掉分的 95% 分位数 **0.67 → 0.60**，
纯噪声下 |掉分| ≥ 0.5 的比例 **8.9% → 6.2%**（`--repeats 5` 买到的统计功效）。
本次表仍用 `CAUGHT = 0.89`，比标定值保守，没改。

### 突变验（11 个突变，11 个被抓住）

每一条修复单独撤掉，对应的闸必须变红。**基线 196 绿。**

| # | 把什么改坏 | 结果 |
|---|---|---|
| ① | 短路整个撤掉（同参数照样打后端） | ✅ 6 红 |
| ② | 跨轮的重复也只回一句「已经查过」 | ✅ 1 红 |
| ③ | 账本不再给短路层报轮次（`before_round`） | ✅ 1 红 |
| ④ | 事实日期不入账 | ✅ 2 红 |
| ⑤ | 日期错位一条（对到下一条事实身上） | ✅ 4 红 |
| ⑥ | 被取代的那条不带回来，只标记 | ✅ 2 红 |
| ⑦ | 未裁决的冲突也当成「被取代」 | ✅ 1 红 |
| ⑧ | `summarize` 不按前置条件分组 | ✅ 2 红 |
| ⑨ | 取材器不报偏移（退回 `find` + 中点兜底） | ✅ 1 红 |
| ⑩ | 数字块不再优先挑后面还有正文的 | ✅ 1 红 |
| ⑪ | 定位不到时又去编一个位置 | ✅ 1 红 |

③ 是专门补的一条：`before_round` 被删掉时，`query_cache` 里的「这一轮」
永远停在初值，于是**跨轮的重复也会被当成同一轮**只回一句提示——
按上面那次真跑，第 2 轮 45 条材料会整批消失，而且没有任何报错。
写第一版时这条没有闸盯着，是照突变清单反推补上的。

⑩ 也是反推补的：最早那条「优先挑后面还有正文的」用例，在测试用的那篇笔记上
**换成老实现也照样绿**（那篇最密的一节本来就不在末尾）。
另写了一篇「末节数字最密」的用例才真的钉住。**没抓住先怀疑用例不够。**

### 计划外发现

1. **`before` 那一半也是错的**（见上）。台账批 9 只记了 `after` 恒为空，
   而同一个兜底把 `before` 变成了「整篇的前半截」。
   *只报一个症状的 bug，修的时候要把它的整条因果链走完。*
2. **批 9 台账自己读错了一个四舍五入后的数**（0.888 当成 0.89 报「抓住」）。
   报告里的数字一旦被四舍五入，就不能再拿去跟阈值比。
3. **`superseded_by` 全库零条**：冲突收件箱上线至今没有一条被裁决过。
   2.2 里「已裁决」那条路径在生产里目前零流量——它是对的，但今天不产生收益；
   ~~今天产生收益的是 open 那一档的提醒。~~
   **后半句批 12 撤回**（批 11 H1）：真实用户名下 open 冲突也是 0 行，
   **两条分支在生产里都是零流量**。
4. ~~**`kb_conflicts` 那 4 行里至少 3 行是误报**……这是实证依据，不是推测。~~
   **整条批 12 撤回**（批 11 H1 自验）：那 4 行分属 `fresh678` / `fresh678b` /
   `shot-demo`，**三个全在 `corpus_lineage.FIXTURE_USERS` 名单上**，真实用户
   一行都没有。拿夹具的行算比例，正是那个模块整篇在禁止的事——
   **而且这是语料污染第三次，这次绕过的是我们自己刚建的判据**。
   「未裁决的不许当成取代」这条设计仍然成立，但它的依据只剩
   `conflict_confirm.py` 开头那次**真实用户**的实拍（两条候选全是误报）。
5. **短路省得掉查询，省不掉那次规划调用。** 真跑里 4 次重复查询被短路，
   但模型仍然花了一次模型调用去**规划出**这批重复查询。2.1 的上限就在这儿，
   2.4 / 2.5 才治得了它。
6. **第 2 轮 `facts_new = 0` 而 harness 没停。** `material_used_up` 是在第 3 轮
   才触发的。`modes.py` 里那条阈值「几乎不会触发」的老注释，这次有真数了：
   连着一轮零新材料仍在继续写。2.5（覆盖率驱动停机）该拿这个当依据。

### 闸

后端 **1380 passed**（批 9 基线 1340，新增 40 条：短路 12、被取代 9、
账本 6、测量台 13）。前端 **51 文件 / 254 条**全绿。
`test_doc_counts` / `test_directory_map` 当场抓到三处文档没跟上
（middleware 14→15、目录图缺 `query_cache.py` 和 `supersede.py`、
`harness/__init__.py` 的地图缺 `query_cache.py`），已同步。
`test_facts_accumulate` 那条「`st.facts` 只有一个写入方」的闸也抓到了
`supersede.py`——它是这一批唯一改变材料的东西，白名单里写明了为什么。

### 下一步

1. **2.4（账本摘要进 prompt，以「缺口」形式）现在有实测依据了**：真跑里
   第 2 轮把第 1 轮的三条查询一字不差重发，而账本里明明记着那三条查过、
   查回来什么。缺口形式（而不是库存形式）是 §10⑤ 那条反面证据要求的。
2. **2.5（覆盖率驱动停机）的依据也有了**：`facts_new = 0` 的那一轮没停机。
   注意别只看这一个信号——短路之后「没带回新的」会更频繁地出现，
   两条改动叠在一起会互相放大，得一起测。
3. **`factual_grounding` 对占位符仍然是全表样本量最大的失败行**
   （5 篇 50 次，掉 0.00，三批一致）。跟接线无关，`grounding_rules.
   placeholder_lines` 本来就能确定性地抓——该按 5.x 交给代码判据。
4. **`right_kind` 翻成「没抓住」**（1.2→1.2）。n=1 篇不下结论，但它跟
   `chart_validity`(handwrite) 的「未跑」一起说明图表那一组**必须先有第二篇
   真实语料**，否则这 7 维一直是在一篇笔记上自说自话。
5. 短路的白名单是手写的，加工具时要顺带看一眼；`test_query_cache` 里那条
   「白名单里不许有会写东西或读正文的工具」是它的闸。

## 批 11 · 审查复核批 7–10（2026-09-17）

审查 agent 对抗性复核四批。判定：**批 7 / 批 8 可过（带保留）；批 9 只能当中间态不得引用；批 10 不能过。**

### H1 语料污染**第三次**，而且绕过了自己刚建的判据（自验属实）

批 10 的 `supersede.py` 写着「库里 4 行 open 冲突有 3 行是误报……这是实证依据」。
自验：

```
kb_conflicts 全部 4 行 → fresh678(2) / fresh678b(1) / shot-demo(1)
三个都在 corpus_lineage.FIXTURE_USERS 名单上
真实用户 terrence：0 行
```

**后果两条**：① 那个「3/4 是误报」的比例正是 `corpus_lineage` 自己的文档**明令禁止**
用夹具算的那种数；② 台账写「今天产生收益的是 open 那一档的提醒」是错的——
terrence 的 open 也是 0，**`Supersede` 两条分支在生产里都是零流量**。

**最要紧的是它怎么绕过去的**：`supersede.py` 直接调 `store.list_conflicts`，
**没走 `corpus_lineage`**。批 7 刚把血缘判据抽成共用模块，批 10 就从旁边绕过去了。

> **新规矩（第三条）：建了判据不等于用了判据。**
> 凡是「从库里取数据用来支撑一个结论或一条产品行为」的地方，
> 都必须经过 `corpus_lineage`，并且**要有闸禁止绕过**
> （就像仓里已有的「禁止长出第二份 `FIXTURE_USERS`」那条）。

### H3 头条 p 值是两个变量一起动的（审查做了隔离实验）

台账批 10 写「`fits_context` 从 p=0.105 变成 **p=0.0015**——判词一个字没动」。
但批 9 是 `--repeats 3`、批 10 是 `--repeats 5`，**repeats 和上下文修复同时变了**。
审查用同一份日志按 r3 子集重算，隔离出上下文修复单独的效果：

| 维度 | 批 9（坏上下文 r3） | **r3 修好上下文** | 批 10（r5 修好） |
|---|---|---|---|
| `fits_context` | 0.44, p=0.105 | 0.56, **p=0.0205** | 0.53, p=0.0015 |
| `spine_fidelity` | 0.67, p=0.094 | 0.67, **p=0.0937** | 0.60, p=0.0232 |

**`fits_context` 的方向站得住**（光靠修上下文就从 0.105 过到 0.0205），
**但 0.105→0.0015 这个幅度里一大半是 repeats 买的**；而 `spine_fidelity`
修好上下文后 p=0.0937 跟批 9 的 0.094 一模一样——
台账把它写在「上下文修对之后重测」一节里说「显著了」，
**实际 100% 是 repeats 3→5 的功劳、0% 是上下文修复**。

### H2 批 10 唯一会改材料的东西，零灵敏度覆盖，而且自相矛盾

`supersede.py` 特意写了「**不按 `fact_budget` 再裁一刀**：被挤掉的话，
被更正的那条反而留在材料里，比不补更糟」——但它把更正行 append 在**末尾**，
而 `score_context.material()` 是**从头累加、`break` 截断**
（实测 60 条 806 字只留下 11 条）。**它防的那个失败模式在打分器那一侧原样发生。**

### H4 / M4 / M5 灵敏度台的语料和材料都比数字看起来弱

- **材料是从干净正文里摘的**，于是打分器手里拿的是「正文原句的逐字副本」当知识库事实
  ——四条对材料判分的维度测在**最有利的情况**下，那是**接线通没通的上界**，不是生产灵敏度。
- **5 篇语料的真实质量远弱于「5 篇」这个数字**：唯一带表那篇，表里**每个格子都是占位符**
  （"填写具体金额"）；唯一带图那篇，源 mermaid **本身就是坏的**；
  取材器交给打分器的 subject 开头是一个游离的围栏收尾符 ``` 。
  所以图表/表格那几维的「无从判断 / 基线偏低」**是取材缺陷，不是"这篇没图"**。
- 血缘名单还缺三个**跑在真实 user_id `terrence` 下**的脚本签名
  （`harness_stress_test` 的 `压测-*`、`agent_tools_ab` 的 `ab-*`、`full_output_sample` 的 `sample-*`）。
  今天没出事是运气。

### M1 / M2 两个突变存活

- `_verdict` 改成拿**四舍五入后**的掉分比阈值 → **1380 条全绿**。
  批 10 自己在台账里写了这条教训（"数字一旦被四舍五入就不能再拿去跟阈值比"），
  **只修了读数、没留闸**，而 `CAUGHT=0.89` 且上次出事的正是 0.888。
- `query_cache` 的分母改掉 → **1380 条全绿**。
  「重复查询率 33.3%/40%」这个头条数就是这个分母算出来的，**没有任何用例钉住它**。

### 审查确认没问题的（有依据）

`loop._evaluate` 传的确实是 `st.facts`（改成 `facts_new` → 2 红）；
不存在上下文溢出风险（最坏情形构造出来 20645 字，远低于上限）；
6000 字截断真的生效且尾注真的加上（撤掉 → 1 红）；
写作和打分看的窗口确实一样（改掉 → 1 红）；
跨轮短路回的确实是完整结果（实测 1508 字原样返回）；
`before_round` 报轮次那条闸是真的（撤掉 → 1508 字变 67 字、零报错）；
白名单跟 memory 组八个工具**对称差为空**；p 值种子固定、报告逐字节可复现。

### 下一步（批 12 整改）

1. **H1**：`supersede` 走 `corpus_lineage`；加闸禁止绕过血缘判据取数
2. **H2**：更正行要能活过截断（放最前 / 或截断时优先保留）；给它配一条 probe
3. **H3**：台账那张表拆成「上下文修复带来的」和「repeats 带来的」两列；
   `spine_fidelity` 那行改回「不是上下文的功劳」
4. **M1 / M2**：两个存活的突变各补一条闸
5. **M4 / M5**：修 `chart-block` 取材器（跟批 10 修的 `numeric-block` 同型）；
   血缘名单补三个 terrence 下的脚本签名
6. **H4**：材料改成不从干净正文摘（或明确标注这是上界），台账相应加免责

## 批 12 · 整改批 11 的六条（2026-09-17）

批 11 判「批 10 不能过」，六条整改逐条落地。**产品代码只动了两个文件**
（`middleware/supersede.py` 的依据和更正行记号、`score_context.py` 的截断），
其余全在测量台和闸上。

### 改了什么

| # | 改动 | 落在哪 |
|---|---|---|
| ① | `supersede` 那条「实证依据」换成**真的那条**（`conflict_confirm.py` 的真实用户实拍），并写明上一版那个比例是拿夹具库算的、两条分支在生产里都是零流量 | `app/harness/middleware/supersede.py` |
| ① | **三条闸禁止绕过血缘判据取数**（分层判断见下） | `tests/test_corpus_lineage.py`（+4 条） |
| ② | 更正行带 `NOTICE_MARK`，**打分那一侧的截断按记号优先保留**（并排在材料最前） | `score_context.py` + `supersede.py` |
| ② | 给它配了一条 bench probe：`note/whole/use_superseded_date`（材料里放一条被取代的旧事实 + 生产写的那行更正） | `scripts/dimension_sensitivity_bench.py` |
| ③ | 批 10 那张表拆成三列（批 9 坏上下文 r3 / 修好 r3 / 修好 r5），`spine_fidelity` 那一行的结论改回来 | 本文件批 10 那一节 |
| ③ | **报告头记 `repeats`**（连同 notes / caught / alpha / 重排次数 / 种子），且日志里没进统计的行**分两类报** | 同上 |
| ④ | `_verdict` 拿没四舍五入的掉分比阈值 → 补闸；`query_cache` 的分母 → 补闸 | `tests/test_dimension_sensitivity_bench.py` / `tests/test_query_cache.py` |
| ⑤ | `chart-block` / `chart-block-narrated` 的引子只认**干净的正文段**（不含围栏标记） | `scripts/dimension_sensitivity_bench.py` |
| ⑤ | 血缘名单补三个真实 user_id 下的脚本签名（`压测-` / `ab-` / `sample-`）+ 一条「签名必须在脚本里逐字找得到」的闸 | `scripts/corpus_lineage.py` + 它的测试 |
| ⑥ | 报告里加一节「材料那几维是**上界**」，架构文档同步 | bench 的 `render_report` + `docs/harness-framework.md` |

### ① 闸怎么立的：两侧的规矩**不是同一条**

`corpus_lineage.py` 在 `scripts/` 下，`supersede.py` 是产品代码，而
**产品代码不该依赖 `scripts/`**。想清楚之后分成两侧：

* **脚本那一侧（硬规矩）**：结论要拿去改判词、定阈值，语料是谁产的直接决定
  结论真不真。所以——**从笔记库取数就必须 import `corpus_lineage`**
  （`test_从库里取数的脚本必须走血缘判据`）。形状照抄仓里已有的那条
  「bench 里不许再长出一份 `FIXTURE_USERS`」：那条管「别再写一份名单」，
  这条管「取了数就得用名单」，两次出事正好是这两个形状。
* **产品那一侧（反过来）**：`corpus_lineage` 的知识全部是**关于测量脚本的**，
  只在这台开发机上成立；生产里每个用户只看得见自己的数据，运行时根本没有
  「夹具用户」这个概念。**把它下沉进 `app/` 是错的**——那等于把开发机的事实
  变成生产依赖。所以产品这边**不许 import 它**
  （`test_产品代码不许依赖scripts里的血缘判据`，查 import 不查文本：
  第一版用子串查，当场把 `supersede.py` 里那段「为什么这条依据是假的」误伤了）。

  那产品禁什么？**禁那次真正出事的动作：拿本机库里的行当依据。**
  `app/harness/` 里每出现一句「库里 N 行 / N 条」，都要进白名单并注明这个数
  出自哪次真跑（`test_产品代码不许拿本机库里的行当依据` + 一条防白名单腐烂的）。
  今天名单里只有两条，都是 `terrence` 真库上真跑量到的（412 条事实 / 341 条
  成本记录）。**判据宁可窄一点**：只认「库 / 表 + 数字 + 行 / 条」这一种写法，
  不做语义推断——换个说法绕得过去，但误伤一条真实拍出来的依据更贵。

### ② 更正行为什么按记号保留、而不是插到最前面

材料这一份**有两个读者**：写作那一步（`prompts.facts_block`，全量不截断）和
打分那一步（`score_context.material`，6000 字从头累加、到点 `break`）。
按位置修只对其中一个成立，下一个人换个窗口（计划 3.2 的事实索引要动的正是这里）
就又漏了。所以记号跟位置无关，`material()` 认记号保留。

记号放在**行尾**不放行首：`checks/citations.supplied_ids` 认的是行首那个
`[事实 id]`，插到行首会让「带回来的那条新事实」不再算给过的材料，
模型引用它时被当成悬空引用去查库（`test_带回来的那条仍然算给过的材料` 钉着）。

### ③ 拆开之后的那张表（批 10 头条，**两个变量分开记**）

| 维度 · probe | ① 批 9：坏上下文 · r3 | ② 修好上下文 · r3 | ③ 批 10：修好 · r5 | 上下文买到了什么 | repeats 买到了什么 |
|---|---|---|---|---|---|
| `fits_context` · eda/heading_flood | 掉 0.44，p=**0.105** | 掉 0.56，p=**0.0205** | 掉 0.53，p=**0.0015** | **方向站得住**（光修上下文就过了线） | 0.0205→0.0015 全是它 |
| `spine_fidelity` · note/off_spine_graft | 掉 0.67，p=**0.094** | 掉 0.67，p=**0.0937** | 掉 0.60，p=**0.0232** | **0%** | **100%** |

**哪些结论变了**：

1. `fits_context` 那条「**接线才是瓶颈，判词一个字没动**」**仍然成立**——
   但幅度要改口：从 p=0.105 到 **0.0205** 是上下文修复买的，
   到 0.0015 的那一段是 `--repeats` 3→5 买的。
2. `spine_fidelity` 那条**撤回**。批 10 把它写在「上下文修对之后重测」一节里
   说「显著了」，实际修好上下文之后 p=0.0937 跟批 9 的 0.094 一模一样，
   **100% 是 repeats 的功劳**。批 10 的 ④「顺带的变化」里那句也划掉了。
3. 从这一批起，**报告头印着 `repeats`**。不记它的后果不是少一个数：
   拿默认 `--repeats 3` 去读一份 r5 的日志，那张表会实质不同，而且
   **328 行有效数据会被报成「对不上语料」**（见下）。

### ⑤ `chart-block` 那个取材缺陷，和它的代价

唯一那篇带 mermaid 的真实笔记（`06647b9c2031`）**全篇只有 3 个** ``` ——
图前面那一段是 `]` 加一个**游离的围栏收尾符**（上一次生成漏掉的残片）。
上一版拿「命中块前面那一段」当引子，于是交给打分器的 subject
**开头是一个孤零零的 ``` 、整段奇数个围栏**。所以 `chart_validity`
「干净版恒 0 / 无从判断」**是取材缺陷，不是"这篇没图"**——跟批 10 修的
`numeric-block` 同型（那次是「命中块前面那一段」其实是整篇的前半截）。

修法：引子只认**不含围栏标记**的正文段；一段都挑不到时**引子留空、起点指到块
本身**，不拿残片凑（`clean_leads`）。

**代价要说出来**：格子身份带正文指纹，这一改让 **60 行**图表那一组的旧分数
自动作废，6 条 chart probe 现在全是「未跑」。在重跑之前，
**图表那一组一条结论都不许引用**（架构文档第 4 节已加这一段）。

### 突变验（15 个，15 个变红）

每条改动单独撤掉，对应的闸必须变红。**基线 1415 绿。**
（每次撤完都 `rm -rf __pycache__`——见「计划外发现」③，这次真栽了一回。）

| # | 把什么改坏 | 结果 |
|---|---|---|
| ① | 产品注释里又拿本机库的行当依据 | ✅ 1 红 |
| ② | 白名单里留着一条已经不存在的论断 | ✅ 1 红 |
| ③ | 产品代码 import `corpus_lineage` | ✅ 1 红 |
| ④ | 新增一个从库里取数、不走血缘判据的脚本 | ✅ 1 红 |
| ⑤ | 三个新签名之一漂了（脚本改了格式、名单没跟） | ✅ 2 红 |
| ⑥ | 三个新签名整个删掉 | ✅ 4 红 |
| ⑦ | `material()` 退回「从头累加、到点就停」 | ✅ 3 红 |
| ⑧ | `supersede` 写的更正行不带记号 | ✅ 2 红（bench 那条 probe 也红了） |
| ⑨ | `_verdict` 拿四舍五入后的掉分比阈值 | ✅ 1 红 |
| ⑩ | `query_cache` 的 `calls += 1` 挪到白名单判断之后 | ✅ 1 红 |
| ⑪ | 引子退回「前面那一段」不看围栏 | ✅ 4 红 |
| ⑫ | 更正行不加进 bench 的材料 | ✅ 2 红 |
| ⑬ | `production_context` 不走 `material` 钩子 | ✅ 2 红 |
| ⑭ | 脚本自己抄一份更正行的格式 | ✅ 2 红 |
| ⑮ | 两类「没进统计的行」又混成一个数 / 报告头不记 `repeats` / 上界那一节删掉 | ✅ 各 1 红 |

⑮ 第三条**第一版突变没抓住**：只删了那一节的标题、正文还在，测试照绿。
换成把整节删掉才是真的撤回修复。**没抓住先怀疑用例不够**——这次是突变体不够。

### 计划外发现

1. **批 11 自己那个「976 行有效数据被误报」的数要拆**。实测（本机日志）：
   拿默认 `--repeats 3` 读那份 r5 的日志，报出来的 976 行里
   **328 行是「重复次数排在外面」（数据仍然有效）、648 行是指纹真对不上的**。
   前者调回 `--repeats 5` 就回来，后者必须重跑——两类混成一个数，
   人只会当成「日志脏了」。现在分开报，两个数都印在报告头上。
2. **`chart-block-narrated` 跟 `chart-block` 是同一个毛病**，批 11 只点了后者。
   同一段围栏残片会被 `covers_the_data` 那条 probe 当成「叙述」的一部分——
   修一个不修另一个，等于把这个缺陷留了一半。
   *只报一个症状的 bug，修的时候要把它的整条因果链走完*（批 10 记过同一条）。
3. **`__pycache__` 又咬了一次，而且这次是在"撤回突变之后"。** 撤回突变体、
   恢复原文件之后跑全量，`test_query_cache` 报红——文件内容是对的，
   红的是上一轮突变体留下的 `.pyc`。批 5 记的是「植入突变体之前要清」，
   这次证明**撤回之后同样要清**：否则会把一条好闸误判成坏闸，
   然后去"修"一个根本不存在的问题。
4. **这条 probe 是这套 harness 里第一条会动材料的 probe。** 为此给 `Probe`
   加了 `material` 钩子，并配了一条闸钉住**只有它一条在用**
   （`test_别的probe的材料一个字都没动`）：钩子漏进别的 probe，整张表的材料
   都会变，而格子指纹会让旧数据**静默**作废重跑，钱花了、症状没有。

### 闸

后端 **1380 → 1415**（+35：`test_dimension_sensitivity_bench` +20、
`test_corpus_lineage` +8、`test_supersede` +3、`test_score_context` +2、
`test_query_cache` +2）。前端 **51 文件 / 254 条**全绿。
`test_doc_counts` / `test_directory_map` / `test_architecture_claims` 没响
（没加 Mode / check / middleware / 工具）；架构文档第 4 节、第 18 节、
middleware 表里 Supersede 那一行按这一批改了（植入器 27 → 28）。

### 这一批**没做**什么

* **没跑评测。** 这一批改了取材器（作废 60 格）、加了一条新 probe（从没跑过），
  两件事都要花钱重跑；按仓里的规矩**跑之前先说明改动和成本**。
  所以台账里这一批**没有任何新的灵敏度数字**——改的是台子和闸。
* **材料仍然从干净正文摘**（H4 只做了「标注是上界」那一档）。
  换成「从别的笔记摘材料」需要先有证据说明新做法更接近生产，
  为改而改会把这张表唯一还能比的基线也弄丢。

### 下一步

1. **重跑这两组**：图表那 6 条 probe（60 格作废）+ 新的 `use_superseded_date`
   那一条。跑之前报一次成本。`use_superseded_date` 掉分为 0 是个**硬结论**：
   材料里明写着「这条取代了那条」都判不出来，那就该动判词了。
2. **H4 那一档的下半截**：材料换成「从**别的**笔记摘」或真跑一次检索拿真材料，
   要能拿出证据说明新做法更接近生产（比如量一下生产材料跟正文的逐字重合率）。
3. 2.4（账本摘要以「缺口」形式进 prompt）和 2.5（覆盖率驱动停机）的依据
   批 10 已经攒齐，两条会互相放大，得一起测。
4. `chart_validity` / `right_kind` 那一组仍然卡在**只有 1 篇真实语料带图**。
   取材修好之后这条限制没变——要量准它得先有第二篇真实产出。

## 批 13 · 2.4 账本摘要进 prompt（缺口形式）+ 2.5 覆盖率驱动停机（2026-09-18）

批 12 说「2.4 / 2.5 会互相放大，得一起测」。这一批把两条一起做完、一起测。
**产品代码动了六个文件**（`middleware/ledger.py` 加缺口摘要、`hooks/note.py` 接线、
`agent_loop.py` 停机、`policy.py` 换掉那个脏信号、`params.py` 开关、
`prompts/note.py` 摆位），其余在闸和测量台上。

### 改了什么

| # | 改动 | 落在哪 |
|---|---|---|
| 2.4 | **账本摘要进检索规划 prompt，以「缺口」形式**（没取过的排最前、已取压成一个计数） | `middleware/ledger.gap_summary()` |
| 2.4 | 主题树的分母折进账本（它是 `prepare` 直接调的，`fold` 看不见） | `ledger.note_topics()` + `hooks/note.prepare` |
| 2.4 | 摘要摆在 `retrieval_plan_user` **最前面**；一个开关整段关掉 | `prompts/note.py` + `params.LEDGER_IN_PROMPT` |
| 2.5 | **连着两次调用一条新 id 都没带回来就停**（确定性，不用模型） | `agent_loop.BARREN_STOP = 2` |
| 2.5 | 跨轮那份「已经有哪些 id」由账本喂进来 | `hooks/note.prepare` 的 `known_ids` |
| 2.5 | 策略器收预算的判据从 `tool_calls == 0` 换成 `tool_stopped_barren` | `policy.adjust` + `middleware/runtime.py` |
| 审查 | **停机那一发不再丢掉同一条消息里剩下的工具调用**（半成品的真 bug，见下） | `agent_loop.py` |
| 审查 | 灵敏度 bench 的「没进统计的行」从两类拆成**三类** | `scripts/dimension_sensitivity_bench.py` |

### 接手复核：半成品哪里不够格

逐条核对上一个 agent 留下的 15 个文件 / +658 行。**四条通过，两条不通过。**

**通过（有依据、有闸）**：① 摘要确实是缺口形式（`untouched` 按库里条数倒序排最前，
已取压成一句「另有 N 个方向这次已经取过」，一个名字都不报）；② 那条边界守住了——
摘要里没有任何「用了几条 / 还剩几条没用」，`test_摘要里不许出现用了几条` 逐词钉着
（`_FACTUAL_GROUNDING` 的 guidance 写着「检索到的事实没有被全部用上，明确不算不足」，
那句话是扣过一次分、下一轮就编出知识库里没有的日期人名才写进去的）；
③ `params.LEDGER_IN_PROMPT` 能单独关掉 2.4 而不牵连账本；
④ 2.5 是确定性判据，`BARREN_STOP = 2` 不是 1（一发空手很常见）、只有 `FACT_TOOLS`
参与计数（`list_topics` 算进去会把两级路径在第一步判成走到头）。

**不通过 ①：`stopped_barren` 那一发会把同一条 assistant 消息里剩下的工具调用整个丢掉。**
第一版的 `break` 打在「遍历这一条消息里的若干个 `tool_calls`」那层循环上。于是
`extra` 里那条 assistant 消息带着 3 个 `tool_calls` 返回，后面只跟着 2 条 tool 结果。
**这不是洁癖**：`hooks/block.prepare` 会把 `msgs + extra` 原样喂给第二次
`gather_context`（EDA / ANALYSIS 的 `focus_groups` 那一轮），而「带 `tool_calls` 的
assistant 消息后面必须跟齐每个 `tool_call_id`」是接口硬校验，缺一个直接 400。
EDA / ANALYSIS 的 groups 里有 `memory`（= `FACT_TOOLS`），`MAX_CALLS_PER_ITER` 又允许
一条消息发 5 个——**触发条件齐全，而 1433 条闸全绿**。
改法：停机判据只管「不再发起下一轮」，当前这条消息里已经发出去的调用照常执行完；
补一条闸逐一核对 `tool_call` 和 `tool` 消息的 id 配对（突变 ⑲）。

**不通过 ②：注释里写着一条假依据。** `agent_loop` 和 `test_tools` 两处都写着
「策略器拿 `truncated` 去判要不要加预算」——**全仓没有一处读 `RoundFeedback.tool_truncated`**
（`runtime.py` 写、无人读）。`adjust()` 读的是 `tool_stopped_barren`。
一条假理由比没理由更贵：下一个人会照着它去「保持兼容」。两处都改成实话。

**另外补了两条闸**（原来只钉了「在不在里面」，太松，批 12 ⑮ 栽过同一个形状）：
摘要必须是检索规划 prompt 的**第一块**（把它挪到末尾，原来的闸全绿）；
bench 报告头必须把三类没进统计的行分开报。

### 真实渲染出来的账本摘要（`terrence` 真库，4 轮那次跑的第 2 轮）

```
【这次跑到现在，哪些方向还没取过】
- work_product_design：库里 3155 条，一条都没取
- work：库里 2862 条，一条都没取
- work_marketing：库里 1140 条，一条都没取
- learning：库里 1097 条，一条都没取
- personal：库里 995 条，一条都没取
- work_product：库里 964 条，一条都没取
- project：库里 621 条，一条都没取
- learning_school_interview_prep：库里 440 条，一条都没取
（还有 32 个方向同样没取全。）

【这些查询已经发过了，别再原样发一遍】
- filter_facts topic=work_hardware
- filter_facts topic=work_product_testing
- filter_facts topic=work_product_release
- filter_facts topic=work_product_cost_control

这一轮把力气花在上面还没取过的方向上，**只查跟这一节真的相关的那些**——不相关的
方向不用管，这些数是用来找空白的，不是要求你取满。
```

**两处是渲染出来才发现的**（不是设计时想到的）：

1. **第一版这一段里一条「一条都没取」都没有**，只有三条已经查过的轴。原因是主题树在
   `prepare` 里**直接调**、不进 `trace.calls`，`fold` 永远看不到它——而 [LED] §10⑤ 那个
   例子（「定价：18 条，一条都没取」）正是靠主题树才知道这个方向存在。补了 `note_topics`，
   **只补分母、不记一条查询**（模型没发过 `list_topics` 这一条）。
2. **第一版把 `render_chart kind=flow … → 0 条，换个方向，不要换措辞重试` 写进了
   「已经发过的查询」**。`render_chart` 根本不返回事实，「0 条」是把「没有事实行」读成
   了「查空了」，而那句话会劝模型别再画图。现在清单只过 `query_cache` 的白名单。

**还有一处渲染出来才看见、这一批没改**：缺口按库里条数从多到少排，于是 `work` 2862 /
`learning` 1097 / `personal` 995 这三个大桶**每一轮都排在最前面**，而它们跟「硬件量产
未决项」这一节毫无关系。上一个 agent 为此在末尾加了那半句相关性护栏。
**真跑 16 次没有一次跑偏**（`both` 臂的查询全落在 `work_product_*` / `work_hardware` /
`work_product_cost_control` 上，一次都没去查 `learning` / `personal`），所以这一批
**不动排序**——没有证据支持的相关性启发式，加了就是又一个没人验过的判据。记在下一步。

### 真跑前后对照（`terrence` 真库，`rails_off=("save",)`，**一篇笔记都没写**）

三臂，同一批三个种子、4 轮预算：`off` = 2.4 / 2.5 都关（`LEDGER_IN_PROMPT=False`
且 `BARREN_STOP` 调到不可能触发）；`b25` = 只开 2.5（隔离实验）；`both` = 生产默认。

| 臂 | 跑 | 轮 | `tool_calls`/轮 | `repeat_calls`/轮 | 重复率 | `facts_new=0` 的轮 | `facts_new`/轮 |
|---|---:|---:|---:|---:|---:|---:|---:|
| off（都关） | 16 | 44 | 3.50 | 1.14 | **32.5%** | **4** | 21.8 |
| b25（只 2.5） | 3 | 9 | 3.22 | 0.56 | 17.2% | 0 | 23.6 |
| both（都开） | 16 | 28 | 4.07 | **0.14** | **3.5%** | **0** | 49.9 |

**这三个数必须按轮归一化，不能按跑加总**——`both` 臂 16 次跑里有 10 次第 1 轮就
`complete` 收工（`off` 是 6 次）。按跑加总的话「重复查询少了」里有一大半只是
「没有第 2 轮可repeat」。上一版计划文档里写的 `5.7 → 0.5` 就是按跑加总的数，
**这一批把它换成按轮的**。

**2.5 单独值多少**：`b25` 把重复率从 32.5% 压到 17.2%、空手轮清零，但重复率**压不到 0**
——批 10 记的那条「短路省得掉查询、省不掉那次规划调用」在这儿再次成立：
2.5 治的是「已经查到头了还在发」，**治不了「又规划出同一批查询」，那是 2.4 治的**。

**`tool_calls`/轮反而升了**（3.50 → 4.07）。这不是回退：缺口清单给了模型更多**不同的**
方向，所以单轮发得更多而重复更少；同时整次跑的轮数从 2.75 降到 1.75，
**每次跑的总调用是 9.6 → 7.1**。

### 产出本身：同一个种子、同样 4 轮，**这才是头条**

聚合分看不出这一条，得读产出（`off` / `both` 各 7 次带正文留档的跑）：

| | off | both |
|---|---:|---:|
| 跑 / 轮 | 7 / 19 | 7 / 18 |
| 字 / 跑 | 1538 | 1419 |
| **正文里的事实 id 引用 / 千字** | **2.42** | **4.53** |
| **占位句（「这里需要补上…」）** | **6** | **1** |
| 重复率 | 33.3% | 5.8% |
| 空手轮 | 3 | 0 |

同一个种子（「硬件量产前的未决项」）、同样跑满 4 轮、长度几乎一样（2514 / 2580 字）：

* **`off` 那篇一条事实 id 都没引**，通篇是「先按风险是否阻断量产来筛」「每一项都要写清
  影响范围和验证证据」这类**换哪家公司都成立**的模板，外加 5 句「这里需要补上…」。
* **`both` 那篇引了 12 处、9 个不同的事实 id**，写的是这个用户自己的东西：KO/EVT/DVT/PVT/MP
  节点、EVT 分纯主机 / 手表 / 手环三种形态、EVT 大节点 4 月 16 日、T0 预计 5 月 15 日、
  PVT 排在 6 月 18 日、DVT 原计划用 T0 模具。

`factual_grounding` 是这张表**第一大阻塞项**，[LED] §10⑤ 那条反面证据说的正是这件事
可能反着来（缩小搜索空间）。**实测是正着来的**——但请注意这是 n=7 对、一份语料、
一个用户，**不外推**。

**一处代价要说出来**：`both` 臂第 1 轮就收工的比例从 6/16 升到 10/16，平均每跑
1432 字 → 922 字。材料更实 → 第 1 轮六维全 2 → `complete`。分数没变差、引用密度更高，
但**用户拿到的字数变少了**。这一条 n 太小（16 次跑），不下结论，只记账。

### 图表那 60 格重跑（批 12 作废的）

| 维度 · probe | 干净 | 植入 | 掉分 | 篇 | 次 | p | 结论 |
|---|---:|---:|---:|---:|---:|---:|---|
| `has_charts` · eda/chart_to_prose | 2.0 | 0.6 | 1.4 | 1 | 10 | 0.0445 | **抓住** |
| `right_kind` · chart/chart_to_image | 1.8 | 1.2 | 0.6 | 1 | 10 | 0.3994 | 只动了一点 |
| `chart_validity` · chart/break_mermaid_fence | 1.2 | 1.2 | **0.0** | 1 | 10 | 1.0 | **没抓住** |
| `chart_validity` · chart/handwrite_mermaid | | | | 0 | 0 | | 未跑（干净版本身就有这个缺陷） |
| `covers_the_data` · eda/drop_mentioned_node | | | | 0 | 0 | | 未跑（取不到 `chart-block-narrated`） |
| `data_grounding` · chart/shift_dates | | | | 0 | 0 | | 未跑（植入器不适用） |
| `no_duplicate_charts` · eda/duplicate_chart | | | | 0 | 0 | | 未跑（植入器不适用） |

**6 条里只有 3 条跑得起来，另 3 条是结构性跑不起来、不是预算不够。**
取材修好换来的是 `chart_validity` 的干净版基线**从 0 抬到 1.2**——批 12 说那个 0 是取材
缺陷，说对了；但**这一维仍然判不出被打断的围栏**（1.2 → 1.2）。
**还有一处代价**：`covers_the_data` 从「有（脏）数据」变成「一格都取不到」——批 12 把引子
收紧成「不含围栏标记的正文段」之后，唯一那篇带图的笔记一段都挑不到。修取材缺陷的代价
是这一条 probe 现在彻底没数。**全组仍然 n=1 篇，跨篇一概不下结论**（批 9 ④ 那条仍然适用：
图表这一组缺的是第二篇真实语料，不是重复次数）。

### `use_superseded_date`：**`supersede` 这条路有效**

| 维度 · probe | 干净 | 植入 | 掉分 | 篇 | 次 | p | 结论 |
|---|---:|---:|---:|---:|---:|---:|---|
| `factual_grounding` · note/use_superseded_date | 2.0 | 0.6 | **1.4** | 1 | 10 | **0.0057** | **抓住** |

材料里放一条被取代的旧事实 + 一行 `middleware/supersede` 真写的更正，正文用被取代的
那一版日期——掉 1.4，远在 `CAUGHT = 0.89` 之上，p = 0.0057。
批 12 下一步写着「掉 0 是个硬结论：材料里明写着『这条取代了那条』都判不出来，那就该动
判词了」——**没掉 0，判词不用动**，2.2 那条取材接线是真的在起作用。
n=1 篇 10 次，**不下跨篇结论**；而且这一格跟整张表的材料一样**是上界**（材料从干净正文
摘，生产里是检索回来的转述）。另一篇语料上这条 probe 的成对自验没通过，所以只有 1 篇。

### 突变验（23 个，23 个变红）

每条改动单独撤掉，对应的闸必须变红。**基线 1437 绿。**
（植入前和撤回后都 `rm -rf __pycache__`——批 12 计划外发现③。）

| # | 把什么改坏 | 结果 |
|---|---|---|
| ① | 缺口不再把「没取过的」排最前（退回按名字排） | ✅ 1 红 |
| ② | 「没取过的」和「取了一点的」混在一起排（缺口塌回库存） | ✅ 1 红 |
| ③ | 把已经取过的方向逐个列出来（= 库存清单） | ✅ 1 红 |
| ④ | 加一句「已取回来的还有 N 条没用上」（覆盖率从诊断变指标） | ✅ 1 红 |
| ⑤ | 去掉相关性护栏那半句 | ✅ 1 红 |
| ⑥ | 查空的那条不再写明「别换措辞重试」 | ✅ 1 红 |
| ⑦ | 已发查询清单不过白名单（`render_chart` 混进去） | ✅ 1 红 |
| ⑧ | 同一条查询列很多遍 | ✅ 1 红 |
| ⑨ | 没有分母的轴也报成缺口（编一个 0 出来） | ✅ 1 红 |
| ⑩ | `limit` 这类分页参数进显示（同一条查询看着像两条） | ✅ 1 红 |
| ⑪ | 主题树的分母不折进账本（第一版 2.4 的真实缺陷） | ✅ 1 红 |
| ⑫ | 摘要不接进检索规划 prompt（建了判据不用判据） | ✅ 3 红 |
| ⑬ | `LEDGER_IN_PROMPT` 关掉也照样进 prompt | ✅ 2 红 |
| ⑭ | 摘要整段不进 `parts` | ✅ 3 红 |
| ⑭b | **摘要还在 prompt 里、只是挪到末尾** | ✅ 1 红（这条是新补的闸） |
| ⑮ | 停机判据整个撤掉 | ✅ 3 红 |
| ⑯ | 一发空手就停（阈值 2→1，误伤两级路径） | ✅ 3 红 |
| ⑰ | 元信息工具也算空手 | ✅ 2 红 |
| ⑱ | 跨轮那份已知 id 不喂进来 | ✅ 1 红 |
| ⑲ | **停机那一发丢掉同一条消息里剩下的调用**（本批修的真 bug） | ✅ 1 红 |
| ⑳ | `stopped_barren` 不传给策略器 | ✅ 1 红 |
| ㉑ | 策略器退回「上一轮没用工具就扣预算」那个脏信号 | ✅ 2 红 |
| ㉒ | 产品注释里那条真跑依据从血缘白名单删掉 | ✅ 2 红 |

**⑭b 第一版突变没抓住**——因为突变体写错了（`if x not in parts` 恒假，等于什么都没改），
不是闸不行。改成真的「先 remove 再 append」之后闸立刻变红。
*突变体本身也要验：一个「存活」的突变，先怀疑它压根没生效。*

### 计划外发现

1. **`hooks/block.prepare` 把 `msgs + extra` 喂回下一次调用**，所以工具循环里任何
   「中途 break」都会造出不配对的 `tool_call`。1433 条闸里没有一条在看这个不变量
   ——它只在 EDA / ANALYSIS 的 `focus_groups` 那一轮、且模型一条消息发多个 memory
   工具时才炸。*一个"只在本函数里安全"的 break，要看调用方拿它的返回值去干什么。*
2. **`RoundFeedback.tool_truncated` 是一段死状态**（只写不读），而两处注释拿它当理由。
   跟 [LED] §10⑥ 记的 `st.bag["last_scores"]` 是同一种东西。
3. **`--only` 会让报告把别的 probe 的行全报成「真作废」**：`--only chart-block` 跑完
   报告头印着「**1548** 行指纹对不上（真作废）」，而真作废的只有 **216** 行（= 6 条
   chart probe × 36 行）。`--only` 把 `all_cells` 一起筛小了。照这个数去重跑等于把整张表
   白烧一遍。批 12 刚把「重复次数排在外面」和「指纹对不上」分开报，**同一个形状第三次**。
   补了第三类 `out_of_scope`；**第一版判据太宽**（拿「有没有 cells」当范围），
   于是一条 probe 在这批语料上一格都取不出来时（`chart-block-narrated` 正是这样）
   它那些真作废的旧行被报成「去掉 `--only` 就在」——**反向误伤，比原来的错更难发现**。
   改成由调用方显式传 `--only` 选中的 id，不传就恒为空。两条闸各钉一个方向。
4. **缺口摘要的排序按库里条数，不按相关性**（见上）。真跑没跑偏，但这是设计上的已知弱点。
5. **`axes[*].taken` 只认 `filter_facts` 那条路**：`search_memory` 取回的事实没有主题
   标签，归不到轴上。所以一个只被 `search_memory` 摸过的方向会一直显示「一条都没取」。
   今天不是问题（缺口清单里那几个大桶本来就没被查过），但它是这个数的已知上限。

### 闸

后端 **1415 → 1437**（+22：`test_harness_ledger` +10、`test_note_hooks` +4、
`test_tools` +4、`test_runtime_policy` +1、`test_corpus_lineage` +1、
`test_dimension_sensitivity_bench` +2）。前端 **51 文件 / 254 条**全绿。
`test_doc_counts` / `test_directory_map` / `test_architecture_claims` 没响
（没加 Mode / check / middleware / 工具）；`harness-framework.md` 第 4 节
（图表那一组重跑的结论）和第 9 节（停机 + 账本进 prompt）按这一批改了。

### 这一批的实际成本

`gpt-5.6-luna`，本批全部调用（19 次真跑 × 最多 4 轮 + 30 格 bench）：
**prompt 1,918,140 token（其中命中缓存 1,209,991）、completion 155,159 token**，
模型墙上时间约 51 分钟。

### 这一批**没做**什么

* **没跑剩下那 245 格**。它们是别的 probe 还没补满 5 篇 × 5 次的格子，跟这一批改的
  东西无关；表里的结论在现有 n 上已经稳定。要跑得再报一次成本。
* **没给 `hooks/section.py` 接 `known_ids` / 缺口摘要。** 2.4 / 2.5 的依据和量到的数
  全在 note harness 上。`section` 那条 harness 今天仍然只有循环内的停机、没有跨轮的
  ——**这是写下来的取舍，不是遗漏**（`middleware/__init__` 开头那条「一个 harness 有、
  另一个没有」的教训）。要接得先在 section 上量一次。
* **没动缺口的排序。** 见计划外发现 4。

### 下一步

1. **缺口按相关性排，而不是按库里条数。** 今天前 8 名恒定是 `work` / `learning` /
   `personal` 三个大桶。可用的确定性信号只有 `list_topics` 返回里的**中文别名**
   （`note_topics` 的正则现在把它丢掉了）——拿别名跟这一节的标题 / spine / beats 做
   词面重合，是这个仓一贯的做法（词法暴力，不引入模型）。**先量一次再改**。
2. **`factual_grounding` 对占位符仍然是全表样本量最大的失败行**（4 篇 40 次，掉 0.00，
   四批一致）。跟接线无关，`grounding_rules.placeholder_lines` 本来就能确定性地抓
   ——该按 5.x 交给代码判据。这一批的真跑顺带给了它一个新数：`off` 臂 7 篇产出里有
   6 句占位、`both` 臂只剩 1 句，**材料变实之后占位句会自己变少，但不会变 0**。
3. **图表那一组仍然卡在 1 篇真实语料**，而且现在 6 条 probe 里 3 条结构性跑不起来。
   要量准它得先有第二篇真实产出——这条从批 9 挂到现在，四批没动过。
4. **`b25` 臂只跑了 3 次**（隔离实验够用，但不足以单独下结论）。要说「2.5 单独值多少」
   得补到跟另外两臂一样的 16 次。
5. `chart_validity` 在取材修好之后仍然**判不出被打断的围栏**（1.2 → 1.2）。
   这是判词的问题还是 n=1 的问题，现在分不开——等第二篇带图语料。

## 批 14 · 跑批写坏了用户的两篇真实笔记（2026-09-17）

**这一批不是计划里的。** 批 13 收尾时按惯例核对 `notes.max(updated_at)`，
发现它从 `2026-09-16T02:53` 跳到了 `2026-09-17T15:54`——
而那一批的实施 agent 报告里写着「**一篇笔记都没写**」。

### 损失

| 笔记 | 跑批前 | 之后 | |
|---|---|---|---|
| `e78306202d78`「产品取舍」 | 1976 字 | **650 字** | **丢了 1326 字用户自己写的内容** |
| `06647b9c2031`「未命名」 | 2762 字 | 5279 字 | 被 harness 产出污染 |

**没有永久丢失**：`data/backups/notes-20260917.sqlite3`（09-17 启动时做的）里
两篇都还是跑批前的样子（`updated_at` 停在 09-02 / 09-03）。已恢复，
恢复前把被写坏的那一份存成了 `reason='before_restore'` 的版本，所以这一步也可逆。

### 这是第二次

`harness_quality_sample.py` 的开头记着第一次：
「之前三篇真实笔记的原文因为『备份-还原』机制的结构性盲区**永久丢失**」。
**第一次之后留下的是一段警告注释，第二次照样发生了。**

### 根因分两层

- **机制层**：`rails_off=("save",)` 本身是好的（`loop.py:42` 按名字过滤 middleware），
  `commit` 对 note 模式是空操作。所以是那 19 次真跑里**有些没走 `rails_off` 那条路**
  ——很可能直接打了 HTTP 路由，而那条链带着 `Save`。
- **流程层（更要紧）**：**这件事能查出来，纯粹因为我按惯例核对了一个数。**
  agent 的自我报告在这件事上是错的，而没有任何东西在核对它。

> **这一批定的规矩：凡是只能靠自报来保证的性质，迟早会被报错一次。**

### 两道闸（`scripts/db_guard.py` + `tests/test_db_guard.py` 9 条）

1. **`readonly()`** —— 跑批脚本开真库一律 `mode=ro`。要写必须显式走
   `writable(why=...)`，理由是**必填参数**：它会让「顺手写一下」变成「先想清楚」。
   *不靠「记得别写 SQL」，因为这次出事正是有人以为自己没写。*
2. **`Watch`** —— 把跑批夹在中间，出来核对笔记表指纹，动了就抛。
   指纹是**三样一起看**，因为任何一样单独都骗得过：
   只看行数 → 改内容不涨行；只看 `max(updated_at)` → 改完把时间戳写回去；
   只看总字数 → 删一段加一段正好抵消。三条各有一个单测钉着。
   `harness_runs` / `llm_usage` **故意不在指纹里**——跑批本来就该写它们，
   算进去会让闸天天误报，而**一个天天误报的闸等于没有闸**。

### 写闸的时候自己踩了一次同类错

`fingerprint()` 第一版把时间列**写死**（`notes` 用 `updated_at`、
`note_revisions` 用 `created_at`）——在真库上碰巧都对，单测的最小表上当场
`no such column`。**「在真库上碰巧对」不是对。** 改成按 `PRAGMA table_info` 挑。

### 批 12 那条闸当场抓到了我

加完两个脚本跑全量，`test_从库里取数的脚本必须走血缘判据`（批 12 加的）**红了**
——它们确实从库里取数却没走 `corpus_lineage`。这两个脚本按定义就该看**整张表**
（给全表做指纹 / 按写死的 id 恢复），筛掉任何一篇都会让它们失效，
所以按闸自己的规矩进白名单**并写明理由**，另加一条防白名单腐烂的断言。
*「建了判据不等于用了判据」这条，这次是判据自己证明了它在工作。*

后端 **1437 → 1448**，前端 51/254 不变。

### 下一步

把 `Watch` 接进跑批脚本（`dimension_sensitivity_bench` / `harness_stress_test` /
`soak` / `suite`），让「这次跑批有没有动用户的笔记」变成每次自动核对的事。
然后回到计划：阶段 3（取消截断，`P0`）。

## 批 15 · `Watch` 接进跑批脚本 + 阶段 3「取消截断」（2026-09-18）

两件事：**A** 是批 14 的收尾（把那道指纹闸真的接上去），**B** 是阶段 3 的三条
（`P0`，出自 [CE] §7「截断是最差的一档」）。

### A. `Watch` 接进跑批脚本

批 14 写出了 `scripts/db_guard.py`，但**只是写出来**。批 15 接上：

| 脚本 | 怎么接 |
|---|---|
| `dimension_sensitivity_bench` / `soak` / `suite` / `agent_tools_ab` / `harness_quality_sample` / `writing_quality_bench` / `editing_quality_bench` / `full_output_sample` | `with db_guard.Watch(): main()` ——**一篇笔记都不许动**，动了当场抛 |
| `harness_stress_test` | `with db_guard.Watch(restores=True)` ——见下 |

顺带把散在脚本里自己拼的 `sqlite3.connect` 收掉：`corpus_lineage` /
`dimension_sensitivity_bench` 改走 `db_guard.readonly()`，`restore_damaged_notes`
改走 `db_guard.writable(why=...)`（它是少数真该写真库的）。
**只读连接现在只有一处实现**——拼一次 `mode=ro` 就多一个地方可能漏掉它，
而批 14 的根因正是「以为自己没写」。一条闸钉着：跑批脚本里不许再出现
`sqlite3.connect(`。

#### `harness_stress_test` 那条怎么处理的

它自己的模块文档写着「真实笔记每次用之前备份、用完立刻还原」——**它是真的要写**。

* 用默认 `Watch()` 会天天误报：还原本身就是一次写，`updated_at` 必然前进、
  `note_revisions` 必然多几行。
* 但**不能用 `Watch(allow=True)`**：那一档等于「随便写，不核对」，
  而这个脚本历史上翻车的形状恰恰是**「以为还原了，其实没有」**
  （它自己的注释记着：进程被外层超时杀掉、`finally` 没跑，
  笔记 `27f255a67662` 的原文永久丢失）。

所以新加了第三档 **`Watch(restores=True)`**：跑的过程中随便写，
**出来时每一篇笔记的正文必须逐字回到原样**，对不上就抛；
`updated_at` / `note_revisions` 允许前进，只打印一行「这是还原留下的痕迹」。

#### 指纹补了第四样：逐篇正文摘要

批 14 的三样是行数 / `max(updated_at)` / 正文**总**字数。那三样里只有一样在看
正文，而它是**总和**——**删 A 的 300 字、给 B 加 300 字，总数一个不差**。
批 14 那次事故正好是一短一长（1976→650、2762→5279），**只是没恰好抵消**
才被总字数抓到。第四样是 `{note_id: sha256(content)[:16]}`，"恰好抵消"在它面前
不成立；`restores=True` 那一档要的也正是这一样。

### B. 阶段 3：取消截断（3.1 / 3.2 / 3.3）

| # | 改了什么 | 落在哪 |
|---|---|---|
| 3.1 | 续写 prompt 的正文：**小节索引（每节一行）+ 按需读回的小节 + 当前小节逐字**；`read_section(n)` 工具；`Compact` 从两条长文 harness 退休 | `middleware/sections.py`（新）、`tools/longform_tools.py`（新，新 group `longform`）、`modes.py` |
| 3.2 | 事实：`facts_all` **全量只追加、一条不丢**；进 prompt 的是「更早那些压成一行的索引 + 最近 40 条逐字」 | `middleware/facts.py`、`prompts/fragments.facts_index_block` |
| 3.3 | `prompt_cache_key = note_id:mode:步骤` | `util/llm.set_cache_key` + `hooks/note` / `hooks/section` 的 `prepare` |

两条边界：
* `compact_context` **这个函数没删**——「智能续写」那条一次性路径仍然用它。
  那条路**没有工具循环**，给它指针它取不回来，摘要在那里仍然是较优的一档。
* 事实索引那一行**取自账本**（`ledger.facts[fid]["line"]`），不另造一份索引。
  账本里没有的（兜底检索 / 多跳结果这类不带 id 的）退回按原文截一段
  ——**漏掉它比截短它更糟**，那等于又丢了一条。

#### [CE] §7 那两条风险，实测各自的下场

**风险一：模型不去调那个工具。** —— **没有兑现。**
8109 字那个种子（索引真正生效的那个）上，`on` 臂 **12 次跑里有 11 次调过
`read_section`**，一共读回 **25 节**；`off` 臂 7 次跑 **0 次**（那边压根没有这个
索引可看）。索引行里明写「要看某一节的全文就调 `read_section(n)`」那条缓解
**是有效的**。
另一半缓解（**当前小节永远逐字给**）由一条闸钉着，突变⑦撤掉它 5 条测试变红。

**风险二：不要为了缓存牺牲那条实拍规矩（模型永远接着它最后看到的东西写）。**
—— **守住了，而且是真跑核对的。** 每一轮续写的 user prompt 尾巴和模型写出来的
头 200 字都截了下来。**没有一次从索引接着写**：输出全部以
`【放到：<某个真实小节标题>】` 开头，然后是正文——那是 `place_directive_block`
要求的格式，也正是 prompt 的最后一块。索引排在逐字正文**前面**，
一条闸（突变⑧，2 红）钉着不许把它挪到末尾。

#### 真跑前后对照（`terrence` 真库，`rails_off=("save",)`，**一篇笔记都没写**）

种子是**两篇 `origin=user` 真实长笔记的副本文本**（走 `corpus_lineage.load_notes()`
的血缘判据取）：`92d07b760f1e`（4889 字 / 17 节）和 `309f19202309` 截到 8109 字。
**必须够长**——`context_keep_last` 是 4000 字，短种子根本走不到索引那条路。
每次跑 4 轮预算。三组：`off` = 两个开关都关（14 次）、`on(v1)` = 第一版（14 次）、
`on(v2)` = 修掉下面那个缺陷之后（10 次）。

| | off | on(v1) | **on(v2)** |
|---|---:|---:|---:|
| 跑 / 轮 | 14 / 52 | 14 / 60 | 10 / 40 |
| **正文里的事实 id 引用 / 千字** | 0.55 | 0.43 | **1.05** |
| 同上，只看 `92d07b76` 那个种子 | 1.28 | 0.99 | **2.25** |
| 占位句 / 跑 | 1.07 | 0.50 | **0.80** |
| `material_use` | 1.60 | 1.11 | 1.20（**仍低 0.40，p = 0.376**） |
| `non_repetition` | 0.42 | 0.50 | **0.77**（+0.35，p = 0.210） |
| `beat_coverage` | 1.60 | 1.89 | 1.60 |
| `coherence` | 0.31 | 0.28 | 0.20 |
| `spine_fidelity` | 1.07 | 1.22 | 1.00 |
| `repeat_calls` / 轮 | 0.23 | 0.15 | 0.30 |
| `tool_calls` / 轮 | 4.12 | 4.37 | **5.08**（+23%，这是代价） |
| 秒 / 跑 | 93 | 98 | 98 |

**`on(v1)` 那一版有一个真缺陷，是真跑量出来的，不是想出来的：**
事实索引块里写着「要看全文调 `fact_sources`」——**而续写那一步根本没有工具**
（`hooks/note.produce` 走 `llm.stream`，工具循环在上一步的检索规划里）。
`material_use` 从 1.60 掉到 1.11，而且 `on` 臂**内部有剂量关系**：
事实索引没生效的 5 轮均 **1.60**（跟 `off` 一模一样）、生效的 13 轮均 **0.92**。
**一条当场做不到的指令比不给指令更糟**：模型要么忽略它，要么把一行摘要当原文用。
改成一句它当场能照办的（「这几行只是提醒，别凭这一行去写具体日期人名数字」）
之后重跑，引用密度从 0.43 直接翻到 **1.05**（比 `off` 的 0.55 高 91%）。

**也不能把这一块搬去检索规划的 prompt**（那里能调 `fact_sources`）：那就是
**库存形式**，而 [LED] §10⑤ 有实测证据说明库存会缩小搜索空间，
批 13 的缺口摘要正是为了避开它。两条闸各钉一个方向（突变 ⑳ / ⑳b）。

**老实说退步的那一格**：`material_use` 仍比 `off` 低 **0.40**（p = 0.376，
n = 15 / 10，置换检验 2 万次）。分种子看，退步集中在长种子那一篇
（1.33 → 0.86），短种子那篇已经回到 2.00。**n 太小，不下结论，只记账**；
真要撤，`MEMOKET_FACT_INDEX=0` 一个开关就退回去，不牵连小节索引。

#### 缓存命中前后：**基本持平，而且根因查清楚了**

| 臂 | 步骤 | 调用 | prompt token | 命中缓存 | 命中率 |
|---|---|---:|---:|---:|---:|
| off | `:tools`（检索规划） | 66 | 666,224 | 410,888 | **61.7%** |
| off | 续写（无步骤后缀） | 62 | 536,146 | 163,552 | 30.5% |
| off | `:judge` | 6 | 40,692 | 0 | **0.0%** |
| off | 合计 | 134 | 1,243,062 | 574,440 | **46.2%** |
| on | `:tools` | 149 | 1,438,304 | 867,066 | 60.3% |
| on | 续写 | 137 | 1,212,610 | 372,626 | 30.7% |
| on | `:judge` | 18 | 130,291 | 0 | **0.0%** |
| on | 合计 | 304 | 2,781,205 | 1,239,692 | **44.6%** |

**没上去。** 这是个诚实的负结果，而且 3.3 本来就解释得通：
`prompt_cache_key` **只改路由、不改命不命中**（它让同一个 key 的请求尽量落到
同一台机器上，前缀匹不匹配是另一回事）。真正卡住的是下面这条。

### 计划外发现

1. **judge 那一路的缓存命中率恒为 0，根因在 `score_context.with_material`。**
   打分 prompt 的拼法是 `system → context → dimensions → content → dup_hints`，
   而**材料块是 `context` 的一项**，排在 `[Content]` **之前**，并且**每一轮都在长**
   （这次跑实测 `facts_new` 每轮 41~46 条）。于是断点落在正文之前，
   **正文那几千 token 从来没被缓存过一次**——**跟批 2 修掉的 `dup_hints` 是一模一样
   的形状**，只是这一处没人再看一眼。`with_material` 的注释里写着这是有意的取舍
   （「判词要的是正文对不对得上材料，两块离得越近越好……这里选了准确率」），
   但**把材料挪到 `[Content]` 之后同样是紧挨着**，相邻性一点没丢。
   这一批**没动它**（那是另一次 prompt 排布改动，得自己配一次真跑），
   记成下一步第 1 条。[CE] §6 那个「judge 命中率 > 0.7」的目标现在有了明确路径。
2. **`Compact` 在「每节只有一两行」的笔记上等于没跑过。** 它的 `_gist` 是
   「首行 … 末行」，一节只有两行时梗概跟原文一样长，它结尾那条「压缩不许把东西
   压大」的护栏就把整段原样退回来了。真库上 6 篇超 4000 字的笔记里有 1 篇
   （`e4ddd599b56a`，26714 字、**整篇只有 1 节**）压不动。
   **也就是说「续写 prompt 太长」这件事，在一部分真实笔记上一直是满额的。**
3. **索引也会把东西撑大，撞出来一条护栏。** `92d07b760f1e`（4889 字、17 节）
   在 `keep_last=4000` 之下逐字尾巴几乎是整篇，再加 17 行目录 = **5514 字，
   比直接给全文还多 600 字**，而且原文一个字都没省下来。补了一条
   「拼出来比原文长就给原文」（突变⑨钉着）。**代价要说出来**：这条护栏一开，
   3.1 在 4000~6000 字这一档笔记上**不生效**——这次两个种子里有一个正好落在
   这一档，所以表里的 3.1 效果实际只来自另一个种子。
4. **4 轮预算下 3.2 很少真正触发。** 一次跑累积的事实是 27~57 条，
   而 `fact_budget = 40`——**索引行数 0~17**，多数跑里是 0。
   [MR] §1 说的「攒满 40 条之后每加一条就整体平移」要 8 轮那一档才常态发生。
   这次能量到 `material_use` 的剂量关系，纯粹是因为那 13 轮索引确实非空。
5. **闸被自己的注释骗过去了。** 「会跑 harness 的脚本必须夹在 `Watch` 里」
   第一版判据是 `"db_guard.Watch(" not in text`。突变③把 `soak.py` 的
   `with db_guard.Watch(): main()` 撤成裸 `main()`，**这条闸照样是绿的**
   ——因为上面那段接线注释里写着「跑批一律夹在 `db_guard.Watch()` 里」，
   子串还在。改成匹配行首的 `^\s*with db_guard\.Watch\(` 才变红。
   *判据去读源码的时候，注释也是源码。*
6. **`test_layering` 当场拦下了一次分层违规。** 第一版把两个 scratch 键名定义在
   `middleware/sections.py`、由工具 import 过去——而那条闸钉着「工具不许认识运行时」。
   改成键名定义在工具侧、middleware 反过来取（`runtime.py` 本来就在 import tools，
   方向是既有的）。*一条 2 年前写的边界闸，今天抓到了新代码。*

### 突变验（29 个，29 个变红）

**基线 1489 绿。** 每条改动单独撤掉，对应的闸必须变红（植入前后都
`rm -rf __pycache__`）。

| # | 把什么改坏 | 结果 |
|---|---|---|
| ① | 指纹不看逐篇正文摘要（退回批 14 的三样） | ✅ 1 红 |
| ② | `restores` 退化成 `allow`（写了不核对还原） | ✅ 1 红 |
| ③ | 一个跑批脚本不接 `Watch` | ✅ 1 红（**第一版没抓住，见计划外发现 5**） |
| ④ | 脚本自己拼只读连接 | ✅ 1 红 |
| ⑤ | 豁免的 `dump_prompts` 开始发调用 | ✅ 2 红 |
| ⑥ | 索引里不写「要看全文调 `read_section`」 | ✅ 1 红 |
| ⑦ | **当前小节不逐字给**（全靠模型自己去查） | ✅ 5 红 |
| ⑧ | **索引摆到最后**（逐字正文不再垫底） | ✅ 2 红 |
| ⑨ | 拼出来比原文长也照发 | ✅ 1 红 |
| ⑩ | 分节丢掉第一个标题前面的引子 | ✅ 2 红 |
| ⑪ | `before_round` 不发布分节（工具循环那一轮拿不到） | ✅ 5 红 |
| ⑫ | `SECTION_INDEX` 关不掉 | ✅ 2 红 |
| ⑬ | `read_section` 不记节号（这次读白读） | ✅ 2 红 |
| ⑭ | `read_section` 算进 `FACT_TOOLS`（自己的正文喂饱停机判据） | ✅ 1 红 |
| ⑮ | `read_section` 挂 `memory` 组（六个 block 模式也看得见） | ✅ 2 红 |
| ⑯ | `read_section` 进短路白名单（第 3 轮读到第 1 轮那一节） | ✅ 2 红 |
| ⑰ | 事实还是从头丢（退回 `[-40:]`） | ✅ 3 红 |
| ⑱ | 索引不取账本那一行，自己另截一份 | ✅ 1 红 |
| ⑲ | 账本里没有的那几条直接漏掉 | ✅ 1 红 |
| ⑳ | 事实索引块退回那条「调 `fact_sources`」的做不到的指令 | ✅ 1 红 |
| ⑳b | 事实索引搬进检索规划的 prompt（库存形式） | ✅ 2 红 |
| ㉑ | 事实索引排到逐字事实后面 | ✅ 1 红 |
| ㉒ | `FACT_INDEX` 关不掉 | ✅ 2 红 |
| ㉓ | 修复轮也去动材料 | ✅ 2 红 |
| ㉔ | 缓存键不带步骤 | ✅ 2 红 |
| ㉕ | 没设过也硬塞一个键 | ✅ 1 红 |
| ㉖ | 剥参数的判据放宽到「消息里提到这个词」 | ✅ 1 红 |
| ㉗ | 四条调用路径里有一条自己剥 `temperature`（不走公共函数） | ✅ 1 红 |
| ㉘ | 文档里的工具数没跟着改 | ✅ 1 红 |

### 闸

后端 **1448 → 1489**（+41：`test_section_index` 新建 34 条、`test_db_guard` +6、
`test_harness_parity` / `test_harness_modes` 把 `compact` 换成 `sections`）。
前端 51 文件全绿。
`harness-framework.md` 按这一批改了：工具 **21 → 22**（`read_section`），
middleware 列表加 `sections`，`tools/` 那张图加 `longform` 组。

### 开工前后的 `notes` 指纹（自己核对过，不是自报）

|  | 开工前 | 收尾 |
|---|---|---|
| `notes` 行数 | 482 | **482** |
| `note_revisions` 行数 | 40 | **40** |
| `notes` `max(updated_at)` | `2026-09-16T02:53:27+00:00` | **同上，一秒没动** |
| 正文总字数 | 321,250 | **321,250** |
| 482 篇逐篇摘要再取一次摘要 | — | `47dcc54be60aa4f2` |

38 次真跑全程夹在 `db_guard.Watch()` 里，没有一次抛过。

### 这一批的实际成本

`gpt-5.6-luna`，38 次真跑（14 + 14 + 10）+ 若干探针：
**调用 634 次、prompt 5,767,527 token（其中命中缓存 2,545,004 = 44.1%）、
completion 341,263 token**，模型墙上时间约 **59 分钟**。

### 这一批**没做**什么

* **没动 `score_context.with_material`。** 那是 judge 命中率归零的根因（计划外发现 1），
  但它是另一次 prompt 排布改动，得自己配一次真跑，不该混进这一批的 A/B。
* **没给 magic tap 那条路换索引。** 它没有工具循环，给指针取不回来。
* **没把 `material_use` 那 0.40 跑到结论。** n = 15 / 10、p = 0.376。
* **没跑 `dimension_sensitivity_bench`。** 这一批改的是**上下文怎么给**，
  不是哪一维怎么判；灵敏度台量的是「植入缺陷这一维掉不掉分」，
  跟这次的改动不在同一条线上。真要量得先想清楚植入器要植什么。

### 下一步

1. **把打分 prompt 的材料块挪到 `[Content]` 之后**（计划外发现 1）。
   这是 [CE] 全文剩下最大的一处缓存缺口：judge 现在 **0.0%**，
   而 [CE] §6 的目标是 **> 0.7**。相邻性不丢（挪到正文后面同样紧挨着），
   形状跟批 2 已经验过的 `dup_hints` 一模一样。**要配一次真跑核对分数没变。**
2. **`material_use` 那 0.40 补到能下结论的 n。** 现在 p = 0.376。
   补法是同种子多跑，别换语料。
3. **3.1 在 4000~6000 字这一档笔记上不生效**（计划外发现 3）。
   要么把 `context_keep_last` 按篇幅调，要么让索引在这一档更省
   （只列没逐字给出来的那几节）。**先量一次再改。**
4. **3.2 要 8 轮那一档才常态触发**（计划外发现 4）。现在的证据只覆盖到
   「索引 0~17 行」这一段。
5. **`e4ddd599b56a` 那类整篇 1 节的笔记，两条路都压不动**（计划外发现 2）。
   分节靠 `##`，而真实笔记有的一个标题都没有。要不要按段落分节，先量。

## 批 16 · judge 的缓存缺口 + 阶段 5「有 oracle 的那三个模式」（2026-09-18）

两件事：**A** 是批 15 计划外发现①（judge 命中率恒 0，材料块排在正文前面），
**B** 是阶段 5 的三条（`P0`，[IND] 自己排在第 1 位）。
外加**一件不是计划里的**：这一批自己又把两篇真实笔记写坏了（见最后一节，
根因查到了，跟批 14 猜的不是一回事）。

### A. judge 的缓存命中率：改了，**没上去，而且根因不是排布**

#### 先做了计划里那一步

`score_context.with_material` 交出来的那一份现在过一道
`split_for_prompt()`，材料块由 `rubric.evaluate(tail_context=…)` 渲染在
`[Content]` **之后**。生产（`loop._evaluate`）和灵敏度 bench（`run_one`）
共用这一个拆分函数，各自 pop 一份会让 `as-deployed` 那一列失真。

**相邻性那句话核实的结论：不但没丢，是原来就没有。**
批 15 写着「挪到正文后面同样是紧挨着，相邻性一点没丢」，而
`with_material` 的原注释说材料排在 context 末尾「也就是紧挨着 `[Content]`」
——**这句是错的，错了八批没人再看一眼**。`_build_prompt` 的顺序是
`context → [Dimensions to score] → [Content]`，中间隔着**整块维度判词**
（八组里最长的 EDA 那组 1000+ 字）。挪到 `[Content]` 之后，材料才第一次
真的跟正文相邻——「准确率 vs 省钱」那个取舍在这里**根本不存在**。

#### 命中率前后（真数字，按调用类型分）

隔离探针（一篇真实用户长笔记 `309f19202309`，模拟长文跑的 judge 序列：
正文逐轮追加、材料每轮 +6 条，两臂只差排布）：

| 臂 | judge 调用 | prompt token | 命中缓存 | 命中率 |
|---|---:|---:|---:|---:|
| before（材料在正文前） | 7 | 36,261 | 0 | **0.0%** |
| after（材料在正文后） | 7 | 36,266 | 0 | **0.0%** |
| before（第二轮探针，n=18） | 18 | 90,317 | 0 | **0.0%** |
| after（第二轮探针，n=18） | 18 | 90,333 | 0 | **0.0%** |

真跑那一侧（`terrence` 真库、note 模式、每臂 6 次跑 × 3 轮）：

| 臂 | 步骤 | 调用 | prompt | 命中 | 命中率 |
|---|---|---:|---:|---:|---:|
| before | `:tools` | 31 | 275,887 | 158,109 | 57.3% |
| before | 续写 | 34 | 259,963 | 73,636 | 28.3% |
| before | `:judge` | 5 | 40,322 | 8,343 | **20.7%** |
| after | `:tools` | 40 | 345,379 | 210,477 | 60.9% |
| after | 续写 | 44 | 322,715 | 113,901 | 35.3% |
| after | `:judge` | 9 | 62,563 | 0 | **0.0%** |

**`before` 那 20.7% 不是排布带来的**：逐条看，是**同一条 judge prompt 被原样
发了两遍**（那一次跑停在 `no_progress`，一轮什么都没变，于是第 2 次判的是
逐字相同的东西）。除掉那一格，两臂都是 0。

#### 根因：**这个端点的前缀缓存是按 message 为单位的**

`[CE] §2②` 那套「断点落在第几个 token」的模型**在这个端点上不成立**。
受控实验（5 组、每组 3–5 次调用，直接打 `/chat/completions` 读 `usage`）：

| 发什么 | prompt | cached |
|---|---:|---:|
| 一条 user message，第 1 轮 | 6,019 | 0 |
| 同一条 message 追加一段（**第 1 轮是它逐字的 token 前缀**） | 6,023 | **0** |
| 追加式：第 1 轮 | 6,020 | 0 |
| 追加式：第 2 轮（**第 1 轮是它的 message 前缀**） | 6,040 | **6,017（99.6%）** |
| 追加式：第 3 轮 | 6,060 | **6,037（99.6%）** |

另外两组交叉验证了同一条规则：`[sys, 大段, 尾巴甲]` 之后发
`[sys, 大段, 尾巴乙]`——**7,725 token 的共享前缀，命中 0**；
而先单独发过 `[sys, 大段]` 再发 `[sys, 大段, 任意尾巴]`，命中整段。

> **规则：命中的前提是「之前发过的某一条完整请求，它的整个 message 列表是
> 这一条的前缀」。同一条 message 内部再长的共享前缀，一个 token 都不算。**

于是三条都解释通了，而且是**同一个**解释：
* `:tools` 60% —— 工具循环天然是「把这一轮新增的做成新 message 追加上去」；
* 续写 30% —— 同理（前面的消息不动，尾巴换）；
* `:judge` **0%** —— 它只有**一条** user message，整段每轮重拼。
  **材料排在哪儿都改不了这件事。**

**这也意味着批 2 那次 `dup_hints` 的搬家，在这个端点上买到的缓存是 0。**
那次的判据（「小块别卡在大块前面」）本身没错，只是它的收益要等到
端点做 token 级前缀缓存才兑现。

#### 分数有没有变（这才是这一改的验收）

同一段输入、两臂只差排布，18 对配对格子 × 6 维（`309f19202309` 三段正文
× 6 轮）：

| 维度 | before | after | Δ |
|---|---:|---:|---:|
| spine_fidelity | 0.00 | 0.00 | +0.00 |
| beat_coverage | 0.06 | 0.06 | +0.00 |
| non_repetition | 1.44 | 1.50 | +0.06 |
| factual_grounding | 0.00 | 0.00 | +0.00 |
| coherence | 0.00 | 0.11 | +0.11 |
| material_use | 0.00 | 0.00 | +0.00 |
| **总均** | **0.250** | **0.278** | **+0.028** |

配对置换检验 2 万次，**p = 0.475**。真跑那一侧也一样：轮数 2.83 → 3.00、
秒/跑 81.4 → 82.5、12 次跑 0 次报错。**分数没变，这一改留着**——
它把材料真的搬到了正文边上（原来中间隔着整块判词），代价是零。

### B. 阶段 5：有 oracle 的那三个模式（5.1 / 5.2 / 5.3）

[IND] §2–3：图表 / 表格 / 分析三个模式**本来有执行 oracle**，
「每个数字都能追到源表」**是一次精确比对，不是一次判断**。

| # | 落在哪 | 做了什么 |
|---|---|---|
| 5.1 | `checks/numbers.chart_numbers_grounded` | mermaid 的 `bar [...]` / pie 的 `"标签" : 值`、markdown 表里**整格就是一个数**的格子 → 跟「整篇笔记 + 用户指令 + 选区 + 这次跑累积的全部工具返回 + 工具画过的每张图」逐个 diff |
| 5.1 | `checks/structure.table_columns_match` | `table_validity` 的达标线原话「header and rows have matching column counts」。实现从 `dimension_sensitivity_bench` **搬进** `blockcheck`，bench 反过来 import 它 |
| 5.2 | `checks/numbers.numbers_from_tools` | 正文里的**统计量**（eda / analysis） |
| 5.3 | `checks/charts.chart_readable` | VisEval 的 readability 档：y 轴有没有名字、多系列图的图例数不数得上、类目多不多到读不出、x 轴标签有没有被 `safe_label` 截断、流程图节点数 |

接线：`eda` / `analysis` 挂三条，`chart` 挂两条，`table` 挂两条；
**其余四个模式一条都不挂**（没有数据工具 = 没有 oracle），两条闸各钉一个方向。

#### 判据窄在哪 —— 四道，逐条对着一种会误伤的写法

铁律原话：*误伤比漏报贵；正文里「第 3 节」「2026 年」这类数字不是数据，
误判成「编造」会逼模型去删真内容。*

1. **位置即判据（图 / 表）。** 只取**数值位**。图标题、y 轴名、x 轴标签、
   表头行、分隔行一个不取。**整格混着文字的格子不算数据格**
   （「约 40 台」「2026-09-18」「第 3 版」）。
2. **形状即判据（正文）。** 先挖掉 `tabular._NOT_A_QUANTITY`（引用 id /
   链接 / 日期 / 第 N / 型号——那份名单是实拍出来的：数据可视化把
   「第 5、10、15 位用户」画成过柱子），再挖掉**五条正文专属**的
   （`2026 年` / `## 2.1` 章节编号 / 有序列表编号 / `0.5.10` 版本号 /
   `3:2` 比例），最后只留「带 % 或带小数点或 ≥100」的。
   **小整数一律不算**——「三个渠道」「补 2 条」「跑了 8 轮」遍地都是。
3. **哪些数字不算数据，实测又补了三条**（在 24 篇真实用户笔记上真的撞到）：
   * `2026上半年实现等效 138 人` —— 四位年份后面**不跟「年」**，
     原来那条正则从它底下穿过去了 → 光秃秃的 1900–2100 整数一律当年份；
   * `跨柜带宽摔到 100-200GB`、`单基站覆盖 500-600 米` ——
     **区间被读成了 −200 / −600**（负号前面是数字就不算负号）；
   * `可实现 40m 的距离`、`最多开到 20kmh`、`100kW`、`12MW`
     —— 中文笔记里 `k/m/M/w` 绝大多数是**单位**不是倍数，「40m」被读成
     **四千万**。正文这一侧只认中文数量词（万 / 亿 / 千 / 百）；
     源头那一侧（`tabular.numbers_in_text`）照旧两种都收，
     **所以少认一种只会漏、不会误伤**。
4. **没有工具输出就不判。** 手上没有 oracle 时「查无出处」和「无从判断」
   分不开，那一档该由 `charts_from_tools` / `table_present` 去说「你还没调工具」。
   另外容差 0.5%，百分数**两个方向**都算对上（源表 0.38 ↔ 图里 38）。

#### 在真实产出上验零误伤

`origin=user`（走 `corpus_lineage`，**"真实产出"≠"用户写的"**）24 篇，
每篇同时当产出和源头——笔记里的每个数按定义都追得到这篇笔记，所以**一次都不该开火**：

| | 数 |
|---|---:|
| 篇数 | 24 |
| 图 / 表数值位候选 | 32 |
| 正文统计量候选 | **474**（窄化前 548，多出来的 74 全是上面那三类抽错的） |
| **开火** | **0** |

反向那一半也钉了：在同一批真实笔记上把一个字面数字改掉（偏移必须大过
0.5% 容差），**4 篇能植入的全部抓住**。4 是这份语料的上限——24 篇里 8 篇
是空的、7 篇不足千字。

#### 验收为什么不靠 bench

批 11/13 的硬约束：图表那一组**只有 1 篇真实用户语料带图、1 篇带表，
而那篇的表每个格子都是占位符、那张 mermaid 本身就是坏的**。
所以这一批的验收是 `tests/test_number_grounding.py` 的 **43 条**单测 +
构造用例，bench 只用来量误伤，**n=1 一律不下跨篇结论**。

### 突变验（23 条，23 条变红）

**基线 1539 绿。** 每条改动单独撤掉（植入前后都 `rm -rf __pycache__`）。

| # | 把什么改坏 | 结果 |
|---|---|---|
| ① | 材料排回 `[Content]` 之前（`split_for_prompt` 不拆） | ✅ 5 红 |
| ② | `_build_prompt` 忽略 `tail_context` | ✅ 1 红 |
| ③ | `loop` 把材料塞回 `context` | ✅ 4 红 |
| ④ | bench 不走那道拆分（`as-deployed` 跟生产不一样了） | ✅ 1 红 |
| ⑤ | 列数判据恒 False | ✅ 4 红 |
| ⑥ | bench 自己再留一份列数判据 | ✅ 1 红 |
| ⑦ | `chart_numbers_grounded` 恒 None | ✅ 4 红 |
| ⑧ | `numbers_from_tools` 恒 None | ✅ 3 红 |
| ⑨ | `chart_readable` 恒 None | ✅ 5 红 |
| ⑩ | 没有工具输出也照判 | ✅ 4 红 |
| ⑪ | 取消年份过滤 | ✅ 2 红 |
| ⑫ | 取消正文那五条结构性数字过滤 | ✅ 2 红 |
| ⑬ | 小整数也算统计量 | ✅ 1 红 |
| ⑭ | 图的标题 / x 轴标签也参与比对 | ✅ 1 红（**第一版没抓住**，见下） |
| ⑮ | 表头行也当数据行 | ✅ 1 红（**第一版没抓住**，见下） |
| ⑯ | 比对只试 `v` 本身（不试百分数两个方向） | ✅ 1 红 |
| ⑰ | `modes` 撤掉 table 那两条接线 | ✅ 2 红 |
| ⑱ | 正文也认 `k/m` 倍数后缀 | ✅ 3 红 |
| ⑲ | 负号允许跟在数字后面（区间读成负数） | ✅ 2 红 |
| ⑳ | readability 不看被截断的标签 | ✅ 1 红 |
| ㉑ | 笔记原来就有的图也算这一轮画的 | ✅ 1 红 |
| ㉒ | `Revise` 又自己写一次库 | ✅ 2 红 |
| ㉓ | `persist` 不认 `rails_off` | ✅ 1 红 |

**⑭ 和 ⑮ 第一版都没抓住，而且是同一个病**：两条测试用的数字**恰好落在别的
判据的保护伞下**——⑭ 的 x 轴标签写的是年份（另有年份过滤兜着），
⑮ 的表头数字写的是 `12700`（那个数真在工具返回里）。
改成「非年份、源头里也没有」的数字之后当场变红。
*突变没被抓住时，先怀疑用例不够。连着九批了。*

### 计划外发现

1. **这个端点的前缀缓存是按 message 为单位的**（上面 A 那一节，受控实验）。
   这条**改写了 [CE] §2② 的适用范围**：在这个端点上，「把每轮变的小块挪到
   大块后面」买不到任何缓存——买得到的是「**把这一轮新增的东西做成一条新
   message 追加上去**」。批 2 的 `dup_hints` 搬家、批 16 的材料搬家，
   两次都对，两次的缓存收益都是 0。
2. **`Revise` 也在写用户的笔记，而 `rails_off=("save",)` 只摘掉了 `Save`。**
   见下一节——这是批 14 那场事故的**真**根因，批 14 只猜到了一半。
3. **judge 在真跑里很少连着被调两次。** 12 次跑 3 轮共 14 次 judge 调用
   （确定性判据先命中就 `skip_judge`，不花这次钱）。所以即使将来把 judge
   改成追加式，能吃到缓存的轮次也有限——**先量一次「一次跑里 judge 被调
   几次」再决定值不值**。
4. **`numbers_in_text` 那份倍数后缀名单在中文笔记上是有害的**（`40m` →
   四千万）。这一批只在新判据这一侧绕开了它；`tabular.has_quantity` 那条路
   （EDA 挑"哪几句话有可画的数"）**还在用原来那份**，没动——改它会顺带改
   取材行为，是另一件事。记在这儿。

### 这一批自己又把两篇真实笔记写坏了（已恢复）

**第三次了。** 时间线：

| | |
|---|---|
| 04:23–04:33 | A 的真跑 A/B（12 次跑）。**拿真实 note_id 装 `ToolContext`**，靠 `rails_off=("save",)` 挡写 |
| 收尾 | `db_guard.Watch()` **如实抛了 `NotesTouched`**，四样差异一条不落 |
| 但是 | 跑批命令写成 `python run.py \| tail -20`——**管道的退出码是 `tail` 的，恒为 0**。"跑完了、退出码 0"，报警被吞掉 |
| 04:47 | 按惯例核对指纹时才发现：`309f19202309` 30588 字 → **4085 字**，`06647b9c2031` 2762 → 2937，标题双双被改成「批16对照」 |
| 04:50 | 从 `data/backups/notes-20260917.sqlite3` 恢复，恢复前把被写坏的那份存成 `reason='before_restore'` 的版本 |

**闸是好的，是我把它的声音掐了。** 这一条没法写成仓里的测试
（它关于怎么调脚本，不关于代码），所以写进 `restore_damaged_notes.py` 的
模块文档：**别让闸的输出经过任何会改写退出码的管道。**

#### 真根因（批 14 只猜到了一半）

批 14 的复盘写着「`rails_off=("save",)` 本身是好的」，然后去猜是不是有人
直接打了 HTTP 路由。**不是。**

> `middleware/revise.py` **自己也在调 `store.update_note`**
> （修订应用成功、或清掉元话语之后落一次，免得跑到一半断了修订白做），
> 而 `rails_off` 只按 `name` 摘掉了 `Save` 这一个 middleware。

批 15 没出事纯属侥幸：它的种子用的不是真实 note_id，
`UPDATE … WHERE id=?` 一行都没匹配上。

#### 修法：写库收成一个出口，出口自己认 rails

`middleware/save.persist(st)` 是 harness 里**唯一**写用户笔记的地方，
`Revise` 反过来调它；`persist` 第一件事就是查 `"save" in st.mode.rails_off`。
**两件事缺一不可**——只收出口不认 rails，下一个「摘掉写库」的开关照样漏；
只认 rails 不收出口，两处各写一份，下次又只盖住其中一处。

两条闸（`tests/test_db_guard.py`）：
* `test_harness里只有一处在写用户的笔记` —— 扫源码，`store.update_note(`
  在 `app/harness/` 下只许出现一次。**盯的是"出口只有一个"这个性质**，
  再加一个会写库的 middleware 当场红。
* `test_rails_off挡住save时一个字都不许落库` —— 行为闸。词法那条挡不住
  「收成一个函数但函数不认 rails」这一档，而那正是事故的形状。

#### 修完之后的**端到端**证明（不是自报）

用同一个跑批脚本、同样拿**真实 note_id**、`rails_off=("save",)`，
再跑 2 次 × 3 轮（`309f19202309` / `06647b9c2031`），**不经过任何管道**：
`Watch` 没抛，退出码 0，收尾指纹逐字回到基线（见下表）。

### 闸

后端 **1489 → 1539**（+50：`test_number_grounding` 新建 43 条、
`test_db_guard` +2、`test_score_context` +3、`test_dimension_sensitivity_bench` +1、
`test_harness_modes` 的缺陷素材扩了一份）。前端全绿。
`harness-framework.md` 按这一批改了：check **15 → 19**、
目录图加 `checks/numbers.py`、第 8 节补四行、第 3 节那张图 `checks/ ×10 → ×11`。

### 开工前后的 `notes` 指纹（自己核对过，不是自报）

|  | 开工前（= 批 15 收尾） | 事故时 | 恢复 + 收尾 |
|---|---|---|---|
| `notes` 行数 | 482 | 482 | **482** |
| `notes` `max(updated_at)` | `2026-09-16T02:53:27+00:00` | `2026-09-18T04:39:06+00:00` | **`2026-09-16T02:53:27+00:00`** |
| 正文总字数 | 321,250 | 294,922（**−26,328**） | **321,250** |
| 482 篇逐篇摘要再取一次摘要 | `47dcc54be60aa4f2` | 变了两篇 | **`47dcc54be60aa4f2`** |
| `note_revisions` 行数 | 40 | 42 | **44** |

**`note_revisions` 40 → 44 是有意留下的**：+2 是事故当时 harness 存的
`auto` 版本（里面正是原文），+2 是恢复前存的 `before_restore`。
**审计痕迹不删**——删掉它才是把事故藏起来。

### 这一批的实际成本

`gpt-5.6-luna`：记账内 **213 次调用、prompt 1,560,006 token
（命中缓存 564,466 = 36.2%）、completion 106,761 token**，
模型墙上时间约 **24 分钟**；另有约 20 次直接打端点的缓存探针（不走记账，
约 12 万 prompt token）。

### 下一步

1. **judge 要吃到缓存，得把那一步改成「追加式」**（计划外发现 1）：
   第 N+1 轮的 message 列表以第 N 轮的整份为前缀。实验数据摆着
   （0% → 99.6%），但它**改的是打分器读到的东西**（从一份干净 prompt 变成
   一串累积消息），得自己配一次 A/B——**先按发现 3 量一次「一次跑里 judge
   被调几次」**，调不到两次的话这件事根本不值得做。
2. **`[CE] §2②` 那套 token 级前缀模型要标上适用范围。** 批 2 和批 16 两次
   搬家都是照它做的，两次的缓存收益都是 0。
3. **`tabular` 的倍数后缀名单在中文笔记上有害**（`40m` → 四千万，发现 4）。
   `has_quantity` 那条路还在用它，会影响 EDA 挑句子。**先量一次影响面。**
4. **阶段 5 的三条只在单测和 24 篇真实笔记上验过。** 语料一到（带真图真表的
   产出），第一件事是重量误伤率——**建了判据不等于用了判据，判据没误伤过
   也不等于它不会误伤**。
5. 计划里剩下的下一个 `P0` 是**阶段 6**（指令类：从用户那条指令现场生成
   checklist，[IND] §4 的 TICK / RaR）。

## 批 17 · 阶段 6「指令类两个模式：从用户那条指令现场生成 checklist」（2026-09-18）

`P0`，[IND] §4（TICK / RaR / IFEval）。一句话：`prompt` / `custom` 两个模式
**不再只用那三条对所有指令都一样的维度**——跑之前先把用户刚打的那句话拆成
这一次专属的判据，能用代码判准的走代码，判不准的花一次调用生成二元 checklist。

依据是 `Rubrics as Rewards`（ICLR 2026）的消融：**对所有 prompt 用同一份通用
rubric（RaR-Predefined）明显更差**，而我们八个功能**全部**是那一档。
接线早就通了（批 8 把指令递给了打分器，批 9 实测 `follows_prompt` 掉 1.11、
p=0.0005），缺的一直是「这一条指令到底要求了什么」。

### A. 6.2 能用代码判准的那一半（IFEval 那条线）

`checks/instructions.py`：从指令里抽**七类**约束，逐条对着产出验。

| 类型 | 认哪些写法 | 怎么验 |
|---|---|---|
| `max_chars` | 「不超过 200 字」「200 字以内」「最多写 200 字」 | 字数 ≤ N×1.1 |
| `min_chars` | 「至少 300 字」「不少于 300 字」「300 字以上」 | 字数 ≥ N×0.9 |
| `min_bullets` | 「分三点」「列 5 条」「总结成 3 条」（**必须带动词**） | 列表项数或段数 ≥ N |
| `min_paragraphs` | 「写三段」「分为 3 段」 | 同上 |
| `table` | 「用表格」「整理成表格」「表格形式」 | `blockcheck.has_table`（表头 + 分隔行） |
| `must_mention` | 「必须提到「X」」——**只认带引号的** | 忽略空白的逐字包含 |
| `must_not_mention` | 「不要提到「Y」」 | 同上，取反 |

判据窄在哪（铁律第 3 条：误伤比漏报贵）——**每一条都对着一种会误伤的写法**：

1. **否定式先摘掉。** 「不要用表格」里也有「用表格」三个字。不挡住就会把
   「别用表格」抽成「必须用表格」，产出怎么写都不合格。
2. **「每段不超过 100 字」不是「整块不超过 100 字」。** ——**这条是在自己的
   冒烟用例上当场撞到的**：「写三段，每段不超过 100 字」第一版抽成了整块
   100 字，三段写下来必然超标，**完全照做的产出被判不合格**。按段算得先切段
   再摊约束，切得准不准本身又是一次判断——抽不准就不抽。
3. **「必须提到 X」只认带引号的。** 「提到北京和上海的差异」里 X 到底是
   「北京」还是整个短语，猜错就是拿一个用户没说过的词去卡产出。
4. **同一类抽出两个不同的数，整类作废**（「先写 3 段，再分 5 段」）：挑哪个
   都有一半的时候在拿错的数去卡产出。上下限自相矛盾时两条一起作废。
5. **数字要落在合理区间**：`字数 10–5000`、`点/条/段 2–12`。
   「不超过 3 字」不像是在说产出，「第 2024 条」是编号不是要求。
6. **验证一律取宽的那一档**（IFEval 的 loose）：字数 10% 容差；「分三点」认
   三个列表项也认三段；```围栏里的代码不算进字数（工具画的那张 mermaid 是
   判据自己要求必须原样搬进来的，算进去会让「不超过 100 字」在一张图上开火）；
   中文按字算、英文按词算。
7. **判不了就不判**（`verify` 返回 `None`）：正文还没写出来、字数数不出来、
   不认识的约束类型——跟批 16 那条「没有工具输出就不判」是同一条纪律。

抽出来的约束挂成一条 `Check`（`instruction_constraints`），在 `before_judge`
里跑，命中**当场短路掉那次打分调用**（有单测钉着：第 1 轮 `_score` 一次都没被调）。

### B. 6.1 判不准的那一半：现场生成 checklist

`harness/checklist.py` + `middleware/checklist.py`。一次跑**一次**调用
（`before_run`，不是每轮——判据在轮与轮之间漂的话，`BestOf` / `_regressed`
那两条跨轮比较当场失效），生成至多 4 条二元条目，接在原来那三条维度后面。

**二元只用在新条目上**：`Dimension.binary` 两侧一起管——判词里写明
「满足给 2，不满足给 0，不要给 1」，解析那一侧再把漏网的 1 压成 0
（只靠 prompt 说一句是「靠自报保证的性质」）。**`PROMPT_DIMS` / `CUSTOM_DIMS`
那三条一个字都没动**——计划 7.4 写着「先按维度量一致率再决定改哪几维」，
而一致率那一步（阶段 9.2）还没做。

**生成出来的东西可能是错的，所以有三道闸**：
* 每条必须给 `quote`，而且**拿指令原文逐字核对**（忽略空白/大小写）。
  对不上就丢——不是「请模型只写指令里有的」，是核对它交上来的依据。
* **程序已经判了的不许重复**（按依据原文重叠判，不按措辞判）。
* **生成失败 / 全被丢掉 / 模型抛异常 = 一个字都不加**，退回原来那三条维度。

外加总开关 `params.PROMPT_CHECKLIST`（形状照批 13 `LEDGER_IN_PROMPT` /
批 15 `SECTION_INDEX`）：代码这三道闸挡的是能挡的那部分，挡不住「条目本身
跑偏」，那一档只能靠开关。

### 真实样例（8 条典型指令，真跑 8 次调用）

```
指令：把上面这段会议结论写成给客户的一段话，不超过 200 字，必须提到「交付时间」
  代码判：max_chars=200、must_mention=交付时间
  checklist_1：写成给客户的一段话        ← 依据「写成给客户的一段话」

指令：分三点总结一下这次测试暴露的问题，每点一句话
  代码判：min_bullets=3
  checklist_1：总结测试暴露的问题        ← 依据「总结一下这次测试暴露的问题」
  checklist_2：每点使用一句话            ← 依据「每点一句话」

指令：用表格把这几家供应商的报价和交期整理出来
  代码判：table
  checklist_1：整理出各家供应商的报价    ← 依据「报价」
  checklist_2：整理出各家供应商的交期    ← 依据「交期」

指令：接着写一段，说明我们为什么选了方案 B，不要提到「内部代号」
  代码判：must_not_mention=内部代号
  checklist_1：续写一段内容              ← 依据「接着写一段」
  checklist_2：说明选择方案 B 的原因     ← 依据「说明我们为什么选了方案 B」

指令：帮我把这段改得更口语一点
  代码判：（无）
  checklist_1：改写后的表达更口语化      ← 依据「改得更口语一点」

指令：写一段风险提示，要给出触发条件和应对动作
  代码判：（无）
  checklist_1：给出风险触发条件          ← 依据「给出触发条件」
  checklist_2：给出风险应对动作          ← 依据「应对动作」

指令：总结一下上面的讨论
  代码判：（无）
  checklist_1：总结上面的讨论            ← 依据「总结一下上面的讨论」

指令：写三段：现状、问题、下一步，每段不超过 100 字
  代码判：min_paragraphs=3
  checklist_1：包含"现状"段落
  checklist_2：包含"问题"段落
  checklist_3：包含"下一步"段落
  checklist_4：每段不超过100字           ← 依据「每段不超过 100 字」
```

**最后一条正是这一批的分工在真实语料上自己走通的**：`每段不超过 100 字`
是代码**有意不抽**的那一类（见上面窄化第 2 条），而模型把它写成了 checklist
条目——代码放掉的漏，二元条目接住了。

**最后一条的反面也要记**：「总结一下上面的讨论」生成出来的条目
（「总结上面的讨论」）几乎是指令的同义反复。**指令越空泛，条目越接近废话**，
而依据核对那道闸对同义反复完全无效（它逐字抄的就是指令本身）。

### 灵敏度前后对照（`dimension_sensitivity_bench`，真跑 69 格）

`--only paragraph/answer_swap --notes 3 --repeats 3`，语料按血缘只留 `user`。
新增的 `condition="checklist"` 那一档跟自己的 `as-deployed` 兄弟行**严格配对**
（同一段正文、同一份上下文、同一份材料，只差维度表后面多两条二元条目），
有一条闸钉着这个配对关系。

| 维度 | probe | 条件 | 干净 | 植入 | 掉分 | 篇 | 次 | p | 结论 |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| `follows_prompt` | prompt/answer_swap | as-deployed | 1.56 | 0.22 | **1.33** | 3 | 18 | 0.0037 | 抓住 |
| `follows_prompt` | prompt/answer_swap | **checklist** | 1.67 | 0.33 | **1.33** | 3 | 18 | 0.005 | 抓住 |
| `follows_prompt` | custom/answer_swap | as-deployed | 1.56 | 0.67 | **0.89** | 3 | 18 | 0.024 | 只动了一点 |
| `follows_prompt` | custom/answer_swap | **checklist** | 1.56 | 0.33 | **1.22** | 3 | 18 | 0.005 | 抓住 |

`custom` 那条 `answer_swap` probe 是这一批新加的（原来 `custom` 只有
`replaces_cleanly` 一条），所以它的 as-deployed 行也是这一批第一次量。

**`follows_prompt` 本身：`prompt` 一分没变（1.33 → 1.33），`custom` 从
0.89 抬到 1.22、跨过了 0.89 那条线。** n=3 篇，这一格单独不足以下结论。

**真正的收益在新条目自己身上**（逐格分布，36 格）：

| 维度 | 干净版 | 植入版 | 掉分 |
|---|---|---|---:|
| `checklist_1`（prompt） | **18/18 全是 2** | 13/18 是 0 | 1.56 |
| `checklist_2`（prompt） | 12/18 是 2、**6/18 是 0** | **18/18 全是 0** | 1.33 |
| `checklist_1`（custom） | 18/18 全是 2 | 12/18 是 0 | 1.33 |
| `checklist_2`（custom） | 同上一行 prompt 的形状 | 18/18 全是 0 | 1.33 |
| 对照：`follows_prompt` | 11/18 是 2、7/18 是 1 | 12/18 是 0、6/18 是 1 | — |

两件事值得单独拎出来：
1. **二元真的是二元**：36 格 × 2 条条目 = 72 个格子里**一个 1 都没有**。
2. **`checklist_2` 在干净正文上有 6/18 = 33% 的误判**。那一条是
   「按原主题展开，不写其他主题」——**bench 的指令是合成的一句通用话**
   （`instruction_for`：「围绕《标题》…按原主题把它写清楚」），从它拆出来的
   条目必然空泛，而空泛的条目二元判起来最不稳。真实指令（上面那 8 条）具体得多。
   **这个 33% 是误判率的上界，不是生产值**；生产值要等阶段 9.1 的采集。

### 成本：多出来的那次调用值不值

真库真跑（`309f19202309`，同一篇同一位置，开关两臂各跑一次，按 `ctx_feature`
分步骤记账）：

| 指令 | 臂 | 轮 | 调用 | prompt token | completion | 墙上 |
|---|---|---:|---:|---:|---:|---:|
| 分三点总结…必须提到「众筹」 | off | 3 | 9 | 18,020 | 2,160 | 41.0s |
| 同上 | **on** | 2 | 6（含 checklist 1） | 12,607 | 1,552 | 28.6s |
| 接着写一段风险提示…不超过 200 字 | off | 1 | 3 | 5,731 | 459 | 11.1s |
| 同上 | **on** | 1 | 4（含 checklist 1） | 6,082 | 508 | 14.5s |

**那一次调用本身：373 / 358 prompt token、91 / 8 completion token、2.5 / 2.0 秒
——占整趟 prompt token 的 3.0% / 5.9%，占墙上时间的 8.7% / 13.8%。**

第二条那 8 个 completion token 是 `{"items": []}`：**唯一的要求（不超过 200 字）
已经被代码判了**，模型很正确地什么都没再加，这一趟退回原来那三条维度——
「程序判了的不许重复」那道闸在真跑里自己走通了。

第一条那一对里 `on` 臂反而**便宜 30%**（少跑了一轮）。**n=1，不作数**：
写作那步 temperature=0.4，轮数本来就抖。记在这儿只是为了说明「多一次调用」
不等于「整趟贵一次调用」。

### 突变验（29 条，29 条变红）

**基线 1594 绿**（1539 → +55）。每条单独撤掉 / 弄坏，跑前后都 `rm -rf __pycache__`。

| # | 把什么改坏 | 结果 |
|---|---|---|
| ① | 否定式不再作废（「别用表格」读成必须用表格） | ✅ |
| ② | 「每段不超过 N 字」当成整块字数 | ✅ |
| ③ | 「必须提到 X」不再要求带引号 | ✅ |
| ④ | 抽出矛盾的数时挑第一个而不是整类作废 | ✅ |
| ⑤ | 字数不留容差 | ✅ |
| ⑥ | 代码围栏也算进字数 | ✅ |
| ⑦ | 正文还没写出来就判不合格 | ✅ |
| ⑧ | 「分三点」只认列表项，不认三段 | ✅ |
| ⑨ | 数字不再做合理范围检查 | ✅ |
| ⑩ | 快照复原成 dict 的约束也照判 | ✅ |
| ⑪ | 条目不再逐字核对依据 | ✅ |
| ⑫ | 程序已经判了的条目不再剔掉 | ✅ |
| ⑬ | 条目没有条数上限 | ✅ |
| ⑭ | 生成出来的条目不是二元的 | ✅ |
| ⑮ | 打分 prompt 里不再写明二元 | ✅ |
| ⑯ | 二元维度上的 1 分不压成 0 | ✅ |
| ⑰ | **所有**维度的 1 分都压成 0（压过头，动了既有三维） | ✅ |
| ⑱ | 抽到约束也不挂那条判据 | ✅ |
| ⑲ | 总开关关掉也照跑 | ✅ |
| ⑳ | 恢复的跑重新生成一次（多花一次调用） | ✅ |
| ㉑ | 生成失败直接往外抛 | ✅ |
| ㉒ | 条目生成了但没接进维度表 | ✅ |
| ㉓ | `prompt` 模式不挂这个 middleware | ✅ |
| ㉔ | 指令那一块的键名在生产侧改掉（bench 取到空串） | ✅ |
| ㉕ | 现场生成的维度在界面上露出 `checklist_1`（前端） | ✅ |
| ㉖ | 依据只对前两个字（模糊核对） | ✅（**第一版没抓住**） |
| ㉗ | 「无从判断」也当成不合格 | ✅（**第一版没抓住**） |
| ㉘ | 条目文字不截断 | ✅（**第一版没抓住**） |
| ㉙ | 指令多长都生成 | ✅ |

**㉖ ㉗ ㉘ 第一轮都没抓住，而且是同一个病：三条闸各自的「反面」没有用例。**
① 依据核对只测了"完全对不上"（「行文流畅」），没测"对上开头、后面是模型自己加的"
（「谁负责的排期」）；② `verify` 的三种返回值只测了 `None` 在 `verify` 那一层，
没测**判据那一层**读不读得对（`is False` 写成 `is not True`，每一次跑的第 1 轮
都会挨一记"没照做"，而那时正文还没生成）；③ 截断根本没人测。
补了三条用例之后当场变红。*突变没被抓住时，先怀疑用例不够。连着十批了。*

### 闸

后端 **1539 → 1594**（+55：`test_prompt_checklist` 新建 50 条、
`test_dimension_sensitivity_bench` +5；那 50 条里有 3 条是突变验第一轮
没抓住之后补的）。
前端 52 个文件 257 条全绿（新增 `dimLabel.test.ts` 3 条）。
`harness-framework.md` 按这一批改了：middleware **15 → 16**（第 3 节目录、
第 7 节标题和表、架构图里的 `Middleware ×15`、「三个词的位置」那张表）、
`checks/ ×11 → ×12`、第 3 节补 `checklist.py` 和 `checks/instructions.py`、
第 8 节补一条「第 20 条判据不在这张表里，因为它不在 `Mode.checks` 上」。

### 计划外发现

1. **`instruction_constraints` 是仓里第一条「不写在 `Mode` 上」的判据。**
   `Mode` 必须是纯数据（`types.Mode` 的原话），而这条判据的内容来自用户刚打的
   那句话，只能在 `before_run` 里 `dataclasses.replace` 进这一次跑的 Mode。
   连带的后果是 `test_harness_modes` 那条「每条 check 在踩满毛病的正文上至少
   触发一次」**盖不到它**（那条闸扫的是 `modes.ALL`），所以它的覆盖全靠
   `test_prompt_checklist` 自己。**这是一类新的判据，闸的形状得跟着变。**
2. **维度名会漏到界面上。** 现场生成的维度叫 `checklist_1`，而前端两处
   （`AgentActivity` 的维度条、`App.runBlock` 的打分日志）一处有映射表、一处
   直接打印维度名——批 11.3 那条「后端在发、前端一处没消费」的镜像版本。
   这一批把那张表收成一处（`editor/dimLabel.ts`），`checklist_N` → 「你的要求 N」。
   **为什么不干脆拿条目原文当维度名**（界面上更好看）：维度名是打分器要在 JSON
   里逐字复现的键，中文长句当键太容易被改写一两个字，而对不上的键在
   `rubric.evaluate` 里拿到的是 level 0——**一次键名没对上就等于一条凭空的
   「不合格」**，正是误伤最贵的那一档。
3. **空泛的指令生成不出有用的条目，而依据核对拦不住它。**
   「总结一下上面的讨论」→ 条目「总结上面的讨论」，逐字有依据、判起来等于没判。
   bench 那 33% 的干净版误判也是同一个根（合成指令太通用）。
   要治得靠「条目必须比指令更可判」这类新判据，**这一批没做，先记着**。
4. **`min_bullets` / `min_paragraphs` 的验证是同一个函数**（`count_units` 取
   列表项和段数里多的那个）。这是有意放宽：「分三点」用三个自然段写是对的。
   代价是「写三段」用三个列表项也算过——**已知的漏，不是 bug**。

### 开工前后的 `notes` 指纹（自己核对过，不是自报）

|  | 开工前 | 收尾 |
|---|---|---|
| `notes` 行数 | 482 | **482** |
| `notes` `max(updated_at)` | `2026-09-16T02:53:27+00:00` | **`2026-09-16T02:53:27+00:00`** |
| 正文总字数 | 321,250 | **321,250** |
| 482 篇逐篇摘要再取一次摘要 | `47dcc54be60aa4f2` | **`47dcc54be60aa4f2`** |
| `note_revisions` 行数 | 44 | **44** |

三次真跑（8 条指令的样例、69 格 bench、4 趟 `prompt` 真跑）全部夹在
`db_guard.Watch()` 里，**命令一律不经过管道**（批 16 事故：`| tail` 让退出码
恒为 0），每次单独打印 `EXIT=$?`；真跑那一趟另外给 Mode 加了
`rails_off=("save",)` 兜底（block 模式本来就没有 `Save`）。

### 下一步

1. **阶段 6 只覆盖了 `prompt` / `custom`。** [IND] §6① 明说「不要一刀切」：
   长文那两个模式有 spine/beats，合成 rubric 的原料是现成的，但那是另一件事
   （条目要对着**小节**判，跟阶段 4.2「判据从整篇改成按小节」是同一条线）。
2. **条目质量本身还没有判据**（发现 3）。最便宜的下一步是把生成出来的条目
   连同用户最后接受 / 拒绝的结果一起落库（阶段 9.1 的采集），
   **「这条条目有没有用」只有用户的编辑答得出来**。
3. **干净版 33% 的误判要在真实指令上重量一次**（现在这个数来自 bench 的合成
   指令，是上界）。语料一到就重量——**判据没误伤过不等于它不会误伤**（批 16 下一步 4）。
4. `follows_prompt` 在 `prompt` 上一分没变（1.33 → 1.33）：**新条目是加出来的
   一条新轴，不是让老轴变灵敏**。要判断整体是不是更好，得看「用户接受率」，
   而那还是阶段 9.1。
5. 计划里剩下的下一个 `P0` 是**阶段 7**（长文专项：7.1 decompose-then-verify、
   7.2「这一节材料够不够」）。

## 批 18 · 阶段 7 的两条 `P0`（7.1 decompose-then-verify + 7.2「这一节材料够不够」）（2026-09-18）

`P0` 两条：**7.1** [IND] §8①（FActScore / SAFE / VeriScore / Claimify）、
**7.2** [LED] §10③（`Sufficient Context`，ICLR 2025，Google）。
一句话：`factual_grounding` 那条线上**能机械核对的那一类命题，从打分器手里
拿回代码这边**；而「这一节压根没有材料」这件事**第一次有判据在问**。

### A. 7.1 —— 拆解粒度是量出来的，原子选类是量完之后砍剩两类

落点 `backend/app/harness/checks/claims.py`（新文件），挂在 `note` / `section`。
**没另起一套**：源头那一侧、「没有 oracle 就不判」、容差纪律全部复用批 16 的
`checks/numbers.py`——那一条已经是「数字」这一类的 decompose-then-verify。

#### 拆解粒度：三档都量了，取句级

在 24 篇 `origin=user` 真实笔记（走 `corpus_lineage`，非空 18 篇）上量：

| 粒度 | 单元数 | 平均字数 | 带指代的单元占比 |
|---|---:|---:|---:|
| 段级 | 683 | 113.2 | 6.1% |
| **句级** | **1446** | **53.4** | **8.1%** |
| 子句级 | 5903 | 13.1 | 4.2% |

**子句级那个 4.2% 是假的**：切到平均 13 个字，大多数单元里连一个指代词都没有
（分母被"什么都不含的碎渣"灌满了），而 5903 个单元里真正带可查原子的不到 2%
——这正是 `Decomposition Dilemmas` 说的「制造无法验证的碎片」。
段级的问题在另一头：平均 113 字，报出来模型不知道改哪一句
（第 601 轮 `no_placeholder` 那次死锁就是「拿整段说事、模型改不动」）。
**句级是两头都不塌的那一档。**

#### 原子：留两类，**砍掉四类，每一类都对着一个实测数字**

留下的两类，**自源头档**（整篇同时当产出和源头，批 16 那套）**0 开火**：

| 原子 | 自源头档 候选 / 开火 | 严苛档 候选 / 开火 |
|---|---:|---:|
| 完整日期（年月日三字段齐全） | 8 / **0** | 0 / **0** |
| 署名里的那个拉丁名字（`X 说 / 提到 / 确认…`） | 17 / **0** | 6 / 5 |

*严苛档* = 每篇后 30% 当「这一轮写的」、前 70% 当**唯一**源头。生产里源头还含
全部事实和工具返回，**这一档是上界不是生产值**；那 5 次全是 `Speaker A/C/D`、
`Aaron` 这类真人，他们在生产里由事实块带进来。

**砍掉的四类**：

1. **两个字段的日期**（「3 月 31 日」「2026 年 6 月」）：严苛档 23 个候选
   **开火 5 次（21.7%）**，五次全是用户笔记里真有的日期。
2. **中文人名**：18 篇真实笔记 + 16 篇脚本产出里**总共 4 个候选，3 个是错的**
   ——`江汽`（江淮汽车的简称）两次、`方案已`（从「方案已确认」里切出来的碎渣）
   一次。姓氏表 + 言说动词这条启发式在中文上不成立，**整类不要**。
3. **所有拉丁专名**（不要求带言说动词）：严苛档 97 个候选**开火 44 次（45.4%）**
   ——`Zoom` / `Discord` / `Apple` / `Harvard`（世界知识，不是对用户项目的断言）、
   `GWh` / `MWh` / `Wh`（单位）、`This` / `You` / `After`（句首英文词）、
   `Ims` / `Scm` / `DeepSeck`（语音转写错字）。**「专名」这个类本身就把世界知识
   和用户专属断言混在一起了**，靠停用词救不回来。
4. **正文里的统计量**（批 16 已经在 eda/analysis 上用着的 `prose_statistics`）：
   严苛档 167 个候选**开火 79 次（47.3%）**。eda 的 task 明写「所有数字都来自
   工具返回，不要自己算」，长文没有这条规矩——模型把三条材料的数合计一下、把
   「4500 万」换算成「0.45 亿」都是**对的写法**，0.5% 的容差救不了合计和换算。
   **这一类留在 eda / analysis 那条道上，不进长文。**

#### SAFE 三步逐条落在哪

* ① 抽命题 → `decompose()`，句级。
* ② 改写以消解指代 → **结构上不需要**。论文要改写是因为它的原子是自然语言
  命题，脱离上下文查不动；我们的原子是**表面字面量**（一个完整日期、一个名字），
  指代不清对字面量不成立。**这是「封闭语料 + 字面原子」白捡的那一半。**
* ③ 相关性检查 → `relevant()`，而更要紧的是**整条流水线只有一个方向**：
  正文 → 源头。「源头里有、正文里没写」在这个模块里**产生不了任何裁决**。
  `_FACTUAL_GROUNDING` 那条吃过亏才写进 guidance 的规矩（「检索到的事实没有被
  全部用上，明确不算不足」）**从一句指望模型自觉的话，变成一条走不通的路**，
  另有一条单测钉着（40 条一条没用上的材料 + 一段通用正文 → 必须 `None`）。

#### 真实笔记上的误伤（这一批最大的风险）

脚本 `backend/scripts/claim_misfire_probe.py`（只读，夹在 `db_guard.Watch()` 里）：

| | 数 |
|---|---:|
| 语料 | `origin=user` **24 篇**（排掉 458 篇），非空 18 篇 |
| 自源头档 候选 / **开火** | 16 / **0** |
| 严苛档 候选 / 开火 | 6 / 2（两次都是 `Speaker B` / `Speaker D`，上界不是生产值） |
| 反向（把一个真日期的年份挪走，必须抓住） | 抓住 **2**，漏 **0**（16 篇没有完整日期可植入） |

**真跑那一侧**（`terrence` 真库、note 模式、2 次跑共 5 轮、`rails_off=("save",)`）：
**5 轮 0 误伤**——但同时**5 轮一共 0 个候选原子**。也就是说，这条判据在真实长文
产出上**几乎不开火**：模型写的是 `[terrence-1872-5F8]` 这种引用，不写「Speaker A 说」，
也很少写完整年月日。**这是这一批最该被后面几批盯住的一条**（见「下一步」②）。

#### 灵敏度前后（`dimension_sensitivity_bench`，新增 `condition="claims"`）

新增的这一档跟自己的 `as-deployed` 兄弟行严格配对（同一段正文、同一份上下文、
同一份材料），差别只有一样：**判据先不先跑**。生产里 `middleware/checks` 在
`before_judge` 跑，命中就把那一维记成 0 并 `skip_judge`——这一档照做，
**命中的格子一次模型调用都不发**（有闸钉着）。所以 `as-deployed` 那一行量的是
**纯打分器**，`claims` 这一行量的是**生产链路**。

| probe | 条件 | 干净 | 植入 | 掉分 | 篇 | 次 | p |
|---|---|---:|---:|---:|---:|---:|---:|
| `note/fabricate_specifics` | as-deployed | 1.36 | 0.36 | **1.00** | 5 | 25 | — |
| `note/fabricate_specifics` | **claims** | 1.00 | 0.00 | **1.00** | 5 | 30 | 0.0005 |
| `note/shift_dates` | as-deployed | 1.07 | 0.00 | **1.07** | 3 | 15 | 0.0002（批 9） |
| `note/shift_dates` | **claims** | 0.75 | 0.00 | **0.75** | 4 | 24 | 0.0025 |

**严格配对的那个子集**（同一批 (笔记, 重复次) 的格子）：

| probe | 配对格数 | as-deployed 掉分 | claims 掉分 | 差 | 配对置换 p |
|---|---:|---:|---:|---:|---:|
| `fabricate_specifics` | 9 | 1.00 | **1.33** | **+0.33** | 0.497 |
| `shift_dates` | 6 | 1.00 | 1.00 | +0.00 | 1.000 |

**判据本身的命中率（这才是真正的那个数）**：

| probe | 干净臂开火 | 植入臂抓住 |
|---|---:|---:|
| `fabricate_specifics` | **0 / 15** | **15 / 15（100%）** |
| `shift_dates` | **0 / 12** | 3 / 12（25%） |
| 合计 | **0 / 27** | 18 / 27（66.7%） |

`shift_dates` 那 25% 就是**砍掉两字段日期的明码标价**：4 篇语料里只有 1 篇有
完整年月日可挪，另外 3 篇的日期都是「3 月 31 日」这一档，而那一档实测 21.7%
会误伤。**用 75% 的召回换 0 误伤，这是铁律规定的方向，不是保守。**

**必须一起读的一条**：干净臂的打分本来就只有 **1.00 / 1.36**，不是 2.0。
也就是说 `factual_grounding` **41% 不达标的大头在干净正文上**（打分器对没动过的
真实笔记也照样判 0/1），而这一批动的是植入那一侧。**天花板没动。**

### B. 7.2 —— 信号有了，弃答形态仓里早就有

落点 `checks/grounding.material_thin` + `checks/grounding_rules.abstention_lines`，
开关 `params.SUFFICIENT_CONTEXT`。

#### 信号长什么样

两个触发条件，都窄：

* **(a)** 手上一条材料都没有，而正文照样写满了（≥200 字）；
* **(b)** 账本里**问过的方向**有「库里一条都没有」的（`axes` 里 `total<=0` 且
  `taken<=0`），**并且**这一轮零新材料、**并且**这一轮正文里零 `[事实编号]`。

(b) 为什么非要叠三个条件：光凭「这一轮没有新材料」会在正常的收尾轮上开火
——**实测 336 个真实 note 轮次里 58 轮 `facts_new=0`**，绝大多数是在把前几轮
取回来的材料写完。三个同时成立，才叫「在对着空气写」。

**守住 [LED] §4 那条边界**：手上只要有材料就一个字都不说；看的只有**分母**
（这个方向库里有没有东西），从不看**用掉的比例**；报出来的话里
**一个「你还有 N 条没用」都不许出现**——有一条闸用正则钉着这一类措辞，
而且那条闸自己也有反面用例（`"知识库里还有 29 条没用上"` 必须被它抓住）。

#### 真跑：「材料不够」两趟 / 「材料充足」两趟

| 臂 | 用户 | 轮 | 每轮 facts | thin 开火 | claims 开火 | 收尾 |
|---|---|---:|---:|---:|---:|---|
| 空库·下半年规划 | `writing-bench`（`kb_is_empty=True`） | 2 | 0 | **2 / 2** | 0 | `material_used_up` |
| 空库·定价 | 同上 | 2 | 0 | **1 / 2** | 0 | `material_used_up` |
| terrence·众筹节奏 | `terrence`（20000+ 条） | 2 | 12 → 24 | **0 / 2** | 0 | `regressed` |
| terrence·硬件量产 | 同上 | 3 | 12 → 27 → 30 | **0 / 3** | 0 | `max_rounds` |

**弃答真的被触发了。** 空库·定价那一趟第 2 轮，模型自己写出了：

> 「这里需要补上批18探针的实际采购记录、配件金额、渠道费用、报价汇率和结算汇率，
> 完成这次核对后，才能判断原报价是否真正覆盖了总成本。」

`abstention_lines` 认得出它 → 判据当轮放行。**一整条闭环走通了**：
分母（空库）→ 信号 → 诊断（逐字给出写法）→ 模型照做 → 判据不再拦。

**另一趟没照做**（「下半年规划」那个种子太像通用方法论，模型两轮都在写建议），
判据两轮都拦，最后停在 `material_used_up`。**4 次开火里 1 次照做**，n 很小，
但方向对：**开工前那一趟同样的种子跑出来是 `stopped=complete`——
系统告诉用户"写完了"，而正文里一条用户自己的东西都没有。**

**有没有「逼它去凑」的迹象**：没有。`terrence` 那两趟 5 轮一次都没开火，
模型该取多少取多少（12 → 24 / 12 → 27 → 30），没有出现为了满足判据而硬塞
材料的痕迹；空库那两趟手上根本没有材料可凑，模型的选择只有"继续写通用内容"
（被拦）或"写那句弃答"（放行），**两条路都不通向"凑"**。

#### 真跑当场否掉了一道自己写的闸（这一批最值钱的一次真跑）

第一版照批 16「没有工具输出就不判」的样子，给 `material_thin` 也写了一条
「**没发过查询就不判**」。拿空库用户真跑：**模型一次工具都没调**，两轮写了
937 字纯通用内容，`stopped=complete`——**判据被自己那道闸堵住，一声没吭。**

两条纪律的区别在这儿：批 16 那条挡的是「查无出处」，那句话在没有 oracle 时
**确实说不出口**；而这一条说的是「**手上一条材料都没有**」，这件事
**直接看得见**，不需要任何 oracle。闸撤掉，改成按"为什么没有"分三种说法，
每一种都给一个**照办得了**的下一步：

* 问过了、库里没有 → 直接弃答（换个说法再问也不会有）；
* 一次没问 + 库是空的 → 直接弃答；
* 一次没问 + 库里有东西 → **先去查**（给出 `filter_facts` / `search_memory`），
  查完确实没有再弃答。

*给一个照办不了的下一步，等于把剩下的轮次烧掉——第 601 轮那次死锁的形状。*

#### 判据之间不许打架（这次是主动去撞的）

7.2 让模型写的那句话，如果被 `audit_voice_lines` 当成审计腔整句删掉、或者被
`placeholder_lines` 当成占位符打回，这条诊断就是个照办不了的要求。
所以有一条闸**从判据自己的输出里**把那句话摘出来，再过一遍另外三道
（`abstention_lines` 必须认得、`audit_voice_lines` / `placeholder_lines` 必须不响）。
**光钉住字面那句话不够**——把 `_abstain_hint()` 改成「材料不足以说明」，
钉字面的那条测试照样绿，而生产里两条判据当场打起来（突变 ㉗ 就是这一条）。

### 突变验（37 条，37 条变红）

**基线 1594 绿。** 每条单独撤掉 / 弄坏，跑前后都 `rm -rf __pycache__`。

| # | 把什么改坏 | 结果 |
|---|---|---|
| ① | 日期原子放宽到两个字段 | ✅ |
| ② | 署名不再要求紧跟言说动词（退化成所有拉丁专名） | ✅ |
| ③ | 停用名单取消（`Owner 负责…` 当人名） | ✅ |
| ④ | 把中文人名那一类补回来 | ✅ |
| ⑤ | 拆解改成子句级 | ✅ |
| ⑥ | 围栏 / 表格 / 引用块也参与拆解 | ✅ |
| ⑦ | 源头不含整篇笔记 | ✅ |
| ⑧ | 源头不含这次跑之前写出来的部分 | ✅ |
| ⑨ | 判整篇而不是只判这一轮写的 | ✅（**第一版没抓住**，见下） |
| ⑨b | 这一轮写的挪到正文中间时分不干净 | ✅（**第一版没抓住**，见下） |
| ⑩ | 没有 oracle 也照判 | ✅ |
| ⑪ | 取消这一轮字数下限（7.1） | ✅ |
| ⑫ | 源头只给到年月时不算覆盖完整日期 | ✅ |
| ⑬ | **SAFE ③ 的方向反过来**：源头有、正文没写也报 | ✅ |
| ⑭ | 长文两个模式不挂这两条判据 | ✅ |
| ⑮ | block 模式也挂上 | ✅ |
| ⑯ | `material_thin` 排到 `citations_present` 后面 | ✅ |
| ⑰ | `material_thin` 恒不开火 | ✅ |
| ⑱ | 手上有材料也照判（越过 [LED] §4 那条边界） | ✅ |
| ⑲ | 把「没问过就不判」那道闸装回去 | ✅ |
| ⑳ | 已经弃答了还再拦一次 | ✅ |
| ㉑ | 取消这一轮字数下限（7.2） | ✅ |
| ㉒ | 大纲模式也判 | ✅ |
| ㉓ | 打磨模式也判 | ✅ |
| ㉔ | 空方向那一档不叠「这一轮零引用」 | ✅ |
| ㉕ | 有分母的方向也算空白 | ✅ |
| ㉖ | 诊断里写「你还有 N 条没用」 | ✅ |
| ㉗ | 弃答形态改成审计腔（两条判据当场打架） | ✅ |
| ㉘ | 认不出弃答句 | ✅ |
| ㉙ | 开关关掉也照跑 | ✅ |
| ㉚ | bench 自己抄一份判据（不走生产那个函数） | ✅ |
| ㉛ | bench 判据命中了还去打分（白花钱） | ✅ |
| ㉜ | bench 的 `claims` 行没有配对的 `as-deployed` 行 | ✅ |
| ㉝ | 撤掉给 `test_harness_modes` 补的那两句缺陷素材 | ✅ |
| ㉞ | 撤掉给它补的那份「查过但没有材料」素材 | ✅ |
| ㉟ | 文档里的 check 条数不同步 | ✅ |
| ㊱ | `claims.py` 不在第 3 节那张目录图上 | ✅ |

**⑨ 和 ⑨b 第一版都没抓住，而且是同一个病**：`fresh_text` / `sources` 那条缝上，
「行为上看不出差别」被当成了「没差别」。⑨ 把待核对的那一段换成整篇正文——
全套 1645 条一条没红，因为 `sources()` 里本来就含着「这次跑之前已经写出来的
部分」，整篇里多出来的原子按定义全都有出处。⑨b 把「fresh 是 content 的**子串**」
那条分支拿掉——`prior` 于是等于整篇正文（里面含着 fresh 自己），
**判据从此对什么都不开火，而全套测试一声不吭**。
补了两条用例（一条直接钉住那条缝，一条构造「定向续写把这一轮写的插在正文中间」
的形状）之后当场变红。*突变没被抓住时，先怀疑用例不够。连着十一批了。*

### 闸

后端 **1594 → 1648**（+54：`test_claims_grounding` 新建 48 条、
`test_dimension_sensitivity_bench` +5、`test_harness_modes` 的缺陷素材扩了一份）。
前端 52 个文件 257 条全绿（一行没动）。
`harness-framework.md` 按这一批改了：check **19 → 21**（第 1 节 R2、第 6 节
判据三层、第 8 节标题、第 3 节目录树、「第 20 条 → 第 22 条」那条注）、
`checks/ ×12 → ×13`、目录树补 `claims`、第 8 节补两行。

### 这一批的实际成本

`gpt-5.6-luna`：**80 次调用、prompt 429,498 token（命中缓存 282,478 = 65.8%）、
completion 37,568 token**，模型墙上时间约 **10.2 分钟**。
其中 bench 的 `claims` 那一档只花了 36 次调用——**18 个植入格判据当场命中，
一次打分调用都没发**（本来要 54 次）。

### 计划外发现

1. **真跑当场否掉了一道照着上一批抄来的闸**（B 那一节）。
   「没有工具输出就不判」是批 16 的纪律，抄到 7.2 上就变成了「模型不查我就不说」，
   而**模型不查正是要说的那件事**。*上一批的纪律不能按字面抄到下一批。*
2. **`factual_grounding` 的问题大头在干净正文上，不在植入那一侧。**
   bench 日志里这一维在**没动过的真实笔记**上判 0 的有 **72 / 364 格（19.8%）**、
   判 1 的 102 格——干净臂均分只有 1.0~1.36。这一批（以及批 9 那个 1.07）量的
   全是"植入之后掉多少"，而 41% 不达标的分子里，很大一块是**打分器对干净文本
   的误判**。要动它得从判词那一侧走，跟 7.4（三档 → 二元）是同一条线。
3. **7.1 在真实长文产出上几乎没有候选原子**（真跑 5 轮 0 个）。
   这个模型写的是 `[terrence-1872-5F8]` 这种引用，不写「Speaker A 说」，
   完整年月日也少。**建了判据不等于用了判据**——这条现在更像是给"未来某次
   编造"准备的安全网，而不是一条日常起作用的判据。
4. **`tabular` 那份倍数后缀名单的影响面还没量**（批 16 下一步 3 留下的）。
   这一批的 `claims` 绕开了数字这一类，所以没碰它，但那条待办还在。
5. **in-process 跑 harness 时 `ctx_feature` 是空的**：分步骤记账
   （`:tools` / `:judge`）是 `loop._step` 在设，而顶层那个 feature 名由 router 设。
   拿脚本直接驱动 `loop.run` 时用量表里那一列是空串。**不影响产品**，
   但下次做"多花一次调用值不值"的账时要先把它填上，否则分不出是哪一步。

### 开工前后的 `notes` 指纹（自己核对过，不是自报）

|  | 开工前（= 批 17 收尾） | 收尾 |
|---|---|---|
| `notes` 行数 | 482 | **482** |
| `notes` `max(updated_at)` | `2026-09-16T02:53:27+00:00` | **`2026-09-16T02:53:27+00:00`** |
| 正文总字数 | 321,250 | **321,250** |
| 482 篇逐篇摘要再取一次摘要 | `47dcc54be60aa4f2` | **`47dcc54be60aa4f2`** |
| `note_revisions` 行数 | 44 | **44** |

四趟真跑 + 一次 bench + 一次误伤探针**全部**夹在 `db_guard.Watch()` 里，
**命令一律不经过管道**（批 16 事故：`| tail` 让退出码恒为 0），每次单独打印
`EXIT=$?`；真跑那一趟另外给 Mode 加了 `rails_off=("save",)` 兜底。

### 下一步

1. **`factual_grounding` 的天花板要单独立项**（发现 2）：干净正文上 19.8% 判 0，
   这一块任何植入式 probe 都量不到。最接近的现成动作是 7.4
   （三档 → 二元 checklist，[LONG] §4 / [IND] §6②），但它写着「**先按维度量
   一致率再决定改哪几维**」，而一致率是阶段 9.2，依赖 9.1 的采集。
2. **7.1 的候选率要在更多真跑上量一次**（发现 3）。如果连着几十轮都是 0 候选，
   那么下一步不是放宽原子（两字段日期 21.7% 误伤的账摆在那儿），而是**换一类
   有产量的原子**——最可能的一类是「正文里那句话引的 `[id]` 跟它旁边的具体说法
   对不对得上」（ALCE 的 citation precision，计划 2.7 那一条），
   那一类在真实产出里**密度是 4.53 / 千字**（批 13 实测）。
3. **7.2 的「照做率」要攒样本**：4 次开火 1 次照做，n 太小。
   最便宜的办法是把「判据开火 → 下一轮有没有弃答句」记进 `harness_rounds`，
   跟阶段 9.1 的采集一起做。
4. 阶段 7 还剩 **7.3**（`section_coverage` 加字数预算，[LONG] 建议四）和
   **7.4**（三档 → 二元，卡在 9.2）。7.3 不依赖采集，是下一个能直接做的。

## 批 19 · 阶段 4 剩下的五条（4.2 / 4.3 / 4.4 / 4.5 / 4.6）（2026-09-18）

阶段 4「评判形态」补完（**7/7**）。五条里有**两条的结论是「不做」**——
4.5 量完之后选了「承认它只能停机」，4.3 量完之后砍掉了原计划里的两条判据。
两次都是先有数再有结论，数在下面。

### 4.4 + 4.5 —— 同一件事的两半

#### 4.4：`coherence` 不再当兜底桶

`pick_dimension(st, 首选, 次选, 三选)` 的 **13 处调用**里，`"coherence"` 写在
第二 / 第三位。于是 `coherence = 0` 可能意味着审计腔、手写 mermaid、大纲被
压平、表格列数对不上……**也可能真的是文章不连贯**。而 `Repair` 一律读成
「这一轮只修不写」。

改法：兜底落到 `checks/pick.MECHANICS`——**一个不是评分维度的桶**。
打分器见不到它（不在 `Mode.dims` 里）、它不在 `repair.INNER_QUALITY` 里
（排不了修复轮）、也不在 `loop.COVERAGE_DIMS` 里（不算「还没写够」）。
它只表示一件事：**代码判据在这一轮抓到了一个机械缺陷**。

实测这个兜底真的被走到过——`harness_rounds` 的 **354 轮里 222 轮是判据
短路的（62.7%）**，落点：

| 落在哪一维 | 轮次 |
|---|---:|
| `factual_grounding` | 166 |
| `non_repetition` | 55 |
| **`coherence`** | **1** |

那 1 轮就是长文模式下图表判据落在兜底上的形状（第 606 轮那次死锁的同一个
位置）。静态上有 **7 对 (mode, check)** 会落进兜底桶，`tests/test_harness_modes.py`
把这 7 对**逐对写死**——桶最容易变成新的垃圾桶，而垃圾桶是安静地长回来的。

**这一改在真跑里当场看见了**：4.2 的真跑 A/B 里有一轮 `harness_rounds` 记的是
`{"mechanics": 0}`。在这之前，那一轮会往 `coherence` 头上记一笔 0 分，而正文
连贯与否根本没人看过。

#### 4.5：选了「**写明它只能停机**」，依据三条，全是数

[MECH] 第 2 层第 5 条给的是二选一：补一个位置级探测器，或者承认它只能停机
并在代码里写明。这一批去量了一次「那要不要补」，结论是**不补**：

**① 能机械判的那两款，分母接近零。** `_COHERENCE` 那条判词列了五款，只有
第 (2)(3) 款是结构性的——标题层级、小节编号（判词里逐字写着「1、2、4、3」）。
`scripts/coherence_denominator.py`（只读，夹在 `db_guard.Watch()` 里）：

| 血缘 | 篇 | 非空 | 标题 | 相邻标题对 | 兄弟组 ≥2 | 全带编号 | 开火 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `user` | 24 | 18 | 85 | **72** | 21 | **1** | **0** |
| `script` | 21 | 19 | 94 | **76** | 21 | **0** | **0** |
| `fixture` | 437 | 433 | 744 | 314 | 6 | 0 | 0 |

`相邻标题对` 是跳级那一款的分母、`全带编号` 是编号那一款的分母。
**148 个相邻标题对里跳级 0 个、42 个兄弟组里只有 1 组是「每一条都带编号」的**
——「1、2、4、3」那种断号根本没有可比的对象。一条在真实语料上一次都命中不了
的判据，跟一条全部命中的判据一样说明不了任何事（`_corpus.mts` 那条老规矩）。

**② 那一款在生产里已经被明确排除在 `coherence` 之外了。**
`routers/note_harness._score_context` 里记着一次实拍：大纲模式下连着三轮
`coherence` 判「产品和众筹使用三级标题而时间线、团队、反思使用二级标题，
造成标题层级不统一」——**那是用户自己写的大纲**，而且另有一道硬闸保证它改不了。
修法是告诉打分器「不要评价标题的层级、措辞或顺序」。再做一个机械版的标题判据，
等于把那次已经判过的事重新判一遍。

**③ 它几乎从来不是唯一的阻塞项。** 347 个 note 轮次：

| | 数 |
|---|---:|
| `coherence` 出现的轮次 | 123 |
| 其中判 0 | **46（37.4%）** |
| 其中不达标（<2） | 75（61%） |
| **「只剩 `coherence` 一维不达标」** | **2 轮** |
| **连着两轮只剩它** | **0 轮** |

每维不达标次数：`factual_grounding` 249 · `non_repetition` 136 ·
`coherence` 75 · `spine_fidelity` 48 · `beat_coverage` 27 · `material_use` 27。
也就是说它每次拖住回路，旁边都站着一个**有**探测器的维度，修复轮本来就会被
那一个排出来。

**怎么写明的**：不是注释（「凡是只能靠自报来保证的性质，迟早会被报错一次」），
是 `repair.STOP_ONLY` / `_REPAIRABLE` 两个集合 —— `Repair` 只从后者挑要修的
维度，另有一条闸钉着两者加起来正好是 `INNER_QUALITY` 且交集为空。
`coherence` 剩下的作用一点没少：`status` 到不了 `complete`、进 `rank()` 拉低
排名、当它最弱时诊断照样进 `focus_note` 交给修订那一步。
**少的只有一件事：不再为它专门烧掉一整轮「只修不写」。**

顺带退休了一条旧断言：`test_check_stuck.py` 里「打分器真判 coherence 不合格时，
只修不写仍然对」现在反过来了。而它前半截那个 `skip_judge` 分支**留着**——
它挡的是另一个性质（判据伪造的 Evaluation 只有一个维度，`Repair` 的设计前提
是读完整的分数向量）。

**计划里「没有位置级探测器的内在质量维度 2 → 0」这一条，这一批做掉一个**，
剩下 `topic_fidelity`。

### 4.6 —— [EVAL] 说「先看数据」，这一批先看了

`scripts/block_rounds_probe.py`：六个模式 × 3 次真跑，种子是同一篇带真数据表
的真实笔记（`309f19202309`，光标放在那张 benchmark 分数表后面）。
全程 `rails_off=("save",)` + `db_guard.Watch()`，**命令不经过任何管道**。

#### 「前」（还没挂停机条件）：18 次跑 / 38 轮

| 模式 | 跑 | 轮 | 怎么停的 |
|---|---:|---:|---|
| eda | 3 | 9 | `max_rounds` ×3 |
| chart | 3 | 4 | `complete` ×3 |
| table | 3 | 6 | `complete` ×3 |
| analysis | 3 | 9 | `max_rounds` ×3 |
| prompt | 3 | 5 | `complete` ×2 · `max_rounds` ×1 |
| custom | 3 | 5 | `complete` ×2 · `max_rounds` ×1 |

**8 / 18 次跑（44%）跑满轮数**。第 2 轮起的 21 个轮次里：

| 信号 | 轮次 |
|---|---:|
| 产出跟上一轮相似度 ≥ 0.95 | 5（24%） |
| 没成为新的最好那一轮 | 9（43%） |
| **这一轮发的工具调用全是之前发过的** | **8（38%）** |
| **分数向量跟上一轮一字不差** | **2** |

信号是真的在那儿，而**没有任何一条代码在看它们**。

#### 同一批数据当场否掉了两条按字面加的规则

* **「没成为新的最好那一轮就停」不行**：`eda` 有两次跑的第 2 轮没成为最好，
  而**第 3 轮成了**——按这条停会当场扔掉那两轮。
* **「工具调用全是重复的就停」不行**：`table` 有一次跑第 2 轮工具全重复
  （1 次调用 1 次重复）、产出也只跟上一轮差 0.14，而**第 3 轮才达到
  `complete`**——按这条停会交出一份没达标的产物。

所以两条都比字面窄一档：

* `nothing_changed`：**分数向量逐维逐值相同**才算「什么都没变」。
  为什么看分数不看正文：block 的 `produce` 每轮整块重写，措辞总会飘
  ——相似度 ≥0.95 的有 5 轮，而分数一字不差的只有 2 轮。判据短路的轮次
  不参与比对（`Ledger` 只把真打过分的轮次攒进 `score_vectors`）。
* `tools_ran_dry`：工具调用全是重复的**并且这一轮没成为最好的那一轮**。
  叠上第二个条件之后，那 8 轮里只剩 2 轮会停，**误停 0**。

停机条件是**只读**的（`loop.py` 那段注释写死了），所以「上一轮判了多少」由
`Ledger.after_judge` 记 —— 它本来就在记同一份 scores。**那一份不会流到打分器
那边**：第 765 轮删掉 `last_scores` 是因为 anchoring bias，这一份的唯一读者是
一条确定性的停机规则。

#### 「后」（挂上之后）：18 次跑 / 35 轮

| 模式 | 跑 | 轮 | 怎么停的 |
|---|---:|---:|---|
| eda | 3 | 9 | `max_rounds` ×3 |
| chart | 3 | 3 | `complete` ×3 |
| table | 3 | 4 | `complete` ×3 |
| analysis | 3 | 9 | `max_rounds` ×2 · **`tools_ran_dry` ×1** |
| prompt | 3 | 4 | `complete` ×3 |
| custom | 3 | 6 | `complete` ×2 · `max_rounds` ×1 |

**`tools_ran_dry` 在真跑里真的响了一次**，而且响在 `analysis` 的第 3 轮——
正是「前」那一批里 3/3 跑满、第 3 轮每次都被 `numbers_from_tools` 打回的那个
模式。那一轮 4 次工具调用 4 次全是重复的，`became_best=False`，交的是第 2 轮。

**必须一起读的一条**：两批是**独立采样**（温度 0.4），38 → 35 轮这个差
**不能全归因于新判据**。能归因的只有那一格：`max_rounds` 里有一次变成了
`tools_ran_dry`，而「跑满了」和「查到头了」不是一回事——阶段 0 的 0.3 花了
一整条列去分开三种失败，这条是同一件事。

### 4.3 —— `skeleton` 配判据，照 `slides` 形态

落点 `app/harness/checks/skeleton.py`（新文件，纯函数、零模型调用）。
两个入口都接上了：`routers/compose.skeleton`（`SkeletonOut.notes`）和
`hooks/note.skeleton`（`CUSTOM_SKELETON` 事件多一个 `notes`），前端
`SkeletonPanel` 把它显示在骨架下面。**判了不拦着落库**——骨架是一次成型的
产物，重不重新生成由用户定。

语料：`notes` 表里 `spine`/`beats` 非空的 **20 篇**（12 `user` / 3 `script` /
5 `fixture`）。五条判据的阈值全在这 20 份上量：

| 判据 | 量到的分布 | 门槛 | 这 20 份上开火 |
|---|---|---|---:|
| 节拍太少 | 3–6 条，从没出过界 | `< 3` | 0 |
| 两条节拍撞车 | 每份内部两两最像的一对 **0.13–0.29** | `≥ 0.55` | 0 |
| spine 只剩一个话题名 | 32–143 字 | `< 15` 字 | 0 |
| 一条节拍都不带锚点 | 每份至少 **2** 条带（最少的两份是 2/5、2/4） | `== 0` | 0 |
| 把正文的毛病写成写作意图 | — | 词表命中 | 0 |

**五条全部开火 0，这是有意的**：它们是**回归探测器**，盯的是
`SKELETON_SYSTEM` 那段提示词里逐字记着的几次代价很大的实拍（一篇编号
1、2、4、3 的笔记被读成刻意手法、一句自相矛盾被读成「反转张力」、五条节拍
全是修辞功能位导致产出是通用常识而用户库里有 341 条成本记录）。
**提示词治好了它们，而提示词是会被改的。** 反向那一半（逐条植入用例）
在 `tests/test_skeleton_checks.py` 里钉着。

#### 两条量完之后决定**不做**

* **「spine 是不是一个真的张力」不做。** 拿词表判（「不是…而是」「之间」
  「取舍」「如何」…）在 20 份上**误伤 5 份（25%）**，而那 5 份里至少 3 份是
  货真价实的张力，只是措辞不在表上——「拆穿自己用…掩盖…的习惯」、
  「从『被记录的聊天内容』推进成…决策材料」。这正是 `slides.py` 里
  `NOUN_PHRASE_MAX` 那一次的同一课：**枚举语言现象的表永远补不全**。
  能留下的只有量的判断（spine 太薄），那一条在上面。
* **「beats 覆不覆盖标题点到的面」不做。** 20 份里**能从标题拆出两个面的
  一份都没有**——11 份标题是「未命名」，其余是「创业反思」「hi」这类单短语。
  分母是零，判据无从校准。

大纲模式下**不体检**：那时候 beats 是用户自己的目录逐字搬过来的，拿「节拍
太少 / 没有锚点」去说它，跟 `_score_context` 里那条「不要评价标题」是同一件事。

### 4.2 —— 打分器不再每一轮读整篇

`loop._evaluate` 递给 `evaluate()` 的 `content` 现在过一道
`score_context.body_for_scoring`：正文超过 `Mode.context_keep_last` 时，
更早的小节换成**目录行**（标题 + 第一句正文 + 字数），后面几节逐字。
开关 `params.SECTION_SCORING`。

#### 理由是判得准，不是省钱

省钱那一头批 16 已经量死了：这个端点的前缀缓存按 message 为单位，judge 只有
**一条** user message、整段每轮重拼，**排布和长度买不到一个 token**（0.0%）。
留下的理由只有 [LONG] §3 那三条偏差，而实测这不是个假想的规模：

| | 数 |
|---|---:|
| `harness_rounds` 里的 note 轮次 | 347 |
| 正文中位数 | **5241 字** |
| p90 / 最长 | 8396 / 9832 |
| **超过 4000 字的轮次** | **204（59%）** |

真实语料上（`origin=user`，≥600 字的 13 篇）：3 篇过阈值、**2 篇真的被切**
（`309f19202309` 30588 → 4547，**切掉 74%**；`92d07b760f1e` 4889 → 4801）。
第三篇 `715266c1fcb4` 26714 字 **0 个 `##`**，走「分不出小节就退回原文」。

**整个取舍能成立的前提**：确定性判据一律照旧看整篇（`find_repeats` 的
`dup_hints`、`no_restated_paragraph`、`claims`…）。中间那几节没有变成盲区，
变的只是**交给模型的那一份**——铁律原话：能用代码判准的，不交给模型。

#### bench 上的严格配对 A/B（n=1 篇 × 3 次，**不下跨篇结论**）

`dimension_sensitivity_bench` 新增 `condition="whole-piece"`（旧行为的对照臂），
`as-deployed` 跟着生产走了切分。挑的四条 probe 是**最可能被按小节判伤到**
的四条。两臂严格配对：同一篇、同一个植入、同一份上下文，只差正文切没切。

| 笔记 | probe | 维度 | whole-piece 干净/掉分 | as-deployed 干净/掉分 |
|---|---|---|---|---|
| `309f19202309` | `duplicate_paragraph` | `non_repetition` | 1.00 / **1.00** | 1.67 / **0.33** |
| `309f19202309` | `double_ending` | `coherence` | 0.00 / **0.00** | 1.00 / **1.00** |
| `309f19202309` | `heading_levels` | `coherence` | 0.00 / 0.00 | 0.33 / −0.33 |
| `309f19202309` | `shift_dates` | `factual_grounding` | 0.00 / 0.00 | 0.00 / 0.00 |
| `06647b9c2031`（对照，没被切） | 四条全部 | | 0.00 / 0.00 | 0.00 / **0.00** |

对照那一篇两臂**逐字相同**，四条差全是 +0.00——说明这条流水线本身没有引入
噪声。被切的那一篇上，两个方向同时出现：

* **干净臂的分数普遍上去了**（`non_repetition` 1.00 → 1.67、
  `coherence` 0.00 → 1.00 / 0.00 → 0.33）。这正是 [LONG] §3 预测的那一半：
  整篇 30588 字判出来的 0 分里有一大块是「读不动」。跟批 18 发现 2
  （`factual_grounding` 41% 不达标的大头在**干净正文**上）是同一个现象的
  另外两维。
* **召回有得有失**：`double_ending` 掉分 0.00 → **1.00**（二次收尾是结构性的，
  切短之后反而看得见了）；`duplicate_paragraph` 掉分 1.00 → **0.33**。

**那个召回损失是上界，不是生产值**，而且是查得清楚的：bench 调
`evaluate()` 时**不传 `dup_hints`**，而生产里 `Repeats` 在**整篇**上跑
`find_repeats`——拿那一格的植入正文实测，它以 **100% 相似度**抓到了被复制的
那一段，那一对会原样进打分 prompt。（顺带：被复制的那一段这次还留在切过的
那一份里，所以那 0.33 更可能是 n=3 的噪声。）
n=1 篇 × 3 次，bench 自己的报告都写着「两侧 p 最小 0.10，**数学上不可能显著**」
——这是方向，不是结论。

#### 真跑那一侧：**量不到**，而原因本身是条已知的发现

`terrence` 真库、note 模式、种子 `309f19202309`、`rails_off=("save",)`：
`on` 3 次 9 轮、`off` 2 次 6 轮。

| 臂 | 跑 | 轮 | **真的发出打分调用的轮次** | 秒/跑 | 收场 |
|---|---:|---:|---:|---:|---|
| on | 3 | 9 | **3** | 109.4 | `max_rounds` ×3 |
| off | 2 | 6 | **0** | 103.8 | `max_rounds` ×2 |

`off` 那两趟 6 轮**一次真打分都没发生**——每一轮都被确定性判据先短路了。
这跟批 16 计划外发现 3 是同一件事（「judge 在真跑里很少连着被调两次」），
只是这一批撞得更彻底。**所以 4.2 的效果在真跑上结构性地量不到，bench 才是
能量到的那一侧**。0 报错，笔记指纹逐字不动。

#### 动了 `loop.py` 吗：动了一个入参，没动循环结构

铁律写着「不改 `loop.py` 的循环结构」，4.2 确实撞到了它。说服自己的理由：

* `content=` 是**按值**递给 `evaluate()` 的，produce 和 judge 之间**没有任何
  钩子能替换它**——要在 middleware 里做，就得给循环加一个新钩子，**那才是
  改循环结构**；
* 改的是 `_evaluate` 这个**装配函数**的一个入参，循环体、钩子序列、停机规则
  一行没动；批 16 为同一类理由改过同一个函数（材料挪到 `tail_context`）。

理由逐字写进了 `_evaluate` 的 docstring。

### 突变验（32 条，32 条变红）

**基线 1648 绿。** 每条单独撤掉 / 弄坏，跑前后都清 `__pycache__`。

| # | 把什么改坏 | 结果 |
|---|---|---|
| ① | 兜底退回第一个候选（4.4 整条撤掉） | ✅ |
| ② | 图表判据的兜底写回 `coherence` | ✅ |
| ③ | 兜底桶混进 `INNER_QUALITY` | ✅ |
| ④ | 前端兜底桶没有名字（界面上露出 `mechanics`） | ✅ |
| ⑤ | `coherence` 又能排修复轮（4.5 整条撤掉） | ✅ |
| ⑥ | `STOP_ONLY` 清空（两个集合对不上） | ✅ |
| ⑦ | 停机专用的那几维不报出来 | ✅ |
| ⑧ | 顺手把 `non_repetition` 也摘成只能停机 | ✅ |
| ⑨ | 骨架判据恒不报 | ✅ |
| ⑩ | 撞车门槛放到 0.30（贴着实测上界） | ✅ |
| ⑪ | spine 太薄的门槛放到 40 字（越过实测下界） | ✅ |
| ⑫ | 空 spine 也报「太薄」（跟报错路径重复） | ✅ |
| ⑬ | 锚点门槛从「一条都没有」放到「少于一半」 | ✅ |
| ⑭ | 骨架端点不接体检 | ✅ |
| ⑮ | 大纲模式下也体检用户自己的目录 | ✅ |
| ⑯ | 「缺陷当意图」那一类删掉 | ✅ |
| ⑰ | 打分器又读整篇（4.2 整条撤掉） | ✅ |
| ⑱ | 压缩允许把东西压大 | ✅（**第一版没抓住**，见下） |
| ⑲ | 「分不出小节就退回原文」那条分支永不成立 | ✅（**第一版没抓住**，见下） |
| ⑳ | 开关关掉也照切 | ✅ |
| ㉑ | bench 不走生产那个切分 | ✅ |
| ㉒ | bench 的格子指纹还认切之前那一份 | ✅（**第一版没抓住**，见下） |
| ㉓ | 确定性判据也只看切过的那一份 | ✅（**第一版没抓住**，见下） |
| ㉔ | block 模式又一条停机条件都没有 | ✅ |
| ㉕ | `nothing_changed` 恒不响 | ✅ |
| ㉖ | `tools_ran_dry` 不叠「没成为最好那一轮」 | ✅ |
| ㉗ | 一次工具都没调也算「查到头」 | ✅ |
| ㉘ | 判据短路的轮次也进分数向量比对 | ✅ |
| ㉙ | 长文那几条停机条件被 block 那两条顶掉 | ✅ |
| ㉚ | 停机条件自己改状态 | ✅ |
| ㉛ | 文档图上 `checks/` 的文件数不同步 | ✅（**第一版没抓住**，见下） |
| ㉜ | `skeleton` 那一块从第 3 节的目录图上整块摘掉 | ✅（**第一版没抓住**，见下） |

**六条第一版没抓住，六条都是用例不够**（连着十二批了）：

* **⑱** fixture 没踩到那条兜底——59 个小节全装得下逐字尾巴，`first_verbatim`
  恒为 0，那条「压缩不许把东西压大」根本没被执行到。
* **⑲** 那条分支是**同义早退**：`split_sections` 至少给一节，于是凑尾巴的
  循环必然把它整个留下、最后一行原样退回原文——**行为上看不出差别的分支，
  就是没有差别的分支**。它是照抄 `sections.content_for_continue` 抄来的，
  而那边退回的是 `compact_context`（另一种行为）。**照抄结构而不照抄语义，
  会长出测不出来的代码**——跟批 18 那条「上一批的纪律不能按字面抄到下一批」
  是同一个病。这一批把它删了，理由写在原地。
* **㉒** 断言比的是整串 `cell_key`，而里面有 `probe_id`——两档本来就不同，
  拿它做断言等于什么都没查。改成比**指纹段**。
* **㉓** 填充语料**自己就是段内重复的**：第一版「这一节写了很多内容。」×100
  的段内重复比例是 **0.96**，第二版换成「第 n 节的第 i 句…」还是 0.96，
  第三版十个模板轮着填仍有 **0.62**——而判据要抓的正是段内重复，
  于是切没切都照样命中。治本的办法是**让每一段只有一句话**（段内配不出句对，
  比例恒 0）。*造语料的时候，「看起来像正文」和「统计性质像正文」是两件事。*
* **㉛** 文档图上的 `checks/ ×N` **从来没有闸**：`tests/test_doc_counts.py`
  自己的注释写着「那两个数的是文件不是条目，词不一样，不会被这条误伤」。
  新增 `test_图上写的_checks_文件数跟目录里的对得上`。
* **㉜** `test_harness_下的每个文件都在图上` 是个**词袋**：`skeleton` 那一块
  整块摘掉之后它照样绿，因为同一张图上 `routers/compose.py` 那一行的
  「单点动作：skeleton · magic-tap …」里也有这个词。
  *一个判据被别处的同名词顺手满足了，它就没在判它要判的事。*
  新增按块查的 `test_checks_下的每个文件都列在图里_checks_那一块下面`。

### 闸

后端 **1648 → 1695**（+47：`test_block_stops` 新建 13 条、
`test_skeleton_checks` 新建 11 条、`test_section_scoring` 新建 10 条、
`test_coherence_bucket` 新建 9 条、`test_directory_map` +2、
`test_check_stuck` / `test_harness_modes` 各改了一条）。
前端 52 个文件 **257 → 258**（`dimLabel` 补了兜底桶那一条）。
`harness-framework.md` 按这一批改了：目录图 `checks/ ×13 → ×14`、
目录树补 `skeleton`、第 8 节 `no_audit_voice` 那一行的落点改成 `mechanics`。
**check 条数没变（21）**——骨架那五条不进 `Mode.checks`，它是 `slides` 那一档。

### 这一批的实际成本

`gpt-5.6-luna`：**479 次调用、prompt 2,960,743 token（命中缓存
1,853,246 = 62.6%）、completion 175,547 token**，模型墙上时间约 **47.5 分钟**。
大头是两轮 block 真跑（18 × 2 = 36 次跑）和 4.2 的真跑 A/B
（5 次跑 × 3 轮，其中 `off` 那一臂每轮都带着 30588 字整篇正文）。

### 计划外发现

1. **bench 的格子指纹漏掉了「真正交给打分器的那一份」，差点重演批 7 那次
   「续跑拿旧数据当新数据」。** 而且这次的形状更隐蔽：`as-deployed` 和
   `whole-piece` 两档的 `text` **一模一样**，交出去的东西完全不同。
   是读 `cell_key` 的 docstring 读出来的，不是测试报出来的——那条 docstring
   记的正是批 7 的同一次。**修法**：`Task` 多一个 `body` 字段，指纹认它。
2. **「填充语料自己就有那个缺陷」是个反复踩的坑**（见突变验 ㉓）。
   段内查重比例 0.96 / 0.96 / 0.62 三版都错，而错的方式都是「句子看起来
   不一样、字面高度相似」。
3. **同义分支测不出来**（见突变验 ⑲）。照抄一个结构时，要连它**为什么在那儿**
   一起抄——`sections.content_for_continue` 那条分支退回的是另一种行为，
   `body_for_scoring` 这条退回的就是原文。
4. **真跑里 judge 几乎不被调**：4.2 的 `off` 臂 6 轮**一次打分调用都没发**，
   全被确定性判据先短路。批 16 发现 3 说的是「一次跑里 judge 被调几次」，
   这一批撞到的是它的极端形态——**凡是只动打分那一步的改动，真跑量不到，
   只能靠 bench**。这条对阶段 7.4（三档 → 二元）和阶段 9.2（一致率）都成立。
5. **`_first_line` 会把重复原样搬进目录行**：一节的第一句正文要是本身就在
   重复，60 字的提示里会带着它。不是缺陷（目录行本来就是指针），但它让
   「切过之后那段重复就看不见了」这个假设**不总是成立**——测 4.2 的时候
   为此改过一次用例。

### 开工前后的 `notes` 指纹（自己核对过，不是自报）

|  | 开工前（= 批 18 收尾） | 收尾 |
|---|---|---|
| `notes` 行数 | 482 | **482** |
| `notes` `max(updated_at)` | `2026-09-16T02:53:27+00:00` | **`2026-09-16T02:53:27+00:00`** |
| 正文总字数 | 321,250 | **321,250** |
| 482 篇逐篇摘要再取一次摘要 | `47dcc54be60aa4f2` | **`47dcc54be60aa4f2`** |
| `note_revisions` 行数 | 44 | **44** |

两轮 block 真跑（36 次跑）、4.2 的 5 次 note 真跑、一次 bench、两次只读探针
**全部**夹在 `db_guard.Watch()` 里，**命令一律不经过管道**（批 16 事故：
`| tail` 让退出码恒为 0），每次单独打印 `EXIT=$?`；note 真跑那几趟另外给
Mode 加了 `rails_off=("save",)` 兜底。

### 下一步

1. **4.2 的 `duplicate_paragraph` 召回要在「传 `dup_hints`」的条件下重测。**
   bench 那一侧不传，所以实测的 1.00 → 0.33 是**上界**；生产里那一对是
   `find_repeats` 在整篇上以 100% 相似度抓到的，会原样进打分 prompt。
   最便宜的做法是给 bench 补一个「把整篇算出来的 `dup_hints` 也递进去」的档，
   那一档才是真正的 `as-deployed`。
2. **`SECTION_SCORING_MIN_CHARS` 今天借用的是 `Mode.context_keep_last`（4000）**，
   而那个数是按**续写 prompt 的预算**定的。打分这一侧要定自己的数，得先有
   「judge 在多长的正文上开始判不准」的实测——那是阶段 9.2（judge-vs-人
   一致率）才做得出来的事。在那之前这件事写在 `score_context` 里。
3. **4.6 的两条在 `max_rounds=3` 下腾挪空间极小**：唯一能省的只有第 2 轮。
   两批真跑里真正值得治的是另外两件，而它们**不是停机条件能治的**：
   `eda` 3/3 跑满、`analysis` 每次第 3 轮都被 `numbers_from_tools` 打回
   （6 次跑里 5 次），那是**那两个模式的判据跟产出形态对不上**。
4. **阶段 8（`magic-tap` / `journey/report` 配判据）现在可以直接做**：
   4.3 这一次把「`slides` 形态」跑通了第二遍——纯函数 + `notes()` +
   一个不拦路的展示位，两个入口一共二十来行接线。
5. 阶段 4 完了。计划里剩下的下一个不依赖采集的是 **7.3**
   （`section_coverage` 加字数预算，[LONG] 建议四）。

## 批 20 · 阶段 8（两条）+ 7.3（2026-09-18）

三条都是**同一个形态的第三、第四遍**：`slides`（原版）→ `skeleton`（批 19 的 4.3）
→ 这一批的 `magic-tap` / `journey/report`。全确定性、零模型调用、判了不拦着落库、
结果跟产物一起显示给用户。7.3 是另一码事：它**进** `Mode.checks`，会短路一轮打分。

**这一批一次模型调用都没发。** 阈值全部在**已经存在的真实产出**上量
（`scripts/tap_report_denominator.py`，只读 + `db_guard.Watch()`），验收靠
**35 条突变验** + 全量闸。批 19 的 4.3 是同一条路子。

### 8.1 —— `magic-tap` 配判据：四条做、三条量完不做

落点 `app/harness/checks/tap.py`（新文件，纯函数）。接线两处：
`routers/compose.magic_tap` 的 `grounding` 事件多一个 `notes`，前端
`TapProvenance` 把它显示在那条来源行下面。

**在这之前 magic tap 只有两条**：`fact_usage`（材料用上没有）和 `fake_citations`
（引用编号真不真）。`MAGIC_TAP_SYSTEM` 里逐条写着的另外那些规矩——不要复述已有
内容、不要停在半句上、标题必须自带信息、**例子里的字面内容绝对不要抄进正文**
——**一条都没人在看**。

两份语料（`origin=user` 的 18 篇非空真实笔记量误伤；34 份单次续写找真阳性——
后者是 `script` 血缘，按 `corpus_lineage` 的规矩只能看形状）：

| 判据 | 18 篇真实笔记 | 34 份续写 | 结论 |
|---|---:|---:|---|
| 停在半句上（复用 `tailing.needs_tail`） | 5（**不算数**） | **0** | 做 |
| 复述了光标前已有的段落（0.6，复用查重那一份） | **0** | — | 做 |
| 脚手架标题（`## 收束` / `## 收束：真标题`） | **0** | 1（真阳性） | 做 |
| 提示词里的例子被抄进正文 | **0** | 2（**全是真的**） | 做 |
| 审计腔 / 机制泄漏 | 5 | 2 | **不做** |
| 占位符 | 0 | 1（误伤） | **不做** |
| 元评论（「本文将」…） | 0 | 0 | **不做** |

「停在半句」那 5 篇不算数：判的是**这一次写的那一段**，用户自己的笔记停在哪里
跟它无关（`test_体检只看这一次写的那一段` 钉着这条）。

**不做的三条，每一条都对着一个实测**：

1. **审计腔 / 机制泄漏。** 18 篇真实笔记上命中 5 篇，其中 **4 篇命中的是
   「知识库」这个业务词**——「该智能体还将整合全区政务知识库…」是用户在谈一个
   **产品对象**。词表分不开「机制」和「业务词」，而 magic tap 的文字已经流出去了。
2. **占位符。** 34 份续写上命中 1 次，那一次是误伤：
   `- 所有时间类表述带状态标签：已确认 / 计划中 / 待定`——「待定」在这里是内容。
   跟 `placeholder_lines` 注释里记的 mermaid 节点那次是同一种形状。
3. **元评论。** 两份语料上各 0 次，`MAGIC_TAP_SYSTEM` 里也没有这条规矩。
   分母是零的判据校准不出来。

**阈值一个新数都没拍**：复述那条直接用 `repeats.DEFAULT_THRESHOLD`（0.6）和
`MIN_PARAGRAPH_LEN`，理由是「同一个数放两处一定会漂」。

### 8.2 —— `journey/report` 配判据：五条做、两条量完不做

落点 `app/harness/checks/journey.py`。接线：`routers/journey.report` 返回
`notes` 并把它落进 `report.json`（`report_notes`），`GET /day` 的白名单跟着加一项，
前端 `JourneyPage` 显示在日报下面。

**判的只有模型写的那一半**：「时间去哪了」由 `stats.render_time_block()` 算好写好，
判自己算的东西没有意义。比对的也是**真正进了提示词的那几行**（`group_runs` 并过的），
不是原始 `segments.json`——这个区别下面第 2 条「不做」正是栽在它上面。

语料：`<userData>/journey/` 下**两份真实日报**（2026-09-17 / 09-18，18 条 bullet），
输入按 `group_runs` + 同一套行格式**逐字重建**（54 段 → 52 行 / 41 段 → 40 行）。

| 判据 | 两份真实日报上开火 | 门槛 |
|---|---:|---|
| 模型自己算了时长 | **0** | 时长词不在输入里出现过 |
| 写出了规定之外的二级标题 | **0** | 白名单三节 |
| 有 bullet 一个具体东西都不带 | **0 / 18 条** | 一条锚点都没有 |
| 同一节里两条 bullet 说同一件事 | **0**（同节最高 **0.264**） | ≥ 0.55 |
| bullet 里的名字在记录里查无出处 | **0 个拉丁词** | 逐字比对，按 `/` 切开 |

最后那一条正是日报提示词注释里写着的那句「**这跟写作 harness 里 `material_used`
那条判据是同一场仗**」——方法一直是通的，只是没落成判据。

**两条量完之后不做**：

1. **数字查无出处。** 拉丁词 0 个查无出处，**数字有 1 个**：09-17 那份写着
   「第 757 轮调研」，而重建出来的 52 行里没有 `757`。但它**不是编的**——
   原始 `segments.json` 里确实有一条描述带着 757，是 `group_runs` 合并时
   **只留了最长的那一句**把它丢掉了。**这条判据的分母本身不干净**：它报的是
   「合并丢掉了什么」，不是「模型编了什么」。
2. **每节的条数上限。** 提示词要求「每节 2-4 条」，实测两天六节是 4/1/4 和 4/2/3，
   **一次都没出过界**。六节的分母定不出门槛；而「凑条数」真出现时，凑出来的
   那几条通常一个具体名字都不带，锚点那条本来就会接住。

**中途收窄过一次**：拉丁词那条第一版把 `/` 也算进 token，于是
`backend/app/harness/pick_dimension` 整条路径查无出处——而记录里那几层目录和
函数名是**分开出现**的，四段都有出处。两天里唯一的一次开火就是它。按 `/` 切开
之后 0/0。（`test_把记录里的路径拼长一点不算查无出处` 钉着。）

### 7.3 —— `section_coverage` 的字数预算：**能量的都量了，门槛只能这么定**

落点 `app/harness/checks/budget.section_budget`，挂在 `SECTION.checks` 的**最后一位**。

#### 先说分母：分段模式自己**一行数据都没有**

* `harness_rounds` 447 轮里，分段模式 **0 轮**（全是 `note:` 前缀和六个 block 模式）；
* `writing_sections` 里 48 条 `origin=user` 的**正文全是 0 字**（都还是 `pending`，
  压根没有对应的笔记）；
* 唯一有正文的 **13 条全是 `script` 血缘**：
  `411 · 667 · 789 · 886 · 1027 · 1125 · 1182 · 1255 · 1316 · 1795 · 1923 · 1946 · 2862`。

所以这条判据的门槛只能落在那 13 条的最低两条之间。**600 字**：13 条里只有 411
那条在门槛以下，而那一条（《协作原则与工作心态》）四个小标题全是
「信任而非监视」「在线不等于随时在线」这种通用常识，正是要抓的东西。

**照实说：605 那三节（620 / 434 / 429）这条判据只接得住两节。** 抬到 700 能把 620
也接住，代价是把 667 那条卷进来——而那一条读起来是写完了的。
**宁可漏报一节，不为凑一个实拍把门槛抬进观测分布里面。**

#### 它窄在第二个条件上，而那个条件才是 605 那次真正的形状

只有长度那一半是不够的：一节写得短但材料用完了，是**写完了**。所以两个条件
必须同时成立——**正文还只有一轮的量** 且 **手上的材料还剩一大半没写进去**。
605 那次的原话是「`material_used_up` 是 false，硬件那一档知识库里有 412 条事实，
这一节用上了四条」。`material_used` 拦不住它：那一条只在**一条都没用上**时开火
（`grounding_gap` 第一行），用了四条就放行。

另外三道闸：大纲 / 打磨模式不判（跟 `material_thin` 同一条理由）、材料少于 4 条
不判（比例会变成噪声）、**最后一轮不拦**（判据短路会让这一轮没有分数，
`rank()` 返回 `(-1,-1.0)`，而最后一轮之后没有下一轮去改善它）。

#### 它是下限，不是目标

[LONG] §6：**不要为「写得更长」优化**。诊断里一个「还差多少字」都不许出现
——有一条测试逐词禁掉「还差 / 字数 / 写满 / 不少于 / 至少写」。说的只有内容：
「接着写还没写到的那一面，挑一条还没用上的材料」。跟批 13 那条
「覆盖率是诊断不是指标」同源。

#### AgentWrite 那一半**没有照抄**

论文的做法是**计划那一步让模型给每一段一个目标字数**。这一批没这么做，两条理由：
① 那是个**目标**，正是 §6 明令不要的东西；② 那个数会由模型编出来，而它一旦
进了 `Mode.checks` 就成了停机的依据——**能用代码判准的，不交给模型**。
拿过来的是它的**形态**：「够不够长」先做一次确定性判断，模型只判「够不够具体」。

### 突变验（35 条，35 条变红——**3 条第一版没抓住**）

**基线 1735 绿。** 每条单独撤掉 / 弄坏，跑前后都清 `__pycache__`。

| # | 把什么改坏 | 结果 |
|---|---|---|
| ① | `check_tap` 恒空（8.1 整条撤掉） | ✅ |
| ② | 停在半句那条撤掉 | ✅ |
| ③ | 复述门槛抬到 0.95（越过实测上界） | ✅ |
| ④ | 复述门槛压到 0.30（挪进实测分布里） | ✅ |
| ⑤ | 脚手架标题只认光秃秃的功能词（去掉「功能名：真标题」那一支） | ✅ |
| ⑥ | 示例名单里留一条提示词里已经没有的 | ✅ |
| ⑦ | bench 自己抄一份名单 | ✅ |
| ⑧ | magic-tap 端点不接体检 | ✅ |
| ⑨ | 体检改判整篇（把用户自己的正文也算进来） | ✅（**第一版没抓住**，见下） |
| ⑩ | 判了就拦（不让这段落进正文） | ✅ |
| ⑪ | `check_report` 恒空（8.2 整条撤掉） | ✅ |
| ⑫ | 时长那条不看输入，全报 | ✅ |
| ⑬ | 标题白名单里加上程序渲染的那一节 | ✅ |
| ⑭ | 锚点那条删掉 | ✅ |
| ⑮ | 撞车门槛压到 0.25（贴着实测 0.264） | ✅ |
| ⑯ | 撞车跨节也算 | ✅（**第一版没抓住**，见下） |
| ⑰ | 拉丁词不按 `/` 切开 | ✅ |
| ⑱ | 中文也查出处 | ✅ |
| ⑲ | 日报端点不接体检 | ✅ |
| ⑳ | 体检改判整份（含程序渲染的时间块） | ✅ |
| ㉑ | 体检结果不落盘（刷新就没了） | ✅ |
| ㉒ | 翻回旧的一天读不到体检结果 | ✅ |
| ㉓ | `section_budget` 恒 `None`（7.3 整条撤掉） | ✅ |
| ㉔ | 门槛抬到 700（越过实测的 667） | ✅ |
| ㉕ | 门槛压到 300（接不住任何一次实拍） | ✅ |
| ㉖ | 去掉「材料还剩一大半」那个条件 | ✅ |
| ㉗ | 大纲 / 打磨模式也拦 | ✅ |
| ㉘ | 最后一轮也拦 | ✅ |
| ㉙ | 诊断改成逼它凑字数 | ✅ |
| ㉚ | 挂到单篇模式上 | ✅ |
| ㉛ | 排到判据链最前面 | ✅ |
| ㉜ | 文档图上 `checks/` 文件数不同步 | ✅ |
| ㉝ | 文档里 check 条数不同步 | ✅ |
| ㉞ | `tap` 从目录图的 `checks/` 那一块整块摘掉 | ✅（**第一版没抓住**，见下） |
| ㉟ | 前端不显示日报的体检结果 | ✅ |

**三条第一版没抓住，三条都是用例不够**（连着十三批了）：

* **⑨** 纯函数那一侧的用例（「体检只看这一次写的那一段」）**看不见端点怎么调它**
  ——把 `check_tap(written, body.content)` 改成 `check_tap(body.content + written)`，
  函数本身的行为一个字没变，全套照绿。补了一条按源码钉调用形状的断言。
* **⑯** 「跨节不算撞车」那条用例里的一对是**我自己编的**，相似度根本没到门槛
  ——**把「按节切」整个拆掉它照样绿**。换成 09-18 真实日报里跨节最像的那一对
  （0.679，一条在「推进了什么」一条在「卡在哪」，讲的都是
  `harness-upgrade-plan.md`）之后才真的在判「跨节不算」这件事。
* **㉞** 批 19 ㉜ 刚为「词袋」这个病把断言从整张图收到 `checks/` 那一块，
  **同一个病在那一块里又长回来了**：把 `· tap（magic tap 那四条…` 整条摘掉，
  断言照样绿——因为同一行后半截的「magic tap」顺手把 `tap` 满足了。
  改成按**列表项**找（行首或 `·` 之后，后面跟空白 /「（」/「·」）。
  *收窄一个词袋的时候，要连「这个词还能从哪儿被顺手满足」一起想。*

另有一条**不是突变验、是写测试时当场撞到的**：走真 `Checks` middleware 那条
集成用例第一版拿「材料一条都没用上」当素材，而那一档由排在前面的
`material_used` 先短路——**那条用例其实一直在验 `material_used`，跟 7.3 一个字
的关系都没有**。换成「用了一条、还剩九条」（605 那次的真实形状）才对。
顺带把这条先后关系写进了 `budget.py`：这条判据真正说话的区间是
「用了一点点，远不够」。

**造语料又踩了一次批 19 ②**：十条材料第一版是同一个模板换数字，于是一句话
同时命中十条（`fact_usage` 数的是 2-gram 重合，模板本身就贡献了一大半）
——`used=10/10`，判据当场闭嘴。换成十条各说各事的真实形状才对。
*「看起来像材料」和「统计性质像材料」是两件事。*

### 闸

后端 **1695 → 1735**（+40：`test_journey_report_checks` 新建 15 条、
`test_tap_checks` 新建 13 条、`test_section_budget` 新建 11 条、
`test_directory_map` / `test_harness_modes` / `test_corpus_lineage` /
`test_quality_bench_checks` 各改了一条）；前端 52 个文件 258 条**没变**（新接的两处由既有的
`check-css-classes` / `check-api-wired` 两道脚本闸接住）。
`harness-framework.md` 跟着改了：目录图 `checks/ ×14 → ×17`、
`21 条 check → 22 条`（三处）、目录树补 `budget` / `tap` / `journey` 三块、
第 8 节表里补 `section_budget` 一行。

### 计划外发现

1. **`no_audit_voice` 的词表在真实用户笔记上有 27.8% 的误伤面，而它是会短路打分的。**
   量 8.1 的时候顺手发现：`AUDIT_PHRASES` + `LEAK_PHRASES` 在 18 篇 `origin=user`
   真实笔记上命中 **5 篇**，其中 **4 篇命中的是「知识库」这个业务词**（用户在谈
   政务知识库、众筹问答的知识库这些**产品对象**）。magic tap 这边的处置是「不做」，
   但 harness 那边这条判据**挂在 `note` / `section` 上、会短路打分并要求改写**
   ——而 `st.content` 里有一大半是用户自己写的字。这一批没动它（scope），
   写进下一步。
2. **bench 的「提示词示例」名单已经漂了一条。** 搬进 `checks/tap.py` 的时候
   逐条核对提示词，`混合形态：买断覆盖硬件，订阅覆盖运营` 在
   `app/harness/prompts/` 里**一个字都找不到**了（那一版提示词被重写过）。
   留着它等于把「模型自己想出来的一个标题」报成「提示词泄漏」。删掉之后
   34 份续写上的真阳性从 3 次变成 2 次——**少掉的那一条本来就不成立**。
   新增一道闸：名单里每一条都必须逐字出现在 `prompts/` 里。
   bench 那边原来的维护约定是一句注释（「同步往这里加一条」），**注释没拦住它**。
3. **三条「跟着被测常量一起动」的断言**，见突变验④⑮㉔㉕——第一版
   `test_写够了就不报` 写的是 `"正" * MIN_SECTION_CHARS`，门槛改成 700 / 900 /
   2000 它**都照样绿**。同一个形状在日报的撞车门槛上又出现一次（干净素材的
   同节相似度只有 0.044，门槛压到 0.25 全套一条不红）。
   **一个跟着被测常量一起变的断言，没有在断言任何东西。** 三处都补了
   「实测最像的那一对」当安全边际的钉子。

### 开工前后的 `notes` 指纹（自己核对过，不是自报）

|  | 开工前（= 批 19 收尾） | 收尾 |
|---|---|---|
| `notes` 行数 | 482 | **482** |
| `notes` `max(updated_at)` | `2026-09-16T02:53:27+00:00` | **`2026-09-16T02:53:27+00:00`** |
| 正文总字数 | 321,250 | **321,250** |
| 482 篇逐篇摘要再取一次摘要 | `47dcc54be60aa4f2` | **`47dcc54be60aa4f2`** |
| `note_revisions` 行数 | 44 | **44** |

这一批**一次跑批都没有**（零模型调用），唯一碰库的是那个只读探针，夹在
`db_guard.Watch()` 里、**命令不经过任何管道**、单独打印 `EXIT=$?`。

**`<userData>/journey/` 那边另外核对了一次**：那不是笔记库，但同样是用户数据。
两份 `report.json` 的 mtime 和字节数开工前后逐字不变
（`1789638449 / 2754`、`1789711499 / 2502`）——判据是**读**出来的，
新的 `report_notes` 要等下一次用户自己点「重写」才会写进去。

### 这一批的实际成本

**模型调用 0 次、0 token。** 阈值全部量在已经存在的真实产出上（两份日报、
18 篇真实笔记、34 份历史续写、13 条分段正文），验收靠 35 条突变验
（每条一次全量 `pytest`，墙上时间约 30 分钟，全是 CPU）。
批 19 同样形态的那一条（4.3 骨架）也是这个路子。

### 下一步

1. **`no_audit_voice` 的词表要按「业务词 vs 机制词」重新收一次**（计划外发现 1）。
   最便宜的做法是只在**这一轮新写的正文**（`st.fresh`）上判，而不是整篇——
   用户自己写的「知识库」不该被一条写作判据要求改掉。
2. **8.1 / 8.2 都还没在一次真跑里响过。** 两条都是回归探测器（真实产出上开火 0），
   这是设计，但「它在生产里到底会不会响」要等下一次有人用 magic tap / 写日报。
   两条的结果都落了盘（日报进 `report.json`），所以下一批可以直接去读。
3. **7.3 的效果量不到，除非分段模式真的跑起来。** `harness_rounds` 里它 0 轮
   ——这本身是个信号：**这个功能可能根本没人在用**，而我们为它写了 6 个维度、
   14 条判据。下一批值得先去看一眼「分段写作」的真实使用量，再决定要不要
   继续往它上面加东西。
4. 阶段 8 完了（2/2），阶段 7 剩 7.4（三档 → 二元），而 7.4 的前置是 9.2
   （judge-vs-人 一致率），9.2 的前置是 9.1（采集用户编辑）。
   **不依赖采集的只剩阶段 10（把方法固化）和阶段 11（从没审过的部件）。**

## 批 21 · `no_audit_voice` 的量程 + 阶段 10（两条）+ 阶段 11（两条）（2026-09-18）

**这一批一次模型调用都没发。** A 的两组数量在**已经存在的真实产出**上
（`scripts/audit_voice_misfire.py`，只读 + `db_guard.Watch()`），
C 的 11.3 分母量在 `.local/samples` 的 360 次 soak 跑上，
11.1 量在 `harness_rounds` 的 447 轮上。验收靠 **33 条突变验** + 全量闸。

---

### A —— `no_audit_voice` 判的是整篇，而整篇里一大半是用户自己写的字

#### 先把批 20「计划外发现 ①」那句话改对

批 20 写的是「命中 5 篇，其中 **4 篇命中的是「知识库」这个业务词**」。
**逐句读出来不是这样**（9 句原话都在 `scripts/audit_voice_misfire.py` 的输出里）：

| 笔记 | 命中 | 是什么 |
|---|---:|---|
| `309f19202309` / `715266c1fcb4` | 1 + 1 | 「该智能体还将整合全区**政务知识库**…」——**用户在谈的产品对象**，纯误伤 |
| `309f19202309` | 1 | 「当前表格没有『教室类型』字段，因此…**也不能据此确认**…」——审计腔，真的 |
| `06647b9c2031` | 2 | 「**知识库**同时记录 EVT 为 4 月 10 号启动…」——机制泄漏，真的 |
| `ecfac1f3c0aa` | 3 | 「创业第一年**尚不能证明** APP、硬件…已形成稳定闭环」——审计腔，真的 |
| `574f4ff29956` | 1 | 「…而**不能仅凭当前知识库推断**」——机制泄漏，真的 |

**业务词只有 2 篇，另外 3 篇是上一次跑写进用户笔记里的真缺陷。**
（`dimension_sensitivity_bench.AUDIT_SENTENCE` 注释里那句「原样来自
`ecfac1f3c0aa` 那篇真产出」正好对上。）

#### 所以选的是修法 ②，而且①在这份数据面前是不成立的

**①（词表按业务词 vs 机制词重收）做不成**：真正要抓的那 3 篇全是靠「知识库」
命中的，把它从 `LEAK_PHRASES` 里摘掉当场全漏——而「文件夹级实测两次把『知识库』
写进用户的笔记」正是这条判据当初被写出来的原因。①②之间没有词法边界，
**只有「这句话是谁写的」这条边界**。
（突变验 A11 把「知识库」摘出词表，当场变红。）

#### ②怎么实现的：不是 `st.fresh`，是 `content_at_start`

任务里点名的坑是对的，而仓里那套现成机制不叫 `st.fresh` 叫
`st.bag["content_at_start"]`——`loop.py` 开跑时存的那一份，注释写着
「判据看的是整篇正文，而整篇里有很多东西不是这次跑写的——用户自己写的、
上一次跑留下的。**分不清这两者的判据会去打自己没做过的事**」
（第 601 轮的占位符、第 604 轮被删掉的两张图）。

**只看 `st.fresh` 会漏掉一整类**：`revise.py` 的注释里记着实拍
——「a single replace can put audit voice straight back into the text」。
修订是**就地改写旧段落**，改出来的句子不进 `st.fresh`，却确实是这次跑写的。
「开跑时有没有」这个口径两种都接得住。
（`test_修订就地塞回来的审计腔_不在_st_fresh_里也要抓到` 钉着；
突变验 A8 把量程改成只看 `st.fresh`，当场变红。）

比法是**原样字面**。第一版按「去掉全部空白」比，理由是「轮次之间会重新排版」
——**量完发现那是想出来的**：切句本来就在 `\n` 上切、每句还 `.strip()` 过，
9 句命中经 `fix_bold_punct` 之后字面变掉的是 **0 句**。而且原样比在语义上正好对：
**跟开跑时不一样，就说明这次跑动过它**。归一化删掉了。

#### 顺带查出来一件更重的：同一张词表在落盘那一路是**直接删句子**

`hooks/mirror._scrub_and_record` 传进 `scrub_meta_sentences_v` 的是
**整篇笔记**（`st.content` 拼上这一轮的字），`revise.py` 收尾那一处也是。
也就是说用户写的「该智能体还将整合全区政务知识库…」这一句，
**每一轮续写都会被静默删掉**，连个事件都没有。
量出来跟判据那侧一模一样：18 篇里 5 篇、9 句。四个调用点一起收。

#### 误伤前后（真数字）

| | 现状 | 改后 |
|---|---:|---:|
| ① 18 篇 `origin=user` 真实笔记上，判据开火 | **5 篇 = 27.8%**，9 句 | **0 篇 0 句** |
| ④ 同 18 篇，落盘 scrub 会删掉的句子 | **5 篇 9 句** | **0 篇 0 句** |
| ② 18 篇 × 34 份续写（一次真跑的形状），命中句次 | 576 句，其中**来自用户原文 306 句 = 53.1%** | **270 句**，逐句等于「来自这一轮写的」那 270 |

②那份「34 份续写」是 `script` 血缘，按 `corpus_lineage` 的规矩**只看形状不算比例**
——所以比例只在①④上报，那两段的语料全是 `user`。

#### 真阳性没丢

四句**真实的**缺陷原文当这一轮的产出，**四句一句没漏**；同样四句挪到开跑前，**报 0 句**：

1. 「现有材料不足以说明这一判断，仍需与对应的会议记录核对后再写入。」（`AUDIT_SENTENCE`，原样来自 `ecfac1f3c0aa`）
2. 「即使面向发货的相关功能已经可用，也不能据此判断用户已经完成硬件交付。」（`grounding_rules` 注释，文件夹级 bench 实拍）
3. 「Lassie 的能力扩展仍缺少对应的版本与测试记录，因此不能据此断言…」（同上）
4. 「目前 KB 中可核对的记录集中在四月那几周。」（同一段注释里的机制泄漏原话）

②那 270 句也是真阳性侧的证据：**这一轮写出来的审计腔一句没少报。**
`soak.py` 的顾问腔基线（4~11%）这一批没动——那条走的是 `ADVICE` 正则，
跟 `AUDIT_PHRASES` 是两条线。

#### 已知代价，写进代码免得下一个人当 bug 修

**打磨模式（`polish`）什么都不写，整篇都是「开跑时就有的」，于是这条判据在那个
模式下永远不开火**——包括上面那 3 篇真缺陷。不给打磨开后门的理由：
那 3 篇和「政务知识库」那 2 篇**在这张词表眼里一模一样**，而打磨恰恰是整篇都算
「用户已有的字」的那一档，开后门等于把 27.8% 原样留在最该谨慎的模式里。
真要分开，需要的是「这句话是不是上一次跑写的」这个**新信号**
（`note_revisions` / `harness_runs` 里有线索），不是把量程再放宽一次。

**`no_placeholder` 这一批没动**：批 20 量过，它在 18 篇真实笔记上开火 **0 篇**
——分母是零，校准不出来。（`STUCK_ROUNDS` 那条band-aid 记的第 601 轮死锁
是同一个形状，但那是「卡住之后放行」，不是量程。）

---

### B —— 阶段 10.1 + 10.2

**10.1**：六条方法进 `harness-framework.md` **§20**，每条带它的真实出处
（`_COHERENCE` 那两篇全 2 分 / `[bar chart: …]` 拿 2 分 / `modes.py` 那句
"read as sentences … not as labels" / `_NON_REPETITION` 九批 2160 次实测 1.3 与
段落两两最高 0.29 / `for_run` 两个代价 / `pick_dimension` 24 格里 8 格）。
方法④下面补了一条批 21 的实拍：**同一条方法也管判据的「量程」**。
另加 **§21「这十几批定下来的规矩」**七条，每条一栏「哪次栽的」：
排夹具（批 4，33.3%→8.3%）/「真实产出」≠「用户写的」（批 6，4 条结论翻转）/
建了判据不等于用了判据（`check_citations`）/ 自报迟早报错一次（批 14）/
突变没抓住先怀疑用例不够（连着十三批）/ 上一批的纪律不能按字面抄（批 19 ㉜ → 批 20 ㉞）/
「看起来像正文」≠「统计性质像正文」（批 19 ② / 批 20）。

**10.2**：`tests/test_dimension_method_gates.py`（8 条）。

* 「判据落在本模式真有的维度上」——**改成静态**：AST 读每条判据的
  `pick_dimension` 候选名单 × 18 种运行时形态的 `dims` 逐格求交，落进
  `MECHANICS` 兜底桶的 **19 格逐格写死**。为什么不靠 `test_harness_modes`
  那条：**它是动态的**，拿一段「踩满所有毛病的正文」看开火时打翻哪一维，
  **开不了火的组合它看不见**（23 条判据 × 18 种形态，靠一段素材踩满每一格办不到）。
  两条辅闸：候选名必须真的存在（写错一个字母会**安静地**掉进兜底桶）、
  所有 `Verdict` 的维度都必须出自 `pick_dimension`（写死一个会让上面两条闸看不见它）。
  *静态那一版比动态那一版多说了一件事：`no_audit_voice` 只在**没有风格档案**时落桶。*
* 「每个模式至少有一维是这次跑有权改善的」——18 格逐格：`dims` 不许为空
  （空集合会被「所有维度都到 2」判成做完了）、没档案不许有 `style_fit`、
  打磨不许有 `beat_coverage` / `material_use`。**外加一条反向闸**：削完之后
  该留的要真的留下，否则把 `dims` 改成恒空也是绿的。

---

### C —— 阶段 11 的两条

#### 11.1 `policy.py` 的脏信号：**已经没有了，这一批改的是那段过期注释**

`TOOL_ITERS_MIN` 上面那段注释还写着「『上一轮没用工具』…预算被一路扣到了 0」，
读起来像个活着的 bug——**而批 13 的 2.5 已经把判据换成 `tool_stopped_barren`**
（`agent_loop` 里连着两次调用一条新 id 都没带回来，确定性的），
一轮都没查的不再扣预算，闸也是现成的
（`test_honestly_not_retrieving_no_longer_costs_budget`，突变验 C8 变红）。

**旧脏信号的量程量了一次**（`harness_rounds` 447 轮）：

* `tool_calls == 0` 的 **76 轮 = 17.0%**；
* 其中**事实达标**的 **48 轮 = 10.7%**——旧判据真会扣预算的正是这一格；
* 158 次跑里 **12 次**连着 ≥2 轮没用工具，**最长 3 轮**
  ——「从 2 一路扣到下界」在真实数据里走得到，不是假想。

改动：注释改成「这个 bug 已经修了，别再修一次」，并把下界为什么**照旧留着**
写清楚（它挡的是所有规则加起来把预算扣光，不只那一个信号）。

#### 11.3 `CUSTOM_DROPPED`：没消费的是**载荷键**，不是事件名

先量（`.local/samples` 的 **360 次 soak 跑**，三种模式各 120 次）：

| | 值 |
|---|---:|
| 落地的修订（`revision` 事件） | **2280** |
| `dropped` 事件 | **1032**（其中 45 条是「删掉一句元话语」的通知） |
| **被丢掉的修订占模型提出的** | **约 30.2%** |
| 至少丢过一条的跑 | **257 / 360 = 71.4%** |
| 按模式 | 大纲 **36.2%** > 续写 **28.9%** > 打磨 **23.3%** |

再找那一处「没消费」：**`revise.py` 七个发射点里有一个写的是 `{"reason": …}`**，
而前端读的是 `v.detail`（`api.ts` 那条 else-if）——于是它 `push` 进面板的是
`undefined`，**「修订调用失败，跳过这一轮修订」在界面上是一条空白项**
（实测那次 300s 超时走的正是这条路）。事件名对得上、载荷键对不上，
`test_event_contract` 原来只查名字，**一声不吭地绿着**。
更难看的是：`test_revise_middleware` 里那条断言当年**跟着实现一起写成了 `reason`**
——测试跟着被测代码一起错（批 20 计划外发现 3 同一个形状）。

**决定：显示那一半修好，统计那一半落库，不加新界面。**

* 显示：键名改成 `detail`（连 `round` 一起补齐，跟另外六处一致）。
  `test_event_contract` 加两条闸：前端**裸读**的载荷键每个发射点都得有
  （`v.notes ?? []` / `typeof v.round ===` 这种前端自己兜了底的不算「必须有」，
  免得去逼后端补一个前端本来就不指望的键）；载荷不是字典字面量的发射点**逐处登记**，
  免得下一个人把载荷换成变量、闸就安静地不查了。
* 统计：`harness_rounds` 加 **`revisions_proposed` / `revisions_dropped`** 两列。
  **两列一起加，因为只有分子说明不了任何事**：丢 3 条既可能是「提 4 条拦了 3」，
  也可能是「提 30 条成了 27」。分子算的是**提出减落地**，不是「发了几条事件」
  ——应用循环里有四条路是 `continue` 掉的、**一个事件都不发**（不是 dict / op 不认识 /
  **锚点在正文里找不到** / 改完跟原文一样），而那一档正是 11.3 那句
  「用户看不到、我们也没统计」里最看不见的一半。分母按 `max_revisions` 截断后的
  那些算，超额的那几条根本没被裁决过，算进去会把「守卫拦掉的比例」冲淡成
  「模型话多的比例」。
* **那四条静默路要不要也发事件，等这两列攒出数再定**——没有分母就拍界面，
  是「拿一次抽样当基线」那条老账。

---

### 突变验（33 条，33 条变红——**3 条第一版没抓住**）

**基线 1763 绿。** 每条单独撤掉 / 弄坏，跑前后都清 `__pycache__`。

| # | 把什么改坏 | 结果 |
|---|---|---|
| A1 | `no_audit_voice` 又去判整篇 | ✅ |
| A2 | 递给修订的审计腔又是整篇 | ✅ |
| A3 | 修订后的 scrub 又删整篇 | ✅ |
| A4 | 续写落盘的 scrub 又删整篇 | ✅ |
| A5 | `_seen` 恒 True（全放过 = 真阳性全漏） | ✅ |
| A6 | `_seen` 恒 False（量程等于没收） | ✅ |
| A7 | `_seen` 只认开头那一句（`in` → `startswith`） | ✅（**替换掉的那条第一版没抓住**，见下） |
| A7b | `_seen` 反着比（`before in s`） | ✅ |
| A8 | 量程改成只看 `st.fresh` | ✅ |
| A9 | `loop.py` 不再存 `content_at_start` | ✅ |
| A10 | 只收判据不收落盘 scrub | ✅ |
| A11 | 改走修法①：把「知识库」摘出词表 | ✅ |
| A12 | 真阳性名单换成自己编的句子 | ✅ |
| B1 | 候选维度名写错一个字母 | ✅ |
| B2 | 没风格档案也挂 `style_fit` | ✅ |
| B3 | 打磨模式也挂 `beat_coverage` | ✅ |
| B4 | `for_run` 削成空集合 | ✅ |
| B5 | 有一处 `Verdict` 把维度名写死 | ✅ |
| B6 | 六条方法那一节从文档里整块删掉 | ✅（**第一版没抓住**） |
| B7 | 文档里少掉一条方法 | ✅（**第一版没抓住**） |
| B8 | 兜底桶名单少写一格 | ✅ |
| B9 | §21 少掉一条规矩 | ✅ |
| B10 | 文档指到一条不存在的闸 | ✅ |
| B11 | §20 说有闸、那条闸却被删掉 | ✅ |
| C1 | 载荷键改回 `reason` | ✅ |
| C2 | 前端改读 `v.reason` | ✅ |
| C3 | `Ledger` 不记 `revisions_dropped` | ✅ |
| C4 | 库里不加那两列 | ✅ |
| C5 | 丢弃数改成「发了几条事件」 | ✅ |
| C6 | 分母不按 `max_revisions` 截断 | ✅ |
| C7 | 不重置那两个计数 | ✅ |
| C8 | `policy` 换回「上一轮没用工具」那个脏信号 | ✅ |
| C9 | 事件发射点的载荷换成一个变量 | ✅ |

**三条第一版没抓住，三条都是用例不够**（连着十四批了）：

* **A7（旧）**「`_seen` 不做空白归一」照绿。查下去发现**用例根本没在验归一化**：
  我编的「重新排版」排的全是**句子之外**的空行，而切句本来就在 `\n` 上切、
  每句还 `.strip()` 过——**把归一化整个删掉它照样绿**（批 20 ⑯ 同一个形状）。
  于是去量了一次：9 句命中经 `fix_bold_punct` 之后字面变掉的是 0 句。
  **归一化是想出来的，不是观测到的，删掉**；测试改成钉它真在钉的那条性质，
  另补一条反向的（句子被改过一个字就不再算「开跑时就有的」），
  突变验换成 `in → startswith` / 反向比较两条。
* **B6 / B7** 把 §20 整节删掉、或少写一条方法，全套 1759 条照绿。
  **也就是说 10.1 交付的是一段没人盯着的文字**——而 10.1 的全部理由正是
  「这六条只活在注释里，下一个人未必读得到」。挪个地方要是照样没人盯着，
  等于把注释搬进了另一份注释。补了三条闸（六条方法在不在、七条规矩在不在、
  文档说「有闸钉着」那两个名字必须真的指得到）。
  *补完立刻又被咬一次*：B9「§21 少掉一条规矩」照绿——因为
  「建了判据不等于用了判据」这句话**第 18 节里早就有一处**，全篇 `in` 顺手被满足。
  闸改成**只取这一节的正文**再查。**一个在别处顺手被满足的断言，没有在断言任何东西**
  （批 20 ㉞ 同一个形状，第三次了）。

### 闸

后端 **1735 → 1763**（+28）：
`test_audit_voice_scope` 新建 13 条、`test_dimension_method_gates` 新建 8 条、
`test_event_contract` +2、`test_revise_middleware` +4、
`test_scripts_import` +1（新探针脚本自动被参数化进去）；
`test_note_harness` / `test_revise_middleware` 各改了一条断言（两条都是原来写错的）。
前端 **52 个文件 258 条没变**。
`harness-framework.md` 新增 §20 / §21，原「20. 变更记录」顺延为 §22；
Mode / 工具 / check / middleware 四个数一个没动，`test_doc_counts` 照绿。

### 计划外发现

1. **批 20「计划外发现 ①」的归因是错的。** 「4 篇命中的是业务词」——逐句读只有
   **2 篇**是业务词，另外 3 篇是**上一次跑写进用户笔记里的真缺陷**。
   结论没变（还是该收量程），但**如果按那句话去做修法①，会把真正要抓的那 3 篇全漏掉**。
   *顺手量出来的数，下一批要当分母用之前得先逐条读一遍。*
2. **同一张词表在落盘那一路是直接删句子，而且删的是整篇。**
   `hooks/mirror._scrub_and_record` / `revise.py` 收尾两处传的都是整篇正文，
   实测会删掉 5 篇真实笔记里的 9 句——**其中两句是用户自己写的产品描述，
   而且连事件都不发**。判据那侧至少还会把句子指给用户看，这一侧是无声的。
   这一批一起收了。
3. **一条测试跟着被测代码一起错。** `test_修订调用挂了只赔上这一轮的修订` 断言的是
   `d["reason"]`，而前端读 `v.detail`——测试和实现用的是同一个错键，
   **两边一致，所以两边都错得很安静**。
   *「测试跟着实现写」这件事，在契约的两端不在同一个仓时格外贵。*
4. **`test_harness_modes` 那条「判据落在真有的维度上」是动态的，覆盖不全。**
   静态重算之后多说了一件事：`no_audit_voice` 只在**没有风格档案**时落兜底桶，
   有档案时它打 `style_fit`。动态那条按 (模式, 判据) 收敛，看不见这个区别。

### 开工前后的 `notes` 指纹（自己核对过，不是自报）

|  | 开工前（= 批 20 收尾） | 收尾 |
|---|---|---|
| `notes` 行数 | 482 | **482** |
| `notes` `max(updated_at)` | `2026-09-16T02:53:27+00:00` | **`2026-09-16T02:53:27+00:00`** |
| 正文总字数 | 321,250 | **321,250** |
| 482 篇逐篇摘要再取一次摘要 | `47dcc54be60aa4f2` | **`47dcc54be60aa4f2`** |
| `note_revisions` 行数 | 44 | **44** |

这一批**一次跑批都没有**（零模型调用），唯一碰库的两个只读探针都夹在
`db_guard.Watch()` 里、**命令不经过任何管道**、单独打印 `EXIT=$?`。

### 这一批的实际成本

**模型调用 0 次、0 token。** 数量全部量在已经存在的真实产出上
（18 篇 `origin=user` 真实笔记 × 34 份历史续写、360 次 soak 跑的事件计数、
`harness_rounds` 447 轮），验收靠 33 条突变验（每条一次全量 `pytest -x`，
墙上时间约 20 分钟，全是 CPU）。

### 下一步

1. **打磨模式现在对「上一次跑留下的审计腔」完全失明**（A 的已知代价）。
   要治它需要的是新信号「这句话是不是上一次跑写的」——`note_revisions` /
   `harness_runs` 里有线索，但那是一件独立的事，别拿放宽量程去凑。
2. **`revisions_proposed` / `revisions_dropped` 刚落库，一行数据都还没有。**
   下一批可以直接去读：如果「静默 `continue`」那四条路占了大头（尤其锚点找不到），
   那该补的是事件不是界面；如果大头是守卫拦下的，30.2% 本身就值得去看守卫是不是太狠。
3. **10.3（criteria drift 的重新校准入口）是阶段 10 最后一条**，它要的是
   「判据依赖当初看到的那批产出」这件事的复查机制——批 21 的 A 正好是一次手工的
   criteria drift 复查（`LEAK_PHRASES` 当初是对着 harness 自己的产出定的，
   而今天它要在用户自己写的字上跑）。**下一批做 10.3 时，把 A 当成那个流程的第一例。**
4. 阶段 11 还剩 5 条，其中 11.2（`rank()` 标量折叠）有第 602 轮的实拍，
   是剩下几条里证据最硬的一条。

---

## 批 22 · 阶段 11 剩下的五条（11.2 / 11.4 / 11.5 / 11.6 / 11.7）（2026-09-18）

**这一批一次模型调用都没发。** 11.2 的数量在 `harness_rounds` 的 447 轮 /
158 次跑上（`scripts/best_of_pareto_probe.py`，只读 + `db_guard.Watch()`），
11.4 的数量在 `harness_runs` 的 103 行上，11.5 / 11.6 / 11.7 是三份并行的只读
代码审计。验收靠 **29 条突变验** + 全量闸。

**五条的处置：11.2 折叠本身量完不做、改了它漏掉的那一半；11.4 找到四处
「只挡住一半」、修了四处；11.5 / 11.6 / 11.7 从没审过，审完各修一条最硬的、
其余写清楚为什么不改。**

---

### 11.2 —— 折叠**没有**挑错，挑错的是它旁边那条停机规则

#### 先量（`scripts/best_of_pareto_probe.py`，把 158 次跑逐跑重放）

| 段 | 数 |
|---|---:|
| 多轮跑 | 123（单轮 35） |
| 其中**可比**（≥2 个真打过分、维度集合相同的轮次） | **51** |
| ① `rank()` 挑的那一轮被同跑里别的轮次 **Pareto 支配** | **0 次** |
| ② 前沿只有一个成员 | 31 |
| ② 前沿多成员、`rank()` 挑的**正是**最靠后的那个前沿成员 | 16 |
| ② 前沿多成员、`rank()` 挑的不是最靠后那个 | **4** |
| ③ 全程判据短路（`rank()` 一律 `(0,0.0)`）的多轮跑 | 36 |
| ③ 其中 best 落在**最后一轮** | **36 / 36** |
| ④ 「武装了且这一轮排名更低」 | **2 次**，其中**覆盖反转 1 次** |

**结论一：`best_of` 的标量折叠不改。** 三条依据：

* **0/51**——折叠从来没挑中一个「每一维都不更好」的轮次；
* 那 4 次「不是最靠后的前沿成员」里 **3 次是同一个形状**（后一轮把某个覆盖
  维度写达标，代价是别的维度掉一档），那件事由下面结论二那一行治，不需要换排序；
* **结构性的一条**：GEPA 的前沿回答的是「下一步该变异哪个候选」，可以同时留着
  好几个；我们要回答的是「这一次交哪一份正文给用户」，**只能交一份**——任何
  一条「交哪个」的规则都会把前沿重新折回一个标量。换成前沿只是把折叠挪个地方
  写，还多一份状态要进快照。

**第 602 轮那个实拍（四轮全打回、best 钉在第 1 轮）的另一半已经好了**：
`>=`（平手归后来者）让全程判据短路的 **36 次跑 36 次**把 best 落在最后一轮。
任务里点名的「那只治了平手」是对的——治不了的那一半在下面。

#### 结论二：`_regressed` 的覆盖守卫只挡住一半（这是一处「只挡住一半」，也是 11.4 的同族）

第 607 轮教过一次：**这一轮**还有覆盖维度没达标时，分数波动是干活的代价，
不算退步（`_coverage_unmet`）。**同一件事的另一半没人挡**：
*最好那一轮之所以排名高，正因为它没写够*——短、干净、不重复的残篇在 `rank()`
眼里是一份好产出（§20① 记着的第 605 轮：三节各跑一轮全 2 分判完成，交出来
620 / 434 / 429 字）。

实拍（全表唯一一次真的按 `regressed` 收工的跑，`2d64b594db9b` /
`note:309f19202309`）：

| 轮 | 分数向量 | `rank()` | 正文 |
|---|---|---|---:|
| 1 | spine 2 · **beat_coverage 1** · non_rep 2 · fact 2 · coh 2 · material 2 | (5, 1.83) | 537 字 |
| 2 | spine 2 · **beat_coverage 2** · non_rep 1 · fact 2 · coh 1 · material 2 | (4, 1.67) | 1092 字 |

第 2 轮**刚把 `beat_coverage` 从 1 写到 2**，代价是 `non_repetition` /
`coherence` 各掉一档 → 排名更低 → `regressed` → **交出去的是第 1 轮的 537 字，
第 2 轮的 1092 字整个扔掉**。

改法：`BestOf` 记下最好那轮**当时写够了没有**（`st.bag["best_coverage_unmet"]`，
进快照），`_regressed` 多一条守卫。**记在 bag 不塞进 `st.best` 的元组**：
`_regressed` 拿 `best_rank[0]` 当「差几个维度」在用，元组一变形那行就得跟着改，
而它跟这件事没关系。`COVERAGE_DIMS` 和判断搬到 `state.py`（两处要问同一个
问题，写两份会飘），`loop.py` 照旧 re-export。

**分母要老实说**：武装条件全表只走到 **2 次**，覆盖反转 **1 次**。
这 1 次是真交出去了（有 `stopped=regressed` 为证），不是推出来的；
但「158 次跑里 1 次」就是它的量级，不要当成高频。
另外 `harness_rounds` 里的跑绝大多数是测量脚本触发的，按 `corpus_lineage` 的
规矩**只看形状不算生产发生率**。

---

### 11.4 —— 「同一件事只挡住一半」，成体系过了一遍，找到四处

批 3 留的原话是「同类的大概率不止一处，归 11.4」。**四处，修了四处。**

#### ① `History` 把「跑满轮数」整类跑丢掉了（**最重的一处**）

`middleware/history.py` 开头原来是 `if not st.ev: return`，而 `st.ev is None`
在 `after_run` 有**两个**互不相干的含义：

* 「打分调用失败了」——批 3 修的就是这一半（`_regressed` 现在会放过它）；
* **「循环在每轮末尾把 `st.ev` 清空了，而这一轮没触发任何停机条件，`for` 正常
  跑完进了 `else`」——那就是 `max_rounds`。**

实测：

| | 值 |
|---|---:|
| `harness_rounds` 158 次跑里**跑满 `max_rounds`** | **17 次 = 10.8%** |
| `harness_runs` 里 `stopped='max_rounds'` 的行 | **0** |
| `analysis` 模式：跑满 3 轮的跑 / 历史里的行 | **6 / 1**（那 1 行是唯一一次靠 `tools_ran_dry` 停的） |
| `eda` 模式：跑满 3 轮的跑 / 历史里的行 | **6 / 0** |

`stopped` 这一列是计划 0.3 专门为了把「跑满轮数」从 `continue` 里拆出来才加的
——**它想记的那个值结构上记不到**。方向更难看：跑满轮数 = 从头到尾没达标，
**那正是下一次跑最该学的一类**（`policy.from_history` 只读 `weak_dimensions`），
却恰好是唯一学不到的一类。

#### ② 同一个文件：判据短路那一轮的**伪造分数**被当成这次跑的终评

判据命中时 `middleware/checks.py` 伪造一份只有一个维度、分数 0 的 `Evaluation`。
`Ledger`（不记进 `score_vectors`）、`Repair`（开头 `skip_judge` 分支）、
`loop._regressed` 三处都明写着排除它，**只有 `History` 照单全收**。

| | 值 |
|---|---:|
| `harness_runs` 103 行里 `final_scores` 只有一维且为 0 | **14 行 = 13.6%** |
| 落点 | `factual_grounding` 11 · `non_repetition` 2 · `numbers_from_tools` 1 |
| 15 个可比 key 里会推出 `chronic` 维度的 | 5，其中 **1 个**靠伪造分数撑起来 |

改法：终评取**最后一份真打出来的向量**——`st.ev` 真打过分就用它，否则退回
`Ledger` 的 `score_vectors[-1]`（那份清单天然只收真打过分的轮次），一份都没有
就给空的。**没判过就是没判过，不编一个出来。** 另外加一条窄的：
`st.round < 1`（`precheck` 挡下来、循环体一次都没进）不记——那一档没有任何
关于写作的信息，记下来只在 `from_history` 的分母里加噪声。

#### ③ `snapshot.dropped_keys` 建了没用（**「建了判据不等于用了判据」第三次**）

`snapshot.py` 的模块注释写着「编不进 JSON 的**吵闹地丢**：快照记下它丢了什么，
于是一次少了某个能力的恢复是看得见的，而不是神秘的」——而 `dropped_keys()`
**在这一批之前唯一的调用方是它自己的单测**。改法：恢复那条 SSE 在跑循环之前
先发一条 `warning`（前端 `onWarning` 已经在接），不拒绝恢复——丢的是某个
middleware 的私有草稿，恢复本身仍然是对的，只是得有人知道。

#### ④ `rails_off=("save",)` 那个形状：**已经在批 16 收干净了，这一批复核过**

`middleware/save.persist` 是唯一出口且**出口自己认 `rails_off`**，
`revise.py` 收尾那处走的也是它（全仓 `store.update_note` 在 `app/harness/` 下
只剩 `save.py` 一处）。**不用再改**。

---

### 11.5 `agent_loop` 的工具循环 —— 批 13 那条的**同型另一个入口**，是真 bug

任务点名要先读批 13 那段（停机那一发会把同一条 assistant 消息里剩下的
`tool_call` 整个丢掉 → `msgs + extra` 喂回去直接 400）。读完去找同型的，**找到了**：

**`kept == []` 的那一发。** 第 2 轮起深度门（`_cap_calls` 的 `iteration >= 1`）
把纯广度的调用整批丢掉；模型这一轮**只发广度工具**时 `kept` 是空的，而原来的
代码照样把 `{"tool_calls": []}` 这条 assistant 消息 append 进 `convo` 和 `extra`。
接口对空数组同样是硬校验（`Invalid 'messages[N].tool_calls': empty array`）。

* **走得到吗**：`DEPTH_TOOLS` 上面那段注释记着的实测原话是
  **「4 次真实采样的工具循环全部撞上限，模型每轮都在广度上把预算花光——并行发
  3-5 个 `search_memory`」**。也就是说这个场景是观测到的常态，不是边角料。
* **后果两档**：① 这条消息进 `convo`，下一次调用当场 400，被 `except` 吞成
  「没查」，第 1 轮查到的全丢、还白烧一次 20-90 秒的调用；② 要是它落在最后一轮，
  就原样返回给调用方，`hooks/block.prepare` 把 `msgs + extra` 喂给补图那一轮，
  同样 400、同样被吞——**图画不出来而且一点痕迹都没有**。
* 修法是 `break` 不是 `continue`：`convo` 和 `spec` 都没变，再问一次模型只会
  拿回同一批广度调用。

**同一批还修了两条同族的：**

* **中途挂了不该连配平的消息一起扔。** 原来是 `return [], trace`，而那一半跟
  `trace` 对不上——`trace.calls` 非空、`trace.used` 为真，消息列表却是空的。
  `hooks/note` / `hooks/section` 用的是 `trace.as_facts()` 所以从没露馅，
  **`hooks/block` 用的正是 `extra`**：补图那一轮的「上面已经查到的数据里，挑最
  值得看的画成图」指向一个空的「上面」。交出去是安全的——异常发生在把这一轮的
  assistant 消息 append **之前**。
* **`hooks/block` 合并第二次工具循环的轨迹时手抄了两个字段、漏掉四个**
  （`stopped_barren` / `error` / `truncated` / `barren_calls`）。各自都有读者：
  `middleware/runtime` 把 `stopped_barren` 喂给 `policy.adjust`，那是「工具预算
  -1」唯一的判据（计划 2.5）；`error` 更直接，`hooks/block` 本来就没有
  `trace.error and not facts` 的降级。改成 `ToolTrace.merge()`，**并且闸钉在
  调用点**——把那一行换回手抄两行，`merge` 自己的逐字段闸照样全绿
  （§21「一个在别处顺手被满足的断言，没有在断言任何东西」）。

**审过但这一批不改的**：`hooks/block` 没有 `note` / `section` 那种
`trace.error and not facts` 的关键词检索兜底。**依据是分母为 0**：`trace.error`
从来没落过库、没发过事件，「它多久发生一次」现在答不出来。要动它得先让它可见
（下一步①）。

---

### 11.6 `skills` 那 447 行 —— 一条真 bug，其余**分母是 0**

**修了一条**：`load_skill` 的加载额度数错了东西。`skill_bodies` 在
`middleware/skills` 的第一轮就已经被 **scope 注入**的正文填过了（13 条内置里
`verify` / `edit` / `plan_generate` 三个 scope 各注入 2 条），而额度原来数的正是
那个 list 的长度。于是模型**一条都没加载就只剩 1 次额度**；哪天某个 scope 配到
3 条，`load_skill` 会**永久返回拒绝**，而拒绝的原话是「Already loaded 3 skills」
——**告诉模型它做过一件它没做过的事**，那是最坏的一种反馈。
（原来那条上限用例的 fixture 一条 scope 都没配，**正好绕开了这个交互**，
所以一直是绿的——§21「突变没被抓住先怀疑用例不够」的又一例。）

**审出来但这一批明确不改的，各自的依据：**

| 发现 | 为什么不改 |
|---|---|
| **沙箱整块在生产里不可达**：`run_skill_script` 注册在 `skill_script` 组，而没有任何 Mode 声明这个组，`RuntimePolicy.extra_tool_groups` 全仓没有一处赋过值；同时没有任何 API 能把 `sandbox` 配成 `compute`/`files`（`install()` 恒写 `"none"`，库里现存行全是 `none`） | 这是**一整块能力要不要接上**的决定，不是 bug 修复。接上之前它的几个洞（macOS 上超时只杀直接子进程、`OUTPUT_BYTES` 只数 scratch 顶层文件、stdout 先全量读进后端进程再截断）都触发不了；接上的同一个改动里必须一起修 |
| `block_write` 这个 scope **一条内置技能都挂不上**（四个块模式声明了它，`BUILTIN_SCOPES` 13 条里没有一条含它） | 修它等于**写一条新的内置技能正文**，那是内容不是判据。记在这儿，等有人真要给块模式配技能时一起做 |
| 出厂状态下技能菜单恒空（`listed` 的条件是「没有任何 scopes」，而 13 条内置全有 scopes） | 设计如此。但它意味着**「模型选技能选得准不准」这个问题在默认安装上根本没有发生过** |
| `MAX_BODY_CHARS = 20_000`，而实测单条 body 最大 **236 字符**、单个 scope 注入最多 **414 字符**（`verify`）——上限是真实用量的 **85 倍** | 阈值拍得宽不等于有害；要收得先有「上下文撑不撑得住」的数，现在没有 |
| 创建技能会静默覆盖同名技能；编辑技能会把沙箱等级重置成 `none` | 后者在沙箱不可达之前无实害；两条都归到「接上沙箱那一笔」 |
| `max_calls_per_round` 实际是 per-iteration（`_cap_calls` 每次迭代新建计数），于是 `read_skill_ref` 实际是 6 次/轮 | **影响的是全部工具的预算语义**，不只技能。改它要先量「今天实际发生几次」，而那个数现在也没有 |

**分母**：`harness_rounds` / `llm_usage` **没有任何技能维度的列**，
6 份探针日志 `grep -c load_skill` 全是 0，`skill_config` 表里**没有一个用户改过
任何 scope 配置**。「技能选得准不准 / 披露预算够不够」今天答不出来。

---

### 11.7 `replan_rules` —— 约束的形状是对的，但**整个机制可能一直在空转**

**修了一条**（窄、代码判、不依赖任何没有的数）：
`middleware/replan` 原来判「改没改」看的是 `changes` 非空，而 `changes` 是
**给人看的变更记录**，里面也包含被守卫丢掉的那几条（「还有 N 条新增被丢掉：
节拍数量不能净增…」）。模型只返回 `add` 是三种操作里最好想的一种，这时
`room = 0`、一条都加不进去、`new_beats` 跟 `beats` **逐字相同**，于是
**烧掉 1/2 的重规划预算，并向前端播一条「骨架变了」**，而骨架一个字没变。
判据改成问 `new_beats`。

**审出来但这一批不改的，各自的依据：**

| 发现 | 为什么不改 |
|---|---|
| **头号**：`score_context` 在 `routers/note_harness` 开跑前算一次、把 beats 折成**字符串**，重规划改的是 `st.bag["beats"]`，**没有任何 middleware 刷新 `score_context`**——于是改完节拍，判 `beat_coverage` 的还是旧节拍，写作者和判分者此后对着两份不同的目标工作 | 推理是硬的，但**分子不可观测**（见下）。而且修它要动「一次跑里 `score_context` 什么时候重算」，那是接缝层的结构改动，值得单独一批，先把观测补上 |
| 重规划产物**不过 `check_skeleton`**（`checks/skeleton.py` 五条、阈值全在 20 份真实骨架上量过），而 `prompts/note.py` 把同两件事改成散文交给模型自觉——违反「能用代码判准的，不交给模型」 | 形状上该改，但它是个**拦不拦**的决定（4.3 那五条的形态是「判了不拦着落库」），而这里没有任何数说明拦下来会误伤几次。跟上一条一起做 |
| drop 的下界是 1，而 `checks/skeleton.MIN_BEATS = 3`：两次 drop 能把 3 条砍到 1 条，**而砍节拍恰好是让 `beat_coverage` 达标最省事的办法** | 同上 |
| rewrite 出来的节拍**不封顶**（初始骨架有 `store.clamp_skeleton` 的 60 字）、**不去重**（`add` 去重、`rewrite` 不去重） | 同上 |
| 模型返回的不是 list（包一层 `{"ops": …}`）时**零事件静默 return**，且不消耗预算，下一轮继续烧调用 | 同上；这条的修法是发事件，而发事件之前先得有落库 |
| 前端 `onReplan` **全仓没有一处传 handler**：`replan_rules` 里「变更记录直接进 SSE，用户必须看得见改了什么」在生产里是假的 | 前端改动，且跟「补哪些观测」是同一笔 |

**分母（这一条才是 11.7 最重要的结论）**：
触发条件在真库里**确实开过火**——对 365 个 `note` 轮次重放 `should_replan`：
打过 `beat_coverage` 的 125 轮里不达标 29 轮，命中触发一（卡 2 轮）**1 轮**、
命中触发二（`facts_new > 0`）**17 轮**，涉及 **16 次跑**。
但**「重规划真的把某条节拍改掉了」这件事，在 `harness_rounds`（没有对应列）、
`harness_snapshots`（0 行）、探针日志、样本报告（renderer 不认这个事件）里
一处记录都没有**。触发器的分母 ≈ 17 轮，**应用成功的分子 = 不可观测**。
在这个状态下讨论「约束够不够」的前提不成立：上面那条 `score_context` 的 bug
意味着即使它每次都改成功，效果也等于 0，而**没有任何仪表会告诉我们这件事**。

---

### 突变验（29 条，29 条变红——**1 条第一版没抓住**）

**基线 1763 绿。** 每条单独改坏 / 撤掉，跑前后都清 `__pycache__`。

| # | 把什么改坏 | 结果 |
|---|---|---|
| A1 | 去掉 `_regressed` 的 best 覆盖守卫 | ✅ |
| A2 | `BestOf` 不记「best 那轮写够了没有」 | ✅ |
| A3 | 那个标记改成记「这一轮」而不是「best 那一轮」 | ✅ |
| A4 | 守卫改成无条件放过（`regressed` 永不开火） | ✅ |
| A5 | `coverage_unmet` 恒 False | ✅ |
| A6 | `coverage_unmet` 恒 True | ✅ |
| A7 | 探针脚本的覆盖维度名单抄错一个字母 | ✅ |
| A8 | 探针的「平手归后来者」改成归先到者 | ✅ |
| A9 | 探针的 `rank` 不认「没打上分垫底」 | ✅ |
| B1 | `History` 又靠 `st.ev` 决定记不记 | ✅ |
| B2 | 伪造分数又当终评 | ✅ |
| B3 | 一律读 `score_vectors`，不看这一轮真打的分 | ✅ |
| B4 | 一轮没跑过的也记 | ✅ |
| B5 | 暂停等处置的也记 | ✅ |
| B6 | 不记 `stopped` | ✅ |
| B7 | `weak_dimensions` 把达标的也算进去 | ✅ |
| C1 | 恢复时不再报丢掉的 bag 键 | ✅ |
| C2 | `dropped_keys` 恒空 | ✅ |
| D1 | 去掉「整轮被深度门丢光就收工」 | ✅ |
| D2 | 那一发改成 `continue`（会再烧一次调用） | ✅ |
| D3 | 中途挂了又把配平的消息一起扔掉 | ✅ |
| D4 | `hooks/block` 又手抄两个字段 | ✅（**第一版没抓住**，见下） |
| D5 | `merge` 漏掉 `stopped_barren` | ✅ |
| D6 | `merge` 漏掉 `error` | ✅ |
| D7 | `ToolTrace` 加了个字段但 `merge` 没跟上 | ✅ |
| E1 | 加载额度又数「上下文里一共几条」 | ✅ |
| E2 | 模型加载过的不计数（额度等于没有） | ✅ |
| F1 | 又拿 `changes` 判「改没改」 | ✅ |
| F2 | 无条件不改骨架 | ✅ |

**D4 第一版没抓住，又是用例不够**（连着十五批了）：`ToolTrace.merge` 的逐字段
闸是对**纯函数那一侧**的，它看不见调用点怎么调它——把 `trace.merge(trace2)`
换回手抄两行，六个字段的闸一条都不会红（§21 里那条「纯函数那一侧的用例看不见
端点怎么调它」的第三例）。补了一条**钉在调用点**的：`hooks/block.prepare` 真跑
两轮，第二轮的 `stopped_barren` / `error` / `truncated` / `barren_calls` 必须折回主
`trace`。

### 闸

后端 **1763 → 1785**（+22）：`test_best_of_pareto` 新建 6 条、
`test_run_history` 新建 7 条、`test_tools` +3、`test_harness_resume` +1、
`test_block_harness` +1、`test_skill_loop` +1、`test_policy_wiring` +2、
`test_dimension_method_gates` 的规矩名单 +1、`test_scripts_import` +1
（新探针脚本自动被参数化进去）；`test_harness_resume` 改了一条断言
（那条用例的 State 从来没设过 `round`，而「一轮都没跑过的不记」是新加的窄判据）。
前端 **52 个文件 258 条没变**。
`harness-framework.md` §21 加第 8 条规矩（Mode / 工具 / check / middleware
四个数一个没动，`test_doc_counts` 照绿）。

### 计划外发现

1. **`stopped` 这一列从加进来那天起就记不到它最想记的那个值。** 计划 0.3
   的原话是「54% 的跑记成 `continue`，而『跑满轮数』『连着几轮没动静』『比最好
   那轮更差主动停』三件事该采取的行动完全不同」——而 `max_rounds` 这一档
   结构上到不了这一列。**一个为了区分三种失败而加的字段，漏掉的正是最常见的
   那一种。** 落库加了字段之后要跟着问一句「它的每个取值都真的写得进去吗」。
2. **`harness_runs` 里 `stopped='regressed'` 全表只有 1 行，而那 1 行正好就是
   11.2 那个形状。** 分母小得可怜，但分子是 1/1。这两件事要一起说：
   证据很硬（真交了 537 字的残篇），量级很小（158 次跑里 1 次）。
3. **`hooks/block` 是三个 `prepare` 里唯一没有 `trace.error` 兜底的那个，
   而它恰好也是唯一一个真的消费 `extra` 的。** 两件事叠在一起，工具阶段挂掉
   在块模式下是**完全无声**的：没有兜底、没有事件、没有落库。
4. **`middleware/replan` 的模块注释指向一个不存在的文件**（「The convergence
   guards live in `app/replan.py`」，实际在 `app/harness/replan_rules.py`）。
   顺手改了。
5. **`scripts/dump_prompts.py` 是坏的**：7 处调用 `store.enabled_skills_for_scope`，
   而 `test_architecture_claims` 断言的正是这个函数必须从 `app/` 里消失。
   `test_scripts_import` 只 import 不执行，所以一直没暴露。**没改**（它不在这一批
   的范围里），但记在这儿：*「只 import 不执行」的闸，挡不住已经死掉的调用。*

### 开工前后的 `notes` 指纹（自己核对过，不是自报）

|  | 开工前（= 批 21 收尾） | 收尾 |
|---|---|---|
| `notes` 行数 | 482 | **482** |
| `notes` `max(updated_at)` | `2026-09-16T02:53:27+00:00` | **`2026-09-16T02:53:27+00:00`** |
| 正文总字数 | 321,250 | **321,250** |
| 482 篇逐篇摘要再取一次摘要 | `47dcc54be60aa4f2` | **`47dcc54be60aa4f2`** |
| `note_revisions` 行数 | 44 | **44** |

这一批**一次跑批都没有**（零模型调用），唯一碰库的探针
（`scripts/best_of_pareto_probe.py`）只读、夹在 `db_guard.Watch()` 里、
**命令不经过任何管道**、单独打印 `EXIT=$?`。

### 这一批的实际成本

**模型调用 0 次、0 token。** 数量全部量在已经存在的落库数据上
（`harness_rounds` 447 轮 / 158 次跑、`harness_runs` 103 行），
11.5 / 11.6 / 11.7 是三份**并行的只读代码审计**（三个 agent 同时跑，
合计约 32 万 token、128 次工具调用、墙上时间约 4 分钟）。
验收靠 29 条突变验（每条一次targeted `pytest -x`）+ 两次全量闸。

### 下一步

1. **`trace.error` 得先可见再谈兜底。** 它今天既不落库也不发事件，
   所以「工具循环整个挂掉」的频率答不出来——而 `hooks/block` 那一档是完全
   无声的。最便宜的一步跟 11.3 一样：`harness_rounds` 加一列（或者复用
   `Provenance` 那条已经在发的 `round` 载荷多一个键），攒出分母再决定。
2. **重规划要么补观测要么先关掉。** 触发器一轮都没少开火（17 轮 / 16 次跑），
   而「改成功了没有、改完有没有用」一处记录都没有，同时有一条硬 bug
   （`score_context` 不刷新）意味着**即使每次都改成功，效果也是 0**。
   下一批做它的时候顺序是：先落库两个数（提出 / 应用），再修 `score_context`，
   最后才谈约束够不够。
3. **`revisions_proposed` / `revisions_dropped` 还是一行数据都没有**（批 21
   下一步②原样留着）——这一批同样没跑任何真跑。要读它得先跑一次真跑。
4. **10.3（criteria drift 的重新校准入口）是阶段 10 最后一条**，仍然没做。
5. 阶段 11 的七条到这一批全部处置完（做 / 明确不做 / 审完记账）。
   剩下的大头是阶段 9（ground truth 采集，**越早越值钱**）和阶段 12（用户这一端）。

---

## 批 23 · 阶段 9（9.1 / 9.3）+ 阶段 12（12.2 / 12.3 / 12.4）（2026-09-18）

**这一批有真跑。** 5 次 note 模式的真跑（`scripts/revision_ledger_probe.py`，
真实笔记 `309f19202309`、`rails_off=("save",)`、整趟夹在 `db_guard.Watch()` 里），
**59 次模型调用、864,835 token**——为的是 12.2 那两列从批 21 加进来到现在
**一行数据都没有**。12.3 的上限量在已经存在的落库数据上
（`scripts/run_cost_probe.py`，只读）。验收靠 **34 条突变验** + 全量闸。

**四条的处置：9.1 采集开张（今天 0 行，越早越值钱）、9.3 只报不回滚、
12.2 真跑出数并顺手把一条词法闸换成真的、12.3 第一次有上限。
外加 12.4（9.3 的界面那一半）——不接前端的话 9.3 就是一条没人听的事件。**

---

### 9.1 —— 这个回路唯一可能的 ground truth，先把口子开出来

[MECH] §5 的判断是整个回路**没有 ground truth**：没有任何证据表明「五维全
2 分」等于「用户愿意留下这篇笔记」，而 Goodhart 已经发生过一次
（`middleware/best_of.py` 开头记着：第 3 轮为了讨好打分器加了一张单值柱状图，
然后第 3 轮被交付了）。[IND] §8⑥ 给了现成的名字：PRELUDE（NeurIPS 2024）、
coactive learning——后者的假设弱到只要求**「编辑后的文本比提出的文本更好」**。

#### 表结构和关联方式

| 放哪 | 存什么 | 为什么 |
|---|---|---|
| `note_revisions` **+ 一列 `run_id`** | AI 那一份正文（`reason='harness'`） | 这张表本来就在，缺的**只是「跟哪一次跑有关」**。用已经存在的版本机制存正文，而不是另起一张表——那才是「第二份笔记副本」 |
| **新表 `harness_edits`** | `run_id` · `key` · `revision_id` · `status` · `base_chars` · `ai_chars` · `user_chars` · `kept_chars` | **只存 id + 一行数**，跟账本那条边界（只存 id + 一行，全文永远回 kite 取）是同一个道理 |
| `harness_runs` **+ `id` 改用同一个 run_id** | —— | `harness_runs.id` = `harness_rounds.run_id` = `harness_edits.run_id`。**这三张表在这之前没有任何 join 键** |

一行的生命周期：跑完 `Edits.after_run` 开一行（`open`，AI 那一侧填好）→
用户**下一次真的改了正文再保存**时 `store.update_note(source="user")` 关掉
（`edited`，填 `user_chars` / `kept_chars`）→ 同一篇又跑一次而上一行还开着，
上一行记 `superseded`（两行同时开着的话，一次保存会被两次跑同时认领，而其中
至少一个是错的）→ AI 那一版被 `REVISION_KEEP` 修剪掉了记 `lost`（没有「AI 提
出了什么」，剩下的数只是一次保存）。

**`update_note` 多了一个 `source`（user / harness / import）**。这是这份信号
成不成立的关键：`middleware/save` **每一轮**都在写库，把它算成一次用户编辑，
采到的就全是「用户一个字没改」。默认值是 `user`，代价是「新加一处机器写入而
忘了声明会被当成用户编辑」——所以 `app/` 下每一处调用在
`tests/test_harness_edits.py` 里**逐处登记**（按文件不按行号：钉行号的话上面
加一行注释就红，而它什么都没查出来）。

#### 三条边界，每条都有闸

* **只采集，不调参。** 一条闸盯着「`app/` 里除了采集那一处和 `store`，没有
  第二个人碰 `harness_edits`」——哪天有人把它接进 prompt / policy / 打分，
  这条当场变红，那时该做的是先看样本量，不是把闸删掉。
* **不是第二份笔记副本。** 只存指针和四个整数。「用户删掉的是这次跑写的哪
  几段」要按段落对齐才答得出来，那是 9.2 的事，靠 `revision_id` 回头重算。
* **绝对不碰 `notes`。** 落库那一处问的是
  `middleware/save.writes_note(st)`——`rails_off=("save",)` 的跑一行都不许落
  （`note_revisions` 正是 `db_guard` 指纹盯着的两张表之一），所以**所有跑批
  脚本自动安全**，这一批 5 次真跑下来 `harness_edits` **0 行**、
  `note_revisions` **44 行没动**，正是这条闸在起作用。

#### 边写边查出来的两件事

1. **`Edits` 挂在 BASE 上，于是六个 block 模式也会走它——而那是错的。**
   block 的 `st.content` 是**一个块**，`hooks/block.commit` 是空的、笔记一个
   字都没被动过。在那儿开一行，`ai_chars` 数的是块、`revision_id` 指的是没被
   动过的整篇，**两边说的不是同一份东西**。判据因此不是「有没有 `Save` 这个
   名字」而是「这次跑的产出会不会变成那篇笔记」，抽成 `save.writes_note()`
   一份实现、两个调用点。
2. **恢复到旧版本也是一次用户编辑，而且是最重的一种**（他把 AI 写的整个扔
   了）。`restore_revision` 绕开 `update_note` 自己 UPDATE，本来采不到。
   恢复到 **AI 那一版**则不算——那时正文跟 `revision_id` 指的那份逐字相同，
   关行那一步自己认得出来，这一行继续开着。

---

### 9.3 —— 比上次差就提示，**一个字都不改**

`BestOf` / `loop._regressed` 只管一次跑内部；用户第二次点「跑」的时候，
没有任何东西在比「这次跑完是不是比上次差」（[EFF] P2 实测三篇笔记
9→6→4、9→7→4→3）。`middleware/cross_run` 拿 `harness_runs` 里现成的历史
回答这个问题，差了发一条 `cross_run` 事件，**正文、`best`、停机原因一律不动**
（计划第 4 节「不做」里写死了不做跨跑自动回滚）。

两处形状是抄批 22 的：

* **可比才比**——两次跑的**维度集合必须相同**（维度集合会随「有没有风格档案」
  「是不是打磨模式」变，拿不同的集合折叠出来的两个标量比大小，比出来的是
  **配置差异**不是质量差异）。折叠用 `rank()` 那一套：先看几维达标，再看均分。
* **必须排在 `History` 前面**——`History` 这一步就把这次跑写进 `harness_runs`
  了，之后读「最近一次」读到的是自己。这条不靠注释：`History` 声明
  `after=("cross_run",)`，`_order.verify` 每次组链都验（突变验 B3 / B4 把两者
  换位 / 摘掉声明，当场变红）。

「记不记这一次」跟 `History` / `Edits` 共用**同一个函数**
（`history.records_this_run`）。三处各写一句 `if` 就是 §21 那条
「同一件事挡住一半等于没挡」。

---

### 12.2 —— 那两列第一次有数据（5 次跑 / 15 轮）

批 21 加了 `revisions_proposed` / `revisions_dropped`，批 21 和批 22 **一次模型
调用都没发**，所以到这一批为止**一行都没有**。

| | 值 |
|---|---:|
| 跑 / 轮 | **5 / 15**（note 模式、真实笔记、`max_rounds=3`） |
| 提出（`revisions_proposed` 之和） | **47** |
| 落地（`revision` 事件） | **27** |
| 丢掉（`revisions_dropped` 之和 = 提出 − 落地） | **20 = 提出的 42.6%** |
| 其中**守卫拦下、用户看得见的**（`dropped` 事件） | **14 = 丢掉的 70.0%** |
| 其中**静默 `continue` 掉的**（没事件、没人看见） | **6 = 丢掉的 30.0%**，占提出的 12.8% |
| 第 1 轮的提出数 | **5 次跑全是 0**（`Revise` 从第 2 轮才开工，符合预期） |
| 另有「不是修订丢弃」的 `dropped` 事件 | **5 条**，全是「删掉一句元话语」 |

**回答批 21 下一步②那个问题**：它当时写的是「静默那四条路占了大头（尤其锚点
找不到）就补事件；大头是守卫拦下的，30.2% 本身就值得去看守卫是不是太狠」。
**实测大头是守卫（70%）**，静默的那一半真实存在但不是主体。按它自己定的判据
→ **这一批不补事件**，该看的是守卫。但**分母只有 5 次跑、一篇笔记、一个模式**，
按 `corpus_lineage` 的规矩只看形状不算比例——所以「守卫是不是太狠」留给样本
再多一些之后，而那两列从今天起自己会攒。

**顺带纠正一个口径**：批 21 从 360 次 soak 跑的**事件计数**推出来的 30.2%，
结构上是**偏低的**——事件只看得见守卫拦下的那一档，静默的四条路一个事件都不
发。落库这一列同时数两档，所以这一批量到 42.6%。两个数不是矛盾，是
**两个不同的分子**；批 21 那个数今后应该读作「守卫拦下的比例」。

**还查出一个更小的口径问题**：`dropped` 事件里混着「删掉一句元话语」和
「输出被截断」两类，它们**不是「一条修订被拦下」**。批 21 从 1032 条里扣掉了
45 条元话语（4.4%）；这 5 次跑里是 **5/19 = 26%**——这个比例跟语料强相关，
拿它当常数减会出事。探针按原话前缀分类，名单写死在脚本里并说明了为什么不
import（`revise.py` 那两处发的是 f-string，没有可复用的常量）。

**同一批还换掉了一条词法闸**：`test_两个数真的被记进_harness_rounds` 原来
grep 三个文件里有没有那几行字符串——而「源码里出现过这个名字」和「那个数
真的进了库」是两件事（§21 的 `check_citations` 就是这么躺了整个改造期的）。
改成真的走一遍 `Ledger.after_judge` 再把行读回来（突变验 D1）。

---

### 12.3 —— 单次跑第一次有上限，上限是量出来的

[MECH] §7：「成本从不进入停机决策」——`judge` 只说 continue / complete /
blocked，不问「再花十几秒值不值」，而一次跑能花多少**完全没有约束**。

#### 先量（`scripts/run_cost_probe.py`，只读，158 次跑 / 447 轮）

`llm_usage` 有步骤没有 run_id，`harness_rounds` 有 run_id 没有 token，所以
「单次跑的成本」这个数**在库里不存在**，只能按时间窗口把两张表贴回去
（一笔用量属于时间上排在它后面、最近的那一行轮次，300s 以内算数）。

```
一次跑的 token（入+出）
  p25 20,192 · 中位 85,041 · p75 139,050 · p90 186,243
  p95 207,741 · p99 225,561 · 最大 248,160 · 最小 6,190
每轮
  中位 26,483 · p90 46,690 · 最大 82,720
按模式
  note     117 次  中位 112,705  最大 248,160
  eda        6 次  中位  59,624  最大  61,641
  analysis   6 次  中位  36,053  最大  49,181
  table / prompt / custom / chart 各 6~11 次  中位 11,439~14,505  最大 34,421
```

**这份重建错在哪，脚本自己打出来**：两次跑重叠的相邻对 **11**（重叠段的账会
算到先结束那次头上）、贴不上的用量行 **63**（全是几个 bench 的打分调用）、
跑之前的 `skeleton` 调用贴不上、挂掉的调用没有 usage 因而完全看不见
（**所以这个数偏低，上限因此偏保守**）。

**交叉验两次，都对上了**：
① 09-13~09-16 那段**真实用户使用**的 888 笔调用按 120s 间隔聚成 47 团，
中位 **113,404**——跟上面 note 模式的 112,705 几乎一字不差（那份聚类会把挨得
近的两次跑并起来，所以只能当上界，但中位对得上说明重建没有系统性偏移）。
② 这一批 5 次真跑落了库之后，拿重建的数跟**真的那一列**逐跑对：

```
04c01e68a982  重建 180,131  落库 180,131   +0
5652edb33cdf  重建 180,561  落库 180,561   +0
594ca9048090  重建 158,246  落库 158,246   +0
d3ac1074cb98  重建 166,917  落库 166,902  +15   ← 多算了 1 次调用
```
**3/4 逐 token 相同**，第 4 条多出来的 15 token / 1 次调用，正是我在跑探针前
手打的那一次连通性测试（「回一个字：好」）落进了那次跑的窗口里——
**脚本注释里写的那个失效形态，被实拍抓了个正着**。

#### 上限定成多少，为什么

**`RUN_TOKEN_CAP = 500,000`**（入+出的原始 token，环境变量可改，0 = 关掉）：

* 是观测到的最大值（248,160）的 **2.0 倍**；
* 也高于「拿库里最长那篇笔记（47,273 字符）线性外推」的 ≈383,000；
* **在已经量到的 158 次跑上一次都不会开火**——这是有意的。它是**安全网不是
  控制器**，同 `CONTINUE_MAX_TOKENS` 那条注释拿实拍换来的结论：
  *一个会在正常使用里被撞到的"安全网"就不是安全网*。它要拦的是工具循环空转、
  正文失控增长这类**形状不同**的跑。
* 不折算价格：库里没有价目表，而缓存命中的输入 token 便宜一档
  （这一批 864,835 token 里 **443,579 是缓存命中的输入**），所以这个数偏保守。

#### 形态：停下来告诉用户，不静默截断

* `middleware/cost` 在 `before_run` 往调用链上绑一份账本
  （`llm.bind_usage_sink`；`util/llm._record` 是全仓唯一记用量的地方），
  轮末结一次账；
* 超了发一条 **`cost` 事件带上数字**（花了多少 / 上限多少 / 几次调用），
  停机规则 `_over_budget` 跟着收工，`RUN_FINISHED` 的 reason 是 `cost_cap`，
  同一个值进 `harness_runs.stopped`；
* **判在轮末**，所以最多超出一轮的开销（p90 46,690）——轮中掐断等于把一轮的
  钱花了又不要它的产出；
* **交的是最好的那一轮**：`cost_cap` 跟循环末尾那个 `else:`（跑满轮数）是同一
  个形状——**停机的理由跟这一轮写得好不好无关**，那正是「最后一轮最不可能是
  最好那轮」的时候。名单写成 `loop.SHIP_BEST_ON` 而不是 `hit in ("a","b")`：
  下一个加停机原因的人得先决定自己属于哪一档；
* **排在 `complete` / `blocked` 后面**（那两个是这次跑真正的结局，不该被钱盖
  掉）、**排在 `_no_progress` / `_regressed` 前面**（那两个说质量，这条说预算，
  两个都成立时用户更需要知道后者）。两条都有突变验（C3 / C6）。

**顺手把分母补上**：`harness_runs` 加 `tokens` / `calls` 两列，`History` 写。
**下一次读这个数的人不用再跑那个探针**——而且这一批的 5 次真跑已经证明它
**真写得进去**（166,902 / 158,246 / 180,131 / 180,561 / 178,980，调用
11 / 10 / 12 / 13 / 12），`stopped='cost_cap'` 也有单测真跑一趟读回来。
（§21：落库加字段之后要问一句「它的每个取值都真写得进去吗」——批 22 的
`stopped` 就是从加进来那天起记不到 `max_rounds`。）

---

### 12.4 —— 9.3 / 12.3 的界面那一半

`api.ts` 两个新 handler（`onCrossRun` / `onCost`）、`App.tsx` 两条 toast、
`RUN_FINISHED` 的文案多认一个 `cost_cap`。**不接前端的话，那两条事件就是
「建了判据不等于用了判据」的第四例**——而 `test_event_contract` 那条
「后端每个 custom 事件前端都接得住」会当场报出来。

---

### 突变验（34 条，34 条变红——**1 条第一版没抓住**）

**基线 1785 绿。** 每条单独改坏，跑目标用例，跑前后都清 `__pycache__`。

| # | 把什么改坏 | 结果 |
|---|---|---|
| A1 | `Edits` 不认「这次跑不许碰这篇笔记」 | ✅ |
| A2 | 又跑一次时旧行不记 `superseded` | ✅ |
| A3 | `update_note` 的 `source` 被忽略（harness 自己落盘也算用户编辑） | ✅ |
| A4 | 正文一个字没改也把行关掉 | ✅ |
| A5 | `kept_chars` 开着 `autojunk` | ✅ |
| A6 | AI 那一版没了还照样关行（而不是记 `lost`） | ✅ |
| A7 | `Edits` 自己写一句 `if st.round >= 1`，不共用 `records_this_run` | ✅ |
| A8 | 落版本时不带 `run_id`（`note_revisions` 那一列恒空） | ✅ |
| A9 | `restore_revision` 不再算一次编辑 | ✅ |
| A10 | 删笔记时不删采集样本 | ✅ |
| A11 | 没有 `run_id` 也开行（指针指向空气） | ✅ |
| A12 | 让另一个 middleware 读 `harness_edits`（= 开了写回路） | ✅ |
| A13 | 新增一处 `update_note` 不登记 | ✅ |
| A14 | block 模式也采（`writes_note` 只看 `rails_off`） | ✅ |
| B1 | 跨跑比较不再要求维度集合相同 | ✅ |
| B2 | 平手也报「变差了」 | ✅ |
| B3 | `CrossRun` 排到 `History` 后面 | ✅ |
| B4 | `History` 不声明 `after=("cross_run",)` | ✅ |
| B5 | `CrossRun` 不共用 `records_this_run` | ✅ |
| B6 | 报完顺手把正文回滚（= 替用户做了决定） | ✅ |
| B7 | 没有历史也报一条 | ✅ |
| B8 | 一分没打上也去比 | ✅（**第一版没抓住**，见下） |
| C1 | 账本不加输出侧的 token | ✅ |
| C2 | `before_run` 每次新建账本（暂停恢复后重新从 0 记） | ✅ |
| C3 | 把 `_over_budget` 从停机规则里拿掉 | ✅ |
| C4 | 上限 ≤ 0 也判（关不掉） | ✅ |
| C5 | `cost_cap` 不进 `SHIP_BEST_ON`（交最后一轮） | ✅ |
| C6 | `_over_budget` 排到 `_complete` 前面 | ✅ |
| C7 | `record_harness_run` 不写 `tokens` / `calls` | ✅ |
| C8 | `harness_runs.id` 自己生成（三张表又没了 join 键） | ✅ |
| C9 | 记账出错静默吞掉 | ✅ |
| C10 | 上限每轮现读环境变量 | ✅ |
| C11 | `Cost` 不在 BASE 里 | ✅ |
| D1 | `Ledger` 把那两列写死成 0 | ✅ |

**B8 第一版没抓住，而这次不是「用例不够」——是那条守卫本身多余。**
`CrossRun` 里「这次一分没打上就不比」删掉照样绿，因为下面 `compare()` 的
「维度集合必须相同」已经答了同一个问题（空集合跟任何非空集合都不相等，
两边都空时 `_rank` 又都返回垫底值）。§21 那条「突变没被抓住先怀疑用例不够」
在这里要多一档：**也可能是那条守卫多余**。两条路——删掉它，或者把它挡住的
那件事变成可观测的。选了后者：不该比的时候**连历史都不该去读**，断言改成
「`recent()` 一次都没被问过」，突变当场变红。规矩补进 `harness-framework.md`
§21 那一行（**没有新增第九条**——那条说的是同一件事的第四种形态）。

### 闸

后端 **1785 → 1830**（+45）：`test_harness_edits` 新建 17 条、
`test_cross_run` 新建 13 条、`test_run_cost` 新建 13 条、
`test_scripts_import` +2（两个新探针自动被参数化进去）；
`test_revise_middleware` 改了一条（词法闸 → 真跑一遍读回来）、
`test_db_guard` 改了一条断言（原来钉的是 `middleware/save.py:64` 这个**行号**，
改成钉文件名——上面加一行注释就红的断言没有在断言任何东西）。
前端 **52 个文件 258 → 260 条**（`harnessStreamRounds.test.ts` +2）。
`harness-framework.md`：middleware **16 → 19**、CUSTOM 名字 **12 → 14**、
停机条件 **3 → 5**、目录和 §7 的表跟着改，`test_doc_counts` / `test_directory_map`
照绿。

### 计划外发现

1. **`Edits` 挂在 BASE 上会让六个 block 模式采到一份指错对象的样本**
   （`ai_chars` 数的是块、`revision_id` 指的是没被动过的整篇）。判据因此不是
   「有没有 `Save` 这个名字」而是「这次跑的产出会不会变成那篇笔记」——
   抽成 `save.writes_note()`。**一份指错对象的 ground truth 比没有更糟。**
2. **批 21 那个 30.2% 结构上是偏低的**，因为它数的是事件，而静默 `continue`
   的四条路一个事件都不发。今后应该读作「守卫拦下的比例」。
3. **`dropped` 事件里「元话语删除」的占比跟语料强相关**：批 21 是 4.4%
   （45/1032），这 5 次跑是 26%（5/19）。拿它当常数减会出事。
4. **`harness_runs` 和 `harness_rounds` 在这之前没有任何 join 键**，两张都记
   「一次跑」却连不起来——批 22 量 `stopped` 那一列、这一批量成本，都是绕着
   这个洞走的。这一批让 `harness_runs.id` 直接用 `Ledger` 生成的 run_id。
5. **`restore_revision` 绕开 `update_note` 自己 UPDATE `notes`**。它是「写用户
   笔记」的第二个入口，只是恰好不改正文以外的东西。9.1 因此差点漏掉最重的
   那一类信号（把 AI 写的整个扔掉）。
6. **一条测试钉的是行号**（`test_harness里只有一处在写用户的笔记` 里的
   `middleware/save.py:64`）。这一批往那个文件上面加了注释，行号就变了——
   它有个 `or len(writers) == 1` 兜着所以没红，但那意味着前半句从来没在查
   什么。改成钉文件名。

### 开工前后的 `notes` 指纹（自己核对过，不是自报）

|  | 开工前（= 批 22 收尾） | 收尾 |
|---|---|---|
| `notes` 行数 | 482 | **482** |
| `notes` `max(updated_at)` | `2026-09-16T02:53:27+00:00` | **`2026-09-16T02:53:27+00:00`** |
| 正文总字数 | 321,250 | **321,250** |
| 482 篇逐篇摘要再取一次摘要 | `47dcc54be60aa4f2` | **`47dcc54be60aa4f2`** |
| `note_revisions` 行数 | 44 | **44** |
| `harness_edits` 行数 | （表不存在） | **0** |

**这一批有 5 次真跑**（note 模式、真实笔记 `309f19202309`），全部
`rails_off=("save",)`、整趟夹在 `db_guard.Watch()` 里、**命令不经过任何管道**、
单独打印 `EXIT=$?`。`harness_edits` 收尾 0 行**正是 9.1 那条 rails 闸在起作用**
——采集口开了，但跑批一条样本都不许采。

### 这一批的实际成本

**59 次模型调用、864,835 token**（其中 **443,579 是缓存命中的输入**），
全部来自 12.2 那 5 次真跑（每次 3 轮，单次 158,246~180,561 token、
87~116 秒）。12.3 的分布量在已经存在的落库数据上（158 次跑 / 447 轮 /
1,943 行用量），零调用。验收靠 34 条突变验（每条一次 targeted `pytest -x`）
+ 两次全量闸。

### 下一步

1. **9.1 采到的第一份样本要逐条读，别直接当分母**（§21：顺手量出来的数，
   当分母用之前得先逐条读——批 21 的「4 篇业务词」就是这么错的）。特别要看
   `kept_chars` 这个口径：它对的是**整篇**，而整篇里有一大半是开跑前就有的
   （`base_chars` 一起记着就是为了这个）。
2. **9.2 / 9.4 仍然等样本**。今天 `harness_edits` 是 0 行，而这两条的整个前提
   是「有一批人的判断可以对照」。
3. **12.2 的守卫值不值得放松，等那两列自己攒**。5 次跑说不了什么，但从今天起
   每一次真跑都会往里写。静默那 6 条要不要补事件，按批 21 自己定的判据
   （大头是守卫）**暂时不补**。
4. **`RUN_TOKEN_CAP` 要复查一次**：它在 158 次跑上开火 0 次是设计，但
   「从来不开火」和「拦不住真正该拦的」在数据上长得一模一样。等
   `harness_runs.tokens` 攒够，去看一眼实际分布的右尾有没有长出新的形状。
5. **10.3（criteria drift 的重新校准入口）是阶段 10 最后一条**，连着两批没做。
   12.1（「这一轮为什么这么跑」补 `steer` 和判据命中）是阶段 12 最后一条。

---

## 批 24 · 阶段 10.3 + 12.1 + 两条审计遗留（2026-09-18）

**这一批一次模型调用都没发。** 10.3 的数量在 470 篇现存笔记上
（`scripts/criteria_drift.py`，只读 + `db_guard.Watch()`），R1 的复现用真 registry
+ 打桩端点，R2 的分母是**结构性**的（从 `Mode.focus_groups` × 工具注册表算出来）。
验收靠 **27 条突变验** + 全量闸。

**四条的处置：10.3 入口开张并复现了批 21 手工那一次、顺手查出三条判据没有量程
（只报不改）；12.1 前端第一次看得见诊断去了哪儿和哪条判据命中；R1 是真 bug、
复现了、修了；R2 分母为 0，不改，改成把这个 0 钉成一条会说话的断言。**

---

### 10.3 —— criteria drift 的重新校准入口

`scripts/criteria_drift.py`，**只读、只报不改**。三个口径 × 三类血缘：

| 口径 | State 怎么摆 | 回答什么 |
|---|---|---|
| **whole** | `content_at_start=""` · `fresh=正文` | 判据的上界：它一共会对这批文字开几次火 |
| **stale** | `content_at_start=正文` · `fresh=""` | **量程**：这一档命中的每一句，都是判据在打不是这次跑写的字 |
| **probe / facts** | 合成探针；同 whole 但 `st.facts` 非空 | 两个 yes/no：前提成不成立、开的火是不是这个脚本自己造的 |

#### 语料（`corpus_lineage` 分的三类）

`user` **18** 篇 · `script` **19** 篇 · `fixture` **433** 篇（共 470 篇非空笔记）。
比例只在 `user` 上说，`script` 只看形状，`fixture` 是噪声——这是批 4 / 批 6 的账。

#### 真实漂移数字（分血缘，whole / stale）

| 判据 | 活 | user whole | user stale | script whole | script stale | fixture whole | fixture stale |
|---|:-:|---:|---:|---:|---:|---:|---:|
| `no_audit_voice` | 活 | **5/18 = 27.8%** | **0** | 3/19 | 0 | 1/433 | 0 |
| `material_thin` | 活 | 13/18 = 72.2% | 0 | 14/19 | 0 | 291/433 | 0 |
| `no_repeated_lists` | 活 | **3/18 = 16.7%** | **3/18** | 1/19 | 1/19 | 1/433 | 1/433 |
| `no_restated_paragraph` | 活 | **1/18 = 5.6%** | **1/18** | 2/19 | 2/19 | 0 | 0 |
| `no_fake_charts` | 活 | **1/18 = 5.6%** | **1/18** | 0 | 0 | 0 | 0 |
| `charts_from_tools` | 活 | 2/18 = 11.1% | **0** | 2/19 | 0 | 0 | 0 |
| `citations_exist` | 活 | 0 | 0 | 0 | 0 | 1/433 | 1/433 |
| `no_placeholder` · `outline_intact` · `citations_hold` · `citations_present` · `material_used` · `no_same_sources_twice` · `unsupported_specifics` · `section_budget` | 否 | 0 | 0 | 0 | 0 | 0 | 0 |

另有 7 条（`heading_fits` / `tail_clashes` / `table_present` / `table_columns_match` /
`chart_numbers_grounded` / `chart_readable` / `numbers_from_tools`）**这份语料量不了**：
它们判的是光标旁边那一块，拿整篇笔记喂它们是范畴错误（`table_present` 会在每一篇
没有表的笔记上开火，那个 100% 什么都不说明）。报告里单独一栏列着并写明理由——
**不是悄悄漏掉**，有一条闸盯着「一条判据都不许既不被量也不说为什么」。

#### 入口先验了一次自己

`no_audit_voice` 在 18 篇 `origin=user` 上开火 **5 篇 = 27.8%**，**命中的正是批 21
逐句读过的那 5 篇**（`06647b9c2031` / `ecfac1f3c0aa` / `574f4ff29956` /
`309f19202309` / `715266c1fcb4`），而 stale 那一档 **0 篇**——批 21 收的那个量程
到今天还在。**一个复现不了已知结论的校准入口，报出来的新结论也不值钱。**

#### 哪几条漂了：**三条判据没有量程**

| 判据 | 量程绑在哪 | 结果 |
|---|---|---|
| `no_audit_voice` | `st.bag["content_at_start"]` | stale **0**（批 21 收的） |
| `charts_from_tools` | `st.bag["content_at_start"]` | stale **0** |
| `no_repeated_lists` | `st.fresh`，而且写的是 `if fresh and …` | stale **3/18**：**打磨轮 / 只清理轮的 `st.fresh` 是空的，那一句直接短路，量程当场静默失效** |
| `no_restated_paragraph` | **没有** | stale 1/18 |
| `no_fake_charts` | **没有** | stale 1/18 |

**「这一轮写了什么」会是空的，「开跑时有什么」不会。** 这条进了
`harness-framework.md` §20④。

#### 逐条读完再说（§21：顺手量出来的数，当分母用之前得先逐条读）

`--show` 把每一条命中的**正文原文**连上下文列出来，读完 + 查这几篇的
`harness_runs` / `note_revisions` 血缘：

| 笔记 | 判据 | 跑过 harness 吗 | 读出来是什么 |
|---|---|---|---|
| `92d07b760f1e` | `no_repeated_lists` | **一次都没有**（`harness_runs` 0 行、`note_revisions` 0 行） | 用户自己把「录制信任、关联即时反馈、总结行动化、图谱自维护」在「框架」和「下一步」各写了一次——**纯误伤** |
| `e78306202d78` | `no_repeated_lists` | 跑过 29 次，但**已经还原回 09-02 的原文**（`before_restore` 那一版） | 用户原文里的一处逐字重复——**纯误伤** |
| `06647b9c2031` | `no_repeated_lists` · `no_restated_paragraph` | 跑过，且笔记 `updated_at` 在那次跑之后 | 「下一轮 10 台到货为 6 月 15 日…」逐字两遍——更像**上一次跑写进去的真缺陷** |
| `3a3a96354546` | `no_fake_charts` | 跑过（09-03T08:32 complete/4 轮），笔记 09-03T08:48 才更新 | 「先看硬件参数 → 跳到软件功能列表 → 回到定价 →」箭头链——更像**这次跑之后留下的真缺陷** |

**2 篇纯误伤 + 2 篇真缺陷**，正是批 20/21 那个形状的第二次。
所以这一批**按入口自己的规矩只报不改**：真要收量程，得先决定「修订那条线能不能
改掉上一次跑留下的那两处」，那是独立一件事，不能拿一次统计去顺手做。

#### 一个会骗人的数，入口自己把它摘出去了

`material_thin` 在 18 篇真实笔记上开火 **13 篇 = 72.2%**，看着比 `no_audit_voice`
还严重——**而那个数说的是这个脚本没去检索**：它的第一个触发条件就是「手上一条
材料都没有」，而这个入口不发任何调用、`st.facts` 恒空。把同一批开火的换成
「手上有材料」再判一次：**13 → 0**。所以入口多了一档 `with_facts`，
报告里直接写「这个数说的是这个脚本的形态，不是这批文字」。
**一个会被下一个人当成结论直接用的数，比没有这个数更糟。**

#### 「和上次跑比变了多少」

基线存 `.local/criteria_drift/latest.json`（**不进 git**：里面带笔记 id 和命中片段，
那是用户内容）。第二次跑起报「哪条判据的哪个血缘的哪个口径从 N 变成了 M」、
新增的判据、以及**消失的判据**（被删掉或者从模式上摘了）。

---

### 12.1 —— 「这一轮为什么这么跑」补上 `steer` 和判据命中

`AgentActivity.tsx` 原来显示的是检索预算和温度，而那两个是 `policy.adjust()` 的
**结果**。补的两样都走已有的事件，没加新的 CUSTOM 名。

#### ① 诊断去了哪儿

`round_summary` 多四个键：`steer`（上一轮最弱那一维的诊断原话）、`steer_dim`、
`steer_material`（这一维是不是**检索**改善得了的那一类，`policy.MATERIAL_DIMS`，
由后端算——那份名单跟 `repair.INNER_QUALITY` 是互补的一对，前端再抄一份必然漂）、
`steer_in_plan`。

`steer_in_plan` **不是自报**：`hooks/note.prepare` 是**回头在真正发出去的那条 user
消息里找它**（`plan_steer in msgs[-1]["content"]`）——`retrieval_plan_user` 那一句是
`if steer:` 才加的，而 `policy.steer` 自己又被 `MATERIAL_DIMS` 过滤过。
§21：凡是只能靠自报来保证的性质，迟早会被报错一次。

**`null` 和 `false` 是两回事，界面上也说两句话**：`null` = 这一轮压根没有检索规划
这一步（打磨 / 只清理 / 关了 `AGENT_TOOLS`），`false` = 有这一步但诊断没进去。
混成一个值，面板只能瞎说一句。这个键读完就 `pop`——`bag` 是跨轮活着的，
留着不 pop 的话打磨轮会顶着上一轮的答案报「进了检索计划」（突变验 12.1-M2）。

界面上于是能说出这三句的其中一句：
「→ 这句话进了这一轮的检索计划。」/
「→ 不进检索计划：这一维再查十条事实也修不好，它走的是修订那条线。」/
「→ 这一轮没有检索规划这一步（只清理 / 打磨）。」

#### ② 哪几条判据命中了

`check_hit` 多三个键：`round` · **`check`（判据自己的名字）** · `ran`（跑到第几条）；
分母 `checks_total` 在 `round_summary` 里。

**为什么非要判据名**：`no_placeholder` / `citations_hold` / `citations_exist` /
`material_thin` / `unsupported_specifics` **五条判据全落在 `factual_grounding` 这一维
上**，用户看到的「事实依据 0 分」根本不知道是谁判的。而原来界面上还是原样打英文
维度名（`<b>{r.checkHit.dimension}</b>`）。前端补了一张 23 条的中文名表
（`editor/dimLabel.checkLabel`），**后端每挂一条判据它就必须有一个中文名**，
`tests/test_why_this_round.py` 按模式逐个 parametrize 钉着（动态挂上去的
`instruction_constraints` 另有一条，因为 parametrize 看不见它）。

**前端原来是单数字段、后到的把先到的盖掉。** 一轮里可以先后到达好几条：
连着卡满被放行的那几条（`STUCK_ROUNDS` 之后后端照发）+ 最后真正短路的那一条。
**判据命中了但界面不显示，等于用户看不见**——跟「建了判据不等于用了判据」是
同一个形状。改成攒成一串，并且在一条都没命中时明说「N 条代码判据全过，
这一轮的分是打分模型给的」（没有分母，「全过了」跟「判据根本没跑」长得一样）。

**那一行 setState 回调没有任何测试够得着**：把它改回覆盖式，全套前端闸照绿
（实测）。所以抽成纯函数 `editor/agentRound.withCheckHit` 才钉得住。

#### ③ 顺手：整轮被深度门丢光，此前完全无声（观测性，不是 bug）

`if not kept: break` 之前不加 `trace.iters`、不置 `truncated`（`_cap_calls` 特意
不把深度门丢掉的算进去——「那是刻意的取舍，不是资源不够」），于是
**「模型发了 4 个调用全被丢了」跟「模型一个都没发」在 trace / 落库 / SSE 上
长得一模一样**，而 `DEPTH_TOOLS` 的注释说这是观测到的常态（4 次真实采样全部
撞上限）。做了：`ToolTrace` 加 `dropped_depth` / `stopped_all_dropped`（`merge`
跟上，逐字段闸当场变红把我拦了一次）、`harness_rounds` 加 `depth_dropped` 一列
（`Ledger` 写，**真跑一遍 `Ledger` 再把行读回来**，不是 grep 源码）、
`round_summary` 带上、面板上一行「有 N 发检索被『第 2 轮起只深挖』这条规则丢掉」。
**不动 `iters`**：它的含义是「真的执行了几轮工具」，`merge` 和 `policy` 都按这个读。

---

### R1（真 bug）—— `_parse_call` 只在**读**的那一侧容错

#### 复现（真 registry，打桩端点，当前 HEAD `9de1c7c`）

喂进两种 `_parse_call` **明确兜住**的异形：
① `function.arguments` 是 dict 不是 string、而且没有 `id`；
② `name` / `arguments` 平铺在顶层、没有 `function` 层、也没有 `id`。
`gather_context` 返回的 `extra` 原样打出来：

```json
{"role": "assistant", "content": "", "tool_calls": [
  {"id": "", "type": "function",
   "function": {"name": "filter_facts", "arguments": {"topic": "定价"}}},
  {"name": "fact_sources", "arguments": "{\"fact_id\": \"f1\"}"}]}
{"role": "tool", "tool_call_id": "", "name": "filter_facts",  "content": "（没有匹配的事实）"}
{"role": "tool", "tool_call_id": "", "name": "fact_sources",
 "content": "（fact_sources 的参数必须是一个对象，收到的是 str）"}
```

**五处违反协议**：`arguments` 是对象不是字符串 · 第二条没有 `function` 对象 ·
两个 `tool_call.id` 是空的 · **两条 tool 回复的 `tool_call_id` 都是空串**。
根因一句话：`_parse_call` 只管**取值**，而 `msg["tool_calls"] = kept` 塞回去的是
端点原样给的 dict（`util/llm.complete_raw` 也是 `out["tool_calls"] = msg["tool_calls"]`
原样透传）。**容错只做在读的那一侧，等于把问题藏到下一跳。**

后果跟批 13 / 批 22 那条一模一样：`hooks/block.prepare` 把 `msgs + extra` 喂给补图
那一轮 → 400 → 被 `except` 吞掉 → **图画不出来而且一点痕迹都没有**。
**这是同一条 bug 的第三个入口。**

批 13 那道闸比的是 `asked == answered` 的 id 列表，而实拍下来两边都是 `["", ""]`
——**相等，照样通过**。§21：一个谁都满足的断言没有在断言任何东西。

#### 计划外：`_parse_call` 的读那一侧**本身也是坏的**

第二条 tool 回复的原话是「**参数必须是一个对象，收到的是 str**」。平铺形状下
`fn.get("arguments")` 是 `None`，于是走到
`json.dumps(… or call.get("arguments") or {})`——而顶层那个 `arguments`
**本来已经是一个 JSON 字符串**，`json.dumps` 又包了一层，工具那边
`json.loads` 回来拿到的是 `str` 不是对象。**它号称兜住了这种形状，其实只兜住了
「取得到名字」。**

#### 修法

* `_parse_call`：**先取到值、再决定要不要编码**（拿不拿得到参数跟它嵌在哪一层无关）；
* 新增 `_rebuild_call()`：拿归一化之后的结果**重建**那条 call（`id` 缺失时按
  `(第几轮, 第几个)` 补一个确定性的合成 id，不跟端点自己的 `call_xxx` 撞）；
* 归一化放在 `_cap_calls` **之前**，于是 `kept` 里每一条都已经是协议形状，
  塞回 `msg["tool_calls"]` 的不再是端点原样那份。

修完同一段复现：违反协议 **0 处**，`asked == answered == ["tc_0_0", "tc_0_1"]`，
而且 `fact_sources` 真的拿到了 `fact_id=f1`（报「找不到事实 f1」而不是类型错）。
批 13 的三条老闸也一起收紧成「**id 不许是空串**」。

---

### R2（可疑）—— `hooks/block` 第二次 `gather_context` 的**入口**状态：**分母为 0，不改**

形状确实是「同一件事挡住一半」的第五种：第二发的 `seen_ids` 从空集起步
（`BARREN_STOP` 失效）、`trace2.iters` 从 0 起步（`_cap_calls` 的深度门整个放开），
而 `hooks/note.py` 恰恰是特意把账本的 `known_ids` 喂进来的，两处做法相反。
批 22 的 `merge()` 修的是**出来**那一侧，进去那一侧没动。

**先量分母，而且量出来是结构性的 0：**

| | 值 |
|---|---|
| 声明了 `focus_groups` 的模式 | **2**（EDA / ANALYSIS），两个都是 `("chart",)` |
| `chart` 组注册的工具 | `chart_column` · `chart_from_text` · `render_chart` |
| 跟 `FACT_TOOLS` 的交集 | **空** —— 而 `seen_ids` 只在 `if name in FACT_TOOLS` 里被读 |
| 跟 `BREADTH_TOOLS` 的交集 | **空** —— 而深度门只丢 `name in BREADTH_TOOLS` |
| 库里两个模式的轮次 | eda 18 轮 / analysis 18 轮（tool_calls 85 / 33），**一发都够不着那两条判据** |

补图那一轮的 `groups` 是写死的 `st.mode.focus_groups`，模型在那一发**根本发不出**
事实类或广度类调用。所以**不改**（批 22 的规矩：分母为 0 就写「不改」并说清理由）。
改成传进去，加的是两条谁也证明不了它在挡什么的守卫——§21 说那比没有更糟。

**改成把这个 0 钉住**（批 23 的那一档：把守卫挡的事变成可观测的断言）：
`test_补图那一轮的工具组里不许出现事实类或广度类工具` —— 哪天有人给某个模式的
`focus_groups` 加上 `memory`，这条当场变红，那时候要做的正是把 `known_ids` 和
迭代序号接上去，而不是删掉这条闸。（突变验 R2-M1 实拍变红。）

---

### 突变验（27 条，27 条变红——**4 条第一版没抓住**）

**基线 1830 绿 / 前端 260 绿。** 每条单独改坏，跑目标用例，跑前后都清 `__pycache__`。

| # | 把什么改坏 | 结果 |
|---|---|---|
| R1-M1 | 写回消息的还是端点原样那份（撤掉归一化） | ✅ |
| R1-M2 | 缺 id 时不补合成 id | ✅ |
| R1-M3 | 合成 id 用同一个常量（两条撞一起） | ✅ |
| R1-M4 | `_parse_call` 回到二次编码那一版 | ✅ |
| R1-M5 | 归一化顺手改写端点已经给对的 id | ✅ |
| OBS-M1 | `_cap_calls` 不报被深度门丢掉几发 | ✅ |
| OBS-M2 | 整轮丢光时又不留痕迹 | ✅ |
| OBS-M3 | `merge` 漏掉 `dropped_depth` | ✅ |
| OBS-M4 | `Ledger` 不写 `depth_dropped` | ✅ |
| OBS-M5 | 落库那个数写死成 0 | ✅ |
| R2-M1 | 给 EDA 的 `focus_groups` 加上 `memory` | ✅ |
| 12.1-M1 | steer 进没进检索计划改成自报 | ✅ |
| 12.1-M2 | 读完不 pop（上一轮的答案漏给下一轮） | ✅ |
| 12.1-M3 | `steer_material` 恒真 | ✅ |
| 12.1-M4 / M5 | 命中事件不带判据名（两个发射点各一次） | ✅ |
| 12.1-M6 | 卡满那条不再继续往下看别的判据（一轮只报一条） | ✅ |
| 12.1-M7 | 轮次载荷里不给判据分母 | ✅ |
| 12.1-M8 | 前端少掉一条判据的中文名 | ✅ |
| FE-M1 | 前端把命中改回覆盖式（后到的盖先到的） | ✅（**第一版没抓住**，见下） |
| 10.3-M1 | 「活着」只看探针 | ✅ |
| 10.3-M2 | stale 那一档不把正文当开跑前就有的 | ✅ |
| 10.3-M3 | 三个血缘桶合着算 | ✅ |
| 10.3-M4 | 「量不了」那一栏空着（判据被静默漏掉） | ✅ |
| 10.3-M5 | `--show` 不列原文片段 | ✅（**第一版没抓住**） |
| 10.3-M6 | 判据抛异常被当成没开火且不出声 | ✅（**第一版没抓住**） |
| 10.3-M7 | 「换成手上有材料」那一档不再重判 | ✅（**第一版没抓住**） |

**四条第一版没抓住，四条都是用例不够**（连着十六批了）：

* **FE-M1**：那一行是 `App.tsx` 里 setState 回调的一部分，**前端一条闸都够不着它**
  （`npm test` 的 `tsc -b` 也拦不住——改成 `[d]` 类型照样对）。抽成纯函数
  `editor/agentRound.withCheckHit` 才钉得住。*一段只活在 setState 回调里的逻辑，
  等于没有测试。*
* **10.3-M5**「`--show` 不列原文片段」照绿——因为我的断言写的是「命中的那句话出现
  在输出里」，而**诊断本身就逐字引着那句话**（§21「一个在别处顺手被满足的断言」，
  第五次）。断言改成只看「原文：」那几行，素材里给那句话加上**只有原文才带得出来
  的上下文**（前后各一句）。*而这一改当场发现 `_snippets` 从来就是坏的*：它只按
  `；` 切，`piece[:30]` 落在诊断自己的措辞上，正文里根本找不到——
  **`--show` 从写下那天起一行原文都没列出来过，而那正是这个入口的全部价值。**
  修完在真库上又露出第二个形态：`no_repeated_lists` 的判词把两段原文用
  「甲」和「乙」串在一条里，按分隔符切完还是一整串，所以**先按直角引号取**。
* **10.3-M6 / M7**：`_fire` 的异常分支和 `with_facts` 那一档**一条用例都没有**。
  补了两条，其中 M7 那条正是「`material_thin` 72.2% 是脚本造出来的」这个结论的闸。

---

### 闸

后端 **1830 → 1871**（+41）：`test_why_this_round` 新建 21 条、
`test_criteria_drift` 新建 13 条、`test_tools` +4、`test_block_harness` +1、
`test_dimension_method_gates` +1（第⑦条方法指到的入口必须真的在）、
`test_scripts_import` +1（新脚本自动被参数化进去）；
`test_tools` 改了 3 条断言（批 13 那三条 `asked == answered` 一起收紧成「id 不许是
空串」）、`test_dimension_method_gates` 的方法名单 +1。
前端 **52 个文件 260 → 263 条**（`harnessStreamRounds.test.ts` +3）。

`harness-framework.md`：§20 加第⑦条（标题「六条方法」→「七条方法」，目录跟着改）、
§20④ 补「量程要绑在开跑时有没有上」那一段、§21「同一件事挡住一半」那一行补第六种
形态、§11 的 `round_summary` / `check_hit` 两行补载荷、§12 的 handler 表 +1 行。
**Mode / 工具 / check / middleware 四个数一个没动**，`test_doc_counts` /
`test_directory_map` 照绿。

---

### 计划外发现

1. **`_parse_call` 的读那一侧本身是坏的。** 平铺形状下参数被 `json.dumps` 二次编码，
   工具收到的是一个 JSON 字符串而不是对象，当场报「参数必须是一个对象，收到的是
   str」。它号称兜住了这种形状，**其实只兜住了「取得到名字」**——
   *一个写着「这里一并容错」的函数，容错到哪一步得自己验一次。*
2. **`--show` 从写下那天起就没列出过一行原文**（10.3-M5）。而「一键列出原文命中片段
   供人逐条读」正是这个入口存在的理由——**功能的核心那一半坏着，报告还是照常打印
   出一堆数**。抓住它的不是我，是突变验。
3. **`st.steer` 在 note / section 两个模式里写了没人读。** `loop.py` 每轮末尾都算
   `st.steer = _steer(st)`，而 `hooks/note` 读的是 `policy.steer`（Runtime 那条线）、
   `hooks/section` 压根没有 policy（`SECTION.extra_mw` 里没有 `Runtime`），
   **全仓唯一真读 `st.steer` 的是 `hooks/block.produce`**。诊断在长文那两个模式里
   走的是另一条线（`bag["focus"]` / `focus_note` → `Revise`）。12.1 把两条线都摆到
   界面上了，但「`st.steer` 在长文模式里是个死字段」这件事本身还在。
4. **`test_event_contract` 里那条 `missing -= {"warning", "check_hit"}` 的
   `check_hit` 是死的**：前端 `api.ts` 明明有 `payload.name === 'check_hit'` 分支，
   正则取得到，减不减都一样。*一条永远不生效的豁免，读起来像「这个事件前端没接」。*
   这一批没动它（不在范围内），记在这儿。
5. **`no_repeated_lists` 的量程写成 `if fresh and …`**，于是「这一轮没写东西」
   （打磨 / 只清理）和「这一轮写的里没有这些」被当成了同一件事——
   **前者会让整条量程静默消失**。这跟批 21 选 `content_at_start` 而不是 `st.fresh`
   是同一个理由的另一面：那次的理由是「修订就地改写旧段落，改出来的不进 `st.fresh`」，
   这次是「`st.fresh` 会是空的」。*一个可能为空的量程，就不是量程。*

---

### 开工前后的 `notes` 指纹（自己核对过，不是自报）

|  | 开工前（= 批 23 收尾） | 收尾 |
|---|---|---|
| `notes` 行数 | 482 | **482** |
| `notes` `max(updated_at)` | `2026-09-16T02:53:27+00:00` | **`2026-09-16T02:53:27+00:00`** |
| 正文总字数 | 321,250 | **321,250** |
| 482 篇逐篇摘要再取一次摘要 | `47dcc54be60aa4f2` | **`47dcc54be60aa4f2`** |
| `note_revisions` 行数 | 44 | **44** |
| `harness_edits` 行数 | 0 | **0** |

这一批**一次跑批都没有**（零模型调用）。唯一碰真库的两处都只读、夹在
`db_guard.Watch()` 里、**命令不经过任何管道**、单独打印 `EXIT=$?`：
`scripts/criteria_drift.py`（10.3 的全部数字）和一次血缘核对查询（读
`harness_runs` / `note_revisions` 判那四篇笔记的出身）。

### 这一批的实际成本

**模型调用 0 次、0 token。** 10.3 的数量全部量在已经存在的 470 篇笔记上，
R1 的复现是真 registry + 打桩端点（零网络），R2 的分母是从 `Mode.focus_groups`
× 工具注册表算出来的**结构性 0**。验收靠 27 条突变验（每条一次 targeted
`pytest -x`，跑前后清 `__pycache__`）+ 后端 / 前端各两次全量闸。

### 下一步

1. **三条判据的量程要不要收，是一件独立的事。** 10.3 只报不改是对的，但它报出来
   的东西得有人接：`no_restated_paragraph` / `no_fake_charts` 完全没有量程、
   `no_repeated_lists` 的量程在打磨轮会消失。收之前要先答一个问题——
   **修订那条线能不能改掉「上一次跑写进用户笔记里的重复」**？答得出来才知道
   收量程是止损还是丢真阳性（批 21 的 A 就是这么过来的）。
2. **`criteria_drift.py` 要定期跑，而且下一次跑之前不要动 `.local` 那份基线。**
   它现在只有一份快照，「变了多少」这一栏第二次跑才有内容。
3. **`harness_rounds.depth_dropped` 今天一行数据都没有**（这一批零真跑）。
   攒出来之后能第一次回答「深度门是不是太狠」——那条规则从写下起就没有任何数。
   同批 23 的 `RUN_TOKEN_CAP` 一样：*从来不开火* 和 *拦不住真正该拦的* 在数据上
   长得一模一样。
4. **`st.steer` 在长文模式里是个死字段**（计划外发现 3）。要么接上、要么删掉，
   但别留着——一个每轮都算、没人读的字段，下一个人会以为诊断已经喂回去了。
5. 阶段 10 / 11 / 12 到这一批全部做完。剩下的是 **9.2（judge-vs-人 一致率）**
   和 **9.4（judge 模型槽）**，两条都在等 9.1 攒样本，而 `harness_edits`
   到今天仍然是 **0 行**——**它只会在真实用户真的改了 AI 写的正文之后才长**，
   跑批脚本按设计一条都采不到。

---

## 批 25 · 批 24 留下的四条 + 一条口径（2026-09-18）

**这一批一次模型调用都没发。** A 的先决问题用代码 + 库里的数答的（`harness_rounds`
380 个 note 轮次、`note_revisions` 44 行、`criteria_drift.py --show` 逐条读原文），
三处碰真库都只读、夹在 `db_guard.Watch()` 里、**命令不经过任何管道**、单独打
`EXIT=$?`。验收靠 **23 条突变验**（**3 条第一版没抓住**）+ 全量闸。

**五条的处置：A 的先决问题答「够得着」，所以三条判据分头处置——两条收、一条
故意不收，并且顺手数出了同一处机制的第二个调用点；B 量完发现它既不该接也不是
死字段，删掉的是那一份重复；C 扫出 1 条，实拍全套闸绿着；D 两条豁免都是死的，
一起清掉并加了一条查豁免的闸；E 写进两处。**

---

### A —— 先答先决问题：**修订那条线够得着**

批 24 只报不改，但留了一句话：三条判据的量程要不要收，得先答
**「修订那条线能不能改掉上一次跑写进用户笔记里的重复」**。答案是**够得着**，
三处证据，一处都不是推理：

1. **代码。** `middleware/revise.py` 对一条修订的锚点**只有一个限制**：
   `anchor not in st.content` 就跳过；而 `st.content` 在开跑那一刻**就等于整篇
   笔记**（`loop.py`：`st.bag["content_at_start"] = st.content`）。全趟唯一两处
   按「这段字是谁写的」做判断的地方是 `outline_mode`（大纲笔记里用户自己写的标题）
   和递进提示词的 `defect_lines`（审计腔那一半，批 21 收过）。
   喂给修订的三个信号 `dup_hints` / `focus` / `focus_note` **一个都没有量程**。
2. **库里实拍过反向的后果。** `e78306202d78` 的 `note_revisions` 记着
   1976 → 1843 → 664 字，而开跑时它是 1976——批 14 那场事故里
   **1326 字用户自己写的内容被这条线删掉了**。「够得着上一次跑写的」是
   「够得着开跑前所有的字」的真子集。
3. **那条门本来就没关。** `middleware/repeats.Repeats` 每轮**两次**把
   `find_repeats(st.content)` 放进 `bag["dup_hints"]`，整篇算、没有量程——
   开跑前就有的重复本来就每轮都在递给修订那一步和打分器。
   这三条判据的量程根本不是挡住它的那道门。

**所以不能一刀切。** 够得着意味着收与不收都有代价，得逐条看
「误伤了没有」+「它的修法落在谁身上」。

#### 逐条读（自己跑的 `--show`，不是抄批 24）

批 24 那张表里四篇笔记、两组数加起来是 4 不是 3——核对下来是因为
`06647b9c2031` **同时**命中 `no_repeated_lists` 和 `no_restated_paragraph`，
所以 3 + 1 + 1 落在 4 篇上。三条各自的 `user whole` 是 **3 / 1 / 1**。

| 判据 | 笔记 | 读出来是什么 | 判 |
|---|---|---|---|
| `no_repeated_lists` | `92d07b760f1e` | 「录制信任、关联即时反馈、总结行动化、图谱自维护」在「挑战」和「下一步」各写一次——**一次正常的回指**。这篇 `harness_runs` **0 行、`note_revisions` 0 行**，只可能是用户自己写的 | 误伤 |
| | `e78306202d78` | 「录后自动分发、自动摘要、直达共创群与案例库」逐字两遍。当前正文 1976 字 = `updated_at` 2026-09-02 那一版，已经还原回用户原文 | 误伤 |
| | `06647b9c2031` | 「4 月下旬至 5 月上旬**进入**…」／「…**完成**欧美数据最小化、存储位置、删除权三条基线评审」，中间夹着四个空行 | 真缺陷 |
| `no_restated_paragraph` | `06647b9c2031` | 「…改良包装。下一轮 10 台到货为 6 月 15 日… KLR 包装，现需求上周发生变更需改良包装。下一轮…**装。**下一轮…」——**从词中间接上的**，前面顶着八个空行，36% 的正文是段内重复。`script` 那两篇（soak / bench 产出）是同一个形状 | 真缺陷 |
| `no_fake_charts` | `3a3a96354546` | 「用户在页面停留的路径已经测出来了：先看硬件参数 → 跳到软件功能列表 → 回到定价 → 退出。」——**一句正常的叙述**，而判词要求把它换成一张图，每一次跑要求一遍 | 见下 |

#### 三条各自的处置

**① `no_repeated_lists` —— 收。** 它的量程**本来就有**，docstring 写着
「用户原来正文里就有的重复不该每轮都报一次」——坏的只是绑在
`st.fresh` 上。换成 `content_at_start` 之后**两个方向都更准**：

* 打磨轮 / 只清理轮从「`if fresh and …` 短路 → 整篇都报」收成「只报这次跑碰过的」；
* 写作轮从「只认追加的那段字」扩到「认这次跑写的字」——**修订就地改出来的清单
  不在 `st.fresh` 里**，旧口径整档漏掉（`revise.py` 末尾那段注释记着同一个形状）。

代价是 `06647b9c2031` 那处真缺陷在**下一次**跑里不再被这条报。**它没有掉出网**：
同一篇上 `no_restated_paragraph` 照样开火（下面那条故意不收）。

**② `no_fake_charts` —— 收。** 三条依据，一条比一条硬：

* **它的孪生兄弟早就收了。** `charts_from_tools` 判同一维的另一面，量程写的正是
  `mermaid_blocks(st.bag["content_at_start"])`，理由是第 604 轮真跑——用户自己画的
  两张合法流程图被修订整个删掉，删完这一条又报「这条流程是用箭头串在正文里的」，
  **删图和要图来回打架**。两条判据打同一维、一条收了一条没收，正是「挡住一半」。
* **判词第一句是假的。** 「**这一轮**没有真的画图」——对着开跑前就躺在笔记里的
  一句叙述说这话，是在报一件没发生的事。
* **这一维在长文里排不出修复轮。** `note` / `section` 的 `dims` 里既没有
  `has_charts` 也没有 `chart_validity`，`pick_dimension` 落到 `checks.pick.MECHANICS`
  兜底桶，那个桶按设计不在 `repair.INNER_QUALITY` 里。开跑前就有的那一处
  **既修不掉也停不下来**，只会每轮短路一次打分。

实现上两侧都要不设上限（突变验 A-M5a / A-M5b，两个坑方向相反：豁免名单被默认
上限截断 → 第四张旧图被当成新的误报；正文那侧被截断 → 第四张新图漏报），
箭头链**两边都过一遍 `text_flow` 再比**，不是拿结果去 `before` 里搜——
它返回的是空白规范化 + 截到 80 字之后的串（突变验 A-M6）。

**③ `no_restated_paragraph` —— 不收，并且把「它还会开火」钉成断言。** 三条依据：

* **0 误伤。** 18 篇上开火 1 篇，读出来是不折不扣的机器损伤；`script` 那 2 篇同形状。
* **它是唯一够得着这一类的判据**，而这一处损伤**是上一次跑留下来的**——
  按先决问题的答案，修订那条线改得掉。收了量程就再也没人报它。
* **`RESTATED_RATIO = 3%` 是在「整篇」这个分母上量出来的**（18 篇真产出、
  15 篇精确 0.0%）。换成「只数这次跑写的那部分」，分母变了，3% 在新口径上
  **一次都没量过**——§20④：收窄哪一侧都要有据。

`tests/test_check_scope.py` 里那条断言直接写着「这不是笔误就去读它的 docstring」，
`tests/test_criteria_drift.py` 的「没有量程的判据在 stale 那一档也会开火」
也把样本从 `no_repeated_lists` 换成了它——**谁顺手统一一下，两处同时红**。

#### 计划外：同一处机制的**第二个调用点**

会消失的那个量程一共两处，两边逐字一样的 `if fresh and a not in fresh and …`：
`blockcheck.repeated_lists` 和 `citations.same_sources_twice`。
后者在这份语料上**一次都没开过火**（`alive=False`，分母 0）。跟着改的理由不是数据，
是「同一件事挡住一半等于没挡」——修一处留一处，下一次踩的就是留下的那处。
**分母为 0 不是「不改」的理由**：那条理由（批 22 的 R2）只对「加一条谁也证明不了
它在挡什么的守卫」成立，对「一个已经证明会失效的机制的第二个调用点」不成立。
另加一条闸扫 `checks/` 里 `st.content, st.fresh` 这个形状，一条都不许再有。

#### 入口自己报出了这次改动

改完重跑 `criteria_drift.py`，「跟上次跑比」那一栏（批 24 存的基线）直接说出了它：

```
no_repeated_lists   user stale: 3 → 0     script stale: 1 → 0     fixture stale: 1 → 0
no_fake_charts      user stale: 1 → 0
```

**`whole` 一个数都没动**（3/18、1/18 照旧）——收的是量程，不是判据本身。
`no_restated_paragraph` 的 1/18 stale 还在，报告里照旧把它列进「该看的」。

---

### B —— `st.steer`：**先量，量完发现两条路都不对**

台账（批 24 计划外发现 3）写的是「要么接上要么删掉」。先量：

| | |
|---|---|
| 库里 `note` 轮次 | **380**（`section` 一轮都没有——那一半的分母是 0，据实说） |
| `st.steer` 会非空的轮次 | **351 = 92.4%** |
| 落点 | `factual_grounding` 226 · `non_repetition` 99 · `spine_fidelity` 10 · `beat_coverage` 7 · `mechanics` 5 · `coherence` 3 · `material_use` 1 |
| 诊断类别 | **material（检索改善得了）66.7% · 内在质量（走修订）29.1%** · 其它 10 · 兜底桶 5 |
| 其中判据短路轮 | **244 / 380 = 64.2%**——这些轮次的 `st.ev` 是伪造的单维 0 分，「诊断原话」其实是 `Verdict.message` |

**量完的结论是两条路都不对**：

* **接不得。** 那 92.4% 里的诊断**早就到了修订那一步**——`loop.py` 紧挨着的两行把
  同一个 `st.ev` 的同一句话存进了 `bag["focus"]` / `bag["focus_note"]`，而
  `revise.py` 逐个读它们。再接一遍是同一句话喂两遍。要接进**检索规划**的话，
  批 22 划的线是「只有 material 类诊断能进」，`policy.steer` 已经按 `MATERIAL_DIMS`
  过滤过了——绕开它接一条没过滤的，正好是那条线要挡的东西（内在质量那 29.1%）。
* **删不掉。** `hooks/block.produce` 真读它（块模式每轮整块重写，没有 policy、
  也没有修订那条线，这句诊断是它唯一的回路），`middleware/provenance` 也读它
  （批 24 的 12.1 刚接的面板）。

所以台账那句「写了没人读」本身就不准：**它不是一个空字段，是一份重复的字段**。
删掉的是那一份重复：

* `State.steer` 从一个 dataclass 字段变成**只读属性**，当场从 `bag` 那份算出来；
* `loop.py` 每轮那次 `st.steer = _steer(st)` 和 `_steer()` 本身删掉（**循环结构没动**，
  删的是一行赋值，原地留了一段注释说去哪儿了）；
* `snapshot` 里 `"steer"` 那个键去掉——`bag` 本来就整份存着，存两份的话恢复出来的
  两份可能说的不是同一句话，而谁都不知道该信哪个。

唯一的行为差别：打分器给出了维度名、却给了一句**空**诊断时，旧的返回
`"non_repetition: "`（`hooks/block` 会挂一个没内容的小标题），现在返回空串。

「算了没人用」变成了两条闸：一条钉住 `st.steer` 跟 `bag` 那份同源、而且**存不进去**
（想再存一份独立的当场 `AttributeError`），一条钉住 **`st.steer` 在 `hooks/` 下的
读者只有 `block.py`**——`hooks/note` 或 `hooks/section` 谁把它接进 prompt，当场红，
并在断言里写清该走 `policy.steer`（过滤过的）还是 `bag['focus_note']`（修订那条线）。

---

### C —— 「断言在别处顺手被满足」的同族排查：**扫出 1 条**

判据写得窄：只找 `assert <针> in <草堆>`，而且要求**那根针同时也被当成输入喂进了
系统**（针的字面量是同模块里另一个字面量的子串，或者它所在的素材在同一个测试里
被当成实参传出去过）——「输出里出现了我喂进去的那句话」正是这个形状的前提。

两轮筛：AST 扫全部 145 个测试文件先得 **104 条**；去掉「针是标识符」和
「草堆是源码文本」（那是 grep 闸，针在源码里正是它的目的）之后剩 **21 条**；
逐条读完，只有 1 条真的是这个形状。

**`tests/test_claims_grounding.py::test_编造的日期和署名会被抓住`。**
`checks/claims.unsupported_specifics` 每点名一个原子，就顺手把**它所在的整句**
也引进诊断（`f"「{a.surface}」（出现在：{unit}）"`），而那一句里
日期和署名都在。断言写的是 `"2027 年 4 月 9 日" in v.message and "Speaker K" in v.message`
——实拍：`v.message.count("Speaker K") == 3`，其中两次来自两条「出现在：」。

**实拍撤掉修复**：`atoms()` 里的 `out += attributed_atoms(unit)` 换成 `out += []`
（署名类原子整个不抓），**全套 1887 条闸一条都没红**。
断言收到只有点名那一行造得出来的形状（`「Speaker K」`）+ 点名的个数
（`count("（出现在：") == 2`），再撤修复当场红（突变验 C-M1 / C-M2）。

另外 20 条**都不是**，逐条的理由：

* **11 条**出自 `dimension_sensitivity_bench`（植入器自验：注入一个缺陷之后
  「别的小节原样还在」）。草堆只有一个产出者——那个植入器本身，没有第二条路径
  能把那段字放回去。
* **7 条**的针是输入、草堆是同一个函数的返回（`claims.sources()` /
  `score_context.material()` / `restructure.apply_ops()` / `prompts.magic_tap_user()` /
  `structure.heading_fits` 的 fix），同样是单一产出者；而且旁边都另有结构性断言
  （`len(items) == 4`、`prompt.index("续航实测") > prompt.index("[Content]")`、
  `content_drift(md, out) == ""`）把「原样还在」以外的那一半钉住了。
* **1 条**是扫描器自己的假阳性（`test_harness_ledger` 那条的针是
  `gap_summary` **造出来**的字符串，根本不是喂进去的）。
* **1 条**是我这一批刚写的。

**一条没凑数，也一条没为了凑数去改正常测试。**

---

### D —— `test_event_contract` 里的两条死豁免

`missing -= {"warning", "check_hit"}`，注释说「warning 是给开发看的诊断，
前端不展示」。而 `frontend/src/api.ts` 里这两条分支一直都在
（`payload.name === 'check_hit'` / `=== 'warning'`，第 1210–1211 行），
取名字的那条正则也取得到——**减不减一模一样。台账只记了 `check_hit`，
实际上 `warning` 是同一回事。**

清掉的不只是那一行：留下一个空的 `NOT_ON_SCREEN`，外加一条查它的闸——
**豁免了一条前端其实接得住的事件，当场红**（另一半：豁免了一条后端根本不发的，
也红）。一条永远不生效的豁免读起来像「这个事件前端没接」，
下一个人会照着它去补一个已经存在的分支，或者反过来把真接上的那条删掉。

---

### E —— 口径：**这个仓有两份笔记库**

| | 跑批 / `criteria_drift` 量的 | 装起来用的桌面 app |
|---|---|---|
| 路径 | `backend/data/notes.sqlite3` | `~/Library/Application Support/memoket-note-desktop/data/notes.sqlite3` |
| 谁指过去的 | `db_guard.DEFAULT_DB` = `corpus_lineage.DB_PATH` | `desktop/src/main.ts` 在 `app.isPackaged` 时传 `KITE_DATA_DIR`（理由写在 `app/util/config.py`：相对路径会落进 .app 包内部，而 macOS 更新时整个包被替换） |
| 体量 | **482 篇 / 321,250 字** | **62 篇 / 144,870 字 / 最后改于 2026-09-18** |

差了将近八倍，而**在这一批之前仓里一个字都没写过这件事**。后果很具体：
`criteria_drift` 报的「18 篇 `origin=user` 上开火 5 篇 = 27.8%」的分母是**开发库**
那 18 篇，读成「用户在 app 里看到的笔记有 27.8% 带审计腔」是一句错话。
（开发时 `app.isPackaged` 为假、不传 `KITE_DATA_DIR`，所以 `--probe` 连拍跟跑批
量的是同一份——**只有装起来用的那个 app 不是**。）

写进两处：`harness-framework.md` 新开 **§18.1**，`criteria_drift.py` 的模块开头。
并且**把「怎么量另一份」变成真的能用**：加了 `--db <路径>`，换库时先打一行
「这一次量的不是默认那份开发库」；`Watch` / `readonly` 跟着走那一份——
换了库还去核对默认那份的指纹，等于一边量着 A 一边替 B 作保，
而 B 这一趟根本没被打开过，它当然「没变」。**没有去读 app 那一份。**

三条闸：入口自己得说清它量的是哪一份（`memoket-note-desktop` / `KITE_DATA_DIR`
逐字在源码里）、`Watch` 看的必须是这一次真要量的那份库、文档里那条完整路径
和两个体量数得在一起（突变验 E-M4 抓住了第一版：我自己那条断言写的是
`"memoket-note-desktop" in doc`，而那个词在前后文里也出现，**删掉路径那一行照样绿**
——这一批刚扫完「在别处顺手被满足」，转头自己又写了一条）。

---

### 突变验（23 条，23 条变红——**3 条第一版没抓住**）

**基线 1871 绿 / 前端 263 绿。** 每条单独改坏，跑目标用例，跑前后都清 `__pycache__`。

| # | 把什么改坏 | 结果 |
|---|---|---|
| A-M1 | 量程传回 `st.fresh`（调用点那一侧） | ✅ |
| A-M2 | 两处清单里任意一处是旧的就跳过 | ✅ |
| A-M3 | 量程整个不过滤 | ✅ |
| A-M4 | `no_fake_charts` 不排除开跑前就有的 | ✅ |
| A-M5a | 豁免名单那一侧用默认上限（第四张旧图被当成新的） | ✅（**第一版没抓住**） |
| A-M5b | 正文那一侧用默认上限（第四张新图被挤掉） | ✅（**第一版没抓住**） |
| A-M6 | 箭头链拿结果去 `before` 里搜，不两边都过 `text_flow` | ✅（**第一版没抓住**） |
| A-M7 | 顺手把 `no_restated_paragraph` 也收了量程 | ✅ |
| A-M8 | `same_sources_twice` 的量程留在 `st.fresh` 上（只修一半） | ✅ |
| A-M9 | `no_fake_charts` 的量程在校准入口那一档失效 | ✅ |
| B-M1 | `st.steer` 恒空 | ✅ |
| B-M2 | `st.steer` 自己编一句，不读 `bag` | ✅ |
| B-M3 | `steer` 改回一个存得住的字段（两份载体又回来了） | ✅ |
| B-M4 | `hooks/note` 自己去接 `st.steer`（绕过 `MATERIAL_DIMS`） | ✅ |
| B-M5 | 快照里把 `bag` 的 `focus` 丢掉 | ✅ |
| C-M1 | 署名类原子整个不抓 | ✅ |
| C-M2 | 只点名第一个原子 | ✅ |
| D-M1 | 把 `check_hit` 放回豁免名单（死豁免又回来了） | ✅ |
| D-M2 | 前端删掉 `check_hit` 那条分支 | ✅ |
| E-M1 | 入口不再说清它量的是哪一份库 | ✅ |
| E-M2 | `Watch` 回到写死的默认库 | ✅ |
| E-M3 | `readonly` 回到写死的默认库 | ✅ |
| E-M4 | 架构文档里把两份库那一段删掉 | ✅（**第一版没抓住**） |

**三条第一版没抓住，三条都是用例不够**（连着十七批了）：

* **A-M5a / A-M5b**：只钉了一侧。那两个坑**方向相反**——豁免名单被截断是
  *误报*，正文侧被截断是*漏报*，一个用例挡不住两个方向。
  *一条判据两侧各有一个上限，就得两侧各有一个用例。*
* **A-M6**：素材写得齐齐整整，`text_flow` 规范化前后一模一样，那条缝一个用例都够
  不着。素材改成箭头两边空格不齐（真实 markdown 就长这样）之后当场红。
  *一个只在「输入不规整」时才存在的差别，用规整的素材验不出来。*
* **E-M4**：**我自己写了一条「在别处顺手被满足」的断言**——`"memoket-note-desktop"
  in doc` 被前后文顺手满足了。改成钉那条只有那一段写得出来的完整路径 + 两个体量数。
  *刚扫完一条同形状的，下一个文件里自己又写了一条。*

---

### 闸

后端 **1871 → 1888**（+17）：`test_check_scope.py` 新建 **12** 条、
`test_criteria_drift` +2、`test_why_this_round` +2、`test_event_contract` +1；
改断言的有 `test_blockcheck` / `test_grounding_check`（量程参数换名）、
`test_harness_resume`（诊断改走 `bag`）、`test_claims_grounding`（C 那条收窄）、
`test_criteria_drift`（「没有量程」的样本从 `no_repeated_lists` 换成
`no_restated_paragraph`）、`test_why_this_round` 的 `_st()`（`focus` / `focus_note`
走 `bag`，不再手工维持两份载体的一致）。前端 **52 个文件 263 条，一条没动**。

`harness-framework.md`：新开 **§18.1**「量的是哪一份笔记库」、§20④ 补
「该不该收是逐条的事」那一整段（含三条的处置表和依据）、§21 三行各补一段
（「建了判据不等于用了判据」的第三个变体「算了没人读」、「同一件事挡住一半」
第七种形态、「在别处顺手被满足」第六次）。
**Mode / 工具 / check / middleware 四个数一个没动**，`test_doc_counts` /
`test_directory_map` 照绿。

---

### 计划外发现

1. **`no_same_sources_twice` 是同一个量程 bug 的第二个调用点**（批 24 没点到它，
   因为它在这份语料上一次都没开过火）。跟着改了，理由是机制不是数据。
2. **`test_event_contract` 的死豁免是两条不是一条。** 台账只记了 `check_hit`，
   而 `warning` 在 `api.ts` 里同样有分支——两条都是死的。
   *一条豁免的注释说的是「为什么豁免」，不是「豁免有没有生效」。*
3. **台账把 `st.steer` 说成「写了没人读」，不准。** 它有三个读者
   （`hooks/block.produce` 功能性、`provenance` 面板、`snapshot` 持久化），
   而且非空率 92.4%。真正的问题是**同一句诊断有两个载体**，而其中一个在长文
   模式里没有功能读者。「要么接上要么删掉」这个二选一是照着一个不准的描述提的，
   **先量一次就换了个问题**。
4. **`criteria_drift` 的基线文件只有一份，换库跑会盖掉。** 加 `--db` 的时候撞上的，
   写进了模块文档（换库要么配 `--no-save`）。

---

### 开工前后的 `notes` 指纹（自己核对过，不是自报）

|  | 开工前（= 批 24 收尾） | 收尾 |
|---|---|---|
| `notes` 行数 | 482 | **482** |
| `notes` `max(updated_at)` | `2026-09-16T02:53:27+00:00` | **`2026-09-16T02:53:27+00:00`** |
| 正文总字数 | 321,250 | **321,250** |
| 482 篇逐篇摘要再取一次摘要 | `47dcc54be60aa4f2` | **`47dcc54be60aa4f2`** |
| `note_revisions` 行数 | 44 | **44** |
| `harness_edits` 行数 | 0 | **0** |

**逐字相同**（`diff` 退出码 0）。这一批**一次跑批都没有**（零模型调用）。
碰真库的三处都只读、夹在 `db_guard.Watch()` 里、**命令不经过任何管道**、
单独打印 `EXIT=$?`：A 的血缘核对查询（`harness_runs` / `note_revisions` / `notes`）、
B 的 `harness_rounds` 分布查询、`criteria_drift.py`（含三次 `--show` 逐条读原文）。
**没有读也没有写 `~/Library/Application Support` 那一份。**

### 这一批的实际成本

**模型调用 0 次、0 token。** A 的先决问题答在代码 + 462 行 `harness_rounds`
+ 44 行 `note_revisions` 上，B 的分布量在 380 个已有 note 轮次上，
C 是静态 AST 扫 145 个测试文件 + 一次全量突变实拍。
验收靠 23 条突变验（每条一次 targeted `pytest -x`，跑前后清 `__pycache__`）
+ 后端 / 前端各两次全量闸。

### 下一步

1. **`no_restated_paragraph` 的「不收」是有到期条件的。** 它今天成立靠的是
   「1 篇命中、0 误伤」，而 n=1。下一次跑 `criteria_drift` 如果它的 `user whole`
   长出误伤来，`RESTATED_RATIO` 那个 3% 就得**先在「只数这次跑写的」这个新分母上
   重量一遍**，再谈收量程——换分母不重量门槛，是拿一个没量过的数当判据。
2. **`.local/criteria_drift/latest.json` 这次被批 25 的数字覆盖了**（那正是它的用途：
   「跟上次跑比」那一栏第一次有内容，而且直接报出了这次改动）。
   下一批之前别再动它，也别用 `--db` 跑一次把它盖成另一份库的数。
3. **`section` 模式的轮次库里一行都没有**（B 的分布全部来自 380 个 note 轮次）。
   `st.steer` 在 `hooks/section` 上「没有功能读者」这一条是**读代码**得出的
   （`SECTION.extra_mw` 里没有 `Runtime`），不是量出来的——那一半的分母是 0。
4. **`harness_rounds.depth_dropped` 到今天仍然 0 行**（批 24 的下一步 3，这一批
   同样零真跑）。`harness_edits` 也仍然 **0 行**——它只会在真实用户真的改了 AI
   写的正文之后才长。**9.2 / 9.4 还在等这两张表。**
5. **C 那个扫法可以留成一条常跑的闸吗？** 这一批是一次性脚本（AST 扫 → 人读 →
   突变验）。要变成闸的话，唯一靠得住的判准是**突变**（把被测那一半停掉看断言红不红），
   而那是全量突变测试，成本另算。先记在这儿，别在没量过成本之前接上去。
