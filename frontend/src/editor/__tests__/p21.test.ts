// @vitest-environment jsdom
/**
 * P21：保留期 + ⌘K 里的去处 + 日记 ribbon 那一块。
 *
 * 这一批钉的几条，每一条都对应一个**页面上看得见**的毛病：
 *   · 启动栏有、⌘K 里没有（屏幕活动 / 写作 Skill）——靠 ⌘K 导航的人找不到
 *   · 「留多久」说不出用户能据此决定的数
 *   · 「全部删掉」之前一句「确定吗」不算说清楚删的是什么
 *   · 日记 ribbon 点进去落错日子（拿今天的年份凑去年那篇日记）
 */
import { describe, expect, it, vi } from 'vitest'

import { COMMANDS } from '../../components/CommandPalette'
import { sayKeep, saySize, wipeLines } from '../../components/JourneyRetentionPanel'
import type { JourneyRetention } from '../../api'
import { DESTINATIONS, paletteLabel } from '../../util/destinations'
import { journalDateOf } from '../../util/journalDate'
import { JOURNEY_DAY_EVENT, openJourneyDay, takePendingJourneyDay } from '../../util/journeyOpen'

describe('⌘K 里的去处（P20 清单 #10）', () => {
  it('启动栏上的每个去处，⌘K 里都列得出来', () => {
    // **钉的是结果，不是「两处一样」**：两处从同一份生成，那「一样」是白给的；
    // 这里要的是「⌘K 这个列表里真的有屏幕活动这一条」。
    for (const d of DESTINATIONS) {
      expect(COMMANDS.map((c) => c.label)).toContain(paletteLabel(d))
    }
    expect(COMMANDS.map((c) => c.label)).toContain('今天的屏幕活动')
  })

  it('屏幕活动打「屏幕」「今天」都搜得到——⌘K 是搜出来的', () => {
    // 面板的筛法就是 label.includes(q)
    const hit = (q: string) => COMMANDS.filter((c) => c.label.includes(q)).map((c) => c.label)
    expect(hit('屏幕')).toContain('今天的屏幕活动')
    expect(hit('今天')).toContain('今天的屏幕活动')
    expect(hit('Skill')).toContain('写作 Skill')
  })

  it('点那一条发的是 open-virtual + 它自己的 id', () => {
    const seen: string[] = []
    const on = (e: Event) => seen.push((e as CustomEvent<string>).detail)
    window.addEventListener('open-virtual', on)
    COMMANDS.find((c) => c.label === '今天的屏幕活动')!.run()
    window.removeEventListener('open-virtual', on)
    expect(seen).toEqual(['app:journey'])
  })
})

describe('留多久：写给人看的那几个数', () => {
  it('天数写成人话，0 是「一直留着」', () => {
    expect(sayKeep(0)).toBe('一直留着')
    expect(sayKeep(7)).toBe('1 周（7 天）')
    expect(sayKeep(30)).toBe('1 个月（30 天）')
    expect(sayKeep(90)).toBe('3 个月（90 天）')
    expect(sayKeep(1)).toBe('1 天')
  })

  it('体量不出现「0.0 MB」——那读起来像坏了，不像「没有东西」', () => {
    expect(saySize(0)).toBe('没占地方')
    expect(saySize(400)).toBe('1 KB')
    expect(saySize(3 * 1024 * 1024)).toBe('3.0 MB')
    expect(saySize(136 * 1024 * 1024)).toBe('136 MB')
    expect(saySize(2.5 * 1024 * 1024 * 1024)).toBe('2.5 GB')
  })

  it('「全部删掉」之前要一条条说清楚删的是什么', () => {
    const r = { days: 4, segments: 295, described: 143, thumbs: 420, reports: 2,
                bytes: 136 * 1024 * 1024, oldest: '2026-09-16' } as JourneyRetention
    const lines = wipeLines(r)
    // 天数 / 段数 / 缩略图 / 日报 / 知识库里的记忆 / 体量：六样都得说到
    expect(lines.join('\n')).toContain('4 天')
    expect(lines.join('\n')).toContain('2026-09-16')
    expect(lines.join('\n')).toContain('295 段')
    expect(lines.join('\n')).toContain('420 张缩略图')
    expect(lines.join('\n')).toContain('2 份写好的日报')
    expect(lines.join('\n')).toContain('知识库')
    expect(lines.join('\n')).toContain('136 MB')
  })

  it('没有缩略图 / 没有日报时就不说那两行——说了是假的', () => {
    const r = { days: 1, segments: 3, described: 0, thumbs: 0, reports: 0,
                bytes: 1024, oldest: '2026-09-19' } as JourneyRetention
    expect(wipeLines(r).join('\n')).not.toContain('缩略图')
    expect(wipeLines(r).join('\n')).not.toContain('日报')
  })
})

describe('日记那篇笔记是哪一天（ribbon 那一块，计划 §8.4）', () => {
  const tree = [
    { note_id: 'root', parent_note_id: '', title: '根' },
    { note_id: 'j', parent_note_id: 'root', title: '日记' },
    { note_id: 'y25', parent_note_id: 'j', title: '2025' },
    { note_id: 'y26', parent_note_id: 'j', title: '2026' },
    { note_id: 'm09-25', parent_note_id: 'y25', title: '09 月' },
    { note_id: 'm09', parent_note_id: 'y26', title: '09 月' },
    { note_id: 'd14', parent_note_id: 'm09', title: '09-14 周日' },
    { note_id: 'd14old', parent_note_id: 'm09-25', title: '09-14 周日' },
    { note_id: 'other', parent_note_id: 'root', title: '产品取舍' },
    { note_id: 'fake-y', parent_note_id: 'root', title: '2026' },
    { note_id: 'fake-m', parent_note_id: 'fake-y', title: '09 月' },
    { note_id: 'fake-d', parent_note_id: 'fake-m', title: '09-14 号方案' },
  ]

  it('认出日记树上「某一天」那一层', () => {
    expect(journalDateOf(tree, 'd14')).toBe('2026-09-14')
  })

  it('**年份从树上读，不拿今天的年份凑**——去年那篇日记查的是去年那天', () => {
    expect(journalDateOf(tree, 'd14old')).toBe('2025-09-14')
  })

  it('不是日记树上的，一律不认（月 / 年 / 普通笔记 / 长得像的别的子树）', () => {
    expect(journalDateOf(tree, 'm09')).toBeNull()
    expect(journalDateOf(tree, 'y26')).toBeNull()
    expect(journalDateOf(tree, 'other')).toBeNull()
    expect(journalDateOf(tree, 'fake-d')).toBeNull()   // 2026 / 09 月 / 09-14 但树根不是「日记」
    expect(journalDateOf(tree, '不存在')).toBeNull()
  })

  it('月份那层跟当天那层对不上就不认——宁可不显示，也不显示一个错的日子', () => {
    const moved = [...tree, { note_id: 'dx', parent_note_id: 'm09', title: '10-02 周四' }]
    expect(journalDateOf(moved, 'dx')).toBeNull()
  })
})

describe('从 ribbon 打开某一天（util/journeyOpen）', () => {
  it('两条路一起发：开页面的事件 + 已经开着时当场翻天的事件', () => {
    const virt: string[] = []; const day: string[] = []
    const a = (e: Event) => virt.push((e as CustomEvent<string>).detail)
    const b = (e: Event) => day.push((e as CustomEvent<string>).detail)
    window.addEventListener('open-virtual', a)
    window.addEventListener(JOURNEY_DAY_EVENT, b)
    openJourneyDay('2026-09-14', new Date('2026-09-19T10:00:00'))
    window.removeEventListener('open-virtual', a)
    window.removeEventListener(JOURNEY_DAY_EVENT, b)
    expect(virt).toEqual(['app:journey'])
    expect(day).toEqual(['2026-09-14'])
    expect(takePendingJourneyDay()).toBe('2026-09-14')
  })

  it('今天那篇日记进去就是「今天」这一档，不是「翻到过去某天」', () => {
    openJourneyDay('2026-09-19', new Date('2026-09-19T10:00:00'))
    expect(takePendingJourneyDay()).toBe('')
  })

  it('取走就没了：之后用户自己翻天，再刷新不该被拽回去', () => {
    openJourneyDay('2026-09-14', new Date('2026-09-19T10:00:00'))
    expect(takePendingJourneyDay()).toBe('2026-09-14')
    expect(takePendingJourneyDay()).toBe('')
  })
})

describe('「写这一天的回顾」转起来要能停（P20 留给 P21 的第 3 条）', () => {
  it('journeyReport 把 signal 传下去——没有它，停止只是把按钮复位', async () => {
    const seen: RequestInit[] = []
    const fetchMock = vi.fn(async (_u: string, init: RequestInit) => {
      seen.push(init)
      return { ok: true, status: 200, json: async () => ({ date: '', report: '', segments: 0, report_at: '', took_ms: 1 }) } as Response
    })
    vi.stubGlobal('fetch', fetchMock)
    const { journeyReport, journeySpan } = await import('../../api')
    const ctrl = new AbortController()
    await journeyReport('2026-09-18', ctrl.signal)
    await journeySpan(7, ctrl.signal)
    vi.unstubAllGlobals()
    expect(seen).toHaveLength(2)
    expect(seen[0].signal).toBe(ctrl.signal)
    expect(seen[1].signal).toBe(ctrl.signal)
  })
})
