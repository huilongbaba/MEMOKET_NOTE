/**
 * 把 FastAPI 后端当子进程管起来。
 *
 * 桌面版不重写后端——17k 行的 harness、KITE 适配、sqlite 都在那边，重写一遍
 * 是把产品的核心扔掉。所以 Electron 干的事就是「起它、等它、收它」。
 */
import { spawn, type ChildProcess } from 'node:child_process'
import { existsSync } from 'node:fs'
import { createServer } from 'node:net'
import path from 'node:path'

export type Backend = { port: number; stop: () => void }

/** 要一个当前空闲的端口。
 *
 * **不写死 8000。** 开发机上经常已经手工跑着一个后端（我自己就撞过），写死
 * 端口的话桌面版要么起不来、要么静悄悄连到那个陈旧进程上——那比起不来更糟，
 * 因为界面看着是好的，跑的却是别人的代码。 */
function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = createServer()
    srv.on('error', reject)
    srv.listen(0, '127.0.0.1', () => {
      const addr = srv.address()
      if (addr && typeof addr === 'object') srv.close(() => resolve(addr.port))
      else reject(new Error('拿不到端口'))
    })
  })
}

/** 找 python 解释器和 backend 目录。
 *
 * 开发时用仓库里的 venv；打包之后是 PyInstaller 出来的单文件可执行程序，
 * 那时候用户机器上**不需要装 python**。 */
function locate(isPackaged: boolean, resourcesPath: string) {
  if (isPackaged) {
    const exe = path.join(resourcesPath, 'backend', 'memoket-note-backend')
    return { kind: 'bundled' as const, exe, cwd: path.dirname(exe) }
  }
  const repo = path.resolve(__dirname, '..', '..')
  const venv = path.join(repo, 'backend', '.venv', 'bin', 'python')
  if (!existsSync(venv)) {
    throw new Error(
      `找不到后端的 venv：${venv}\n` +
      `开发模式需要它。先在 backend/ 下建好虚拟环境并装依赖。`)
  }
  return { kind: 'dev' as const, exe: venv, cwd: path.join(repo, 'backend') }
}

/** 等后端真的能应答。
 *
 * **不能只看进程起没起。** uvicorn 进程存在 ≠ 能收请求：import 整个 app
 * （KITE、模型配置、sqlite 迁移）在慢机器上要好几秒，这期间开窗口就是一个
 * 连接被拒的白屏。所以轮询 /api/health 直到它回 200。 */
async function waitHealthy(port: number, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs
  let lastErr = ''
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/api/health`)
      if (r.ok) return
      lastErr = `HTTP ${r.status}`
    } catch (e) {
      lastErr = String((e as Error).message ?? e)
    }
    await new Promise((r) => setTimeout(r, 200))
  }
  throw new Error(`后端在 ${timeoutMs / 1000} 秒内没能起来（最后一次：${lastErr}）`)
}

export async function startBackend(opts: {
  isPackaged: boolean
  resourcesPath: string
  webDir: string
  /** 数据落在哪。**打包之后必须是系统的用户数据目录**——不给的话后端会用
   *  相对路径 ./data，那在 .app 里解析到包内部：macOS 的应用包在真实安装
   *  场景下只读，而且**更新时整个包会被替换，用户的笔记跟着没**。
   *  实拍踩过：第一次打包出来的 .app 把 notes.sqlite3 建在了
   *  Contents/Resources/backend/data/ 里。 */
  dataDir?: string
  onLog?: (line: string) => void
  timeoutMs?: number
}): Promise<Backend> {
  const port = await freePort()
  const { kind, exe, cwd } = locate(opts.isPackaged, opts.resourcesPath)

  const args = kind === 'dev'
    ? ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port)]
    : ['--host', '127.0.0.1', '--port', String(port)]

  const child: ChildProcess = spawn(exe, args, {
    cwd,
    env: {
      ...process.env,
      PYTHONPATH: cwd,
      // 后端据此把打包好的前端挂到 /，于是前端里所有 `/api/...` 的相对路径
      // 原样可用，桌面和网页不分叉。
      MEMOKET_NOTE_WEB_DIR: opts.webDir,
      // 让后端自己盯着我们。**stop() 靠不住**：⌘Q 走得到，SIGKILL、崩溃、
      // 活动监视器里「强制退出」都走不到，实测强杀之后 uvicorn 活了下来，
      // 占着 sqlite 和端口。后端那边看 os.getppid() 变了就退。
      MEMOKET_NOTE_PARENT_PID: String(process.pid),
      ...(opts.dataDir ? { KITE_DATA_DIR: opts.dataDir } : {}),
      PYTHONUNBUFFERED: '1',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  const log = opts.onLog ?? (() => {})
  child.stdout?.on('data', (b) => log(`[backend] ${b}`))
  child.stderr?.on('data', (b) => log(`[backend] ${b}`))

  let exited: string | null = null
  child.on('exit', (code, signal) => {
    exited = `退出码 ${code}${signal ? ` 信号 ${signal}` : ''}`
    log(`[backend] 进程结束：${exited}`)
  })

  try {
    await waitHealthy(port, opts.timeoutMs ?? 60_000)
  } catch (e) {
    child.kill('SIGKILL')
    throw new Error(`${(e as Error).message}${exited ? `；子进程已${exited}` : ''}`)
  }

  return {
    port,
    stop: () => {
      // 先好好说，不听再强制。SIGTERM 让 uvicorn 有机会关掉 sqlite 连接。
      if (child.exitCode === null && child.signalCode === null) {
        child.kill('SIGTERM')
        setTimeout(() => { try { child.kill('SIGKILL') } catch { /* 已经没了 */ } }, 3000)
      }
    },
  }
}
