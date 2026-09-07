// 校验 docs/ 里的 mermaid 代码块能不能解析。
// 需要 jsdom：mermaid.parse 在纯 node 下会因为 DOMPurify 缺 DOM 而炸。
import { JSDOM } from 'jsdom'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

const dom = new JSDOM('<!doctype html><html><body></body></html>')
;(globalThis as any).window = dom.window
;(globalThis as any).document = dom.window.document
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true })
;(globalThis as any).SVGElement = dom.window.SVGElement

const mermaid = (await import('mermaid')).default
mermaid.initialize({ startOnLoad: false, securityLevel: 'strict' })

const dir = new URL('../../docs/', import.meta.url).pathname
let total = 0, bad = 0
for (const f of readdirSync(dir).filter(n => n.endsWith('.md'))) {
  const text = readFileSync(join(dir, f), 'utf8')
  const blocks = [...text.matchAll(/```mermaid\n([\s\S]*?)```/g)].map(m => m[1])
  for (const [i, code] of blocks.entries()) {
    total++
    try { await mermaid.parse(code) }
    catch (e: any) { bad++; console.log(`✗ ${f} 第 ${i + 1} 块: ${(e?.message || e).toString().slice(0, 200)}`) }
  }
}
console.log(bad ? `${bad}/${total} 块解析失败` : `${total} 块 mermaid 全部解析通过`)
process.exit(bad ? 1 : 0)
