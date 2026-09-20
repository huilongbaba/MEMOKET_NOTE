/** 正文从 React 同步进编辑器的那一下，**不要再回声一遍**（P68 A）。
 *
 * ## 这条回声掉了 320 个字
 *
 * `MarkdownEditor` 是双向的：`content` 变了往 CM 里 dispatch 一次；CM 的文档变了
 * 通过 `onChange` 报回去、上层 `setContent`。**回声本身是必要的**——用户自己打的字
 * 只有这条路能进 React。原来靠 `lastEmitted` 这个 ref 防死循环：回声回来的那一份
 * 跟自己刚发出去的一模一样，同步 effect 就不再 dispatch。
 *
 * 防得住死循环，**防不住过期的回声盖掉新值**。智能续写流式写入时一秒钟几十次
 * `setContent`，而回声那一下 `onChange(旧文档)` 是在**同步 effect 里**发出的：
 * React 把它排在后面处理，于是「刚到的那一片」被「上一片的回声」盖回去。
 * P68 实拍（打包壳、真 CM、`--mode adv` 三轮）：
 *
 *     sync 735 -> 807 · emit 735 -> 807      ← 回声排队
 *     roundEnd r=3 server=1103 live=1103 cm=807
 *     done  server=1103 live=1103 cm=807 delta=1060
 *     save  content=807                      ← 自动保存把 807 写回库
 *
 * 后端交出去、并且已经 commit 进库的是 **1103 字**，编辑器里只剩 **807**——
 * 少掉的 296 字是 AI 写的最后一段，而且**自动保存 1.5 秒后把这份短的写回了库**，
 * 把后端刚落的那一份盖掉。界面上同时摆着「+1060 字」和一篇 807 字的正文
 * （P64 问题 #1 / P66 问题 #1 读到的「+1060 vs +740」就是这个，三批都记成了
 * 「计数没跟着 `ship_best` 回退」——**方向反了**：那个计数是对的，丢字的是正文）。
 *
 * ## 判据宁可窄
 *
 * 这里**不是**「同步来的改动一律不回声」：CM 有可能把我们发过去的改动再改一道
 * （别的扩展在同一条事务上追加），那一份只有回声报得上去。所以标注里带上**我们
 * 发过去的那一份正文**，回来时**逐字比一次**：一模一样才当回声扔掉，不一样照报。
 */
import { Annotation } from '@codemirror/state'
import type { ViewUpdate } from '@codemirror/view'

/** 这条事务是「React 的 content 同步进来」那一下；值 = 同步过去的那一份正文。 */
export const syncedFromApp = Annotation.define<string>()

/** 这次更新是我们自己刚同步进去的那一份、逐字没被改过 —— 那就别再回声给 React。 */
export function isAppEcho(update: ViewUpdate, text: string): boolean {
  return update.transactions.some((t) => t.annotation(syncedFromApp) === text)
}
