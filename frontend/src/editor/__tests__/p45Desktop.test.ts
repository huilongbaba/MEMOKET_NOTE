/**
 * P45 #2 的壳那一侧：窗口永远连自己那个后端。
 *
 * 三处改动，三组闸：
 *   ① `main.ts` 的 `onCrash` 重拉之后按**新端口** `loadURL`，不是 `reload()`
 *      （原来那句注释「端口固定，地址不变」是假的——`freePort` 会退到 `preferred+k`）；
 *   ② `backend.ts` 的 `waitHealthy` 按 **pid** 核「这个端口上应答的是不是我的子进程」，
 *      对不上抛 `PortTakenError`，`startBackend` 换端口重来（`freePort` 跳过 `taken`）；
 *   ③ `/api/health` 带上后端自己的 pid / 数据目录，前端核一次（另一个文件）。
 *
 * ② 是**真跑**（起一个本机 HTTP 服务当假后端），不是读源码：`waitHealthy` 是纯
 * fetch + 定时器，跑得起来就该跑起来。① 只剩源码断言——它是 Electron 主进程里
 * 的一行，离开 Electron 摆不出来；那一条另有一份真造两份 app 的实拍（台账 P45）。
 */
import { afterEach, describe, expect, it } from 'vitest'
// @ts-expect-error vitest 跑在 node 上；前端 tsconfig 没带 node 类型
import { createServer, type Server } from 'node:http'
import mainSrc from '../../../../desktop/src/main.ts?raw'
// **真导入那份模块，不是读它的源码**。走 `import.meta.glob` 而不是直接 `import`：
// 直接写会把 `desktop/src/backend.ts` 拉进**前端的 tsconfig 工程**里，而它是 node 代码
// （`node:child_process` / `process` / `__dirname` 全不在前端的类型里），`tsc -b` 当场
// 十条红。glob 在类型上只是一张 `Record<string, () => Promise<unknown>>` 的表，
// 运行时照样是真的那份模块——量具不许把被测的东西拖进不属于它的工程。
const _backendMod = import.meta.glob('../../../../desktop/src/backend.ts')
type BackendMod = {
  waitHealthy(port: number, timeoutMs: number, ownPid?: number): Promise<number>
  freePort(isPackaged: boolean, log?: (l: string) => void, taken?: ReadonlySet<number>): Promise<number>
  PortTakenError: new (...a: never[]) => Error
}
const loadBackend = async (): Promise<BackendMod> =>
  (await Object.values(_backendMod)[0]()) as BackendMod
import backendSrc from '../../../../desktop/src/backend.ts?raw'
import preloadSrc from '../../../../desktop/src/preload.ts?raw'

// ------------------------------------------------------------------ ②

/** 假后端：`/api/health` 回一个自报 pid 的 200。 */
function fakeBackend(pid: number): Promise<{ port: number; close: () => void }> {
  return new Promise((resolve) => {
    const srv: Server = createServer((_req: unknown, res: {
      writeHead: (c: number, h: Record<string, string>) => void; end: (b: string) => void
    }) => {
      res.writeHead(200, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ status: 'ok', backend: { pid, data_dir: '/tmp/x' } }))
    })
    srv.listen(0, '127.0.0.1', () => {
      const a = srv.address() as { port: number }
      resolve({ port: a.port, close: () => srv.close() })
    })
  })
}

const opened: Array<() => void> = []
afterEach(() => { while (opened.length) opened.pop()!() })

describe('P45 #2 ② waitHealthy 按 pid 认人', () => {
  it('pid 对上了：正常返回那个 pid', async () => {
    const { waitHealthy } = await loadBackend()
    const be = await fakeBackend(4242)
    opened.push(be.close)
    await expect(waitHealthy(be.port, 3000, 4242)).resolves.toBe(4242)
  })

  it('端口上坐着别人的后端：抛 PortTakenError，不是静静接受那个 200', async () => {
    // **这就是 P44 问题 #2 那一屏**：200 漂漂亮亮，可那是另一份实例的库。
    const { waitHealthy, PortTakenError } = await loadBackend()
    const be = await fakeBackend(9999)
    opened.push(be.close)
    await expect(waitHealthy(be.port, 3000, 4242)).rejects.toBeInstanceOf(PortTakenError)
  })

  it('没传 ownPid（谁都不核）时照旧放行——这条改动不许把别的调用方判死', async () => {
    const { waitHealthy } = await loadBackend()
    const be = await fakeBackend(9999)
    opened.push(be.close)
    await expect(waitHealthy(be.port, 3000)).resolves.toBe(9999)
  })

  it('端口上没人应答：照旧是「没能起来」那条超时错，不是 PortTakenError', async () => {
    const { waitHealthy, PortTakenError } = await loadBackend()
    const be = await fakeBackend(1)
    be.close()                                   // 立刻关掉：这个端口上没人
    await expect(waitHealthy(be.port, 500, 4242)).rejects.not.toBeInstanceOf(PortTakenError)
  })

  it('freePort 跳过已证实被占的那几个端口（不然重试原地打转）', async () => {
    const { freePort } = await loadBackend()
    const p1 = await freePort(false)             // 开发档 = 47232 起
    const p2 = await freePort(false, () => {}, new Set([p1]))
    expect(p2).not.toBe(p1)
  })
})

// ------------------------------------------------------------------ ①

describe('P45 #2 ① 重拉后端之后窗口跟着改地址', () => {
  it('onCrash 里是 loadURL(appUrl(新端口))，不是 webContents.reload()', () => {
    expect(mainSrc).toMatch(/win\?\.loadURL\(appUrl\(b\.port\)\)/)
    // 「端口固定，地址不变」那句话和那一行 reload 都不许再回来
    expect(mainSrc).not.toMatch(/win\?\.webContents\.reload\(\)/)
  })
  it('端口真的换了要在落盘日志里留一句（用户报「笔记不是我的」时唯一的线索）', () => {
    expect(mainSrc).toMatch(/后端换到了 \$\{b\.port\}/)
  })
})

describe('P45 #2 ③ 「我连的是谁」这条通道是接上的', () => {
  it('主进程报 port / pid / dataDir', () => {
    expect(mainSrc).toMatch(/ipcMain\.handle\('backend:info'/)
    expect(mainSrc).toMatch(/pid: backend\.pid/)
  })
  it('preload 把它露给界面', () => {
    expect(preloadSrc).toMatch(/backendInfo\(\)/)
    expect(preloadSrc).toMatch(/ipcRenderer\.invoke\('backend:info'\)/)
  })
  it('Backend 带着 pid 出来（不带的话上面两条无从报起）', () => {
    expect(backendSrc).toMatch(/pid: child\.pid \?\? 0/)
  })
  it('抢输了那一档要先把自己的子进程收掉，再换端口重来', () => {
    expect(backendSrc).toMatch(/if \(e instanceof PortTakenError\) throw e/)
    expect(backendSrc).toMatch(/taken\.add\(e\.port\)/)
  })
})
