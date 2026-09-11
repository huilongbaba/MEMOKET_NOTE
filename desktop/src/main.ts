/**
 * MEMOKET NOTE 桌面版的主进程。
 *
 * 三件事：起后端、开窗口、退出时收干净。界面本身全在渲染进程里，跟网页版
 * 是同一份代码——**桌面和网页不分叉**，这是 backend 自己托管前端换来的。
 */
import { nativeTheme, app, BrowserWindow, Menu, dialog, shell } from 'electron'
import { existsSync, writeFileSync } from 'node:fs'
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

function appUrl(port: number): string {
  const q = new URLSearchParams()
  if (forcedUser) q.set('user', forcedUser)
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

function createWindow(url: string) {
  win = new BrowserWindow({
    width: 1440,
    height: 900,
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
    },
  })

  win.once('ready-to-show', () => win?.show())
  win.on('closed', () => { win = null })

  // 外链走系统浏览器，不在应用里开一个没有地址栏的窗口。
  win.webContents.setWindowOpenHandler(({ url: target }) => {
    if (/^https?:/.test(target)) shell.openExternal(target)
    return { action: 'deny' }
  })

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
    backend = await startBackend({
      isPackaged: app.isPackaged,
      resourcesPath: process.resourcesPath,
      webDir,
      // 打包之后数据落在系统的用户数据目录（macOS 上是
      // ~/Library/Application Support/<appName>）。开发时不传，后端保持
      // 相对 ./data，跟手工起后端时用的是同一个库。
      dataDir: app.isPackaged ? path.join(app.getPath('userData'), 'data') : undefined,
      onLog: remember,
    })
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

/** 应用菜单。macOS 上没有它，⌘C/⌘V 这些 role 快捷键在 Electron 里不生效；
 *  缩放三件套（⌘= / ⌘- / ⌘0）也从这里来——照 Trilium 的 zoomIn/Out/Reset。 */
function installMenu() {
  const isMac = process.platform === 'darwin'
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    ...(isMac ? [{ role: 'appMenu' as const }] : []),
    { role: 'fileMenu' as const },
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
  ]))
}

app.whenReady().then(() => { installMenu(); return boot() })

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
app.on('before-quit', () => backend?.stop())
process.on('exit', () => backend?.stop())
