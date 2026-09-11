# Trilium UI 逐项比对 — 差距清单

> **这份文档只做比对，不含改动。** 每一条都带 Trilium 的**文件 + 行号**作为依据，
> 不写「整体风格需要优化」这种没法执行的话。
>
> **判据**：`docs/product-north-star.md` 三条 —— ①每个 AI 能力是一个按钮不是聊天框
> ②记忆不离开编辑页就能用 ③自动化的计划和判据要看得见。
> 有些东西 Trilium 有而我们**故意不要**，那些不算差距，单列在最后一节。

## 路径约定

| 记号 | 实际路径 |
|---|---|
| `$T` | `.../scratchpad/trilium/apps/client/src` |
| `$TS` | `.../scratchpad/trilium/packages/trilium-core/src` |
| `$M` | `/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/frontend/src` |

> **关于行号**：`$T` / `$TS`（Trilium）那一侧的行号是这次比对的**证据**，取自
> 浅克隆的固定快照，可以直接照着翻。`$M`（我们）那一侧的行号是
> **2026-09-10 20:49 的快照**——比对期间 `App.tsx` / `NoteTree.tsx` / `styles.css`
> 正被另一个进程改着（20:42–20:49 都有写入），所以我们这边的行号可能已经偏了几十行。
> **类名、变量名、结论本身都复核过仍然成立**；对不上行号时按类名 grep。

**一条要先说清的事**：我们 `shell.css:41-44` 的注释写着「尺寸取自 `desktop_layout.tsx`，
这两个数字是它自己写死的，不是我猜的」。这句话**只对了一半**——
`desktop_layout.tsx` 里的 53px / 40px 是**基础布局的值**，theme-next 主题层
用 `!important` 把它们全部覆盖掉了：

- 启动栏 `width: var(--launcher-pane-size) !important` — `$T/stylesheets/theme-next/shell.css:217-218`，
  值 `--launcher-pane-vert-size: 58px` — `$T/stylesheets/theme-next/base.css:40`
- 标签行 `height: var(--tab-bar-height) !important` — `$T/stylesheets/theme-next/shell.css:1008,1014`，
  值 `--tab-bar-height: 50px` — `$T/stylesheets/theme-next/base.css:56`（横版布局才是 44px，`shell.css:46`）

也就是说，**跑起来的 Trilium 是 58px / 50px，不是 53px / 40px**。
下面所有尺寸都以主题层的最终值为准。

---

## 1. 布局尺寸

| 维度 | Trilium 怎么做 | 我们现在 | 等级 | 建议 |
|---|---|---|---|---|
| 左栏宽度可调 | Split.js（`@triliumnext/split.js`）挂在 `["#left-pane","#rest-pane"]`，`gutterSize: 5`，`minSize: [150, 300]`，`onDragEnd` 存 `options.save("leftPaneWidth")` — `$T/services/resizer.ts:4,46-55` | `.left-pane { width: 260px; flex-shrink: 0 }` 写死，不能拖 — `$M/shell.css:124` | **严重** | 上一个 splitter（`react-split-pane` 或自己写 8 行 pointermove），最小 150px，宽度存 localStorage 按用户分（跟标签页持久化同一套） |
| **左栏没有滚动容器** | `.tree { height:100%; overflow:auto; padding-bottom:35px }` — `$T/widgets/note_tree.ts:48-53`；`.tree-wrapper { flex: 1 1 60%; min-height: 0 }` — `$T/widgets/note_tree.ts:38-46` | `.left-pane` 无 overflow；树被塞进 `.left-pane-search`（只有 `padding: 8px`，无 flex 无 overflow）— `$M/shell.css:129` + `$M/App.tsx:1726-1751`。`.shell` 是 `overflow: hidden`（`shell.css:91`），**笔记一多，树底部直接被裁掉且滚不到** | **严重** | `shell.css:130` 那条 `.left-pane-body{flex:1;overflow-y:auto}` **已经写好了但从没被用过**（全仓 0 处引用）。把 `App.tsx:1726` 的结构拆成 `.left-pane-search`（只包输入框）+ `.left-pane-body`（包树），一行结构改动就修好 |
| 右栏宽度可调 | Split.js `["#center-pane","#right-pane"]`，`minSize: [300, 180]`，存 `rightPaneWidth`，默认 25% — `$T/services/resizer.ts:81-91`；`$TS/services/options_init.ts:197` | `.right-pane { width: 300px }` 写死 — `$M/shell.css:151` | **严重** | 同上。默认给 25%（1440 宽窗口 ≈ 360px），下限 180px |
| 左/右栏独立折叠 | `LeftPaneToggle`（横版 `bx bx-sidebar` / 竖版 `bx bx-chevrons-left`，600ms 旋转动画）— `$T/widgets/buttons/left_pane_toggle.tsx:10-30`、`left_pane_toggle.css:1-29`；折叠时 `$("#left-pane").toggle()` + `#rest-pane` 吃满 + 启动栏右侧补 2px 分割线 — `$T/services/resizer.ts:18-32`、`$T/stylesheets/theme-next/shell.css:136-138`；状态存 `leftPaneVisible` — `$T/widgets/containers/left_pane_container.ts:23-40`。右栏另有 `toggleRightPane` / `peekRightPane` 两个 action — `$TS/services/keyboard_actions.ts:738-753` | 只有一个 `focusMode` **同时**收掉左栏和右栏 — `$M/App.tsx:1720,1943` | **明显** | 拆成两个独立开关（左栏折叠按钮放启动栏底部，右栏折叠放右栏标题行），各自持久化。`focusMode` 保留为「两个都收」的快捷方式 |
| 分栏拖拽把手 | `.gutter` 竖向渐变，hover 变色，`cursor: col-resize` — `$T/stylesheets/style.css:1627-1641`；theme-next 默认 transparent，hover `--gutter-hover-color`（亮 `#bfbfbf` / 暗 `#626262`）— `$T/stylesheets/theme-next/shell.css:161-168` | 无 | **明显** | 跟上面两条一起做；宽 5px，默认透明，hover 才显形 |
| 启动栏宽度 | 58px（`--launcher-pane-vert-size`）— `$T/stylesheets/theme-next/base.css:40` | 53px — `$M/shell.css:43` | 细节 | 改 58px |
| 启动栏按钮尺寸 | `width/height = calc(58px - 6px*2) = 46px`，`margin: 3px 6px`（gap 3px / margin 6px）— `$T/stylesheets/theme-next/shell.css:276-278`；图标 `font-size: 150%` — `base.css:41`、`shell.css:320-322` | 38×38，`gap: 2px`，容器 `padding: 8px 0`，`font-size: 18px` — `$M/shell.css:102,109-114` | 细节 | 46×46、gap 3px；图标随之放大 |
| 启动栏按钮键盘聚焦 | `outline: 2px solid var(--launcher-pane-button-focus-outline-color)` on `:focus-visible` — `$T/stylesheets/theme-next/shell.css:329-336` | 无 `:focus-visible` 样式 | 细节 | 补一条，值取 `--input-focus-outline-color` |
| 标签行高度 | 50px（竖版布局）— `$T/stylesheets/theme-next/base.css:56` | 40px — `$M/shell.css:44` | **明显** | 改 50px（标签 36px + 上下各 7px 呼吸） |
| **macOS 红绿灯让位** | 检测到窗口控件在左侧时**强制整行宽的标签行**放在最顶上（注释明说：标签行只占 rest-pane 的话给不出位置，红绿灯会画到启动栏上）— `$T/layouts/desktop_layout.tsx:71-77,83-95`；让位靠 `#tab-row-left-spacer { width: env(titlebar-area-x) }` — `$T/stylesheets/style.css:2342-2360` | Electron 用 `titleBarStyle: 'hiddenInset'`（`desktop/src/main.ts:49`），我们只在**53px 宽的启动栏顶部**留了 22px 高的空位 — `$M/shell.css:107` + `$M/App.tsx:1698`。红绿灯横向约 70px > 53px，**右边那截压在左栏搜索框上** | **严重** | 两条路二选一：(a) 照 Trilium 把标签行提到最顶、整行宽、左侧留 `env(titlebar-area-x)`；(b) 保持现结构但把 `.left-pane` 顶部也加同高的让位条。(a) 顺带解决「左栏顶部不能拖窗口」 |
| 中栏圆角 | `--center-pane-border-radius: 10px` — `$T/stylesheets/theme-next/base.css:60`；只作用于 note-split 的**起始上角**，左栏折叠时归零 — `$T/stylesheets/theme-next/shell.css:121-127,1354-1362` | 无 | 细节 | `.note-pane` 加 `border-start-start-radius: 10px`（左栏收起时置 0） |
| 正文左右边距 | `--content-margin-inline: 24px` — `$T/widgets/containers/scrolling_container.css:1-11` | `padding: 14px` — `$M/App.tsx:1789` | 细节 | 提成变量 `--content-margin-inline: 24px` |
| **标题行是否随正文滚走** | `title-row` 是 `ScrollingContainer` 的**兄弟**，固定在滚动区之上；`height/min-height: 50px; align-items: center` — `$T/layouts/desktop_layout.tsx:135-146,150-164`、`$T/stylesheets/style.css:3047-3051` | 标题 input 在 `.note-pane`（`overflow-y:auto`）**内部**的 padding div 里，跟正文一起滚走 — `$M/App.tsx:1772,1789,1804-1809` | **明显** | 把标题 + AI 动作行提出滚动容器，做成固定 50px 的 title-row |
| 标题字号 | `--note-title-size: 180%`（新布局 18px），`padding-inline: 12px`，`line-height: 1` — `$T/widgets/note_title.css:1-20,69-72` | `fontSize: 20, fontWeight: 600, padding: '4px 0'` 内联 — `$M/App.tsx:1808` | 细节 | 提到 CSS，用 `--note-title-size` |
| 状态栏高度 | `min-height: 28px`，`font-size: .85em`，`padding-inline: .25em`，背景走 `--left-pane-background-color`，上边框 `--status-bar-border-color` — `$T/widgets/layout/StatusBar.css:4-14` | `height: 24px`, `font-size: 11px`, `padding: 0 10px`，背景走 `--launcher-bg` — `$M/shell.css:164-170` | 细节 | 高度 28px；背景改左栏色（状态栏在视觉上是左栏的延伸，不是启动栏的） |
| 滚动条样式 | `--scrollbar-thickness: 10px`、`--scrollbar-thumb-thickness: 3px`（hover 6px）、两端各留 8px 空隙；thumb 用渐变 padding 模拟细条 — `$T/stylesheets/theme-next/forms.css:962-1044` | 6 个 `overflow-y: auto` 容器全走系统默认滚动条，无任何样式 | **明显** | 抄 `forms.css:962-1044` 那 80 行（纯样式，不依赖它的 DOM） |

---

## 2. 树

| 维度 | Trilium 怎么做 | 我们现在 | 等级 | 建议 |
|---|---|---|---|---|
| **拖拽移动/克隆** | fancytree `dnd5`：`autoExpandMS: 600`；drop 前/后/内分别调 `moveBeforeBranch` / `moveAfterBranch` / `moveToParentNote` — `$T/widgets/note_tree.ts:391,524-526,615-623`。拖进来的**文件直接导入成笔记** — `$T/widgets/note_tree.ts:584-596` | 完全没有 dnd（`NoteTree.tsx` 里无 `draggable` / `onDrop`）。只能走右键「移动到…」，而那背后是 `window.prompt` 让用户**输序号**（`$M/App.tsx:336-350`） | **明显** | HTML5 dnd 够用：`draggable` + `dragover` 按行内 y 分三段（上 25% = before / 下 25% = after / 中间 50% = over），600ms 悬停自动展开。后端 `PATCH .../move` 端点已经有了 |
| 拖拽视觉反馈 | drop-over 目标 `border: 1px solid var(--main-border-color)` — `$T/stylesheets/tree.css:270-272`；before/after 是一条 100px 宽、2px 高、圆角 1px 的 `--muted-text-color` 线，起点带 8×8 中空圆环（`border: 2px solid`）— `$T/stylesheets/tree.css:274-327`；线的垂直偏移由 JS 实测行高写进 CSS 变量 — `$T/widgets/note_tree.ts:1997-2008` | 无 | **明显** | 跟上一条一起做，照抄那条线 + 圆环的画法 |
| **键盘导航** | `titlesTabbable: true`、`keyboard: true`、`minExpandLevel: 2` — `$T/widgets/note_tree.ts:388-389,398`；note-tree scope 挂了一整套：`Delete` 删除、`Enter` 改标题、`F2` 改分支前缀、`Alt+↑/↓` 上下移、`Alt+←/→` 升降级、`⌘C/V/X` 剪贴板、`⌘A` 选中同级全部、`Shift+↑/↓` 扩选 — `$TS/services/keyboard_actions.ts:150-267` | `.tree-node` 是个只有 `onClick` 的 `div`，**没有 `tabIndex`**，Tab 进不去，上下键无反应 — `$M/components/NoteTree.tsx:94-107` | **严重** | 至少补：容器 `tabIndex=0` + roving `tabindex`，↑/↓ 移动、←/→ 收展、Enter 打开、Delete 删除。这是「键盘用户完全用不了树」级别的问题 |
| 多选 | Shift = 区间选、Ctrl = 新标签打开、Alt = 切换选中 — `$T/widgets/note_tree.ts:412-452`；选中态用 `::after` 伪元素（`z-index:-2`，100ms 入场动画），图标变勾选框 `\ef05` — `$T/stylesheets/theme-next/shell.css:763-779`、`$T/stylesheets/tree.css:215-220` | 无多选 | 细节 | 优先级低于键盘导航。真要做时注意：Trilium 的右键菜单**不因多选而增删项，只把单笔记语义的项置灰**（见第 6 节） |
| 缩进 | **每级 10px**（`:is(#left-pane,…) .ui-fancytree ul { padding-inline-start: 10px }`）— `$T/stylesheets/theme-next/shell.css:716-718`；根节点额外 `padding-inline-start: 12px` — `shell.css:721-723`。基础样式里的 20px 被主题覆盖了 | 每级 16px（`paddingInlineStart: 4 + depth*16`）— `$M/components/NoteTree.tsx:100` | 细节 | 改成 `12 + depth*10` |
| 行高 / 圆角 | `height: 2.4em; padding: 4px` — `$T/stylesheets/tree.css:30-44`；主题把圆角改成 **6px**（`border: unset; border-radius: 6px; cursor: default`）— `$T/stylesheets/theme-next/shell.css:710-714` | `height: 2.4em; padding: 4px; border-radius: 5px` — `$M/styles.css:431-438` | 细节 | 圆角 5→6px；`cursor` 我们用 `pointer`，Trilium 用 `default`（这个不用改，pointer 更符合直觉） |
| **激活态画法** | 背景由 `::before` 伪元素画（本体 transparent），四边内缩 `--left-pane-item-selected-shadow-size: 2px`，`border-radius: 6px`，`box-shadow: var(--left-pane-item-selected-shadow)`，入场 `left-pane-item-select 200ms ease-out`；**标题不加粗**（`font-weight: normal`，主题特意取消了基础样式的 bold）— `$T/stylesheets/theme-next/shell.css:725-761,831-833` | `background: var(--bg)` + `box-shadow: inset 2px 0 0 var(--accent)` 左竖条 + 标题染 accent 色 + `font-weight: 500` — `$M/styles.css:440-441` | **明显** | 两套观感完全不同：Trilium 是「浮起来的白卡片」，我们是「左边一道蓝杠」。**顺带一个 bug**：`shell.css:30-33 / 66-69` 定义的 `--left-pane-item-selected-bg/-fg/-shadow/-hover-bg` 四个令牌**全仓 0 处引用**，抄来的 Trilium 树配色根本没生效 |
| hover 态 | `background: var(--left-pane-item-hover-background)`（亮 `rgba(0,0,0,.032)` / 暗 `#ffffff0d`）— `$T/stylesheets/theme-next/shell.css:835-837` | `background: var(--bg)`（= `--accented-bg`，暗色 `#555`）— `$M/styles.css:439` | **明显** | 用上那两个死掉的令牌；现在暗色下 hover 是一大块 `#555` 中灰，太重 |
| **图标** | 每行一个图标：`.fancytree-custom-icon { width:1em; height:1em; font-size:1.2em }`，与标题间距 7px — `$T/stylesheets/tree.css:144-151,18`；默认 `bx bx-note`，**有子节点自动变 `bx bx-folder`** — `packages/commons/src/lib/notes.ts:140-143`；图标色 `--left-pane-icon-color`（暗色单独提亮到 `#c5c5c5`）— `$T/stylesheets/theme-next/shell.css:826-829` | 没有图标 — `$M/components/NoteTree.tsx:108-122` | **明显** | 至少加「叶子 = 文档 / 有子节点 = 文件夹」两个字形。我们的树没有类型区分，但**有 harness 状态**——图标位正好能表达「这篇正在被续写 / 有待处置的修订」，这是判据 3（自动化过程看得见）的一个免费落点 |
| 展开箭头 | boxicons `\ea50`（chevron-right）→ 展开换成 `\ea4a`（chevron-down），**换字符不旋转**，`font-size: x-large`，`margin-inline-end: 5px` — `$T/stylesheets/tree.css:52-62,109-112`；叶子节点把颜色设成背景色「隐形占位」— `tree.css:104-107`；hover 透明度 `.65 → 1`，进 150ms / 出 300ms — `$T/stylesheets/theme-next/shell.css:814-824` | `▾` / `▸` 文本字符，`width: 14px`，`font-size: 10px`，无过渡 — `$M/components/NoteTree.tsx:113` + `$M/styles.css:443-449` | 细节 | 换成同一套 chevron 字形（或 SVG），补 hover 的 opacity 过渡。**我们让叶子占同宽是对的**，跟 Trilium 一个思路 |
| 展开时的 loading 态 | expander 变成 16×16 容器里的 12×12 双环 spinner，`lds-dual-ring 1.2s linear infinite` — `$T/stylesheets/tree.css:68-98` | 无（我们一次拿全树，不懒加载） | — | 不需要 |
| 克隆标记 | 标题尾部追加 `.note-indicator-icon.clone-indicator`，字符 `\eb3d`（bx-link-alt），`font-size: smaller; margin-inline-start: 4px; opacity: .8; cursor: help` — `$T/stylesheets/tree.css:164-183`；tooltip 分「2 个父」和「N 个父 + 父标题列表」两种文案 — `$T/widgets/note_tree.ts:1952-1961`。另外 fancytree `clones: { highlightActiveClones: true }`，**当前笔记的其它克隆位置整行加粗** — `$T/widgets/note_tree.ts:663-665`、`$T/stylesheets/tree.css:185-187` | `⧉` 字符 + `title="这篇笔记同时在 N 个位置"` — `$M/components/NoteTree.tsx:116-121` | 细节 | 我们的做法在语义上够了。**唯一值得补的是 `highlightActiveClones`**：打开一篇克隆笔记时，把它在树上的**其它位置**也加粗——不然用户改了一处，不知道另外哪几处跟着变了 |
| 行内 hover 操作按钮 | hover 出现「+ 新建子笔记」（`bx bx-plus`，class `tree-item-button add-note-button`），另有进入工作区 / 取消 hoist / 刷新搜索三个 — `$T/widgets/note_tree.ts:1875-1941`、`$T/stylesheets/tree.css:239-268`；theme-next 做成圆形（`border-radius: 50%`，`margin-inline-end: 6px`，背景 `--left-pane-item-action-button-background`，200ms 过渡）— `$T/stylesheets/theme-next/shell.css:843-867` | 无。新建子笔记只能走右键菜单 — `$M/App.tsx:276` | **明显** | 加一个 hover 才出现的圆形「＋」。建笔记是最高频动作，藏在右键里成本太高 |
| 底部浮动工具条 | 三个按钮：折叠全树 `bx bx-layer-minus`、**滚动到当前笔记** `bx bx-crosshair`、树设置 — `$T/widgets/note_tree.ts:113-121`；默认收起成 40px 圆钮（`--tree-actions-toolbar-collapsed-width`），hover 展开到 `max-width: 200px`，`400ms ease-out` — `$T/stylesheets/theme-next/shell.css:908-981`、`base.css:50-54` | 无 | **明显** | 「定位到当前笔记」这个按钮我们尤其需要——克隆意味着同一篇在树上有多处，用户会找不到自己在哪儿 |
| 当前笔记自动滚入视图 | `scrollOfs: { top: 100, bottom: 100 }`，`scrollParent: this.$tree` — `$T/widgets/note_tree.ts:393-397`；受 option `treeScrollFollowNavigation` 控制，关掉时在 `beforeActivate` 里临时把 `activeVisible` 设 false 再用 `setTimeout(...,0)` 还原（只影响这一次）— `$T/widgets/note_tree.ts:478-487` | 无——切换笔记后树不动，激活行可能在视口外 | **明显** | 切笔记时 `element.scrollIntoView({ block: 'nearest' })`，上下各留 100px 余量 |
| 自动折叠 | 无操作 **600 秒**后，折叠所有不在当前标签路径上的节点，并弹一次 toast 说明；只读库跳过 — `$T/widgets/note_tree.ts:1232-1273` | 无 | — | 不建议抄。我们的树规模远小于 Trilium，自动收树只会让人找不到东西 |
| 标题截断 tooltip | 只在文字**真被截断**时才设 `title`（用 `isEnclosing` 判断），避免无谓的悬浮框 — `$T/widgets/note_tree.ts:329-353` | 从不设 `title`（截断了也看不到全名）— `$M/components/NoteTree.tsx:115` | 细节 | 抄这个判断，值得 |
| 空标题回退 | 无此机制 | 标题为占位词时退回正文首行，**只在显示层做** — `$M/components/NoteTree.tsx:30-45` | — | 我们的做法更好，保留 |

### 快速搜索

| 维度 | Trilium 怎么做 | 我们现在 | 等级 | 建议 |
|---|---|---|---|---|
| 位置 | 左栏容器内、树之上（仅竖版布局插入）— `$T/layouts/desktop_layout.tsx:103-105` | 位置一致 — `$M/App.tsx:1726-1732` | — | ✅ |
| 触发时机 | **没有防抖**：只在按 Enter 或下拉打开时搜 — `$T/widgets/quick_search.ts:193,222-230` | `setTimeout(200)` 防抖，边打边搜 — `$M/App.tsx`（`noteQuery` 走 `visibleNotes` 过滤） | — | 我们边打边搜更好，保留 |
| 结果呈现 | Bootstrap 下拉浮层：`max-height: 80vh; min-width: 400px; max-width: 720px`，图标 + 高亮标题 + 属性摘要 + 内容摘要（`margin-top:8px; padding:8px; font-size:.85em`），首屏 15 条、滚到底再加 10 条 — `$T/widgets/quick_search.ts:25-52,82-120,141-142,389-407` | 直接**在树的位置**渲染扁平结果列表 — `$M/App.tsx:1735-1739` | 细节 | 我们的做法（搜索时不画树）其实更直白，注释里的理由成立。**唯一该补的是命中高亮**：Trilium 精确匹配 `<b>` 加下划线、模糊匹配 `#e47b19` 点线 — `$T/widgets/quick_search.ts:105-120` |
| 输入框样式 | 背景矩形走 `::before` 伪层，`border-radius: 6px`，2px 透明边，hover / focus 各有专属令牌（`--quick-search-hover-background` / `--quick-search-focus-*`），75ms / 100ms 过渡；搜索按钮 25×25 圆形，`:active { transform: scale(.85) }` — `$T/stylesheets/theme-next/shell.css:561-640` | 走全局 `input` 规则（`$M/styles.css:79`），**全仓没有任何 `:focus` / `:focus-visible` 样式**（唯一一条是 `styles.css:212` 的 `.palette input:focus { outline: none }`，只做减法）→ 只剩浏览器默认焦点环 | 细节 | 补 `--input-focus-outline-color` + `:focus-visible` 一条。`.palette input` 那条 `outline:none` 没有替代样式，**键盘用户在命令面板里看不到焦点在哪**，这本身就是可访问性缺陷 |
| 键盘 | `↓` 进结果列表、`Esc` 关、结果里 `↑` 回输入框 — `$T/widgets/quick_search.ts:232-238,423` | 无 | 细节 | 补 `↓` / `Esc` |

---

## 3. 标签页

Trilium 的实现在 `$T/widgets/tab_row.ts`（**不是** `.js`），我们的在 `$M/components/TabBar.tsx`。

| 维度 | Trilium 怎么做 | 我们现在 | 等级 | 建议 |
|---|---|---|---|---|
| **放不下时怎么办** | 标签宽度 `clamp(100, 240)`，装不下就**扣掉左右两个 36px 滚动按钮并显形**（`bx bx-chevron-left/right`，每次滚 ±210px），另外支持鼠标滚轮横向滚动 — `$T/widgets/tab_row.ts:19-24,520-557,227-257,325-329,424-466` | 一路缩到 48px 下限，`.tab-strip { overflow: hidden }` — `$M/components/TabBar.tsx:17-41` + `$M/shell.css:221-224`。**标签再多就直接看不见也点不到** | **严重** | 两选一：(a) 抄滚动按钮；(b) 保持缩窄但把下限提到 84px 并让 strip `overflow-x: auto`（配 `scrollbar-width: none`）。(b) 改动小得多 |
| 宽度区间 | `TAB_CONTAINER_MIN_WIDTH = 100`、`MAX = 240` — `$T/widgets/tab_row.ts:19-20`；分档常量 `TAB_SIZE_SMALL = 84 / SMALLER = 60 / MINI = 48` 写成 `is-small` / `is-smaller` / `is-mini` 属性 — `tab_row.ts:26-28,585-591` | `MAX_W = 240`、`MIN_W = 48`，**没有分档**，只是线性缩到 48 — `$M/components/TabBar.tsx:17-19,40` | **明显** | 加回三档，用 `data-size` 属性驱动样式（关闭按钮显隐、内边距都靠它） |
| 标签间距 | `MARGIN_WIDTH = 5`（纯间隙，**没有重叠、没有 SVG 背景、没有分隔线**）— `$T/widgets/tab_row.ts:24,565` | `gap: 2px` — `$M/shell.css:222` | 细节 | 改 5px（宽度算法里也要扣 `(n-1)*5`，Trilium 在 `tab_row.ts:536-538` 就是这么算的） |
| 标签高度 / 圆角 | 36px（`--tab-height`），`padding: 7px 5px 7px 11px`，`border-radius: 8px`（四角全圆，横版布局才把下面两角拉直）— `$T/widgets/tab_row.ts:136-152`、`$T/stylesheets/theme-next/shell.css:1174-1189` | `height: 30px`，`padding: 0 8px`，`border-radius: 6px 6px 0 0` — `$M/shell.css:228` | **明显** | 36px + 全圆角 8px。我们的「上圆下方」是浏览器标签的画法，Trilium 竖版布局是「悬浮的胶囊」 |
| 激活态 | `--active-tab-background-color` + `box-shadow: var(--active-tab-shadow)`（亮 `3px 3px 6px rgba(0,0,0,.1), -1px -1px 3px rgba(0,0,0,.05)`），**主题特意取消了加粗**改用阴影表达抬升 — `$T/widgets/tab_row.ts:122-124`、`$T/stylesheets/theme-next/shell.css:1222-1228`、`theme-next-light.css:203` | 纯色块，无阴影 — `$M/shell.css:233` | 细节 | 补 `--active-tab-shadow` 令牌 |
| 非激活文字色 | 专属令牌 `--inactive-tab-text-color`（亮 `#4e4e4e` / 暗 `#7c7c7c`）— `theme-next-light.css:208` / `dark:216` | 复用 `--launcher-fg`（暗 `#909090`，比 Trilium 亮 8%）— `$M/shell.css:229` | 细节 | 加专属令牌，否则激活/非激活的对比被削弱 |
| 关闭按钮 | 22×22 圆形（`border-radius: 50%`，`z-index: 100`），**始终显示**；`is-smaller` 时 `margin-inline-start: auto` 右推；**只有 `is-mini` 且非激活时才 `display: none`**（激活的 mini 标签把叉居中显示）— `$T/widgets/tab_row.ts:37,197-205,272-281` | 16×16，`opacity: .45`（hover `.8`），容器窄于 90px 就整个隐藏（**不分激活与否**）— `$M/shell.css:238-250` | 细节 | 尺寸 22px；隐藏规则改成「窄 **且** 非激活」——当前标签的叉不该消失 |
| 中键关闭 | `mousedown` 且 `e.which === 2` — `$T/widgets/tab_row.ts:661-667` | 有（`onAuxClick`，`e.button === 1`）— `$M/components/TabBar.tsx:55` | — | ✅ |
| 新建按钮 | 外框 36×36（`flex: 0 0 36px`），主题里用 `::before` 画 24px 圆底 + `::after` 画字形，hover 换色 + 阴影，`:active { scale(.85) }` — `$T/widgets/tab_row.ts:83-98`、`$T/stylesheets/theme-next/shell.css:1249-1313`；**不跟随最后一个标签**，是 strip 之外的 flex 兄弟 — `tab_row.ts:892-903` | 26×26，`＋` 字符 — `$M/shell.css:252-257`；在 strip **里面**（会被 overflow 裁掉）— `$M/components/TabBar.tsx:72` | 细节 | 挪出 strip，外框 36px / 内圈 24px |
| 标签行末尾拖动区 | `.tab-row-filler`：`-webkit-app-region: drag`，`min-width: 50`（桌面），`flex-grow: 1` — `$T/widgets/tab_row.ts:44,100-105` | `.tab-bar` 整体是 drag 区，但 strip 占满剩余空间（`flex: 1`），**标签一多就没有空白可拖** — `$M/shell.css:142`、`$M/shell.css:223` | 细节 | 给 strip 后面补一个 `min-width: 50px` 的 filler |
| **拖拽排序** | Draggabilly，`axis: "x"`，透明的 `.note-tab-drag-handle` 盖住整个标签（`z-index: 50`，关闭按钮在其上 `z-index: 100`）；交换动画 **120ms ease-in-out**；拖到边缘自动滚动，步长 105px；**竖向拖出 100px 以上 → 新开窗口** — `$T/widgets/tab_row.ts:2,188-205,302-305,758-784,839-877` | 无 | **明显** | 至少做同行内排序（HTML5 dnd 足够），120ms 交换动画。「拖出新窗口」不急 |
| 新标签入场动画 | `note-tab-was-just-added`：从 `top: 10px` 落到 0，**120ms** — `$T/widgets/tab_row.ts:131-134,282-301,612-614` | 无 | 细节 | 12 行 CSS，值得抄 |
| **标签右键菜单** | 9 项（`$T/widgets/tab_row.ts:377-416`）：固定/取消固定、关闭、关闭其他（只剩 1 个时禁用）、关闭右侧（末位禁用）、关闭全部、**重新打开刚关的**（无记录时禁用）、移到新窗口（固定时禁用）、复制到新窗口 | `TabBar` 收了 `onContextMenu` 这个 prop，但 `App.tsx:1758-1770` **压根没传**——右键菜单是死代码 | **明显** | 至少接上「关闭其他 / 关闭右侧 / 重新打开刚关的」三项。禁用时按我们的习惯带原因 |
| 标签图标 | 主题能力开关 `--tab-note-icons: true`（`theme-next/base.css:101`），开启时用笔记自身图标，`padding-inline-end: 5px` — `$T/widgets/tab_row.ts:362-363,996-1035`、`$T/stylesheets/theme-next/shell.css:1205-1207` | 无 | 细节 | 跟树图标一起做 |
| 未保存标记 | **Trilium 没有**（grep 无命中）。新布局里改用标题行的 `save-status-badge`：保存后 5s 淡出，出错时变红且不淡出 — `$T/widgets/layout/NoteBadges.css:28-45` | 无（我们是自动保存 + 一个「保存」按钮）— `$M/App.tsx:1886` | 细节 | 抄 `save-status-badge` 比留一个「保存」按钮好：自动保存的产品里，按钮暗示「不点就没存」 |
| 工作区色条 | 激活标签顶部 3px 色条：`.note-tab-wrapper::after { top:0; height:3px; background: var(--workspace-tab-background-color) }` — `$T/stylesheets/theme-next/shell.css:1191-1203` | 无（我们没有工作区概念） | — | 不需要。**但这个 3px 色条的位置很适合表达「这个标签的 harness 正在跑」** |
| 复合标题（分屏时） | 多个 split 的标题用 `" • "` 连接，当前 split 高亮、其余 `opacity: .55` — `$T/widgets/tab_row.ts:173-177,1042-1072` | 无分屏 | — | 分屏做了再说 |
| 标签 tooltip | 挂在 drag-handle 上，`delay: 500ms`，`placement: bottom` — `$T/widgets/tab_row.ts:626-639` | 用原生 `title`，且带 `⌘N` 提示 — `$M/components/TabBar.tsx:51` | — | 我们带快捷键提示更好，保留 |

---

## 4. Ribbon

| 维度 | Trilium 怎么做 | 我们现在 | 等级 | 建议 |
|---|---|---|---|---|
| **默认展开与否** | 每次换笔记时取**第一个 `shouldShow && activate` 为真的 tab** 自动展开；都不满足才收起 — `$T/widgets/ribbon/Ribbon.tsx:46-51`；`activate` 可以是函数 — `$T/widgets/ribbon/ribbon-interface.ts:29` | `useState(defaultOpen)`，`App.tsx` **没传 `defaultOpen`** → 永远默认收起 — `$M/components/Ribbon.tsx:33`、`$M/App.tsx:1794-1808` | **严重** | 这条直接违反判据 3（「计划要看得见」）。写作骨架有内容（`beats.length > 0`）时**必须默认展开**——一个折叠起来的计划，跟一个转圈的指示器没区别。`Ribbon.tsx` 加一个 `activate?: boolean \| (() => boolean)` 字段照抄它的规则 |
| 展开状态持久化 | **不持久化**（纯组件 state），换笔记按上面的规则重算 — `$T/widgets/ribbon/Ribbon.tsx:23` | 同样不持久化 | — | ✅ 一致 |
| tab 按钮样式 | **默认只显示图标，激活时才追加文字**（`{active && <span class="ribbon-tab-title-label">}`）— `$T/widgets/ribbon/Ribbon.tsx:141`、`Ribbon.css:91-93`；图标 `font-size: 150%` — `Ribbon.css:41-44`；**无圆角**，非激活 `border-bottom: 1px solid var(--main-border-color)`，激活 `color: var(--main-text-color)` + **`border-bottom: 3px solid`（下划线，不是胶囊）** — `Ribbon.css:27-52` | 图标 + 文字常显，`border-radius: 6px` 胶囊，激活 `background: var(--accented-bg)` — `$M/shell.css:181-188` | 细节 | 两套观感都成立。真要对齐就换成 3px 下划线——好处是暗色下不会像现在这样出现一块 `#555` 的亮斑（`--accented-bg` 暗色值是 `#555`，作为激活底色偏亮） |
| tab 排布 | `.ribbon-tab-container { margin-inline-start: 10px; flex-flow: row wrap; justify-content: center }`，tab 之间夹 `.ribbon-tab-spacer`（`max-width: 35px`，最后一个 `10000px` 吃掉剩余）— `$T/widgets/ribbon/Ribbon.css:18-25,66-79` | `.ribbon-strip { gap: 2px; padding: 4px 6px; flex-wrap: wrap }`，靠左 — `$M/shell.css:180` | 细节 | Trilium 是**居中**的，我们靠左。只有 1 个 tab 时无所谓 |
| 高度 / 边距 | `.ribbon-top-row { min-height: 36px }` — `Ribbon.css:13-16`；`.ribbon-container { margin-bottom: 5px }`，但 **theme-next 改成 `margin-bottom: 0 !important`** — `$T/stylesheets/theme-next/shell.css:1388-1390`；`.ribbon-body { border-bottom: 1px solid; margin-inline: 10px 5px }` — `Ribbon.css:81-85` | 无 min-height；`.ribbon { border-bottom }`，`.ribbon-body { padding: 6px 12px 12px }` — `$M/shell.css:179,194` | 细节 | 加 `min-height: 36px`，否则 tab 少时这条带子会随内容抖动 |
| 角标 | **ribbon tab 上没有任何数量角标**（`Ribbon.tsx` / `Ribbon.css` 全无 badge 代码）；新布局的 `<NoteBadges />` 属于标题行不属于 ribbon — `$T/layouts/desktop_layout.tsx:140` | 有 `ribbon-badge`（节拍数）— `$M/components/Ribbon.tsx:50-52` | — | **我们的加法更好，保留**。收起时也能看见「骨架有 7 个节拍」，正是判据 3 要的 |
| tab 数量 | 14 个内置 tab — `$T/widgets/ribbon/RibbonDefinition.ts:19-125` | 1 个（写作骨架）— `$M/App.tsx:1794-1808` | **明显** | 我们不需要它那 14 个中的大多数，但有两个**语义上就该在 ribbon** 的：**① 笔记路径**（`NotePathsTab`，`RibbonDefinition.ts:97-103`）——我们有克隆，一篇笔记同时在多处，用户必须能看到「它还长在哪儿」；**② 笔记信息**（`NoteInfoTab`，`:118-124`）——创建/修改时间、字数 |
| ribbon 右侧的动作菜单 | `<NoteActions />` 三点菜单（35×35）在 tab 条右端 — `$T/widgets/ribbon/Ribbon.tsx:92`、`NoteActions.css:1-15`；含 笔记内查找 / 附件 / 导入 / 导出 / 打印 / 修订历史 / 命名修订 / 外部打开 / 查看源码 — `$T/widgets/ribbon/NoteActions.tsx:138-206` | 导出 / 复制 / 专注模式散在正文上方的 `toolbar-secondary` 行里 — `$M/App.tsx:1885-1892` | **明显** | 把这些低频动作收进 ribbon 右端的三点菜单。**判据 1 说「AI 能力一个按钮」，反过来也成立：非 AI 的杂项不该跟 magic tap / 智能续写 抢同一行的注意力** |

---

## 5. 右栏

Trilium 的新布局右栏在 `$T/widgets/sidebar/RightPanelContainer.{tsx,css}` + `RightPaneTabs.tsx`。

| 维度 | Trilium 怎么做 | 我们现在 | 等级 | 建议 |
|---|---|---|---|---|
| 标签条形态 | `TabStrip` 是**图标-only 的分段按钮组**（`btn-group`，凹槽底 + 凸起激活段），`--icon-button-size: 26px`，`gap: 2px`，`padding: 2px`，`justify-content: safe center`，放不下时**自己横向滚动**（`scrollbar-width: none`）— `$T/widgets/react/TabStrip.css:1-58` | 文字标签，`border-radius: 6px 6px 0 0`，激活 `background: var(--accented-bg)`，不滚动 — `$M/shell.css:201-212` | 细节 | 我们的标签名是中文词（目录 / 运行 / 修订 / 来龙去脉 / 知识库），纯图标反而认不出。**保留文字，但补 `overflow-x: auto` + `scrollbar-width: none`**——5 个中文标签在 300px 宽的栏里已经很挤，栏一窄就会溢出 |
| 标签条所在的头部行 | `.right-pane-header`：固定 `--right-pane-header-height: 34px`，`flex-shrink: 0`，下边框 1px；用 `::before { flex: 1 1 0 }` 做配重让标签组**居中**；右端是 `.right-pane-actions`（钉住 / 关闭，`--icon-button-size: 24px`，`min-width: max-content` 保证任何宽度下按钮都完整可点）— `$T/widgets/sidebar/RightPanelContainer.css:9,110-145` | `.right-pane-tabs { padding: 6px 8px 0 }`，无固定高度，无右端动作区 — `$M/shell.css:201-204` | **明显** | 固定 34px；右端加「折叠右栏」按钮 |
| 内容分区 | 每个 tab 里是若干 `.card`，**可折叠**（`.card-header` 有 chevron，`.collapsed` 时 `rotate(-90deg)`）；只有一个 widget 的 tab 不给 chevron（`.not-collapsible`）— `$T/widgets/sidebar/RightPanelContainer.css:148-219` | 每个 tab 一整块内容，不分区不可折叠 | 细节 | 「运行」面板迟早会长（每轮的判据 + 丢弃的修订），到时候需要按轮折叠 |
| 多分区共享高度 | 一个 tab 里多个 card 同时展开时，各自 `flex: 1 1 0; max-height: max-content` —— 内容少的 card 把用不完的高度**还回去**再分给内容多的，而不是每个都被裁一点；指定 `grow` 的 card 有 `--right-pane-grow-min-height: 110px` 的地板 — `$T/widgets/sidebar/RightPanelContainer.css:236-323`（配了 60 行注释解释为什么） | 无（单块内容） | — | 做了分区再说，但这套算法值得照抄 |
| 被外部指向时的定位反馈 | `.card.highlighted::after` 一层 1s 淡出的高亮遮罩（`right-pane-widget-highlight`），因为「一个 tab 里的各段长得很像，滚过去可能只挪了几像素」— `$T/widgets/sidebar/RightPanelContainer.css:191-211,334-338` | 无 | 细节 | 我们从正文的行内出处点进「来龙去脉」时正好需要这个 |
| peek（浮层）模式 | 右栏能从停靠切成**浮在正文之上**：绝对定位、`right-pane-peek-in 200ms`、`backdrop-filter: blur(12px) saturate(1.5)`、`--peek-pane-shadow-depth: 42px`、点空白（spacer）关掉；关掉时内容**不卸载**，再打开是瞬时且保状态的 — `$T/widgets/sidebar/RightPanelContainer.css:1-13,58-93`；对应 action `peekRightPane` — `$TS/services/keyboard_actions.ts:746-753` | 无 | 细节 | 优先级低于「可调宽 + 可折叠」 |
| 常驻区 | 无（Trilium 右栏全是标签） | `.right-pane-ambient { max-height: 42%; overflow-y: auto }` 常驻「相关记忆」— `$M/shell.css:197-200` | — | **有意分歧，保留**（理由见判据 2 与 `RightPane.tsx:1-20`）。但 42% 是个魔法数字，建议改成可拖的分割（Trilium 的 `.gutter-vertical` 在右栏内部就是干这个的 — `RightPanelContainer.css:325-327`） |
| `alwaysShown` | 有内容才显示的 tab 会随笔记切换而进出，导致「标签在鼠标下面跑掉」，所以给了 `alwaysShown` 让它留在条上、在内容区说明为什么是空的 — `$T/widgets/sidebar/RightPaneTabs.tsx:7-14,21-32` | 抄了 `alwaysShown`，但**空 tab 的内容区不说明原因** — `$M/components/RightPane.tsx:27-31` | 细节 | 空态给一句话（「这篇还没有修订记录」），别留白 |
| 死代码 | — | `.right-pane-heading`（`$M/shell.css:156-160`）和 `.left-pane-body`（`:130`）**全仓 0 处引用** | 细节 | 要么用起来（见 1.2），要么删掉——留着会让下一个人以为已经有了 |

---

## 6. 右键菜单

**先说三条我们比 Trilium 强的**（不要「对齐」回去）：

1. **Esc 关闭**：Trilium 的 context menu **完全没有键盘支持**——`$T/menus/` 全目录 grep 无 `keydown` / `Escape` / `tabindex`，没有上下键选择、没有 Esc、没有 Enter。我们有 Esc（`$M/components/ContextMenu.tsx:46`）。
2. **禁用项给原因**：Trilium 有 `.dropdown-menu .disabled .contextual-help` 的样式钩子（`$T/stylesheets/style.css:510-521`），但**没有任何构造代码往禁用项里塞它**——树菜单的禁用项只是变灰。我们用 `hint` 字段说明原因（`$M/App.tsx:287-296`），这正是判据 1「禁用时也要说清为什么」。
3. **贴边处理**：Trilium 主菜单是**钳制**（clamp 到距边 5px），只有子菜单才翻转 — `$T/menus/context_menu.ts:155-201,203-232`。我们也是钳制（`ContextMenu.tsx:34-43`），一致。

| 维度 | Trilium 怎么做 | 我们现在 | 等级 | 建议 |
|---|---|---|---|---|
| 菜单圆角 / 内边距 / 字号 | `--dropdown-border-radius: 10px`，`padding: var(--menu-padding-size)` = **8px**，`font-size: 0.9rem` — `$T/stylesheets/theme-next/shell.css:12`、`theme-next/base.css:77,153-155` | `border-radius: 8px`，`padding: 4px`，`font-size: 13px` — `$M/styles.css:468-474` | 细节 | 圆角 10px、内边距 8px |
| 菜单毛玻璃 | `::before` 伪层 `backdrop-filter: blur(20px) saturate(6)`，背景 `--menu-background-color`（亮 `white` / 暗 `#222222d9`，**带 alpha**）— `$T/stylesheets/theme-next/base.css:174-187` | 实色 `var(--panel)` — `$M/styles.css:472` | 细节 | 抄毛玻璃 + 半透明底 |
| 菜单阴影 | `0 10px 20px rgba(0,0,0,var(--dropdown-shadow-opacity))`，**opacity 亮 0.2 / 暗 0.6** — `$T/stylesheets/style.css:482`、`theme-next-dark.css:23` | `0 8px 28px rgba(0,0,0,.18)` 亮暗同值 — `$M/styles.css:473` | 细节 | 引入 `--dropdown-shadow-opacity` 令牌（这条对整个应用的所有阴影都成立，见第 8 节） |
| 菜单项 padding / 圆角 | 纵 2px、起始 8px、**结束 22px**（给子菜单箭头留位），`border-radius: 6px` — `$T/stylesheets/theme-next/base.css:225-241` | `padding: 6px 8px`，`border-radius: 5px` — `$M/styles.css:475-480` | 细节 | 圆角 6px |
| 图标槽 | 图标在前，与标题之间硬编码 `" &nbsp; "`；**无图标时也插 `&nbsp;` 占位**（文档建议用 `bx bx-empty`）— `$T/menus/context_menu.ts:317-334,44-48`；`translate: 0 -1px` 做视觉对齐 — `theme-next/shell.css:899-902` | `.cm-icon { width: 16px; text-align: center }` 恒占位 — `$M/styles.css:485` | — | ✅ 我们的做法更干净 |
| 快捷键提示 | `.keyboard-shortcut` `flex-grow: 1; text-align: end; padding-inline-start: 12px`，`margin-inline-start: 16px`；`<kbd>` 去边框去背景；macOS 把 `⌃⌥⇧⌘` 按 Apple 顺序**合并进一个 kbd**（`⇧⌘J`），非 mac 每个 token 一个 kbd 用 `+` 连 — `$T/menus/context_menu.ts:348-368`、`$T/stylesheets/style.css:560-575`、`packages/commons/src/lib/keyboard_shortcut_display.ts:110,198-200` | `.cm-hint { color: var(--muted); font-size: 11px }` — `$M/styles.css:486`；但 hint 现在装的是**说明文字**（「成为它的下一级」「同一篇，两处都能看到」）不是快捷键 — `$M/App.tsx:276,291` | 细节 | 分成两个字段：`hint`（说明，靠右淡色）和 `shortcut`（快捷键，`<kbd>` 样式）。用了 hint 装说明是对的——但两者混用一个槽位，以后加快捷键就撞了 |
| 分隔线 | `.dropdown-divider` 的边框设 transparent，真正的线用 `::after` 画并**向两侧各溢出 `--menu-padding-size`** 做通栏 — `$T/stylesheets/theme-next/base.css:316-331`；**连续 separator 自动去重**（`prevItemKind === "separator"` 时跳过）— `$T/menus/context_menu.ts:277-280` | `height: 1px; margin: 4px 6px`（**内缩**，不通栏），无去重 — `$M/styles.css:487` | 细节 | 改通栏 + 加去重。去重不是洁癖：我们的树菜单里 `disabled` 的项虽不消失，但将来一旦改成条件渲染就会出现连着两条线 |
| 分组标题 | `{ kind: "header" }` → `<h6 class="dropdown-header">`，大写 + `0.8em` + letter-spacing + 底部通栏线 — `$T/menus/context_menu.ts:283-285`、`theme-next/base.css:378-400` | 无 | 细节 | 我们的树菜单已经 5 组 13 项（`$M/App.tsx:270-301`），加分组标题（打开 / 新建 / **AI** / 组织 / 危险）比单纯分隔线更好读——尤其中间那组是我们独有的 harness 动作 |
| 子菜单 | 纯 CSS `:hover` 展开（`li.dropdown-submenu:hover > ul.dropdown-menu { display: block }`），定位 `inset-inline-start: calc(100% - 2px)`（那 `-2px` 是**刻意的**，防止父子间出现缝隙导致 hover 断掉），箭头用 `\ed3b` 字形；下边/右边放不下时加 `submenu-flip-up` / `submenu-flip-start`，且**翻过去装不下就不翻** — `$T/stylesheets/style.css:1714-1754`、`$T/menus/context_menu.ts:203-232`、`theme-next/base.css:334-369` | 无子菜单 | 细节 | 「插入子笔记」按类型分（Trilium `tree_context_menu.ts:173-181` 用 `columns: 2`）对我们意义不大——我们只有 markdown 一种笔记 |
| 菜单项禁用 | 只加 `.disabled` class，handler 照绑，靠 `pointer-events: none` 拦；theme-next 用 `opacity: var(--menu-item-disabled-opacity)`（暗色 0.5） — `$T/menus/context_menu.ts:412-414`、`theme-next/base.css:275-279` | `disabled` 属性 + `opacity: .4` — `$M/styles.css:482` | — | ✅ |
| 破坏性项 | `.destructive-action-icon` / `.bx-trash` 图标**自动染红** — `$T/stylesheets/theme-next/base.css:281-284` | `.context-menu-item.danger { color: var(--del) }`（整行染红）— `$M/styles.css:483` | 细节 | Trilium 只染图标不染文字。整行红在删除项上过于抢眼，建议只染图标 |
| 打开动画 | `dropdown-menu-opening` 100ms ease-in（仅 opacity）— `$T/stylesheets/style.css:438-445` | 无 | 细节 | 3 行 CSS |
| 打开时先收 tooltip | `note_tooltip.dismissAllTooltips()` + `body.addClass("context-menu-shown")`，供 tooltip 判断「菜单开着就别弹」— `$T/menus/context_menu.ts:106,118` | 无 | 细节 | 我们有 `.cm-fact-peek` 行内出处浮框，在正文里右键时会跟菜单叠 |
| 树菜单项数与分组 | 8 组 33 项 — `$T/menus/tree_context_menu.ts:108-355`。分组顺序：打开方式(6) → 新建(2) → 加密(2) → **Advanced 子菜单**(10) → 剪贴板/移动/删除(9) → 颜色选择器(custom) → 导入导出(2) → 子树内搜索(1) | 5 组 13 项 — `$M/App.tsx:270-301` | — | 数量不是目标。**该补的只有三个**：`copyNotePathToClipboard`（我们有克隆，路径是刚需——已有 ✅）、**「在新标签打开」**（Trilium `:143` 还带 `Ctrl+Click` 提示，我们有标签页却没这个入口）、**「排序子笔记」**（`:234-240`，我们的 harness 会往子树里塞很多篇） |
| 多选时菜单怎么变 | **不增删项，只把单笔记语义的项置灰**（`noSelectedNotes` 开关，`$T/menus/tree_context_menu.ts:120-123`）；只有颜色选择器是真消失 — `:332` | 无多选 | — | 真做多选时照这个规则来——项目位置不动，用户的肌肉记忆才不会废 |
| 右键目标高亮 | 给被右键的行加 `fancytree-menu-target`（`box-shadow: inset 0 0 0 1px var(--main-border-color)`），`onHide` 时移除 — `$T/menus/tree_context_menu.ts:466-472`、`$T/stylesheets/tree.css:226-228` | 无——右键一行之后**看不出菜单是对哪一行的** | **明显** | 6 行代码，值得。尤其我们的菜单里有「删除（连同子树）」 |
| Ctrl+右键 | 不开菜单，直接 `openInPopup` 快速编辑 — `$T/widgets/note_tree.ts:712-721` | 无 | — | 见第 9 节 PopupEditor |

---

## 7. 键盘

Trilium 的全表在 `$TS/services/keyboard_actions.ts`。我们的全部实现在 `$M/App.tsx:664-690`（8 个）+ `$M/components/CommandPalette.tsx:23-33`（⌘K）。

| 维度 | Trilium 怎么做 | 我们现在 | 等级 | 建议 |
|---|---|---|---|---|
| **⌘F 页内查找** | `findInText` = `⌘F`（仅 Electron），配套 `FindWidget` 在每个 note-split 里 — `$TS/…:823-830`、`$T/layouts/desktop_layout.tsx:166` | 无。⌘F 会落到 Electron 默认行为 | **严重** | 长文档没有页内查找是硬伤。CodeMirror 6 的 `@codemirror/search` 直接给 |
| **Alt+←/→ 前进后退** | `backInNoteHistory` / `forwardInNoteHistory`：Win/Linux `Alt+←/→`，**macOS 是 `⌘[` / `⌘]`**（`Alt+←/→` 在 mac 被树的升降级占了）— `$TS/…:19-35,171-184`；UI 入口 `TabHistoryNavigationButtons`（`bx bx-left-arrow-alt` / `right`，右键出历史菜单，Electron 下按 `navigationCanGoBack/Forward` 禁用）— `$T/widgets/TabHistoryNavigationButtons.tsx:12-37` | 无历史栈，无前进后退 | **明显** | 有标签页就必须有它——用户跳去看一篇旧笔记后要能一键回来（正是判据 2 的痛点 12）。mac 用 `⌘[` / `⌘]` |
| **⌘J 跳转到笔记** | `jumpToNote` = `⌘J`；命令面板是**另一个** `⇧⌘J` — `$TS/…:37-43,53-58` | 只有 ⌘K（笔记 + 知识库合一）— `$M/components/CommandPalette.tsx:24-27` | 细节 | 我们的合一是有意的（判据 2：一个框搜到底）。**但 ⌘K 是 Trilium 里不存在的键**——它的搜索是 `quickSearch = ⌘S`（`$TS/…:68-74`），而 ⌘S 在我们这里是保存。保留 ⌘K，另加 ⌘J 作为别名即可 |
| **Delete 删除 / Enter 重命名** | note-tree scope：`deleteNotes` = `Delete`（`$TS/…:150-156`）、`editNoteTitle` = `Enter`（`:185-192`）、`editBranchPrefix` = **`F2`**（注意：F2 是改**分支前缀**不是改标题，`:193-200`） | 无（树没有焦点，见 2.键盘导航） | **明显** | 跟树的键盘导航一起做 |
| **⌘⇧T 重开刚关的标签** | `reopenLastTab` = `⇧⌘T` — `$TS/…:293-301` | 无（关掉就没了）— `$M/App.tsx:676-679` | **明显** | 关错标签无法挽回。存一个 closedTabs 栈即可 |
| ⌃Tab / ⌘PageDown 切标签 | `activateNextTab` = `⌘Tab`, `⌘PageDown`；`activatePreviousTab` = `⇧⌘Tab`, `⌘PageUp` — `$TS/…:302-317` | 无 | 细节 | 补上，两行 |
| ⌘1..9 | `firstTab`..`ninthTab` = `⌘1`..`⌘9`（⌘9 是**第九个**）；`lastTab` **刻意不绑**，把 `⌘0` 让给 `zoomReset` — `$TS/…:343-414,864-871` | ⌘9 = **最后一个**（浏览器约定）— `$M/App.tsx:680-687` | — | 我们的更符合大众直觉，保留。但要知道这是**有意偏离** |
| ⌘. | `scrollToActiveNote`（滚动到当前笔记）— `$TS/…:60-66` | `focusMode` 切换 — `$M/App.tsx:672` | — | 有意偏离，保留。但 `scrollToActiveNote` 这个功能我们需要（见 2.底部工具条），换个键 |
| 折叠左/右栏 | `toggleLeftPane` / `toggleRightPane` / `peekRightPane` **都无默认键**，只在设置里可绑 — `$TS/…:738-753,831-838` | 无 | 细节 | Trilium 自己也没绑，不算差距；但我们做了折叠按钮之后可以顺手给 `⌘\` / `⌘⇧\` |
| 缩放 | `zoomIn` `⌘=`/`⌘+`、`zoomOut` `⌘-`、`zoomReset` `⌘0`（仅 Electron）— `$TS/…:846-871` | 无 | 细节 | Electron 桌面应用的基本预期，三行 |
| 禅模式 | `toggleZenMode` = `F9` — `$TS/…:335-342` | `focusMode` = `⌘.` | — | 一致，只是键不同 |
| 快捷键提示面板 | `showShortcutHints` = `Alt+F1`；另有可挂在任意 widget 上的 `ShortcutHintButton`（浮层按钮，按需收集当前上下文的快捷键）— `$TS/…:552-558`、`$T/widgets/shortcut_hints/shortcut_hint_button.tsx:22-55` | 无 | 细节 | 我们的快捷键散在各处 `title` 里。做一个 `?` 面板成本很低 |
| 冲突检测 | 设置页有跨 scope 的快捷键冲突检测器 — `$T/widgets/type_widgets/options/shortcuts.tsx` | 无（快捷键写死在一个 `if/else if` 链里） | — | 不需要 |
| **scope 概念** | 四个 scope：`window` / `note-tree` / `text-detail` / `code-detail`，各自绑到不同元素 — `$T/services/keyboard_actions.ts:37-72` | 只有一个全局 `window` 监听，且**先判 `metaKey \|\| ctrlKey` 再分发**（`$M/App.tsx:667`），所以 Delete / Enter / F2 这类**无修饰键的快捷键根本进不来** | **明显** | 做树的键盘导航之前必须先解决这个结构问题：至少分出 `window` 和 `note-tree` 两个 scope |

---

## 8. 主题

Trilium 有 **322 个**配色令牌（`theme-next-light.css` / `theme-next-dark.css` 各自 `:root` 7–419 行）+ base.css 约 35 个尺寸令牌；我们有 **34 个**（覆盖率约 10.6%）。下面只列**会导致视觉出错**的，纯粹「没抄」的（看板、日历、空间占用图等我们没有的模块）略过。

### 8.1 会出错的（先修这些）

| 维度 | Trilium 怎么做 | 我们现在 | 等级 | 建议 |
|---|---|---|---|---|
| **`--bg` 的语义倒置** | `--accented-background-color`（亮 `#f5f5f5` / **暗 `#555555`**，`theme-next-light.css:27`）在 Trilium 是**抬升的强调面**，页面底色是 `--main-background-color`（暗 `#242424`） | `--bg: var(--accented-bg)` 被当**页面底色**用了 12 处：`body`(`styles.css:35`)、`input/textarea`(`:83`)、`.md-editor`(`:134`)、`.palette`(`:204`)、`.modal-backdrop`(`:219`)、`.tree-node:hover/.active`(`:439-440`)、`.context-menu-item:hover`(`:481`)… — `$M/styles.css:6` | **严重** | 暗色下页面底 `#555` 比卡片 `--panel`=`#242424` **还亮**，整套层级是反的：卡片比页面暗、遮罩是浅灰、输入框是灰块。改 `--bg: var(--main-bg)`，另立 `--surface-raised: var(--accented-bg)` 给真正需要抬升的地方 |
| **`data-theme` 是半坏的死代码** | 整文件切换：`theme-next-light.css` 无 media、`theme-next-dark.css` 带 `media="(prefers-color-scheme: dark)"`；用户在设置里选定时只注入其中一个（绕过系统偏好）— `$T/services/theme.ts:66-76`；另有 matchMedia 监听 + Electron `nativeTheme` 联动 — `theme.ts:250-272` | 三条实际 bug：**B1** `shell.css:48` 的暗色守卫是 `:root:not([data-theme="light"])`，但 `styles.css:21` 的暗色块是**裸 `:root`** → 设 `data-theme="light"` 时 shell 的 24 个令牌回亮色，而 `--muted/--accent/--ins/--ins-bg/--del/--del-bg` 仍是暗色值（亮底配 `#14351f` 深绿块）。**B2** 没有任何 `[data-theme="dark"]` 规则，浅色系统下强制暗色做不到。**B3** 全仓 grep，`data-theme` 只在 `shell.css:48` 出现一次，**从没有代码写入过它** | **严重** | 要么把两个文件的守卫改成一致并真的实现主题切换 UI，要么把 `:not([data-theme="light"])` 删掉。**留着一个半坏的 escape hatch 比没有更糟** |
| **幽灵变量** | — | `--card-alt` 被引用 4 次（`components/SkeletonPanel.tsx:42`、`editor/theme.ts:20,84,103`）但**从未定义** → 行内代码/代码块背景永远走 fallback `rgba(127,127,127,0.0x)`，亮暗两模式都不跟随主题。`--hover` 被引用 1 次（`styles.css:310`）同样未定义 | **明显** | 补两个定义。Trilium 对应的是 `--inline-code-background-color`（亮 `rgba(0,0,0,.05)` / 暗 `rgba(255,255,255,.08)`，`theme-next-light.css:297`）和 `--hover-item-background-color`（`:92`） |
| **抄来的树令牌全是死的** | — | `--left-pane-item-hover-bg` / `-selected-bg` / `-selected-fg` / `-selected-shadow` 定义在 `$M/shell.css:30-33` + `66-69`，**全仓 0 处引用**；树实际用的是 `--bg` + `--accent`（`styles.css:439-441`） | **明显** | 见 2.激活态。抄了值却没接上，等于没抄——而且下一个人会以为已经接上了 |
| 亮暗**同值**的阴影/遮罩 | `--dropdown-shadow-opacity`：亮 `0.2` / 暗 `0.6`（`theme-light.css:24` / `theme-next-dark.css:23`）；`--modal-backdrop-color`：亮 `#7c7c7c` / 暗 `#000`；`--code-block-box-shadow` 亮暗**方向都不同** | 9 处硬编码 `rgba(0,0,0,…)` 亮暗同值：`styles.css:172,196,199,205,273,298,472,500` + `shell.css:26/62`（后者是**唯一**做了亮暗区分的） | **明显** | 引入 `--shadow-opacity`（亮 .18 / 暗 .55）和 `--backdrop-color`，把那 9 处换掉 |
| 白字硬编码在 accent 底上 | 无对应（Trilium 没有通用 accent 概念） | `#fff` 硬编码 4 处：`shell.css:192`（`.ribbon-badge`）、`shell.css:215`（`.pane-tab-badge`）、`styles.css:51,77`（`button.primary`）。暗色 `--accent: #60a5fa` 上白字对比度 **2.4:1**，不达 AA | **明显** | 加 `--accent-fg`：亮色 `#fff`，暗色 `#0b1220` |
| 焦点环 | `--input-focus-outline-color`（亮 `#00000063` / 暗 `#ffffff57`）+ `--input-focus-background` — `theme-next-light.css:70-71` | 全仓 `grep` 只有两条 outline 相关：`styles.css:79` 的全局 input 规则不含 focus，`styles.css:212` 是 `.palette input:focus { outline: none }`（纯减法，无替代） | **明显** | 键盘用户看不到焦点在哪。补一条 `:focus-visible { outline: 2px solid var(--focus-ring) }` |
| 未随主题的实色 | — | `components/SkeletonPanel.tsx:17` 三档色 `{0:'#c0392b',1:'#d68910',2:'#27ae60'}` 完全不随主题（**同一个文件的 `:41-42` 却正确用了 `var(--accent)`**）；`components/AgentActivity.tsx:46` 三档里**中间那档**硬编码 `#d68910`，另两档走变量 | **明显** | 补一个 `--warn` 令牌（亮 `#b45309` / 暗 `#fbbf24`），三处统一 |
| mermaid 主题双判 | Electron 主 CSS 走 media query | `editor/mermaid.ts:11` 自己又 `matchMedia` 了一次 → 两处独立判断，可能不同步 | 细节 | 统一从一个地方读 |

### 8.2 该补但不紧急的令牌

| Trilium 令牌（`theme-next-light.css` 行号） | 亮 → 暗 | 控制什么 | 我们现在 |
|---|---|---|---|
| `--muted-text-color` `:61` | `#666` → `#bbb` | 全局次要文字 | 自造 `--muted` `#6b7280`/`#9ca3af`；亮色偏淡 6%、**暗色偏暗 7%**（对比度更低） |
| `--scrollbar-thumb-color` / `-hover` / `-background-color` `:263-265` | `#0000005c` → `#fdfdfd5c` | 滚动条 | 完全无 |
| `--selection-background-color` `:268` | `#3399FF70`（**亮暗同值**） | 文本选区 | 无 |
| `--link-color` `:87` | `#0076af` → `#95c3d9` | 链接 | 用 `--accent`（色相差 40°，明显更「科技蓝」） |
| `--active-tab-shadow` `:203` | `3px 3px 6px rgba(0,0,0,.1), -1px -1px 3px rgba(0,0,0,.05)` | 激活标签的抬升 | 无 |
| `--inactive-tab-text-color` `:208` | `#4e4e4e` → `#7c7c7c` | 非激活标签文字 | 复用 `--launcher-fg`（暗色偏亮 8%） |
| `--left-pane-icon-color` `:141` | currentColor → `#c5c5c5` | 树图标（暗色**需单独提亮**） | 无（也还没有图标） |
| `--left-pane-item-action-button-*` `:146-150` | `rgba(0,0,0,.11)` → `#ffffff73` | 树行内 hover 按钮 | 无 |
| `--card-background-color` / `-hover` / `-border` `:291-295` | `#0000000d` → `#ffffff12`（**半透明叠加**） | 卡片 | `--panel` = 实色主背景 |
| `--status-bar-border-color` `:261` | `#00000026` → `#ffffff17` | 状态栏上边框 | 复用 `--subtle-border`（暗色 `#313131` 是实色，比 9% 白叠加更「划线感」） |
| `--floating-button-*`（10 个）`:232-243` | `#eaeaeacc` → `#494949d2` | 浮动按钮 | 无（见第 9 节） |
| `--main-font-family` base.css:25 | `"Inter", sans-serif` | 字体 | 无令牌，`styles.css:37` 写死 `system-ui,…` |
| `--tab-height` / `--new-tab-button-size` / `--icon-button-size` / `--center-pane-border-radius` base.css:57,58,93,60 | 36 / 24 / 32 / 10 px | 尺寸 | 写死在规则里 |

**另外**：`--tab-close-hover-fg` 只在亮色定义（`$M/shell.css:37`），暗色靠「叠加式 override」继承。当前值恰好一致所以不塌，但这是**隐性依赖**——哪天暗色块改成整块替换就会漏。

---

## 9. 它有而我们完全没有的控件

按「对我们是否有价值」排序，判据在括号里。

| 控件 | Trilium 在哪 | 它解决什么 | 对我们的价值 | 等级 |
|---|---|---|---|---|
| **FloatingButtons（正文右上角浮层按钮）** | `$T/widgets/FloatingButtons.{tsx,css}`，`position: absolute; top: 14px; inset-inline-end: 10px; z-index: 100`，按钮 `width: 40px`；`--floating-button-height: 34px` — `FloatingButtons.css:6-57`、`theme-next/base.css:62-64`；定义表 `$T/widgets/FloatingButtonsDefinitions.tsx`（DESKTOP_FLOATING_BUTTONS 16 项） | 跟正文相关的动作**浮在正文上**，不占正文的行 | **高（判据 1）**。北极星表里明写「浮动按钮 = 一个动作一个按钮（润色/改写/画图/排版）」。我们现在这些按钮是**正文流里的一行**（`$M/App.tsx:1816-1861`），会随正文滚走，而且跟正文抢宽度 | **明显** |
| **FindWidget（页内查找）** | `$T/widgets/find.ts`，挂在每个 note-split 里 — `$T/layouts/desktop_layout.tsx:166`；⌘F — `$TS/…:823-830` | 长文档里定位 | **高**。CodeMirror 6 自带 `@codemirror/search` | **严重** |
| **PopupEditor / TreePopupEditor（快速编辑浮层）** | `$T/widgets/dialogs/PopupEditor.tsx:35-60`；入口：树菜单「Quick edit」(`tree_context_menu.ts:146`) 和 **Ctrl+右键树节点**(`note_tree.ts:712-721`) | 不切走当前笔记就能看/改另一篇 | **很高（判据 2 的直接落地）**。「为了看一条旧记录而离开当前页面 = 失败」——右栏的相关记忆解决了「浮现」，但**点进去读全文**目前只能开新标签 | **明显** |
| **SplitNoteContainer（分屏）** | `$T/widgets/containers/split_note_container.ts` + `CreatePaneButton` / `ClosePaneButton` / `MovePaneButton` — `$T/layouts/desktop_layout.tsx:133-146`；resizer `$T/services/resizer.ts:102-160` | 对照着另一篇写 | **高**。`docs/trilium-migration-plan.md` 里 61–75 轮就写了分屏，标签页做了但分屏没做 | **明显** |
| **NoteIcon（可点的笔记图标）** | `$T/widgets/note_icon.{tsx,css}`，`--note-icon-size: 30px`（新布局 16px），容器 padding 10px（新布局 6px），点开是图标选择器 — `note_icon.css:1-24,38-74` | 笔记的视觉标识 | 中。树图标做了之后自然要有 | 细节 |
| **save-status-badge（保存状态）** | `$T/widgets/layout/NoteBadges.css:28-45`：`opacity: .4`，保存成功后 5s 淡出，出错变红且不淡出 | 自动保存的产品里告诉用户「存了」 | **中高**。我们是自动保存 + 一个「保存」按钮，按钮反而暗示「不点就没存」 | 细节 |
| **StatusBar 的 Breadcrumb（笔记路径面包屑）** | `$T/widgets/layout/Breadcrumb.tsx` + `StatusBar.css:16-19`（`flex-grow: 1`，`--icon-button-size: 23px`） | 当前笔记在树的哪个位置 | **中高**。我们有克隆——同一篇在多处，面包屑是唯一能说清「你现在看的是哪一份」的东西 | **明显** |
| **shortcut_hints 面板 + 按钮** | `$T/widgets/shortcut_hints/`：`Alt+F1` 开面板，另有可挂在任意 widget 上的浮层 `?` 按钮，**按当前上下文收集快捷键** — `shortcut_hint_button.tsx:22-55` | 快捷键可发现 | **已做**（2026-09-12）：`⌘/` 快捷键一览 + 欢迎页常用键，键表在 `shortcuts.ts`，TRACELOG [31] | — |
| **tree-actions 工具条（折叠全树 / 定位当前笔记）** | `$T/widgets/note_tree.ts:113-121`；收起 40px 圆钮 hover 展开 — `theme-next/shell.css:908-981` | 树导航 | **中高**（见第 2 节） | **明显** |
| **TabHistoryNavigationButtons（前进后退）** | `$T/widgets/TabHistoryNavigationButtons.tsx:12-37`，右键出历史菜单 | 跳去看一篇再回来 | **高（判据 2 痛点 12）** | **明显** |
| **Backlinks（反向链接）** | 浮动按钮 `Backlinks` — `$T/widgets/FloatingButtonsDefinitions.tsx:372-437`；面板 `.backlinks-items { width: 400px; top: 50px }` — `FloatingButtons.css:112-158`；侧栏版 `$T/widgets/sidebar/Backlinks.tsx` | 「哪些笔记引用了我」，带**摘录片段** | **已做**（2026-09-12）：事实反链在 ribbon「引用」的「也引用于」；笔记之间的链接 `[[` 补全 + `note://` 标记 + ribbon「链接」（链出 / 链到这篇的），见 TRACELOG [32] | — |
| **NoteMap / NoteMapGraph** | `$T/widgets/sidebar/NoteMap.tsx` | 笔记关系图 | 低。我们有 `KnowledgeGraph.tsx`（713 行），但它是弹层不是右栏 tab；北极星表里写着该进右栏 | 细节 |
| **branch_prefix 对话框** | `$T/widgets/dialogs/branch_prefix.tsx`，F2 — `$TS/…:193-200` | 同一篇在不同位置显示不同前缀 | 低。克隆量小的时候用不上 | — |
| **delete_notes 确认对话框** | `$T/widgets/dialogs/delete_notes.tsx` | 删子树前列出会删掉什么 | 低。我们走的是**乐观删除 + 撤销窗口**（`$M/App.tsx:882` 的注释明说「不用 confirm 对话框」），对单篇比确认框好。**但树菜单的「删除（连同子树）」是例外**——它会连带删掉看不见的东西，用户在点之前不知道会删几篇 | 细节 |
| **item_picker / clone_to / move_to 对话框** | `$T/widgets/dialogs/{item_picker,clone_to,move_to}.tsx`（带搜索的笔记选择器） | 选目标笔记 | **中高**。我们的 `pickTarget` 是 **`window.prompt` + 把整棵树拍平成编号列表**，让用户输序号（`$M/App.tsx:336-350`，注释自己写着「先做对，再做好看」）。笔记上百篇之后这个 prompt 会长到滚不动；`renameNode`（`:321-322`）同样是 `window.prompt`。而且在 Electron 里 `window.prompt` 是**系统级模态**，样式完全不受主题控制 | **明显** |
| **ScrollPadding** | `$T/widgets/scroll_padding.ts` — `desktop_layout.tsx:163` | 正文底部留白，最后一行也能滚到视线中间 | 细节。写作时很有感 | 细节 |
| **note_tooltip（笔记悬浮预览）** | `$T/services/note_tooltip.ts`（菜单开着时抑制 — `note_tooltip.ts:50`） | 悬停链接看摘要 | **中高（判据 2）**。跟 `.cm-fact-peek` 同一类 | 细节 |
| **shared_info / PromotedAttributes / bulk_actions / OptionsDialog** | — | 分享状态、提升属性、批量操作、设置页 | 低（我们没有这些概念，设置已是独立面板） | — |

---

## 10. 故意不抄的

| Trilium 的东西 | 位置 | 为什么不抄 |
|---|---|---|
| **SidebarChat（右栏 AI 对话）** | `$T/widgets/sidebar/SidebarChat.{tsx,css}`；右栏 tab 定义里的 `{ id: "chat", icon: "bx bx-bot" }` — `$T/widgets/sidebar/RightPaneTabs.tsx:29` | **它是个聊天框，正是判据 1 要消灭的东西。** 北极星原话：「右侧加个聊天框也一样，只是把横跳从『跨应用』变成了『跨栏』」。我们右栏的「运行」放的是 harness 每一轮做了什么、判了什么——**执行记录，不是对话** |
| **ribbon 的 14 个 tab 里的 11 个** | `$T/widgets/ribbon/RibbonDefinition.ts:19-125` | classic_editor_toolbar（CKEditor 的）、script/query、search_definition、file/image_properties、owned/inherited_attributes、similar_notes、note_map 都绑在我们没有的概念上（富文本编辑器、脚本笔记、保存的搜索、属性系统、多种笔记类型）。**只有 note_paths 和 note_info 值得进来**（见第 4 节） |
| **脚本系统（笔记里写 JS 执行）** | `$T/widgets/ribbon/ScriptTab.tsx`、`api_log.tsx`、`RunActiveNoteButton` | `docs/trilium-migration-plan.md §4` 已明确：那是另一个产品方向 |
| **CKEditor / FormattingToolbar** | `$T/widgets/ribbon/FormattingToolbar.tsx` | 产品既定选择是 markdown + CodeMirror（`migration-plan §4`）。我们的 `MarkdownToolbar` 是它的对应物 |
| **属性系统（labels & relations）** | `$T/widgets/attribute_widgets/`、`PromotedAttributes.tsx`、`Alt+L` / `Alt+R` — `$TS/…:625-639` | 我们的元数据模型是「写作骨架 + 节拍覆盖 + 修订」，不是 key-value 标签。硬套会让 ribbon 变成两套并行的元数据 |
| **保护/加密子树** | 树菜单 `protectSubtree` / `unprotectSubtree` — `$T/menus/tree_context_menu.ts:185-187` | `migration-plan §4`：不做同步/加密 |
| **分享（share）** | `shared_info.tsx`、树上的 `shared-indicator` — `$T/widgets/note_tree.ts:1964-1974` | 同上，不做分享 |
| **hoist（把某个子树当作临时的根）** | `toggleNoteHoisting` `Alt+H` / `unhoist` `Alt+U` — `$TS/…:792-807`；树上一整套 UI | Trilium 需要它是因为它的树可以有上万个节点。我们的规模（几十到几百篇）用不上，而它会带来一堆状态（hoisted 时哪些菜单项要禁用，见 `tree_context_menu.ts:148-159`），成本远大于收益 |
| **归档笔记（archived）+ 隐藏子树** | 树菜单 `:294-321`、`:226-233`；`toggleArchivedNotes` `⇧⌘H` — `$TS/…:114-121` | 同上，是大规模笔记库的整理工具。我们的等价物应该是 harness 的状态，不是一个手工标签 |
| **自动折叠树（600 秒无操作）** | `$T/widgets/note_tree.ts:1232-1273` | 树规模小，自动收树只会让人找不到东西 |
| **快速搜索的 Enter 才搜** | `$T/widgets/quick_search.ts:193,222-230` | 我们边打边搜（200ms 防抖）体验更好 |
| **`⌘9` = 第九个标签** | `$TS/…:399-405` | 我们用浏览器约定（⌘9 = 最后一个）。**这是有意偏离，不是没抄到** |
| **右键菜单的多列子菜单（`columns: 2`）** | `$T/menus/tree_context_menu.ts:169,179` | 它用来铺开十几种笔记类型。我们只有 markdown 一种 |
| **`⌘.` = 滚动到当前笔记** | `$TS/…:60-66` | 我们把 `⌘.` 给了专注模式。「滚动到当前笔记」这个**功能**要（放进树的底部工具条），但不占这个键 |
| **横版布局（launcher 在顶部）** | `$T/layouts/desktop_layout.tsx:66,197-202`；一整套 `--launcher-pane-horiz-*` 令牌 | 一个布局选项就是两套要维护的 CSS。我们只做竖版 |
| **移动端 / mobile_layout** | `$T/layouts/mobile_layout.tsx` | `migration-plan §4`：不做移动端 |

---

## 附：建议的落地顺序

不按 UI 好看程度排，按「现在会不会坏」排。

**第一批（现在就是坏的）**
1. 左栏加滚动容器（`.left-pane-body` 已经写好了，接上就行）— 1.2
2. 标签行溢出可达（strip `overflow-x: auto` 或抄滚动按钮）— 3.1
3. `--bg` 语义倒置 — 8.1
4. `data-theme` 半坏死代码 — 8.1
5. macOS 红绿灯压住左栏 — 1
6. 写作骨架 ribbon 默认展开（判据 3）— 4.1

**第二批（结构性，越晚改越贵）**
7. 左/右栏可拖宽 + 可独立折叠（Split + 持久化）— 1
8. 快捷键分 scope（`window` / `note-tree`），否则树的键盘导航做不了 — 7
9. 树的键盘导航 + Delete/Enter — 2、7
10. 标题行提出滚动容器 — 1
11. 补 `--card-alt` / `--hover` 两个幽灵变量，接上四个死掉的树令牌 — 8.1

**第三批（补齐 Trilium 的手感）**
12. 树拖拽移动 + drop 标记线 —— 顺带干掉 `pickTarget` 那个输序号的 `window.prompt` — 2、9
13. 树图标 + 行内 hover「＋」 + 底部「定位到当前笔记」 — 2
14. 标签右键菜单（App.tsx 里 prop 都留好了）+ 拖拽排序 + ⌘⇧T — 3、7
15. ⌘F 页内查找、前进后退 — 7、9
16. 尺寸对齐（58/50/36px、缩进 10px、间距 5px、圆角 8px）— 1、2、3
17. 滚动条样式、阴影令牌、焦点环 — 1、8

**第四批（长出 Trilium 没有但我们需要的）**
18. FloatingButtons 化：把 AI 动作从正文流里提到浮层（判据 1）— 9
19. PopupEditor：不离开当前笔记看另一篇（判据 2）— 9
20. Backlinks：一条事实还被哪几篇引用过（判据 2）— 9 ✅ 事实反链 + 笔记反链 [32]
21. 分屏 — 9
