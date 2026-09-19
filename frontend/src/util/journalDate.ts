/** 这篇笔记是不是**日记里的某一天**，是的话是哪一天。
 *
 * 用在日记那篇笔记的 ribbon 上挂一块「今天的屏幕活动」
 * （`docs/daily-journey-plan.md` §8.4：两边互相找得到，但**不把机器写的内容
 * 直接塞进用户的笔记正文**）。
 *
 * 判法照后端 `store.journal_node` 建出来的那条链：
 * `日记 / 2026 / 09 月 / 09-14 周日`。**按标题认，不按 id**——那棵树本来就是
 * 按标题找的（`journal_node` 的注释：没有属性系统就用最朴素的办法），
 * 用户把「日记」改名之后会另起一棵，这一块也就跟着不认了，两边一致。
 *
 * 年份必须从**树上那一层**读，不能拿今天的年份凑：翻到去年那篇日记时，
 * 屏幕活动会去查一个根本不存在的日子，页面上写「这一天没有记录」——
 * 比不显示更糟（它看起来像个事实）。
 */
export type JournalRow = { note_id: string; parent_note_id: string; title: string }

const DAY = /^(\d{2})-(\d{2})(\s|$)/
const MONTH = /^(\d{2})\s*月$/
const YEAR = /^(\d{4})$/

export function journalDateOf(rows: JournalRow[], noteId: string): string | null {
  const by = new Map(rows.map((r) => [r.note_id, r]))
  const day = by.get(noteId)
  const d = day && DAY.exec(day.title)
  if (!day || !d) return null
  const month = by.get(day.parent_note_id)
  const m = month && MONTH.exec(month.title.trim())
  if (!month || !m) return null
  const year = by.get(month.parent_note_id)
  const y = year && YEAR.exec(year.title.trim())
  if (!year || !y) return null
  // 最上面那一层得真叫「日记」——不然任何一棵 `2026 / 09 月 / 09-14` 形状的
  // 子树都会被当成日记（用户完全可能这么给别的东西编号）
  if (by.get(year.parent_note_id)?.title !== '日记') return null
  // 月份那一层和当天那一层对不上（手动搬过）就不认：宁可不显示，
  // 也不能显示一个错的日子
  if (m[1] !== d[1]) return null
  return `${y[1]}-${d[1]}-${d[2]}`
}
