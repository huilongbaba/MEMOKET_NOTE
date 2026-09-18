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
