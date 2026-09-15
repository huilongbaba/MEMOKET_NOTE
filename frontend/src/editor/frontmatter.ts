/**
 * YAML front-matter 不该被当成标题渲染。
 *
 * **实拍（第 686 轮）**：一篇幻灯片笔记开头是
 *
 *     ---
 *     marp: true
 *     slides: true
 *     ---
 *
 * CommonMark 里没有 front-matter 这回事，`---` 只是「setext 下划线」——于是
 * `slides: true` 被解析成一个二级标题，在编辑器里是一行**加粗放大的字**。
 * 用户的元数据看起来像正文里最重要的一句话。
 *
 * 不去改 markdown 解析器（那要动语法扩展，风险大得多），只在**文档最开头**
 * 那一段加一层行装饰：等宽、弱色、正常字号。判据严格——必须第一行就是 `---`，
 * 且后面 30 行内有闭合的 `---`，中间每行长得像 `key: value` 或是列表项。
 * 判不出来就什么都不做，正文该怎么渲染还怎么渲染。
 */
import { Decoration, EditorView, ViewPlugin, type DecorationSet, type ViewUpdate } from '@codemirror/view'
import { RangeSetBuilder } from '@codemirror/state'

/** 最多往下找几行的闭合 `---`。front-matter 再长也不该超过这个数。 */
const MAX_LINES = 30

const line = Decoration.line({ class: 'cm-frontmatter' })

/** 文档开头那段 front-matter 占到第几行（1-based，闭合的 `---` 那一行）；没有就是 0。 */
export function frontmatterEnd(doc: string): number {
  const lines = doc.split('\n')
  if (lines[0]?.trim() !== '---') return 0
  for (let i = 1; i < Math.min(lines.length, MAX_LINES); i++) {
    const t = lines[i].trim()
    if (t === '---') return i + 1
    // 空行、`key: value`、`- 列表项`、缩进的续行之外的东西 → 这不是 front-matter
    if (t && !/^[\w.-]+\s*:/.test(t) && !/^-\s/.test(t) && !/^\s/.test(lines[i])) return 0
  }
  return 0
}

function build(view: EditorView): DecorationSet {
  const b = new RangeSetBuilder<Decoration>()
  const end = frontmatterEnd(view.state.doc.toString())
  for (let n = 1; n <= end; n++) b.add(view.state.doc.line(n).from, view.state.doc.line(n).from, line)
  return b.finish()
}

export const frontmatterDim = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet
    constructor(view: EditorView) { this.decorations = build(view) }
    update(u: ViewUpdate) { if (u.docChanged) this.decorations = build(u.view) }
  },
  { decorations: (v) => v.decorations },
)
