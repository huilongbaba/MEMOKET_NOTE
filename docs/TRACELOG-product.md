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
