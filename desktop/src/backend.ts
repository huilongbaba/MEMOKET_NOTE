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

/** 把流的 data 块切成整行再交给 emit；半行留到下一块再拼，流结束时 flush 剩下的。 */
export function lineTagger(emit: (line: string) => void) {
  let rest = ''
  const push = (b: Buffer | string) => {
    rest += String(b)
    const parts = rest.split(/\r?\n/)
    rest = parts.pop() ?? ''
    for (const l of parts) emit(l)
  }
  const flush = () => { if (rest) { emit(rest); rest = '' } }
  return { push, flush }
}

export type Backend = {
  port: number
  /** 这个端口上的后端**是哪个进程**（P45 #2）。窗口刷新 / 自检都拿它核身份。 */
  pid: number
  stop: () => void
}

/** 「这个端口上应答的不是我起的那个后端」——**别人的实例抢在了前面**。
 *
 * `freePort` 是「先 listen 一个探测 server、再 close、再让 uvicorn 去 bind」，
 * close 到 bind 之间那一小段足够同机上另一份 app 抢走同一个端口（P44 问题 #2
 * 的下半截）。**这条 TOCTOU 堵不住**（要堵得把探测 socket 的 fd 直接交给
 * uvicorn，跨 Electron / PyInstaller 两种起法都得改）——所以不假装堵住它，
 * 改成**认得出来**：健康检查里带着后端自己的 pid，对不上就换个端口重来。
 *
 * 判据是**代码判得准**的那一种（两个整数相等），不是「看着像不像」。 */
export class PortTakenError extends Error {
  constructor(readonly port: number, readonly theirPid: number, readonly myPid: number) {
    super(`端口 ${port} 上应答的是另一份实例的后端（pid ${theirPid}，我的是 ${myPid}）`)
    this.name = 'PortTakenError'
  }
}

/** 要一个端口：优先固定的那个，被占了才随机。
 *
 * **不写死 8000。** 开发机上经常已经手工跑着一个后端（我自己就撞过），写死
 * 端口的话桌面版要么起不来、要么静悄悄连到那个陈旧进程上——那比起不来更糟，
 * 因为界面看着是好的，跑的却是别人的代码。
 *
 * **但也不能每次都随机。** 页面的 origin 是 `http://127.0.0.1:<port>`，
 * localStorage 按 origin 隔离——端口一变，标签页、分屏、右栏、外观这些存在
 * localStorage 里的状态每次启动全部清零（实拍：设置里选了深色，重开是浅色）。
 * 所以先试一个冷门的固定端口；真被占了（多开一份、或者上次的进程还没退干净）
 * 再退回随机，这时状态丢一次，总比起不来强。 */
/** 正式版 47231；开发 / 探针实例 47232——两者经常同时开着，各用各的。 */
const PREFERRED_PORT = { packaged: 47231, dev: 47232 }

function listenFree(port: number): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = createServer()
    srv.on('error', reject)
    srv.listen(port, '127.0.0.1', () => {
      const addr = srv.address()
      if (addr && typeof addr === 'object') srv.close(() => resolve(addr.port))
      else reject(new Error('拿不到端口'))
    })
  })
}

/** @param taken 这次启动里**已经证实被别人占着**的端口（`PortTakenError` 攒出来的）：
 *               探测说「空着」也不信，直接跳过。不跳的话重试会原地打转（P45 #2）。 */
export async function freePort(isPackaged: boolean, log: (line: string) => void = () => {},
                               taken: ReadonlySet<number> = new Set()): Promise<number> {
  const preferred = isPackaged ? PREFERRED_PORT.packaged : PREFERRED_PORT.dev
  // 上一份进程 ⌘Q 之后 uvicorn 还要一两秒才真正退出、放开端口；紧接着重开
  // 会撞上它。等一小会儿再放弃，不然「重启一下」就把状态清零了。
  if (!taken.has(preferred)) {
    for (let i = 0; i < 20; i++) {
      try { return await listenFree(preferred) } catch { await new Promise((r) => setTimeout(r, 250)) }
    }
  }
  // P17 实拍：正式版开着（占 47231）再起一份，每次都退回随机端口——origin 每次不同，localStorage
  // 每次清零（标签 / 主题 / 托盘全没）。先按顺序试后面几个固定端口，同一台机上第二份也能稳定在同一个 origin 上。
  for (let k = 1; k <= 8; k++) {
    if (taken.has(preferred + k)) continue
    try {
      const p = await listenFree(preferred + k)
      log(`[desktop] 固定端口 ${preferred} 被占，改用 ${p}（下次也先试它）\n`)
      return p
    } catch { /* 下一个 */ }
  }
  const p = await listenFree(0)
  // 走 onLog 而不是 console.warn：这句要进落盘日志（用户报「设置全没了」时，唯一的线索就是它）
  log(`[desktop] 固定端口 ${preferred} 一直被占，退回随机端口 ${p}（本次 localStorage 状态会丢）\n`)
  return p
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
export async function waitHealthy(port: number, timeoutMs: number, ownPid?: number): Promise<number> {
  const deadline = Date.now() + timeoutMs
  let lastErr = ''
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/api/health`)
      if (r.ok) {
        // **200 不等于「是我的那个后端」**（P45 #2）。同机第二份实例起来时，
        // `freePort` 的探测和 uvicorn 真 bind 之间那一小段被别人抢走，这里照样
        // 会拿到一个漂漂亮亮的 200 ——**那是别人的库**。健康检查里带着后端自己的
        // pid，两个整数一比就知道；对不上是 `PortTakenError`，由 `startBackend`
        // 换个端口重来，而不是把窗口接到别人身上（P44 靠 `lsof` 才发现的那一条）。
        const who = (await r.json().catch(() => null)) as { backend?: { pid?: number } } | null
        const theirPid = Number(who?.backend?.pid ?? 0)
        if (ownPid && theirPid && theirPid !== ownPid) throw new PortTakenError(port, theirPid, ownPid)
        return theirPid
      }
      lastErr = `HTTP ${r.status}`
    } catch (e) {
      if (e instanceof PortTakenError) throw e
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
  /** 屏幕活动的段落落在哪。**必须由壳告诉后端，不能让后端去猜**：采集在壳里、
   *  读取在后端，两边各自拼一次 `<userData>/journey` 就会在开发时对不上
   *  （开发的 userData 带 `-dev` 后缀），于是壳一直在记、「今天」页一直是空的。
   *  实拍踩过（第 636 轮）。 */
  journeyDir?: string
  onLog?: (line: string) => void
  timeoutMs?: number
  /** 子进程**不是我们叫停的**却退出了（崩了、被系统杀了）。主进程据此决定要不要拉起一个新的。 */
  onCrash?: (info: string) => void
}): Promise<Backend> {
  const log = opts.onLog ?? (() => {})
  // **端口被别人抢走是要重来的，不是要报错的**（P45 #2）。`freePort` 的探测
  // 只能说「刚才那一刻空着」；真相由 `waitHealthy` 的 pid 核对给出。抢输了就
  // 把那个端口记进 `taken`、换一个重来。三次是因为「同机同时起三份」已经不是
  // 用户场景，而无上限的重试会把「后端起不来」变成一个永远不结束的转圈。
  const taken = new Set<number>()
  for (let attempt = 1; ; attempt++) {
    try {
      return await spawnOn(opts, log, taken)
    } catch (e) {
      if (!(e instanceof PortTakenError) || attempt >= 3) throw e
      taken.add(e.port)
      log(`[desktop] ${e.message}——换一个端口重来（第 ${attempt} 次）\n`)
    }
  }
}

async function spawnOn(opts: Parameters<typeof startBackend>[0], log: (line: string) => void,
                       taken: ReadonlySet<number>): Promise<Backend> {
  const port = await freePort(opts.isPackaged, log, taken)
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
      ...(opts.journeyDir ? { MEMOKET_JOURNEY_DIR: opts.journeyDir } : {}),
      PYTHONUNBUFFERED: '1',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  // 按行打 [backend] 标：一个 data 块常常带好几行（uvicorn 启动那几句一起来），原来只给块首那行
  // 加前缀，落盘日志里就有一堆裸的「INFO: Waiting for application startup.」（第 481 轮翻日志 117 行）。
  // 半行留到下一块再拼，别把一行拆成两条。
  const out = lineTagger((l) => log(`[backend] ${l}\n`)); const err = lineTagger((l) => log(`[backend] ${l}\n`))
  child.stdout?.on('data', out.push)
  child.stderr?.on('data', err.push)
  child.stdout?.on('end', out.flush)
  child.stderr?.on('end', err.flush)

  let exited: string | null = null
  let stopping = false
  let healthy = false
  child.on('exit', (code, signal) => {
    exited = `退出码 ${code}${signal ? ` 信号 ${signal}` : ''}`
    log(`[backend] 进程结束：${exited}`)
    // 起来过、又不是我们叫停的 → 崩了。启动阶段的失败走 waitHealthy 那条错误路径。
    if (healthy && !stopping) opts.onCrash?.(exited)
  })

  try {
    await waitHealthy(port, opts.timeoutMs ?? 60_000, child.pid)
    healthy = true
  } catch (e) {
    // 抢输了那一档：**我们自己的子进程照样得收掉**（它多半正在 EADDRINUSE 里
    // 打转，或者还没来得及失败）。杀完把 `PortTakenError` 原样抛出去，
    // `startBackend` 据此换端口重来；别的错照旧包一层往上报。
    child.kill('SIGKILL')
    if (e instanceof PortTakenError) throw e
    throw new Error(`${(e as Error).message}${exited ? `；子进程已${exited}` : ''}`)
  }

  return {
    port,
    pid: child.pid ?? 0,
    stop: () => {
      stopping = true
      // 先好好说，不听再强制。SIGTERM 让 uvicorn 有机会关掉 sqlite 连接。
      if (child.exitCode === null && child.signalCode === null) {
        child.kill('SIGTERM')
        setTimeout(() => { try { child.kill('SIGKILL') } catch { /* 已经没了 */ } }, 3000)
      }
    },
  }
}
