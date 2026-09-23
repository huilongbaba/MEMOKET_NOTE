/** 启动栏上有的去处，**⌘K 里都得有**。
 *
 *     npx tsx scripts/check-destinations.mts
 *
 * **为什么有这条**（第 779 轮 / P21）：屏幕活动在启动栏、欢迎页、菜单栏托盘、
 * 「文件」菜单四个地方都有入口，唯独 ⌘K 里没有——而 `docs/daily-journey-plan.md`
 * §8.4 明写「⌘K 加『今天的屏幕活动』」。靠 ⌘K 导航的人因此找不到这个功能。
 * 顺手查出来「写作 Skill」也一样不在。**不是漏了一行，是两处各写各的清单。**
 *
 * **所以这条闸门盯的是「来源」，不是「两份清单字面上一不一样」。**
 * 后者听起来更直接，但它意味着加一个新入口要改两处（清单 + 闸门的期望值），
 * 而「要记得改两处」正是当初漏掉屏幕活动的那个失败。这里查三件事：
 *
 *   1. `util/destinations.ts` 里那份 DESTINATIONS 还在，且每条长得像个去处
 *   2. App.tsx 的**启动栏那一段**从 DESTINATIONS 生成，没有手写的
 *      `openVirtual('app:…')`
 *   3. CommandPalette 的 COMMANDS 从 DESTINATIONS 生成，没有手写的
 *      `detail: 'app:…'`
 *
 * 于是「加一个去处」= 改 `destinations.ts` 一个文件，左栏和 ⌘K 同时有；
 * 想绕过这份清单单独加一个，这条闸门当场红。
 * 「⌘K 里确实列得出每一个去处」由单测钉（`__tests__/destinations.test.ts`）——
 * 闸门管**结构**，单测管**结果**（对拍式的「两边一样」保证不了两边一起错）。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const src = (p: string) => readFileSync(resolve(import.meta.dirname, '../src', p), 'utf8')

let bad = 0
const fail = (why: string) => { console.error('✗ ' + why); bad++ }

// —— 1. 那份清单 ————————————————————————————————————————————————
const dest = src('util/destinations.ts')
const ids = [...dest.matchAll(/\{\s*id:\s*'([^']+)'/g)].map((m) => m[1])
if (ids.length < 3) fail(`util/destinations.ts 里只读到 ${ids.length} 个去处——这份清单是两处入口的唯一来源，闸门失效`)
for (const id of ids) {
  if (!id.startsWith('app:') && id !== 'kb') fail(`去处 id「${id}」不是 app:* 或 kb——启动栏上的去处都必须是虚拟页`)
}
if (!ids.includes('app:journey')) fail('屏幕活动（app:journey）不在去处清单里——它就是这条闸门的由来')

/** 把注释挖空（行数不变），免得闸门被自己的散文绊倒（UI_SPEC §5 第 7 条）。 */
const strip = (s: string) => s
  .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
  .split('\n').map((l) => l.replace(/\/\/.*$/, '')).join('\n')

// —— 2. 启动栏 ————————————————————————————————————————————————
const app = strip(src('App.tsx'))
const pane = /className="launcher-pane"[\s\S]*?<UserSwitcher \/>/.exec(app)?.[0]
if (!pane) fail('在 App.tsx 里找不到启动栏（.launcher-pane）那一段——闸门失效')
else {
  if (!/DESTINATIONS\s*\.\s*filter[\s\S]*?\.map\(/.test(pane))
    fail('启动栏没有从 DESTINATIONS 生成——两处各写各的清单，就是这条闸门要拦的那件事')
  for (const m of pane.matchAll(/openVirtual\(\s*'(app:[^']+)'/g))
    fail(`启动栏里手写了 openVirtual('${m[1]}')：去处要加进 util/destinations.ts，不然 ⌘K 里不会有`)
}

// —— 3. ⌘K ————————————————————————————————————————————————————
const palette = strip(src('components/CommandPalette.tsx'))
const commands = /const COMMANDS[\s\S]*?\n\]/.exec(palette)?.[0]
if (!commands) fail('在 CommandPalette.tsx 里找不到 COMMANDS——闸门失效')
else {
  if (!/\.\.\.DESTINATIONS\.map\(/.test(commands))
    fail('⌘K 的 COMMANDS 没有从 DESTINATIONS 生成——屏幕活动当初就是这么漏掉的')
  // 注释已经挖空了，所以「深链」那条要在挖空**之前**的原文里认：
  // `detail: 'app:import' /* 深链 */`（开的是导入页里的某一块，不是去处本身）。
  const raw = src('components/CommandPalette.tsx')
  for (const m of commands.matchAll(/detail:\s*'(app:[^']+)'/g)) {
    if (new RegExp(`detail: *'${m[1]}' *\\/\\* *深链`).test(raw)) continue
    fail(`⌘K 里手写了 detail: '${m[1]}'：去处要走 util/destinations.ts 那一份`)
  }
}

if (bad) { console.error(`\ncheck-destinations: ${bad} 处`); process.exit(1) }
console.log(`check-destinations: ok（${ids.length} 个去处，启动栏和 ⌘K 都从同一份生成）`)
