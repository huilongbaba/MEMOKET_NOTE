import { describe, expect, it } from 'vitest'
import { fmtDate, fmtDateTime } from '../../util/time'

describe('时间显示转本地', () => {
  it('UTC ISO 转成本地小时，不再是 UTC 的数字', () => {
    const iso = '2026-09-12T05:38:00+00:00'
    const d = new Date(iso)
    expect(fmtDateTime(iso)).toBe(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`)
    expect(fmtDate('')).toBe('—')
    expect(fmtDate('not-a-date')).toBe('not-a-date'.slice(0, 10))
  })
})
