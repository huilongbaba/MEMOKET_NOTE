/** TSX / TS 里用到的 className，CSS 里得有定义。
 *
 *     npx tsx scripts/check-css-classes.mts
 *
 * 为什么要有：第 483 轮「移动到…」的列表容器叫 `.palette-list`，CSS 里根本没这个类，外层
 * `overflow:hidden` 一裁，笔记多的人超出 60vh 的那截根本滚不到——tsc / eslint / vitest 都不管这种。
 * 纯当锚点 / 容器、自己不需要样式的类进 HOOK_ONLY（子元素有样式或探针用来定位）。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const root = resolve(import.meta.dirname, '../src')
const walk = (d: string, out: string[] = []) => { for (const f of readdirSync(d)) { const p = join(d, f); if (statSync(p).isDirectory()) { if (!p.includes('__tests__')) walk(p, out) } else out.push(p) } return out }
const files = walk(root)
/* 注释里的点号不是选择器。第 679 轮换肤时，注释里写的「源仓库的 `.cat-chip` 是
   30px 高的筛选条」被当成定义了一个 `.cat-chip`，反向检查立刻判它是死样式——
   **闸门被散文绊倒**。先去掉块注释再解析。 */
const stripComments = (s: string) => s.replace(/\/\*[^]*?\*\//g, ' ')
/* url() 里的点号也不是选择器。第 682 轮自绘勾选框用了一个 data URI，里面的
   `xmlns='http://www.w3.org/2000/svg'` 让反向检查报出一个叫 `.w3` 的死样式。
   跟注释那条同一个毛病：**闸门不该把不是选择器的东西当选择器。** */
const stripUrls = (s: string) => s.replace(/url\((?:[^)\\]|\\.)*\)/g, ' ')
const css = files.filter((f) => f.endsWith('.css')).map((f) => stripUrls(stripComments(readFileSync(f, 'utf8')))).join('\n')
const defined = new Set([...css.matchAll(/\.([A-Za-z_][\w-]*)/g)].map((m) => m[1]))
const HOOK_ONLY = new Set(['app-logo', 'export-back', 'export-back-result', 'mini-bars', 'tab-list', 'tl-month'])
const PREFIX_OK = ['bx', 'cm-', 'mm-']
// 代码里拼出来的类名（`'drop-' + where`）：反向检查按前缀放过
const DYNAMIC_PREFIX = ['drop-']

const used = new Map<string, Set<string>>()
const note = (c: string, f: string) => { if (PREFIX_OK.some((p) => c.startsWith(p)) || !/^[A-Za-z_][\w-]*$/.test(c)) return; if (!used.has(c)) used.set(c, new Set()); used.get(c)!.add(f.replace(root + '/', '')) }
for (const f of files.filter((f) => /\.tsx?$/.test(f))) {
  const s = readFileSync(f, 'utf8')
  for (const m of s.matchAll(/className=(?:"([^"]*)"|\{'([^']*)'|\{`([^`]*)`|\{\(?'([^']*)')/g)) {
    const txt = (m[1] ?? m[2] ?? m[3] ?? m[4]).replace(/\$\{[^}]*\}/g, ' ')
    for (const c of txt.split(/\s+/)) if (c) note(c, f)
  }
  for (const m of s.matchAll(/\+ ' ([a-z][\w-]*)'/g)) note(m[1], f)
  for (const m of s.matchAll(/className = '([^']*)'/g)) for (const c of m[1].split(/\s+/)) if (c) note(c, f)
}
const missing = [...used].filter(([c]) => !defined.has(c) && !HOOK_ONLY.has(c))
const stale = [...HOOK_ONLY].filter((c) => defined.has(c) || !used.has(c))
for (const [c, fs] of missing) console.log(`✗ .${c} 没有 CSS 定义 ← ${[...fs].join(', ')}`)
// 反向：CSS 里定义了、代码里一个字都没提到的（死样式，第 485 轮清掉 5 个）
const code = files.filter((f) => /\.tsx?$/.test(f)).map((f) => readFileSync(f, 'utf8')).join('\n') + readFileSync(resolve(root, '../index.html'), 'utf8')
const dead = [...defined].filter((c) => !PREFIX_OK.some((p) => c.startsWith(p)) && !DYNAMIC_PREFIX.some((p) => c.startsWith(p)) && !/^[a-z]+-$/.test(c) && !code.includes(c))
for (const c of dead) console.log(`✗ .${c} 在 CSS 里定义了，代码里没人用`)
for (const c of stale) console.log(`✗ HOOK_ONLY 里的 .${c} 已经有定义或没人用了，从名单去掉`)
if (missing.length || stale.length || dead.length) process.exit(1)
console.log(`OK: ${used.size} 个类名都有定义（${HOOK_ONLY.size} 个纯锚点类在名单里）；${defined.size} 个 CSS 类没有死样式`)
