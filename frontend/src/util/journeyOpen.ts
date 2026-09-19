/** 「打开某一天的屏幕活动」这一下怎么走。
 *
 * 两条路一起用，因为**那一页可能还没挂上、也可能已经开着**：
 *   · 还没开：`open-virtual` 把它开出来，`JourneyPage` 挂载时**取走**这个日期
 *   · 已经开着：`openVirtual` 会提前 return（同一个虚拟 id 不重开），页面不重挂，
 *     所以还得有一个事件让它当场翻过去
 *
 * 少任何一条，从日记 ribbon 点第二次就没反应——这类「第二次点没用」的毛病
 * 最难被发现，因为第一次总是对的。
 */
export const JOURNEY_DAY_EVENT = 'journey-day'

let pending = ''

/** 今天用空串：那一页的「今天」和「某一天」是两种状态（页头那句「记录中」
 *  只在今天说），传一个等于今天的日期会把它降级成「翻到过去某天」。 */
export function openJourneyDay(date: string, today = new Date()): void {
  const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
  pending = date === iso ? '' : date
  window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'app:journey' }))
  window.dispatchEvent(new CustomEvent(JOURNEY_DAY_EVENT, { detail: pending }))
}

/** 取走待打开的那一天（**取走** = 只生效一次：之后用户自己翻天，
 *  再刷新不该被拽回去）。 */
export function takePendingJourneyDay(): string {
  const d = pending
  pending = ''
  return d
}

// ---------------------------------------------------------------- ⌘K 的「这一周的屏幕活动」

/**
 * **它打开什么，以及为什么不直接跑**（P23 #7，计划 §8.4 剩下的那半条）。
 *
 * 「最近 7 天的回顾」是**一次模型调用**：几十秒到几分钟，本地模型上更久，还会在
 * 树上落下一篇笔记。P21 把这半条留下来时写的就是这句话——「不能在 ⌘K 里直接花钱」。
 * 三条各自独立的理由，任何一条成立就够：
 *
 *   1. **⌘K 是一路回车过去的**。挑中一条命令的动作是「敲两个字 + Enter」，没有第二次
 *      确认。这一页上所有花钱的钮旁边都写着代价（「按一下是一次模型调用」），⌘K 的
 *      列表里没有摆这句话的地方。
 *   2. **停止键在那一页上**（P21 #5 刚给它接的 `AbortController`）。从 ⌘K 起跑 = 让一件
 *      要跑几分钟的事在它唯一的出口还没画出来时就开始——P3 立的那条「非流式动作要有
 *      停止」会当场破功。
 *   3. **范围得由用户挑**。7 天和 30 天是两个价钱，⌘K 里选了「这一周」就等于替他把
 *      范围也定了。
 *
 * 所以这一条命令干的是：**打开屏幕活动那一页 → 滚到「回顾一段时间」→ 把「最近 7 天」
 * 那个钮标成主按钮并说明白为什么这一下留给你按**。它是导航，跟 ⌘K 里别的去处一样。
 */
export const JOURNEY_SPAN_EVENT = 'journey-span'
/** ⌘K 那一条指的是几天。改这个数要连 `CommandPalette` 里那条命令的名字一起改。 */
export const JOURNEY_SPAN_DAYS = 7

let pendingSpan = 0

export function openJourneySpan(days = JOURNEY_SPAN_DAYS): void {
  pendingSpan = days
  window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'app:journey' }))
  window.dispatchEvent(new CustomEvent(JOURNEY_SPAN_EVENT, { detail: days }))
}

/** 取走待提示的那个范围（跟 `takePendingJourneyDay` 同一条规矩：只生效一次）。 */
export function takePendingJourneySpan(): number {
  const d = pendingSpan
  pendingSpan = 0
  return d
}
