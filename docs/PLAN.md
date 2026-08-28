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

## 4. 知识库可视化

当前只有 `GET /api/memory/stats`。数据源用 KITE 的 `CodebookInspector`，
不自己解析 XML。

```
GET /api/memory/topics              topic 树（parents 字段构成层级）
GET /api/memory/entities            实体，按 type 分组
GET /api/memory/facts               分页 + 按 kind/who/conf/topic/entity 过滤
GET /api/memory/facts/{id}/sources  原始证据
GET /api/memory/timeline            按 session date / fact t 聚合
```

前端四个视图：

| 视图 | 作用 |
|---|---|
| 概览 | 计数与入库趋势 |
| 主题地图 | topic 树，点击下钻到 facts |
| 时间线 | 按日期排布，体现时序推理 |
| 事实表 | 过滤 + 展开看原文证据 |

**证据回溯是重点**。`fact → src → 原始 line / 页码 / 音频时间戳` 这条链要打通 ——
这是 KITE 相对向量检索的核心差异，也是「构建出来的东西看得见」最有价值的部分。
后端已有 `UserMemory.source_lines()`，可直接复用。

`CodebookInspector` 属于 `research` 模块，上游明说不是稳定 API（约束 8），
需要包一层适配器隔离。

## 5. 其他已知缺口

- 无认证（`routers/deps.py` 的 `current_user` 是占位）
- 修订建议基于纯文本 anchor，用户改动 anchor 所在文字后修订会失效
- 跨语言提问召回率低（符号引擎没有语义嵌入）
