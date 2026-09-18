# 产品就绪台账

> 计划：`docs/product-readiness-plan.md`。每一批一节。
> **没有「用户看得见的前后对比」的批，不算做完。**
> 每节固定六栏：用户怎么发现 · 复现 · 依据 · 改了什么 · 前后对比 · 下一步。


## P1 · 第 769 轮：复现用户点名的六条，能修的当批修（2026-09-18）

> HEAD 开工时 `305407f`。探针全部跑在仓库里 `backend/data` 那份库（482 篇）上，`--probe` 模式下前端
> `save()` 直接返回、块生成不落库、magic tap 不落库，所以真跑也不碰 `notes`；开工 / 收尾指纹见文末。
> 截图在 `$S/p1-*.png`（S = 本轮 scratchpad）。**每条都是先在真实 app 里重放、再修、再重放。**

### 1a. 「有时有引用，有时无引用」

- **用户怎么发现**：同一篇笔记点两次「续写」，一次正文里带 `[terrence-xxx]`、一次一个都没有，界面只说
  「自由续写 · 知识库中没有相关记录」，不说为什么。
- **复现**：零调用先量——`p1_quant.py`（只读）拿 terrence 全部 19 篇非空笔记跑一遍续写用的检索
  （尾部 600 字，limit 6）：**「全部」/「只看会议记录」两档 19/19 篇取满 6 条；「只看笔记」19/19 篇 0 条；
  「只看导入的」17/19 篇 0 条**。原因是他的库里 20361 条事实全来自会议记录，`note-*` 来源的事实是 0，
  `apple-*` 只有 45 条。那个范围下拉在右栏「记忆」顶部，**存 localStorage、换一次一直生效**，而续写这边
  不显示当前范围。然后真跑重放（同一篇 `06647b9c2031`，同一个按钮，各 1 次）：
  `tap:…:scope=notes` → 0 条材料、正文 0 引用（`p1-tap-scope-before.png`）；`tap:…:scope=all` →
  6 条材料、ribbon「引用 3」（`p1-tap-all-after.png`）。**「有时」= 记忆范围停在了一档没有材料的档上。**
- **依据**：`compose.py:magic_tap` 的 `meta.grounded=False` 只有一个布尔；`api.memoryScope()` 的白名单
  还漏了 `'screen'`（下拉能选「只看屏幕活动」，读回来是 `'all'`——界面说一档、请求发另一档）。
  另外两条试过但**不是**条件：① 尾部检索命中——19 篇全命中，不是它；② 引用 id 大小写被当编造摘掉——
  翻遍 scratchpad 的历史产出，`[terrence-…]` 的十六进制段没有一条小写，没证据，不改。
  DB 里量不到模型侧（`harness_rounds.fired_checks` 489 行只有 27 行非空、快照表 0 行、不存产出正文），
  所以 harness 那条路（智能续写）的引用有无本轮**没有量**，留给 P5 的 D3/D4 人读。
- **改了什么**：`compose.py` 新增 `why_no_facts()`：0 条材料时 meta 带 `why_empty`——库空 / 范围筛掉了
  （**顺手拿「全部」再查一次，告诉他那一档有几条**）/ 尾巴没命中，三种各给一个能照做的动作；
  `TapProvenance` 显示这句，范围筛掉的给「切到「全部」」一键；`api.memoryScope()` 认 `'screen'`。
  测试：`test_p1_readiness.py::test_1a_*` 4 条、`p1Readiness.test.ts` 「记忆范围」1 条。
- **前后对比**：`p1-tap-scope-before.png`（只有「自由续写 · 知识库中没有相关记录」，还被滚出视口）→
  `p1-tap-scope-after.png`（「记忆范围现在是「只看笔记」，这一档里没有能用的记录；「全部」里能取到 6 条。
  右栏「记忆」顶部可以换档。切到「全部」，再点一次续写」）；`p1-tap-all-after.png`（同一篇换「全部」：
  「引用知识库 · 检索到 6 条事实」，ribbon「引用 3」）。
- **下一步**：智能续写（harness 路）的引用有无要靠 P5 D3/D4 人读 5 篇真跑；`harness_rounds.fired_checks`
  为什么 489 行里只有 27 行非空，值得单独查一下（那是唯一能回溯「判据开没开火」的列）。

### 1b. 「Skill 有时能加载，有时无法加载」

- **用户怎么发现**：同一篇笔记两次跑，感觉一次带了 skill 一次没带；界面上**没有任何一处**说这次带没带。
- **复现**：生产路径读下来规则是确定的（下面写全了），「有时」来自两处：
  ① **播种只挂在 GET /api/skills 上**（`routers/skills.py:56`）——没打开过技能面板的用户在每条生成路径上
  都是零技能、不报错；`data/` 下 25 个用户目录 14 个没有 `skills/`，桌面壳 `main.ts` 又记着 localStorage
  丢过一次、随手生成过 `user-4u6jzn` 这种新身份——那一次会话里就是零技能。
  ② 看不见：`Skills` 中间件算完注入哪几条就完了，事件、卡片、日志里一个字都没有。
  `dump_prompts.py` 那 7 处 `store.enabled_skills_for_scope` 是死调用（函数早删了），生产路径没有同款残留。
- **依据（一个 skill 什么时候会进 prompt——完整规则，每条一个测试）**：
  1. `data/<user>/skills/<slug>/SKILL.md` 存在且合法（name 小写连字符 ≤64、description 非空 ≤1024）；
     坏文件静默跳过。
  2. `skill_config.enabled`（没行 = 启用）。关掉的既不注入也不进菜单。
  3. `scopes` 非空 → 调用点的 `skill_scope ∈ scopes` 时**整段正文注入**（顺序按 `idx`）；别的范围不带、
     也不进菜单。
  4. `scopes` 为空（导入的第三方默认这样；面板自建的必须至少选一个）→ 只进「可用技能」菜单，正文等模型调
     `load_skill`（每次跑模型自己最多 3 条）。菜单只在带 `skill` 工具组的 harness 里管用：续写整篇、分段写作、
     六个 `/` 块模式；校验 / 重写 / 润色 / 骨架 / 回顾 / 一次性续写没有工具，菜单在那儿是摆设。
  5. 调用点的范围必须在 `SKILL_SCOPES` 里（面板只认这 13 个）。**计划外发现**：`slides`、`journey` 两个
     调用点在 `compose_system` 里用了不在表里的范围，技能永远配不上；本轮没加（不是「时能时不能」），记着。
  6. 一次跑第一轮算一次，之后不重算（模型自己加载的不能被冲掉）；恢复的跑从快照里带回来。
- **改了什么**：`skills.load_all()` 目录不存在就先 `seed()`（幂等、一次）；`Skills.before_round` 变成异步
  生成器，第一轮发 `CUSTOM skills {scope, injected, menu}`；前端 `consumeHarnessStream` / `composeBlock`
  接 `onSkills`，轮次卡片多一行「技能：按范围自动带上 N 条：…；另有 M 条留给模型按需加载」
  （`AgentActivity.skillsLine`），`/` 运行块日志多一行「技能」；技能面板顶部写「什么时候生效」四句，
  没选范围的条目挂「没选范围 · 只会被模型按需加载」；`dump_prompts.py` 7 处改成 `compose_system(base, scope, USER)`。
  测试：`test_1b_*` 8 条（规则 1–5 各一条 + 播种 + 事件 + dump_prompts）、`test_skills.py` +1、
  `test_skill_loop.py` 改成抽干生成器；前端 `skillsLine` 1 条。
- **前后对比**：`p1-skills-before.png` → `p1-skills-after.png`（面板顶部那段规则）；
  `p1-skills-runlog-after.png`：真跑一次 `/` → 用 AI 写（`slashpick:prompt:…` 探针），运行块日志里
  「技能 带上 去 AI 写作痕迹（受 llm-writing 启发）」——这是用户第一次能看见「这次带了哪条」。
- **下一步**：`slides` / `journey` 两个范围补进 `SKILL_SCOPES`；智能续写整篇的轮次卡片那一行要在真跑里
  拍一张（本轮没跑整篇 harness——它服务端落库，探针模式挡不住 `Save` 中间件）。

### 1d. 记忆浮现的那个点：一行还是一段？绿的黄的是什么？

- **用户怎么发现**：正文右缘偶尔亮一个点，不知道它管一行还是一段、颜色什么意思、光标点到哪会查什么。
- **规则对不对（先答这个）**：一个点 = **一段**（空行隔开算一段），画在段首行右边。只看含数字 / 日期的段，
  是因为判定器（`kb/relations.detect`）**只比量**：同一个量值一样 = 印证（绿），值不一样 = 冲突（黄），
  库里有一条随时间变的线 = 延续（紫），库里还有你没写的条件 = 叠加（紫 60%），有具体的量却一条沾边记录
  都没有 = 缺依据（灰），库里两条说的是同一件事 = 合并（灰 60%）。没有量的段落没法核，不画——这条规则
  本身站得住（零模型、毫秒级、不会瞎猜），**错的是它从来没写在界面上**。中文数字（「三百台」「五月初」）
  不算数字，这是已知盲区，记着。一段判出几种关系时点只画一种：`detect()` 收尾已经按
  冲突 > 延续 > 缺依据 > 叠加 > 合并 > 印证 排好，`cands[0]` 就是最要紧的（本轮加了一条闸钉住这个顺序，
  第一版我以为它是「先算出来的那条」，写了个 `most_urgent` 又删了）。
  光标停在一段 0.9s → 右栏查这段的关系；正文末 500 字 → 召回下面那几条记忆。
- **复现**：`margin:309f19202309`（30588 字、244 段）实拍一个点都看不见（`p1-margin-before.png`）。
  零调用量下来：这篇 244 段里含数字的 **> 80 段**，而前端 `.slice(0, 80)`、后端 `[:80]`——第 80 个含数字
  的段落之后**永远没有点**；前 80 段里 61 段无关系、17 段缺依据（灰点）、2 段叠加。灰点在白底上
  `opacity .85`，几乎看不见。「有的段有点、有的段没有」正是这两件事叠出来的。
- **改了什么**：前端不封顶、按 80 一批分几次发（`marginParagraphs` / `chunked`，正文改了在途的那批作废）；
  悬停那句话写全（`markTitle`：「这一段（第 N 行起）· 冲突 · 那句人话 · 页边圆点规则 · 这段还判出另外
  K 种关系 · 点一下在右栏看全部」，后端 `relations/batch` 多回 `kinds`）；右栏「记忆」顶部一段图例：
  规则一句 + 六个色点各是什么 + 光标停 0.9s / 末 500 字两条触发。
  测试：`test_1d_*` 1 条（顺序）、前端「页边圆点」2 条。
- **前后对比**：`p1-margin-before.png`（没有图例、没有点）→ `p1-memtab-after.png`（右栏顶部图例）；
  `p1-tap-scope-after.png` 右缘能看到两个灰点（缺依据）。
- **下一步**：灰点在白底上太淡，要不要换成空心圈；中文数字；A5（右栏每条记忆「为什么给我看这条」）。

### 2-B1. 右键「自定义提示…」输入为空

- **用户怎么发现**：选一段 → 右键 → 自定义提示 → 什么都不写按 Enter：**选中的那段当场被清掉**，占位块转圈
  「改写选区：在看要用哪些材料…」，请求照发（后端日志 `POST /api/compose/block 200`）。字数 2304 → 2220。
- **复现**：`custom-empty:06647b9c2031` 探针（真实重放：选段 → 右键菜单 → 自定义 → 空 Enter），
  `p1-custom-empty-before.png`。顺带查的：只有空格 → 同样放行；选区为空点自定义 → `sel.empty` 静默返回、
  什么都不发生；超长 → 没有上限。
- **依据**：`SlashPrompt.onRun(value)` 不判空；`runBlock` 第一件事就是 `changes: {from, to, insert: ''}`
  把选区删掉，然后才发请求；后端 `compose_block` 对 `prompt` / `selection` 没有任何校验。
- **改了什么**：一份规则两处用——前端 `slashMenu.blockPrecondition()` / 后端 `compose_block.block_precondition()`
  （空指令、只有空格、空选区、超过 2000 字、空白笔记）。`SlashPrompt` 自己先拦：不关、不发、红字一句
  「先写一句要对选中的这段做什么——什么都不写，它不知道该改成什么样」，输入框 `maxLength=2000`；
  `runBlock` 在删选区之前再判一次（`/` 直接跑的那几项没有输入框）；空选区点自定义 → toast；
  后端 400（一次模型都不调，有测试盯着）。「智能表格」允许留空——它的输入框写着「留空则自动判断」。
  测试：后端参数化 11 条 + 400 用例 1 条；前端 5 条。
- **前后对比**：`p1-custom-empty-before.png`（选区没了、转圈、字数 2220）→ `p1-custom-empty-after.png`
  （输入框还开着、红字提示、选区还在、字数 2304、后端日志没有 block 请求）。
- **下一步**：P3 把 `/` 菜单 + 右键菜单 + ribbon 每个按钮按 §1.3 九种临界条件列全表。

### 2-B2. 「智能插图」在空白笔记上

- **用户怎么发现**：新建空白笔记 → `/` → 智能插图：转圈「智能插图：在看要用哪些材料…」，开了一趟三轮
  harness（`POST /api/compose/block`），工具循环转、模型被要求「为当前位置配一张图」，可能落到
  `render_image` 烧几十秒；0 字的笔记。
- **复现**：`slashpick:chart:34b988c208db`（terrence 一篇 0 字的笔记），`p1-chart-blank-before.png`。
  AI 组每一条在空白笔记上的行为（P3 临界条件表的种子，有测试钉着）：

  | 条目 | 空白笔记上 | 为什么 |
  |---|---|---|
  | 用 AI 写 | 允许（要有指令） | 一条指令就够写 |
  | 智能插图 / 智能表格 / 数据可视化 / 智能数据分析 | **拦**：「笔记还是空的——先写点内容…」 | 拿什么画 / 拼 / 算 |
  | 图片转表格 / 语音输入 / 插入音频 | 允许 | 不吃正文 |

- **依据**：`modes.py` 六个块模式只有 EDA 有 `precheck`；`CHART` / `TABLE` / `ANALYSIS` 没有；
  前端 `onSlash` 对 chart / eda 直接 `runBlock(item, from, to, '')`。第一版前端拦漏了一次：判空时正文里
  还留着刚打的那个 `/`，不是空串——改成去掉 `[from,to)` 再判。
- **改了什么**：`modes._has_context` 挂到 CHART / TABLE / ANALYSIS 的 `precheck`（规则能判的别让模型试三轮，
  跟 `_eda_has_data` 同一条纪律）；前端 `blockPrecondition` 的空白笔记规则 + `runBlock` 先收掉 `/查询词`、
  toast、不发请求。测试：后端 1 条（三个模式 + prompt 不拦 + eda 用自己的），前端 2 条。
- **前后对比**：`p1-chart-blank-before.png`（转圈，请求已发）→ `p1-chart-blank-after.png`
  （`/` 收掉、右下 toast「笔记还是空的——先写点内容（哪怕一句话说这篇讲什么），再来插图 / 拼表 / 分析」，
  后端日志 0 个 block 请求）。
- **下一步**：光标附近有字但没数字时插图该不该拦（现在只拦整篇为空）；P3 全表。

### 3. 正文里的灰色字

- **用户怎么发现**：正文里整段整段是灰的，「根本不便于阅读」。
- **复现**：`note:06647b9c2031` 浅色 / 深色各一张（`p1-grey-before-light.png` / `p1-grey-before-dark.png`）：
  段落是 `--fg`，而**每一条列表项整行是灰的**（「- 核心功能：找人、联系…」三行）。harness 写出来的正文
  一半是列表，于是一半正文是灰的。
- **依据（正文里会变灰的东西，逐类）**：

  | 来源 | 是什么 | 判 |
  |---|---|---|
  | `theme.ts` `tags.list: color --muted` | lezer 的 `"BulletList/... OrderedList/..."` 是**连后代一起**，整条列表项都染灰；原注释说「只有项目符号淡一点」，是错的 | **正文，改 `--fg`** |
  | `theme.ts` `tags.quote: color --muted` + 斜体 | `"Blockquote/..."` 同理，整段引用块灰 | **正文，改 `--fg`**（斜体留） |
  | `tags.url: --muted` | `[文字](地址)` 里的地址 | 标记，留灰 |
  | `.cm-syntax-mark opacity .35` | `#` `**` `>` 记号；第 705 轮前后用户要过「markdown 的格式还是灰色吧」 | 元信息，留；`ListMark` 补进去，`- ` `1. ` 跟 `#` 一致 |
  | `.cm-placeholder`、`.cm-frontmatter`、mermaid 容器文字、`.tap-prov`、标题占位 | 占位 / 元信息 | 留灰。注：这篇标题是「未命名」，大标题显示的是正文首行**占位**（`--ink-3`），所以截图里标题也是灰的——那是「还没起标题」的信号，不是正文 |

- **改了什么**：`tags.list` / `tags.quote` 不设颜色；`MARK_NODES` 加 `ListMark`；高亮表导出成
  `MARKDOWN_HIGHLIGHT_SPEC` 让闸读得到。测试：前端 3 条（list / quote 无 color、整张表只有 url 允许 muted、
  lezer 确实把 tag 传给后代——把原来那条错误注释钉死）。
- **前后对比**：`p1-grey-before-light.png` → `p1-grey-after-light.png`、`p1-grey-before-dark.png` →
  `p1-grey-after-dark.png`：列表项跟段落同色，`- ` 记号淡 35%。
- **下一步**：C3 编辑器基本功那批一起看 `.cm-md-table` 表格预览、运行块预览的字色。

### 闸 / 指纹 / 成本

- 后端 `pytest -q`：**1960 passed**（基线 1933；+26 `test_p1_readiness.py`、+1 `test_skills.py`；
  `test_block_harness._run` 给了一句正文——空白笔记上 chart 现在会被门槛拦，那是对的、有自己的用例）。
- 前端 `npm test`：**53 文件 / 276 条**（基线 52 / 263；+`p1Readiness.test.ts` 13 条），exit 0。
- `notes` 指纹开工 / 收尾：482 行 / `max(updated_at)=2026-09-16T02:53:27` / 321,250 字 /
  `47dcc54be60aa4f2` / `note_revisions` 44 / `harness_edits` 0 —— **一个字没动**。
- 真跑 8 次（magic tap ×4、`/` 块生成 ×4，含 before 那几次），全在探针模式下、不落库。

## P2-fix · 第 770 轮：导出三件套按 P2 清单修（2026-09-18）

> HEAD 开工时 `1276a5f`。上一批（`docs/_research/export-verification-P2.md`）只验不修，列了 17 条；这一批
> **17 条全做了**（1–8 必做，9–17 顺手），每条有代码判准的测试。笔记库跑在 scratchpad 里的**库拷贝**上
> （`KITE_DATA_DIR=…/scratchpad/p2fix/data`，从真库 cp 一份），桌面壳的 userData 也挪到 scratchpad
> （新加的 `MEMOKET_USER_DATA` 开发期覆盖），真库只用 `db_guard.readonly()` 做了三次指纹；开工 / 收尾见文末。
> 截图 `$S/p2fix-*.png`。**每条都在真实 app 里重放：先拍 HEAD 的样子，再修，再拍。**
> 真发飞书两篇（测试文件夹 `Q6AkfiHtylL2LrdMJc5cKi4anyf`，凭据 `importlib` 加载 `config.py`，没 cat、没打印），
> Notion 无凭据：纯函数 + 真打 api.notion.com 的 401 路径。

### 1. 内容保真（表格 / 行内样式 / mermaid / 引用 / 图片 / h4–h6 / 嵌套列表 / 任务 / 分隔线 / 多行引用 / 硬换行）

- **用户怎么发现**：打开导出去的飞书文档：17 行表格拼成一行文字、图片是一行 `![…](_assets/…)`、粗体带 `**`、
  `[terrence-1346-1F3]` 裸露、mermaid 是纯文本代码。
- **复现**：P2 报告 §2.5 / §3.5 两张表 + 真发的 `UnP3d4DJeoDsbNxDGhdcobSyn5b`（252 块：text 203，0 个表格块 / 图片块）。
  修之前先在真实 API 上试了要用的接口（`$S/p2fix/spike_feishu*.py`）：`descendant` 接口一次能建嵌套树
  （表格 31 → 单元格 32 → 文本 2；列表项带 children），实测 1000 个段落 / 20×5 表格一次过；
  图片三步 = 空图片块 → `upload_all(parent_type=docx_image, parent_node=块 id)` → `replace_image`；
  `batch_delete` 一次删 1370 块也过；URL 从 `drive/v1/metas/batch_query` 拿。
- **依据**：`_md_lines` 只认六种块、段内硬换行用英文空格拼、行内 markdown 原样塞进 `text_run`。
  重写成 `md_to_blocks()`（块树：heading / bullet / ordered / todo / code / quote / para / table / divider / image，
  列表项按缩进嵌套，`>` 连行合一块，`|` 表格按分隔行认）+ `inline_runs()`（粗体 / 斜体 / 行内代码 / 删除线 /
  链接 / wiki 链接，嵌套递归；`[terrence-xxx]` **剥掉**——对面没有知识库能解析它，留着是乱码；做脚注得把
  事实原文带过去，而那是会议记录，用户未必想让它出现在飞书里）。
  两家各自渲染：Notion `annotations` / `link` / `table`+`table_row` / `to_do` / `divider` / `children`
  （一次请求最多嵌两层，更深的拍平成第二层兄弟）/ `language: "mermaid"`（原生渲染）/ h4–h6 做粗体段落
  （Notion 没有 h4，压成 heading_3 会抹平层级）/ **本地图片老实写成一行「[图：alt]（Notion API 不接受本地文件）」，
  外链图片才是 image 块**；飞书 `text_element_style` / 31+32 表格 / 17 todo / 22 divider / heading1–9 直映 /
  图片块带 `_asset` 标记、写完拿真 id 上传（文件不在本机就换成一行说明）/ mermaid 飞书没有这个语言枚举，
  留纯文本代码块（源码还在，报告 §3.5 也这么判）。
- **改了什么**：`backend/app/database/exporters.py`（`Block` / `md_to_blocks` / `inline_runs` / `_notion_rich` /
  `_feishu_elements` / `FeishuWriter.flatten` + `descendant` 分批 ≤300 块 / `upload_image`）。
  测试 `test_p2fix_export.py::test_1_*` 7 条（§2.5 / §3.5 表里每一行构件各有断言）+ `test_export_back.py` 两处随之改。
- **前后对比**：真发 `309f19202309`「公司汇报：」（30,588 字）：P2 那份 252 块（text 203 / 0 表格 / 0 图片）→
  现在 **`PKjRdBxCOotvycxgrCncwGkAn9O`**（https://acn0p1esxk6c.feishu.cn/docx/PKjRdBxCOotvycxgrCncwGkAn9O）
  API 回读 **504 块：table 2（6×9、9×8）/ table_cell 126 / image 2（都有 token，1024×1024）/ h4 3 / text 325 /
  bullet 17 / h2 11 / h3 12 / ordered 2 / code 1 / quote 1 / h1 1**，正文里 `**` 0、`[terrence-` 0、`![` 0、`|---` 0。
  第二篇 `5f65df10cad6`「harness 测试」→ **`MgGmd50Z6ogv9OxsLbUcQNYUn1c`**：151 块，**bold 样式 run 27 个**
  （P2 那份是 25 个块带字面量 `**`）、table 3×8、code 2。纯函数上同一篇：Notion 251 块含 table 2 / code mermaid。
- **下一步**：飞书表格单元格里只放一个 text 块（单元格里有列表 / 代码会被拍成文字）；Notion 图片要真传得先有可访问的 URL
  （得起一个上传点，本轮不做）；`$$` 公式 / 原始 HTML / 脚注仍是段落文字。

### 2. 失败提示读对面的 code / msg

- **用户怎么发现**：token 错看到 `Client error '401 Unauthorized' for url …` + MDN 链接；飞书文件夹 token 错同样。
- **复现**：`p2fix-fail-before.png`（HEAD 后端 + HEAD 前端，`export-one:309f19202309:feishu:bad` 探针填一组错凭证）：
  「400 一篇都没导出去：公司汇报：: 飞书返回 10003：invalid param」——看不出是 App ID。
- **依据**：`raise_for_status()` 在读响应体之前；飞书 4xx 的响应体里本来就有 `code / msg / error.helps[].description`
  （中文排查建议，实测 1770039 带「当前文件夹不存在，请检查 folder token 是否填写正确」），Notion 有 `message`。
  code → 话的映射来自真实响应：10003 App ID、10014 App Secret、1770039 文件夹、99991663/672 权限范围、
  1770032… 协作者；Notion 401 → 重新复制 secret、404 → 页面没 Connect、403 → Capabilities、429 → 限流。
- **改了什么**：`RemoteError(status, code)` + `explain_notion()` / `explain_feishu()`；两个 `_req` 先 `r.json()` 再判；
  断网说「连不上 Notion / 飞书（…）——检查网络或代理」。测试 `test_2_*` 5 条（含真形状的 4xx 响应体）。
  前端 `exportErrorText()` 去掉「400 」前缀。
- **前后对比**：`p2fix-fail-before.png` → `p2fix-fail-after.png`：「飞书说 App ID 不对（10003 invalid param）——开放平台 →
  应用 → 凭证与基础信息，复制 App ID」+「复制」钮、15 秒。Notion 真打 api.notion.com：
  「Notion 拒绝了这个 token（API token is invalid.）——去 notion.so/profile/integrations 重新复制 Internal Integration Secret」。
- **下一步**：飞书「文件夹没加协作者」实测不到（这个应用有权限），映射是按 code 段写的，第一次真遇到要核一下措辞。

### 3. fail-fast

- **用户怎么发现**：token 错 + 整库 28 篇 = 转圈 23.7 秒再报一句。
- **依据 / 改了什么**：循环前 `w.probe()`（Notion `GET /users/me`，飞书 `token()`），要新建时 Notion 再
  `GET /pages/{parent}`；循环里 `_Breaker`：同一类（status:code）错误连着第二次就停，回包带 `untried`，
  400 那句末尾「（还有 N 篇没再试）」。超时 60 → 30 秒。测试 `test_3_*` 4 条（token 错一篇 POST 都不发；父页面
  没 Connect 开跑前停；连错两次即停、6 篇只发 2 次）。
- **前后对比**：真打 Notion 6 篇坏 token：**2.0 秒、一次请求**（之前每篇一次）。
- **下一步**：黑洞式断网仍要等一次 30 秒超时。

### 4. 成功后给链接

- **用户怎么发现**：toast「导回 1 篇」就没了，不知道东西在哪；信息面板「副本」只有日期。
- **改了什么**：后端回 `url`（一篇时）/ `urls`，`note_remotes.remote_path` 存 URL（飞书 `metas/batch_query`，
  Notion 响应里的 `url`，Obsidian `obsidian://open?path=…`）；`toastAction('导回 1 篇','打开',…)`；弹层顶部那行
  和信息面板「副本」做成链接（`remoteUrl()`；Obsidian 要本机记得 vault 才拼）；桌面壳 `setWindowOpenHandler`
  放行 `obsidian:`。测试后端 `test_4_*` 3 条、前端 `p2fixExport.test.ts` 「副本那一行」2 条。
- **前后对比**：`p2fix-info-before.png`（副本 Obsidian · 2026-09-12 导回，纯文字）→ `p2fix-info-after.png`
  （「飞书 · 2026-09-18 导回 ↗」可点）；`p2fix-feishu-after-1.png`（toast「导回 1 篇 打开」+ 顶部「飞书 · 09-18 导回 ↗」）；
  `p2fix-obsidian-after.png`（Obsidian 也有「打开」，两个副本都是链接）。

### 5. 凭据记住 + 怎么拿

- **改了什么**：桌面壳 `export-credentials.json`（identity.json 旁，0600；`exportCreds:load/save` IPC，键名 / 长度白名单），
  前端 `util/exportCreds.ts`：弹层和导入页打开时带出来、写成功后存；网页版没这个口子照旧每次填，文案按平台说清。
  弹层 / 导入页各加「怎么拿凭证」链接（Notion integrations 页 / 飞书开放平台），title 里是完整步骤。
  Secret / token 输入框改 `type=password`（第一版截图把 App Secret 拍进去了，删了重拍）。
- **前后对比**：`p2fix-panel-before.png`（三个空框、「凭证不会存下来」）→ `p2fix-panel-after.png`
  （「凭证记在本机」+「怎么拿凭证」）；`p2fix-feishu-after-1.png` 三个框由桌面壳填好、Secret 打码。

### 6. note_id 不存在时不撒谎

- 后端三条路都带 `missing:[…]`；前端 `exportOutcome()`：n=0 且 skipped=0 且有 missing → 「没有匹配的笔记——这篇可能已经删掉了」，
  全是冲突 → 「对方那边改过，跳过了 N 篇」，只有真的 skipped>0 才说「没改过」。测试后端 `test_4_6_*`、前端 5 条。

### 7. / 8. 飞书文件夹 token

- 7：二选一选了**必填**（飞书 API 空 token 确实建得出来——spike 实测建在应用自己的空间，用户在飞书里找不到；已删）。
  导入页 title「留空 = 应用根目录」改成必填 + 按钮禁用，弹层 placeholder 写「必填：新文档建在它下面」。
- 8：弹层 `ready` 在已有飞书 / Notion 副本时不看文件夹 token / 父页面 id（`test_4_8_*` 第二次留空 `updated:1`）。

### 9–17

- 9 **对方改过就跳过**：`note_remotes.remote_rev`（Notion `last_edited_time` / 飞书 `revision_id`），下次不一样就进
  `conflicts`，`force` 才覆盖；弹层的「覆盖对方改过的」对三个平台都显示。`test_9_*` 2 条。
- 10 **>500 块删干净**：翻页数到底、循环删到 0。`test_10_*` 2 条（700 块一次删完；descendant 分批 ≤300）。
- 11 **`vault_dir` 空 / 相对路径 / 是文件 → 400**。`test_11_*`。
- 12 **front-matter 加引号**：`yaml_scalar()` 只在会被 YAML 误读时加双引号，对面 `parse_frontmatter` 只 strip 引号。`test_12_*`。
- 13 / 17 **Obsidian 链接**：`render_tree` 两遍（先定路径再渲染），`note://id` → `](<../项目/项目.md>)`，
  子目录里的图片补 `../`。`test_13_17_*`；真跑 `p2fix-obsidian-after.png` 的 `Notes/公司汇报：.md` 里 3 张图都是 `../_assets/`。
- 14 硬换行 `\n`（第 1 条里）。15 App ID / Secret 映射（第 2 条里）。
- 16 失败 toast 带「复制」、15 秒；弹层底部渲 `failed[]`；导入页渲 `missing` / `untried` / 每篇链接。
- 顺手：`.palette input`（0,1,1）压掉了 `input[type=checkbox]`，弹层里的勾选框成了一根下划线（第一版截图看出来的），
  `styles.css` 加 `.palette input[type=checkbox]`。

### 没做 / 说清楚的

- Notion **真发没有**（这台机器上没有 integration token，报告 §2.1 写了去哪拿）——纯函数 + 401 路径而已。
- Obsidian 没在 Obsidian 应用里实开（本机没装）。`obsidian://open?path=` 是它文档里的协议，没实点。
- 飞书 mermaid 仍是纯文本代码块；Notion 本地图片是一行说明；Notion 列表超过两层拍平；表格单元格只放文本。
- P2-fix 之前导过的飞书 / Notion 副本 `remote_path` 是空的，再导一次才有链接（老记录不瞎拼）。
- 网页版凭证仍不存。

### 闸 / 指纹 / 成本

- 后端 `pytest -q`：**1983 passed, 3 skipped**（基线 1960；+26 `test_p2fix_export.py`；3 个 skipped 是
  `test_corpus_lineage` / `test_number_grounding` 要 `backend/data/notes.sqlite3`，worktree 里没有真库——把库拷贝
  临时放进去单跑这两个文件 72 passed，跑完删掉）。
- 前端 `npm test`：**54 文件 / 285 条**（基线 53 / 276；+`p2fixExport.test.ts` 9 条），所有 check-* 脚本 exit 0。
- `notes` 指纹开工 / 中途 / 收尾：482 行 / `max(updated_at)=2026-09-16T02:53:27` / 321,250 字 / `47dcc54be60aa4f2` /
  `note_revisions` 44；真库 `note_remotes` 仍是 19 行 obsidian、0 行 feishu / notion——**一个字没动**。
- 飞书真发 3 次（新建 ×2、更新 ×1）+ 两个 spike 文档（`AJOQdXlzho7U2vxDmgwcWHThnae` 在测试文件夹里可删；应用根目录那个已删）。
- 探针跑 10 次，全在库拷贝 + scratchpad userData 上。


## P3 · 第 770 轮：B 线临界条件表 + 修第一批（2026-09-18）

> HEAD 开工时 `1276a5f`。**一个真笔记都没碰**：所有探针跑在 scratch 拷贝上（`KITE_DATA_DIR=$S/p3data`，
> `notes.sqlite3` + `terrence/` 拷贝），供应商指向一个假模型 / 假语音服务（`$S/fakellm.py`，`ok / err500 / err401 / hang`
> + `asr-ok / asr-err` 六种模式，`$S/p3cfg.py` 切），黑洞用真关机的 `192.168.77.8`，「后端没起来」用 `netdown` 探针把
> `fetch` 换成一律 `Failed to fetch`。截图 `$S/p3-*.png`（52 张）。导出那几个文件另一个 agent 在改，一行没碰。

- **用户怎么发现**：第 768 轮原话「容错根本没做……好好查一下这些功能的临界条件、容错处理」。第一次用最容易栽的三种形状：
  点了**什么都不发生**（新建 / 导入 / 智能排版 / 生成骨架）；**指错地方**的报错（后端没起来说「去设置里检查 LLM 供应商」，
  语音服务没开也说 LLM）；**明知不可达还转圈**（状态栏红着「LLM 不可达」，每个按钮照样发请求，黑洞主机下转 75 秒+，
  非流式动作没有停止、要等满 300 秒）。
- **复现**：先从代码数出动作清单（`SLASH_ITEMS` 18 项、`SelectionAction` 6 项、浮动按钮 + ▾ + ⋯ 19 项、ribbon 六页签 12 行、
  右栏 6 行、侧栏 / 导入 / 树右键 16 行 = 67 行），逐格填 `docs/edge-cases.md`（555 格）。**表的统计：✅ 189 / ✅P3 55 /
  ❌ 2 / ？ 19 / — 286**。❌ 全部先复现：新加 7 种可拼接探针（`netdown` / `click` / `toasts` / `type` / `selact` / `audiopick` /
  `mdpick`），`toasts:` 把 toast、红字、运行块、忙态写进日志——「静默」靠 `toasts=[] runs=[]` + 后端 0 个请求证，
  不靠推理。修前复现到 18 格（表末「复现记录」逐条：探针串 + before/after 截图名）。
  最扎眼的五个：① 生成骨架三种失败全静默（`onClick={onRun}` 把鼠标事件当成了 `background`）；② 后端没起来时
  新建 / 导入 .md 什么都不发生（promise 静默拒绝）；③ `/` 块和智能续写的错误把 `HTTPStatusError … for url 'http://…'
  For more information check: https://developer.mozilla.org/…` 整段写进正文的运行块 / 轮次卡片，状态还停在「在写…」；
  ④ 插入音频在语音服务没开时音频传上去了却没插进笔记、报错指去 LLM 供应商；⑤ 校验在黑洞主机下 11 秒仍在转、
  状态栏同时红着「LLM 不可达」。计划外发现两条：`custom-empty` / `click` 这类无 `harnessProbeDone` 的探针步骤会被
  App 的探针 effect 在 notes 变化时重跑（toast 出两遍，`ranOnce` 兜住）；`ribbon:` 的 defaultOpen 读整条探针串，
  `;;` 后面的东西被当成页签名（改成只读第一段）。另：开发端口 47232 会跟另一个 agent 的实例撞（一次「address already in use」，重跑即可）。
- **依据**：`friendlyError` 把 `Failed to fetch`（浏览器→后端）和 `All connection attempts failed`（后端→模型）都翻成
  「模型连不上——去设置」；`loop.run` 的 `except` 直接 `f"{type(exc).__name__}: {exc}"`；`llm.py` 四个 `httpx.AsyncClient(timeout=300/600)`
  连接超时也是 300 秒；`runSlides` 有 `abortRef` 却没有停止钮；`SelectionMenu` 忙态只有转圈；⋯ 菜单「存入知识库」只按
  `loading==='ingest'` 禁用、不看 `job`（ribbon 那处看了）；`onPickFile` 音频路径先转写后插播放器；`newNote` / `newNoteUnder` /
  `importMarkdown` 没有 catch；`restructureNote` 空正文 `return`。九种条件的摆法记在表头。
- **改了什么**（9 处根因，覆盖 55 格；前后端共用同一份前置判断）：
  ① 新增 `editor/preconditions.py` ↔ `editor/preconditions.ts`（骨架 / 续写 / 智能续写 / 打磨 / 排版 / 幻灯片 / 存入知识库的
  空正文那句话，一份两处，`test_p3_edge_cases::test_precondition_strings_exist_in_frontend_verbatim` 逐句核对），
  骨架 / 续写 / 排版路由改用它，前端各入口先拦不发请求；② `SkeletonPanel` 改 `onClick={() => onRun()}`，`runSkeleton` 只认
  `background === true`；③ `friendlyError` 分三档：后端没起来 / 语音服务 / 后端翻好的中文原样给；④ `llm.describe_error()`
  一处翻译：`loop.run` 的 RUN_ERROR、`main.py` 全局 `httpx.HTTPError → 502`、排版的 502 都从这里拿话；`hooks/note.py`
  骨架失败改发 `warning`（RUN_ERROR 现在只在整个跑挂掉时发，前端据此说「出错停下」+ toast + 状态行）；⑤ 连接超时
  `httpx.Timeout(300/600, connect=10)`，语音同款 `(1800, connect=10)`；⑥ 前端 `llmGate()`：健康检查红着「LLM 不可达」就拦
  （续写 / 智能续写 / 打磨 / 骨架 / 排版 / 幻灯片 / `/` 块 / 右键五项），带「打开设置」并顺手重测；⑦ 右键菜单忙态「停止」
  （`selectionAbortRef` + 四个 api 加 `signal`）、幻灯片忙态胶囊「停止」；⑧ 插入音频：先插播放器，语音离线不发转写，
  失败保留播放器只说转写没成；`asr.describe_error` 说语音服务；⑨ 新建 / 插入子笔记 / 导入 .md 兜 catch → toast；
  ⋯「存入知识库」按 `job` 禁用 + 函数里再拦；`runBlock` 的 catch 走 `friendlyError`；`runSlides` 中止有 toast。
  测试：后端 `test_p3_edge_cases.py` 28 条（+ `test_note_hooks` 改 1 条）；前端 `p3EdgeCases.test.ts` 8 条（+ `friendlyError.test.ts` 改 1 条）。
- **前后对比**（18 对，全在 `docs/edge-cases.md`「复现记录」，这里点名）：`p3-skeleton-blank-before.png`（点了没反应）→
  `-after.png`（toast「先写点内容（或标题）再生成骨架」，0 请求）；`p3-newnote-netdown-before/after`；`p3-mdpick-netdown-before/after`；
  `p3-restructure-blank-before/after`；`p3-ingest-double-before`（两个 POST）→ `-after`（第二下禁用）；`p3-slashprompt-err500-before`
  （运行块一段 httpx 英文 + MDN 链接）→ `-after`（「模型服务返回 500（地址）——多半是那边出错了」）；`p3-harness-err500-before/after`；
  `p3-tap-netdown-before`（「去设置里检查 LLM 供应商」+ 打开设置）→ `-after`（「连不上应用后台…」）；`p3-selact-verify-blackhole-before`
  （红字 + 转圈）→ `-after`（10 秒报「10 秒内没连上（地址）」）+ `p3-tap-blackhole-gate-after`（红着就拦）；
  `p3-selact-rewrite-hang-before`（只有转圈）→ `-after`（停止 → 「已停止」）；`p3-slides-hang-before/after`；
  `p3-audiopick-asrdown-before`（音频没插进笔记、报错指 LLM）→ `-after`（播放器已插入 + 「语音服务不可达…这次没转写」，0 转写请求）；
  `p3-audiopick-asrerr-before/after`。
- **下一步（剩下的 ❌ / ？ 排序）**：1) 智能排版 × 超时、生成骨架 × 超时——两格 ❌，加停止（AbortController + 忙态钮，跟幻灯片同款）；
  2) 图片转表格 / 语音输入 / 录音 / 存入知识库 的超时与「停止只撤块、请求照跑、跑完仍插进正文」（？×5，先复现）；
  3) 导入页 Obsidian / Notion / 飞书和关系卡的 toast 用 `e.message` 原样（英文 `Failed to fetch`），改走 `friendlyError`（？×4）；
  4) 复制路径 / 删除 5 秒后真删失败 的静默（？×2）；5) 来龙去脉在模型报错下 KITE 内部重试转多久（？×1）；6) 零库时校验 / 扩展
  要不要零调用直接拦（表里两条备注）；7) 续写 / 智能续写第二下 = 停止但没有一句「已停止」。

### 闸 / 指纹 / 成本

- 后端 `pytest -q`：**1988 passed**（基线 1960；+28 `test_p3_edge_cases.py`；`test_note_hooks` 一条改成认 warning）。
- 前端 `npm test`：**54 文件 / 284 条**（基线 53 / 276；+`p3EdgeCases.test.ts` 8 条），exit 0（27 个 check 脚本全绿）。
- `notes` 指纹开工 / 收尾：482 行 / `max(updated_at)=2026-09-16T02:53:27` / 321,250 字 / `47dcc54be60aa4f2` / `note_revisions` 44
  —— **一个字没动**（探针全在 scratch 拷贝上跑；真库连读都只读了一次算指纹）。
- 真模型调用 **0 次**（全部假服务）；探针跑 57 次。



## P4 · 第 771 轮：D1 脉络梳理 + D2 记忆——人读评测，不修代码（2026-09-18）

> HEAD 开工时 `d626f6c`。**判法按计划 §2 D 线：不用打分器，人读。** 语料 = `corpus_lineage` 的 `user` 血缘（真库里只有 24 篇，
> ≥800 字的 12 篇），全部实验跑在 `KITE_DATA_DIR=$S/p4data`（真库整目录拷贝，不含 backups）上、后端起在 8791；
> 真库只读了一次算指纹。脚本和原始产出在 `$S/d1_skeleton.py` / `d1_skeleton_out.json` / `d2_memory.py` / `d2_memory_out.json` /
> `d2_none_cause.py`（S = 本轮 scratchpad）。**这一批的交付物是评测表和问题清单，一行产品代码都没改。**

### 选的 5 篇（id · 标题 · 字数 · 为什么选它）

| # | id | 标题 | 字数 | 选它的理由 |
|---|---|---|---|---|
| N1 | `715266c1fcb4` | 公司汇报： | 26,714 | 最长的一篇（展厅讲解词，14 个行业段落、**零个 markdown 标题**），看长文的脉络和目录 |
| N2 | `92d07b760f1e` | 未命名（产品四项挑战 + 上线时间线） | 4,889 | 有标题层级、mermaid、一堆指标和日期，还带 harness 留下的重复标题和乱码（L50/52、L76 `<|start|>`） |
| N3 | `c3464ab74c7d` | 未命名（plaud 的优势分析 → 四线闸门） | 2,767 | 决策机制类，人名 / 日期 / 阈值密集，后半段两节内容重复 |
| N4 | `e78306202d78` | 未命名（国际高中） | 1,976 | 会谈记录类，中文月份（「6月末/7月」）、英文引语、Discord |
| N5 | `603dca25403a` | 未命名（卖房中介对比） | 810 | 最短、纯论述 + 一张空表，**全篇没有一个阿拉伯数字** |

### D1 脉络梳理准确性（骨架 = spine + beats，`POST /api/skeleton`，跟面板「生成骨架」同一条路）

- **用户怎么发现**：点「生成骨架」，右栏出一句 spine 和 5–6 条 beats；他会拿 beats 当目录读——哪条正文里有、哪条是编的、漏了什么，他一眼看不出来。
- **复现**：5 篇各生成一次（真模型 `gpt-5.6-luna`，走 `provider_config`），每条我逐条对回正文。判法：`对` = 正文有对应段落且意思没变；
  `编` = 正文没有、也没标成「待补」；`变味` = 正文有但骨架说反了 / 说成没有；`漏` = 正文的主要段落骨架没盖住。**分母是读了几条（spine 算一条）。**
- **成本（实际）**：5 次调用，prompt 33,072（其中缓存 1,272×5）+ completion 2,988 = **36,060 token**，耗时 6.3–11.6 s；
  N1 一篇就 21,052 prompt。历史均值（`llm_usage` 25 次 `skeleton`）：2,301 / 457。

| 篇 | 读了 | 对 | 编 | 变味 | 漏（正文有、骨架没盖住） | 顺序 |
|---|---|---|---|---|---|---|
| N1 26.7k | 6 | 5 | 1 | 0 | 智慧教育（L117–129）、油气 / 燃气 / 化工 / 电力（L145–201）、金融（L249–285，招行十年三阶段）、交通铁路 / 公路 / 机场（L287–331）、数字能源（L345–405）、制造 / 制药（L407–467）——**6 个大段、约 15k 字，一条都没有** | 对 |
| N2 4.9k | 6 | 5 | 0 | 1 | 三个阶段小节（3/10、3/10–31、late March，L71–95）和 mermaid 时间线只被 B3 一句带过 | 对 |
| N3 2.8k | 7 | 7 | 0 | 0 | —（mermaid 图没提，合理） | 对 |
| N4 2.0k | 6 | 5 | 0 | 1 | 「数据流转译如何落地」一节（L238–246）没有一条「已写」盖住，反被 B5 说成「尚缺」 | 对 |
| N5 0.8k | 6 | 6 | 0 | 0 | —（但骨架 ≈500 字，正文 810 字：骨架是逐段复述，不是脉络） | 对 |
| **合计** | **31** | **28** | **1** | **2** | | 5/5 |

逐条证据（只贴判「编 / 变味 / 漏」的，和几条有代表性的「对」）：

- **N1 B5（编，未标注）**：「最后还需要把跨行业案例收束为一套可复用的合作方法：先识别最昂贵或最危险的环节，再以算力和数据底座承载模型，
  保留人的关键决策与行业责任…并明确客户下一步应从哪个场景、哪类数据和哪组伙伴开始落地」——正文没有这样的收束段。散落的影子有：
  L467「形成了"先找最大成本环节、再用成熟AI 能力精准突破"的合作范式」、L113「AI 只做助手，最终裁决权仍然属于仲裁员」、L267「AI 做辅助增强，人做关键决策」。
  是提示词要求的「预测缺失功能」，**但没有像 N2/N4 那样标「待补」**，用户读起来就是「这篇有这么一段」。
- **N1 B4（对，但只挑了 5 个案例）**：深圳 / 武汉城市智能体（L87–91）、陕西 1.2PB / 12 亿条博观（L107）、湖北病理（L139–141）、伊敏矿（L209–223）、天津港（L337–341）都在；
  可正文 14 个行业段里它只点了 5 个。**长文的骨架上限是 6 条**（`compose.py:137 beats[:6]`、提示词「3-6 条」），26k 字分 6 条，每条盖 4k 字。
- **N2 B5（变味）**：标着「待补：…需要在 3 月 10 日 Preview、3 月 21 日样机到达、3 月底正式版本三个闸门下明确负责人、验收证据、回滚条件…特别是驾驶邮件必须经过用户语音确认后才能发送，图谱维护必须验证约 5 秒的确认成本」——
  这些正文**已经写了**：L96–101「### 3 月 21 日样机到达后的兑现闸门…由 agent 朗读内容，并在用户语音确认后发送；未完成语音确认时，不应自动发送…确认的目标仍控制在约 5 秒内」，
  负责人 L73「UXUI 由 Slowo & Jia Rui 负责」/ L85「由 Elisa & Aaron 负责修复…验收标准为投递成功率≥98%」，回滚 L75–76。**把已写的说成待补，续写就会再写一遍**——这篇 L50/L52 两行一模一样的「我们产品上线的时间线是什么？」正是这种病留下的。
- **N4 B5（变味）**：「尚缺：…补齐数据流各环节的责任人、课程标签与Discord/案例库的接入方式，以及用"打开即有答案、不用再记录"在销售上市前验证…」——
  课程标签 L242「按课程标签自动推送到共创群，同时写入案例库」、Discord L246「Speaker A 说在 Discord 上建一个 MemoCad 的账号」、验收标准 L221「用"不用再去记录"衡量合作价值是否兑现」都在正文里；
  真缺的只有「责任人」和「试点决策」。
- **N3（7/7 对）**：B6「Slowo 超过 48 小时可放行占位图、创始人 48 小时未否决视为默认通过，以及将 9 月学位不确定性纳入"人才保留风险"月度简报」= L169 / L184 / L176 / L188，逐字对得上。
  是五篇里最好的一篇——正文本身结构最清楚、又只有 2.8k 字。
- **N5（6/6 对，但没用）**：B2「不再按中介逐一复述，而要并置当前方案，分别呈现报价、行情判断、目标买家、成交周期、依据及待核实项」= L353–359 那张表的表头。
  5 条 beat 62 / 73 / 89 / 103 / 111 字 + spine 62 字 = 500 字，正文 810 字：**这不是脉络，是缩写**。提示词写的是「beat 是一个短语」（`store.py:1164` 注释），模型给的是整句。
- **顺序**：5 篇 beats 顺序全部跟正文一致。

**目录（右栏「目录」= `DocumentOutline.parseHeadings`，零模型）**：N1 26.7k 字**零个 `#` 标题**（段落名是「政府：」「金融：」「智慧教育」这种裸行）→ 目录面板空白，用户在最长的一篇里没有任何导航；
N2 的目录里会出现一条 `我们该如何克服挑战：### 如何克服挑战：`（L24 一行里夹着两级标题，原样显示 `###`）。

**计划外发现——骨架落库被截成半句**：`POST /api/skeleton` 返回的 beats 87–185 字（`compose.py` 没 clamp），而 `persistSkeleton` → `PUT /notes/{id}/skeleton` →
`store.set_skeleton` → `clamp_skeleton` 按 **`BEAT_MAX = 60`**（`store.py:1167`）截断。在 scratch 库上回放（`d1_roundtrip.py`）：发 `[57, 87, 72, 92, 96]` → 存 `[57, 60, 60, 60, 60]`，
第二条变成「已写：用Speaker B关于录后打开手机、上传、等待和二次操作的反馈，具体暴露硬件交互与真实使用目标之间的断点，并将问」。
**真库里 4 篇已经是这样**（`e78306202d78` / `a941efecd390` / `df3b4f7e987d` / `0eecee3d7b94`，beats 长度清一色 60）——用户生成时看到整句，重开笔记看到半句；
`hooks/note.py:99` 智能续写用的骨架也是截过的，模型每轮读的是「…并将问」。

### D2 记忆准确性（右栏「记忆」：关系卡按光标段落、记忆列表按正文末 500 字；页边圆点 `relations/batch`）

- **用户怎么发现**：光标停在一段，右栏冒出几条记忆——他分不清这几条是按什么查出来的，也不知道为什么这一段有点、那一段没有。
- **复现**：10 个光标位置（每篇 2 个：一个含数字 / 日期的段、一个纯论述段），按前端的真实规则发请求：
  `paragraphAt`（标题不算、空行断段）→ `stripForRecall` → 有数字且 ≥8 字才发 `POST /memory/relations {confirm: true}`（`RelatedMemory.tsx:56`）；
  记忆列表 = `content.slice(-500)` → `POST /memory/recall {limit: 5}`（`RelatedMemory.tsx:100`）；页边圆点 = `marginParagraphs` 全篇分批 `relations/batch`。
  查询词取 `/recall` 返回的 `terms`（就是 `kite_memory.recall` 认出来的表层词）。
- **零模型——确认**：D2 全程 `llm_usage` **新增 0 行**。`/recall` 和 `/relations/batch` 是纯词法（`search.plan` + `rank`，每次 75–140 ms）。
  **但 `/relations` 不是绝对零模型**：`memory.py:198` 在有「冲突」候选时会打一次模型改写那句人话（历史 4 次，`memory/relations`）；本轮 10 个位置没触发。
  图例上那句「零模型」对圆点成立，对关系卡差一个条件。

**表 A：10 个光标位置（关系卡 + 圆点）**

| # | 篇·行 | 段落（原文） | 实际查询词 `terms` | 候选池 (limit 8) 相关/沾边/不相关 | 关系卡 | 圆点 | 判 |
|---|---|---|---|---|---|---|---|
| 1 | N1 L185 数 | 「实现了功率预测精度提升 8+%。具体：超短期I5 分钟预测准确率达 97.24%、4小时预测达 91.72%，中短期 24小时预測整体突破90%。」 | `小时预` `中短期` `分钟预` | 0 条 → 0/0/0 | 缺依据 | 灰 ✓ | **对**：库里确实没有功率预测的记录；但查询词是三个 2–3 字碎片，用户看不懂 |
| 2 | N1 L33 论 | 「现在超节点不再比谁卡多、谁算力堆得大，而是比谁能真正"多柜合一、全城无损"…」 | （无数字，前端不发） | — | 无 | 无 | 按规则不查 |
| 3 | N2 L74 数 | 「- 录制信任闭环：演示现场就绪信号可视率≥90%，3 秒录性评分触发率≥80%，现场因设备犹豫放弃率<5%…- 第一`<|start|>`关联感知：第一段录音后锚点卡打开率≥70%…」 | **`start`**（唯一一个词，来自乱码 `<|start|>`） | 8 条 → 0/0/**8**（「why we start this company」「business development can start after Kickstarter」「start exploring AI」…全是 start-up） | **无** | **无** | **错**：一段 8 个指标，应是「缺依据」灰点；因为 `start` 跟短英文事实一重合（1/8 ≥ 0.12）`related` 非空，缺依据被压掉，又判不出别的 → 什么都没有 |
| 4 | N2 L11 论 | 「把客户 A、客户 B、客户 C 分别的三段录音连接起来…」 | （无数字） | — | 无 | 无 | 按规则不查 |
| 5 | N3 L9 数 | 「…3月10号上众筹，众筹里面会有很多的页面是要放我们自己的ui的页面…随后五月到六月渠道收回到官网做预购…六月末或七月…七月份启动正式销售…」 | `ui` `的页面` `众筹里` `号上众` `3月10` | 8 条 → 1/3/4（相关：`1238-7F4`「因为3月10号上众筹上众筹里面会有很多的页面是要放我们自己的ui的页面」；沾边：UI 晚一天、一周刷 ui、说明书等 UI 图定；不相关：豆包 ui 快捷键、slack 里的 ui、需求不是 ui、改法动不动 ui） | 印证「日期跟知识库 2026-03 的记录一致」→ `1238-7F4` | 绿 ✓ | **对**（唯一一张对的卡）；**漏**：库里 `1439-0F4`「Speaker B 说 应该在 6 月末或 7 月会在网站上开始销售产品」没出来——正文写的是「六月末或七月」中文数字 |
| 6 | N3 L3 论 | 「团队的地理布局本身就是一个产品壁垒…迁移到美国洛杉矶…」 | （无数字） | — | 无 | 无 | 按规则不查 |
| 7 | N4 L27 数 | 「决策节奏需要收束。午餐会要把方向共识转化为可落地的闭环方案，并以6月末/7月销售上市窗口为验收边界：」 | `月末` `并以` | 4 条 → 1/1/2（相关：`1439-0F4`「应该在 6 月末或 7 月会在网站上开始销售产品」；沾边：`1872-3F9`「五月末还是六月才能有…500台样机」；不相关：三月末发 kol、轮播观看率） | **无** | **无** | **错**：库里有一模一样的话，应是印证绿点；`extract_values` 只认「X月X日」，「6月末/7月」既不是日期也不是数字 → `pv` 空 → 只可能报合并 → 空 |
| 8 | N4 L23 论 | 「午餐会要谈的不是愿景，是把"行业案例支撑"和"师资协作"变成可执行的动作…」 | （无数字） | — | 无 | 无 | 按规则不查 |
| 9 | N5 L11 数 | 表格 + 「表中要把内容分成**三类**：已经发生、可以核实的事实；中介基于经验作出的推测…」 | （无阿拉伯数字，前端不发） | — | 无 | 无 | 这篇**全文 0 个数字段 → 0 个点**；「三类」是中文数字（P1 记过的盲区，这里实证） |
| 10 | N5 L13 论 | 「这样整理后，下一步才会明确：要求报价偏高或偏低的中介补充可比案例…」 | （无数字） | — | 无 | 无 | 按规则不查 |

含数字的 4 个位置：卡 1 对、1 对但漏、2 错（该有点没点）。6 个论述段按设计一律不查——**光标停在纯论述段上，右栏关系区永远是空的**，这条规则本身对，但用户在 N5 这种笔记里一个点都看不到。

**表 B：记忆列表（末 500 字召回，跟光标无关；5 篇各 5 条）**

| 篇 | 末 500 字讲的是 | `terms` | 相关/沾边/不相关 | 逐条 |
|---|---|---|---|---|
| N1 | 恒瑞医药 翻译准确率 70% → 90–95%、每年省 5000 万 | `ai` `华为` `华为的` `90%` | 0/3/2 | 沾边：`apple-…-1F10/1F16/1F4` 灵衢 / 内存池化 / 液冷——**是这篇笔记自己前半段导入库后的事实**；不相关：`1837-13F10`「一半的代码是AI写的。现在90%多」（撞了 `90%`）、`1975-29F1`「They have the AI in their DNA」 |
| N2 | 3/21 样机、驾驶邮件语音确认、图谱自维护 5 秒 | `memocat` `hui long` `phil stoler` `driving` `preview` `3月10`… | 4/1/0 | 相关：`1815-5F3` drafting e-mail when driving、`2394-3F15` Hui Long can get it done、`2394-3F16`「why consumers would not just use ChatGPT」（**这条是正文没写的新信息**）、`1674-4F3` 3月10号 preview；沾边：`1522-4F8` press a button while driving |
| N3 | 9 月学位不确定性 / 人才保留风险 / 四线节拍器 | `slowo` `ui` `个人` `uiux` | 1/4/0 | 相关：`2046-1F5` Speaker C 不明白 APP 跟着 UIUX 走还是先做 UIUX（正文 L109 引的）；沾边：新 UXUI by Slowo & Jia Rui、uiux 缺页、UI 晚一天、需求不是 ui——**末 500 字讲的是学位和评审，5 条没有一条沾学位 / 评审 / Offer** |
| N4 | Memocad 前提 + Discord 讨论板块 | `memocad` `discord` `exists` `believe` `better` `function` `re` `跟这个` `的账号` | 5/0/0 | 全部相关——但 5 条都是正文已经逐字引过的原话（`1812-0F1` Memocad exists because…、`1838-19F4` Discord 账号、`1596-14F7` operating everything on the memocad app、`1596-9F4`、`1812-0F6`）：**告诉他的都是他刚写的** |
| N5 | 中介对比表、三类信息、下一步追问 | **`记录`**（只剩一个词） | 0/0/5 | `1837-17F6` Vlog 记录生活、`1814-19F10` 记录在聊天窗口、`2392-3F6` 记录工作生活、`1850-10F10` 崩溃率日志记录、`1838-14F9` 一按记录东西——库里根本没有卖房的内容，应该什么都不给 |
| 合计 | | | **10/8/7** | |

**页边圆点全篇统计（4 篇有数字段的，零模型）**：162 个含数字段 → **40 个点**（N1 136 段：灰 36 / 紫叠加 2 / 灰合并 1 / 无 97；N3 9 段：绿 1；N2 15 段：0；N4 2 段：0）。
122 个没点的段拿 `detect()` 逐段复盘（`d2_none_cause.py`）：

- **71 段：数字没被认成「量」**（`relations._UNITS` 里没有 年 / 卡 / 辆 / 秒 / TB / 度 / kW / MW / 平方公里，序号「3.」「5.」也算数字）。
  例 L3「营收几乎与2020年的巅峰持平」、L19「950 超节点…8 个 NPU 刀片」、L209「100辆矿卡…42.35平方公里…3500万吨…-50度」——`pv` 空 → 连「缺依据」都不判。
- **51 段：被一个弱重合压掉**（`overlap` 按 min 归一，事实只有 3 个词时撞上 1 个就过 0.12）。
  例 L7「每年至少投入营收的10%到研发上…华为现在21万员工」top 事实是 `1850-9F4`「他的通信就是要通过WiFi。」重合 **0.67**（只因为 `wifi`）；
  L137 / L141 / L149 三段（病理 70% 90%、会诊 4-5 天、勘探 50 亿参数）的 top 事实都是 `1975-29F2`「This post was written by AI.」（0.33，只因为 `ai`）。
  有了「沾边」就不报缺依据，又没有同单位的量 → 空。
- 3 张紫 / 灰关系卡点开的事实**全不相干**：L97 文旅「用户规模超400万」叠加 `1604-9F2`「我10秒打一个，过10分钟又打了一下」；
  L135 病理「单个文件都是 GB级」叠加 `1596-15F14`「64 GB would be 20,000 hours」+ `1712-10F8`「MP4少于10 GB」；
  L283 反欺诈「50000+tps…S0ms」合并 `1818-7F1`「这个也是新加坡的」+ `1818-7F2`「OK，好，这个也是新加坡的」（一场转写成「社会社会社会」的废录音）。
- N2 有 10 个含数字的**独立标题行**（`### 1. CaptureVoicesAnywhere…`、`### **3 月 10 日 - Preview 预热启动**`）按规则跳过——对。

- **依据**：`kb/relations.py:18-24`（单位表）、`:66-70`（min 归一）、`:126-128`（无量只判合并）、`:275`（`related` 非空就不报缺依据）；
  `kb/search.py:119-137`（查询词只留词表命中，长句退化到 1 个泛词时没有下限）；`RelatedMemory.tsx:23-24 / 56 / 100`（0.9 s、末 500 字、有数字才查）。
- **改了什么**：无（本批只评测）。
- **前后对比**：上面两张表就是「前」；「后」等 P6 修完按同样 10 个位置、同 5 篇重跑（脚本已在 scratchpad，零模型，几秒）。

### 问题清单（按「用户第一次看到会怎么想」排序）——P6 的输入

1. **骨架重开笔记变半句**。现象：生成时 beats 整句，切走再回来每条 60 字戛然而止（真库 4 篇已是）。证据：上面 `d1_roundtrip.py` 的 `[57,87,72,92,96] → [57,60,60,60,60]`。
   根因：`store.py:1167 BEAT_MAX = 60` 在 `set_skeleton` 里截，`routers/compose.py:114-146` 返回前不截，两边不一致；`hooks/note.py:99` 同样截了再喂给续写。
   建议：要么 route 也 clamp（所见即所存），要么把 `BEAT_MAX` 提到实际分布（本轮 57–185，历史 28–185）之上、比如 200；并让提示词二选一：要短语就 ≤40 字，要整句就别叫「短语」。
2. **骨架说「待补」的，正文已经有**（N2 B5、N4 B5，2/31）。用户会以为没写 → 点续写 → 再写一遍 → 就是 N2 L50/L52 那种重复。
   根因：`prompts/writing.py:18` `SKELETON_SYSTEM` 让模型「补上显然该有的功能」，没有任何代码核对「它说缺的东西正文里有没有」；`checks/skeleton.py` 五条判据都不看正文。
   建议：加一条零模型判据——`待补/尚缺` 条目跟正文每段做 `overlap`，≥0.3 就改标「正文 L 某已有」并在面板上给链接；顺手把标签规范成 JSON 字段（`status: written|missing`），现在五篇五种写法（「已写：」「【已写】」「已写并需继续收紧」「待补」「尚缺」、N1/N3 不标）。
3. **长文骨架盖不住、目录又是空的**（N1：6 条盖 26.7k 字，6 个行业段 15k 字没条目；0 个 `#` 标题 → 目录空白）。
   根因：`compose.py:137 beats[:6]` + 提示词「3-6 条」不随长度变；`DocumentOutline.parseHeadings` 只认 `#`。
   建议：beats 上限按字数放（每 2k 字 1 条、封顶 12）；目录对无标题长文退回「短行 + 冒号结尾」（「政府：」「金融：」「智慧教育」）当伪标题，或者干脆用 beats 当目录并给每条一个正文锚点（现在 beats 没有位置信息，这是 A5「为什么给我看这条」的同一个缺口）。
4. **含数字的段 3/4 没点，图例却说「只看含数字的段」**（162 段 → 40 点）。用户：「这段明明有数字，怎么没点？」
   根因 a：`relations.py:18` 单位表缺 年 / 卡 / 辆 / 秒 / TB / 度 / kW / MW / 平方公里，裸年份「2020年」不算日期（71 段）；
   根因 b：`relations.py:275` 只要 `related` 非空就不报缺依据，而 `overlap()` min 归一让「wifi」「ai」一个词就 0.33–0.67（51 段）。
   建议：a 补单位 + 「YYYY年」当年份；b 「缺依据」改成「没有一条事实跟这段共享任何一个量」，`related` 门槛加 `|∩| ≥ 2`。
5. **两个位置该亮没亮（#3、#7）**——比「没点」更糟的是**错过了库里一模一样的话**（N4 L27 ↔ `1439-0F4`「6 月末或 7 月」）。
   根因：`extract_values` 只认「X月X日」；「6月末/7月」「六月末或七月」「三类」「三百台」都是空（P1 记过的中文数字盲区，本轮 N3 #5、N4 #7、N5 整篇三处实证）；`<|start|>` 这种乱码被 `_EN` 当英文词。
   建议：日期加月级（「6月」「6月末」「六月末」→ `2026-6`）、中文数字归一（一…十百千万）；查询词剔掉 `<|…|>` 里的东西；月级印证允许「同月」。
6. **记忆列表退化到一个泛词，给一屏不相干**（N5 `记录` → Vlog / 日志 5 条；N1 `ai 华为 90%`；N3 末段讲学位却全是 `ui`）。用户：「这跟我写的有什么关系？」
   根因：`search._terms` 留下任何词表命中，`rank` 对长查询没有「至少命中 2 个内容词」的下限；第 747 轮那条「长句全被剔光就返回空」只管全剔光、不管只剩一个泛词。
   建议：自动召回（查询 ≥100 字）要求每条命中 ≥2 个不同内容词、且不能只靠 ≤2 字的词；命中不到就显示「这段没有能查的具体词」而不是凑 5 条。顺带把 `terms` 里「小时预」「并以」「号上众」这种切碎的 bigram 别显示给用户（A5）。
7. **记忆列表跟光标无关**：它只看正文末 500 字（`RelatedMemory.tsx:100`），用户在 N1 顶部写华为芯片，右栏是恒瑞翻译的记忆（或者因为退化，是它自己前半段）。
   建议：记忆列表也按光标段落（`paragraph` 已经传进来了，关系卡就在用），末 500 字只在光标在文末时用。
8. **给他看的记忆是他刚写的**（N4 5/5 相关，全是正文逐字引过的原话；N3、N2 也各 1–2 条）。不算错，但零信息量。
   建议：召回结果里跟正文任一段 `overlap ≥ 0.8` 的标成「已在正文 L 某」折叠，把位子让给新的（N2 的 `2394-3F16`「why not just use ChatGPT」就是该浮上来的那种）。
9. **叠加 / 合并卡的事实不相干**（L97 400万用户 ↔ 10秒10分钟；L135 GB级 ↔ 64GB/10GB；L283 ↔ 「这个也是新加坡的」×2）。
   根因：`relations.py:283-300` 叠加只要 `overlap ≥ 0.2` 且对面有正文没写的单位；`_merge_candidate` 在召回池里两两比，跟正文是否相关无关。
   建议：叠加要求共享 ≥1 个单位或 ≥3 个内容词；合并候选两条都得跟正文 `overlap ≥ 0.3`；转写成「社会社会」的会话在入库时就该丢。
10. **「零模型」差一个条件**：`/relations` 有冲突候选时会打模型（`memory.py:198`），图例写的是零模型。建议图例改成「圆点零模型；关系卡里的冲突会让模型复核一次」。

### 闸 / 指纹 / 成本

- 没改产品代码，没跑测试套件（不适用）。
- `notes` 指纹开工 / 收尾：482 行 / `max(updated_at)=2026-09-16T02:53:27` / 321,250 字 / `47dcc54be60aa4f2` / `note_revisions` 44 —— **一个字没动**
  （真库只读打开一次算指纹；所有请求打的是 8791 端口上 `KITE_DATA_DIR=$S/p4data` 的拷贝，拷贝上的 `PUT /skeleton` 回放只写了拷贝）。
- 真模型调用 **5 次**（全在 D1），36,060 token；D2 **0 次**。
