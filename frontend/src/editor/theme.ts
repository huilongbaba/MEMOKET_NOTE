import { syntaxTree } from '@codemirror/language'
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language'
import type { EditorState } from '@codemirror/state'
import { Decoration, EditorView, ViewPlugin, type DecorationSet, type ViewUpdate } from '@codemirror/view'
import { tags } from '@lezer/highlight'

/** Content styling -- headings/emphasis/links/code actually look like
 * headings/emphasis/links/code instead of raw '#'/'*'/'`' text, without
 * leaving plain-text mode (the doc is still one string underneath). */
export const markdownHighlight = HighlightStyle.define([
  { tag: tags.heading1, fontSize: '1.6em', fontWeight: '700' },
  { tag: tags.heading2, fontSize: '1.4em', fontWeight: '700' },
  { tag: tags.heading3, fontSize: '1.2em', fontWeight: '700' },
  { tag: [tags.heading4, tags.heading5, tags.heading6], fontWeight: '700' },
  { tag: tags.emphasis, fontStyle: 'italic' },
  { tag: tags.strong, fontWeight: '700' },
  { tag: tags.strikethrough, textDecoration: 'line-through' },
  { tag: tags.link, color: 'var(--accent, #4a7dfc)', textDecoration: 'underline' },
  { tag: tags.url, color: 'var(--muted, #888)' },
  { tag: tags.monospace, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', background: 'var(--card-alt, rgba(127,127,127,0.12))' },
  { tag: tags.quote, fontStyle: 'italic', color: 'var(--muted, #888)' },
  // NOT colored like tags.link -- a plain "- " list item isn't clickable,
  // and coloring it the same accent blue as a real link is a misleading
  // affordance (reported directly: "看起来像链接但点不了"). Only the bullet
  // marker itself gets a light tint, matching how the "- "/"1. " markers
  // are dimmed elsewhere via .cm-syntax-mark, not the list content.
  { tag: tags.list, color: 'var(--muted, #888)' },
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

export const editorTheme = EditorView.theme({
  '&': {
    fontSize: '16px',
    backgroundColor: 'transparent',
  },
  '.cm-content': {
    padding: '0',
    lineHeight: '1.8',
    fontFamily: 'inherit',
    caretColor: 'var(--fg, #111)',
  },
  '.cm-scroller': {
    fontFamily: 'inherit',
    minHeight: '60vh',
  },
  '&.cm-focused': { outline: 'none' },
  '.cm-syntax-mark': { opacity: 0.35 },
  '.cm-mermaid-widget': {
    margin: '10px 0',
    padding: '12px',
    borderRadius: '8px',
    background: 'var(--card-alt, rgba(127,127,127,0.06))',
    textAlign: 'center',
    fontSize: '13px',
    color: 'var(--muted, #888)',
  },
  '.cm-mermaid-widget svg': { maxWidth: '100%' },
  '.cm-mermaid-autofix-note': {
    fontSize: '11px',
    color: 'var(--muted, #888)',
    fontStyle: 'italic',
    marginBottom: '6px',
  },
  '.cm-mermaid-error': { textAlign: 'left' },
  '.cm-mermaid-error-msg': { color: 'var(--del, #d33)', marginBottom: '6px' },
  '.cm-mermaid-error-code': {
    whiteSpace: 'pre-wrap',
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    fontSize: '12px',
    color: 'var(--fg, #111)',
    background: 'var(--card-alt, rgba(127,127,127,0.12))',
    borderRadius: '6px',
    padding: '8px',
    margin: 0,
  },
  '.cm-image-embed': {
    maxWidth: '100%',
    maxHeight: '480px',
    borderRadius: '6px',
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
