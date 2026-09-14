import { describe, expect, it } from 'vitest'
import { dupSuffixes } from '../../util/dupTitles'

const row = (key: string, title: string, at = '') => ({ key, title, at })

describe('树上撞名的那几行', () => {
  it('只给真正撞名的那几行加后缀', () => {
    const d = dupSuffixes([
      row('a', '创业一年回顾', '2026-09-07T06:09:14+00:00'),
      row('b', '创业反思', '2026-09-02T04:44:18+00:00'),
      row('c', '创业一年回顾', '2026-09-10T10:22:53+00:00'),
    ])
    expect([...d.keys()].sort()).toEqual(['a', 'c'])
    expect(d.get('a')).toBe('09-07')
  })

  it('同一天写的两篇要上到分钟——只给日期等于没分开', () => {
    const d = dupSuffixes([
      row('a', '创业一年回顾', '2026-09-07T06:09:14+00:00'),
      row('b', '创业一年回顾', '2026-09-07T12:58:28+00:00'),
    ])
    expect(d.get('a')).toBe('09-07 06:09')
    expect(d.get('b')).toBe('09-07 12:58')
  })

  it('到分钟还分不开就不标：标了也没用', () => {
    const same = '2026-09-07T06:09:14+00:00'
    expect(dupSuffixes([row('a', 'X', same), row('b', 'X', same)]).size).toBe(0)
  })

  it('空标题不算撞名——一列「未命名」不该全挂上日期', () => {
    expect(dupSuffixes([row('a', '', '2026-09-07T06:09:14+00:00'),
                        row('b', '  ', '2026-09-08T06:09:14+00:00')]).size).toBe(0)
  })

  it('两两不同就一个都不标', () => {
    expect(dupSuffixes([row('a', 'A', '2026-09-07T00:00:00+00:00'),
                        row('b', 'B', '2026-09-08T00:00:00+00:00')]).size).toBe(0)
  })

  it('前后空白算同一个名字', () => {
    const d = dupSuffixes([row('a', '创业 ', '2026-09-07T00:00:00+00:00'),
                           row('b', ' 创业', '2026-09-08T00:00:00+00:00')])
    expect(d.size).toBe(2)
  })
})
