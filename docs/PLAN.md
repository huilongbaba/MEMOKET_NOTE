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

## 2. 批量导入 + 多格式

当前 `/api/ingest/text` 收单条正文，`/api/ingest/audio` 收单个文件。
需要扩成批量 + 文档格式。

```
多文件上传 → 建 job（含 N 个 item）
     ↓  每个 item 独立处理，失败不拖垮整批
  ├─ 音频 wav/mp3/m4a/flac → Whisper（已接）
  ├─ PDF   → PyMuPDF，保留页码
  ├─ DOCX  → python-docx
  └─ TXT/MD→ 直读，markdown 按标题层级切分
     ↓
  复用现有 _chunks() 切分
     ↓
  投递到该用户的单写者队列（第 1 节）
```

**幂等**：`session_id` 用 `{doc_id}-{chunk_idx}`。KITE 在 LLM 调用之前就拒绝
重复 session_id（约束 3），失败重跑既不写重也不浪费 LLM 调用。

**成本**：实测约 13 s/chunk。100 个文档 × 10 chunk ≈ 3–5 小时。
批量导入本质上是**小时级后台任务**，job 必须能后台跑、能续、能看进度。

## 3. 异步进度接口

当前只有 `GET /api/ingest/jobs/{id}` 轮询。批量场景需要推送。

```
POST /api/ingest/batch              多文件 → {job_id, items[]}
GET  /api/ingest/jobs/{id}/events   SSE 进度流
POST /api/ingest/jobs/{id}/cancel
GET  /api/ingest/jobs               历史列表
```

item 状态机：`queued → extracting → transcribing → chunking → remembering →
done | failed | cancelled`

magic tap 已经在用 SSE，前端有现成的处理方式可复用。

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
