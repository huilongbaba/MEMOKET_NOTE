import { syntaxTree } from '@codemirror/language'
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language'
import type { EditorState } from '@codemirror/state'
import { Decoration, EditorView, ViewPlugin, type DecorationSet, type ViewUpdate } from '@codemirror/view'
import { tags } from '@lezer/highlight'

/** Content styling -- headings/emphasis/links/code actually look like
 * headings/emphasis/links/code instead of raw '#'/'*'/'`' text, without
 * leaving plain-text mode (the doc is still one string underneath). */
/** 正文的高亮规则。**正文永远 `--fg`，灰色只给元信息**（P1-3，用户第 768 轮：
 *  「正文还有灰色字，根本不便于阅读」）。
 *
 *  实拍里灰掉的是**整条列表项和整段引用块**：lezer-markdown 的样式表写的是
 *  `"OrderedList/... BulletList/..."` → `tags.list`、`"Blockquote/..."` → `tags.quote`，
 *  `/...` 是「这个节点和它所有后代」——原来这里给 `tags.list` 上了 `--muted`，
 *  注释还写着「只有项目符号本身淡一点」，而实际染灰的是列表里每一个字。
 *  harness 写出来的正文一半是列表，于是「正文一半是灰的」。
 *
 *  现在：列表 / 引用块的**文字**不设颜色（继承 `--fg`）；`- ` `1. ` `> ` 这些
 *  记号跟 `#` `**` 一样走 `.cm-syntax-mark` 淡 35%（那是用户第 705 轮前后要过的
 *  「markdown 的格式还是灰色吧」）。`tags.url` 保留 muted：它是 `[文字](地址)` 里的
 *  地址，是标记不是正文。导出成数组是为了让闸能读到它（`__tests__/bodyColor.test.ts`）。 */
export const MARKDOWN_HIGHLIGHT_SPEC = [
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
  { tag: tags.quote, fontStyle: 'italic' },
  // NOT colored like tags.link -- a plain "- " list item isn't clickable,
  // and coloring it the same accent blue as a real link is a misleading
  // affordance (reported directly: "看起来像链接但点不了"). No color at all:
  // the list *content* is body text; only the "- "/"1. " marker is dimmed,
  // via ListMark in MARK_NODES below.
  { tag: tags.list },
]
export const markdownHighlight = HighlightStyle.define(MARKDOWN_HIGHLIGHT_SPEC)

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
export const MARK_NODES = new Set(['HeaderMark', 'QuoteMark', 'LinkMark', 'EmphasisMark', 'CodeMark', 'ListMark'])

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
