/** 服务端给的是 UTC ISO（`…+00:00`）。直接 slice 字符串显示出来的是 UTC 时间——
 *  信息面板里「修改 05:38」其实是本地 13:38（实拍）。一律转成本地时间再显示。 */
const pad = (n: number) => String(n).padStart(2, '0')

export function fmtDate(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function fmtDateTime(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.replace('T', ' ').slice(0, 16)
  return `${fmtDate(iso)} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}


/** 列表里的「什么时候」：今天给钟点，昨天说昨天，今年给月日，往年才给全。
 *
 *  侧栏按最近排时，光给日期等于没分——「我昨天写的那篇」和「前天那篇」都写着
 *  一样的 `09-13`，而同一天写的三篇更是完全一样（docs/sidebar-ia-plan.md §3）。
 *  分辨力跟着距离走：越近的越需要钟点，越远的越只需要哪一天。
 */
export function fmtWhen(iso: string, now: Date = new Date()): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10)
  const day = (x: Date) => `${x.getFullYear()}-${pad(x.getMonth() + 1)}-${pad(x.getDate())}`
  const hhmm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  if (day(d) === day(now)) return `今天 ${hhmm}`
  const y = new Date(now); y.setDate(y.getDate() - 1)
  if (day(d) === day(y)) return `昨天 ${hhmm}`
  if (d.getFullYear() === now.getFullYear()) return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  return day(d)
}
