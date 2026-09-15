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

/* **彩色 emoji 不许当图标。**（UI_SPEC 硬规矩第 13 条）
   第 687 轮清过一批，正则漏了几段——第 695 轮用完整的 emoji 区段重扫，
   还剩 8 处（🚀 🤖 ⚙️ 🧩 📥 🪄 ⏸）。emoji **拿不到令牌色**：深色下还是那几个
   彩块，也没法让状态跟着语义色走。
   **单色字形放行**（⌘ ⇧ ✕ ↑ ● ○ ▾ → ☑ ▦ ⚠ …）——它们跟着 currentColor。 */
{
  /* 只认**一定是彩色**的：U+1F000–1FAFF 这一大段，加上任何显式带了
     U+FE0F（变体选择符 16，强制 emoji 呈现）的字符。
     `⚠ ⚑ ☑ ⚙ ▦` 这些在 U+2600 段里的**默认是单色文字呈现**，跟着 currentColor
     走——第一版把它们一起报了，是误伤（第 695 轮当场收紧）。 */
  const COLOR_EMOJI = /[\u{1F000}-\u{1FAFF}]|.\u{FE0F}/u
  for (const f of walk(root)) {
    if (!/\.tsx?$/.test(f) || f.includes('__tests__')) continue
    const rel = f.replace(root + '/', '')
    readFileSync(f, 'utf8').split('\n').forEach((line, i) => {
      const code = line.split('//')[0]
      if (code.trimStart().startsWith('*') || code.includes('/*')) return   // 注释里讲到 emoji 不算
      const m = COLOR_EMOJI.exec(code)
      if (!m) return
      bad++
      console.log(`✗ ${rel}:${i + 1} 用了彩色 emoji ${m[0]} —— 它拿不到令牌色，换 boxicons：${code.trim().slice(0, 70)}`)
    })
  }
}
if (bad) { console.error(`${bad} 处`); process.exit(1) }
console.log('OK: 图标名都存在，也没有彩色 emoji 当图标')
