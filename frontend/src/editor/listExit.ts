/** Enter 在**空的**列表项 / 引用行上 = 退出（P10 C3-1）。
 *
 *  lang-markdown 的 `insertNewlineContinueMarkup` 对「第二项是空的」这种情况会先在上面插一个空行
 *  （把列表变成 loose list），再按一次 Enter 才删掉记号——实拍：`- [ ] 待办` ⏎ `- [ ] ` ⏎ 多了一个空行、
 *  记号还在；`> ` ⏎ 变成 `>` + `> `。Notion / Obsidian / Typora 都是**一次 Enter 就退出**，
 *  用户第一天写列表就会撞上。这条排在 lang-markdown 的键前面：空项就删记号，不空的照旧续项。 */
import type { EditorView } from '@codemirror/view'
import { Prec } from '@codemirror/state'
import { keymap } from '@codemirror/view'

/** 空的列表项 / 任务项 / 引用行：只剩记号（允许缩进、允许尾随空白） */
export const EMPTY_ITEM = /^(\s*)(?:(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s*)?|>\s*)$/

export function exitEmptyItem(view: EditorView): boolean {
  const { state } = view
  const range = state.selection.main
  if (!range.empty) return false
  const line = state.doc.lineAt(range.head)
  if (range.head !== line.to) return false
  const m = EMPTY_ITEM.exec(line.text)
  if (!m) return false
  // 嵌套的空项：先退一级（`  - ` → `- `），顶层才真的退出——跟 Notion 一样逐级出来
  const indent = m[1]
  const insert = indent.length >= 2 ? indent.slice(0, -2) + line.text.slice(indent.length) : ''
  view.dispatch({ changes: { from: line.from, to: line.to, insert }, selection: { anchor: line.from + insert.length }, userEvent: 'delete' })
  return true
}

export const listExitKeymap = Prec.high(keymap.of([{ key: 'Enter', run: exitEmptyItem }]))
