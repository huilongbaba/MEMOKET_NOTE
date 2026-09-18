import { EditorSelection } from '@codemirror/state'
import type { EditorView } from '@codemirror/view'

/** Wrap/unwrap the selection in a symmetric marker (**bold**, *italic*,
 * `code`). Toggles off if the selection is already exactly wrapped, so
 * clicking Bold twice on the same text un-bolds it -- matches the common
 * expectation from every other rich-text-ish editor. */
function wrapSelection(view: EditorView, marker: string) {
  const { state } = view
  const tr = state.changeByRange((range) => {
    const before = state.sliceDoc(Math.max(0, range.from - marker.length), range.from)
    const after = state.sliceDoc(range.to, range.to + marker.length)
    if (before === marker && after === marker) {
      return {
        changes: [
          { from: range.from - marker.length, to: range.from },
          { from: range.to, to: range.to + marker.length },
        ],
        range: EditorSelection.range(range.from - marker.length, range.to - marker.length),
      }
    }
    const text = state.sliceDoc(range.from, range.to)
    return {
      changes: { from: range.from, to: range.to, insert: `${marker}${text}${marker}` },
      range: text
        ? EditorSelection.range(range.from + marker.length, range.to + marker.length)
        : EditorSelection.cursor(range.from + marker.length),
    }
  })
  view.dispatch(state.update(tr))
  view.focus()
}

export function boldCmd(view: EditorView) { wrapSelection(view, '**') }
export function italicCmd(view: EditorView) { wrapSelection(view, '*') }
export function inlineCodeCmd(view: EditorView) { wrapSelection(view, '`') }
export function strikeCmd(view: EditorView) { wrapSelection(view, '~~') }

/** Toggle a line-start prefix (heading/quote/list markers) across every
 * line the selection touches. If every touched line already has the exact
 * prefix, remove it from all of them; otherwise add it to whichever lines
 * don't have it yet. */
function toggleLinePrefix(view: EditorView, prefix: string) {
  const { state } = view
  const tr = state.changeByRange((range) => {
    const startLine = state.doc.lineAt(range.from)
    const endLine = state.doc.lineAt(range.to)
    let hasAll = true
    for (let n = startLine.number; n <= endLine.number; n++) {
      if (!state.doc.line(n).text.startsWith(prefix)) { hasAll = false; break }
    }
    const changes: { from: number; to?: number; insert?: string }[] = []
    let deltaFrom = 0
    let deltaTo = 0
    for (let n = startLine.number; n <= endLine.number; n++) {
      const line = state.doc.line(n)
      if (hasAll) {
        changes.push({ from: line.from, to: line.from + prefix.length })
        if (n === startLine.number) deltaFrom -= prefix.length
        deltaTo -= prefix.length
      } else if (!line.text.startsWith(prefix)) {
        changes.push({ from: line.from, insert: prefix })
        if (n === startLine.number) deltaFrom += prefix.length
        deltaTo += prefix.length
      }
    }
    return {
      changes,
      range: EditorSelection.range(range.from + deltaFrom, range.to + deltaTo),
    }
  })
  view.dispatch(state.update(tr))
  view.focus()
}

const HEADING_RE = /^#{1,6}\s+/

/** Toggle heading level on every touched line. Unlike toggleLinePrefix
 * (which only knows its own exact prefix), this replaces whatever heading
 * level a line already has -- clicking H1 on a line that's currently H2
 * converts it to H1 instead of stacking a second "# " in front of "## ".
 * Only when every touched line is ALREADY exactly this level does the
 * click remove the heading entirely (the toggle-off case). */
function toggleHeading(view: EditorView, level: 1 | 2 | 3) {
  const { state } = view
  const prefix = '#'.repeat(level) + ' '
  const tr = state.changeByRange((range) => {
    const startLine = state.doc.lineAt(range.from)
    const endLine = state.doc.lineAt(range.to)
    let allExact = true
    for (let n = startLine.number; n <= endLine.number; n++) {
      if (!state.doc.line(n).text.startsWith(prefix)) { allExact = false; break }
    }
    const changes: { from: number; to: number; insert?: string }[] = []
    let deltaFrom = 0
    let deltaTo = 0
    for (let n = startLine.number; n <= endLine.number; n++) {
      const line = state.doc.line(n)
      const existing = HEADING_RE.exec(line.text)
      const existingLen = existing ? existing[0].length : 0
      const insert = allExact ? '' : prefix
      changes.push({ from: line.from, to: line.from + existingLen, insert })
      const delta = insert.length - existingLen
      if (n === startLine.number) deltaFrom += delta
      deltaTo += delta
    }
    return {
      changes,
      range: EditorSelection.range(range.from + deltaFrom, range.to + deltaTo),
    }
  })
  view.dispatch(state.update(tr))
  view.focus()
}

export function heading1Cmd(view: EditorView) { toggleHeading(view, 1) }
export function heading2Cmd(view: EditorView) { toggleHeading(view, 2) }
export function heading3Cmd(view: EditorView) { toggleHeading(view, 3) }
export function quoteCmd(view: EditorView) { toggleLinePrefix(view, '> ') }
export function bulletListCmd(view: EditorView) { toggleLinePrefix(view, '- ') }
export function orderedListCmd(view: EditorView) { toggleLinePrefix(view, '1. ') }
export function taskListCmd(view: EditorView) { toggleLinePrefix(view, '- [ ] ') }

export function linkCmd(view: EditorView) {
  const { state } = view
  const tr = state.changeByRange((range) => {
    const text = state.sliceDoc(range.from, range.to)
    if (text) {
      const insert = `[${text}](url)`
      const urlStart = range.from + text.length + 3
      return {
        changes: { from: range.from, to: range.to, insert },
        range: EditorSelection.range(urlStart, urlStart + 3),
      }
    }
    return {
      changes: { from: range.from, to: range.to, insert: '[]()' },
      range: EditorSelection.cursor(range.from + 1),
    }
  })
  view.dispatch(state.update(tr))
  view.focus()
}

export function codeBlockCmd(view: EditorView) {
  const { state } = view
  const tr = state.changeByRange((range) => {
    const text = state.sliceDoc(range.from, range.to)
    const insert = text ? `\`\`\`\n${text}\n\`\`\`` : '```\n\n```'
    const cursorPos = text ? range.from + insert.length : range.from + 4
    return {
      changes: { from: range.from, to: range.to, insert },
      range: EditorSelection.cursor(cursorPos),
    }
  })
  view.dispatch(state.update(tr))
  view.focus()
}

/** 插入一张 3 列的空表格。
 *
 * **放在工具栏而不是 `/` 菜单里**：`/` 是"让 AI 干活"的入口，纯插入的东西
 * 混进去会让那个菜单越长越难用。
 *
 * 前后各留一个空行：markdown 表格必须自成一段，紧贴着上一行文字的话
 * GFM 解析不出来，编辑器里也就渲染不成表格。 */
export function tableCmd(view: EditorView) {
  const { state } = view
  const template = '\n| 列1 | 列2 | 列3 |\n|---|---|---|\n|  |  |  |\n|  |  |  |\n\n'
  const tr = state.changeByRange((range) => ({
    changes: { from: range.from, to: range.to, insert: template },
    // 光标落到第一个数据格里，插完直接就能打字
    range: EditorSelection.cursor(range.from + template.indexOf('|  |') + 2),
  }))
  view.dispatch(state.update(tr))
  view.focus()
}


export function mermaidCmd(view: EditorView) {
  const { state } = view
  const template = '```mermaid\ngraph TD\nA[开始] --> B[结束]\n```'
  const tr = state.changeByRange((range) => ({
    changes: { from: range.from, to: range.to, insert: template },
    range: EditorSelection.cursor(range.from + template.length),
  }))
  view.dispatch(state.update(tr))
  view.focus()
}

/** 跟工具栏按钮同一批动作的键。
 *
 * 原来只有三个，注释写的是「discoverable via the toolbar」——而第 704 轮把常驻
 * 工具条收起来之后，这句话就不成立了：**标题、列表、引用、代码块一个键都没有**
 * （第 706 轮逐条核对我自己给过的理由时发现的）。
 *
 * 选键的规矩：不发明。⌘1…⌘9 已经是「跳到第 n 个标签」，所以标题走 ⌘⌥1/2/3
 * （Notion / Obsidian 同款）；列表走 ⌘⇧7 / ⌘⇧8 / ⌘⇧9（Word / Notion 同款）。
 * 加一个键就要往 `shortcuts.ts` 的表里加一行——**表里查不到的键等于没有**。 */
export const markdownKeymap = [
  { key: 'Mod-b', run: (view: EditorView) => { boldCmd(view); return true } },
  { key: 'Mod-i', run: (view: EditorView) => { italicCmd(view); return true } },
  // 行内代码 ⌘E / 删除线 ⇧⌘X（P13 #4，P10 C3-1 记的「缺行内代码 / 删除线的键」）：Obsidian / Notion 同款，不发明
  { key: 'Mod-e', run: (view: EditorView) => { inlineCodeCmd(view); return true } },
  { key: 'Mod-Shift-x', run: (view: EditorView) => { strikeCmd(view); return true } },
  // ⌘K 是外壳的搜索 / 跳转（Notion、VSCode 的约定），插链接让位到 ⇧⌘K
  { key: 'Mod-Shift-k', run: (view: EditorView) => { linkCmd(view); return true } },
  { key: 'Mod-Alt-1', run: (view: EditorView) => { heading1Cmd(view); return true } },
  { key: 'Mod-Alt-2', run: (view: EditorView) => { heading2Cmd(view); return true } },
  { key: 'Mod-Alt-3', run: (view: EditorView) => { heading3Cmd(view); return true } },
  { key: 'Mod-Shift-7', run: (view: EditorView) => { orderedListCmd(view); return true } },
  { key: 'Mod-Shift-8', run: (view: EditorView) => { bulletListCmd(view); return true } },
  { key: 'Mod-Shift-9', run: (view: EditorView) => { taskListCmd(view); return true } },
]
