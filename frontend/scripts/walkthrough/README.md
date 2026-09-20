# 打包壳上的全流程走查：量具在哪儿、怎么跑

P62 / P63 / P64 三批各留过同一条：**壳那一侧的量具还在 scratch 里，下一次壳上的数还是复现不出来。**
P66 把驱动搬了进来，**步骤脚本留在了外面**——于是 P66 / P67 / P68 / P70 又各欠了一批。
**P72 把步骤脚本也收了进来**，欠的四批一次还清。

## 进了仓库的

| 东西 | 在哪儿 | 接在哪条链上 |
|---|---|---|
| CDP 驱动 `cdp.mjs`（`d.must` / `d.toasts` / `d.dots` / `d.menuItems` / `d.expandDetails` / `d.readCard` / `d.noteId` / `d.openNoteById` / `d.shot` / `d.cmText` …） | `frontend/scripts/walkthrough/cdp.mjs` | 选择器那一半进了 `npm test`；跑的那一半要壳 |
| **步骤脚本 31 份**（十一步 + 几批专题探针 + 两份共用量具） | `frontend/scripts/walkthrough/steps/` | **`npm test`**（`check-walkthrough-selectors.mts` 现在**默认扫它们**；`check-walkthrough-runnable.mts` 逐个 import） |
| **身份的唯一出处**（P78 A）`whoami.mjs`（`USER_KEY` / `USER` / `USER_SOFT`） | `frontend/scripts/walkthrough/whoami.mjs` | **`npm test`**（`check-walkthrough-selectors.mts` 第三件事：这个键只准在这一份里出现） |
| 选择器静态自检 | `frontend/scripts/check-walkthrough-selectors.mts` | **`npm test`** |
| 「按 README 跑得起来」那条闸 | `frontend/scripts/check-walkthrough-runnable.mts` | **`npm test`** |
| userData 造法（写 `identity.json`、拷 codebook 并核字节数、起壳前过闸） | `backend/scripts/walkthrough_udd.py` | **`pytest`**（`backend/tests/test_p66.py`） |
| **起壳那一套**（P74 搬的）：`go.sh` / `launch.sh` / `step.sh` / `haspage.mjs` | `frontend/scripts/walkthrough/` | 路径和「有没有写死的绝对路径」进 **`npm test`**（`check-walkthrough-fakeshell.mts`）；跑得起来要真 `.app` |
| **假模型端点**（P74 搬的） | `backend/scripts/walkthrough_fakellm.py` | **`pytest`**（`backend/tests/test_p74.py` 直接 import 跑形状自检） |
| **假壳那条路**（P74 立的）：不打包也能真跑几步 | `frontend/scripts/walkthrough/fakeshell/main.cjs` + `frontend/scripts/walkthrough/fakeshell/preload.cjs` + `frontend/scripts/run-walkthrough-fakeshell.mjs` | 真跑那一半**手动**（本机才有 Electron / venv / dist）；「这条路还接着吗」进 **`npm test`**（`check-walkthrough-fakeshell.mts`） |

`walkthrough_udd.py` 为什么在 backend：它是 Python、读的是 `backend/data` 那棵树，
而 `frontend/scripts/` 那边只有 node / tsx，没有跑得动它的地方，也就没有闸接得住它。

## 十一步 → 哪个脚本

走查表（`docs/TRACELOG-product.md` 每一批那张「# / 步骤 / 空库新用户 / 482 篇老用户」）的十一步，
两个身份各走一遍。**同一步在两个身份上常常是两份脚本**——空库那一趟要从设置页配模型开始。

| 步 | 走查表那一步 | 空库新用户 | 482 篇老用户（terrence） |
|---|---|---|---|
| 1 | 第一次打开 → 设置页配模型 | `steps/bnew.mjs` `steps/bnew2.mjs` `steps/bnew3.mjs` | `steps/whoami52.mjs` `steps/b1old.mjs` |
| 2 | 新建 → 打标题 → 右栏「计划」 | `steps/bnew.mjs` | `steps/b1old.mjs` |
| 3 | 打三段正文 → 圆点两档 + 右栏「记忆」 | `steps/bnew.mjs` | `steps/b1old.mjs` |
| 4 | `/` 菜单全项 + Esc | — | `steps/b1old.mjs` |
| 5 | 右键六项 + 选区 | — | `steps/b1b.mjs`（右键那一半在 `steps/ctxmenu52.mjs`） |
| 6 | 智能续写 → 轮次卡片 → **读库** | — | `steps/b2old.mjs` |
| 7 | 导回到 Obsidian | — | `steps/b2old.mjs` |
| 8 | 屏幕活动 | `steps/bnew.mjs` | `steps/b3old.mjs` `steps/b4old.mjs` `steps/journey64.mjs` |
| 9 | ⌘K 全部去处 | `steps/bnew.mjs` | `steps/b1old.mjs` |
| 10 | 关掉重开（**真的重开**：单独一次 `go.sh`，壳是新起的） | — | `steps/reopen64.mjs` |
| 11 | 深色 + 900px | `steps/bnew.mjs` `steps/bnew3.mjs` | `steps/b1old.mjs` |

十一步之外还有几批的**专题探针**，同在 `steps/`，按需单跑：
`steps/adv64.mjs`（advisory / judge_floor 两档）、`steps/adv70.mjs`（收工那行 +N 字 · 编辑器 / 库两头）、
`steps/recall64.mjs`、`steps/lock64.mjs`、`steps/emptyday58.mjs`、`steps/flipday60.mjs`、
`steps/rounds58.mjs`、`steps/rounds60.mjs`、`steps/stalled.mjs`、`steps/syn.mjs`、`steps/tomb.mjs`、
`steps/ro.mjs`、`steps/probe60.mjs`、`steps/setuser.mjs`、`steps/wipe66.mjs`、
`steps/recall74.mjs`（P74 加：把「命中：」那一行**逐词点名**打出来，段落从命令行给
——P71 那两族「变差」是离线尺子上读出来的，这一份把它们搬到界面上看一眼）。

共用量具两份，**没有 default 导出**（它们不是「一步」）：
`steps/lib.mjs`（`docText` / `statusWords` / `pageText` / `until`）、`steps/lib52.mjs`（屏幕活动那一页）。
`steps/clickexact.mjs` / `steps/ctxmenu52.mjs` 两者兼有：既能单跑，也被别的步骤 import。

## 不打包也能真跑几步：**假壳**（P74）

P66～P72 一路欠着的那条是：**「真跑一趟」那三分之二只有真起一次壳才能答**，
而真起一次壳要先 `npm run dist`（十几分钟、产物不进 git）。
P72 自己写着：要接得**先有一条「用假壳跑通一步」的路**。

那条路在这儿。**真壳那三样前置里只有第一样是假的**：

| 前置 | 真壳 | 假壳 |
|---|---|---|
| 一个真打出来的 `.app` | `npm run dist`（vite + pyinstaller + electron-builder + 重签） | **换掉**：`desktop/node_modules` 里那个 Electron + `frontend/dist` + 源码跑的后端 |
| 一份真用户库 | `backend/scripts/walkthrough_udd.py` 那一套 | **没换**（默认跑空库新用户那个身份，不碰真库） |
| 一个活着的 CDP 端口 | `--remote-debugging-port` | **没换**，步骤脚本走的还是 `frontend/scripts/walkthrough/cdp.mjs` |

```sh
cd frontend && npm run build          # 要先有 frontend/dist
WALKTHROUGH_SCRATCH=<一个空目录> node scripts/run-walkthrough-fakeshell.mjs
```

它跑的是**走查本来就在跑的那几步**（`steps/whoami52.mjs` / `steps/bnew.mjs` / `steps/bnew3.mjs`，
一个字节没改），判据写在 `frontend/scripts/run-walkthrough-fakeshell.mjs` 的 `PLAN` 里。
**够不着什么**（打包 / 主进程那一圈 / 482 篇那一趟 / CI）逐条写在那份文件的头上。

## 怎么跑一趟走查

```sh
# ① 先跑两条静态自检（`npm test` 里本来就有，这儿是单跑）
cd frontend
npx tsx scripts/check-walkthrough-selectors.mts
npx tsx scripts/check-walkthrough-runnable.mts

# ② 造 userData（身份 + 语料 + 起壳前过闸）
cd backend
./.venv/bin/python -c 'import scripts.walkthrough_udd'   # 真正的造法见该文件的 docstring

# ③ 打壳（前端 + 后端 + electron-builder），或者拿上一批打好的那份重打 asar
cd desktop && npm run dist

# ④ 起壳 + 跑步骤。截图目录**必须显式给**，cdp.mjs 不猜
unset ELECTRON_RUN_AS_NODE
export WALKTHROUGH_SHOT_DIR=<scratch>
# 这一批的截图批次前缀（P76 C①）。**设了就不用事后改名**：步骤脚本里写死的
# `p70-xxx.png` 落盘时会变成 `p76-xxx.png`，名字里没有 `p<数字>-` 的原样不动。
# **不设 → 原样不动**（老批次的跑法逐字复现得出来）。
export WALKTHROUGH_SHOT_PREFIX=p76
node frontend/scripts/walkthrough/cdp.mjs <cdp-port> frontend/scripts/walkthrough/steps/b1old.mjs [args...]
```

每一步的入口契约由 `cdp.mjs` 定死（`mod.default(d, args)`）：
**默认导出一个 `async (d, args) => {}`**，`d` 是驱动、`args` 是命令行第 4 个起的那些。
`check-walkthrough-runnable.mts` 逐个 import 过来核这条契约。

几条每批都要重记一遍的：

* **`unset ELECTRON_RUN_AS_NODE`**，否则 Electron 当 node 跑，没有窗口。
* **端口起之前逐个核过空着**，撞了换。
* **改了 `desktop/src` 底下的东西就必须重打 asar**，否则壳里跑的还是旧的那份。
  「壳里几个可执行件核几个」：`app.asar/dist/{main,preload,capture,backend}.js`
  逐字节对着 worktree 现编的那份核，`Resources/web` 整树哈希对着 `frontend/dist` 核。
* **后端那个可执行件不许拿 `strings` 核**（P69 合并那天栽的）：PyInstaller 把纯 Python 模块
  压在 exe 尾巴的 PYZ 里逐个 zlib 压过，符号名不以明文出现，`strings` 恒为 0——
  **那条 grep 不管壳对不对都是 0，它不是尺子**。走 `backend/scripts/check_shipped_source.py`（解 PYZ 读符号表）。
* **`~/Library/Application Support` 一次都不许碰**：走查的 userData 一律在 scratch 下，
  壳用 `--user-data-dir=<scratch>/...` 起。
* **真库只读**：`sqlite3.backup` 拷一份出来，扫全库把真 key 换掉、三个 base_url 指本机，
  **扫完再核一遍**才准起壳。

## 那一圈现在进来了：`go.sh` / `launch.sh` / `step.sh` / `haspage.mjs` / 假模型（P74）

P66～P72 这儿一直写着「不是懒得搬，是搬进来也跑不了」。**那个理由只对了一半**——
「跑不了」说的是它们要一个真 `.app`，而**「搬不搬」跟「跑不跑得了」是两件事**：
留在 scratch 里的后果是**每一次走查都得现写一遍**，而现写的那一份跟上一批不一样，
于是「上一批那个数」复现不出来（P62 / P63 / P64 各留过同一条）。

搬进来之后每一份变的都只有一处：**写死的 scratch / worktree 绝对路径一律改成参数或环境变量**，
一个都不猜（`cdp.mjs` 的 `WALKTHROUGH_SHOT_DIR` 是同一条理由）。
这一条本身有闸看着：`frontend/scripts/check-walkthrough-fakeshell.mts` 逐行扫这几份，
**代码行里出现 `/Users/…` / `/private/tmp/…` 当场红**（注释里举例不算）。

```sh
# 一趟真壳的走查（假模型 + 起壳 + 跑清单 + 收摊，全在一次调用里）
WALKTHROUGH_APP=<…/MEMOKET NOTE.app> WALKTHROUGH_UDD=<…/udd> WALKTHROUGH_SHOT_DIR=<…/shots> WALKTHROUGH_LOG_DIR=<…/log> zsh frontend/scripts/walkthrough/go.sh <cdp-port> <llm-port> <steps 清单文件>
```

`go.sh` 还替 P68 那条老坑立了一声：起壳前拿 udd 库里的 `provider_config.local_base_url`
跟这一趟的假模型端口对一次，**对不上就吵**（对不上的后果是「AI 功能一个都不响应」，
看起来像产品坏了）。

## 真壳那一圈为什么非要真打包

**每一份都要下面三样同时在**，而 `npm test` / `pytest` 里一样都没有（假壳换掉的是第 1 样）：

1. **一个真打出来的 `.app`**。壳要 `npm run dist`：前端 `vite build` + 后端 `pyinstaller`
   （一份几百 MB 的单文件可执行）+ `electron-builder` 出 dmg，再 adhoc 重签。
   一次十几分钟，产物不进 git，CI 上没有。
2. **一份真用户库**。走查那一半的判据是「482 篇老用户身上长什么样」，
   而真库不进 git（`.gitignore` 的 `data/` + `*.sqlite3`），并且**只读拷贝之前要扫全库换掉真 key**。
3. **一个活着的 CDP 端口**。`--remote-debugging-port` 起的是一个真窗口，
   跑一步几秒到几十秒，一趟走查十几分钟。

**步骤脚本不一样**，那正是 P72 搬它们的理由：它们是**纯模块**，
不起进程、不连端口、import 进来什么都不会发生——
所以「装得进 node 吗 / 符不符合入口契约 / 选的类名前端里有没有」这三件事
`npm test` 全核得动，而这三件正是 P70 两个问题（#2 正则太窄、#3 第一次对着真调用点跑就误报）的形状。
**一条永远绿的闸不是闸**，但**一条能核到三分之一的闸比留在 scratch 里强三分之一**——
够不着的那三分之二写在 `check-walkthrough-runnable.mts` 自己的注释里，不许含糊过去。
