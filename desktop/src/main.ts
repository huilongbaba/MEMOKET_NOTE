/**
 * MEMOKET NOTE 桌面版的主进程。
 *
 * 三件事：起后端、开窗口、退出时收干净。界面本身全在渲染进程里，跟网页版
 * 是同一份代码——**桌面和网页不分叉**，这是 backend 自己托管前端换来的。
 */
import { nativeTheme, app, BrowserWindow, Menu, dialog, shell, ipcMain, session, screen } from 'electron'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'

import { startBackend, type Backend } from './backend.js'

// **--dev 只管开不开 devtools。** 「前端从哪来」必须看 app.isPackaged：
// 用命令行标志决定的话，忘了带 --dev 就会去找打包后才存在的目录，后端挂不上
// 前端，窗口里甩出一个裸的 {"detail":"Not Found"}——第一次跑就踩了。
const wantDevTools = process.argv.includes('--dev')
/** `--user=xxx`：用指定身份打开。开发和排查时用——不给的话渲染进程会给
 *  自己造一个随机用户，看到的是空库。 */
const forcedUser = process.argv.find((a) => a.startsWith('--user='))?.slice(7)
/** `--probe=xxx`：把界面驱动到某个状态供截图核对（右键菜单、弹层这些只有
 *  交互之后才存在的东西）。正常使用时不带这个参数，那段代码一次都不会跑。 */
const probe = process.argv.find((a) => a.startsWith('--probe='))?.slice(8)
/** `--dark` / `--light`：强制主题，给截图核对暗色用——不用去系统设置里来回切。 */
const forcedTheme = process.argv.includes('--dark') ? 'dark' : process.argv.includes('--light') ? 'light' : null
/** `--shot=/path.png [--shot-delay=ms]`：页面加载完等一会儿，用 webContents.capturePage
 *  把窗口内容存成 PNG 然后退出。给截图核对用——比 screencapture 可靠：不依赖窗口
 *  在不在前台、桌面有没有被切走、有没有辅助功能权限。 */
const shotPath = process.argv.find((a) => a.startsWith('--shot='))?.slice(7)
// 多个延迟用逗号隔开：`--shot-delay=20000,60000` → 各截一张（文件名加 -1 / -2），
// 看一个跑几分钟的过程（智能续写）中间长什么样。
const shotDelays = (process.argv.find((a) => a.startsWith('--shot-delay='))?.slice(13) ?? '9000')
  .split(',').map((s) => Number(s)).filter((n) => n > 0)

/** 身份落在主进程的文件里，不只靠渲染进程的 localStorage。
 *  实拍：localStorage 丢过一次（端口变了 / leveldb 锁），界面随手生成了 user-4u6jzn，
 *  用户打开看到一个空库——23 篇笔记都在 terrence 名下好好的，只是身份换了。
 *  渲染进程每次定下身份就回报一次（remember-user），主进程写进 identity.json；
 *  下次启动把它塞进 ?user=，localStorage 再丢也认得回来。探针 / --user 强制时不写。 */
const identityFile = () => path.join(app.getPath('userData'), 'identity.json')
function loadIdentity(): string | undefined {
  try {
    const u = (JSON.parse(readFileSync(identityFile(), 'utf8')) as { user?: string }).user
    return typeof u === 'string' && /^[\w.-]{1,64}$/.test(u) ? u : undefined
  } catch { return undefined }
}
function saveIdentity(user: string) {
  try { writeFileSync(identityFile(), JSON.stringify({ user, saved_at: new Date().toISOString() })) } catch { /* 写不了就下次再说 */ }
}

function appUrl(port: number): string {
  const q = new URLSearchParams()
  const user = forcedUser ?? (probe ? undefined : loadIdentity())
  if (user) q.set('user', user)
  if (probe) q.set('probe', probe)
  const s = q.toString()
  return `http://127.0.0.1:${port}/` + (s ? `?${s}` : '')
}
let backend: Backend | null = null
let win: BrowserWindow | null = null
const logs: string[] = []

function remember(line: string) {
  logs.push(line.trimEnd())
  if (logs.length > 400) logs.shift()      // 只留最近的，别把内存吃光
  process.stdout.write(line)
}

const boundsFile = () => path.join(app.getPath('userData'), 'window.json')

function loadBounds(): { x?: number; y?: number; width: number; height: number } | null {
  try {
    const b = JSON.parse(readFileSync(boundsFile(), 'utf8')) as { x?: number; y?: number; width: number; height: number }
    if (!b || !b.width || !b.height) return null
    // 显示器换了（外接屏拔了）就别把窗口放到看不见的地方
    const onScreen = screen.getAllDisplays().some((d) => {
      const a = d.workArea
      return b.x !== undefined && b.y !== undefined && b.x >= a.x - 50 && b.y >= a.y - 50
        && b.x < a.x + a.width - 100 && b.y < a.y + a.height - 100
    })
    return onScreen ? b : { width: b.width, height: b.height }
  } catch { return null }
}

let boundsTimer: NodeJS.Timeout | null = null
function rememberBounds(w: BrowserWindow) {
  if (boundsTimer) clearTimeout(boundsTimer)
  boundsTimer = setTimeout(() => {
    try { if (!w.isDestroyed() && !w.isFullScreen()) writeFileSync(boundsFile(), JSON.stringify(w.getBounds())) } catch { /* 无所谓 */ }
  }, 400)
}

// 退出前让界面把没存的正文存完：自动保存有 1.5 秒防抖，⌘Q 正好卡在这 1.5 秒里
// 就丢最后几句。主进程先拦一次退出，问界面一声，存完（或 800ms 没回音）再真退。
let flushed = false
function flushThenQuit(e: Electron.Event) {
  if (flushed || !win || win.isDestroyed()) return
  e.preventDefault()
  const started = Date.now()
  const done = () => { if (flushed) return; flushed = true; remember(`[desktop] 退出前保存：界面 ${Date.now() - started}ms 后回应`); app.quit() }
  ipcMain.once('flushed', done)
  win.webContents.send('flush')
  setTimeout(done, 800)
}

function createWindow(url: string) {
  // `--win=WxH`：截图核对窄窗口用
  const winArg = process.argv.find((a) => a.startsWith('--win='))?.slice(6).split('x').map(Number)
  // 上次的窗口位置和大小（Trilium 也记）。探针传了 --win 就不用。
  const saved = (winArg || probe) ? null : loadBounds()   // 探针要固定尺寸的截图
  win = new BrowserWindow({
    ...(saved ?? {}),
    width: winArg?.[0] || saved?.width || 1440,
    height: winArg?.[1] || saved?.height || 900,
    minWidth: 900,
    minHeight: 600,
    // 左上角留出红绿灯的位置——照 Trilium 的做法，标题栏交给界面自己画，
    // 启动栏顶部会空出一块给系统按钮。
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#ffffff',
    show: false,
    webPreferences: {
      // 渲染进程里跑的是纯网页代码，不需要 node。关掉是默认该有的姿势：
      // 这个界面会渲染知识库里的内容和模型写出来的文本。
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  })

  win.once('ready-to-show', () => win?.show())
  win.on('closed', () => { win = null })

  // 外链走系统浏览器，不在应用里开一个没有地址栏的窗口。
  win.webContents.setWindowOpenHandler(({ url: target }) => {
    if (/^https?:/.test(target)) shell.openExternal(target)
    return { action: 'deny' }
  })

  win.on('resize', () => win && rememberBounds(win))
  win.on('move', () => win && rememberBounds(win))
  win.loadURL(url)
  if (wantDevTools) win.webContents.openDevTools({ mode: 'detach' })
  if (shotPath) {
    win.webContents.once('did-finish-load', () => {
      shotDelays.forEach((delay, i) => {
        setTimeout(async () => {
          const file = shotDelays.length === 1 ? shotPath : shotPath.replace(/\.png$/, '') + `-${i + 1}.png`
          try {
            const img = await win!.webContents.capturePage()
            writeFileSync(file, img.toPNG())
            process.stdout.write(`[shot] ${file} ${img.getSize().width}x${img.getSize().height}\n`)
          } catch (e) { process.stderr.write(`[shot] failed: ${e}\n`) }
          if (i === shotDelays.length - 1) app.quit()
        }, delay)
      })
    })
  }
}

let quitting = false
let restarts = 0

/** 拉起后端；崩了自动再拉一次并刷新窗口（端口固定，地址不变）。
 *  连崩两次就不再硬撑——那多半是数据或环境的问题，弹框把日志给用户。 */
async function launchBackend(webDir: string): Promise<Backend> {
  return startBackend({
    isPackaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
    webDir,
    // 打包之后数据落在系统的用户数据目录（macOS 上是
    // ~/Library/Application Support/<appName>）。开发时不传，后端保持
    // 相对 ./data，跟手工起后端时用的是同一个库。
    dataDir: app.isPackaged ? path.join(app.getPath('userData'), 'data') : undefined,
    onLog: remember,
    onCrash: (info) => {
      if (quitting) return
      remember(`[desktop] 后端崩了（${info}），${restarts < 2 ? '重新拉起' : '不再重试'}`)
      if (restarts >= 2) {
        dialog.showErrorBox('后端反复崩溃',
          `已经自动重启过两次，不再重试。\n\n最后几行日志：\n${logs.slice(-12).join('\n') || '（没有输出）'}`)
        return
      }
      restarts += 1
      backend = null
      setTimeout(() => {
        void launchBackend(webDir).then((b) => {
          backend = b
          win?.webContents.reload()
        }).catch((e) => {
          dialog.showErrorBox('后端没能重新启动',
            `${(e as Error).message}\n\n最后几行日志：\n${logs.slice(-12).join('\n') || '（没有输出）'}`)
        })
      }, 800)
    },
  })
}

async function boot() {
  const webDir = app.isPackaged
    ? path.join(process.resourcesPath, 'web')
    : path.resolve(__dirname, '..', '..', 'frontend', 'dist')

  // 前端没构建就当场说清楚。不检查的话症状是窗口里一行 JSON 404——
  // 那个错误信息跟真实原因（少跑了一次 npm run build）毫无关系。
  if (!existsSync(path.join(webDir, 'index.html'))) {
    dialog.showErrorBox(
      '前端还没构建',
      `${webDir} 下没有 index.html。\n\n` +
      (app.isPackaged
        ? '这个安装包不完整，请重新安装。'
        : '开发模式下先构建一次前端：\n    cd frontend && npm run build'))
    app.quit()
    return
  }

  try {
    backend = await launchBackend(webDir)
  } catch (e) {
    // **起不来要说清是什么原因。** 一个白窗口或者静默退出，用户除了重装
    // 什么都做不了；后端最后几行日志几乎总能指出真正的毛病。
    dialog.showErrorBox(
      '后端没能启动',
      `${(e as Error).message}\n\n最后几行日志：\n${logs.slice(-12).join('\n') || '（没有输出）'}`)
    app.quit()
    return
  }
  createWindow(appUrl(backend.port))
}

if (forcedTheme) nativeTheme.themeSource = forcedTheme
// 设置页的「外观」：跟随系统 / 浅色 / 深色。截图探针强制的主题优先。
ipcMain.on('remember-user', (_e, user: unknown) => {
  if (forcedUser || probe) return
  if (typeof user === 'string' && /^[\w.-]{1,64}$/.test(user) && user !== loadIdentity()) {
    saveIdentity(user)
    remember(`[desktop] 记住身份 ${user}`)
  }
})
// 导回 Obsidian 要选 vault 目录：网页拿不到本机路径，只能主进程弹系统对话框
ipcMain.handle('pick-directory', async (_e, title: unknown) => {
  const r = await dialog.showOpenDialog({ title: typeof title === 'string' ? title : '选择文件夹', properties: ['openDirectory', 'createDirectory'] })
  return r.canceled ? '' : (r.filePaths[0] || '')
})
ipcMain.on('set-theme', (_e, theme: unknown) => {
  if (forcedTheme) return
  if (theme === 'system' || theme === 'light' || theme === 'dark') nativeTheme.themeSource = theme
})

/** 应用菜单。macOS 上没有它，⌘C/⌘V 这些 role 快捷键在 Electron 里不生效；
 *  缩放三件套（⌘= / ⌘- / ⌘0）也从这里来——照 Trilium 的 zoomIn/Out/Reset。 */
function installMenu() {
  const isMac = process.platform === 'darwin'
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    ...(isMac ? [{ role: 'appMenu' as const }] : []),
    {
      // Trilium 的 File 菜单：新建 / 日记 / 导入 / 导出都在这儿，不只一个「关闭窗口」（第 167 轮）。
      // 快捷键只是显示：真正的按键在渲染进程里处理，这里 click 发同名事件。
      label: '文件',
      submenu: [
        // registerAccelerator: false = 菜单上只显示快捷键、不向系统注册——按键还是渲染进程处理，
        // 否则 ⌘N 会被菜单吃掉再发一次事件（或者两边各建一篇）
        { label: '新建笔记', accelerator: 'CommandOrControl+N', registerAccelerator: false, click: () => win?.webContents.send('menu', 'new-note') },
        { label: '今天的日记', accelerator: 'CommandOrControl+Shift+D', registerAccelerator: false, click: () => win?.webContents.send('menu', 'today') },
        { type: 'separator' as const },
        { label: '导入…', click: () => win?.webContents.send('menu', 'import') },
        { label: '导出全部笔记…', click: () => win?.webContents.send('menu', 'export-all') },
        { label: '最近删除', click: () => win?.webContents.send('menu', 'trash') },
        { type: 'separator' as const },
        { role: 'close' as const, label: '关闭窗口' },
      ],
    },
    { role: 'editMenu' as const },
    {
      label: '视图',
      submenu: [
        { role: 'resetZoom' as const, label: '实际大小' },
        { role: 'zoomIn' as const, label: '放大', accelerator: 'CommandOrControl+=' },
        { role: 'zoomOut' as const, label: '缩小' },
        { type: 'separator' as const },
        { role: 'togglefullscreen' as const },
        { role: 'toggleDevTools' as const },
      ],
    },
    { role: 'windowMenu' as const },
    {
      // Trilium 的 Help 菜单：快捷键、数据在哪、日志在哪、去哪报问题
      label: '帮助',
      submenu: [
        { label: '快捷键一览', accelerator: 'CommandOrControl+/', click: () => win?.webContents.send('menu', 'shortcuts') },
        { type: 'separator' as const },
        { label: '导出全部笔记…', click: () => win?.webContents.send('menu', 'export-all') },
        { label: '打开备份文件夹', click: () => { void shell.openPath(path.join(app.isPackaged ? path.join(app.getPath('userData'), 'data') : path.resolve(__dirname, '..', '..', 'backend', 'data'), 'backups')) } },
        { label: '打开数据文件夹', click: () => { void shell.openPath(app.isPackaged ? path.join(app.getPath('userData'), 'data') : path.resolve(__dirname, '..', '..', 'backend', 'data')) } },
        { label: '导出后端日志…', click: () => {
          const file = path.join(app.getPath('logs'), `memoket-note-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.log`)
          try { writeFileSync(file, logs.join('\n') + '\n', 'utf8'); shell.showItemInFolder(file) }
          catch (e) { dialog.showErrorBox('导出失败', String(e)) }
        } },
        { type: 'separator' as const },
        { label: '报告问题', click: () => { void shell.openExternal('https://github.com/huilongbaba/MEMOKET_NOTE/issues') } },
      ],
    },
  ]))
}

// 开发 / 探针跑的实例用自己的 userData：不然它跟装好的正式版共用一个
// Local Storage（leveldb 只允许一个进程持锁），正式版开着时探针那份的
// localStorage 会静默变成内存版——实拍「选了深色重开是浅色」查了三层
// （端口、刷盘）最后是这个。
if (!app.isPackaged) app.setPath('userData', app.getPath('userData') + '-dev')

// 单实例（Trilium 同款）：第二份直接把第一份的窗口拉到前面。两份同时跑会
// 抢同一个 sqlite 和 localStorage，界面看着正常、数据各写各的。
if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (win) { if (win.isMinimized()) win.restore(); win.focus() }
  })
  app.whenReady().then(() => { installMenu(); return boot() })
}

app.on('window-all-closed', () => {
  // macOS 的习惯是关窗不退出；但后端是这个 app 的子进程，留着它空跑没有意义
  // ——重新激活时 boot() 会再起一个。
  backend?.stop()
  backend = null
  if (process.platform !== 'darwin') app.quit()
})

app.on('activate', () => {
  if (win) return
  if (backend) createWindow(appUrl(backend.port))
  else void boot()
})

// 退出路径不止一条（⌘Q、关窗、崩溃），每条都要收掉子进程，否则会留下一个
// 占着端口和 sqlite 的孤儿进程。
// localStorage（标签页 / 分屏 / 外观…）是 Chromium 攒着慢慢落盘的，退出得快
// 就丢：实拍「设置里选深色 → 重开是浅色」，client-log 证实同一 origin 下
// 上次存的值没了。退出前强制刷盘。
app.on('before-quit', (e) => {
  flushThenQuit(e)
  if (!flushed) return
  quitting = true
  try { session.defaultSession.flushStorageData() } catch { /* 没有 session 时无所谓 */ }
  backend?.stop()
})
process.on('exit', () => backend?.stop())
