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
import {
  Decoration, type DecorationSet, EditorView, ViewPlugin, type ViewUpdate,
  hoverTooltip,
} from '@codemirror/view'

/** 事实 id 的形状：`<用户>-<数字>-<十六进制>`，见 KITE 的 fact id。
 *  写死这个形状而不是「任何 [xxx]」，是为了不把普通的方括号引用误标成出处。 */
const CITE = /\[([A-Za-z0-9_-]+-\d+-[0-9A-Fa-f]+)\]/g

/** 取一条事实的详情。调用方注入，编辑器这一层不认识 api 模块——它要能被
 *  单独测试，也要能在别的宿主里复用。 */
export type FactLookup = (id: string) => Promise<{
  text: string
  when?: string
  sources?: string[]
} | null>

const citeMark = Decoration.mark({ class: 'cm-fact-cite' })

function buildCites(view: EditorView): DecorationSet {
  const b = new RangeSetBuilder<Decoration>()
  for (const { from, to } of view.visibleRanges) {
    const text = view.state.doc.sliceString(from, to)
    CITE.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = CITE.exec(text))) {
      const start = from + m.index
      // 代码块里的方括号不是出处——那可能是代码本身
      const node = syntaxTree(view.state).resolveInner(start, 1)
      if (/CodeBlock|FencedCode|InlineCode/.test(node.type.name)) continue
      b.add(start, start + m[0].length, citeMark)
    }
  }
  return b.finish()
}

const citePlugin = ViewPlugin.fromClass(class {
  decorations: DecorationSet
  constructor(view: EditorView) { this.decorations = buildCites(view) }
  update(u: ViewUpdate) {
    if (u.docChanged || u.viewportChanged) this.decorations = buildCites(u.view)
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
