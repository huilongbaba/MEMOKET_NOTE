# 打包壳上的全流程走查：量具在哪儿、怎么跑

P62 / P63 / P64 三批各留过同一条：**壳那一侧的量具还在 scratch 里，下一次壳上的数还是复现不出来。**
P66 把**能进的都搬进来了**，进不了的在下面写清楚为什么。

## 进了仓库的

| 东西 | 在哪儿 | 接在哪条链上 |
|---|---|---|
| CDP 驱动 `cdp.mjs`（`d.must` / `d.toasts` / `d.dots` / `d.menuItems` / `d.expandDetails` / `d.readCard` / `d.noteId` / `d.openNoteById` / `d.shot` / `d.cmText` …） | `frontend/scripts/walkthrough/cdp.mjs` | 选择器那一半进了 `npm test`（下一行）；跑的那一半要壳 |
| 选择器静态自检 | `frontend/scripts/check-walkthrough-selectors.mts` | **`npm test`**（`npx tsx scripts/check-walkthrough-selectors.mts`） |
| userData 造法（写 `identity.json`、拷 codebook 并核字节数、起壳前过闸） | `backend/scripts/walkthrough_udd.py` | **`pytest`**（`backend/tests/test_p66.py`） |

`walkthrough_udd.py` 为什么在 backend：它是 Python、读的是 `backend/data` 那棵树，
而 `frontend/scripts/` 那边只有 node / tsx，没有跑得动它的地方，也就没有闸接得住它。

## 没进仓库的：步骤脚本（`steps/*.mjs`）

它们还在 scratch（`<scratch>/p66/steps/` 这一类）。**不是懒得搬，是搬进来也跑不了**——
每一份都要下面三样同时在，而 `npm test` / `pytest` 里一样都没有：

1. **一个真打出来的 `.app`**。壳要 `npm run dist`：前端 `vite build` + 后端 `pyinstaller`
   （一份几百 MB 的单文件可执行）+ `electron-builder` 出 dmg，再 adhoc 重签。
   一次十几分钟，产物不进 git，CI 上没有。
2. **一份真用户库**。走查那一半的判据是「482 篇老用户身上长什么样」，
   而真库不进 git（`.gitignore` 的 `data/` + `*.sqlite3`），并且**只读拷贝之前要扫全库换掉真 key**。
3. **一个活着的 CDP 端口**。`--remote-debugging-port` 起的是一个真窗口，
   跑一步几秒到几十秒，一趟走查十几分钟。

搬进来的后果会是一堆「在 CI 上永远跳过」的文件——**一条永远绿的闸不是闸**，
一份永远跳过的脚本比留在 scratch 更糟：它看着像被覆盖了。

**所以进链的是不需要壳的那一半**：`check-walkthrough-selectors.mts`
把量具里选的每一个类名对着 `frontend/src` 点一遍名。P64 收工那一趟这条闸
**当场点名了那一批新写的 `.journey-day-opt`**（前端里根本没有这个类，
`option` 那一半退回去把「留多久」两个下拉的选项读了回来，看起来像天列表）。

## 怎么跑一趟走查

```sh
# ① 先跑静态自检，**把这一批的步骤脚本目录显式点名**（默认只扫仓库里的公共驱动）
cd <worktree>/frontend
npx tsx scripts/check-walkthrough-selectors.mts <scratch>/p66/steps

# ② 造 userData（身份 + 语料 + 起壳前过闸）
cd <worktree>/backend
./.venv/bin/python <scratch>/p66/setup66.py     # 里面 import scripts.walkthrough_udd

# ③ 打壳（前端 + 后端 + electron-builder），或者拿上一批打好的那份重打 asar
cd <worktree>/desktop && npm run dist

# ④ 起壳 + 跑步骤。截图目录**必须显式给**，cdp.mjs 不猜
unset ELECTRON_RUN_AS_NODE
export WALKTHROUGH_SHOT_DIR=<scratch>
node <worktree>/frontend/scripts/walkthrough/cdp.mjs <cdp-port> <scratch>/p66/steps/xxx.mjs [args...]
```

几条每批都要重记一遍的：

* **`unset ELECTRON_RUN_AS_NODE`**，否则 Electron 当 node 跑，没有窗口。
* **端口起之前逐个核过空着**，撞了换。
* **改了 `desktop/src/**` 就必须重打 asar**，否则壳里跑的还是旧的那份。
  「壳里几个可执行件核几个」：`app.asar/dist/{main,preload,capture,backend}.js`
  逐字节对着 worktree 现编的那份核，`Resources/web` 整树哈希对着 `frontend/dist` 核。
* **`~/Library/Application Support` 一次都不许碰**：走查的 userData 一律在 scratch 下，
  壳用 `--user-data-dir=<scratch>/...` 起。
* **真库只读**：`sqlite3.backup` 拷一份出来，扫全库把真 key 换掉、三个 base_url 指本机，
  **扫完再核一遍**才准起壳。
