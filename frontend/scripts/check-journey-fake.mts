/** 假采集源那个注入口（第 794 轮 / P52，P50「留给下一批」①）。
 *
 * **为什么这条闸值得单独有一份**：`makeRecorder` 的第四个参数是走查唯一一条
 * 「不真开屏幕录制也能把采集循环跑起来」的路——P20 #4 / #6 那几格
 * （暂停到点自己醒 / 锁屏别解掉用户的暂停 / 「自动描述停了：<原因>」）
 * 从第 778 轮起三次走查都写着「没摆出来」，就是因为没有它。
 * 这条路一坏，下一次走查又只能写「没摆出来」，而且**不会有任何东西红**。
 *
 * 四件事：
 *   ① `capture.ts` 能当**普通模块** import（一行 electron 都不许有，
 *      跟 `check-journey-merge.mts` 同一条理由）。
 *   ② 注入进去的那个源**真的被用了**：`blind` 的源要让状态变成 `no-permission`。
 *   ③ 正常的假源真的把一段写进 `segments.json`，图是那张 1px 的（= 来自假源，
 *      不是 `screencapture` 拍的）。
 *   ④ **默认值没被动过**：不给第四个参数时用的是 `REAL_SOURCE`（产品行为不变）。
 *
 *     npx tsx scripts/check-journey-fake.mts
 */
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { dayDir, fakeSource, makeRecorder, onPowerEvent, REAL_SOURCE, type CaptureState, type Segment } from '../../desktop/src/capture.ts'

let bad = 0
const ok = (cond: boolean, why: string, extra = '') => {
  console.log(`${cond ? '✓' : '✗'} ${why}`)
  if (!cond) { bad++; if (extra) console.log(`    ${extra}`) }
}
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))

// ——— ① 一行 electron 都不许有 ————————————————————————————————
{
  const here = path.dirname(fileURLToPath(import.meta.url))
  const src = readFileSync(path.join(here, '../../desktop/src/capture.ts'), 'utf8')
  ok(!/from ['"]electron['"]/.test(src) && !/require\(['"]electron['"]\)/.test(src),
     'capture.ts 里没有 electron —— 对拍脚本才 import 得动')
}

// ——— ④ 默认值还是真的那一套 ————————————————————————————————
//
// **不能靠跑一遍来验**：真的那一套第一步就是 `screencapture`，在这台机器上跑
// 等于给用户的屏幕拍一张。所以判的是「默认参数指着 REAL_SOURCE 这个对象」，
// 而 `REAL_SOURCE` 的四个成员各自是不是真的那四个函数，在下面一格单独判。
{
  const here = path.dirname(fileURLToPath(import.meta.url))
  const src = readFileSync(path.join(here, '../../desktop/src/capture.ts'), 'utf8')
  ok(/src: CaptureSource = REAL_SOURCE/.test(src),
     '不给第四个参数时用的是 REAL_SOURCE —— 产品行为一个字没变')
  ok(REAL_SOURCE.front.name === 'frontApp' && REAL_SOURCE.shot.name === 'shot'
     && REAL_SOURCE.hash.name === 'dhash' && REAL_SOURCE.frame.name === 'saveFrame',
     'REAL_SOURCE 挂的就是 osascript / screencapture / sips 那四个',
     [REAL_SOURCE.front.name, REAL_SOURCE.shot.name, REAL_SOURCE.hash.name, REAL_SOURCE.frame.name].join(' '))
}

// ——— ② / ③ 真把采集循环跑起来（一张屏都不拍）————————————————————
const logs: string[] = []
const log = (s: string) => { logs.push(s.trim()) }

{
  const ud = mkdtempSync(path.join(tmpdir(), 'p52-fake-'))
  const rec = makeRecorder(ud, log, () => 0, fakeSource({
    windows: [{ app: 'Code', title: 'capture.ts — MEMOKET_NOTE' }],
  }))
  rec.start()
  await wait(600)                       // start() 会立刻 void tick() 一次
  const dir = dayDir(ud)
  const f = path.join(dir, 'segments.json')
  ok(existsSync(f), '假采集源真的把一段落到了盘上', dir)
  const segs = existsSync(f) ? JSON.parse(readFileSync(f, 'utf8')) as Segment[] : []
  ok(segs.length === 1 && segs[0].app === 'Code', '段上写的是假源给的那个窗口',
     JSON.stringify(segs).slice(0, 200))
  const png = segs[0]?.frames?.[0]
  const bytes = png && existsSync(png) ? readFileSync(png) : null
  // **判据宁可窄一点**：不写死字节数（换一张占位图这条闸就该跟着走），判的是
  // 「这是一张几十字节的 PNG」——`screencapture` 拍一屏是几百 KB，差着四个数量级。
  ok(!!bytes && bytes.length < 200 && bytes.subarray(1, 4).toString() === 'PNG',
     '大图是假源那张 1px 的 PNG（几十字节）—— 不是 screencapture 拍来的',
     png ? `${png} ${bytes ? bytes.length : '不存在'} 字节` : '没有 frames')
  const th = segs[0]?.thumb
  ok(!!th && existsSync(th) && readFileSync(th).length === (bytes?.length ?? -1),
     '缩略图也是假源写的那一张（跟大图逐字节同一份）', String(th))
  ok(rec.state() === 'running', '状态是 running', rec.state())
  rec.stop()
  rmSync(ud, { recursive: true, force: true })
}

{
  // `blind`：一张都拍不到 → 走 `no-permission` 那一路。
  // **这一格证明「注入进去的那个源真的被用了」**：它换掉的正是 `shot`。
  const ud = mkdtempSync(path.join(tmpdir(), 'p52-blind-'))
  const rec = makeRecorder(ud, log, () => 0, fakeSource({
    windows: [{ app: 'Code', title: 'x' }], blind: true,
  }))
  rec.start()
  await wait(600)
  ok(rec.state() === 'no-permission', '拍不到就变 no-permission（托盘那个 ⚠）', rec.state())
  ok(logs.some((l) => l.includes('截不到屏')), '日志里那一行也在', logs.join(' | '))
  rec.stop()
  rmSync(ud, { recursive: true, force: true })
}

{
  // 换窗口就切段：哈希由「第几个窗口」算出来，所以这件事是**摆出来的**不是碰运气。
  const ud = mkdtempSync(path.join(tmpdir(), 'p52-two-'))
  const src = fakeSource({ windows: [{ app: 'Code', title: 'a' }, { app: 'Safari', title: 'b' }] })
  const a = await src.front(); const ha = await src.hash('', '')
  const b = await src.front(); const hb = await src.hash('', '')
  ok(a.app === 'Code' && b.app === 'Safari', '窗口按顺序轮着来', `${a.app} → ${b.app}`)
  ok(ha !== hb, '换了窗口哈希就不一样（= 画面换了 → 切段）', `${ha} ${hb}`)
  const src2 = fakeSource({ windows: [{ app: 'Code', title: 'a' }], hold: 3 })
  await src2.front(); const h1 = await src2.hash('', '')
  await src2.front(); const h2 = await src2.hash('', '')
  ok(h1 === h2, '同一个窗口两次采样哈希一模一样（= 不切段）', `${h1} ${h2}`)
  rmSync(ud, { recursive: true, force: true })
}

// ——— 锁屏 / 解锁那一下（P20 #6，走查里摆不出来，只能靠这条闸）—————————
//
// 「明确的动作要赢过被动规则」：用户自己按的暂停，不因为一次锁屏解锁就被替他打开。
{
  const cases: [string, 'lock' | 'unlock', CaptureState, boolean, 'pause' | 'resume' | null][] = [
    ['记录中锁屏 → 自动暂停', 'lock', 'running', false, 'pause'],
    ['自己暂停着又锁屏 → 什么都不做', 'lock', 'paused', false, null],
    ['没开过就锁屏 → 什么都不做', 'lock', 'off', false, null],
    ['权限没了时锁屏 → 什么都不做', 'lock', 'no-permission', false, null],
    ['自动暂停的解锁 → 恢复', 'unlock', 'paused', true, 'resume'],
    ['**用户自己按的暂停，解锁不许替他打开**', 'unlock', 'paused', false, null],
    ['自动暂停之后用户又自己停掉了 → 不恢复', 'unlock', 'off', true, null],
    ['没暂停过的解锁 → 什么都不做', 'unlock', 'running', false, null],
  ]
  for (const [why, ev, st, auto, want] of cases) {
    const got = onPowerEvent(ev, st, auto)
    ok(got === want, `锁屏 / 解锁：${why}`, `得到 ${String(got)}，该是 ${String(want)}`)
  }
  const here2 = path.dirname(fileURLToPath(import.meta.url))
  const m = readFileSync(path.join(here2, '../../desktop/src/main.ts'), 'utf8')
  ok(/onPowerEvent\(ev, journey\?\.state\(\) \?\? 'off', autoPaused\)/.test(m),
     '壳那四个 powerMonitor 事件真的走这个函数 —— 不然上面八条一条都没验到产品')
  ok(/powerMonitor\.on\('lock-screen', autoPause\)/.test(m)
     && /powerMonitor\.on\('suspend', autoPause\)/.test(m)
     && /powerMonitor\.on\('unlock-screen', autoResume\)/.test(m)
     && /powerMonitor\.on\('resume', autoResume\)/.test(m),
     '四个事件一个都没掉（锁屏 / 睡眠 / 解锁 / 醒来）')
}

// ——— 壳那一侧：`_fake.json` 的那句承认不许能被省掉 ————————————————
{
  const here = path.dirname(fileURLToPath(import.meta.url))
  const src = readFileSync(path.join(here, '../../desktop/src/main.ts'), 'utf8')
  ok(/const FAKE_OK = '我知道这不是真的屏幕活动'/.test(src)
     && /spec\?\.fake !== FAKE_OK/.test(src),
     '壳只认写着那句承认的 _fake.json —— 踩不进来')
  ok(/fake: fakeCapture,/.test(src),
     'journey:state 把「挂着假采集源」这件事交给页面 —— 它得在页面上吵')
}

process.exit(bad ? 1 : 0)
