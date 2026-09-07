/** markdown 表格预览的自测。
 *
 *     npx tsx scripts/check-table.mts
 *
 * 用 GFM 语法树真的解析一遍，确认能认出表格、能取到对齐方式、光标进表格时
 * 换回原文。这套 UI 的同类实现（roundDiff 的按钮、slash 菜单）都出现过
 * "构建通过但东西不出现"，所以先在状态层验一遍。
 */
import { EditorState } from '@codemirror/state'
import { markdown } from '@codemirror/lang-markdown'
import { GFM } from '@lezer/markdown'
import { syntaxTree } from '@codemirror/language'

import { tablePreview } from '../src/editor/tablePreview.ts'

let bad = 0
const ok = (c: unknown, m: string) => { console.log(`${c ? '✓' : '✗'} ${m}`); if (!c) bad++ }

const ext = [markdown({ extensions: [GFM] }), tablePreview]
const mk = (doc: string, cursor = 0) =>
  EditorState.create({ doc, extensions: ext, selection: { anchor: cursor } })

const DOC = `前面一段话。

| 月份 | 渠道 | 销量 |
|---|:---:|---:|
| 3月 | 官网 | 1200 |
| 4月 | 众筹 | 800 |

后面一段话。`

// GFM 是不是真的把它解析成 Table 节点
let found = 0
syntaxTree(mk(DOC, 0)).iterate({ enter: (n) => { if (n.name === 'Table') found++ } })
ok(found === 1, `GFM 认出 1 个表格节点（实际 ${found}）`)

// 光标在表格外：应该有装饰（藏原文 + 渲染 widget）
const outside = mk(DOC, 0).field(tablePreview)
ok(outside.size === 2, `光标在外面时有 2 条装饰：藏原文 + 表格 widget（实际 ${outside.size}）`)

// 光标在表格里：不渲染，显示原文让人编辑
const inside = mk(DOC, DOC.indexOf('官网')).field(tablePreview)
ok(inside.size === 0, `光标在表格里时不渲染（实际 ${inside.size} 条装饰）`)

// 没有分隔行的不算表格
const fake = mk('| 只有一行 |\n\n正文。', 0).field(tablePreview)
ok(fake.size === 0, '只有一行竖线的不当表格')

// 代码块里的假表格不能误判
const inCode = mk('```\n| a | b |\n|---|---|\n| 1 | 2 |\n```\n', 0).field(tablePreview)
ok(inCode.size === 0, '代码块里的表格不渲染')

// 渲染出来的 DOM 结构与对齐
const { JSDOM } = await import('jsdom')
const dom = new JSDOM('<!doctype html><html><body></body></html>')
;(globalThis as any).document = dom.window.document
const decos = mk(DOC, 0).field(tablePreview)
let html = ''
let aligns: string[] = []
decos.between(0, DOC.length, (_f, _t, d) => {
  const w = (d.spec as { widget?: { toDOM(): HTMLElement } }).widget
  if (w) {
    const el = w.toDOM()
    html = el.innerHTML
    aligns = [...el.querySelectorAll('th')].map((th) => (th as HTMLElement).style.textAlign)
  }
})
ok(html.includes('<table'), '渲染出真正的 <table>')
ok((html.match(/<td/g) ?? []).length === 6, `6 个数据格（实际 ${(html.match(/<td/g) ?? []).length}）`)
ok(html.includes('1200') && html.includes('众筹'), '格子内容完整')
ok(aligns.join(',') === 'left,center,right', `对齐来自分隔行 |---|:---:|---:|（实际 ${aligns.join(',')}）`)

console.log(bad ? `\n✗ ${bad} 项没通过` : '\n表格预览：通过')
if (bad) process.exit(1)
