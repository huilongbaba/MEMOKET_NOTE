/** 边缘记忆（docs/agent-native-editor.md §3.3）：正文右缘一条「记忆带」——哪一段跟知识库
 *  有关系（冲突 / 延续 / 叠加 / 合并 / 印证 / 缺依据）就在那一段的第一行右边亮一个点，颜色 = 关系。
 *  点一下：光标落到那段，右栏「记忆」的关系卡就出来了。数据由上层批量算好塞进来
 *  （零 LLM 的代码候选），这里只管画和跟着文档改动映射行号。 */
import { StateEffect, StateField, type Extension } from '@codemirror/state'
import { EditorView, gutter, GutterMarker } from '@codemirror/view'
import type { MemoryRelationKind } from '../api'

export type MarginMark = {
  /** 1 起的行号（段落第一行） */
  line: number
  relation: MemoryRelationKind
  say: string
}

export const setMarginMarks = StateEffect.define<MarginMark[]>()

class Dot extends GutterMarker {
  constructor(readonly m: MarginMark) { super() }
  eq(other: Dot) { return other.m.relation === this.m.relation && other.m.say === this.m.say }
  toDOM() {
    const el = document.createElement('span')
    el.className = 'mm-dot mm-' + this.m.relation
    el.title = this.m.say + '\n点一下看详情'
    return el
  }
}

export const marginField = StateField.define<MarginMark[]>({
  create: () => [],
  update(marks, tr) {
    for (const e of tr.effects) if (e.is(setMarginMarks)) return e.value
    if (!tr.docChanged || marks.length === 0) return marks
    // 行号跟着文档改动走：把段首位置映射过去再换算回行号
    const old = tr.startState.doc
    return marks.map((m) => {
      const ln = Math.min(Math.max(1, m.line), old.lines)
      const pos = tr.changes.mapPos(old.line(ln).from, 1)
      return { ...m, line: tr.newDoc.lineAt(Math.min(pos, tr.newDoc.length)).number }
    })
  },
})

export function marginMemory(onClick: (m: MarginMark) => void): Extension {
  return [
    marginField,
    gutter({
      class: 'cm-memory-gutter',
      side: 'after',
      lineMarker(view, line) {
        const n = view.state.doc.lineAt(line.from).number
        const m = view.state.field(marginField).find((x) => x.line === n)
        return m ? new Dot(m) : null
      },
      lineMarkerChange: (u) => u.docChanged || u.transactions.some((t) => t.effects.some((e) => e.is(setMarginMarks))),
      domEventHandlers: {
        mousedown(view, line) {
          const n = view.state.doc.lineAt(line.from).number
          const m = view.state.field(marginField).find((x) => x.line === n)
          if (!m) return false
          view.dispatch({ selection: { anchor: line.from }, effects: EditorView.scrollIntoView(line.from, { y: 'nearest' }) })
          onClick(m)
          return true
        },
      },
    }),
  ]
}

/** 把正文按空行切成段，给每段的第一行行号（1 起）。跟后端一起用：段落文本去查关系，行号回来画点。 */
export function paragraphsWithLines(content: string): { text: string; line: number }[] {
  const out: { text: string; line: number }[] = []
  const lines = content.split('\n')
  let i = 0
  while (i < lines.length) {
    if (!lines[i].trim()) { i++; continue }
    const start = i
    const buf: string[] = []
    while (i < lines.length && lines[i].trim()) { buf.push(lines[i]); i++ }
    out.push({ text: buf.join('\n'), line: start + 1 })
  }
  return out
}
