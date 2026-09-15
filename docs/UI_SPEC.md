# MEMOKET NOTE · UI 规范

**这份文档是 UI 的唯一裁决依据。**以后往这个应用里加任何界面，先对一遍这里；
对不上就改界面，不是改文档（要改文档，先说清楚为什么，并改在这一份里）。

- **风格来源**：`memoket/memoket-desktop` 的 Design System v3
  （`electron/src/renderer/src/styles/design-theme.css`，本机检出在
  `~/code/memoket_desktop`），它自己又对齐移动端 APP 的 `AppTheme`
  （品牌紫 `#620FF0`）。
- **本应用现状**：配色和组件抄自 Trilium（`frontend/src/shell.css` 是 Trilium
  令牌，`frontend/src/styles.css:1-60` 是一层语义别名），accent 是蓝色 `#2563eb`。
- **这次要做的事**：把**视觉身份**换成 memoket 的，**布局和交互不动**。

## 0. 铁律

> **风格跟 memoket-desktop 对齐，布局和交互走这个应用自己的。**

抄的是颜色、字号字重、圆角、阴影、控件长相。**不抄**它的三栏结构、侧边栏导航、
录音条、MemoChat——那是另一个产品的 IA。这个应用的 IA 是 Trilium 式的
（启动器 + 树 + 标签 + 三栏 + ribbon），那部分已经做了 670 多轮，不动。

同理，**不抄它的 `[data-theme]` 切换方式**。这个应用的深色是
`@media (prefers-color-scheme: dark)`，桌面版靠 Electron `nativeTheme.themeSource`
驱动（`desktop/src/main.ts:304`）——网页版也能跟随系统，是有意的。
深色令牌一律写在 media 块里，**不要引入 `[data-theme]` 选择器**。

## 1. 令牌

### 1.1 新增一层：`frontend/src/design-tokens.css`

这个应用已经有一层别名（`styles.css:1-33` 把 `--bg`/`--fg`/`--line` 指到
Trilium 令牌）。**这次照样走别名，不做全局改名**——理由跟当初一样写在那儿：
这十来个名字散在两千多行 CSS 和几十个组件的内联样式里，一次性改完是纯机械风险。

新文件只定义**源令牌**，`shell.css` 和 `styles.css` 改成指向它。

| 令牌 | 浅色 | 深色 | 来源 |
|---|---|---|---|
| `--brand` | `#620FF0` | `#9B6BFF` | `design-theme.css:10` / `:66` |
| `--brand-2` | `#8B5AE8` | `#B794FF` | `:11` / `:67` |
| `--brand-press` | `#4A1F9C` | `#8A55F5` | `:12` / `:68` |
| `--brand-weak` | `#F1EAFE` | `rgba(98,15,240,.20)` | `:13` / `:69` |
| `--brand-text` | `#620FF0` | `#C9B2FF` | `:14` / `:70` |
| `--grad` | `135deg,#620FF0,#8B5AE8 55%,#6F5BFF` | `#7B3BF0,#9E6BFF 55%,#6E8BFF` | `:15` / `:71` |
| `--live`（危险/录音红） | `#F05049` | `#FF6A64` | `:16` / `:72` |
| `--mk-bg`（窗口底） | `#E4E0F0` | `#050409` | `:19` / `:74` |
| `--mk-surface`（卡面） | `#FFFFFF` | `#16131F` | `:20` / `:75` |
| `--mk-paper`（正文纸面） | `#FCFBFF` | `#120F1A` | `:21` / `:76` |
| `--mk-sidebar` | `#F5F3F9` | `#0E0B15` | `:22` / `:77` |
| `--ink` | `#0E1014` | `#F2EFF7` | `:23` / `:78` |
| `--ink-2` | `#6E7682` | `#A39EB0` | `:26` / `:79` |
| `--ink-3` | `#8E949E` | `#6C6678` | `:27` / `:80` |
| `--mk-line` | `rgba(0,0,0,.10)` | `rgba(255,255,255,.09)` | `:42` / `:93` |
| `--mk-line-2` | `rgba(0,0,0,.05)` | `rgba(255,255,255,.055)` | `:43` / `:94` |
| `--mk-hover` | `rgba(0,0,0,.04)` | `rgba(255,255,255,.05)` | `:44` / `:95` |
| `--sel` | `#F1EAFE` | `rgba(98,15,240,.18)` | `:45` / `:96` |
| `--success` / `--success-text` | `#0FBD58` / `#0E9E49` | `#34D17E` / `#4ADB8F` | `:34-36` / `:85-87` |
| `--warning` | `#F0A815` | `#F7B955` | `:37` / `:88` |
| `--shadow-card` | `0 1px 2px rgba(33,30,41,.05), 0 6px 18px -10px rgba(33,30,41,.10)` | `none` | `:51` / `:99` |
| `--shadow-pop` | `0 20px 56px -16px rgba(35,22,70,.30), 0 2px 8px rgba(20,16,40,.07)` | `0 22px 60px -14px rgba(0,0,0,.75)` | `:49` / `:97` |
| `--r-sm` / `--r` / `--r-lg` / `--r-xl` | `9px` / `12px` / `18px` / `24px` | 同 | `:55` |
| `--sans` | `-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", "PingFang SC", "Microsoft YaHei", sans-serif` | 同 | `:60` |
| `--mono` | `"SF Mono", ui-monospace, "JetBrains Mono", Menlo, monospace` | 同 | `:61` |

> **别照抄，先算。**（第 679 轮实算，三处源仓库的值在这个应用上不过线）

| 令牌 | 源仓库 | 这里用 | 为什么 |
|---|---|---|---|
| `--ink-2` | `#6E7682` | **`#666E7A`** | 源仓库那个值是对**纯白**量的（4.59）；这个应用的正文纸面是 `#FCFBFF`，同一个值只有 **4.45**，差一点点。暗一步之后纸面 5.00 / 侧栏 4.68 / 卡面 5.15，三处都过 AA。 |
| `--ink-3` | `#8E949E` | **`#7A818C`**，**并且改用法** | 原值在纸面只有 **2.96**，连 AA 大字都不过。与其硬调到 4.5（那就跟 `--ink-2` 没区别了），不如**把要读的东西挪走**：分组标题、计数角标一律改用 `--ink-2`，`--ink-3` 只留给占位符、图标底色这类不用读的。 |
| 深色主按钮 | 白字压 `--brand #9B6BFF` | **新令牌 `--brand-fill`** | 白字压在 `#9B6BFF` 上只有 **3.53**，不过 AA。但 `--brand` 又该留着做图标 / 链接 / 边框——那些场合越亮越清楚。**一个职责一个令牌**：`--brand-fill` 是「实心块上的品牌色」，浅色 `#620FF0`（白字 7.38），深色 `#7C46EE`（白字 5.29）。 |

### 1.4 `--ink-3` 不承载需要读的内容

这是上表第二行推出来的一条规矩，单独列出来因为它管的是**用法**：
`--ink-3` 只用于占位符、图标底色、分隔性的弱装饰。任何**用户需要读**的字
（标签、计数、说明、标题）至少用 `--ink-2`。

### 1.2 不动的令牌

- **`--jn-1..8`（屏幕活动的分类色）**：`shell.css:62-64`。这是一套过了
  色盲校验的 8 槽分类调色板，**换成品牌色系会毁掉它的可分辨性**。原样保留。
- **`--ins` / `--del`（修订的增删色）**：绿/红是 diff 的通用约定，跟品牌无关。
  保留，但深浅两套要跟新底色重新配一次对比度。
- **阴影不改配方，只换值**：源仓库的阴影是给窗口化应用做纵深的，这个应用同样是
  窗口化的，直接用它的四个。

### 1.3 别名怎么接

| 现有别名 | 现在指向 | 改成指向 |
|---|---|---|
| `--bg`（`styles.css:11`） | `var(--main-bg)` | `var(--mk-paper)` |
| `--panel`（`:17`） | `var(--main-bg)` | `var(--mk-surface)` |
| `--surface-raised`（`:12`） | `var(--accented-bg)` | `var(--mk-sidebar)` |
| `--fg`（`:14`） | `var(--main-fg)` | `var(--ink)` |
| `--muted`（`:15`） | `#666666` | `var(--ink-2)` |
| `--line`（`:16`） | `var(--main-border)` | `var(--mk-line)` |
| `--hover`（`:13`） | `var(--hover-item-bg)` | `var(--mk-hover)` |
| `--accent`（`:18`） | `#2563eb` | `var(--brand)` |
| `--accent-fg`（`:19`） | `#ffffff` | `#ffffff`（不变） |
| `--warn`（`:20`） | `#b45309` | `var(--warning)` |
| `--del`（`:23`） | `#dc2626` | `var(--live)` |

`shell.css` 的 Trilium 令牌同样改成指向新令牌（`--root-bg → --mk-bg`、
`--main-bg → --mk-surface`、`--left-pane-bg → --mk-sidebar`…）。
**一改就是全应用**，这正是当初留这层别名的目的。

## 2. 组件规范

每条都给了源仓库的 `file:line`。新加组件时按这张表挑，不要自己发明尺寸。

### 2.1 按钮

| | 值 | 源 |
|---|---|---|
| 高度 | `33px`（紧凑场合 28px） | `design-theme.css:222` |
| 圆角 | `var(--r-sm)`（9px） | 同 |
| 内边距 | `0 13px` | 同 |
| 字号/字重 | 13.5px / 600 | 同 |
| 默认态 | 透明底、透明边、`--ink-2` 字 | 同 |
| hover | 底 `--mk-hover`，字 `--ink` | `:223` |
| active | `transform: scale(.97)` | `:224` |
| 主按钮 | 底 **`--brand-fill`**（不是 `--brand`，见 §1.3 表）、白字、`--shadow-brand` | `:225` |
| 主按钮 hover | 底 `--brand-press` | `:226` |
| 危险按钮 | 底 `--live`、白字 | `:227` |
| 禁用 | `opacity:.5`，**并且必须有 title 说明为什么**（`check-a11y` 闸门） | 本应用 |

**默认按钮是「幽灵按钮」**（透明底 + 无边框），不是现在这种「有边框的白底方块」。
这是这次适配最显眼的一处变化：工具栏、面板里成排的按钮会安静下来，
主按钮因此真的跳出来。

### 2.2 输入

| | 值 | 源 |
|---|---|---|
| 高度 | 表单 `38px`，搜索条 `32px` | `shell.css:90` / `design-theme.css:171` |
| 圆角 | `var(--r-sm)` | 同 |
| 边 | `1px solid var(--mk-line)` | 同 |
| 底 | `var(--mk-surface)` | 同 |
| 聚焦 | `border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-weak)` | `shell.css:91` |
| placeholder | `--ink-3` | `design-theme.css:172` |

**聚焦环换成品牌紫的三像素光晕**，替掉现在那条 `:focus-visible` 的黑色 outline
（`styles.css:70`）。键盘可达性不变——只是换了长相。

### 2.3 选中态（树、标签、列表行）

| | 值 | 源 |
|---|---|---|
| 浅色选中 | 底 `--mk-surface` + `--shadow-card`，字重 600 | `design-theme.css:178` |
| 深色选中 | 底 `rgba(255,255,255,.06)`，**无阴影** | `:179` |
| 选中行的图标 | `--brand` | `:181` |
| hover | 底 `--mk-hover` | `:177` |
| 行高 | 导航 36px / 文件夹 34px | `:176` / `:185` |

**「选中 = 抬起来的白片 + 图标变紫」**，不是「刷一块背景色」。这条同时管
左树、标签页、命令面板、事实表行。

### 2.4 Chip / 标签片

**源仓库没有这个组件**，只有 30px 高的筛选条 `.cat-chip`（`design-detail.css:281`，
一排就几个）。这个应用的 chip 是**标签云**（实体页上百个）。实测照搬 30px
会把 8 个实体从 2 行撑成 4 行。

> **抄不到就推导，并且写下来。** 抄的是视觉语言（胶囊、弱边弱字、选中品牌实心），
> **不是高度**——密度按用途定。这条以后遇到源仓库没有的组件一律照办。

| | 值 | 来源 |
|---|---|---|
| 高度 / 圆角 | `26px` / `13px`（胶囊） | 本应用自定（密度） |
| 默认 | 底 `--panel`、边 `--mk-line`、字 `--ink-2`、12px/600 | 推自 `.cat-chip` |
| hover | 字 `--ink`、边 `--ink-3` | `design-detail.css:282` |
| 选中 | 底+边 `--brand`、白字（含里面的图标和计数） | `:283` |

### 2.5 计数角标 / kbd

| | 值 | 源 |
|---|---|---|
| 计数 | 圆角 `999px`、底 `--mk-hover`、字 `--ink-3` 11px/700、内边距 `1px 7px` | `design-theme.css:150` |
| 快捷键 | `--mono` 10px/700、边 `1px var(--mk-line)`、圆角 5px、内边距 `1px 5px` | `:183` |

### 2.6 分组标题

`11px / 700 / letter-spacing .08em / uppercase / --ink-3`（`design-theme.css:184`）。
**中文不做 uppercase**（无效且会影响字距），只取字号、字重、字距、颜色。

### 2.7 菜单 / 弹层

| | 值 | 源 |
|---|---|---|
| 容器 | 底 `--mk-surface`、边 `1px --mk-line`、圆角 `var(--r)`、`--shadow-pop`、内边距 6px | `design-detail.css:199` |
| 行 | 内边距 `9px 10px`、圆角 `var(--r-sm)`、13.5px | `:201` |
| 行 hover | 底 `--mk-hover` | `:202` |
| 危险行 | 字和图标都 `--live` | `:204-205` |
| 分隔线 | `1px --mk-line`，`margin: 5px 6px` | `:208` |
| 小标题 | 10.5px/700/.05em/uppercase/`--ink-3` | `:200` |

### 2.8 对话框

圆角 `var(--r-lg)`、`--shadow-pop`、内边距 20px、标题 16px/700、
按钮行右对齐 gap 8px（`shell.css:89-93`）。

### 2.9 Toast

底 `--ink`、字 `--mk-surface`（**反色**）、圆角 10px、13px/600、内边距 `10px 18px`、
`box-shadow: 0 10px 30px -8px rgba(0,0,0,.35)`（`design-detail.css:749`）。

现在这个应用的 toast 是「白底+边框」（`styles.css:210`），改成反色块。
错误态保留 `--live` 作为左边一条 3px 的竖条，而不是把整块变红。

### 2.10 勾选框

19px、圆角 6px、`1.6px solid var(--ink-3)`，勾选后底和边都是 `--brand`、勾是白色
（`shell.css:96-97`）。

### 2.11 卡片

底 `--mk-surface`、边 `1px --mk-line`、圆角 `var(--r)`、`--shadow-card`
（`design-theme.css:163`）。现在是 8px 圆角无阴影（`styles.css:177`）。

## 3. 新增界面必须遵守的硬规矩

1. **不写字面颜色**。一切颜色走令牌。`#` 开头的颜色值只允许出现在
   `design-tokens.css` 里。
2. **不发明尺寸**。圆角只用 `--r-sm/--r/--r-lg/--r-xl`；按钮高度 33/28；
   输入高度 38/32；行高 36/34。
3. **主按钮一屏一个**。品牌紫是「这一屏你最该点的那个」，摆两个就等于没有。
4. **危险动作用 `--live`，并且要可撤销**（这个应用已有的 `toastAction` 模式）。
5. **深色一起写**。任何新令牌、任何新组件，浅色和深色同时给值；
   深色写在 `@media (prefers-color-scheme: dark)` 里，不用 `[data-theme]`。
6. **输入框要有名字**（`aria-label` 或可见 label）——`check-a11y` 闸门会拦。
7. **图标按钮要有 title**，**禁用按钮要说明为什么**——同一条闸门。
8. **能点的 div 要能键盘按**（用 `util/clickable`）——同一条闸门。
9. **分类色不碰 `--jn-*`**。那套是过了色盲校验的，改一个值就得重新验。

## 4. 改动清单

| 文件 | 改什么 |
|---|---|
| `frontend/src/design-tokens.css`（新建） | §1.1 的全部源令牌，浅色 `:root` + 深色 media 块 |
| `frontend/src/main.tsx` | 在 `shell.css` 之前 import 新文件（令牌要先于使用者） |
| `frontend/src/shell.css:13-64,67-100` | Trilium 令牌改成指向新令牌；`--jn-*` 不动 |
| `frontend/src/styles.css:1-60` | §1.3 的别名改指向；`--card-alt`/`--menu-bg`/`--scrollbar-*` 等跟着换算 |
| `frontend/src/styles.css:83-95,115` | 按钮改成 §2.1（幽灵按钮 + 品牌主按钮） |
| `frontend/src/styles.css:119-135` | input/select/textarea 改成 §2.2，聚焦环换品牌光晕 |
| `frontend/src/styles.css:70` | `:focus-visible` 换成品牌色 |
| `frontend/src/styles.css:177-178` | `.card` 改成 §2.11 |
| `frontend/src/styles.css:188-190` | `.badge` 改成 §2.5 |
| `frontend/src/styles.css:210-215` | `.toast` 改成 §2.9 |
| `frontend/src/styles.css:263-268` | `.modal` / backdrop 改成 §2.8 |
| `frontend/src/styles.css:868-872` | `.chip` 改成 §2.4 |
| `frontend/src/styles.css:663` | `.kb-section-title` 改成 §2.6 |
| `frontend/src/styles.css:515-540` | `.tree-node` 选中态改成 §2.3 |
| `frontend/scripts/check-ui-tokens.mts`（新建） | 第 5 节那条闸门 |

## 5. 怎么验

1. `cd frontend && npm test`（tsc + eslint + vitest + 23 条 check 脚本）；
   后端 `pytest` 不该受影响，但照跑。
2. **新增一条闸门 `check-ui-tokens`**：扫 `src/**/*.{css,tsx}`，
   除 `design-tokens.css` 外出现字面颜色（`#rgb`/`#rrggbb`/`rgb(`/`hsl(`）就失败，
   白名单里每一条要写明理由。**规范不上闸门就是许愿**（第 675 轮那条
   `check-a11y` 的教训）。
3. **实拍核对**：浅色 + 深色各一轮，至少覆盖首屏 / 知识库 / 笔记正文 /
   设置 / 导入 / 技能 六屏。用 `shot.sh <user> <probe> <name> [--dark]`。
4. **对比度要算，不要看**。第 679 轮实算抓到三处「看着没问题」的不过线
   （见 §1.3 表）。改任何颜色令牌之后重算这几对：白字/主按钮（亮+暗）、
   `--ink-2`/纸面、`--ink-2`/侧栏、`--ink-3`/纸面、`--ink`/纸面、`--brand`/纸面。
   正文级要 ≥4.5，纯装饰的 `--ink-3` 允许 ≥3。

## 6. 这份规范明确不做的事

- **不动布局**。启动器 / 左树 / 标签栏 / 三栏 / ribbon / 状态栏的结构一律不动。
- **不动交互**。快捷键、右键菜单、拖拽、撤销全部不动。
- **不引入 `[data-theme]`**。见 §0。
- **不换图标库**。继续用 boxicons；源仓库用的是别的图标集，换一遍是纯粹的
  机械风险，且用户认得现在这套。
- **不抄 `--fs` 密度乘子**。源仓库每个字号都写成 `calc(13px*var(--fs))`，
  那是为它的「界面缩放」设置服务的；这个应用没有那个设置，抄过来是一层
  没人用得到的间接。要加密度设置，另开一轮，那时再引。
