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
  /** 这段一共判出几种关系；点只画最要紧的一种 */
  kinds?: number
}

/** 六种关系的人话。右栏关系卡、页边圆点的悬停、图例三处同一份。 */
export const RELATION_LABEL: Record<MemoryRelationKind, string> = {
  conflict: '冲突', continuation: '延续', corroborated: '印证', unsupported: '缺依据', accumulation: '叠加', merge: '合并',
}

/** 圆点的规则，一句话（P1-1d，用户第 768 轮问「一个点代表一行还是一段？绿色黄色是什么？」）。
 *  写在这里而不是散在各处：悬停提示、右栏图例读的是同一句。 */
export const MARGIN_RULE = '页边圆点：每段一个（空行隔开算一段），只看含数字 / 日期的段落——判的是量的比对，零模型'

/** 悬停在点上看到的话：这一段 · 关系 · 那句人话 · 规则 · 还有别的没有。 */
export function markTitle(m: MarginMark): string {
  const more = (m.kinds ?? 1) > 1 ? `这段还判出另外 ${(m.kinds ?? 1) - 1} 种关系，` : ''
  return `这一段（第 ${m.line} 行起）· ${RELATION_LABEL[m.relation]}\n${m.say}\n${MARGIN_RULE}\n${more}点一下在右栏「记忆」看全部`
}

/** 哪些段落会拿去判关系：**跟后端 `relations_batch` 同一条门槛**（≥8 字、含数字、不是标题）。
 *  不封顶——原来 `.slice(0, 80)` 把 30k 字笔记第 80 个含数字的段落之后全丢了，
 *  「有的段有点、有的段没有」正是从这儿来的；请求按 80 一批分几次发（后端每批上限 80）。 */
export const MARGIN_BATCH = 80
export function marginParagraphs(content: string, clean: (s: string) => string): { text: string; line: number }[] {
  return paragraphsWithLines(content).map((p) => ({ ...p, text: clean(p.text).trim() }))
    .filter((p) => /\d/.test(p.text) && !p.text.startsWith('#') && p.text.length >= 8)
}
export function chunked<T>(xs: T[], n: number): T[][] {
  const out: T[][] = []
  for (let i = 0; i < xs.length; i += n) out.push(xs.slice(i, i + n))
  return out
}

export const setMarginMarks = StateEffect.define<MarginMark[]>()

class Dot extends GutterMarker {
  constructor(readonly m: MarginMark) { super() }
  eq(other: Dot) { return other.m.relation === this.m.relation && other.m.say === this.m.say }
  toDOM() {
    const el = document.createElement('span')
    el.className = 'mm-dot mm-' + this.m.relation
    el.title = markTitle(this.m)
    el.setAttribute('aria-label', RELATION_LABEL[this.m.relation])
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
