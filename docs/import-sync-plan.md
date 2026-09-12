# 导入 / 同步 / 导回：方案

> 回答四个问题：飞书怎么接、能不能导回去、增量同步怎么做、大批量导入的断点续传 /
> 进度 / 用量 / 预估。前提是 `import-from-other-note-apps.md`（Obsidian / Notion /
> Apple Notes / Evernote 已经接了）和 `agent-native-editor.md` §3.4（导入的东西是
> **材料**，不是搬家）。先说现状，再说每一问怎么做，最后是顺序。

## 0. 现状（读代码得来，不是想象）

| 能力 | 现在 | 落点 |
|---|---|---|
| 导入源 | .md 文件 / Obsidian vault / Evernote .enex / Notion（token）/ Apple Notes（本机） | `routers/import_sources.py`、`database/ingest/importers.py` |
| 落点 | 「笔记」「知识库」「两者」三选一（`to=`） | `_land()` |
| 增量 | **已经有一半**：知识库侧 session_id = `<源>-<源侧稳定 id>-<块号>`，KITE 拒绝重复 id 且不花 LLM，重跑导入 = 跳过已导过的块 | `_land()`、`_ingest_job()` |
| 增量的缺口 | 笔记侧**没有**增量：重跑会再建一篇同名笔记；源侧改过的内容不会更新（旧 session 还在，新内容因为 id 相同被跳过——**改过的东西永远进不来**） | — |
| 进度 | job + item 两级状态（queued / extracting / chunking / remembering / done / failed / cancelled），SSE 推帧，可取消 | `ingest_jobs` / `ingest_items`、`/jobs/{id}/events` |
| 断点 | 每个 item 独立、失败不拖垮整批；**但进程重启后 job 就丢了**（后台任务在内存里，DB 里的 item 永远停在 queued/remembering） | — |
| 用量 / 预估 | 无。每块一次 LLM 调用约 13s，用户只看到「处理中」 | — |
| 导出 | 整库 Markdown zip（层级 / 前言 / 克隆 / 资产） | `routers/export.py` |
| 导回 | 无 | — |

## 1. 飞书

### 1.1 能拿到什么

飞书开放平台的文档 API 有两条路：

- **云文档（docx）**：`GET /open-apis/docx/v1/documents/{document_id}/raw_content` 给纯文本；
  `GET .../documents/{document_id}/blocks` 给块结构（标题、列表、表格、图片、代码块）。
  用块结构能还原成 Markdown，纯文本只能当材料。
- **知识库（wiki）**：`GET /open-apis/wiki/v2/spaces` 列空间，`GET .../spaces/{id}/nodes`
  列节点（带 `obj_type=docx` 和 `obj_token`），再走上面的 docx 接口取内容。
- **旧版 doc**（2022 前的）：`GET /open-apis/doc/v2/{docToken}/content`，返回 JSON 树。

权限：自建应用 + `docx:document:readonly`、`wiki:wiki:readonly`、`drive:drive:readonly`；
用户侧要 `user_access_token`（OAuth）才能读个人文档，`tenant_access_token` 只能读应用被
授权的文档。个人用户最省事的路：**应用 + 把文档 / 知识库「添加协作者」给应用**——跟
Notion 的「connect integration」是同一个模型，设置页放 app_id / app_secret 两个框。

### 1.2 怎么接

```
importers.py      +  FeishuNote → ImportedNote（blocks → markdown：标题 / 列表 / 表格 /
                     代码块 / 图片占位；日期取 document 的 create_time / update_time）
import_sources.py +  POST /api/import/feishu  {app_id, app_secret, scope: wiki|drive|doc_ids}
                     → 列节点 → 逐篇取块 → _queue()（走已有的 item 流水线）
                     source = "feishu", source_id = document_id（稳定 → 增量）
settings          +  飞书 app_id / app_secret（存 provider_config，跟 asr_base_url 同一张表）
```

一次导入 = 一个 job，每篇一个 item，进度 / 取消 / 断点都复用下面 §4 的机制。测试：
块 → Markdown 的转换用真实块 JSON 样本做纯函数测试（不打网络）；HTTP 层用假客户端。

## 2. 导回（Obsidian / Notion / 飞书）

先定原则：**导回是「视图」，不是双向同步的另一半**（`agent-native-editor.md` §3.7）。
一篇笔记的真相在这里；导回是把它按目标平台的规则渲染出去，带上一个「来自 MEMOKET
NOTE · 笔记 id · 时间」的尾注，下次再导回时按 id 覆盖而不是新建。

| 目标 | 怎么写 | 增量 |
|---|---|---|
| **Obsidian** | 直接写 vault 目录（用户选一次路径）：`<树路径>/<标题>.md`，frontmatter 带 `memoket_id`、`updated`；资产复制进 `attachments/` | 按 `memoket_id` 找到旧文件覆盖；对方改过（mtime 比我们记的新）就先提示 |
| **Notion** | API `POST /v1/pages`（父页面由用户选）+ 把 Markdown 转成块（标题 / 段落 / 列表 / 表格 / 代码 / 图片外链）；Notion 2026-02 起有 Markdown 直写接口，优先用它 | 记 `notion_page_id`，再导回走 `PATCH`（清空块再写） |
| **飞书** | `POST /open-apis/docx/v1/documents` 建文档 + `POST .../blocks/{id}/children` 写块；或者用 `convert` 接口把 Markdown 直接转块（2025 起有） | 记 `feishu_document_id`，再导回先删旧块再写 |

落点：`note_links` 之外加一张 `note_remotes(note_id, platform, remote_id, remote_updated,
exported_at)`；导出面板列出「这篇在哪些平台有副本、上次导回是什么时候」。

**明确不做**：对方改了自动拉回来（那是双向同步，冲突处理是个无底洞）。做成：导回前
检查对方有没有改，改了就提示「对方改过，覆盖 / 先导入对方的版本」。

## 3. 增量同步

三层，各自的「稳定 id」和「改没改」判据：

| 层 | 稳定 id | 改没改 | 现在 | 要做 |
|---|---|---|---|---|
| 知识库（事实） | session_id = `<源>-<源侧 id>-<块号>` | KITE 按 id 拒重复 | 有 | 内容变了要**先删旧 session 再重抽**：`remove_sessions(prefix)` + 重跑（笔记的「同步」也走这个） |
| 笔记（正文） | `notes.source`、`notes.source_id`（新列） | 源侧 `updated`（Obsidian mtime / Notion last_edited_time / 飞书 update_time）比 `imported_at` 新 | 无（重导就建重复篇） | 按 source_id 找到旧笔记：源侧新 → 更新正文；本地也改过 → 不动、标「两边都改过」 |
| 材料 ↔ 正文 | 见 `agent-native-editor.md` §3.4 | — | — | 材料层做完后，导入默认进材料层，正文层由用户决定 |

判据：**同一份材料导十次，知识库里还是一份、笔记里还是一篇、LLM 只花一次**。
测试用「同一 vault 导两遍、改一篇再导第三遍」三步走。

内容变了怎么判：块级哈希。每篇 `<源>-<源侧 id>` 记一个 `content_sha`，源侧内容的
sha 不变就整篇跳过（一次文件读取，零 LLM），变了才删旧 session 重抽。这比「按块比对」
简单，也够用——一篇笔记改一个字重抽一次，成本是可接受的。

## 4. 大批量导入：断点、进度、用量、预估

### 4.1 断点续传

现在 item 是持久的，后台任务不是。要做的是「**任务可恢复**」：

1. job 增加 `payload_path`：导入前把清洗好的笔记列表落成一个 JSON 文件（在 data 目录），
   进程重启后还在。
2. 启动时扫 `ingest_jobs`：状态是 running / queued 且有 payload 的 → 标成 `interrupted`，
   界面上给「继续」按钮（不自动跑：用户可能就是不想要它了）。
3. `POST /jobs/{id}/resume`：只跑 `status not in (done, cancelled)` 的 item；已经 done 的
   item 的 session 本来就在，KITE 会拒重复——所以**块级**也是天然断点：一篇导到第 3 块
   崩了，恢复时前 2 块被跳过、不花钱。
4. 一篇内部的进度写进 item.detail（`3/7 块`），恢复时从 detail 读起点只是优化，不做也对。

### 4.2 进度

现在只有状态字。补三个数，都从已有的表算出来，不加新表：

- **篇数**：`done / total`，失败 / 跳过分开数（`_land` 已经在 detail 里写「跳过 N 块」）。
- **块数**：每篇分块后把 `chunks_total` 写进 item，每块完成 `chunks_done + 1`（item 加两列）。
  进度条按块走，不按篇走——一篇 40 块的会议记录和一篇 2 块的随手记权重不一样。
- **当前在做什么**：item 的 status 已经区分 extracting / transcribing / chunking /
  remembering；界面把当前 item 的文件名 + 状态显示出来（现在只有整体状态）。

### 4.3 用量（token）

`llm.py` 的 `stats` 字典已经能拿 `finish_reason`；同一个地方把响应里的 `usage`
（prompt_tokens / completion_tokens）也记下来。KITE 的抽取调用走的是它自己的
`providers.llm`，拿不到 usage——两条路：

- 简单：按字数估。中文约 1.5 字 / token，抽取 prompt 固定开销约 1200 token，每块
  ≈ `1200 + len(chunk)/1.5 + 输出 ≈ 400`。误差 20% 以内，够用来预估费用。
- 准确：给 `memoket_kite.providers.llm` 打一个记录 usage 的钩子（它是我们自己的包，
  可以加）。

界面：job 卡上「已用 ≈ 38k token · 约 ¥0.12」（单价按供应商配置表，本地模型显示 0）。

### 4.4 预估时间

每块的耗时是稳定的（同一模型 ±30%）：跑完前 3 块之后，`剩余块数 × 最近 10 块的
中位耗时`；块数在分块阶段就知道了（4.2）。显示「约 12 分钟 · 已用 3 分钟」，每帧
更新。任务开始前也能估：篇数 × 平均块数 × 13s（平均块数按历史 job 统计，没有历史就按
每 800 字一块）。**开始前就要告诉用户这一批要跑多久、大概多少钱**——412 篇笔记的
用户点下去之前应该知道这是一个小时的事。

### 4.5 并发

现在一次一篇串行（KITE 写锁是全库独占）。抽取（LLM 调用）和写入（XML 重写）是两
步，只有写入需要锁：把「抽取」放线程池跑 3 并发、「写入」串行，吞吐能到 2-3 倍。
这一条要动 `UserMemory.remember`（把 `extract_facts` 和 `append_session` 拆开），
放在最后做。

## 5. 顺序

1. **笔记 ↔ 知识库链接层**（正在做）：`remove_sessions` + 重抽，是 §3 知识库侧增量的
   基础；同时修一个真 bug——笔记摄入的事实 id（`note-<id>-0F1`）不匹配引用正则，
   摄入进去的事实**没法被引用**。
2. §4.2 进度（块数 + 当前文件）和 §4.4 预估：只加两列一个计算，收益最直接。✅ 2026-09-12
3. §4.1 断点续传（payload 落盘 + interrupted + resume）。✅ 2026-09-12（导入任务；批量上传的字节不落盘，只标失败）
4. §3 笔记侧增量（`notes.source / source_id / content_sha`）。✅ 2026-09-12：`find_note_by_source` 按 (source, source_id) 找旧篇；sha 没变整篇跳过；变了更新正文，本地 `updated_at > imported_at` 就不动只说明；知识库侧变了先 `remove_sessions` 再重抽。
5. §1 飞书导入。
6. §2 导回（Obsidian 目录写入最先，Notion / 飞书 API 其次）。
7. §4.3 用量记账（先估算，后钩子）；§4.5 并发。
