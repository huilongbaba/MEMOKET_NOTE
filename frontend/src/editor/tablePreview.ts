/** markdown 表格的即时预览。
 *
 * 跟 mermaid 那套完全同一个模式（见 editor/mermaid.ts）：光标**在表格外面**
 * 时把原文藏起来、渲染成真表格；光标**进到表格里**就换回原文让你编辑。
 * 两种同时显示是冗余，编辑时看渲染结果又是陈旧的。
 *
 * 为什么不是只做语法高亮：GFM 的表格语法本身是解析得出来的（lang-markdown
 * 已经带 GFM），但一堆竖线和 |---| 在正文里既读不出结构也对不齐——AI 现在
 * 会生成整表（智能表格 / EDA），不渲染的话最有用的产出反而最难读。
 */
import { syntaxTree } from '@codemirror/language'
import { StateField, type EditorState, type Range } from '@codemirror/state'
import { Decoration, EditorView, WidgetType, type DecorationSet } from '@codemirror/view'

/** ``| a | b |`` → ``['a','b']``。首尾的竖线是分隔符不是空格子，要去掉；
 * 中间的 ``\|`` 是转义的竖线，不能当分隔。 */
function cells(line: string): string[] {
  const t = line.trim().replace(/^\|/, '').replace(/\|$/, '')
  const out: string[] = []
  let cur = ''
  for (let i = 0; i < t.length; i++) {
    if (t[i] === '\\' && t[i + 1] === '|') { cur += '|'; i++; continue }
    if (t[i] === '|') { out.push(cur.trim()); cur = ''; continue }
    cur += t[i]
  }
  out.push(cur.trim())
  return out
}

/** 分隔行 ``|---|:--:|`` 决定每列对齐方式。 */
function alignments(line: string): ('left' | 'center' | 'right')[] {
  return cells(line).map((c) => {
    const l = c.startsWith(':')
    const r = c.endsWith(':')
    return l && r ? 'center' : r ? 'right' : 'left'
  })
}

function isSeparator(line: string): boolean {
  const cs = cells(line)
  return cs.length > 0 && cs.every((c) => /^:?-{1,}:?$/.test(c))
}

class TableWidget extends WidgetType {
  constructor(readonly source: string) { super() }
  eq(other: TableWidget) { return other.source === this.source }

  toDOM() {
    const lines = this.source.split('\n').filter((l) => l.trim())
    const wrap = document.createElement('div')
    wrap.className = 'cm-md-table'
    const table = document.createElement('table')
    const align = lines[1] ? alignments(lines[1]) : []
    const head = document.createElement('thead')
    const hr = document.createElement('tr')
    cells(lines[0]).forEach((c, i) => {
      const th = document.createElement('th')
      th.textContent = c
      th.style.textAlign = align[i] ?? 'left'
      hr.append(th)
    })
    head.append(hr)
    const body = document.createElement('tbody')
    for (const line of lines.slice(2)) {
      const tr = document.createElement('tr')
      cells(line).forEach((c, i) => {
        const td = document.createElement('td')
        td.textContent = c
        td.style.textAlign = align[i] ?? 'left'
        tr.append(td)
      })
      body.append(tr)
    }
    table.append(head, body)
    wrap.append(table)
    return wrap
  }

  // 点一下表格要能把光标放进原文去改，所以**不能**吞掉事件
  ignoreEvent() { return false }
}

/** 找出所有 GFM 表格。lang-markdown 的 GFM 扩展把它解析成 ``Table`` 节点，
 * 直接用语法树，不自己按行扫——自己扫会在代码块里的假表格上误判。 */
function tableDecorations(state: EditorState): DecorationSet {
  const decos: Range<Decoration>[] = []
  const ranges = state.selection.ranges
  syntaxTree(state).iterate({
    enter: (node) => {
      if (node.name !== 'Table') return
      const text = state.doc.sliceString(node.from, node.to)
      const lines = text.split('\n').filter((l) => l.trim())
      if (lines.length < 2 || !isSeparator(lines[1])) return
      // 光标在表格里 = 正在编辑，显示原文
      if (ranges.some((r) => r.from <= node.to && r.to >= node.from)) return
      decos.push(Decoration.replace({ block: true }).range(node.from, node.to))
      decos.push(Decoration.widget({
        widget: new TableWidget(text), side: 1, block: true,
      }).range(node.to))
    },
  })
  return Decoration.set(decos, true)
}

// 块级装饰必须来自 StateField，不能是 ViewPlugin —— CM6 会直接抛
// `RangeError: Block decorations may not be specified via plugins`
// （mermaid 那边的注释里记着同一个坑）。
export const tablePreview = StateField.define<DecorationSet>({
  create(state) { return tableDecorations(state) },
  update(value, tr) {
    return (tr.docChanged || tr.selection) ? tableDecorations(tr.state) : value
  },
  provide: (f) => EditorView.decorations.from(f),
})
