/** AI 写进来的字怎么并成**一个**撤销单位（P10 C3-2 → P11 #2 → P13 #5：一套机制、两个入口）。
 *
 *  「续写」（tap）和「智能续写」（harness）流进编辑器的每一片都在**编辑器只读**（AI 在写）的时候由
 *  `MarkdownEditor` 的 content 同步落地，落地时就带这里给的 history 标注：一轮的第一片
 *  `isolateHistory('before')` + `input.ai`（另起一条、不许并进用户刚打的字），之后每一片
 *  `userEvent: 'input.type.compose'`——CM 的 history 对 compose 事件**无视 500ms 分组和相邻与否**
 *  一律并进上一条（`HistoryState.addChanges` 的 compose 分支）。于是一轮 = 一条，⌘Z 一次一轮
 *  （修订的 replace / delete 和续写的 insert 一起），再按才轮到用户的字。
 *
 *  「一轮」的边界由入口给：智能续写每轮开跑 App 把 `undoGroup` 加一；「续写」一次就是一轮，
 *  只读一开始就是边界。**P10 那版 `sealAsOneUndo`（写完之后不记历史地删掉、再记历史地插回）
 *  P13 删掉了**：它只封得住一段连续的字，而且那一笔不记历史的改动会把更早的撤销事件沿途映射坏
 *  （P11 实拍第 2 轮删掉第 1 轮的半句再封，⌘Z 两次之后那半句留在正文里）；两个入口一套机制之后
 *  它也没有事可做了。没有任何不记历史的改动，更早的事件一个都不会被映射坏。 */
import type { TransactionSpec } from '@codemirror/state'
import { isolateHistory } from '@codemirror/commands'

export function aiSyncSpec(fresh: boolean): Pick<TransactionSpec, 'userEvent' | 'annotations'> {
  return fresh
    ? { userEvent: 'input.ai', annotations: [isolateHistory.of('before')] }
    : { userEvent: 'input.type.compose' }
}
