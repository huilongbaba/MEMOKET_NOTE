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
