/** 把一段流式写进来的文字封成**一个**撤销单位（P10 C3-2）。
 *
 *  续写是一片一片 dispatch 进来的；CM6 的 history 只把 500ms 内相邻的改动并成一组
 *  （`newGroupDelay`），真模型流式中途停顿 >500ms 很常见（工具调用、网络抖动）——实拍
 *  `p10-undo-before`（假模型四片各隔 900ms）：⌘Z 一次只撤掉 22 / 48 字，按四次才干净，
 *  第五次就吃掉用户自己的字。Notion 里 AI 写的一段是一个撤销步。
 *
 *  做法：写完之后把那段**不记历史地**删掉、再**记历史地**原样插回——两笔在同一次 dispatch 里
 *  应用，DOM 不闪；history 里只剩「插入这一整段」一条，前面那些片段事件被删除映射成空、自动丢掉。 */
import { Transaction } from '@codemirror/state'
import type { EditorView } from '@codemirror/view'

/** `text` 给了就核对一遍：正文跟预期对不上（用户已经在改）就什么都不做，宁可留着碎片也不动错地方。 */
export function sealAsOneUndo(view: EditorView, from: number, to: number, text?: string): boolean {
  if (to <= from || to > view.state.doc.length) return false
  const cur = view.state.sliceDoc(from, to)
  if (text != null && cur !== text) return false
  const sel = view.state.selection
  // **两个事务，不是一个带两笔的事务**：`dispatch(specA, specB)` 会把 spec 合成一个事务，addToHistory=false
  // 就盖住了整笔、净变化为空，history 里什么都不剩（第一版实拍 ⌘Z 只撤掉前面的换行）。
  const del = view.state.update({ changes: { from, to }, annotations: [Transaction.addToHistory.of(false)] })
  const ins = del.state.update({ changes: { from, insert: cur }, selection: sel, userEvent: 'input.ai' })
  view.dispatch([del, ins])
  return true
}
