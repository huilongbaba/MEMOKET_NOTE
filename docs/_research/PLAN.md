# 后续路线

现状：笔记 CRUD、骨架线、修订线、magic tap、单条文本/音频入库、符号检索
都已实现（见 README）。本文档只列**剩余工作**。

## 1. 并发写保护 ✅ 已完成

实现在 `app/kite_writer.py`，`UserMemory.remember()` 全程持锁。

两层锁：进程内 `threading.Lock` 覆盖 `BackgroundTasks` 线程池，
文件锁覆盖 `uvicorn --workers N` 的多进程部署。锁粒度是单个 codebook 文件，
不同用户可以并行（KITE 只禁止同一文件的并发写）。

回归测试见 `tests/test_write_lock.py`。其中 `test_unlocked_writes_lose_data`
刻意断言「不加锁就会丢数据」—— 没有这条基线，其他测试通过也可能只是并发没撞上。

## 2. 批量导入 + 多格式 ✅ 已完成

`POST /api/ingest/batch` 收多文件，PDF/DOCX/TXT/MD/音频混着传：

```
多文件上传 → create_batch_job() 建 job + N 个 item
     ↓  顺序处理，单个 item 失败不拖垮整批（try/except 包一层）
  ├─ 音频 wav/mp3/m4a/flac → asr.transcribe()（已接）
  ├─ PDF   → extract.py，PyMuPDF，逐页标 [pN]
  ├─ DOCX  → extract.py，python-docx，读段落
  └─ TXT/MD→ 直读；MD 按标题行先切段（_markdown_sections），
              再对每段跑 _chunks_for()
     ↓
  mem.remember()，session_id = f"{item_id}-{chunk_idx}"
```

实现：`app/extract.py`（格式提取）+ `routers/ingest.py` 的 `_batch_job` /
`_chunks_for` / `_markdown_sections`。`store.py` 新增 `ingest_items` 表，
`update_job_from_items()` 把 item 状态聚合成 job 状态。

**幂等**用的是 item_id（uuid）而不是文档路径 —— 重跑同一批次会产生新
session_id，不去重；如果要支持"重新导入同一份文档不产生重复 fact"，
还需要按文件内容 hash 复用 item_id，目前没做。

回归测试见 `tests/test_batch_ingest.py`：切块规则、格式提取、
job/item 状态聚合（含"有一个失败但其余成功"这类场景）。

## 3. 异步进度接口 ✅ 已完成

```
POST /api/ingest/batch              多文件 → {job_id, items[]}
GET  /api/ingest/jobs/{id}/events   SSE 进度流（已实现）
POST /api/ingest/jobs/{id}/cancel   已实现
GET  /api/ingest/jobs               历史列表，已实现
```

item 状态机：`queued → extracting → [transcribing] → chunking →
remembering → done | failed | cancelled`，与计划一致。

**实现方式**：没有引入消息队列 —— `/events` 是轮询 SQLite（0.7s 一次），
状态没变化就不推帧，job 到终态推 `end` 事件后关闭连接。批量任务本身
在一个 `BackgroundTasks` 里顺序处理所有文件（没有跨文件并发），取消
语义因此很简单：正在跑的文件跑完，还没轮到的直接标 `cancelled`。

前端：`api.ts` 的 `watchJob()` 复用了 magic tap 的 SSE 帧解析方式；
`MemoryPanel.tsx` 加了"批量导入"区块，多文件选择器 + 实时进度列表 + 取消按钮。

**已知取舍**：顺序处理意味着一个文件卡住（比如 LLM 调用挂起）会让队列里
后面的文件都等着。真要支持并发，`remember()` 本身的锁允许同用户多文件
并发写（第 1 节的锁按文件粒度，不是按用户），可以把 `_batch_job` 里的
顺序 for 循环换成有限并发（比如 asyncio.Semaphore(3)），但目前没有实测
瓶颈在哪，先不做。

## 4. 知识库可视化 ✅ 已完成

```
GET /api/memory/topics              topic 树（parents 字段构成层级）
GET /api/memory/entities            实体，按 type 分组
GET /api/memory/facts               分页 + 按 kind/who/conf_min/topic/entity 过滤
GET /api/memory/facts/{id}/sources  原始证据
GET /api/memory/timeline            按 session date / fact t 聚合
GET /api/memory/stats               扩充：units/lines/speakers/日期跨度
```

**实现取舍：没有用 `CodebookInspector`**。计划里原本设想走 KITE 的
`research.CodebookInspector`，但上游明说那不是稳定 API（约束 8），需要包一层
适配器隔离。实际做下来发现完全不需要 —— `CodebookInspector` 底层也只是包了一层
`core.Store` / `core.Vocab`（`UserMemory._index()` 已经在用的那一层，`recall()`
也走这条路），直接读 `store.facts.values()` / `vocab.topics` / `vocab.downset()`
就够了，反而比引入 research 模块更少一层不稳定依赖。代价是分页/过滤是在 Python
里线性扫描 `store.facts`（KITE 的 query 算子没有 skip/offset 这种分页原语），
量级到几万条 fact 之前应该没问题，之后要分页就得自己加索引。

实现：`app/kite_memory.py` 新增 `topics()` / `entities()` / `facts_page()` /
`fact_sources()` / `timeline()`；`routers/memory.py` 挂对应端点。
`facts_page()` 的 topic 过滤走 `vocab.downset()` 做子主题闭包，语义跟 `recall()`
一致（父主题命中子主题下的 fact）。

前端 `components/MemoryBrowser.tsx`：模态框 + 四个 tab（概览 / 主题地图 /
时间线 / 事实表），从 `MemoryPanel` 的「浏览」按钮打开。主题地图和实体列表点
一条会跳到事实表并带上对应过滤条件。**证据回溯**（PLAN 原本最看重的部分）：
事实表点开一条才按需调 `/facts/{id}/sources`，不在列表页把每条的原文都查一遍。

用真实 LLM 端到端跑通过一遍（批量导入一份 md → 抽出 5 条 fact → 四个可视化端点
都能正确读到），另外给纯逻辑部分（分页/过滤/聚合）写了 10 个单元测试
（`tests/test_memory_browse.py`），用真实的 KITE dataclass 手搭 Store/Vocab，
不用碰真实 XML 或 LLM。

## 5. 其他已知缺口

- 无认证（`routers/deps.py` 的 `current_user` 是占位）
- 修订建议基于纯文本 anchor，用户改动 anchor 所在文字后修订会失效
- 跨语言提问召回率低（符号引擎没有语义嵌入）
