/**
 * 行内出处：正文里的 `[terrence-1872-5F8]` 变成一个可悬停的标记，浮层里
 * 显示这条事实的原文和它的原始对话行。
 *
 * **为什么是浮层不是跳转**（判据 2，docs/product-north-star.md）：
 *
 *   > 写报告时想查一篇旧笔记，找了半天读完回来，忘了这一点是为了支撑什么。
 *
 * 跳走再回来，代价是那条思路。浮层的成本是「移开鼠标」，代价接近零。
 * 对标 Trilium 的 note peek / `openNoteInPopup`。
 *
 * 也直接对着痛点 13：汇总零散笔记时「有些事实好像也不对」——事实旁边就是
 * 它的原话，对不对当场看得见，不用相信模型。
 */
import { syntaxTree } from '@codemirror/language'
import { RangeSetBuilder, type Extension } from '@codemirror/state'
import { CITE_RE_SOURCE } from '../util/wordCount'
import {
  Decoration, type DecorationSet, EditorView, ViewPlugin, type ViewUpdate,
  hoverTooltip, WidgetType,
} from '@codemirror/view'

/** 事实 id 的形状：`<用户>-<数字>-<十六进制>`（KITE 的 fact id），或者笔记摄入的
 *  `note-<12 位 hex 笔记 id>-<块号>F<n>`——后一种之前不认，摄入进去的事实没法被引用。
 *  写死这个形状而不是「任何 [xxx]」，是为了不把普通的方括号引用误标成出处。
 *  跟后端 store._CITE / checks/citations / prompts/fragments、util/wordCount 一处源，四处同步。 */
export { CITE_RE_SOURCE }
const CITE = new RegExp(CITE_RE_SOURCE, 'g')

/** 取一条事实的详情。调用方注入，编辑器这一层不认识 api 模块——它要能被
 *  单独测试，也要能在别的宿主里复用。 */
export type FactLookup = (id: string) => Promise<{
  text: string
  when?: string
  sources?: string[]
} | null>

/** 正文里不直接露出 `[用户名-数字-哈希]`：那是机器主键，对作者没有阅读价值。
 * 底层文本仍然原样保留，复制、导出、校验和模型 grounding 都继续使用完整 id；
 * 光标进入引用时也会展开原文，用户仍能删除或修正它。 */
export function citeChipLabel(id: string): string {
  const suffix = id.match(/-([0-9A-Fa-f]+)$/)?.[1]?.toUpperCase()
  return suffix ? `来源 · ${suffix.slice(-4)}` : '来源'
}

class FactCiteWidget extends WidgetType {
  constructor(readonly id: string) { super() }
  eq(other: FactCiteWidget) { return other.id === this.id }
  toDOM() {
    const el = document.createElement('span')
    el.className = 'cm-fact-cite-chip'
    el.textContent = citeChipLabel(this.id)
    el.title = '查看这条来源'
    el.tabIndex = 0
    el.setAttribute('role', 'link')
    el.setAttribute('aria-label', `打开引用来源 ${this.id}`)
    const open = () => window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'kb:fact:' + this.id }))
    el.addEventListener('mousedown', (e) => { e.preventDefault(); open() })
    el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open() }
    })
    return el
  }
  ignoreEvent() { return true }
}

function buildCites(view: EditorView): DecorationSet {
  const b = new RangeSetBuilder<Decoration>()
  const sel = view.state.selection.main
  for (const { from, to } of view.visibleRanges) {
    const text = view.state.doc.sliceString(from, to)
    CITE.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = CITE.exec(text))) {
      const start = from + m.index
      const end = start + m[0].length
      // 代码块里的方括号不是出处——那可能是代码本身
      const node = syntaxTree(view.state).resolveInner(start, 1)
      if (/CodeBlock|FencedCode|InlineCode/.test(node.type.name)) continue
      // 光标进来时露出完整原文，跟 note link / 图片预览的编辑规则一致。
      if (sel.from <= end && sel.to >= start) continue
      b.add(start, end, Decoration.replace({ widget: new FactCiteWidget(m[1]) }))
    }
  }
  return b.finish()
}

const citePlugin = ViewPlugin.fromClass(class {
  decorations: DecorationSet
  constructor(view: EditorView) { this.decorations = buildCites(view) }
  update(u: ViewUpdate) {
    if (u.docChanged || u.viewportChanged || u.selectionSet) this.decorations = buildCites(u.view)
  }
}, { decorations: (v) => v.decorations })

/** 悬停浮层。缓存查过的事实：同一条出处在一篇长文里会被反复扫到，每次都
 *  打一次网络会让悬停有明显的迟滞。 */
function citeTooltip(lookup: FactLookup) {
  const cache = new Map<string, Awaited<ReturnType<FactLookup>>>()

  return hoverTooltip(async (view, pos) => {
    const line = view.state.doc.lineAt(pos)
    CITE.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = CITE.exec(line.text))) {
      const from = line.from + m.index
      const to = from + m[0].length
      if (pos < from || pos > to) continue
      const id = m[1]
      if (!cache.has(id)) {
        try { cache.set(id, await lookup(id)) } catch { cache.set(id, null) }
      }
      const fact = cache.get(id)
      return {
        pos: from, end: to, above: true,
        create() {
          const dom = document.createElement('div')
          dom.className = 'cm-fact-peek'
          if (!fact) {
            // **查不到要说出来。** 一条指向不存在事实的引用是个真问题
            // （模型编的、或者知识库重建过），静默显示成普通文字等于把它藏起来。
            dom.textContent = `找不到这条记录（${id}）——可能是引用写错了，或者知识库重建过`
            dom.classList.add('missing')
            return { dom }
          }
          const when = document.createElement('div')
          when.className = 'peek-when'
          when.textContent = fact.when ?? ''
          const body = document.createElement('div')
          body.className = 'peek-text'
          body.textContent = fact.text
          dom.append(when, body)
          for (const s of (fact.sources ?? []).slice(0, 3)) {
            const src = document.createElement('div')
            src.className = 'peek-source'
            src.textContent = s
            dom.append(src)
          }
          return { dom }
        },
      }
    }
    return null
  }, { hoverTime: 200 })
}

export function factCite(lookup: FactLookup): Extension {
  return [citePlugin, citeTooltip(lookup)]
}
