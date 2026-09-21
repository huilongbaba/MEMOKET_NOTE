/** 轮次卡**按 note id 存**（P95 A，收 P93 问题 #1）。
 *
 * ── 那个洞长什么样（P93 在真壳上实拍的）────────────────────────────────────
 * 在 A 篇跑完 2 轮智能续写，⌘K 新建一篇**空**笔记（`0 字`、正文空），
 * 右栏「计划」那一格上写着 **`计划 2`**，底下摆着 **A 篇那两轮的执行记录**，
 * 连「本轮写出的正文（72 字）」都在。
 *
 * 根因：`agentRounds` 原来是**一整个 App 一份**的 `useState`，
 * 只在 harness **开跑那一刻**被清（`setAgentRounds([])`），
 * **没有任何一条「换篇就清」的路**——而 P17 给 `verifyResult` / `roundDiff`
 * 各立过一条 `useEffect(() => setX(null), [current?.id])`。
 *
 * ── 为什么不照抄 P17 那两条 ───────────────────────────────────────────────
 * P17 那两条清的是**消息**，清掉就是清掉：
 *   · `verifyResult` 是「**按 A 的选区**算出来的校验结果」，换篇之后它说的那一段
 *     根本不在屏幕上，**清掉之后没有任何东西该回来**；
 *   · `roundDiff` 是「给编辑器的一条**加一层**消息」，层本身活在编辑器的 field 里，
 *     **消息发过就该作废**（不作废的话编辑器一重挂就按旧坐标再加一遍层）。
 *
 * 轮次卡不是消息，是**这一篇的一段历史**：它只活在内存里（不落库），
 * 所以照抄那个形状 = 「跑着 harness 切走再切回，这一次跑的卡**永久丢**」。
 * P93 正是因为这个代价判了「这一批不改」，并写着**正经改法是按 note id 存**。
 * 这份模块就是那个改法。
 *
 * ── 它顺手把另外两件事也治了 ──────────────────────────────────────────────
 *  · **虚拟页**（知识库 / 设置…，`current === null`）：`noteId` 空 ⇒ 一格都读不到，
 *    不再拿上一篇的卡充数（P91 A 是在 `planTabContent` 那一侧挡的，这儿是源头）。
 *  · **两篇之间互不串台**：A 在跑、切到 B，B 上看到的是 B 自己的（空的）。
 *
 * ── 它答不了 / 没管什么（**这一段别含糊过去**）────────────────────────────
 *  · **切走的那几秒里到达的事件照旧丢。** `App.tsx` 那个 `guarded` 包装
 *    （「run 属于 noteId 那篇，用户切走之后它的每个事件都不该碰现在显示的这篇」）
 *    在 `HEAD` 上就是这么拦的，这一批**一个字没动**——动它要连正文那一半一起动，
 *    那是另一件事。所以改完之后「切走再切回」丢的是**那段时间的轮次**，
 *    **切走之前那几轮还在**（P93 担心的「永久丢」是指连之前的也没了）。
 *  · **不落库**：关掉 app 还是没了，跟改之前一样。
 *  · **多大算多**：一次会话里跑过 harness 的篇数就是这张表的条数（跑一次 harness
 *    是几十秒的事，不是敲一下键），所以**没做上限**；真要长到该收了，
 *    那是另一条判据，不在这儿偷偷加。
 */
import type { AgentRound } from '../components/AgentActivity'

/** 这一篇一轮都没跑过时返回的那一份。
 *
 *  **模块级常量，不是每次现造一个 `[]`**：它直接当 `<AgentActivity rounds={…}>`
 *  的 prop，每次新引用会让「这一篇没变」这件事在 React 那一侧看起来像变了。
 *  **别往里 `push`**——所有写入都走 {@link writeRoundsIn}，它只造新数组。 */
export const NO_ROUNDS: AgentRound[] = []

/** note id → 那一篇的轮次卡。**键是 note id，不是标题、不是序号。** */
export type RoundsByNote = Record<string, AgentRound[]>

/** 这一篇的轮次卡。
 *
 *  `noteId` 是空 / `null` / `undefined`（虚拟页、还没开笔记）⇒ **空**，
 *  不是「上一篇那一份」——**这一条就是 P93 问题 #1 的正面**。 */
export function roundsFor(m: RoundsByNote, noteId: string | null | undefined): AgentRound[] {
  if (!noteId) return NO_ROUNDS
  return m[noteId] ?? NO_ROUNDS
}

/** 往**某一篇**的轮次卡上写。`noteId` 是必给的——「往当前这篇写」正是那个洞。
 *
 *  `fn` 原样返回（没改）⇒ 整张表原样返回，不造新对象：
 *  `setState` 拿到同一个引用就不会白重渲染一次。 */
export function writeRoundsIn(
  m: RoundsByNote, noteId: string, fn: (rs: AgentRound[]) => AgentRound[],
): RoundsByNote {
  const prev = m[noteId] ?? NO_ROUNDS
  const next = fn(prev)
  if (next === prev) return m
  return { ...m, [noteId]: next }
}
