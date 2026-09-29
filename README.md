# MEMOKET NOTE

**桌面顶部灵动岛**：默认只有屏幕顶部一个入口，首次展开进入笔记，随时记录、接入内容并调用 AI；之后重新展开保留上次使用的面板。悬停 120 ms 展开，离开 260 ms 后按状态收起；弹簧动效可在途中反向，内容保持稳定，悬停不抢当前应用焦点。暂存箱、知识库与专注通过顶部的分段标签进入；`⌘⇧N` / `Ctrl+Shift+N` 直接打开笔记编辑器。浮窗是一块纯黑的物体，与刘海连成一体：写作时正文下方一行「N 条相关记忆」把知识库里相关的事实带到眼前，点「引用」即写入草稿并带上来源标记；「知识库」标签则是同一索引的搜索入口，不是聊天框。完整笔记库保留为长文编辑、搜索与资料整理的次入口。交互规则、原生拖放及权限边界见 [灵动岛开发说明](docs/desktop-layer.md)。

笔记直接展示正文编辑器。需要 AI 时，在正文中右键或打开底部紧凑菜单，调用**整理笔记、一键续写、提炼要点、生成图表、整理表格、提取待办**；暂存架没有常驻 AI 按钮，这六项功能也不在主页铺开。处理范围优先使用选中文字，没有选区时使用当前笔记正文，空稿则使用界面上显示的剪贴板候选；菜单会标明本次范围。AI 在后台处理，笔记底部仅显示一行任务状态；可以继续编辑、使用暂存架或专注，也可以收起浮窗。完成后结果直接写进正文：续写只写 3–5 行，到自然停顿处就停；整理替换所处理的范围，提炼、图表、表格、待办插在范围之后；底部留一行「已写入 N 行 · 撤销」，一键退回。只有「从暂存架选择」的材料流仍在小面板里预览后再保存。

**拖文件或图片时选择用途**：仅在拖入期间显示左右两个目的地，左侧「附加到笔记」把文件复制为当前草稿的附件，图片显示真实缩略图，保存时连同可用资源链接写入笔记；右侧「放入暂存箱」保留独立临时副本，不改笔记。一次释放只写入选中的目的地，拖离后取消分区。附件随草稿保留，收起浮窗不会丢失，也不会因为附到笔记而自动进入暂存架。原文件不移动或删除。

展开「随手记」时，当前剪贴板文字直接以浅色预览出现在正文编辑区；按 `Tab` 才接入草稿，继续输入或按 `Esc` 忽略，不再占用顶部卡片空间。尚未接入正文或明确用于 AI 处理的候选只在内存中，不保存历史、不创建笔记，也不发送给模型。也可从 AI 菜单进入暂存材料选择。专注计时与工作台共享同一用户的本机进度，收起后在小岛上继续显示剩余时间。

暂存架以纯黑背景衬托一行四个真实内容缩略图，点击可在浮窗内看大图；搜索按需展开，「添加」菜单集中放置文件、剪贴板、窗口、文字与链接入口。暂存只负责放入、预览和取回，不自动生成笔记或调用 AI。文档页面由 macOS Quick Look 在本机生成，窗口使用实际静态截图；无法预览会说明原因。文件导入会在本机保留独立副本，原件不动；移除副本后可从已移除文件夹找回。旧版路径引用保持原状，并在界面中标明。

浏览器交互预览：依赖准备后运行 `bash scripts/dev-workspace.sh`，打开 [顶部灵动岛预览](http://127.0.0.1:5178/?user=ui-review&surface=preview)。记录连接真实笔记接口，专注使用本机计时，新数据目录为空；浏览器没有原生暂存桥接或自动剪贴板候选，不能代替桌面的跨应用拖放、系统剪贴板与窗口唤回。该脚本默认关闭外部模型调用，显式加 `--use-provider` 才使用启动环境中的模型配置。安装步骤和完整笔记库功能见 [工作台开发说明](docs/desktop-workspace.md)。下面保留原有功能及架构说明。

AI 驱动的编辑器 + 个人知识库。写作时自动引用你自己的记录，语音和文档都能入库。
长期记忆由 [KITE](https://github.com/memoket/memoket-kite) 提供。

前后端分离，基础笔记与知识库可在本地运行。使用 Gemini 时，会在明确点击后把本次选中的文字、链接摘录、纯文本文件节选及要求发送给 Google；不会读取网页全文、图片或其他未选材料。

## 功能

| 功能 | 说明 |
|---|---|
| **顶部灵动岛** | 首次展开进入笔记；存入的笔记自动进知识库（后台抽取，底部一行说进度）；拖文件时左边附到当前笔记、中间交给 Claude、右边放入暂存架；会话、待办和完整笔记库按需进入 |
| **拿主意** | 双击 ⌃ 框一块屏幕（不用先选中），或任何应用里选中文字按 ⌥D（没选中就用刚复制的那段文字或那张图），岛先在药丸里想、答案到了才展开，给出 3–4 个选项和校准过的概率（Jev 判断与打分，Gemini 出候选，理由引用知识库事实）；不是决定题先反问三个问题；选定后记下来 / 变成待办 / 问 Claude 展开 |
| **会话** | 岛上直接和 Claude Code 对话：无头运行本机已登录的 `claude`，选模型、续接会话；回复一键引用到笔记或存为笔记，产出的文件一键放入暂存箱。只允许读写会话工作目录里的文件，不跑命令，不带 MCP 连接器；拖进来的文件随下一句一起发 |
| **剪贴板候选** | 仅展开随手记时预览当前文字，Tab 接入正文，长内容提示粘贴全文；不自动存入笔记或暂存架 |
| **待办** | 今天要做的几件事，与工作台首页「今日重点」是同一份本机列表；勾选、回车添加、悬停删除，前几天没做完的一键移到今天；收起后岛上显示下一件待办 |
| **浮窗 AI 菜单** | 从正文右键或底部菜单调用整理、续写、提炼、图表/表格、待办；选区优先，其次当前正文，空稿可用显示的剪贴板候选；结果默认真实预览，原材料与草稿保留 |
| **magic tap 续写** | 先查知识库，命中就据此续写；没命中退回模型自由发挥。流式输出 |
| **写作骨架**（线 1） | 为当前正文提炼主线逻辑，作为后续编辑和续写的依据 |
| **智能编辑**（线 2） | 对照骨架和知识库检查正文，以 track-changes 形式给出修订，逐条接受/拒绝，**绝不直接覆盖原文** |
| **语音入库** | 录音 → Whisper 转写 → 抽成结构化事实存入知识库 |
| **语音输入** | 录音 → 转写 → 直接插到光标处 |
| **批量导入** | 多文件（PDF/DOCX/TXT/MD/音频）一次上传，每个文件独立处理、失败不拖垮整批，SSE 推进度 |
| **知识库检索/提问** | 两条路径，见下 |
| **知识库可视化** | 概览 / 主题地图 / 时间线 / 事实表，事实展开可回溯到原文出处 |
| **写作 harness** | 「写一轮 → 判一轮 → 决定继不继续」的自动循环。八个功能共用同一份循环，差别全部表达成配置。见下 |
| **Skill** | 用 SKILL.md 目录教它你的写法。菜单按需加载（先给一行简介，模型要用才读全文），第三方 skill 的脚本跑在沙箱里 |
| **主题簇 / 抽取判据** | 知识库自己的质量闭环：事实聚成主题簇、抽取质量用同一套打分引擎判 |
| **笔记树**（照 Trilium） | 没有文件夹：有子节点的笔记就是文件夹。同一篇可以**克隆**到多处（改一处处处都变），拖拽移动，系统里的 .md 直接拖进树就成笔记，键盘导航，右键菜单里直接长着 harness 的动作 |
| **笔记图标**（照 Trilium 的 NoteIcon） | 标题行图标点开选择器挑一个（⌘K「换个图标」/ 树右键也行），树 / 标签 / ⌘K / 链接面板同一个；日记、定期回顾、导入建出来的笔记自带图标；随导出 front-matter 走、再导入还原 |
| **知识库长在树上** | 知识库是树底部的一棵虚拟子树（主题 / 实体 / 时间线 / 最近摄入 / 总览 / 主题地图 / 回顾）。一条事实打开就是一篇只读笔记；正文里的 `[引用]` 悬停看出处，树上直接看每篇引用了几条（◆N）、摄入过没有（⇡） |
| **笔记之间的链接** | 正文里打 `[[` 搜标题插 `[标题](note://id)`，光标不在上面时折成一枚可点的标记，悬停看摘要；ribbon「链接」列链出 / 链到这篇的（Trilium 的 referenced by） |
| **日志落盘** | 桌面主进程日志（含后端输出）写到 ~/Library/Logs/memoket-note-desktop/memoket-note.log，2MB 滚一代；帮助菜单「打开日志文件夹」「导出后端日志」 |
| **自动备份** | 后端每次启动一天一份笔记库备份（sqlite 在线备份，留最近 7 日 + 3 个月），帮助菜单「打开备份文件夹」；整库还能随时导出成 Markdown zip。启动时空页太多会 VACUUM，删掉的东西不会让库和备份一直胖下去 |
| **历史版本** | 保存时正文变了且离上一版超过十分钟自动留一版，也可手动存版；ribbon「历史」里预览、一键恢复（恢复前先把现在存一版，永远可逆） |
| **定向续写 / 从光标处续写** | 智能续写让模型先说「放到哪一节」，位置由代码算、前端就地插入；「续写」在光标处写（后文当衔接） |
| **完整笔记库** | Electron 桌面版按需打开完整窗口，后端随 .app 打包。保留标签页、可折叠分栏、前进后退、页内查找、命令跳转、快捷键表与浅深主题 |

## 架构

```
桌面 (Electron, desktop/)   单顶部灵动岛 + 按需打开完整笔记库；托管后端与构建后的前端
    │
前端 (Vite + React, :5173)  顶部小面板；完整笔记库保留树 · 标签行 · 编辑器 · 上下文右栏
    │  HTTP / SSE（AG-UI 事件）
后端 (FastAPI, :8000)
    app/
      harness/     agent 运行：一份循环 · Mode · 判据 · middleware · 工具 · skill · 沙箱
      database/    知识库和数据库：sqlite · KITE 适配 · 主题簇 · 摄入
      editor/      既不是 agent 也不是知识库的那部分：大纲 · 重排 · 图片转表格 · 画像
      routers/     和前端对接：认 Mode、装 State、翻事件
      util/        公共：配置 · LLM 客户端
    │
shared/          前后端共同的判据（见 shared/README.md）
    │
    ├── KITE Memory      每用户一个 XML codebook
    ├── Gemini           原生 REST：显式选材 → 整理草稿 → 用户确认保存
    ├── LLM              完整笔记库原有 AI 使用 OpenAI 兼容端点
    └── Whisper Turbo    whisper.cpp server
```

**一份循环，八个功能共用。** 之前是三份手抄的循环（555 + 245 + 156 行），
「这条 harness 有、那条没有」的 bug 付了四次学费。现在加一条 harness ＝ 写一个
`Mode`（配置）加三个回调，循环本身不用碰。判据分两半：代码能确定判的用
`Check`（零成本、能自动修），只有模型判得了的才走 `Dimension`——打分的和被
打分的是同一个本地模型，它的盲区跟写作者的完全重合。

## 关键设计：检索为什么不走 KITE 原生 API

KITE 的 `recall()` / `answer()` 会用 LLM 把问题编译成查询计划（`compile_plan.py`）。
在本地 30B 模型上实测：

| 操作 | 耗时 | LLM 调用 |
|---|---|---|
| 原生 `recall()` | 188.6s | 3 次 |
| 降低推理强度后 | 51.5s | 3 次 |
| **本项目的符号检索** | **~1 ms** | **0 次** |

profiling 显示 `recall()` 的 38s 里，**本地符号检索只占 0.0s，100% 的时间都在 LLM planning**。

所以本项目把两件事拆开：

- **入库（异步，可以慢）** —— 走 KITE 原生 `remember()`，用 LLM 抽取结构化事实。约 13s/段，后台跑。
- **检索（交互路径，必须快）** —— 用 `Vocab.resolve_topic/resolve_entity` 做确定性符号解析，
  手工构造 plan dict 交给 `execute_plan()`。零 LLM，亚毫秒。

**代价**：失去意图理解和时序推理（"现在谁负责" 这类需要按时间取最新的问题）。
所以保留了 `/api/memory/ask` 走原生 planning，用在用户主动提问的路径 —— 那里用户
按下按钮就知道要等，而且确实需要推理能力。写作路径一律用零 LLM 的 `/recall`。

### 跨语言检索

KITE 的抽取提示词是英文的，中文输入有时抽出英文 fact，符号通道匹配不上。
但原始 `<line>` 保留了中文原文，所以有三级回退：

1. 符号匹配（topic / entity）
2. 英文词法 grep
3. **中文 n-gram grep 原始行 → 定位 session → 取该 session 的 facts**

n-gram 生成有两个要点：从**最靠近光标的片段**开始（续写时正文尾部才相关），
按片段**轮转取样**（否则第一个长片段会吃光候选配额）。

## 设计文档

| 文档 | 内容 |
|---|---|
| [`docs/harness-framework.md`](docs/harness-framework.md) | **写作 harness 的完整设计**：为什么循环要硬编码、判据为什么分两半、能力为什么做成默认全开的 middleware。第 3 节是目录地图，`tests/test_directory_map.py` 盯着它跟代码一致 |
| [`docs/kb-architecture.md`](docs/kb-architecture.md) | 知识库这一侧：主题簇怎么聚、抽取质量怎么判、检索计划怎么定 |
| [`docs/import-from-other-note-apps.md`](docs/import-from-other-note-apps.md) | 从别的笔记应用导入 |
| [`docs/kite-constraints.md`](docs/kite-constraints.md) | 读 KITE 源码得出的 8 条硬约束，每条标了源码位置。升级 KITE 后应重新核对 |
| [`docs/_research/P0-findings.md`](docs/_research/P0-findings.md) | 中英文对照实测，量化了中文召回的退化幅度 |
| [`docs/_research/PLAN.md`](docs/_research/PLAN.md) | 后续路线 |

## 快速开始

```bash
cd backend
cp ../.env.example .env   # 按需改 LLM / Whisper 地址（后端从自己的目录读 .env）
python3 -m venv .venv     # Python 3.11–3.14 都验证过；requirements 里的 memoket-kite 装自 GitHub，需要 git 和网络
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
PYTHONPATH=. .venv/bin/uvicorn app.main:app --reload --port 8000

cd ../frontend
npm install
npm run dev               # http://localhost:5173
```

`GET /api/health` 会报出 LLM 和语音服务是否可达。

## 桌面版

先准备后端虚拟环境和前端依赖，桌面版使用构建后的前端：

```bash
npm --prefix frontend run build
cd desktop && npm install
npm run dev            # 编译桌面壳并启动 Electron，默认显示顶部灵动岛；不启动 Vite
npm run dist           # 打包：先 PyInstaller 后端、再 electron-builder → out/*.dmg
npx electron . --user=<id> --probe=<name> --dark   # 截图核对用：固定用户 / 摆好某个界面状态 / 强制暗色
```

灵动岛的「拿主意」（⌥D 读选区 / 剪贴板，双击 ⌃ 框一块屏幕）还要三样：

- **密钥**：Gemini（出候选、读图）和 Jev（判断是不是决定题、给概率），见下文「配置」；没有 Jev 时概率是 Gemini 的估计并标「模型估计」。
- **权限**：系统设置 › 隐私与安全性 里给 Electron（打包后是 MEMOKET NOTE）**辅助功能**和**自动化 › System Events**；双击 ⌃ 截图另需**屏幕录制**。第一次用时系统会问。
- **双击 ⌃ 的原生辅助进程**由 `npm run build:helpers` 编（`npm run dev` / `npm start` 自带），要 Xcode Command Line Tools 里的 `swiftc`；没有就只少这一条入口，⌥D 照旧。

`--workspace` 可直接打开完整笔记库。新暂存文件使用独立副本，原文件保持原状；旧记录仍保留原路径引用。窗口暂存是静态预览与引用，目前仅 macOS 支持列出和唤回，需要屏幕录制及辅助功能权限，权限不足会说明原因。更多操作与启动环境配置见 [灵动岛开发说明](docs/desktop-layer.md)。

打包出来的 .app 自带后端（`Contents/Resources/backend/`），数据落在
`~/Library/Application Support/memoket-note-desktop/data/`——**不在 .app 包内**，
更新时不会跟着包被替换掉。见 `docs/desktop-plan.md` 与 `docs/TRACELOG-trilium.md`。

## 测试

灵动岛与独立 Gemini 生成接口的回归：

```bash
# 仓库根目录
npm --prefix desktop test
cd frontend
npm exec -- vitest run src/components/__tests__/desktopCompanion.test.tsx
cd ../backend
PYTHONPATH=. .venv/bin/pytest -q tests/test_desktop_notes.py
```

以上使用模拟 OS 依赖与 Gemini 响应，不读取真实桌面或调用真实模型。其他前后端回归保持原入口：

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt
PYTHONPATH=. pytest -q                     # 950 条，约 42 秒，不需要模型

cd ../frontend && npm test                 # tsc + eslint + vitest + 检查脚本；其中几个对拍脚本要用 backend/.venv，先按上面把后端装好
```

两道闸门都在 `.github/workflows/ci.yml` 里，每次 push 和 PR 自动跑。

后端全部不打模型：判据、循环、middleware、修订的四道防线都靠打桩驱动，
所以跑得起来、跑得快。真实模型只在 `backend/scripts/` 下的 bench 里用。

前端 `npm test` 串起四样：类型检查、ESLint（只开抓 bug 的规则）、`src/editor/__tests__/` 下的单元测试、
以及 `frontend/scripts/` 下的十九个检查脚本（格式化幂等性、撤回可逆性、
diff 状态层、`/` 菜单、表格预览、图谱/编辑器/skill 导入 smoke、文档里的 mermaid 能不能画、
TSX 用到的类名 CSS 里得有 + 反向查死样式、可点的 div 键盘也能按）。其中六个是**前后端对拍**：客户端在轮内镜像服务端
的正文变换（修订重放 `check-revision-parity`、引用 / 链接正则 `check-regex-parity`、
删元话语句子 `check-scrub-parity`、空行归一 + 定向插入 `check-stream-parity`、同名消歧的正文首行 / 显示名 `check-preview-parity`、字数 `check-wordcount-parity`），
样本同时喂 TypeScript 和 Python 两份实现，结果不一样就红——两份实现是有意的（服务端
要在没人审核时自动应用），代价就是会漂，靠这四个盯着。
`backend/tests/test_api_contract.py` 盯着「每个检查脚本都被 npm test 跑到」
——写了却不执行的检查比没写还糟，读的人会以为这块被守着。

### 实拍探针（界面级回归）

界面的每个状态都能用 `--probe=<name>` 把桌面版驱动到那里、`--shot=` 自截图（capturePage，
不依赖系统截屏），后端日志和前端 client-log 一起落到同名 `.log`：

```bash
cd desktop && env -u ELECTRON_RUN_AS_NODE npx electron . --user=<用户> --probe=tabs --shot=/tmp/tabs.png --shot-delay=6000
```

探针清单在 `frontend/src/App.tsx` 的探针 effect 里（palette / shortcuts / slash / mention / wikilink /
sel:* / ribbon:<tab> / harness:<id> / tap:<id> / plan-run:<id> / delete:<id> / draft:<id> / imgdrop …），
`--dark` 看暗色，`--win=900x600` 看窄窗。探针模式下 `save()` 被拦截，截图不会污染真实笔记；
`harness:` / `tap:` 会在服务端改笔记，只对草稿笔记跑。

## 配置

顶部「整理成笔记」使用 Gemini 原生 API。同一份凭据也给知识库的事实抽取用：没配本地模型或 GPT 时，抽取走 Gemini 的 OpenAI 兼容端点，岛上存的笔记才进得了知识库。启动环境提供 `GEMINI_API_KEY`，或设置 `MEMOKET_GEMINI_KEY_FILE` 指向仅含密钥的本机私密文件；同时设置时环境密钥优先。`GEMINI_MODEL` 可配置，目前默认为已完成一次真实生成验证的 `gemini-3.5-flash`。「拿主意」的 Jev 密钥同理：`JEV_API_KEY`，或 `MEMOKET_JEV_KEY_FILE` 指向仅含密钥的文件。密钥文件建议放在 `.local/secrets/`（整个 `.local/` 已在 .gitignore 里）。密钥不返回给前端，也不要写进仓库。例子只包含文件路径：

```bash
MEMOKET_GEMINI_KEY_FILE=/absolute/path/to/private/gemini-key \
MEMOKET_JEV_KEY_FILE=/absolute/path/to/private/jev-key \
GEMINI_MODEL=gemini-3.5-flash \
  npm --prefix desktop start
```

完整笔记库原有 AI、视觉与语音功能仍使用各自的供应商配置。旧样板指向内网服务，切 OpenAI 兼容 API 时可修改对应 `.env` 配置：

```bash
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4.1-mini
```

## API

| 端点 | 说明 |
|---|---|
| `GET /api/desktop/ai-status` | Gemini 是否已配置、模型名与供应商；不返回密钥，配置存在不等于生成已成功 |
| `POST /api/desktop/compose-note` | 根据 1–12 项明确选中的文字/链接生成带来源的可编辑草稿；总输入上限 30,000 字符，不自动保存 |
| `GET/POST/PUT/DELETE /api/notes` | 笔记 CRUD（新建时同时挂到树上） |
| `GET /api/tree` · `POST/DELETE /api/tree/branches` · `PATCH .../move` `.../reorder` `.../expanded` · `GET .../paths/{id}` | 笔记树：整棵拿全（带引用数/摄入标记）、克隆、摘除、移动、拖拽重排、展开、一篇在树上的所有路径。**没有文件夹这种东西**——有子节点的笔记就是文件夹 |
| `GET /api/kb/tree` · `GET /api/kb/tree/children` | 知识库的虚拟子树：分类层一次给全，展开一个分类时才取它名下的事实（实体超过 200 个、多段材料的各段也是展开时才取） |
| `GET /api/notes/brief` | 轻量笔记列表（不带全文，`?q=` 搜）：⌘K 和 `[[` 补全每敲一个字用的；正文命中带片段和第一行正文 |
| `POST /api/notes/{id}/icon` | 给笔记设图标（boxicons 类名如 `bx-rocket`，空串清掉）；树、标签、标题行同一个图标 |
| `POST /api/notes/today` · `GET /api/notes/trash` · `POST /api/notes/trash/{id}/restore` | 今天的日记（日记 / 年 / 月 / 日，没有就建）；最近删除（软删 30 天，恢复时父链一起回来） |
| `GET /api/notes/{id}/revisions` · `POST /api/notes/{id}/revisions` · `GET /api/notes/{id}/links` · `POST /api/notes/{id}/pin` · `PUT /api/notes/{id}/skeleton` | 历史版本（自动 + 手动，可恢复）、笔记之间的链接（链出 / 链入 / 链到已删笔记的 `dangling`）、置顶、写作骨架 |
| `GET /api/notes/{id}/graph` | 这篇周围有什么：正文引用的 + 它贡献的事实挂在哪些主题 / 实体上，ribbon「引用」里画成局部图（Trilium 的 NoteMap 在我们这儿的样子） |
| `GET /api/export/markdown` · `POST /api/export/obsidian` · `POST /api/import/files` · `POST /api/import/notion` · `POST /api/import/feishu` · `POST /api/import/apple` | 整库导出 zip / 导回 Obsidian 目录；从 Obsidian / Evernote / Notion / 飞书 / Apple 备忘录导入（可断点续跑 `POST /api/import/jobs/{id}/resume`） |
| `POST /api/kb/fact` · `PATCH /api/kb/fact/{id}` · `DELETE /api/kb/fact/{id}` · `POST /api/kb/fact/merge` · `GET /api/kb/conflicts` · `POST /api/kb/conflicts/{id}/resolve` | 手工加 / 改 / 删 / 合并事实；冲突收件箱 |
| `GET /api/kb/dashboard` · `GET /api/kb/topic/{code}` · `GET /api/kb/entity/{code}` · `GET /api/kb/unit/{id}` · `GET /api/kb/timeline` · `GET /api/kb/quality` · `POST /api/kb/rebuild` | 知识库各页的数据；抽取质量；重建索引 |
| `POST /api/digest` · `POST /api/verify` · `POST /api/expand` · `POST /api/rewrite` | 定期回顾、选中文本校验 / 扩写 / 重写 |
| `GET/POST /api/skills` · `PUT/DELETE /api/skills/{id}` · `POST /api/skills/generate` · `GET/POST /api/profile` · `GET/POST /api/settings/provider` · `GET /api/settings/usage` | 写作 Skill、个人偏好、LLM / 语音供应商、模型用量 |

完整接口清单看后端自带的 Swagger：应用跑起来后开 `http://127.0.0.1:47231/docs`（开发实例 47232）。上表只列了读代码前该知道的那些。
| `GET /api/memory/facts/{id}` · `.../citing` | 一条事实（行内出处浮层用，找不到 404）· 哪些笔记引用了它（反向链接） |
| `POST /api/skeleton` | 线 1：生成写作骨架 |
| `POST /api/magic-tap` | 续写，SSE 流式（`meta` / `delta` / `done`） |
| `POST /api/memory/recall` | 符号检索，零 LLM，~1 ms |
| `POST /api/memory/trace` | **来龙去脉**：给一段正文，回它涉及的事按时间怎么演进的。问题由后端拼，用户不写 prompt——见 `docs/product-north-star.md` 判据 1 |
| `GET /api/memory/stats` | 知识库统计（facts/topics/entities/units/lines/speakers/日期跨度） |
| `GET /api/memory/topics` | topic 树（parents 字段构成层级） |
| `GET /api/memory/entities` | 实体列表 |
| `GET /api/memory/facts` | 事实表：分页 + 按 kind/who/conf_min/topic/entity 过滤 |
| `GET /api/memory/facts/{id}/sources` | 一条事实的原始出处（证据回溯） |
| `GET /api/memory/timeline` | 按日期聚合的 session 数 / fact 数 |
| `POST /api/ingest/text` | 文本入库（后台任务，返回 job_id） |
| `POST /api/ingest/audio` | 语音入库 |
| `POST /api/ingest/transcribe` | 只转写不入库 |
| `POST /api/ingest/batch` | 批量导入：多文件（PDF/DOCX/TXT/MD/音频）→ {job_id, items[]} |
| `GET /api/ingest/jobs` | 当前用户的入库任务列表 |
| `GET /api/ingest/jobs/{id}` | 入库任务状态（含批量任务的 items 明细） |
| `GET /api/ingest/jobs/{id}/events` | 批量任务的 SSE 进度流 |
| `POST /api/ingest/jobs/{id}/cancel` | 取消批量任务（已在处理的文件会跑完，未处理的直接标 cancelled） |
| `POST /api/note-harness/run` | 单篇 harness：一篇笔记内部自动修订 + 自动续写，SSE 推 AG-UI 事件 |
| `POST /api/writing-plan/start` · `/run` | 文件夹级无限续写：拆分段、每段各写一篇、写完再判断还缺不缺 |
| `GET /api/harness/paused` · `POST /api/harness/{id}/resume` | 轮末暂停与恢复（State 存成快照） |
| `POST /api/compose/block` | 编辑器里 `/` 唤起的块生成 |
| `GET/POST/PUT/DELETE /api/skills` | Skill 的增删改查、启停、排序、让模型自己生成一个 |
| `GET /api/kb/clusters` · `/coverage` · `/quality` | 主题簇、覆盖度、抽取质量（后两个是运维/诊断端点，界面上没有入口） |

用户身份走 `X-User-Id` 请求头，每个 user_id 对应一个独立的 codebook。
原型阶段没有认证，生产环境把 `routers/deps.py` 里的 `current_user` 换成真实鉴权即可。
桌面版后端只绑 127.0.0.1，且拒绝来源不是本机的写请求（`main.py` 看 `Origin` / `Sec-Fetch-Site`）：
CORS 只管读，跨站网页用 `<form>` / multipart 发的 POST 不预检、照样执行，这一层把它们挡在导入 / 上传接口外。

## 踩过的坑

- **思考内容关不掉**。Muse-Glimmer 总会先输出 `reasoning_content`，实测
  `reasoning_budget=0` / `thinking_budget=0` / `chat_template_kwargs` 都压不住
  （最好一档仍有 467 字符思考）。所以 `max_tokens` 必须预留额度 —— 见 `llm.py`
  的 `REASONING_RESERVE`。给小了正文会被截断甚至返回空字符串。
- **推理强度影响巨大**。交互路径一律 `reasoning_effort=low`，比 high 快 3 倍。
- **KITE 只从 `os.environ` 读 provider 配置**（`OPENAI_API_KEY` / `OPENAI_BASE_URL`），
  不走参数传递，调用前必须先 export。
- **KITE 的 `remember()` 不加锁**。它全量重写 XML，两个并发写会互相覆盖，
  且不报错 —— 事实会静默消失。写入必须持有 `kite_writer.write_lock()`，
  且 `Memory.load()` 要在锁**内**（锁外加载等于拿过期快照）。
- **anchor 必须逐字匹配**。修订建议里模型给的 anchor 如果不在正文中出现，前端
  定位不到，后端会直接丢弃这条。

## 许可证

AGPL-3.0-only，全文在 `LICENSE`。桌面壳与外观复用了 Trilium（AGPL-3.0），PDF 导入依赖 PyMuPDF（AGPL），
派生作品必须同一许可证；复用了什么、每个依赖的许可证见 `docs/third-party-notices.md`。
以网络服务方式提供本软件时，要向使用者提供对应源码（AGPL §13）。

## 已知限制

- 修订建议基于纯文本 anchor，不是富文本编辑器的 diff 引擎。用户改动 anchor 所在
  文字后，对应的修订会自动失效并从面板消失。
- 跨语言提问（中文库用英文问，反之亦然）召回率低 —— 符号引擎没有语义嵌入。
- 没有认证。原型定位，`routers/deps.py` 的 `current_user` 是占位。
