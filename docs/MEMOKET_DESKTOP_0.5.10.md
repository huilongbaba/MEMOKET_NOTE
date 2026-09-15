# 参照物：memoket desktop 0.5.10（正式版实测）

> 第 711 轮建。**这份文档取代之前所有对「memoket desktop 视觉」的记述。**
>
> 第 679–710 轮那一大段视觉适配对错了东西：我对的是
> `~/code/memoket_desktop` 仓 **`v3-demo-ux` 分支**上 `electron/UIUXtest/shots/`
> 里 **2026-06** 那批展示稿（0.3.x 时代）。用户点名「文件列表栏那个淡紫色太丑」
> 之后才查出来——**他们自己早就把外壳从淡紫改成中性了**，只是那批图没跟上。
>
> 正确的参照物：**用户这台 mac 上装着的 `/Applications/Memoket.app`**，
> `CFBundleShortVersionString = 0.5.10`，构建于 **2026-09-14**。

## 怎么取的证（两路互证，都要）

1. **实拍**：`open -a Memoket` → `screencapture -x -o <file>`（全屏，1x），
   再裁出窗口逐像素量。**构图和颜色以这一路为准。**
   （`osascript` 拿窗口坐标要「辅助访问」权限，这台机器没给，靠像素找边界。）
2. **出货 CSS / JS**：从 `app.asar` 里扒出来——
   ```
   npx @electron/asar extract-file /Applications/Memoket.app/Contents/Resources/app.asar \
       out/renderer/assets/index-HDj-fLbQ.css
   ```
   （文件名从 `out/renderer/index.html` 里读。）**精确数值以这一路为准。**

**两路缺一不可**：只读 CSS 会把不出货的分支当真（它同时带着 mac / Windows /
深色三套覆盖）；只看实拍量不出圆角和字重。

## 1. 底色：外壳是**中性**的，紫只给强调面

0.5.10 新增了一整套 `--home-*`，并在 `.home` / `.sidebar` 作用域里把
`--ink` / `--ink-2` / `--ink-3` 覆盖掉：

| 令牌 | 值 | 实拍量到 |
|---|---|---|
| `--home-canvas` | `#FDFDFD` | `(253,253,253)` ✓ |
| `--home-sidebar` | `#F3F2F0`（暖中性，R−B **+3**） | `(241,240,238)` |
| `--home-ink` | `#111111` | — |
| `--home-ink-2` | `#666666` | — |
| `--home-ink-3` | `#999999` | — |
| `--home-border` | `rgba(0,0,0,.16)` | 搜索框边线 `(212,212,212)` ✓ |
| `--line` | `rgba(0,0,0,.10)` | 卡片边线 `(227,227,227)` ✓ |
| `--line-2` | `rgba(0,0,0,.05)` | — |
| `--hover` | `rgba(0,0,0,.04)` | — |
| `--sel` | `#F1EAFE` | — |

紫色在整屏上只出现在：主按钮（Record）、选中态 `--sel`、周报卡
（实拍 `(241,236,253)`）、Beta 横幅（`(245,241,254)`）、品牌图标。
**大面积的 chrome 一律中性。**

**深色不变**：深色下 `--home-canvas: var(--paper)`、`--home-sidebar: var(--sidebar)`、
`--home-ink: var(--ink)`，全部指回原来带紫的那套。**这次中性化只发生在浅色。**

### 我们这边有意的偏离（只有一处）

`--ink-3` 不取 `#999999`：它在我们纸面上只有 **2.80**、侧栏 **2.55**，
而 UI_SPEC §5 定的门槛是「纯装饰的 `--ink-3` 也要 ≥3」。
**色相照搬（纯中性灰，这正是用户嫌紫的那一点），亮度收一档**到 `#8C8C8C`
（纸面 3.31 / 侧栏 3.01）。要读的东西（计数、分组标题）照旧走 `--ink-2`。

## 2. 字

```
--sans:    -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue",
           "PingFang SC", "Microsoft YaHei", sans-serif      ← 跟我们原来一模一样
--display: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text",
           "PingFang SC", "Helvetica Neue", sans-serif       ← 他们叫 --serif
--mono:    "SF Mono", ui-monospace, "JetBrains Mono", Menlo, monospace
```

`--display` 只用在大标题（`.home-greet` 36px）。SF 这两支是给不同尺寸调过的：
Text 加粗细节笔画保证小字清楚，Display 收紧字距和开口，大字才不松。

## 3. 图标：**lucide-react v1.17.0**（ISC）

从 bundle 里确认（`@license lucide-react v1.17.0`，100 处引用）。
我们现在用的是 **boxicons**（字体图标）——这是「一眼像不像」的根之一，
两者的笔形、粗细、端点完全不同。lucide 是 24 viewBox、stroke 2、圆端圆角。
他们在个别位置把 stroke 调到 1.7–2.1。

## 4. 尺寸与布局（出货 CSS 原文）

```css
--sidebar-width: 280px;
--shell-topbar-height: 44px;        /* .home-topbar 实际 min-height: 52px */
--shell-content-pad-x: 16px;
--r-sm: 9px;  --r: 12px;  --r-lg: 18px;  --r-xl: 24px;   /* 跟我们已有的一致 */
```

| 组件 | 规则 |
|---|---|
| `.sidebar` | 宽 280、底 `--home-sidebar`、`border-right: 1px solid var(--line-strong)`（mac 分支是 0） |
| `.sb-search` | `margin: 16px 16px 24px`；高 **40**；`padding: 0 14px`；`gap: 12`；圆角 **12**；底 `--surface`；边 `--home-border`；图标 20；input **13px**；focus = 品牌色边 + `0 0 0 3px var(--brand-weak)` |
| `.nav-item` | 高 **36**；`padding: 0 8px`；圆角 **10**；`gap: 6`；**14px / 500**；图标盒 **20×20**（字形 16）；行距 4 |
| `.nav-item.sel` | `background: var(--home-canvas)`；**`box-shadow: none`**（实拍逐像素核对：药丸上下边是底色直接跳到面色，**无描边无阴影**） |
| `.nav-item .ic` | 20×20，`color: var(--ink)`；**选中时不变品牌色**（`.sel .ic { color: var(--ink) }`） |
| `.nav-item .count` | **12px / 400 / `--ink-3`**，`background: transparent`，无圆角 |
| `.sb-section` | `padding: 12px 10px 6px`；**11px / 700**；`letter-spacing: .08em`；大写；`--ink-3` |
| `.sb-folder-row` | 高 **36**；圆角 **10** |
| `.home-topbar` | `min-height: 52`；`padding: 9px 22px 9px 16px`；右对齐 |
| `.home-section` | **12px / 700**；`letter-spacing: .07em`；大写；`--ink-3`；`margin: 34px 0 12px` |
| `.home-notescard` | flex，`gap: 14`；`padding: 18px`；边 `1px var(--line)`；圆角 **`--r-lg`(18)**；底 `--surface`；`--shadow-card`；**hover = 边线染 45% 品牌色 + `translateY(-1px)` + `0 14px 30px -16px rgba(40,24,90,.3)`** |
| `.home-greet` | `--display`，**36px / 1.05**，`letter-spacing: .005em` |
| `.home-sub` | **15px**，`--ink-2`，`line-height: 1.5` |

## 5. 构图（实拍读出来的）

- 侧栏自上而下：红绿灯留白 → 搜索框 → 导航行（Home / MemoChat / Integrations /
  Weekly Reports）→ 大片留白 → 底部账号行（头像 + 名字 + 套餐 + ⌄）。
  **侧栏和画布之间没有可见分隔线**（mac 分支 `border-right: 0`），靠 12 级亮度差分开。
- 内容区：顶栏右对齐两个动作（ghost 图标钮 + 紫色实心 `Record` 胶囊）→
  横幅卡 → 两张并排卡（Today / Weekly Reports）→ `All files 1366 ⌄` 大标题 →
  **按时间分组的大写小标题** → 一列**卡片**（不是密排行，卡之间留 12px）。
- 底部常驻 composer：圆角条，左侧占位符「Ask or summarize your notes」，
  右侧麦克风 + 发送圆钮，浮在内容之上。

## 6. 落地进度

逐条落地记在 `TRACELOG-trilium.md` 第 711 轮起，规范同步进 `UI_SPEC.md`。

| # | 项 | 状态 |
|---|---|---|
| 1 | 面 / 墨 / 线 中性化（浅色） | ✅ 第 711 轮 |
| 2 | 侧栏分界线 `--mk-line-strong`、搜索框 40/12/14 | ✅ 第 711 轮 |
| 3 | 树行 36 / 10 / 14 / 500 / 图标 20×20、选中态去阴影 | ✅ 第 712 轮 |
| 4 | 大标题走 `--display` | ✅ 第 712 轮 |
| 5 | 行尾计数去掉品牌紫 | ✅ 第 712 轮 |
| 6 | 图标 boxicons → lucide（1.17.0，同版） | ✅ 第 713 轮 |
| 7 | AI 入口搬到底部 composer（dock + 玻璃胶囊） | ✅ 第 714 轮 |
| 8 | 卡片 18 圆角 / 18 内边距 / 边线 .10 / hover 染边上浮 | ✅ 第 715 轮 |
| 9 | 分组标题两档（侧栏 11/.08em、内容 12/.07em + 34px 上白） | ✅ 第 715 轮 |
| 10 | 深色下玻璃边 / line-strong 补值 | ✅ 第 715 轮 |
| 11 | 顶栏 52 高、主动作胶囊 | 待办 |
| 12 | 逐屏复核（浅色 + 深色） | 进行中 |
