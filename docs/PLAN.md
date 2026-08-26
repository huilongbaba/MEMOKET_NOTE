# 实施计划

## 批量导入流水线（P1）

```
多文件上传 → 落盘 + 建 job
     ↓  每文件一个 task，并行
  ├─ 音频 wav/mp3/m4a/flac → Whisper large-v3-turbo（实测 RTF 45x）
  ├─ PDF   → PyMuPDF，保留页码用于证据回溯
  ├─ DOCX  → python-docx
  └─ TXT/MD→ 直读，markdown 保留标题层级用于切分
     ↓
  语义切分 → session 粒度
     ↓
  KITE remember()  ← 每个 artifact 一个单写者队列
     ↓
  SSE 推进度
```

**并行策略**：写入按笔记本/来源分片成多个 artifact。KITE 的 `remember()` 要求
单文件且不加锁，但 `recall()` 支持多文件同时 load（见 `kite-constraints.md`
约束 1、2），因此不同 artifact 可以并行写，检索时合并。

**幂等**：`session_id` 用 `{doc_id}-{chunk_idx}`。KITE 在 LLM 调用之前就会
拒绝重复 session_id（约束 3），失败重跑既不写重也不浪费调用。

### 异步接口

```
POST /api/ingest                    多文件 → {job_id, items[]}
GET  /api/ingest/{job_id}/events    SSE 实时进度
GET  /api/ingest/{job_id}           轮询快照
POST /api/ingest/{job_id}/cancel
GET  /api/ingest                    历史 job
```

item 状态机：`queued → extracting → transcribing → chunking → remembering →
done | failed | cancelled`。每个 item 独立，单个失败不拖垮整批。

**成本预期**：每个 chunk 一次 LLM 调用，本地模型实测 ~12 s/session。
100 个文档 × 10 chunk ≈ 3–5 小时。分片并行可摊薄，但批量导入本质上是
**小时级后台任务**，job 系统必须能后台跑、能续、能看进度。

## 知识库可视化（P2）

数据来自 KITE 的 `CodebookInspector`，不自己解析 XML。

| 视图 | 数据来源 | 作用 |
|---|---|---|
| 概览 | `summary()` | facts / topics / entities / sessions 计数，入库趋势 |
| 主题地图 | `topics()` 的 `parents` 字段 | KITE 的 governed topic map，树形下钻 |
| 时间线 | session `date` + fact `t` | 体现时序推理 |
| 事实表 | facts + `sources()` | 按 kind / who / conf / topic / entity 过滤 |

```
GET /api/memory/summary
GET /api/memory/topics
GET /api/memory/entities
GET /api/memory/facts              分页 + 过滤
GET /api/memory/facts/{id}/sources 原始证据
GET /api/memory/timeline
```

**证据回溯是重点**。`fact → src → 原始 line / 页码 / 音频时间戳` 这条链要打通 ——
这是 KITE 相对向量检索的核心差异（README 里的 "receipts"），
也是「构建出来的东西看得见」最有价值的部分。

`CodebookInspector` 属于 `research` 模块，上游明说不是稳定 API（约束 8），
需要包一层适配器隔离。

## magic tap（P3）

```
点击 → answer_with_evidence(当前段落上下文)
        ├─ 有证据 → 带引用续写，引用可点开看原文
        └─ 无证据 → 退回模型自由续写
```

**注意**：P0 实测发现 `recall()` 返回空但 `answer()` 能答对的情况
（两条路径召回不一致）。判断「知识库有没有相关内容」不能只看 `recall()` 的
返回长度，否则会误退回自由续写。

**延迟是主要风险**。P0 实测查询 90–110 秒，magic tap 等不了。
缓解手段见 `P0-findings.md` 发现 3。若优化后仍超 10 秒，
改成异步触发的建议流，而非同步等待。

## 自动化编辑（P4）

两条后台线，对应产品构思里的设计：

- **骨架线**：正文防抖 → LLM → 大纲 JSON
- **修订线**：骨架 + 正文 + KITE 检索 → 结构化 diff

修订以 **track-changes** 形式呈现，用户逐条 accept / reject，
不直接覆写用户输入。前端用 TipTap 的 mark + decoration 渲染增删。

## 阶段

| 阶段 | 内容 |
|---|---|
| P0 | 骨架 + 中文可行性验证（gate） |
| P1 | 批量导入流水线 |
| P2 | 知识库可视化 |
| P3 | magic tap |
| P4 | 自动化编辑 |
| P5 | 编辑器前端 + 修订 UI |
| P6 | 打包部署 |

先建知识库并让它看得见，再在其上做写作功能。

## 风险

1. **中文召回** — P0 实测 3/4，且存储语言不一致（见 `P0-findings.md`）。
   需要把「事实存英文、中文原文留作证据」变成显式设计。
2. **查询延迟** — 90–110 秒，直接威胁 P3 的交互形态。
3. **导入成本** — 小时级，需要完整的 job 生命周期管理。
4. **上游稳定性** — `remember()` 标着 Experimental，`research` 模块非稳定 API。
