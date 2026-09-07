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

/** Cmd/Ctrl keybindings for the same actions the toolbar buttons trigger --
 * discoverable via the toolbar, faster via keyboard once learned. */
export const markdownKeymap = [
  { key: 'Mod-b', run: (view: EditorView) => { boldCmd(view); return true } },
  { key: 'Mod-i', run: (view: EditorView) => { italicCmd(view); return true } },
  { key: 'Mod-k', run: (view: EditorView) => { linkCmd(view); return true } },
]
