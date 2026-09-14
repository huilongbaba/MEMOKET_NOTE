import { describe, expect, it } from 'vitest'
import { fmtWhen } from '../../util/time'

/** 侧栏按最近排时，光给日期等于没分——同一天写的三篇会显示成一模一样。
 *  分辨力跟着距离走：越近的越需要钟点，越远的越只需要哪一天。 */
describe('列表里的「什么时候」', () => {
  const now = new Date('2026-09-14T15:00:00')
  const at = (s: string) => fmtWhen(new Date(s).toISOString(), now)

  it('今天给钟点——同一天写的几篇得分得开', () => {
    expect(at('2026-09-14T09:05:00')).toBe('今天 09:05')
    expect(at('2026-09-14T14:32:00')).toBe('今天 14:32')
  })

  it('昨天说昨天，也带钟点', () => {
    expect(at('2026-09-13T22:10:00')).toBe('昨天 22:10')
  })

  it('今年内给月日，往年才给全', () => {
    expect(at('2026-09-07T13:29:00')).toBe('09-07')
    expect(at('2025-12-31T13:29:00')).toBe('2025-12-31')
  })

  it('跨月 / 跨年的「昨天」也认得出', () => {
    expect(fmtWhen(new Date('2025-12-31T23:00:00').toISOString(), new Date('2026-01-01T10:00:00')))
      .toBe('昨天 23:00')
  })

  it('空的和坏的不炸', () => {
    expect(fmtWhen('')).toBe('—')
    expect(fmtWhen('不是时间')).toBe('不是时间')
  })
})
