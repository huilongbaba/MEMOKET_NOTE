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
  // 禁用的按钮要说清为什么（判据 1）。只在「条件没满足」时要求：
  // 正在跑（busy / saving / loading / 有 spinner）和「就是当前这一个」自明，不算。
  for (const m of s.matchAll(/<button\b/g)) {
    const end = tagEnd(m.index!)
    const tag = s.slice(m.index, end)
    if (!/\bdisabled\b/.test(tag)) continue
    if (/title|aria-label/.test(tag)) continue
    const cond = /disabled=\{([^]*?)\}\s*(?:[a-zA-Z-]+=|>|$)/.exec(tag)?.[1] ?? ''
    if (/busy|saving|loading|running|starting|pending|probing|item\.disabled|=== ?(p|cur|active|current)/.test(cond)) continue
    // 按钮自己在转圈（`<span className="spinner" />`）：禁用的原因就画在按钮上
    if (/spinner/.test(s.slice(end, s.indexOf('</button>', end) + 9))) continue
    bad++; console.log(`✗ ${rel}:${s.slice(0, m.index).split('\n').length} 禁用按钮没说为什么：disabled={${cond.replace(/\s+/g, ' ').slice(0, 70)}}`)
  }
  /* 输入框要有名字。**占位符不是名字**：填上字它就没了。
     实拍（第 675 轮，全新用户的设置页）：GPT 那一组三个框填着
     `gpt-5.6-luna`、`https://api.openai.com/v1`，**旁边一个字都没有**说这是什么；
     屏幕阅读器读到的也只是「编辑框」。
     算数的名字：aria-label / aria-labelledby / id+<label htmlFor> / 外面裹一层
     <label> / title。勾选框和单选框不算——它们后面跟着文字，那就是名字。 */
  const labelled = new Set([...s.matchAll(/htmlFor="([^"]+)"/g)].map((m) => m[1]))
  for (const m of s.matchAll(/<(input|select|textarea)\b/g)) {
    const end = tagEnd(m.index!)
    const tag = s.slice(m.index, end)
    if (/aria-label|aria-labelledby|\btitle=/.test(tag)) continue
    if (/\btype="(checkbox|radio|file|hidden)"/.test(tag)) continue
    const id = /\bid="([^"]+)"/.exec(tag)?.[1]
    if (id && labelled.has(id)) continue
    // 外面裹了一层 <label>：往前找最近的 <label 和 </label>，前者更近就算裹住了
    const before = s.slice(0, m.index)
    if (before.lastIndexOf('<label') > before.lastIndexOf('</label>')) continue
    bad++; console.log(`✗ ${rel}:${before.split('\n').length} 输入框没有名字（占位符填上字就没了）：${tag.replace(/\s+/g, ' ').slice(0, 90)}`)
  }
}
if (bad) { console.error(`${bad} 处`); process.exit(1) }
console.log('OK: 可点的 div / span 都能键盘按，图标按钮 / 禁用按钮 / 输入框都有说明')
