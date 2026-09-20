// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * P50（第 793 轮）：**「描述这 N 段」那个死胡同从另一扇门回来了。**
 *
 * P20 清单 #5 修的是「没大图的别数进去」。它今天仍然成立，但真实数据里
 * 出现了它挡不住的第二种形状——后端 `catch_up` 判定「没有截图」时只写了
 * `skip`，**那条指向不存在的文件的路径留在 `frames` 里**，于是接口上
 * `has_frame` 照样是 true。实拍的量（只读真目录）：
 * 09-16 **37 段**、09-17 **71 段**、09-18 **2 段**。
 *
 * 用户看到的：按钮写着「描述这 10 段」，那些行写着「还没描述」，
 * 点下去只回一句「没有要描述的了」，**按钮和行一个字都不变**——点多少次都一样。
 *
 * 这一份钉的是**用户看得见的东西**：按钮在不在、行上写的是什么、toast 说什么。
 */

const toasts: { text: string; kind?: string }[] = []
vi.mock('../../toast', () => ({
  toast: (text: string, kind?: string) => { toasts.push({ text, kind }) },
  toastAction: (text: string) => { toasts.push({ text }) },
}))

/** 一天：一段等着描述、两段**已经被判出局但 `has_frame` 还说图在**。 */
const DAY = {
  date: '2026-09-19',
  segments: [
    { i: 0, start: '2026-09-19T08:41:00Z', end: '2026-09-19T08:42:00Z', app: 'Code', title: 'a',
      desc: '', has_frame: true, has_thumb: false, skip: '' },
    { i: 1, start: '2026-09-19T09:41:00Z', end: '2026-09-19T09:42:00Z', app: 'Feishu', title: 'b',
      desc: '', has_frame: true, has_thumb: false, skip: '没有截图' },
    { i: 2, start: '2026-09-19T10:41:00Z', end: '2026-09-19T10:42:00Z', app: 'Safari', title: 'c',
      desc: '', has_frame: true, has_thumb: false, skip: '截图已过期' },
  ],
  report: '', report_segments: 0, report_at: '', report_notes: [] as string[],
}
const KEEP = {
  segment_days: 30, thumb_days: 7, frame_days: 3,
  segment_choices: [7, 30, 0], thumb_choices: [1, 7, 0],
  days: 3, segments: 3, described: 0, thumbs: 0, reports: 0,
  bytes: 1000, oldest: '2026-09-18', failures: [] as string[],
}
let catchUpResult = { described: 0, ingested: 0, skipped: 0, left: 0 }
const calls: string[] = []

vi.mock('../../api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../api')
  return {
    ...actual,
    journeyDay: () => Promise.resolve(DAY),
    journeyDays: () => Promise.resolve(['2026-09-19', '2026-09-18']),
    journeyRetention: () => Promise.resolve(KEEP),
    journeyThumb: () => '',
    journeyCatchUp: (d: string, n: number) => { calls.push(`catch-up ${d} ${n}`); return Promise.resolve(catchUpResult) },
  }
})

const { default: JourneyPage } = await import('../../components/JourneyPage')

async function mount(node: React.ReactNode) {
  const el = document.createElement('div')
  document.body.append(el)
  const root = createRoot(el)
  await act(async () => { root.render(node) })
  for (let i = 0; i < 3; i++) await act(async () => { await Promise.resolve() })
  return el
}

const click = async (el: Element) => { await act(async () => { (el as HTMLElement).click() }) }
const byText = (el: HTMLElement, t: string) =>
  Array.from(el.querySelectorAll('button')).find((b) => (b.textContent ?? '').replace(/\s+/g, '').includes(t.replace(/\s+/g, '')))

Element.prototype.scrollIntoView = function scrollIntoView() { /* jsdom 里没有 */ }

beforeEach(() => { toasts.length = 0; calls.length = 0; catchUpResult = { described: 0, ingested: 0, skipped: 0, left: 0 } })
afterEach(() => { document.body.innerHTML = '' })

const page = () => <JourneyPage onLater={() => {}} onOpenNote={() => {}} onOpenJournal={() => {}} />

describe('P50 · 「描述这 N 段」不再是死胡同', () => {
  it('已经被判出局的段不进那个数——3 段里只有 1 段真的等着描述', async () => {
    const el = await mount(page())
    expect(byText(el, '描述这 1 段')).toBeTruthy()
    expect(byText(el, '描述这 3 段')).toBeFalsy()
  })

  it('那两行要说清为什么补不了，而不是一句「还没描述」等着人白等', async () => {
    const el = await mount(page())
    const rows = Array.from(el.querySelectorAll('.journey-desc')).map((e) => (e.textContent ?? '').trim())
    expect(rows).toContain('还没描述')                 // 真等着的那一段照旧
    expect(rows).toContain('没有截图，补不了描述')
    expect(rows).toContain('截图已过期，补不了描述')
  })

  it('一段都没描述成、却写死了几段时，toast 要说真的发生了什么', async () => {
    catchUpResult = { described: 0, ingested: 0, skipped: 9, left: 2 }
    const el = await mount(page())
    await click(byText(el, '描述这 1 段')!)
    expect(calls).toEqual(['catch-up  10'])          // 空日期 = 今天（后端自己取当天）
    expect(toasts[0].text).toBe('这 9 段的截图已经没了，补不了描述，还剩 2 段等着')
  })

  it('真的什么都没发生时照旧是那一句', async () => {
    catchUpResult = { described: 0, ingested: 0, skipped: 0, left: 0 }
    const el = await mount(page())
    await click(byText(el, '描述这 1 段')!)
    expect(toasts[0].text).toBe('没有要描述的了')
  })
})
