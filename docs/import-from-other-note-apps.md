# 从 Apple Notes / Notion / Evernote / Obsidian 自动导入

调研于 2026-09-05。目标：把用户在别处积累的笔记搬进 memoket-note，成为写作
harness 能检索到的材料。

---

## 0. 结论先行

四个源的难度差得很远，建议按这个顺序做：

| 源 | 拿到内容的方式 | 难度 | 能不能真正「自动」 |
|---|---|---|---|
| **Obsidian** | vault 就是磁盘上的 markdown 文件 | 极低 | 能，watch 目录即可增量同步 |
| **Notion** | 官方 Markdown API（2026-02 上线） | 低 | 能，token + 轮询 |
| **Apple Notes** | AppleScript（官方路径）或直读 NoteStore.sqlite | 中 | 能，但只能在用户自己的 Mac 上跑 |
| **Evernote** | ENEX 导出文件（离线解析） | 中 | 半自动：导出这一步基本要人工触发 |

**先做 Obsidian 和 Notion**：这两个能做成真正的后台同步，而且覆盖了大部分
有大量结构化笔记的用户。Apple Notes 只能做成「本机小工具」，Evernote 现实
上是一次性迁移而不是持续同步。

---

## 1. 先决定：导进来当「材料」还是当「笔记」

memoket-note 有两个完全不同的落点，选错了整个导入白做：

| 落点 | 接口 | 结果 | 适合 |
|---|---|---|---|
| **知识库** | `POST /api/ingest/text`、`POST /api/ingest/batch` | 抽成事实进 KITE，写作时被检索 | 会议记录、资料、别人的笔记 |
| **笔记** | `POST /api/notes` | 一篇可编辑的文档，出现在列表里 | 用户自己在写、还想接着写的东西 |

多数场景要的是**两者都做**：正文进笔记列表（用户能接着写），同时进知识库
（以后写别的东西时能被引用）。这一步没有现成接口，需要导入器自己调两次。

---

## 2. 现有导入路径的两个缺陷（必须先补）

批量导入之前，`app/routers/ingest.py` 有两处会直接毁掉导入质量：

### 2.1 日期被写成「今天」

```python
# app/routers/ingest.py:81 和 :199
date=_date.today().isoformat(),
```

所有导进来的内容，日期都变成导入当天。而知识库里事实的日期是写作时判断
`factual_grounding` 的依据（见 `docs/_research/harness-architecture.md` 第 9 节
「事实的时间信息从未进过 prompt」那条根因）——**一次导入会把用户几年的笔记
全部压成同一天，时间线彻底失真**。

对照 `scripts/ingest_terrence_corpus.py:107` 是对的：`date=started_at`。

**要改**：`IngestTextIn` 加 `date: str = ""`，批量接口按文件 mtime 或来源
元数据带上原始日期。

### 2.2 session_id 随机，重复导入会翻倍

```python
session_id=f"{source}-{uuid.uuid4().hex[:8]}-{i}",   # 每次导入都是新 id
```

KITE 会拒绝重复的 session_id（不花 LLM 调用就跳过），这是 `ingest_terrence_corpus.py`
能断点续跑的原因。但 HTTP 导入路径用的是随机 id，**同一批笔记导两次就在知识库里
存在两份**，而且第二份还要重新花一遍抽取的钱。

**要改**：session_id 用源侧稳定标识拼，例如
`f"notion-{page_id}-{chunk_idx}"`、`f"obsidian-{相对路径的 sha1}-{chunk_idx}"`。
这样重跑导入自动变成增量同步，不需要额外的去重逻辑。

这两条改完，下面四个导入器都只是「把内容取出来，POST 进去」。

---

## 3. Obsidian（最简单，先做这个）

vault 就是一个装满 `.md` 的目录，没有 API、没有鉴权、没有格式转换。

```python
import hashlib, pathlib, httpx

VAULT = pathlib.Path("~/Documents/MyVault").expanduser()
BASE, H = "http://localhost:8000", {"X-User-Id": "me"}

for md in VAULT.rglob("*.md"):
    if any(p.startswith(".") for p in md.parts):      # 跳过 .obsidian/ .trash/
        continue
    text = md.read_text(encoding="utf-8")
    rel = md.relative_to(VAULT).as_posix()
    httpx.post(f"{BASE}/api/ingest/text", headers=H, json={
        "content": text,
        "title": md.stem,
        "source": f"obsidian:{hashlib.sha1(rel.encode()).hexdigest()[:12]}",
        # "date": ...  ← 等 2.1 改完，用 frontmatter 的 created 或 md.stat().st_mtime
    }, timeout=300)
```

**要处理的 Obsidian 特有语法**：

- `[[wiki 链接]]`：抽取时是噪声，建议转成纯文本（`[[A|B]]` → `B`，`[[A]]` → `A`）
- YAML frontmatter：`---` 之间的部分单独解析，`created`/`date` 拿来当日期，
  `tags` 可以拼进 title，正文里去掉
- `![[附件.png]]`：直接删掉，KITE 只吃文本
- Dataview / Templater 代码块：删掉，是模板不是内容

**做成持续同步**：`watchdog` 监听 vault 目录，文件变更就重新 POST。因为
session_id 稳定（2.2 改完之后），重复 POST 自动是覆盖而不是新增。

---

## 4. Notion（有官方 Markdown API，2026-02 上线）

以前要递归拉 block 树自己拼 markdown，现在有一个端点直接给 markdown：

```
GET https://api.notion.com/v1/pages/{page_id}/markdown
Authorization: Bearer {token}
Notion-Version: 2026-03-11
```

对 public / internal / personal access token **都开放**，需要 `read_content`
能力。

枚举「这个 token 能看到哪些页面」仍然走 search：

```python
import httpx

NH = {"Authorization": f"Bearer {TOKEN}",
      "Notion-Version": "2026-03-11",
      "Content-Type": "application/json"}

def all_pages():
    cursor, out = None, []
    while True:
        body = {"filter": {"property": "object", "value": "page"}, "page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        r = httpx.post("https://api.notion.com/v1/search",
                       headers=NH, json=body, timeout=60).json()
        out += r["results"]
        if not r.get("has_more"):
            return out
        cursor = r["next_cursor"]

for page in all_pages():
    md = httpx.get(f"https://api.notion.com/v1/pages/{page['id']}/markdown",
                   headers=NH, timeout=120).json()
    httpx.post(f"{BASE}/api/ingest/text", headers=H, json={
        "content": md.get("markdown", ""),
        "title": _title_of(page),          # properties.title[].plain_text
        "source": f"notion:{page['id']}",  # 稳定 → 重跑即增量
        # "date": page["created_time"][:10]  ← 等 2.1 改完
    }, timeout=300)
```

**坑**：

- **限流 3 请求/秒**，几百页就要几分钟；导入器要自己 sleep，别指望 Notion 报错重试
- **超大页面会被截断**（约 2 万 block 以上），返回里会出现 unknown 标签
- **子页面没共享给这个 integration 就取不到** —— 用户必须在 Notion 里把
  目标页面/数据库显式 Connect 给这个 integration，这是最常见的「导了但是空的」原因
- 数据库行（database page）也是 page，会被 search 返回；要不要导进来取决于
  用户，建议做成可选项，否则一个 500 行的数据库会灌进 500 条碎片

---

## 5. Apple Notes（只能在用户自己的 Mac 上跑）

没有公开 API，两条路：

### 5.1 AppleScript（官方、安全，推荐）

Apple 认可的唯一自动化路径，不需要开发者模式、不碰 TCC、不会破坏 iCloud 同步。

```applescript
tell application "Notes"
    repeat with n in notes
        set noteTitle to name of n
        set noteBody to body of n          -- HTML
        set noteDate to modification date of n
        set noteFolder to name of container of n
        -- 写成 JSON / 文件，交给 Python 侧 POST
    end repeat
end tell
```

- `body of n` 拿到的是 **HTML**，要转 markdown（`html2text` / `markdownify`）
- 首次运行会弹「允许终端控制 Notes.app」的授权框，**必须用户手动点** ——
  这是它做不成无人值守服务的根本原因
- 性能可接受：实测 macOS Sequoia / M3 Pro 上约 100 条 / 3 秒

### 5.2 直读 NoteStore.sqlite（快但脆）

```
~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite
```

正文是 **gzip 压缩过的 protobuf**，不是纯文本，要自己解。版本升级会改 schema。
**只读，绝对不要写** —— 写会破坏 iCloud 同步。

现成工具可以省掉这部分活：
- [`kzaremski/apple-notes-exporter`](https://github.com/kzaremski/apple-notes-exporter)
  （Swift App，保留文件夹结构，导多种格式）

**建议**：做成一个用户在自己 Mac 上跑一次的小脚本（AppleScript 导出 →
转 markdown → 批量 POST），不要试图做成服务端集成。

---

## 6. Evernote（现实上是一次性迁移）

Evernote 的 API 是 **OAuth 1.0**，而且应用要 Evernote 人工审批才能在生产环境
激活 —— 对一个导入功能来说这条路成本过高。

**走 ENEX 文件**：

- 桌面客户端：选中笔记本 → 导出为 `.enex`
- 或者用 [`vzhd1701/evernote-backup`](https://github.com/vzhd1701/evernote-backup)：
  先同步到本地 SQLite，再离线导出 ENEX（**导出这一步完全离线，不走 Evernote API**），
  一个笔记本一个 `.enex`

ENEX 是 XML，一个 `<note>` 一条笔记：

```python
import base64, xml.etree.ElementTree as ET
from markdownify import markdownify

for note in ET.parse("笔记本.enex").getroot().iter("note"):
    title = note.findtext("title") or "无标题"
    content = note.findtext("content") or ""     # ENML，是 XHTML 的子集
    created = (note.findtext("created") or "")[:8]   # 20260315T…
    body = markdownify(content)
    # <resource> 是 base64 附件，KITE 只吃文本，跳过
```

**坑**：

- ENML 不是 HTML，有自己的 DTD（`<en-note>`、`<en-media>`）；`markdownify`
  基本能用，但 `<en-media>` 要先删掉，否则会留下垃圾
- 日期格式是 `20260315T091500Z`，要转成 `2026-03-15`
- 大笔记本的 ENEX 可以到几百 MB，**要流式解析**（`ET.iterparse`）而不是
  `ET.parse` 一次读进内存

---

## 7. 建议的实施顺序

1. **先补 §2 的两个缺陷**（日期 + 幂等 session_id）。不补的话，后面每个导入器
   都会把用户的时间线压平、重跑就翻倍，返工成本比现在改高得多。
2. **Obsidian 导入器**：一个 100 行的脚本 + `watchdog` 持续同步。用它把整条
   链路跑通（正文清洗 → 双落点 → 增量）。
3. **Notion 导入器**：复用 2 的清洗和落点逻辑，只换取内容那一段。
4. **Apple Notes**：做成用户本机跑的一次性脚本，不进服务端。
5. **Evernote**：文档化「怎么导出 ENEX + 把文件拖进来」，走已有的
   `POST /api/ingest/batch`（它已经收 md/txt/pdf/docx，加一个 `.enex` 解析即可）。

---

## Sources

- [Notion — Working with markdown content](https://developers.notion.com/guides/data-apis/working-with-markdown-content)
- [Notion — Export your content](https://www.notion.com/help/export-your-content)
- [kzaremski/apple-notes-exporter](https://github.com/kzaremski/apple-notes-exporter)
- [Export Apple Notes via AppleScript（gist）](https://gist.github.com/able8/0a7ac85ebb3f77b7b427288621551b86)
- [MacMost — Export All Of The Notes On Your Mac Using a Script](https://macmost.com/export-all-of-the-notes-on-your-mac-using-a-script.html)
- [vzhd1701/evernote-backup](https://github.com/vzhd1701/evernote-backup)
- [Evernote 论坛 — 命令行导出 ENEX 的讨论](https://discussion.evernote.com/forums/topic/147854-export-enex-via-commandline-in-evernote-10x/)
