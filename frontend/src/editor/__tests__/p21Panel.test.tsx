// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * 「留多久」那一块在**后端没起来**时长什么样（`docs/edge-cases.md` H 组，P21）。
 *
 * 这两格 P20 记的是「✅ toast 走 json() 的 catch」——**读代码读出来的**。
 * 真跑一遍才发现两件事：
 *   · 这一页的 toast 从来没过 `friendlyError`，后端没起来时用户看到的是
 *     一行英文 `Failed to fetch`（P3 整整一批就是在修这类话）
 *   · 「删掉这一天 / 删一段」压根没有 catch，**一个字都不说**
 *     （实拍 `p21-delday-netdown-before-light`：`promise Failed to fetch` 进日志、
 *     `toasts=[]`，而用户刚点过「确定」——他会以为删掉了）
 *
 * 所以这里判的是**用户看得见的那句话**，不是代码长什么样。
 */

const toasts: { text: string; kind?: string }[] = []
vi.mock('../../toast', () => ({
  toast: (text: string, kind?: string) => { toasts.push({ text, kind }) },
  toastAction: (text: string) => { toasts.push({ text }) },
}))

const KEEP = {
  segment_days: 30, thumb_days: 7, frame_days: 3,
  segment_choices: [7, 14, 30, 90, 180, 0], thumb_choices: [1, 3, 7, 14, 30, 0],
  days: 4, segments: 295, described: 143, thumbs: 420, reports: 2,
  bytes: 3_700_000, oldest: '2026-09-16', failures: [] as string[],
}

let down = false
vi.mock('../../api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../api')
  const boom = () => Promise.reject(new TypeError('Failed to fetch'))
  return {
    ...actual,
    journeyRetention: () => Promise.resolve(KEEP),
    journeySetRetention: () => (down ? boom() : Promise.resolve(KEEP)),
    journeyWipeAll: () => (down ? boom()
      : Promise.resolve({ ...KEEP, days: 0, segments: 0, bytes: 0,
                          swept: { days_removed: ['2026-09-16'], facts_removed: 7 } })),
  }
})

const { default: JourneyRetentionPanel } = await import('../../components/JourneyRetentionPanel')

async function mount(node: React.ReactNode) {
  const el = document.createElement('div')
  document.body.append(el)
  const root = createRoot(el)
  await act(async () => { root.render(node) })
  await act(async () => { await Promise.resolve() })
  return { el, unmount: () => act(() => root.unmount()) }
}

const click = async (el: HTMLElement) => { await act(async () => { el.click() }) }
const byText = (el: HTMLElement, t: string) =>
  Array.from(el.querySelectorAll('button')).find((b) => (b.textContent ?? '').includes(t))!

// jsdom 没有 scrollIntoView（真浏览器里一定有）：补一个空的，不然一挂载就抛
Element.prototype.scrollIntoView = function scrollIntoView() { /* jsdom 里没有 */ }

beforeEach(() => { toasts.length = 0; down = false })
afterEach(() => { document.body.innerHTML = '' })

describe('「留多久」这一块', () => {
  it('一眼能读到：留多久 + 现在盘上有多少', async () => {
    const { el } = await mount(<JourneyRetentionPanel />)
    expect(el.textContent).toContain('4 天')
    expect(el.textContent).toContain('295 段')
    expect(el.textContent).toContain('3.5 MB')
    expect(el.textContent).toContain('2026-09-16')
    // 两个能改的档 + 一个不能改的（大图）
    const sels = el.querySelectorAll('select')
    expect(sels.length).toBe(2)
    expect((sels[0] as HTMLSelectElement).value).toBe('30')
    expect((sels[1] as HTMLSelectElement).value).toBe('7')
    expect(el.textContent).toContain('最多 3 天')
    // 「一直留着」是选项之一，但不是当前值
    expect(Array.from(sels[0].options).map((o) => o.textContent)).toContain('一直留着')
  })

  it('「全部删掉」先摊开会删掉什么，再让人确认', async () => {
    const { el } = await mount(<JourneyRetentionPanel />)
    expect(el.querySelector('.journey-keep-confirm')).toBeNull()
    await click(byText(el, '全部删掉'))
    const box = el.querySelector('.journey-keep-confirm')!
    expect(box.textContent).toContain('4 天的记录')
    expect(box.textContent).toContain('295 段')
    expect(box.textContent).toContain('420 张缩略图')
    expect(box.textContent).toContain('2 份写好的日报')
    expect(box.textContent).toContain('知识库')
    expect(box.textContent).toContain('没有回收站')
    // 「先不删」要能退出来
    await click(byText(el, '先不删'))
    expect(el.querySelector('.journey-keep-confirm')).toBeNull()
  })

  it('删完说清楚删了几天、连带几条记忆', async () => {
    const { el } = await mount(<JourneyRetentionPanel />)
    await click(byText(el, '全部删掉'))
    await click(byText(el, '确认删掉'))
    expect(toasts.at(-1)!.text).toBe('删掉了 1 天的屏幕活动，连带 7 条记忆')
  })

  it('后端没起来：说人话，不是一行 Failed to fetch', async () => {
    const { el } = await mount(<JourneyRetentionPanel />)
    down = true
    await click(byText(el, '全部删掉'))
    await click(byText(el, '确认删掉'))
    expect(toasts.at(-1)!.kind).toBe('error')
    expect(toasts.at(-1)!.text).toContain('连不上应用后台')
    expect(toasts.at(-1)!.text).not.toContain('Failed to fetch')
  })

  it('删不掉的文件原样摆在这一块上——不许静默', async () => {
    KEEP.failures = ['/Users/x/journey/2026-09-16/thumbs/003.jpg：Permission denied']
    try {
      const { el } = await mount(<JourneyRetentionPanel />)
      expect(el.querySelector('.journey-keep-fail')!.textContent).toContain('Permission denied')
      expect(el.textContent).toContain('有 1 个文件没删掉')
    } finally { KEEP.failures = [] }
  })
})
