/** 可点的 div / span 必须键盘也能按：带 onClick 就得有 role（util/clickable 给的）或自己接 onKeyDown。
 *
 *     npx tsx scripts/check-a11y.mts
 *
 * 第 506 轮横扫出 8 处只有 onClick 的卡片 / 行，Tab 走不到。遮罩层（点空白关掉）不算——它们是
 * 鼠标的快捷路径，键盘走 Esc。图标按钮（只有一个 <i class="bx …">）必须有 title 或 aria-label。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const root = resolve(import.meta.dirname, '../src')
const walk = (d: string, out: string[] = []) => { for (const f of readdirSync(d)) { const p = join(d, f); if (statSync(p).isDirectory()) { if (!p.includes('__tests__')) walk(p, out) } else if (p.endsWith('.tsx')) out.push(p) } return out }
// 遮罩 / 弹层容器：onClick 只是「点空白关掉」或 stopPropagation
const BACKDROP = /palette-backdrop|'modal'|embedded-panel|stopPropagation\(\)\s*\}\s*$/
let bad = 0
for (const f of walk(root)) {
  const s = readFileSync(f, 'utf8')
  const rel = f.replace(root + '/', '')
  // 标签到哪儿结束：`>` 得在花括号外面数（onClick={() => …} 里的箭头不算）
  const tagEnd = (from: number) => { let depth = 0; for (let i = from; i < s.length; i++) { const c = s[i]; if (c === '{') depth++; else if (c === '}') depth--; else if (c === '>' && depth === 0) return i } return s.length }
  for (const m of s.matchAll(/<(div|span)\b[^>]*?\bonClick=/g)) {
    const tag = s.slice(m.index, tagEnd(m.index!))
    if (/\brole=|onKeyDown=|\{\.\.\.clickable\(/.test(tag) || BACKDROP.test(tag)) continue
    // 已知带键盘逻辑的列表项（自己在容器上接键）
    // 树的展开三角（容器接 ← →）、toast 正文点一下关掉（会自动消失，键盘不需要）
    if (/palette-item|note-tab|tree-node|tree-expander|点击关闭/.test(tag)) continue
    bad++; console.log(`✗ ${rel}:${s.slice(0, m.index).split('\n').length} 只有 onClick 没有 role / onKeyDown：${tag.replace(/\s+/g, ' ').slice(0, 100)}`)
  }
  for (const m of s.matchAll(/<button([^>]*?)>\s*<i className=(?:\{?['"][^>]*|\{[^}]*\})\s*\/>\s*<\/button>/g)) {
    if (/title|aria-label/.test(m[1])) continue
    bad++; console.log(`✗ ${rel}:${s.slice(0, m.index).split('\n').length} 图标按钮没有 title / aria-label`)
  }
}
if (bad) { console.error(`${bad} 处`); process.exit(1) }
console.log('OK: 可点的 div / span 都能键盘按，图标按钮都有说明')
