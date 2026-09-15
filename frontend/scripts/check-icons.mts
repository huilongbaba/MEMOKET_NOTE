/** 用到的 boxicons 图标名必须真的存在。
 *
 *     npx tsx scripts/check-icons.mts
 *
 * **写这条是因为我自己刚犯过**（第 688 轮）：把 `✨ 智能排版` 的 emoji 换成
 * `bx-magic-wand`，而 boxicons 里**没有这个名字**——按钮上的图标直接变成空白，
 * 比原来的 emoji 更糟。tsc / eslint / vitest 全绿，CSS 类名闸门也不管
 * （它只查 `.bx` 前缀就放过）。**名字拼错的图标是看不见的**，只能靠这条查。
 *
 * 动态拼出来的名字（`'bx ' + icon`、`bx-${x}`）查不了，但它们的取值大多来自
 * 代码里的常量表，那些常量本身是字面量，照样会被扫到。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const root = resolve(import.meta.dirname, '../src')
const css = readFileSync(resolve(import.meta.dirname, '../node_modules/boxicons/css/boxicons.min.css'), 'utf8')
const known = new Set([...css.matchAll(/\.(bxs?-[a-z0-9-]+):/g)].map((m) => m[1]))
if (known.size < 100) { console.error('没读到 boxicons 的类名表，闸门失效'); process.exit(1) }

const walk = (d: string, out: string[] = []) => {
  for (const f of readdirSync(d)) {
    const p = join(d, f)
    if (statSync(p).isDirectory()) { if (!p.includes('__tests__')) walk(p, out) } else out.push(p)
  }
  return out
}

let bad = 0
for (const f of walk(root)) {
  if (!/\.(tsx?|css)$/.test(f)) continue
  const rel = f.replace(root + '/', '')
  readFileSync(f, 'utf8').split('\n').forEach((line, i) => {
    for (const m of line.matchAll(/\b(bxs?-[a-z0-9-]+)\b/g)) {
      const name = m[1]
      if (known.has(name)) continue
      bad++
      console.log(`✗ ${rel}:${i + 1} 图标 ${name} 在 boxicons 里不存在 —— 会渲染成空白：${line.trim().slice(0, 80)}`)
    }
  })
}
if (bad) { console.error(`${bad} 处`); process.exit(1) }
console.log(`OK: 用到的图标名都存在（boxicons 共 ${known.size} 个）`)
