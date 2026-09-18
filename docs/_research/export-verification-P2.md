# P2 · 导出到 Obsidian / Notion / 飞书 三件套端到端验证

日期 2026-09-18 · 验证 agent · worktree HEAD `305407f` · **只验证、只报告，没改产品代码**

## 0. 怎么验的（安全边界）

- **真库一个字节没碰。** 后端启动本身就会写库（`backend/app/main.py:59-93`：sweep / reindex_citations / VACUUM / 备份），
  导出本身也会写库（`store.record_remote` → `note_remotes` 表，`backend/app/database/store.py:843`；这张表**不在**
  `db_guard.WATCHED` 里，`Watch()` 根本抓不到它）。所以真库只用 `db_guard.readonly()` 读了两次做指纹，
  实验全部跑在 **scratchpad 里的一份拷贝**上（`KITE_DATA_DIR=…/scratchpad/p2/data`，`notes.sqlite3` + `assets/` 各 cp 一份）。
- 真库指纹 **实验前 = 实验后**：`notes` 482 行 / `max(updated_at)=2026-09-16T02:53:27+00:00` / 正文 321,250 字 /
  逐篇摘要再摘要 `47dcc54be60aa4f2`（= `sha256(json.dumps(digests, sort_keys=True))[:16]`，跟台账口径对上了）。
  真库 `note_remotes` 也没变：仍是 19 行 obsidian、`max(exported_at)=2026-09-12T13:16:09`，0 行 notion / feishu。
- 飞书凭据用 `importlib` 加载 `/Users/huilong/Skills-Bugfixing-Feishu/config.py`，脚本只取字段、**从未打印值**。
- 没碰 `~/Library/Application Support/memoket-note-desktop/`。
- 后端两个实例（8765 正常网络、8766 `HTTPS_PROXY=http://127.0.0.1:9` 模拟断网）用完已 kill；worktree `git status` 干净。
- 脚本都在 `/private/tmp/claude-501/…/scratchpad/p2/`（`obsidian_test.py` `notion_test.py` `feishu_test.py` `netdown_test.py`
  `blocks_fidelity.py` `probe_md.py`），可重放。

**先说结论一句话**：三条路的「管道」都通——Obsidian 落文件、飞书真建出了文档、第二次都是覆盖不是新建；
**但导出去的内容三家都只到「纯文本级」**：表格塌成一段、图片变成一行 `![…](_assets/…)` 字面量、粗体带星号、
`[terrence-xxx]` 引用裸露、mermaid 变普通代码；而 Notion 这条路**在这台机器上没有任何凭据，从没真发过**。

---

## 1. Obsidian

### 1.1 凭据从哪来
不需要凭据，只要一个本机目录。路径存在浏览器 `localStorage['memoket-note:vault-dir']`
（`frontend/src/util/useExportBack.ts:55-61`），桌面版用 `window.memoketDesktop.pickDirectory` 选目录
（`desktop/src/preload.ts:18`），网页版只能手贴。不走 `provider_config`、不走环境变量、不走 `config.py`。

### 1.2 今天能不能真的导出去 —— **能**
拿 terrence 的真实笔记 `309f19202309`「公司汇报：」（30,588 字，含 3 张图、1 个 mermaid、17 行表格、代码、引用）：

| 步骤 | 结果 |
|---|---|
| 第 1 次 `POST /api/export/obsidian {vault_dir, note_ids:[309f…]}` | `200 {written:1, skipped:0, conflicts:[]}` |
| 落到哪 | `<vault>/Notes/公司汇报：.md`（按树的层级：它是「Notes」这篇的子笔记）+ `<vault>/_assets/` 三张 png（1.5M/2.1M/1.8M） |
| front-matter | `id / memoket_id: 309f19202309 / title: 公司汇报： / created / updated`，**有 memoket_id** |
| 正文 | 原样 markdown；`/api/assets/xxx.png` 已改成 `_assets/xxx.png`；mermaid 围栏、表格都在 |
| `note_remotes` | `remote_id=4d7f976871d4ce18`（= 写出内容的 sha1 前 16 位）、`remote_path=Notes/公司汇报：.md` |

顺带：真库里 19 行 `note_remotes` 说明 **整库 Obsidian 导出在 09-12 真跑过一次**，这条路不是「从没验证过」；
Notion / 飞书才是真的从没在真库上发过。

### 1.3 第二次导同一篇 —— **覆盖，不是新建**（四种情形都对）
| 情形 | 结果 |
|---|---|
| 第 2 次，什么都没改 | `{written:0, skipped:1}`，文件 mtime 没变，目录里仍是 1 个 .md |
| 手动在 vault 里那个文件末尾加一行（模拟在 Obsidian 里改过） | `{conflicts:['Notes/公司汇报：.md']}`，文件保留我的改动，没覆盖 |
| 再来一次 `force:true` | `{written:1}`，我的改动被覆盖，仍是 1 个文件 |
| 整库 28 篇导两次 | 第 1 次 `written:28`，第 2 次 `skipped:28`，路径稳定（重名的 `公司汇报： (2).md` 两次一致） |

### 1.4 失败时用户看见什么
前端：`useExportBack.ts:36-37` 把后端 `detail` 原样 `toast(…, 'error')`，红 toast **6 秒自动消失**（`toast.ts:26`），不能复制。

| 场景 | 后端 | 用户看到的 toast |
|---|---|---|
| 目录不存在 | 400 | `400 目录不存在：/…/nope` ✅ 能懂 |
| 目录写不进（`/System`） | 400 | `400 这个目录写不进去：/System` ✅ |
| 填的是文件不是目录 | 400 | `400 目录不存在：…/公司汇报：.md` ⚠️ 说法不准 |
| `~/xxx` | 400 | 已 expanduser，`目录不存在：/Users/huilong/xxx` ✅ |
| **`vault_dir` 为空字符串** | **200 written:1** | 前端按钮禁用了（`ExportNotePanel.tsx:62`）所以 UI 触发不到，**但后端把文件写进了后端进程的 cwd**（实测写出 `backend/Notes/公司汇报：.md` + `backend/_assets/`，已清理）。`export.py:78` `Path("").expanduser()` = `.`，`is_dir()` 为真。打包后 cwd 是 .app 包内或 `/`，要么写进包里要么 400 |
| note_id 不存在 | 200 `written:0` | 绿 toast「**没有需要写的：上次导回之后没改过**」（`useExportBack.ts:33`）⚠️ 撒谎 |
| 正文为空（6 篇） | 200 | 文件只有 front-matter，合理 |
| 标题为空（2 篇） | 200 | 文件名取正文首行（`好几回.md`）/ `未命名.md`；front-matter 里 `title: `（空值）合理 |
| 正文 51,397 字 | 200 | 154KB 文件，正常 |
| 断网 | 200 | 不受影响 ✅ |

### 1.5 内容保真表（Obsidian）
| 构件 | 到对面变成 | 判定 |
|---|---|---|
| `[[wikilink]]` | 库里**没有一处**用 wikilink（`[[` 补全插的是 `[标题](note://<id>)`，`noteLinkCompletion.ts:7-11`）。真有的话原样保留，Obsidian 能认 | 对（但 n/a） |
| `[标题](note://5f65df10cad6)` 笔记间链接（库里 1 处） | 原样保留；Obsidian **点不开**（`note://` 不是它认的协议，也没有改成相对 .md 路径） | **丢了（链接死）** |
| `![alt](/api/assets/x.png)` | 改成 `![alt](_assets/x.png)`，png 复制到 `<vault>/_assets/` | 对（**一处存疑**：这篇在 `Notes/` 子目录，严格相对路径应是 `../_assets/`。Obsidian 通常会按 vault 根再找一遍，但本机没装 Obsidian，**没实开确认**） |
| `[terrence-1346-1F3]` 引用（3 篇有） | 原样字面量 | 对（Obsidian 里就是一段文字，无处可点） |
| mermaid 围栏 | 原样 | 对（Obsidian 原生渲染） |
| 表格 | 原样 | 对 |
| 粗体 / 行内代码 / 引用 / 列表 / h4-h6 | 原样 | 对 |
| front-matter `title:` | **不加引号**（`exporters.py:72`）。标题含 `: `、` #`、开头是 `[ { " ' * & ! ` 等时 YAML 非法，Obsidian 属性面板报 Invalid YAML。terrence 现有 27 篇标题恰好都没踩到；用 `会议: 周会 #1` 试了一下就是裸的 `title: 会议: 周会 #1` | **潜在乱** |

---

## 2. Notion

### 2.1 凭据从哪来 —— **这台机器上哪里都没有**
- 产品：只从弹层输入框来（`ExportNotePanel.tsx:30-31`），**有意不存**（`:59` 提示「凭证不会存下来，每次要填」）。
- `provider_config` 表列：`id, provider, gpt_api_key, gpt_model, gpt_base_url, updated_at, asr_base_url, auto_sync_notes`——没有 notion 字段。
- 环境变量：`env | grep -i notion` 空。
- `Skills-Bugfixing-Feishu/config.py`：字段名列表里没有任何 `NOTION*`。
- 真库 `note_remotes`：0 行 notion → **从没对真库发过**。现有测试 `test_export_back.py:94` 是 mock HTTP 的。

**缺哪两项、去哪拿**（不是我编的，是 API 要求 + 前端字段）：
1. **Integration token**（`ntn_…`）：notion.so → Settings → Connections → Develop or manage integrations
   （https://www.notion.so/profile/integrations）→ New integration（Internal）→ 复制「Internal Integration Secret」。
2. **父页面 id**：目标页面 URL 末尾 32 位 hex（前端会把 `-` 去掉，`useExportBack.ts:48`）；**而且这个页面必须先
   ⋯ → Connections → 加上这个 integration**，否则 Notion 返 404 `Could not find page`。

顺便核了一件事：代码里写死的 `Notion-Version: 2026-03-11`（`exporters.py:265`）**是 Notion 当前最新版本**
（developers.notion.com/reference/versioning 页面确认），不是笔误。

### 2.2 真发结果 —— **没法发**（无凭据）。能验的只有失败路径，下面全是真打 api.notion.com 的结果。

### 2.3 二次导出行为 —— 只能读代码
`export.py:158-166`：有 `note_remotes.remote_id` 就 `replace_children`（改标题 → 逐块 GET/DELETE 旧块 → PATCH 新块）
→ `updated`，同一个 page id；没有就 `create_page` → `created`。逻辑跟飞书那条一致，飞书实测是对的（§3.3），
这条**没有真机证据**。注意 `replace_children` 是「删光再加」，页面里用户手加的块会被清掉，且不像 Obsidian 那样有冲突检测
（`last_edited()` 写了但没人调，`exporters.py:299`）。

### 2.4 失败时用户看见什么
| 场景 | 用户看到的 toast（6 秒红） | 能否知道下一步 |
|---|---|---|
| token 空 | 前端按钮禁用；直打后端 `400 Notion 的 Integration token 没填` | ✅ |
| 父页面 id 空（这篇没导过） | `400 父页面 id 没填——每篇会建成它下面的子页面` | ✅ |
| **token 错** | `400 一篇都没导出去：公司汇报：: Client error '401 Unauthorized' for url 'https://api.notion.com/v1/pages'`↵`For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401` | ❌ Notion 自己的 `"API token is invalid."` 被 `raise_for_status()`（`exporters.py:273`）吞了，用户拿到 httpx 的英文 + MDN 链接 |
| 父页面没 Connect / id 错 | （无 token 没法实测；按代码同上会是 `404 Not Found for url …`，Notion 的 `Could not find page…` 同样被吞） | ❌ |
| **断网** | `400 一篇都没导出去：hi: [Errno 61] Connection refused` | ❌ 没说「网络」两个字 |
| **整库 28 篇 + token 错** | 转圈 **23.7 秒**（28 次注定失败的顺序请求，`export.py:157-168` 没有 fail-fast），然后只报第一篇的错 | ❌ `_need` 的 docstring（`export.py:125-135`）自己都说「别每一篇都发一次注定失败的请求」，但只拦了「没填」，没拦「填错」 |
| note_id 不存在 | 200 `created:0` → 绿 toast「没有需要写的：上次导回之后没改过」 | ❌ 撒谎 |
| 正文空 | `children:[]` 建空页，合理 | — |
| 正文 50k | 每块 ≤2000 字切 rich_text（`exporters.py:211`），块 >100 分批 PATCH（`:281`），代码上 OK | 未实测 |
| 黑洞式断网（不是拒绝而是丢包） | `timeout=60`（`:272`）× 每篇 ≥1 次请求：整库 = 半小时转圈 | ❌ |

### 2.5 内容保真表（Notion，纯函数 `md_to_notion_blocks` 实跑两篇真实笔记 + 一份探针 markdown）
| 构件 | 变成 | 判定 |
|---|---|---|
| `[[wikilink]]` | 段落里的字面量 `[[wiki链接]]` | 乱（n/a，库里没有） |
| `[标题](note://id)` | 字面量，不是链接 | 丢 |
| `![alt](/api/assets/x.png)` | **一段文字** `![alt](_assets/x.png)`，没有 image 块、没上传 | **丢** |
| `[terrence-1346-1F3]` | 字面量夹在段落里 | 乱 |
| mermaid 围栏 | `code` 块 `language: "plain text"`（`exporters.py:228` 查不到 `mermaid`）——**Notion 原生支持 `language: "mermaid"` 并渲染成图**，白白丢了 | 乱（一行改） |
| 表格 | **整张表塌成一个 paragraph**，行与行用空格拼：`\| Method \| Token \| … \| \|---\|---\| \| MemU \| 0.5k …` | **乱** |
| 粗体 / 斜体 / 行内代码 / 删除线 | 字面量 `**粗体**`（`harness 测试` 那篇 25 个块带星号） | 乱 |
| h4 / h5 / h6 | 全压成 heading_3（`:193` `min(…,3)`） | 乱 |
| 嵌套列表 | 全部拍平成一级（`:194` 吃掉前导空格） | 乱 |
| 任务列表 `- [ ]` | bullet，文字 `[ ] 未完成任务` | 乱 |
| `---` 分隔线 | paragraph `---`；`* * *` → bullet `* *` | 乱 |
| 多行 `>` 引用 | 每行一个 quote 块 | 乱 |
| 段内硬换行 | 用**英文空格**拼成一段（`:177`）——中文正文里凭空多出空格 | 乱 |
| 四空格缩进代码块 / `$$` 公式 / 原始 HTML / 脚注 | 全是段落文字 | 乱 |
| 代码块语言 `python` | `language: python` | 对 |
| 一级标题 / 列表 / 引用 / 普通段落 | 对应块 | 对 |
| front-matter | 已剥掉（`:166-169`） | 对 |

---

## 3. 飞书

### 3.1 凭据从哪来
- 产品：三个输入框（`ExportNotePanel.tsx:32-34`），不存。`provider_config` / 环境变量里都没有。
- `Skills-Bugfixing-Feishu/config.py`（importlib 加载，只看字段）：`FEISHU_APP_ID` **有**、`FEISHU_APP_SECRET` **有**、
  `FEISHU_BUGFIX_FOLDER_TOKEN` **有**。产品**不读这个文件**，用户得自己把三样贴进弹层，每次贴。
- 真库 `note_remotes`：0 行 feishu → 真库上从没发过；`test_export_back.py:131` 是 mock。

### 3.2 真发结果 —— **通了**
先用同一个应用在 bugfix 文件夹下建了测试文件夹，全部产物都在里面，用完可整个删：

- **测试文件夹**：`memoket 导出测试 2026-09-18 2159`，token `Q6AkfiHtylL2LrdMJc5cKi4anyf`，
  https://acn0p1esxk6c.feishu.cn/drive/folder/Q6AkfiHtylL2LrdMJc5cKi4anyf

| 笔记 | 结果 | 对面 |
|---|---|---|
| `309f19202309` 公司汇报： | `200 {created:1}`，5.2 s | docx `UnP3d4DJeoDsbNxDGhdcobSyn5b` https://acn0p1esxk6c.feishu.cn/docx/UnP3d4DJeoDsbNxDGhdcobSyn5b · API 回读 252 块（page 1 / text 203 / bullet 17 / h3 15 / h2 11 / ordered 2 / h1 1 / code 1 / quote 1），标题「公司汇报：」，revision 7 |
| `5f65df10cad6` harness 测试（可删） | `created:1` | docx `WCvCdbGRBoctSnxSkoucIKCgnmh` · 103 块 |
| `26fab56dd421`（正文空） | `created:1` | docx `OC8Md9WYpodlroxTxOtcXz8Hngd`，标题「Notes」，只有 page 块 |
| `34b988c208db`（标题空、正文空） | `created:1` | docx `D5R8dbXW9owOk6xF47McQvnLndd`，标题「未命名」 |
| 沙盒里造的 51k 字笔记 | `created:1`，2.5 s | docx `DJAKdy1lqoXtpqx9xkFcxKbuneh`，47 块，最长 text_run 1140 字 |

`note_remotes` 落了 `platform=feishu, remote_id=<document_id>, remote_path=''`。

### 3.3 第二次导同一篇 —— **覆盖，不新建**
- 第 2 次：`{created:0, updated:1}`，4.2 s，`remote_id` 不变，回读仍 252 块（没有翻倍、没有残留）。
- 第 2 次 `folder_token` 留空：`updated:1` ✅（`_needs_create` 只在要新建时才要文件夹，`export.py:179-180`）。
  **但前端弹层不让你这么做**：`ExportNotePanel.tsx:64` 三项都填了按钮才亮，更新也得填文件夹 token。
- 机制是 `batch_delete` 0..n 再分批插（`exporters.py:333-341`），`page_size=500`：**超过 500 块的文档只删前 500 块**，
  剩下的留在后面 → 第二次导出会出现「新内容 + 旧尾巴」（公司汇报 252 块没触发；一篇 60k 字的会）。
- 跟 Obsidian 不同，**没有「对方改过就跳过」**：用户在飞书里改过的内容会被无声覆盖（`edited_time()` 写了没人调，`:343`）。

### 3.4 失败时用户看见什么
| 场景 | toast | 能否知道下一步 |
|---|---|---|
| App Secret 空 | 前端禁用；后端 `400 飞书的 App Secret 没填` | ✅ |
| 文件夹 token 空 + 没导过 | `400 文件夹 token 没填——新文档会建在它下面` | ⚠️ 但导入页那块的输入框提示写着「**留空 = 应用根目录**」（`ExportBack.tsx:84`），前后端打架 |
| **Secret 错** | `400 一篇都没导出去：hi: 飞书返回 10014：app secret invalid` | ⚠️ 勉强 |
| **App ID 错** | `400 一篇都没导出去：hi: 飞书返回 10003：invalid param` | ❌ 看不出是 App ID |
| **文件夹 token 错** | `400 一篇都没导出去：hi: Client error '400 Bad Request' for url 'https://open.feishu.cn/open-apis/docx/v1/documents'`↵`For more information check: https://developer.mozilla.org/…/400` | ❌ 飞书明明在响应体里给了 `code/msg`，但 `exporters.py:314` 先 `raise_for_status()` 再 `:316` 读 code，4xx 时飞书的话全丢 |
| 应用没 docx/drive 权限 / 文件夹没加应用为协作者 | 同上一格的形状（也是 4xx），用户看到的还是 MDN 链接 | ❌ |
| **断网** | `400 一篇都没导出去：hi: [Errno 61] Connection refused`（新建、更新、整库三种都一样，0.1 s） | ❌ 没说「网络」 |
| 黑洞式断网 | `timeout=60`（`:313`）× 每篇 ≥3 次请求（取 token / 建文档 / 插块） | ❌ 整库半小时起 |
| note_id 不存在 | 200 `created:0` → 绿 toast「没有需要写的：上次导回之后没改过」 | ❌ 撒谎 |
| 成功了 | 绿 toast「导回 1 篇」，**没有链接**；信息面板只显示「飞书 · 09-18 导回」（`NoteInfoPanels.tsx:39`），`remote_id` 就是 document_id 却不拼成 URL | ❌ 用户不知道去哪找 |

### 3.5 内容保真表（飞书，API 回读实测）
| 构件 | 到对面变成 | 判定 |
|---|---|---|
| `[[wikilink]]` | 字面量 | 乱（n/a） |
| `[标题](note://id)` | 字面量 | 丢 |
| `![alt](/api/assets/x.png)` | **一个 text 块，内容就是** `![为一篇中文公司汇报…](_assets/1b92815398ecb037dc2561f3.png)`；没有 image 块、没传图 | **丢** |
| `[terrence-1590-2F3]` | 段落里的字面量（回读可见） | 乱 |
| mermaid 围栏 | code 块，`style.language=1`（PlainText）；飞书 docx 没有 mermaid 语言，能做的最多是标成纯文本 | 丢（能看源码） |
| 表格 | **一个 text 块**：`\| Method \| Token \| … \|---\|---\| \| MemU \| 0.5k \| 67.14 …`，17 行拼成一行；两张表都这样 | **乱** |
| 粗体 | 字面量 `**…**`（harness 那篇 25 个块） | 乱 |
| 代码块 `python` | `style.language=43`（Python）✅ | 对 |
| h4-h6 / 嵌套列表 / 任务列表 / `---` / 多行引用 / 硬换行加空格 | 同 Notion §2.5 | 乱 |
| 标题 / 正文首行 | 文档标题「公司汇报：」，第一块又是 H1「公司汇报：」，标题出现两遍 | 小瑕疵 |
| front-matter | 已剥掉 | 对 |

---

## 4. 按「用户第一次用会栽在哪」排序的问题清单

1. **导出去的内容不是笔记，是笔记的纯文本投影**（Notion / 飞书）。表格塌成一段、图片是一行 `![…]` 字面量、粗体带星号、
   `[terrence-xxx]` 裸露、mermaid 变代码。用户第一次打开对面文档就会看出来。
   - `backend/app/database/exporters.py:158-208`（`_md_lines` 只认 heading/bullet/ordered/code/quote/para）、`:215-256`。
   - 修法（按收益排）：a) 表格：连续 `|` 行 → Notion `table` 块（`table_row` 数组）/ 飞书 `block_type 31` 表格（先建表再填 cell）；
     b) 图片：Notion 需要外链 URL（本地 png 没法直传，只能先上传到可访问的地方或退化为「[图：alt]」说明），飞书走
     `POST /drive/v1/medias/upload_all`（parent_type=docx_image）再建 `block_type 27` 图片块；
     c) 行内：把 `**` / `` ` `` / `[x](url)` 解析成 rich_text 的 `annotations.bold/code` + `link`（Notion）/ `text_element_style`（飞书）；
     d) mermaid：Notion 一行改 `_NOTION_LANG["mermaid"]="mermaid"`（`:148-153`），原生渲染；
     e) `[terrence-xxx]`：要么剥掉、要么变成脚注/引用样式，别裸露。
2. **失败提示是 httpx 的英文 + MDN 链接，对面平台自己的错误信息被吞了**（Notion token 错、飞书文件夹错 / 没权限都这样）。
   - `exporters.py:272-274`（Notion）、`:313-317`（飞书）：`raise_for_status()` 在读 `code/msg` 之前。
   - 修法：先 `r.json()`，飞书用 `code/msg`、Notion 用 `message`，拼成中文「飞书拒绝：<msg>（code）」；
     再在 `export.py:167/:196` 把 401/403/404 映射成「token 无效」「页面没 Connect 给这个 integration / 文件夹没把应用加为协作者」。
3. **凭据填错时整库导出会转圈 24 秒（真实网络）到半小时（黑洞网络）再报错**——每篇都发一次注定失败的请求。
   - `export.py:157-168`、`:185-197`：循环里 `except` 后 `continue`；`exporters.py:272/:313` `timeout=60`。
   - 修法：循环前先探一次（Notion `GET /users/me`、飞书 `token()`），失败直接 400；循环内连续 N 次同类 4xx 就 break。
4. **成功后用户不知道东西在哪**：toast「导回 1 篇」没有链接；信息面板「副本」行也只有日期。
   - `frontend/src/util/useExportBack.ts:33`、`frontend/src/components/NoteInfoPanels.tsx:39`、`ExportNotePanel.tsx:85`。
   - 修法：后端返回 `url`（飞书：建文档后 `GET /drive/v1/files` 或直接拼 `https://<tenant>.feishu.cn/docx/<id>`——
     tenant 域名可从 `GET /drive/v1/files` 的 `url` 字段拿；Notion：`create_page` 响应里就有 `url`），
     `note_remotes.remote_path` 存 URL，toast 用 `toastAction('导回 1 篇', '打开', …)`，副本行做成链接。
5. **飞书凭据明明在 `config.py` 里、产品却每次要用户手抄三段**；Notion 更是哪都没有。这是「凭证不落库」的有意设计
   （`ExportBack.tsx:46-48`），但对单用户桌面版是自找麻烦，第一次用的人会卡在「去哪拿 App Secret」。
   - `ExportNotePanel.tsx:30-34`、`ExportBack.tsx:19-23`。
   - 修法：至少存进桌面壳的 keychain / `identity.json` 旁边（Obsidian 路径已经存 localStorage 了，同一条理由）；
     弹层里给一行「怎么拿」的链接（Notion：notion.so/profile/integrations；飞书：open.feishu.cn 应用后台 → 凭证与基础信息）。
6. **「没有需要写的：上次导回之后没改过」在 note_id 对不上时也会出现**（绿 toast 撒谎）。
   - `export.py:83/:120` `only` 里的 id 找不到时静默；`useExportBack.ts:33` 把 `n=0` 一律解释成「没改过」。
   - 修法：后端对 `note_ids` 里不存在的 id 返 404 或在响应里带 `missing:[…]`；前端 `n=0 && skipped=0` 时提示「没有匹配的笔记」。
7. **前后端对「飞书文件夹 token 留空」的说法打架**：导入页说「留空 = 应用根目录」，后端说「没填」。
   - `frontend/src/components/ExportBack.tsx:84` vs `backend/app/routers/export.py:180`。
   - 修法：二选一。真要支持根目录就在 `create_document` 里允许空 `folder_token`（飞书 API 确实允许，建在应用「我的空间」，但用户在飞书里找不到——所以更建议改前端文案为「必填」）。
8. **单篇弹层里更新也要求填飞书文件夹 token**，后端其实不要（实测留空 `updated:1`）。
   - `ExportNotePanel.tsx:62-64`。修法：`remotes` 里已有 feishu 的时候 `ready` 不看 `folder`。
9. **Notion / 飞书没有「对方改过就跳过」**，Obsidian 有。第二次导出会无声删光对面用户手加的内容。
   - `export.py:158-166`、`:186-190`；`exporters.py:299 last_edited()`、`:343 edited_time()` 已写好但没人调。
   - 修法：`record_remote` 时把 `last_edited_time` / `revision_id` 存进 `remote_path`（或加列），下次比对不一致就进 `conflicts`，走 `force`。
10. **飞书 >500 块的文档第二次导出只删前 500 块**，新旧内容拼在一起。
    - `exporters.py:334-338` `page_size=500` 且不翻页。修法：循环 `page_token` 直到 `has_more=false`，或 `batch_delete` 用总数。
11. **Obsidian `vault_dir=""` 时后端把文件写进进程 cwd**（实测写进了 `backend/`）。前端按钮拦住了，但 API 层是个洞。
    - `export.py:78-79`。修法：`if not body.vault_dir.strip(): raise HTTPException(400, "vault 目录没填")`，并要求 `vault.is_absolute()`。
12. **front-matter `title:` 不加引号**，标题含 `: `、` #`、或以 `[ { " ' * & !` 开头时 Obsidian 报 Invalid YAML。
    - `exporters.py:72`。修法：`title: {json.dumps(title, ensure_ascii=False)}`（YAML 双引号字符串），`icon` 同理。
13. **`[标题](note://id)` 笔记间链接导到 Obsidian 是死链**。
    - `exporters.py:69-77` 没处理 `note://`。修法：`render_tree` 已经算出了每篇的路径（`written` 字典，`:91`），
      把 `note://<id>` 改写成相对 `.md` 路径（或 `[[文件名]]`）。
14. **段内硬换行用英文空格拼**，中文正文里凭空多空格（Notion / 飞书）。
    - `exporters.py:177` `" ".join(...)`。修法：改成 `"\n".join`（Notion / 飞书 rich_text 都接受 `\n` 软换行），或按 CJK 判断不加空格。
15. **飞书 App ID 填错报「10003：invalid param」**，看不出是哪个框。
    - `exporters.py:320-327`。修法：`token()` 里把 10003 / 10014 映射成「App ID 不对」「App Secret 不对」。
16. **错误 toast 6 秒消失、不能选中复制**，上面那些长英文根本来不及看。
    - `frontend/src/toast.ts:26`。修法：导出失败走 `toastAction(msg, '复制', …)` 或不自动消失；`ExportNotePanel` 底部把 `failed[]` 渲出来
      （现在只渲 `conflicts`，`:137-141`）。
17. **图片相对路径 `_assets/x.png` 对子目录里的笔记严格说是错的**（应为 `../_assets/`）。Obsidian 大概率靠「按 vault 根再找」兜住，
    但本机没装 Obsidian 没能实开。`exporters.py:77`。修法：按文件深度算 `../` 前缀，或把 `_assets` 改成 Obsidian 的 `![[x.png]]`。

**没验到、要说清楚的**：Notion 真发（无凭据）；Obsidian 在 Obsidian 应用里实开（本机没装）；飞书图片上传（产品没做，无从验）。
