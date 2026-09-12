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
