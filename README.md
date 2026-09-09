# MEMOKET NOTE

AI 驱动的编辑器 + 个人知识库。写作时自动引用你自己的记录，语音和文档都能入库。
长期记忆由 [KITE](https://github.com/memoket/memoket-kite) 提供。

前后端分离，可完全本地运行 —— 笔记内容不出内网。

## 功能

| 功能 | 说明 |
|---|---|
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

## 架构

```
前端 (Vite + React, :5173)
    │  HTTP / SSE（AG-UI 事件）
后端 (FastAPI, :8000)
    app/
      harness/     agent 运行：一份循环 · Mode · 判据 · middleware · 工具 · skill · 沙箱
      database/    知识库和数据库：sqlite · KITE 适配 · 主题簇 · 摄入
      editor/      既不是 agent 也不是知识库的那部分：大纲 · 重排 · 图片转表格 · 画像
      routers/     和前端对接：认 Mode、装 State、翻事件
      util/        公共：配置 · LLM 客户端
    │
    ├── KITE Memory      每用户一个 XML codebook
    ├── LLM              OpenAI 兼容端点（默认内网 Muse-Glimmer-30B）
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
cp .env.example .env      # 按需改 LLM / Whisper 地址

cd backend
pip install -r requirements.txt
PYTHONPATH=. uvicorn app.main:app --reload --port 8000

cd ../frontend
npm install
npm run dev               # http://localhost:5173
```

`GET /api/health` 会报出 LLM 和语音服务是否可达。

## 测试

```bash
cd backend  && PYTHONPATH=. pytest -q      # 649 条，约 35 秒，不需要模型
cd frontend && npm test                    # tsc + vitest + 10 个检查脚本
```

后端全部不打模型：判据、循环、middleware、修订的四道防线都靠打桩驱动，
所以跑得起来、跑得快。真实模型只在 `backend/scripts/` 下的 bench 里用。

前端 `npm test` 串起三样：类型检查、`src/editor/__tests__/` 下的单元测试、
以及 `frontend/scripts/` 下的十个检查脚本（格式化幂等性、撤回可逆性、
diff 状态层、`/` 菜单、表格预览、图谱/编辑器/skill 导入 smoke）。
`backend/tests/test_api_contract.py` 盯着「每个检查脚本都被 npm test 跑到」
——写了却不执行的检查比没写还糟，读的人会以为这块被守着。

## 配置

默认指向内网 DGX Spark 上的服务。切商用 API 只改 `.env`：

```bash
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4.1-mini
```

## API

| 端点 | 说明 |
|---|---|
| `GET/POST/PUT/DELETE /api/notes` | 笔记 CRUD |
| `POST /api/skeleton` | 线 1：生成写作骨架 |
| `POST /api/magic-tap` | 续写，SSE 流式（`meta` / `delta` / `done`） |
| `POST /api/memory/recall` | 符号检索，零 LLM，~1 ms |
| `POST /api/memory/ask` | 原生 planning 提问，支持时序推理，~50 s |
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

## 已知限制

- 修订建议基于纯文本 anchor，不是富文本编辑器的 diff 引擎。用户改动 anchor 所在
  文字后，对应的修订会自动失效并从面板消失。
- 跨语言提问（中文库用英文问，反之亦然）召回率低 —— 符号引擎没有语义嵌入。
- 没有认证。原型定位，`routers/deps.py` 的 `current_user` 是占位。
