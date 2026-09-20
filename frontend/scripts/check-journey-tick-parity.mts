/** 采样周期的**跨进程对拍**（P62）。
 *
 *     npx tsx scripts/check-journey-tick-parity.mts
 *
 * 「这一段的时长跟它采到的样本数对不对得上」这句判断，两头各有一个数：
 *   · 壳里 `desktop/src/capture.ts` 的 `INTERVAL_MS`——**真的每隔这么久采一次**
 *   · 页面里 `JourneyPage.tsx` 的 `JOURNEY_TICK_SEC`——**拿它把 `n` 换算成秒**
 *
 * 前端 import 不到 `desktop/`（两个进程、两份 tsconfig），所以这个数在前端是抄的。
 * **抄来的数就是一个接线洞**：壳哪天把 15 秒改成 30 秒，页面不会报错，
 * 只会把每一天的「采样时间」算成一半，然后对着一堆好数据说「这个合计偏长」——
 * **判错的提示比不提示更伤**。所以它单独一条闸。
 *
 * 同 `check-regex-parity` / `check-scrub-parity` 那几条的做法：两边都按源码正则读，
 * 不在这儿写死第三份。
 */
import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..', '..')
const capture = readFileSync(join(root, 'desktop/src/capture.ts'), 'utf8')
const page = readFileSync(join(root, 'frontend/src/components/JourneyPage.tsx'), 'utf8')

const mShell = /export const INTERVAL_MS = ([\d_]+)/.exec(capture)
const mPage = /export const JOURNEY_TICK_SEC = (\d+)/.exec(page)

let bad = 0
const fail = (msg: string) => { bad++; console.log('✗ ' + msg) }

if (!mShell) fail('desktop/src/capture.ts 里找不到 `export const INTERVAL_MS = …`——选不到 ≠ 没有，先去看它改成什么了')
if (!mPage) fail('JourneyPage.tsx 里找不到 `export const JOURNEY_TICK_SEC = …`')

if (mShell && mPage) {
  const shellSec = Number(mShell[1].replace(/_/g, '')) / 1000
  const pageSec = Number(mPage[1])
  if (!Number.isFinite(shellSec) || shellSec <= 0) fail(`INTERVAL_MS 读出来是 ${mShell[1]}，换算不成秒`)
  else if (shellSec !== pageSec) {
    fail(`采样周期两边对不上：壳 ${shellSec} 秒（INTERVAL_MS=${mShell[1]}）· 页面 ${pageSec} 秒`
      + '（JOURNEY_TICK_SEC）。改了壳就得改页面，否则「合计偏长」那句提示会对着好数据乱说。')
  } else console.log(`check-journey-tick-parity ✓ 两边都是 ${shellSec} 秒`)
}

if (bad) { console.error(`check-journey-tick-parity：${bad} 处`); process.exit(1) }
