import { syntaxTree } from '@codemirror/language'
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language'
import type { EditorState } from '@codemirror/state'
import { Decoration, EditorView, ViewPlugin, type DecorationSet, type ViewUpdate } from '@codemirror/view'
import { tags } from '@lezer/highlight'

/** Content styling -- headings/emphasis/links/code actually look like
 * headings/emphasis/links/code instead of raw '#'/'*'/'`' text, without
 * leaving plain-text mode (the doc is still one string underneath). */
export const markdownHighlight = HighlightStyle.define([
  { tag: tags.heading1, fontSize: 'var(--t-read-h1)', fontWeight: 'var(--w-bold)' },
  { tag: tags.heading2, fontSize: 'var(--t-read-h2)', fontWeight: 'var(--w-bold)' },
  { tag: tags.heading3, fontSize: 'var(--t-read-h3)', fontWeight: 'var(--w-bold)' },
  { tag: [tags.heading4, tags.heading5, tags.heading6], fontWeight: 'var(--w-bold)' },
  { tag: tags.emphasis, fontStyle: 'italic' },
  { tag: tags.strong, fontWeight: 'var(--w-bold)' },
  { tag: tags.strikethrough, textDecoration: 'line-through' },
  { tag: tags.link, color: 'var(--accent)', textDecoration: 'underline' },
  { tag: tags.url, color: 'var(--muted)' },
  { tag: tags.monospace, fontFamily: 'var(--mono)', background: 'var(--card-alt)' },
  { tag: tags.quote, fontStyle: 'italic', color: 'var(--muted)' },
  // NOT colored like tags.link -- a plain "- " list item isn't clickable,
  // and coloring it the same accent blue as a real link is a misleading
  // affordance (reported directly: "看起来像链接但点不了"). Only the bullet
  // marker itself gets a light tint, matching how the "- "/"1. " markers
  // are dimmed elsewhere via .cm-syntax-mark, not the list content.
  { tag: tags.list, color: 'var(--muted)' },
])

// The literal delimiter characters (#, *, _, `, >) -- always visible, styled
// gray/muted rather than hidden. An earlier version hid these on every line
// except the one the cursor is on (full Obsidian-style live preview), but
// that made marks pop in/out while typing nearby and felt jumpy for such a
// small, frequent element -- reverted back to a flat gray on explicit
// request ("markdown的格式还是灰色吧"). The bigger, less-frequent case
// (a whole ```mermaid block) gets the cursor-aware hide/show treatment
// instead, see mermaid.ts -- showing both the diagram AND its full source
// at once is real redundant clutter in a way a few gray "**" characters
// mixed into a sentence isn't.
const MARK_NODES = new Set(['HeaderMark', 'QuoteMark', 'LinkMark', 'EmphasisMark', 'CodeMark'])

function markDecorations(state: EditorState): DecorationSet {
  const decos: { from: number; to: number }[] = []
  syntaxTree(state).iterate({
    enter: (node) => {
      if (MARK_NODES.has(node.name)) decos.push({ from: node.from, to: node.to })
    },
  })
  return Decoration.set(
    decos.map((d) => Decoration.mark({ class: 'cm-syntax-mark' }).range(d.from, d.to)),
    true,
  )
}

export const dimSyntaxMarks = ViewPlugin.fromClass(class {
  decorations: DecorationSet
  constructor(view: EditorView) { this.decorations = markDecorations(view.state) }
  update(update: ViewUpdate) {
    if (update.docChanged) this.decorations = markDecorations(update.state)
  }
}, { decorations: (v) => v.decorations })

/** 正文底部垫 30vh（Trilium 的 ScrollPadding）：最后一行也能滚到视线中间，写到文末时光标
 *  不贴着状态栏；点空白处光标落到文末。只给主编辑器——快速查看 / 分屏 / 历史版本 / 回顾
 *  这些只读小窗本身就有高度上限，垫一截空白只是白滚。 */
export const scrollPadding = EditorView.theme({ '.cm-content': { paddingBottom: '30vh' } })

export const editorTheme = EditorView.theme({
  '&': {
    fontSize: 'var(--t-read)',
    backgroundColor: 'transparent',
  },
  '.cm-content': {
    padding: '0',
    lineHeight: 'var(--lh-read)',
    fontFamily: 'inherit',
    caretColor: 'var(--fg)',
  },
  '.cm-scroller': {
    fontFamily: 'inherit',
    minHeight: '60vh',
  },
  '&.cm-focused': { outline: 'none' },
  '.cm-syntax-mark': { opacity: 0.35 },
  /* front-matter：等宽、弱色、正常字号，**盖掉 setext 标题的加粗放大**
     （见 editor/frontmatter.ts 里的来历）。`!important` 是必要的——
     标题样式来自语法高亮，权重比行装饰高。 */
  '.cm-frontmatter': {
    fontFamily: 'var(--mono)',
    fontSize: 'var(--t-sm)',
    color: 'var(--ink-3)',
  },
  '.cm-frontmatter *': {
    fontSize: 'inherit !important',
    fontWeight: 'var(--w-normal) !important',
    color: 'inherit !important',
  },
  '.cm-mermaid-widget': {
    margin: '10px 0',
    padding: '12px',
    borderRadius: 'var(--r)',
    background: 'var(--card-alt)',
    textAlign: 'center',
    fontSize: 'var(--t-md)',
    color: 'var(--muted)',
  },
  '.cm-mermaid-widget svg': { maxWidth: '100%' },
  '.cm-mermaid-autofix-note': {
    fontSize: 'var(--t-xs)',
    color: 'var(--muted)',
    fontStyle: 'italic',
    marginBottom: '6px',
  },
  '.cm-mermaid-error': { textAlign: 'left' },
  '.cm-mermaid-error-msg': { color: 'var(--del)', marginBottom: '6px' },
  '.cm-mermaid-error-code': {
    whiteSpace: 'pre-wrap',
    fontFamily: 'var(--mono)',
    fontSize: 'var(--t-sm)',
    color: 'var(--fg)',
    background: 'var(--card-alt)',
    borderRadius: 'var(--r-sm)',
    padding: '8px',
    margin: 0,
  },
  '.cm-image-embed': {
    maxWidth: '100%',
    maxHeight: '480px',
    borderRadius: 'var(--r-sm)',
    display: 'block',
    margin: '6px 0',
    cursor: 'text',
  },
  '.cm-task-checkbox': {
    cursor: 'pointer',
    marginRight: '4px',
    verticalAlign: 'middle',
    position: 'relative',
    top: '-1px',
  },
})

export { syntaxHighlighting }
