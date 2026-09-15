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
import { corpus } from './_corpus.mts'

const root = resolve(import.meta.dirname, '../src')
/* **名字表的来源从 boxicons 换成了 `components/Icon.tsx` 的 ICONS 映射**
   （第 713 轮：字形换成 lucide，名字仍沿用 `bx-*`，理由见 Icon.tsx 的注释）。
   名字不在表里的表现是**什么都不画**——跟当初 `bx-magic-wand` 在 boxicons 里
   不存在是同一个坑，所以这条闸门照旧要有。 */
const iconSrc = readFileSync(resolve(import.meta.dirname, '../src/components/Icon.tsx'), 'utf8')
const known = new Set([...iconSrc.matchAll(/^\s*'(bxs?-[a-z0-9-]+)':/gm)].map((m) => m[1]))
if (known.size < 100) { console.error('没读到 Icon.tsx 的 ICONS 映射表，闸门失效'); process.exit(1) }

const walk = (d: string, out: string[] = []) => {
  for (const f of readdirSync(d)) {
    const p = join(d, f)
    if (statSync(p).isDirectory()) { if (!p.includes('__tests__')) walk(p, out) } else out.push(p)
  }
  return out
}

/** 把注释挖空，但**保持行数不变**——不然报出来的行号是错的（UI_SPEC §5 第 7 条：
 *  「闸门不该被散文和 URL 绊倒」，这条在第 713 轮又被自己的注释绊了一次：
 *  Icon.tsx 的注释里举了 `bx-magic-wand` 当反例，闸门把它当成了真的用法）。 */
function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
    .split('\n').map((l) => l.replace(/\/\/.*$/, '')).join('\n')
}

let bad = 0
for (const f of corpus(walk(root), 70, '源文件')) {
  if (!/\.(tsx?|css)$/.test(f)) continue
  const rel = f.replace(root + '/', '')
  stripComments(readFileSync(f, 'utf8')).split('\n').forEach((line, i) => {
    for (const m of line.matchAll(/\b(bxs?-[a-z0-9-]+)\b/g)) {
      const name = m[1]
      if (known.has(name)) continue
      bad++
      console.log(`✗ ${rel}:${i + 1} 图标 ${name} 不在 Icon.tsx 的 ICONS 映射表里 —— 会什么都不画：${line.trim().slice(0, 80)}`)
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
/* **按钮的整个标签就是一个符号字形时，它是「伪装成文字的图标」。**
   上面那条彩色 emoji 的闸门故意放行单色字形（`⚠ ☑ ▦` 这些是**内容**，跟着
   currentColor 走，没问题）。但 `<button>✕</button>` `<button>↺</button>`
   不是内容——它是一个图标按钮，只不过图标是用系统字体画的：粗细、字号、
   基线都跟满屏的 boxicons 对不上（第 701 轮实拍，8 处）。
   判据**故意收得很窄**：只认「整个子节点就是一个符号区字符」，
   汉字 / 字母 / 数字标签一概不碰——误伤比漏报贵。 */
{
  // U+00D7/F7 是 × ÷；U+2010–2BFF 覆盖 ✕ ↺ ▾ → ● ○ 这些箭头 / 几何 / 杂项符号。
  // 汉字（U+4E00 起）、全角标点（U+3000 段）都在范围外，不会被扫到。
  /* **从闭合标签往回认，不从开标签往后认。**
     第一版写的是 `<button[^>]*>…`，两次都漏：① 逐行 exec，跨行写的按钮扫不到；
     ② 就算整份文件一起扫，`onClick={(e) => …}` 里的**箭头自带一个 `>`**，
     `[^>]*>` 会在那里提前收尾（第 704 轮，同一条闸门连错两次）。
     改成认「开标签的 `>` 紧跟一个符号字形、紧跟 `</button>`」——
     属性怎么写、写几行、里面有多少个 `>` 都不影响。 */
  const GLYPH_ONLY = />\s*([\u00D7\u00F7\u2010-\u2BFF])\s*<\/(button|a)>/g
  for (const f of walk(root)) {
    if (!/\.tsx$/.test(f) || f.includes('__tests__')) continue
    const rel = f.replace(root + '/', '')
    const src = readFileSync(f, 'utf8')
    for (const m of src.matchAll(GLYPH_ONLY)) {
      const lineNo = src.slice(0, m.index).split('\n').length
      bad++
      console.log(`✗ ${rel}:${lineNo} <${m[2]}> 的标签就是一个 ${m[1]} —— 这是图标按钮，用 <i className="bx bx-…" />`)
    }
  }
}
/* **标签开头那个符号也是伪装成文字的图标。**（第 717 轮，硬规矩第 17 条的同一件事）
   `<button>+ 新建 skill</button>`、`<button>＋ 补一条</button>`——加号是用系统字体
   画的，跟旁边一屏 lucide 的笔形对不上。上一条判据只认「整个标签就是一个符号」，
   漏掉了「符号 + 文字」这种。
   判据同样收窄：只认**开头**的那几个**动作类**符号（加 / 叉 / 对钩 / 上下箭头），
   后面还得跟一个空格。句子中间的箭头（「旧 → 新」）是内容，不碰。 */
{
  const LEAD_GLYPH = />([+＋✕×✓↑↓])\s+[^<>{}]{1,20}<\/(button|a)>/g
  for (const f of walk(root)) {
    if (!/\.tsx$/.test(f) || f.includes('__tests__')) continue
    const rel = f.replace(root + '/', '')
    const src = stripComments(readFileSync(f, 'utf8'))
    for (const m of src.matchAll(LEAD_GLYPH)) {
      const lineNo = src.slice(0, m.index).split('\n').length
      bad++
      console.log(`✗ ${rel}:${lineNo} 标签开头的 ${m[1]} 是个字符不是图标 —— 用 <Icon n="bx-…" />`)
    }
  }
}
if (bad) { console.error(`${bad} 处`); process.exit(1) }
console.log('OK: 图标名都存在，也没有彩色 emoji 当图标')
