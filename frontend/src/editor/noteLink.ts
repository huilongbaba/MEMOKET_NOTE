/**
 * 笔记内链 `[标题](note://<id>)` 在光标不在它上面时折成一枚可点的标记
 * （Trilium 里内部链接就是一枚带图标的 reference link）。光标进去就展开成
 * 原文可以改。点标记直接打开那篇——它是 widget，不存在「点一下是编辑还是跳转」
 * 的歧义，所以不像外链那样要按住 ⌘。
 */
import { syntaxTree } from '@codemirror/language'
import { RangeSetBuilder, type Extension } from '@codemirror/state'
import { Decoration, type DecorationSet, EditorView, ViewPlugin, type ViewUpdate, WidgetType } from '@codemirror/view'

const NOTE_LINK = /\[([^\]\n]{1,80})\]\(note:\/\/([0-9a-f]{12})\)/g

/** 取一篇笔记的摘要。调用方注入——编辑器这一层不认识 api 模块。 */
export type NoteLookup = (id: string) => Promise<{ title: string; content: string; updated_at: string } | null>

/** 悬停 300ms 出一张摘要卡（Trilium 的 note_tooltip）：不用点开就知道链的是哪篇。
 *  同一篇只查一次；卡片挂在 body 上，跟着标记定位。 */
const peekCache = new Map<string, Awaited<ReturnType<NoteLookup>>>()
let peekEl: HTMLElement | null = null
function hidePeek() { peekEl?.remove(); peekEl = null }

async function showPeek(anchor: HTMLElement, id: string, lookup: NoteLookup, still: () => boolean) {
  if (!peekCache.has(id)) {
    try { peekCache.set(id, await lookup(id)) } catch { peekCache.set(id, null) }
  }
  if (!anchor.isConnected || !still()) return
  const n = peekCache.get(id)
  hidePeek()
  const el = document.createElement('div')
  el.className = 'cm-fact-peek cm-note-peek' + (n ? '' : ' missing')
  if (!n) {
    el.textContent = '这篇笔记不存在了（可能被删了）'
  } else {
    const t = document.createElement('div'); t.className = 'peek-text'; t.textContent = n.title || '未命名'
    const w = document.createElement('div'); w.className = 'peek-when'; w.textContent = n.updated_at.slice(0, 10) + ' · ' + n.content.length + ' 字'
    const b = document.createElement('div'); b.className = 'peek-body'
    // 摘要里把内链折回标题、去掉标题井号——卡片里看到 `](note://…)` 没意义
    const plain = n.content.replace(/\[([^\]\n]+)\]\(note:\/\/[0-9a-f]{12}\)/g, '$1').replace(/^#+\s*/gm, '').trim()
    b.textContent = plain.slice(0, 240) + (plain.length > 240 ? '…' : '')
    el.append(w, t, b)
  }
  const r = anchor.getBoundingClientRect()
  el.style.position = 'fixed'
  el.style.left = Math.min(r.left, window.innerWidth - 440) + 'px'
  el.style.zIndex = '300'
  document.body.append(el)
  // 先挂上量高度：下面放不下就翻到标记上方（链接常在文末，实拍卡片被窗口底切掉）
  const h = el.offsetHeight
  el.style.top = (r.bottom + 6 + h > window.innerHeight ? Math.max(4, r.top - 6 - h) : r.bottom + 6) + 'px'
  peekEl = el
}

class NoteLinkWidget extends WidgetType {
  constructor(readonly title: string, readonly id: string, readonly lookup?: NoteLookup) { super() }
  eq(o: NoteLinkWidget) { return o.title === this.title && o.id === this.id }
  toDOM() {
    const a = document.createElement('a')
    a.className = 'cm-note-link'
    a.title = '打开这篇笔记'
    const i = document.createElement('i')
    i.className = 'bx bx-note'
    a.append(i, document.createTextNode(this.title))
    a.addEventListener('mousedown', (e) => {
      e.preventDefault()
      hidePeek()
      window.dispatchEvent(new CustomEvent('open-note', { detail: this.id }))
    })
    if (this.lookup) {
      let timer = 0
      let hovering = false
      a.addEventListener('mouseenter', () => { hovering = true; timer = window.setTimeout(() => void showPeek(a, this.id, this.lookup!, () => hovering), 300) })
      a.addEventListener('mouseleave', () => { hovering = false; clearTimeout(timer); hidePeek() })
    }
    return a
  }
  ignoreEvent() { return true }
}

function build(view: EditorView, lookup?: NoteLookup): DecorationSet {
  const b = new RangeSetBuilder<Decoration>()
  const sel = view.state.selection.main
  for (const { from, to } of view.visibleRanges) {
    const text = view.state.doc.sliceString(from, to)
    NOTE_LINK.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = NOTE_LINK.exec(text))) {
      const start = from + m.index
      const end = start + m[0].length
      // 光标在里面：展开成原文让人改
      if (sel.from <= end && sel.to >= start) continue
      const node = syntaxTree(view.state).resolveInner(start, 1)
      if (/CodeBlock|FencedCode|InlineCode/.test(node.type.name)) continue
      b.add(start, end, Decoration.replace({ widget: new NoteLinkWidget(m[1], m[2], lookup) }))
    }
  }
  return b.finish()
}

export function noteLinkChips(lookup?: NoteLookup): Extension {
  return ViewPlugin.fromClass(class {
    decorations: DecorationSet
    constructor(view: EditorView) { this.decorations = build(view, lookup) }
    update(u: ViewUpdate) {
      if (u.docChanged || u.viewportChanged || u.selectionSet) this.decorations = build(u.view, lookup)
    }
    destroy() { hidePeek() }
  }, { decorations: (v) => v.decorations })
}
