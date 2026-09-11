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

class NoteLinkWidget extends WidgetType {
  constructor(readonly title: string, readonly id: string) { super() }
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
      window.dispatchEvent(new CustomEvent('open-note', { detail: this.id }))
    })
    return a
  }
  ignoreEvent() { return true }
}

function build(view: EditorView): DecorationSet {
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
      b.add(start, end, Decoration.replace({ widget: new NoteLinkWidget(m[1], m[2]) }))
    }
  }
  return b.finish()
}

export const noteLinkChips: Extension = ViewPlugin.fromClass(class {
  decorations: DecorationSet
  constructor(view: EditorView) { this.decorations = build(view) }
  update(u: ViewUpdate) {
    if (u.docChanged || u.viewportChanged || u.selectionSet) this.decorations = build(u.view)
  }
}, { decorations: (v) => v.decorations })
