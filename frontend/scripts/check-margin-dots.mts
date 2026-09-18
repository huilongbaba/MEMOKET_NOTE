/** 页边圆点的样式闸（P10，修 P1 / P7 遗留的「灰点在白底上太淡」）。
 *
 *     npx tsx scripts/check-margin-dots.mts
 *
 * 缺依据的点原来是 `--muted` 实心再打 85% 透明——白底上几乎看不见，用户第 768 轮问「那个点是什么」
 * 时它就已经淡到看不清。现在是**空心圈、`--fg` 描边**：浅色 #111 / 深色 #F2EFF7，两边都够看，而且
 * 空心跟实心的「印证绿」一眼分得开。这条闸钉住三件事：缺依据不许再回到 `--muted` 实心；印证还是实心绿；
 * 关系卡头那行不许再 nowrap + ellipsis（「还判出 1 种」被吃掉过）。
 * 放在 scripts 而不是 vitest：vitest 把 .css 当空模块，`?raw` 也读不到。
 */
import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

const css = readFileSync(join(resolve(import.meta.dirname, '../src'), 'styles.css'), 'utf8')
const rule = (cls: string) => { const at = css.indexOf(cls + ' {'); return at < 0 ? '' : /\{[^}]*\}/.exec(css.slice(at))?.[0] ?? '' }
let bad = 0
const check = (ok: boolean, msg: string) => { if (!ok) { bad++; console.log('✗ ' + msg) } }

const un = rule('.mm-unsupported')
check(/background: transparent/.test(un), '.mm-unsupported 要是空心（background: transparent）')
check(/border: 2px solid var\(--fg\)/.test(un), '.mm-unsupported 描边要走 --fg（浅深都够看）')
check(!/--muted/.test(un), '.mm-unsupported 不许再用 --muted（白底上看不见）')
const co = rule('.mm-corroborated')
check(/background: var\(--ins\)/.test(co) && !/transparent/.test(co), '.mm-corroborated 印证要保持实心绿，跟空心分得开')
const where = rule('.margin-card-where')
check(!/nowrap|ellipsis/.test(where), '.margin-card-where 不许 nowrap / ellipsis（「还判出 1 种」会被截掉）')

if (bad) { console.error(`check-margin-dots：${bad} 处`); process.exit(1) }
console.log('check-margin-dots ✓ 缺依据空心 --fg 描边 · 印证实心绿 · 卡头不截')
