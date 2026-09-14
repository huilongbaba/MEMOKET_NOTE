import { describe, expect, it } from 'vitest'

import { appColors, bandCells, hhmm, saySpan, stepDay } from '../../components/JourneyPage'

const seg = (start: string, end: string, app = 'Code') =>
  ({ i: 0, start, end, app, title: '', desc: '', n: 1, has_frame: true, has_thumb: false })

describe('屏幕活动那条带', () => {
  it('同一个应用在整页里是同一个颜色，出场顺序决定分到哪一档', () => {
    const c = appColors(['Code', 'Chrome', 'Code', 'Finder'])
    expect(c.get('Code')).toBe('var(--jn-1)')
    expect(c.get('Chrome')).toBe('var(--jn-2)')
    expect(c.get('Finder')).toBe('var(--jn-3)')
  })

  it('第 9 个应用起收进「其他」，不绕回第一档——绕回去等于两个应用同色', () => {
    const c = appColors(Array.from({ length: 10 }, (_, i) => `App${i}`))
    expect(c.get('App7')).toBe('var(--jn-8)')
    expect(c.get('App8')).toBe('var(--jn-other)')
    expect(c.get('App9')).toBe('var(--jn-other)')
  })

  it('中间空出 15 分钟以上就插一格空档，短的间隔不插', () => {
    const cells = bandCells([
      seg('2026-09-14T01:00:00Z', '2026-09-14T02:00:00Z'),
      seg('2026-09-14T02:05:00Z', '2026-09-14T02:30:00Z'),   // 只隔 5 分钟
      seg('2026-09-14T06:00:00Z', '2026-09-14T07:00:00Z'),   // 隔 3.5 小时
    ])
    expect(cells.filter((c) => c.gap)).toHaveLength(1)
    expect(cells).toHaveLength(4)
  })

  it('隔夜那种长空档在带上被封顶，不许把一整天挤成两条缝', () => {
    const cells = bandCells([
      seg('2026-09-13T01:00:00Z', '2026-09-13T02:00:00Z'),
      seg('2026-09-14T01:00:00Z', '2026-09-14T02:00:00Z'),
    ])
    expect(cells.find((c) => c.gap)!.sec).toBe(20 * 60)
  })
})

describe('写给人看的时间', () => {
  it('刚开始记的那一段不能显示成「0 分钟」', () => {
    expect(saySpan(20)).toBe('不到 1 分钟')
    expect(saySpan(0)).toBe('不到 1 分钟')
  })

  it('一小时整不拖一条「0 分钟」的尾巴', () => {
    expect(saySpan(3600)).toBe('1 小时')
    expect(saySpan(3600 + 12 * 60)).toBe('1 小时 12 分钟')
  })

  it('壳写的是 UTC，印出来得是本地时间——差一个时区的时间轴等于没有', () => {
    // 直接截字符串会印成 "01:12"；本地时间才是用户当时看到的钟点
    expect(hhmm('2026-09-14T01:12:00Z')).toBe(
      new Date('2026-09-14T01:12:00Z').toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }))
  })
})

describe('翻天', () => {
  // 新的在前，跟后端 /days 一致
  const days = ['2026-09-14', '2026-09-11', '2026-09-04']

  it('往前翻跳过中间那些没记录的日子', () => {
    // **按日期加一减一会走进一串空日子**：病了一周、出差没带电脑，翻七下才到上一条
    expect(stepDay(days, '', -1)).toBe('2026-09-11')
    expect(stepDay(days, '2026-09-11', -1)).toBe('2026-09-04')
  })

  it('翻回最新那天就还原成空串——日期交给后端算，开着页面过零点才不会钉死', () => {
    expect(stepDay(days, '2026-09-11', 1)).toBe('')
  })

  it('翻到头返回 null（按钮置灰），不是原地不动', () => {
    expect(stepDay(days, '2026-09-04', -1)).toBeNull()
    expect(stepDay(days, '', 1)).toBeNull()
  })

  it('一天记录都没有时哪边都翻不动', () => {
    expect(stepDay([], '', -1)).toBeNull()
  })
})
