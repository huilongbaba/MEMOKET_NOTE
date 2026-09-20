// 假壳的主进程（P74 A）。**不是产品的 `desktop/src/main.ts`，也不冒充它。**
//
// ─────────────────────────────────────────────────────────────────────────────
// 为什么有这个文件
//
// P72 把 30 份步骤脚本收进了 `steps/`，并且把自己够不着的写清楚了：
// **「真跑一趟」那三分之二**（壳打不打得出来 / CDP 连不连得上 / 每一步跑起来对不对）
// 全够不着，理由是「要接得先有一条**用假壳跑通一步**的路，今天没有」。
//
// 这就是那条路。**真壳那三样前置里，只有第一样是假的**：
//
//   1. **一个真打出来的 `.app`** —— 假壳换掉的就是这一样。
//      `npm run dist` 要 `vite build` + `pyinstaller`（几百 MB 单文件）+ `electron-builder`
//      + adhoc 重签，十几分钟，产物不进 git。假壳不打包：
//      **真 Chromium 窗口（`desktop/node_modules/electron`）+ 真前端 `frontend/dist`
//      + 真后端（源码 uvicorn）**，三样都是产品自己的东西，只有「打包」这一层是假的。
//   2. **一份真用户库** —— 没换。照旧 `backend/scripts/walkthrough_udd.py` 那一套
//      （`identity.json` + 真 codebook + 起壳前过闸），真库只读拷贝、扫全库换 key。
//   3. **一个活着的 CDP 端口** —— 没换。`--remote-debugging-port` 起的是真窗口，
//      步骤脚本走的是仓库里那份 `cdp.mjs`，真输入事件。
//
// 所以假壳跑绿 **不等于** 打好的 `.app` 也绿（下面「够不着什么」逐条写着）；
// 但它把 P72 那三分之二里**能不靠打包答的那一部分**变成了每次都能重跑的东西。
//
// ─────────────────────────────────────────────────────────────────────────────
// 这个主进程跟产品 `main.ts` 差在哪（**逐条写出来，不许含糊**）
//
// 一样的：
//   · 从 `<userData>/identity.json` 读身份，挂到窗口 URL 的 `?user=` 上
//     （`walkthrough_udd.write_identity` 的整条理由就在这儿——不挂它，前端会自己
//      随机生成一个身份，482 篇一篇都看不见，而且**不报错，只是静默变差**）。
//   · 页面从 `http://127.0.0.1:<后端端口>/` 加载（后端同源托管 `frontend/dist`），
//     于是前端里所有 `/api/...` 的相对路径原样可用。
//   · `memoketDesktop.setTheme` 走 `nativeTheme.themeSource`——界面暗色靠
//     `prefers-color-scheme`，没有这条通道 `d.setTheme()` 就只是写了个 localStorage，
//     **看着像产品不认深色**（那会是一条假缺陷）。
//
// 不一样的（= 假壳**够不着**的，步骤脚本用到这些就会走 `?.` 的空分支）：
//   · 后端不是这个进程拉起来的，是跑测的那个脚本拉起来的 → 没有 `backend.ts` 那一圈
//     （端口重试 / `MEMOKET_NOTE_PARENT_PID` 自杀 / 崩了重起 / 换端口 `loadURL`）。
//   · 菜单、`onFlush`/`flushed`、`pickDirectory`、`exportCreds`、`slidesToPdf`、
//     `journey`（屏幕活动的采集在主进程里）**一律没有**。
//     → 走查第 ⑦ 步（导回 Obsidian 的目录选择）和第 ⑧ 步的采集那一半，假壳上跑不了。
//   · 不签名、不走 `electron-builder`、没有 `extraResources` → `test_packaging.py`
//     和「壳里几个可执行件核几个」那一圈，假壳一条都答不了。
// ─────────────────────────────────────────────────────────────────────────────
const { app, BrowserWindow, nativeTheme, ipcMain } = require('electron')
const path = require('node:path')
const fs = require('node:fs')

const backendPort = Number(process.env.FAKESHELL_BACKEND_PORT || 0)
if (!backendPort) {
  console.error('[fakeshell] 没给 FAKESHELL_BACKEND_PORT —— 不猜一个端口静默连错地方')
  app.exit(3)
}

/** 身份：跟产品 `main.ts:loadIdentity()` 同一个契约（同一个文件名、同一条正则）。 */
function loadIdentity() {
  try {
    const u = JSON.parse(fs.readFileSync(path.join(app.getPath('userData'), 'identity.json'), 'utf8')).user
    return typeof u === 'string' && /^[\w.-]{1,64}$/.test(u) ? u : undefined
  } catch { return undefined }
}

function appUrl() {
  const user = loadIdentity()
  const q = new URLSearchParams()
  if (user) q.set('user', user)
  const s = q.toString()
  return `http://127.0.0.1:${backendPort}/` + (s ? `?${s}` : '')
}

ipcMain.on('set-theme', (_e, t) => {
  nativeTheme.themeSource = (t === 'light' || t === 'dark') ? t : 'system'
})
ipcMain.on('remember-user', () => { /* 假壳不回写 identity.json：身份由 walkthrough_udd 定死 */ })
// **`pid` 得是后端那个进程的 pid，不是我自己的**（P45 #2）。
// 界面拿这一份跟 `/api/health` 自报的那一份对一次，对不上就摆
//「⚠︎ 连错后端了：这个端口上应答的后端是进程 A，而这份 app 起的是 B」。
// 第一版这儿写的是 `process.pid`（Electron 主进程），于是**假壳每一趟都摆着那条横幅**
// ——看起来像产品坏了，其实是假壳自己给错了数。**这正是 `bnew` 那条反例抓到的。**
const backendPid = Number(process.env.FAKESHELL_BACKEND_PID || 0)
if (!backendPid) {
  console.error('[fakeshell] 没给 FAKESHELL_BACKEND_PID —— 界面会摆「连错后端了」，那是假壳的错不是产品的错')
  app.exit(3)
}
ipcMain.handle('backend:info', () => ({
  port: backendPort, pid: backendPid, dataDir: path.join(app.getPath('userData'), 'data'),
}))

app.whenReady().then(() => {
  const win = new BrowserWindow({
    width: 1440, height: 900, show: true,
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), sandbox: false },
  })
  const url = appUrl()
  console.log(`[fakeshell] userData=${app.getPath('userData')}`)
  console.log(`[fakeshell] loadURL ${url}`)
  win.loadURL(url).catch((e) => console.error(`[fakeshell] 页面加载失败 ${url}：${e}`))
})

// 窗口全关了就退：跑测脚本收摊时先关窗口再兜底 kill。
app.on('window-all-closed', () => app.quit())
