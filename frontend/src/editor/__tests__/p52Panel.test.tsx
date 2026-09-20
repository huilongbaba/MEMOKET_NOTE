// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * P52（第 794 轮）：**今天一段记录都没有的那一页**，外加假采集源那条横幅。
 *
 * 三件事，全是「渲染整页、点真的按钮」而不是直接调函数——`stepDay` 那个单元闸
 * 挡不住「调用方忘了把 `today` 传进来」这一路（默认参数会让它悄悄退回老行为）。
 *
 * 背景：后端 `days()` 从这一批起按「有活的段**或者**有日报」列天（P50 问题 #3），
 * 于是**今天不在列表里**这件事从「几乎不会发生」变成了常态：
 * 停了几天没开、或者今天的段被逐条删光，今天就不在 `/days` 里。
 * 而原来的 `stepDay` 把「今天」硬当成 `days[0]`——实拍两个方向都跳过最近记的那一天。
 */

const toasts: { text: string; kind?: string }[] = []
vi.mock('../../toast', () => ({
  toast: (text: string, kind?: string) => { toasts.push({ text, kind }) },
  toastAction: (text: string) => { toasts.push({ text }) },
}))

const TODAY = '2026-09-20'
const asked: string[] = []

/** 今天（09-20）一段都没有；09-19 有段；09-18 段被删光了、只剩那份日报。 */
const DAYS: Record<string, unknown> = {
  '': { date: TODAY, segments: [], report: '', report_segments: 0, report_at: '', report_notes: [] },
  '2026-09-19': {
    date: '2026-09-19', report: '', report_segments: 0, report_at: '', report_notes: [],
    segments: [{ i: 0, start: '2026-09-19T08:41:00Z', end: '2026-09-19T09:42:00Z', app: 'Code',
                 title: 'a', desc: '写 P52', has_frame: false, has_thumb: false, skip: '' }],
  },
  '2026-09-18': {
    date: '2026-09-18', segments: [], report_segments: 7, report_at: '2026-09-18T23:00:00Z',
    report_notes: [], report: '## 时间去哪了\n\n记到 2 小时。\n',
  },
}
const KEEP = {
  segment_days: 30, thumb_days: 7, frame_days: 3,
  segment_choices: [7, 30, 0], thumb_choices: [1, 7, 0],
  days: 2, segments: 1, described: 1, thumbs: 0, reports: 1,
  bytes: 1000, oldest: '2026-09-18', failures: [] as string[],
}

vi.mock('../../api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../api')
  return {
    ...actual,
    journeyDay: (d: string) => { asked.push(d); return Promise.resolve(DAYS[d] ?? DAYS['']) },
    // **今天不在里面**——这一整份的前提
    journeyDays: () => Promise.resolve(['2026-09-19', '2026-09-18']),
    journeyRetention: () => Promise.resolve(KEEP),
    journeyThumb: () => '',
  }
})

const { default: JourneyPage } = await import('../../components/JourneyPage')

async function mount(node: React.ReactNode) {
  const el = document.createElement('div')
  document.body.append(el)
  const root = createRoot(el)
  await act(async () => { root.render(node) })
  for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve() })
  return el
}
const click = async (el: Element) => { await act(async () => { (el as HTMLElement).click() }) }
const settle = async () => { for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve() }) }
const byTitle = (el: HTMLElement, t: string) =>
  el.querySelector(`button[title="${t}"]`) as HTMLButtonElement | null
const byText = (el: HTMLElement, t: string) =>
  Array.from(el.querySelectorAll('button')).find((b) => (b.textContent ?? '').replace(/\s+/g, '').includes(t.replace(/\s+/g, '')))

Element.prototype.scrollIntoView = function scrollIntoView() { /* jsdom 里没有 */ }

beforeEach(() => { toasts.length = 0; asked.length = 0; delete (window as { memoketDesktop?: unknown }).memoketDesktop })
afterEach(() => { document.body.innerHTML = '' })

const page = () => <JourneyPage onLater={() => {}} onOpenNote={() => {}} onOpenJournal={() => {}} />

describe('P52 · 今天不在「有记录的日子」里', () => {
  it('从今天按「上一条记录」落在 09-19，不跳过它', async () => {
    const el = await mount(page())
    expect(el.querySelector('h2')?.textContent).toContain(TODAY)
    await click(byTitle(el, '上一条记录')!)
    await settle()
    // 判的是**真的去问了哪一天**，不是 stepDay 的返回值——调用方忘了传 today 时这条会红
    expect(asked[asked.length - 1]).toBe('2026-09-19')
    expect(el.querySelector('h2')?.textContent).toContain('2026-09-19')
  })

  it('从 09-18 按「下一条记录」也落在 09-19，不一步跳成今天', async () => {
    const el = await mount(page())
    await click(byTitle(el, '上一条记录')!); await settle()      // → 09-19
    await click(byTitle(el, '上一条记录')!); await settle()      // → 09-18
    expect(el.querySelector('h2')?.textContent).toContain('2026-09-18')
    await click(byTitle(el, '下一条记录')!); await settle()
    expect(el.querySelector('h2')?.textContent).toContain('2026-09-19')
  })

  it('翻到 09-19（最近记过的那天）时「下一条记录」置灰 —— 后面没有记录了', async () => {
    const el = await mount(page())
    await click(byTitle(el, '上一条记录')!); await settle()
    expect(byTitle(el, '下一条记录')!.disabled).toBe(true)
  })
})

describe('P52 · 段删光了只剩日报的那一天', () => {
  it('「删掉这一天」不再置灰 —— 后端把它列出来了，就得删得掉', async () => {
    const el = await mount(page())
    await click(byTitle(el, '上一条记录')!); await settle()
    await click(byTitle(el, '上一条记录')!); await settle()
    expect(el.querySelector('h2')?.textContent).toContain('2026-09-18')
    expect(el.querySelector('.journey-report')).toBeTruthy()      // 日报卡真的在
    const del = byText(el, '删掉这一天')!
    expect(del.disabled).toBe(false)
  })

  it('确认框里不写「0 段」这种废话，只写真会被删掉的那几样', async () => {
    const el = await mount(page())
    await click(byTitle(el, '上一条记录')!); await settle()
    await click(byTitle(el, '上一条记录')!); await settle()
    await click(byText(el, '删掉这一天')!)
    const box = el.querySelector('.journey-keep-confirm')!
    const items = Array.from(box.querySelectorAll('li')).map((e) => (e.textContent ?? '').trim())
    expect(items).toEqual(['这一天写好的那份日报'])
    expect(box.textContent).toContain('删完就真的没有了，没有回收站')
  })

  it('正常的一天一个字没变 —— 四行照旧', async () => {
    const el = await mount(page())
    await click(byTitle(el, '上一条记录')!); await settle()       // 09-19，1 段有描述
    await click(byText(el, '删掉这一天')!)
    const items = Array.from(el.querySelectorAll('.journey-keep-confirm li')).map((e) => (e.textContent ?? '').trim())
    expect(items).toEqual(['1 段，其中 1 段有描述', '这些描述抽进知识库的那些记忆'])
  })
})

describe('P52 · 假采集源要在页面上吵', () => {
  const withBridge = (fake: boolean) => {
    (window as unknown as { memoketDesktop: unknown }).memoketDesktop = {
      journey: {
        state: () => Promise.resolve({ state: 'running', today: 0, until: 0, stalled: '', fake }),
        start: () => Promise.resolve(), pause: () => Promise.resolve(),
        resume: () => Promise.resolve(), stop: () => Promise.resolve(),
      },
    }
  }

  it('挂着假采集源时页面上写清楚这不是真的屏幕活动', async () => {
    withBridge(true)
    const el = await mount(page())
    const txt = (el.textContent ?? '').replace(/\s+/g, '')
    expect(txt).toContain('这一页画的不是真的屏幕活动')
    expect(txt).toContain('journey/_fake.json')
    expect(txt).toContain('删掉那个文件再重开才会真的记')
  })

  it('没挂假采集源时一个字都不多 —— 误报比漏报更糟', async () => {
    withBridge(false)
    const el = await mount(page())
    expect(el.textContent ?? '').not.toContain('不是真的屏幕活动')
  })

  it('老壳（压根不回 fake 这一格）也不许冒出那一句', async () => {
    (window as unknown as { memoketDesktop: unknown }).memoketDesktop = {
      journey: {
        state: () => Promise.resolve({ state: 'running', today: 0 }),
        start: () => Promise.resolve(), pause: () => Promise.resolve(),
        resume: () => Promise.resolve(), stop: () => Promise.resolve(),
      },
    }
    const el = await mount(page())
    expect(el.textContent ?? '').not.toContain('不是真的屏幕活动')
  })
})
