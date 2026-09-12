# 知识库抽什么：可选、可自定义的「抽取偏好」方案

> 用户 2026-09-12 提的：KITE 抽出来的「要点」应该是用户可配置的——① 让用户选，② 用户自定义——
> 不同人记的东西不一样，一套规则满足不了所有人。这份是方案，不改代码；落地另等指令。
> 前提读物：`kite-constraints.md` §5 / §12（profile 写死、只能按锚点打补丁）、`kb-fusion-design.md`
> §3.4.1（笔记 ↔ 知识库链接层，「同步 = 删旧 session 重抽」是本方案「按新偏好重抽」的基础）。

## 0. 现状：「要点」是怎么定的

抽取走 `memoket_kite.pipeline.extract.extract_facts(vocabulary, profile, ...)`，profile 是进程级
全局对象 `DEFAULT_MEMORY_PROFILE`，决定三件事：

| 什么 | 现在 | 在哪 |
|---|---|---|
| **抽什么** | 一句话：「Capture durable information that may matter in a later conversation. Write one self-contained claim per fact; do not infer information not stated.」 | `prompts/extract.py` `_FACT_EXTRACTION_BASE_PROMPT` |
| **要点类型 kind** | 固定 7 种：event · plan · preference · identity · relationship · opinion · other；模型给的不在这 7 个里就落成 other | `defaults.py` `KINDS`；`pipeline/extract.py:223` 校验 |
| **附加面** | topics（受控词表 + 提议子主题）· entities · facets（object / place / event / duration）· who · t · conf | 同上 |

我们这边（`database/kite/kite_extract_profile.py`）用字符串锚点给 prompt 打了四个补丁（中文不翻译、主题要具体、
ASR 误听归一、置信度校准），`UserMemory.remember(profile=)` 在持锁期间临时替换 `EXTRACT_PROMPT`、用完还原。
**没有任何一处是用户能碰的**：会议纪要用户想要「谁承诺了什么、截止日」，日记用户想要「情绪 / 关系 / 习惯」，
研究阅读用户想要「论点 / 数据 / 出处」，现在都只能拿到同一套「durable information」。

## 1. 概念：抽取偏好（Extraction Profile）

一个抽取偏好 = **这个用户眼里什么算一条要点**。三部分，都是可读的文本 / 列表，不是代码：

```
抽取偏好
├─ 要点类型 kinds      每种一个短代码 + 中文名 + 一句定义（决定 kind 字段的取值）
├─ 关注 focus          几条中文规则：什么一定要单独记一条、怎么记（带截止日 / 带负责人 / 带数据）
└─ 忽略 skip           几条中文规则：什么不记（寒暄、复述、临时口误…）
```

跟「写作 Skill」是同一种东西的另一个作用域：可开关、可排序、可自建、可 AI 生成，多个叠加。
区别在于 kinds 是**结构化**的（要进 XML 的 `kind` 属性、要进检索的过滤器），不能只是一段提示词。

### 1.1 让用户选：预设

| 预设 | kinds（在通用 7 种之上加的） | 关注 | 忽略 |
|---|---|---|---|
| **通用**（现状） | 无 | 现有一句 | — |
| **会议纪要** | decision 决定 · action 待办 · commitment 承诺 · risk 风险 · question 待定 | 每个待办单独一条，带负责人和截止日；改了的决定记「从 X 改到 Y」；数字带单位 | 寒暄、复述上一句、会议流程话（「下一个议题」） |
| **个人日记** | emotion 情绪 · habit 习惯 · health 身体 · relationship（已有） | 情绪要带触发它的事；习惯记频率；身体状况带日期 | 天气之类没有后续价值的 |
| **研究 / 阅读** | claim 论点 · evidence 数据 · source 出处 · question 待查 | 论点和支持它的数据分开记、互相引用；出处记书名 / 作者 / 页 | 作者的修辞、过渡句 |
| **客户 / 用户访谈** | pain 痛点 · need 需求 · quote 原话 · objection 异议 | 痛点记场景不记评价；原话逐字，带说话人 | 我方的介绍、引导性问题 |
| **项目管理** | milestone 里程碑 · risk 风险 · change 变更 · blocker 卡点 | 里程碑带日期；变更记前后值和原因 | 已经在别处记过的静态背景 |

预设可以**同时启用多个**（会议 + 项目），叠加 = kinds 取并集、focus / skip 拼接。第一次导入或第一次
「存入知识库」时问一句「你的记录主要是什么？」——三个按钮选一个预设，比让人去设置页找强。

### 1.2 用户自定义

- **改预设**：任何预设点「编辑」都变成自己的一份（内置的不动，跟 skill 一样）。
- **新建**：填名字、要点类型（代码 + 中文名 + 定义，可空 = 只用通用 7 种）、关注、忽略。
- **AI 生成**：写一段「我是做什么的、我的记录里最想以后能找回来的是什么」，模型出一份偏好草稿
  （复用 `POST /api/skills/generate` 那条路：`skill_generate_system` 换成抽取版）。
- **试抽**：设置页底下一块「拿这段试试」——贴一段文字（默认取当前打开的笔记前 3000 字），按当前偏好跑一次
  抽取**不入库**，列出会得到哪些要点、每条什么 kind；旁边一列「不用偏好会抽出什么」对照。
  没有这一块，用户改了规则也不知道改对没有——这是整个机制里最重要的一个按钮。

## 2. 机制：怎么接进 KITE

### 2.1 prompt 拼装（不改 KITE 包）

`kite_extract_profile.build_profile(user, *, override=None) -> type`：返回 `_PatchedProfile` 的一个子类，
在现有四个补丁之上再做两件事：

1. `KINDS = 通用 7 种 + 启用偏好里所有自定义 kind 的代码`（去重、保序）。
2. `EXTRACT_PROMPT` 在 `Rules:` 段末尾（`"src":` 那条之后、`Add retrieval facets` 之前）插一段：

```
- "kind" glossary: event=…, plan=…, decision=一条被拍板的决定, action=一条待办（带负责人和截止日）…
WHAT THIS USER WANTS REMEMBERED (follow these before the generic rule above):
- 每个待办单独一条，带负责人和截止日
- …
DO NOT RECORD:
- 寒暄、复述上一句
```

规则原文是中文就原样放（模型双语没问题，翻译反而失真）。总长封顶 1200 字，超了截断并在设置页提示。
插入用**锚点**（`- "src": one or more message IDs that directly support the fact.`），锚点找不到就
warn + 退回不插（跟现有补丁同一条纪律，`kite-constraints.md` §12）。

### 2.2 替换点

`UserMemory.remember(profile=)` 现在只换 `EXTRACT_PROMPT` / `EXTRACT_PROMPT_NO_FACETS`，**加换 `KINDS`**
（三者都在持锁期间 setattr、finally 还原——`pipeline/extract.py:223` 的 kind 校验读的就是这个全局，
不换的话自定义 kind 会被打成 other）。调用方三处都传 profile：

| 调用方 | 用哪份偏好 |
|---|---|
| 笔记「存入知识库」/ 同步（`routers/ingest.py`） | 这篇笔记的覆盖偏好（§2.4）→ 否则用户默认 |
| 批量导入 / 导入源（`routers/import_sources.py`） | 这次导入对话框里选的（默认记住上次的） |
| 手工加事实（`POST /api/kb/fact`） | 不走抽取，kind 由用户在表单里选（下拉列出当前 KINDS） |

查询侧：`prompts/recall.py` 的 planner 也读 `KINDS`（`KINDS: {kinds}`），自定义 kind 要能当过滤条件用，
`UserMemory._reasoner()` 那条路也要装同一份 `KINDS`（只加不减，多出来的 kind 对 planner 无害）。

### 2.3 存储

新表 `extract_profiles`（跟 `skills` 平行，不复用——kinds 是结构化的）：

```
extract_profiles(user_id, slug, name, kinds_json, focus, skip, enabled, position, builtin, updated_at)
provider_config.extract_onboarded   INTEGER   第一次问过「你的记录主要是什么」没有
notes.extract_profile               TEXT      这篇的覆盖（slug，空 = 用默认）
```

内置预设在代码里（`database/kb/extract_presets.py`），首次访问按用户种进表（跟 skill 种子一样），
用户改的是自己那份；升级预设文案不覆盖用户改过的。

### 2.4 覆盖粒度

- **全局默认**：启用的那几份叠加。
- **按笔记**：引用页（NoteKbPanel）顶部一个下拉「这篇按：默认 / 会议纪要 / …」，改了就提示「按新偏好重抽」
  （= 现有同步：删 `note-<id>-*` session 重抽，手工事实保留）。
- **按导入**：导入对话框（.md / vault / Notion / 飞书 / 批量）多一个下拉，默认上次选的。
- 不做「按主题 / 按文件夹」：多一层规则用户记不住，先看这两层够不够。

### 2.5 试抽（dry-run）

`POST /api/kb/extract/preview {text, profile_slugs?, compare: bool}`：直接调
`memoket_kite.pipeline.extract.extract_facts(vocab, profile, messages, ...)`（它是纯函数，不落盘；
`kite_extract_profile` 的 docstring 已经确认过这是唯一接受 profile 参数的入口），跑一次（compare=true 跑两次，
一次通用一次带偏好），回 `{facts:[{text, kind, who, t, conf}], baseline?: [...]}`。不建 session、不动 XML，
所以不用写锁；一次 LLM 调用约 13s，界面给进度和「大概 15 秒」。

### 2.6 自定义 kind 的显示

知识库各页的 kind chip 现在直接显示代码（`plan` / `event`）。加一张 `kind_labels`（从用户的偏好里汇总
code → 中文名），`pages.annotate()` 顺手带 `kind_label`；事实表的「全部类型」下拉列出当前用户所有出现过的
kind（不只是 7 种）。`_INSTANCE_SKIP_KINDS`（KITE 内部对齐实例时跳过 preference / opinion 等）不认识
自定义 kind，把 emotion / habit / quote 这类「不可计数」的也加进去——这一条在包里，先用 monkeypatch，
和 §4 的 PR 一起交上游。

## 3. 界面

新特殊笔记 `app:extract`（树底部「设置」旁，叫「知识库抽什么」），照「写作 Skill」页的样子：

```
知识库抽什么
每条偏好告诉知识库「什么算一条要点」。可以叠加几份；改完拿一段文字试试。      [+ 新建] [AI 生成]

[● 已启用] 会议纪要   内置                                    ↑ ↓ ✎ ✕
  决定 · 待办 · 承诺 · 风险 · 待定 | 每个待办单独一条，带负责人和截止日；…
[○ 已停用] 个人日记   内置
…
拿这段试试                                       [用当前笔记] [试抽（约 15 秒）]
┌────────────────────────────────┐ ┌────────────────────────────────┐
│ 按当前偏好                      │ │ 不用偏好                        │
│ [待办] 王工下周三给通信测试报告   │ │ [plan] 王工负责补通信模块测试报告  │
│ [决定] 电池容量从 300 改到 380   │ │ [event] 电池容量改为 380mAh      │
└────────────────────────────────┘ └────────────────────────────────┘
```

第一次导入 / 第一次「存入知识库」弹一次：「你的记录主要是什么？ [会议纪要] [个人日记] [研究阅读] [都有一点]」，
选了就启用对应预设，「都有一点」= 通用 + 会议。以后不再问（`extract_onboarded`）。

## 4. 上游（memoket-kite）该改的

现在的替换靠 setattr 全局对象 + 写锁保证串行（`kite-constraints.md` §12），能用但脆：

1. `Memory.remember(..., profile=None)` 正式接受 profile 参数，透传给 `extract_facts`——去掉全局替换。
2. `extract_facts` 作为公开 API 暴露 dry-run（现在是 `pipeline` 内部函数）。
3. `_INSTANCE_SKIP_KINDS` 改成 profile 属性（`UNCOUNTABLE_KINDS`）。

三条一起一个 PR，跟 #8（倒排表）同一个套路：先在本仓用补丁跑通，再交上游。

## 5. 分期

| 期 | 做什么 | 判据 |
|---|---|---|
| **P1** | 表 + 6 份预设 + 自定义 focus / skip（不含自定义 kind）+ `build_profile` 拼 prompt + 三处调用传 profile + `app:extract` 页 + **试抽** | 同一段会议文字，「会议纪要」偏好下待办条数 ≥ 通用的 2 倍且每条带负责人；试抽不落盘（XML mtime 不变） |
| **P2** | 自定义 kind（KINDS 并集、planner 同步、kind_label、事实表下拉）+ 按笔记 / 按导入覆盖 + 首次导入问一句 | 自定义 kind 不再落成 other；改了这篇的偏好 → 同步重抽后 kind 变 |
| **P3** | 上游 PR（§4）+ 「按新偏好重抽这一批」（批量重抽走现有 reextract 流水线，带进度 / 预估） | 本仓不再 setattr 全局对象 |

## 6. 取舍

- **不做**按事实逐条「改 kind」以外的手工分类器：kind 是抽取时定的，事后改单条走现有编辑（`PATCH /api/kb/fact`，
  加 kind 字段即可，一行）。
- **不做**每个预设一套独立 prompt：都是「基础 prompt + 词汇表 + 关注 + 忽略」，只有数据不同——否则四个 ASR 补丁要维护六份。
- **不做**自动判断「这篇是会议还是日记」：猜错比不猜糟；用问一句 + 按笔记覆盖解决。
- 偏好变了**不自动重抽**已入库的：一次全库重抽是几小时的 LLM 调用，只给「重抽这篇 / 这一批」的按钮。
