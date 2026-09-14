// 后端那条「手写流程图也放行」的语法，跟真 mermaid 对一遍。
//
// `checks/blockcheck.py` 的 `is_plain_flowchart` 是我自己手写的正则语法：它说
// 能渲染，就必须真的能渲染——否则判据放行的图会在用户笔记里变成一段红色报错，
// 而这正是「必须跟工具字节一致」当初要防的事。语料是第 607 轮把四次真跑里
// 模型写出来的 mermaid 全收集起来的那 9 块，加上手写的反例。
//
// 只单向要求：**后端放行的，真 mermaid 必须解析得过**。反过来不要求——
// 后端故意保守，解析得过但语法面更大的（xychart / pie / sequence）照旧走工具。
import { JSDOM } from 'jsdom'
import { readFileSync } from 'node:fs'

const dom = new JSDOM('<!doctype html><html><body></body></html>')
;(globalThis as any).window = dom.window
;(globalThis as any).document = dom.window.document
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true })
;(globalThis as any).SVGElement = dom.window.SVGElement

const mermaid = (await import('mermaid')).default
mermaid.initialize({ startOnLoad: false, securityLevel: 'strict' })

const file = new URL('../../backend/tests/fixtures/mermaid_corpus.json', import.meta.url).pathname
const { accept, reject } = JSON.parse(readFileSync(file, 'utf8')) as { accept: string[]; reject: string[] }

let bad = 0
for (const [i, code] of accept.entries()) {
  try { await mermaid.parse(code) }
  catch (e: any) {
    bad++
    console.log(`✗ 后端放行的第 ${i + 1} 块，真 mermaid 解析不过：${(e?.message || e).toString().slice(0, 160)}`)
  }
}
console.log(bad
  ? `${bad}/${accept.length} 块后端放行但渲染不出来——is_plain_flowchart 放得太宽`
  : `${accept.length} 块后端放行的手写流程图，真 mermaid 全部解析通过（另有 ${reject.length} 个反例后端已拒）`)
process.exit(bad ? 1 : 0)
