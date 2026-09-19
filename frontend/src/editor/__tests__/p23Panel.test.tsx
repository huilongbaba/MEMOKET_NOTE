// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * P23（`docs/TRACELOG-product.md` P23 节）里**用户看得见的那几处**：
 *
 *   5. 删一段 / 删掉这一天：页面里的确认，不再是 `window.confirm`
 *      （P21 实拍：系统弹窗会把整个渲染进程挡住，探针都得靠 `confirmyes` 才过得去）
 *   6. 屏幕活动 → 「去这天的日记」（反过来那条路）
 *   7. ⌘K 的「这一周的屏幕活动」：**打开并指出来，不替你花那一次模型调用**
 *   8. 临界条件表剩下的 ？：「生成写作计划」转起来要能停 / 引用补一条 · 改的空文本
 *
 * 判的是**用户看得见的东西**（有没有那句话、钮点不点得动、发没发请求），不是代码长什么样。
 */

const toasts: { text: string; kind?: string }[] = []
vi.mock('../../toast', () => ({
  toast: (text: string, kind?: string) => { toasts.push({ text, kind }) },
  toastAction: (text: string) => { toasts.push({ text }) },
}))

const DAY = {
  date: '2026-09-19',
  segments: [
    { i: 0, start: '2026-09-19T08:41:00Z', end: '2026-09-19T08:42:00Z', app: 'Code', title: 'x',
      desc: '在改 journey.py', has_frame: false, has_thumb: true },
    { i: 1, start: '2026-09-19T08:42:00Z', end: '2026-09-19T08:45:00Z', app: 'Feishu', title: 'y',
      desc: '', has_frame: true, has_thumb: false },
  ],
  report: '', report_segments: 0, report_at: '', report_notes: [] as string[],
}
const KEEP = {
  segment_days: 30, thumb_days: 7, frame_days: 3,
  segment_choices: [7, 30, 0], thumb_choices: [1, 7, 0],
  days: 4, segments: 295, described: 143, thumbs: 420, reports: 2,
  bytes: 3_700_000, oldest: '2026-09-16', failures: [] as string[],
}
const calls: string[] = []

vi.mock('../../api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../api')
  return {
    ...actual,
    journeyDay: () => Promise.resolve(DAY),
    journeyDays: () => Promise.resolve(['2026-09-19', '2026-09-18']),
    journeyRetention: () => Promise.resolve(KEEP),
    journeyThumb: () => '',
    journeyDeleteSegment: (d: string, i: number) => {
      calls.push(`del-seg ${d} ${i}`)
      return Promise.resolve({ removed_facts: 2 })
    },
    journeyDeleteDay: (d: string) => { calls.push(`del-day ${d}`); return Promise.resolve({ removed_facts: 9 }) },
    journeyCatchUp: () => Promise.resolve({ described: 0, ingested: 0, left: 0 }),
    // **花钱的那一下**：⌘K 过来时它一次都不该被叫到
    journeySpan: (days: number) => { calls.push(`span ${days}`); return Promise.resolve({ days, missing: [], note_id: 'n' }) },
  }
})

const { default: JourneyPage } = await import('../../components/JourneyPage')
const { openJourneySpan, takePendingJourneySpan, JOURNEY_SPAN_DAYS } = await import('../../util/journeyOpen')

async function mount(node: React.ReactNode) {
  const el = document.createElement('div')
  document.body.append(el)
  const root = createRoot(el)
  await act(async () => { root.render(node) })
  await act(async () => { await Promise.resolve() })
  await act(async () => { await Promise.resolve() })
  return { el, unmount: () => act(() => root.unmount()) }
}

const click = async (el: Element) => { await act(async () => { (el as HTMLElement).click() }) }
const byText = (el: HTMLElement, t: string) =>
  Array.from(el.querySelectorAll('button')).find((b) => (b.textContent ?? '').replace(/\s+/g, '').includes(t.replace(/\s+/g, '')))

Element.prototype.scrollIntoView = function scrollIntoView() { /* jsdom 里没有 */ }

beforeEach(() => { toasts.length = 0; calls.length = 0; takePendingJourneySpan() })
afterEach(() => { document.body.innerHTML = '' })

const page = (extra: Partial<{ onOpenJournal: (d: string) => void }> = {}) => (
  <JourneyPage onLater={() => {}} onOpenNote={() => {}}
               onOpenJournal={extra.onOpenJournal ?? (() => {})} />
)

describe('#5 删一段 / 删掉这一天：页面里的确认', () => {
  it('删掉这一天：先摊开要删的东西，确认了才发请求', async () => {
    const confirmSpy = vi.fn(() => true)
    vi.stubGlobal('confirm', confirmSpy)
    const { el } = await mount(page())
    await click(byText(el, '删掉这一天')!)
    // **不许碰系统弹窗**（它会把整个渲染进程挡住）
    expect(confirmSpy).not.toHaveBeenCalled()
    // 摊开的那几行要说清删的是什么
    expect(el.textContent).toContain('删掉 2026-09-19 的屏幕活动')
    expect(el.textContent).toContain('2 段，其中 1 段有描述')
    expect(el.textContent).toContain('这些描述抽进知识库的那些记忆')
    // 摊开了还没删
    expect(calls).toEqual([])
    await click(byText(el, '确认删掉这一天')!)
    expect(calls).toEqual(['del-day 2026-09-19'])
    expect(toasts[0].text).toContain('连带 9 条记忆')
    vi.unstubAllGlobals()
  })

  it('删掉这一天：「先不删」就什么都不发生', async () => {
    const { el } = await mount(page())
    await click(byText(el, '删掉这一天')!)
    await click(byText(el, '先不删')!)
    expect(el.textContent).not.toContain('确认删掉这一天')
    expect(calls).toEqual([])
  })

  it('删一段：确认长在那一行下面，原话摆出来', async () => {
    const confirmSpy = vi.fn(() => true)
    vi.stubGlobal('confirm', confirmSpy)
    const { el } = await mount(page())
    // 时间轴上第一行的垃圾桶
    const del = el.querySelector('.journey-del') as HTMLElement
    expect(del).toBeTruthy()
    await click(del)
    expect(confirmSpy).not.toHaveBeenCalled()
    const box = el.querySelector('.journey-row-confirm')!
    expect(box.textContent).toContain('删掉这一段')
    expect(box.textContent).toContain('在改 journey.py')      // 原话，用来核对是哪一段
    expect(box.textContent).toContain('连它抽进知识库的记忆一起删')
    expect(calls).toEqual([])
    await click(byText(el, '确认删掉')!)
    expect(calls).toEqual(['del-seg 2026-09-19 0'])
    vi.unstubAllGlobals()
  })
})

describe('#6 去这天的日记', () => {
  it('把这一天递给外面那一层（找或建都在后端那一份）', async () => {
    const seen: string[] = []
    const { el } = await mount(page({ onOpenJournal: (d) => seen.push(d) }))
    await click(byText(el, '去这天的日记')!)
    expect(seen).toEqual(['2026-09-19'])
  })
})

describe('#7 ⌘K 的「这一周的屏幕活动」', () => {
  it('只打开并指出来，**不替用户开跑**', async () => {
    const opened: string[] = []
    window.addEventListener('open-virtual', (e) => opened.push((e as CustomEvent<string>).detail))
    openJourneySpan()
    expect(opened).toEqual(['app:journey'])
    const { el } = await mount(page())
    const hint = el.querySelector('.journey-span-hint')
    expect(hint?.textContent).toContain(`最近 ${JOURNEY_SPAN_DAYS} 天`)
    expect(hint?.textContent).toContain('一次模型调用')
    // 「最近 7 天」标成主钮，但没有一个请求发出去
    const btn = byText(el, `最近 ${JOURNEY_SPAN_DAYS} 天`)!
    expect(btn.className).toContain('primary')
    // 等一圈宏任务再看：「自己开跑」那种写法多半躲在 setTimeout / effect 里
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
    expect(calls).toEqual([])
    expect(el.textContent).not.toContain('停止')
  })

  it('取走只生效一次：再挂一次就不该还带着那条提示', async () => {
    openJourneySpan()
    const a = await mount(page())
    expect(a.el.querySelector('.journey-span-hint')).toBeTruthy()
    a.unmount()
    const b = await mount(page())
    expect(b.el.querySelector('.journey-span-hint')).toBeNull()
  })
})
