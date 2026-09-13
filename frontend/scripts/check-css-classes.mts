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
const css = files.filter((f) => f.endsWith('.css')).map((f) => readFileSync(f, 'utf8')).join('\n')
const defined = new Set([...css.matchAll(/\.([A-Za-z_][\w-]*)/g)].map((m) => m[1]))
const HOOK_ONLY = new Set(['app-logo', 'export-back', 'export-back-result', 'mini-bars', 'tab-list', 'tl-month'])
const PREFIX_OK = ['bx', 'cm-', 'mm-']

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
for (const c of stale) console.log(`✗ HOOK_ONLY 里的 .${c} 已经有定义或没人用了，从名单去掉`)
if (missing.length || stale.length) process.exit(1)
console.log(`OK: ${used.size} 个类名都有定义（${HOOK_ONLY.size} 个纯锚点类在名单里）`)
