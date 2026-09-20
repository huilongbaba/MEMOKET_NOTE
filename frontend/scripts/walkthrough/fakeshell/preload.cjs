// 假壳的 preload（P74 A）。**只暴露三件产品 preload 也暴露的东西**，一件都不多。
//
// 为什么不是「把 `desktop/dist/preload.js` 直接拿来用」：那一份把十来个通道
// 一次性 `exposeInMainWorld`，而假壳的主进程只接得住其中三个——剩下的
// `ipcRenderer.invoke` 会**挂着不回**（`pickDirectory` / `exportCreds` / `journey`），
// 界面上看起来就是「点了没反应」。**一个挂着不回的桩比没有这个桩更难查。**
// 所以这里反过来：**接得住的才暴露，接不住的一个都不挂**，
// 前端那一侧全是 `window.memoketDesktop?.xxx?.()`，缺了就走空分支，
// 症状是「这个功能在假壳上没有」——而不是「这个功能坏了」。
//
// 暴露的三件（跟 `desktop/src/preload.ts` 逐字同名同签名）：
//   · setTheme     —— 界面暗色靠 `prefers-color-scheme`，Electron 里那个值由
//                     nativeTheme.themeSource 决定。没有它，`d.setTheme('dark')`
//                     只写了一个 localStorage，截图还是浅色——**那会是一条假缺陷**。
//   · rememberUser —— 产品里界面定下身份后回报给主进程。假壳收下不写盘
//                     （身份由 `walkthrough_udd.write_identity` 定死，不许被覆盖）。
//   · backendInfo  —— P45 #2 那一条：界面拿它跟 `/api/health` 自报的那份对一次。
//                     假壳给的是真的那个后端的端口 / 数据目录，所以这条对得上。
//
// **故意不暴露**（走查里用得到它们的那几步在假壳上跑不了，README 的表里标着）：
//   onMenu / onFlush / flushed / pickDirectory / exportCreds / slidesToPdf / journey
const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('memoketDesktop', {
  setTheme(theme) { ipcRenderer.send('set-theme', theme) },
  rememberUser(user) { ipcRenderer.send('remember-user', user) },
  backendInfo() { return ipcRenderer.invoke('backend:info') },
})
