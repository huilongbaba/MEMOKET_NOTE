/** 正在跑的 AI 块：在光标处放一个占位块，点开能看到它在干什么。
 *
 * 为什么不是浮在角落的一个提示条：
 *
 * · **位置**：`/` 可以在文档任何地方触发，产出也落在那里。状态离产出越远，
 *   越看不出"哪一块在跑"——尤其是同时跑好几个的时候。
 * · **并发**：占位块自带位置，位置跟着文档编辑一起映射，所以可以同时跑好几个
 *   而不会互相踩。原来那版是一个全局的 slashBusy，**同时只能跑一个**。
 * · **不往正文里流**：生成过程中的内容只在占位块里预览，跑完才一次性落进正文。
 *   直接往文档里流的话，几个任务同时跑就会把文字交错插在一起。
 */
import { StateEffect, StateField, type Range } from '@codemirror/state'
import { Decoration, EditorView, WidgetType } from '@codemirror/view'

export type RunLog = { at: string; text: string }

export type RunState = {
  id: string
  /** 产出要落到文档里的位置。跟着每一次文档改动映射。 */
  from: number
  label: string
  phase: string
  /** 流式产出的预览。只在占位块里显示，不进正文。 */
  preview: string
  log: RunLog[]
  expanded: boolean
  error: string
}

export const startRun = StateEffect.define<{ id: string; from: number; label: string }>()
export const patchRun = StateEffect.define<{ id: string } & Partial<Omit<RunState, 'id'>>>()
export const appendPreview = StateEffect.define<{ id: string; text: string }>()
export const logRun = StateEffect.define<{ id: string; at: string; text: string }>()
export const endRun = StateEffect.define<string>()
export const toggleRun = StateEffect.define<string>()

export const runsField = StateField.define<RunState[]>({
  create: () => [],
  update(runs, tr) {
    let next = runs
    for (const e of tr.effects) {
      if (e.is(startRun)) {
        next = [...next, { ...e.value, phase: '', preview: '', log: [], expanded: false, error: '' }]
      } else if (e.is(endRun)) {
        next = next.filter((r) => r.id !== e.value)
      } else if (e.is(toggleRun)) {
        next = next.map((r) => (r.id === e.value ? { ...r, expanded: !r.expanded } : r))
      } else if (e.is(patchRun)) {
        next = next.map((r) => (r.id === e.value.id ? { ...r, ...e.value } : r))
      } else if (e.is(appendPreview)) {
        next = next.map((r) => (r.id === e.value.id
          ? { ...r, preview: r.preview + e.value.text } : r))
      } else if (e.is(logRun)) {
        next = next.map((r) => (r.id === e.value.id
          ? { ...r, log: [...r.log, { at: e.value.at, text: e.value.text }] } : r))
      }
    }
    if (tr.docChanged && next.length) {
      // 位置跟着文档改动走。assoc=1：正好插在这个位置的字排在占位块**前面**，
      // 也就是用户在占位块上方继续打字时，产出的落点跟着往后挪。
      next = next.map((r) => ({ ...r, from: tr.changes.mapPos(r.from, 1) }))
    }
    return next === runs ? runs : next
  },
})

/** 停止某一次运行。由 App 侧注入——扩展里不该知道 AbortController 的事。 */
export type StopRun = (id: string) => void

class RunWidget extends WidgetType {
  constructor(readonly run: RunState, readonly stop: StopRun) { super() }

  eq(o: RunWidget) {
    const a = this.run
    const b = o.run
    return a.id === b.id && a.phase === b.phase && a.expanded === b.expanded
      && a.preview.length === b.preview.length && a.log.length === b.log.length
      && a.error === b.error
  }

  toDOM(view: EditorView) {
    const r = this.run
    const wrap = document.createElement('div')
    wrap.className = 'cm-run-block' + (r.error ? ' has-error' : '')

    const head = document.createElement('div')
    head.className = 'cm-run-head'
    const spin = document.createElement('span')
    spin.className = r.error ? 'cm-run-bad' : 'spinner'
    spin.textContent = r.error ? '!' : ''
    const title = document.createElement('span')
    title.className = 'cm-run-title'
    title.textContent = r.label
    const phase = document.createElement('span')
    phase.className = 'cm-run-phase'
    phase.textContent = r.error || r.phase || '在跑…'
    const chev = document.createElement('span')
    chev.className = 'cm-run-chev'
    chev.textContent = r.expanded ? '▾' : '▸'
    const stop = document.createElement('button')
    stop.type = 'button'
    stop.className = 'cm-run-stop'
    stop.textContent = '停止'
    stop.addEventListener('mousedown', (e) => {
      e.preventDefault()
      e.stopPropagation()
      this.stop(r.id)
    })
    head.append(chev, spin, title, phase, stop)
    head.addEventListener('mousedown', (e) => {
      e.preventDefault()
      view.dispatch({ effects: toggleRun.of(r.id) })
    })
    wrap.append(head)

    if (r.expanded) {
      const body = document.createElement('div')
      body.className = 'cm-run-body'
      if (r.log.length) {
        const ul = document.createElement('ul')
        ul.className = 'cm-run-log'
        for (const l of r.log) {
          const li = document.createElement('li')
          const at = document.createElement('span')
          at.className = 'cm-run-at'
          at.textContent = l.at
          li.append(at, document.createTextNode(l.text))
          ul.append(li)
        }
        body.append(ul)
      }
      if (r.preview.trim()) {
        const pre = document.createElement('pre')
        pre.className = 'cm-run-preview'
        // 只显示尾部：一块内容可能上千字，全塞进占位块会把编辑器顶开
        pre.textContent = r.preview.length > 1200
          ? '…' + r.preview.slice(-1200) : r.preview
        body.append(pre)
      }
      if (!r.log.length && !r.preview.trim()) {
        const empty = document.createElement('div')
        empty.className = 'cm-run-empty'
        empty.textContent = '还没有输出'
        body.append(empty)
      }
      wrap.append(body)
    }
    return wrap
  }

  // 里面有按钮要点，不能吞事件
  ignoreEvent() { return false }
}

export function runningBlocks(stop: StopRun) {
  const decos = EditorView.decorations.compute([runsField, 'doc'], (state) => {
    const runs = state.field(runsField)
    if (!runs.length) return Decoration.none
    const len = state.doc.length
    const out: Range<Decoration>[] = runs
      .map((r) => Decoration.widget({
        widget: new RunWidget(r, stop), side: -1, block: true,
      }).range(Math.max(0, Math.min(r.from, len))))
    // 同一个位置上有多个时要按位置排序，否则 CM6 会抛 "Ranges must be sorted"
    out.sort((a, b) => a.from - b.from)
    return Decoration.set(out, true)
  })
  return [runsField, decos]
}

/** 还在跑的有几个。给上层显示用。 */
export function runningCount(state: { field: (f: typeof runsField, req: false) => RunState[] | undefined }): number {
  return state.field(runsField, false)?.length ?? 0
}
