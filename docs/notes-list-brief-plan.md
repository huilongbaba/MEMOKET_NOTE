# 方案：`GET /api/notes` 不再带全文（欠账之一，只出方案不改代码）

> 第 537 轮（2026-09-14）。这是 PROGRESS「已知欠账」第一条。现在的数字：terrence 23 篇正文合计 89KB，
> shot-perf 413 篇 173KB（JSON 转义后约 580KB，10ms）——**今天还不疼**，几十 MB 的库才疼。所以先把
> 改法和改动面写清楚，等库真大了、或者有空档再动，不在巡检循环里顺手改（改动面见下，不是小手术）。

## 现状：谁在用列表里的全文

`App.tsx` 里 `notes` 状态 39 处引用、`notes.find(` 21 处，其中真正读 `content` 的：

| 用途 | 位置 | 全文是不是必需 |
|---|---|---|
| 打开一篇：`open(n)` 直接拿 `n.content` 进编辑器 | `App.tsx open()` / `switchTo()` | 必需，但可以**打开时再取** |
| 侧栏列表的预览行 / 本地搜索（标题 + 正文子串） | `renderNoteItem` / `setSearchResults` | 预览只要首行；正文搜索服务端 `list_notes_brief(q)` 已经会算命中片段 |
| ⌘K「打开的标签」同名消歧、▾ 标签列表同名消歧 | 第 502 / 503 轮 | 只要首行（`first_body`） |
| 链接面板「链出去」的预览 | `NoteLinksPanel knownNotes` | 只要前 80 字 |
| 分屏只读第二栏、快速查看 | `SplitEditor` / `QuickView` | 必需，但打开时再取 |
| `dropIfStillEmpty`、树右键「打磨」禁用判断 | `!(note.content ?? '').trim()` | 只要 `has_body` |
| 哈 harness 结束后 `setNotes` 就地替换那一篇 | `save()` | 不变 |

结论：**除了「打开」和「分屏 / 快速查看」，其它全部只要首行 / 有没有正文**，而这两个本来就该按需取。

## 改法（三步，每步都能单独发）

1. **服务端**：其实已经有了——`GET /api/notes/brief`（`NoteBriefPage`：id / title / updated_at / pinned /
   icon / preview / has_body / first_body / snippet），⌘K 和 `[[` 补全在用。要补的只有列表页可能用到的
   `created_at` / `chars`（信息面板拿 `current` 算，不一定需要）。`GET /api/notes` 全文版先留着不删。
2. **前端类型**：`Note` 拆成 `NoteHead`（列表用）和 `Note`（= NoteHead + content + spine + beats）。`notes`
   状态改成 `NoteHead[]`；`open(n)` / `openInSplit` / `QuickView` 先 `api.getNote(id)` 再进编辑器
   （一次 GET，几 ms；探针里多一个 await）。`previewLine(n.content)` 的四处换成 `n.first_body`；
   本地正文搜索改走 `listNotesBrief(q)`（侧栏搜索已经有 debounce）。
3. **收尾**：`save()` 后的就地替换改成替换 head；`reload()` 改拉 brief。`GET /api/notes` 默认也改成
   brief（或直接删掉全文版），README 接口表更新。

## 风险与验证

- 打开一篇多一次往返：dev 实测 `GET /api/notes/{id}` 3–5ms，感知不到；离线（后端崩）时打开会失败——
  现在的行为是能打开旧内容但存不上，改后要给「后端不可达，打不开」的提示（状态栏已有红字）。
- 探针 `open:` / `harness:` / `split:` 都依赖 `notes.find(...)` 立刻有正文：改成 await，`shot.sh` 的 DELAY 不用动。
- 验证：`shot-perf` 首屏 `GET /api/notes` 从 580KB 降到 ~60KB；vitest 里 `displayTitle` / `previewLine`
  的用例改吃 `first_body`；真跑一次 `harness:5f65df10cad6` 看 `setNotes` 就地替换没坏。

## 不做的

- 不做无限滚动 / 虚拟列表：413 行的树 paint 61ms，列表不是瓶颈。
- 不做客户端缓存全文：打开过的那篇本来就在 `current` 里。
