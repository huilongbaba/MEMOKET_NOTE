// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import * as api from '../../api'
import type { DecideSelection } from '../../desktop'
import CompanionDecide, { EMPTY_NOTE, NO_CHOICE_NOTE, NO_FACTS_NOTE, PERMISSION_NOTE, QUESTIONS_LEAD, type DecidePhase } from '../CompanionDecide'

vi.mock('../../api', () => ({ decide: vi.fn() }))

const roots: Root[] = []
const TEXT = '这批货报价比上次高了 8%，交期却提前了一周\n供应商说下周前要答复'
const selection = (patch: Partial<DecideSelection> = {}): DecideSelection => ({ text: TEXT, source: 'Safari', at: '2026-09-22T12:00:00', ...patch })
/** Nothing selected, an image on the clipboard: the main process ships a scaled PNG data URL and an empty text. */
const IMAGE = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
const DIGEST = '白板上两条路线：先做 iOS，或先做网页版\n下面写着 10 月上线'
const clipboardImage = (patch: Partial<DecideSelection> = {}): DecideSelection => selection({ text: '', image: IMAGE, origin: 'clipboard', ...patch })
const options = (patch: Partial<api.DecideOut> = {}): api.DecideOut => ({
  mode: 'options', frame: '这批货要不要压价', isDecision: 0.93, grounded: true, scorer: 'jev', model: 'jev-1.13.0', tookMs: 1200,
  items: [
    { id: 'a', label: '谈价', why: '上次报价还有余地', probability: 0.62, factIds: ['fact-000001'] },
    { id: 'b', label: '接受', why: '交期更要紧', probability: 0.28, factIds: [] },
    { id: 'c', label: '换供应商', why: '备选还没验过', probability: 0.1, factIds: [] },
  ],
  facts: [{ id: 'fact-000001', text: '上次谈价让了 5%', when: '2026-09-01' }],
  ...patch,
})
const questions = (): api.DecideOut => options({
  mode: 'questions', frame: '这段更像信息', isDecision: 0.2, grounded: false, facts: [],
  items: [
    { id: 'q1', label: '要不要接受这个报价', why: '你提到了价格', probability: 0.5, factIds: [] },
    { id: 'q2', label: '交期提前值不值得多花钱', why: '你提到了交期', probability: 0.35, factIds: [] },
    { id: 'q3', label: '什么时候答复', why: '有一个期限', probability: 0.15, factIds: [] },
  ],
})

type Text = Mock<(text: string) => void>
type Spies = { onInsert: Text; onTask: Text; onAskClaude: Text; onEscape: Mock<() => void>; onPhase: Mock<(phase: DecidePhase, count: number) => void> }
function spies(): Spies { return { onInsert: vi.fn(), onTask: vi.fn(), onAskClaude: vi.fn(), onEscape: vi.fn(), onPhase: vi.fn() } }
function panel(request: DecideSelection | null, s: Spies, active = true) {
  return <CompanionDecide request={request} active={active} onInsert={s.onInsert} onTask={s.onTask} onAskClaude={s.onAskClaude} onEscape={s.onEscape} onPhase={s.onPhase} />
}
async function mount(node: React.ReactNode) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  await act(async () => { root.render(node) })
  return { host, root }
}
async function key(el: Element, k: string, init: KeyboardEventInit = {}) {
  await act(async () => { el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...init })) })
}
async function click(host: HTMLElement, label: string) {
  const button = [...host.querySelectorAll<HTMLButtonElement>('button')].find((b) => (b.textContent || '').trim() === label || b.getAttribute('aria-label') === label)
  expect(button, `button ${label}`).toBeTruthy()
  await act(async () => { button!.click() })
}
async function typeContext(host: HTMLElement, text: string) {
  const input = host.querySelector<HTMLInputElement>('input[aria-label="补一句背景"]')!
  expect(input).toBeTruthy()
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, text)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  return input
}
const stage = (host: HTMLElement) => host.querySelector<HTMLElement>('.dc-decide')!
const cards = (host: HTMLElement) => [...host.querySelectorAll<HTMLElement>('.dc-decide-card')]
const labels = (host: HTMLElement) => cards(host).map((card) => card.querySelector('.dc-decide-label')?.textContent)
const highlighted = (host: HTMLElement) => cards(host).findIndex((card) => card.dataset.highlight === 'true')
const percents = (host: HTMLElement) => [...host.querySelectorAll('.dc-decide-pct')].map((node) => node.textContent)
/** A hand-cranked promise for `decide`, so a test decides when (and whether) each call answers. */
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-09-22T12:00:00'))
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.mocked(api.decide).mockReset()
  vi.mocked(api.decide).mockResolvedValue(options())
  Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn(async () => {}) }, configurable: true })
})
afterEach(async () => {
  await act(async () => { roots.splice(0).forEach((root) => root.unmount()) })
  document.body.innerHTML = ''
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('CompanionDecide', () => {
  it('asks the API for the selection and lays the candidates out with probabilities, fact chips and the scorer', async () => {
    const s = spies()
    const { host } = await mount(panel(selection(), s))
    expect(api.decide).toHaveBeenCalledExactlyOnceWith({ text: TEXT, source: 'Safari', mode: 'auto' }, expect.any(AbortSignal))
    expect(host.querySelector('.dc-decide-text')?.textContent).toBe(TEXT)
    expect(host.querySelector('.dc-decide-source')?.textContent).toBe('来自 Safari')
    expect(host.querySelector('.dc-decide-frame')?.textContent).toBe('这批货要不要压价')
    expect(labels(host)).toEqual(['谈价', '接受', '换供应商'])
    expect(percents(host)).toEqual(['62%', '28%', '10%'])
    expect(cards(host)[0].querySelector<HTMLElement>('.dc-decide-bar')?.style.getPropertyValue('--dc-p')).toBe('0.62')
    expect(host.querySelector('.dc-decide-scorer')?.textContent).toBe('Jev')
    expect(highlighted(host)).toBe(0)
    expect(host.querySelector('.dc-decide-actions')).toBeNull()
    expect(host.querySelector('.dc-decide-progress')).toBeNull()
    expect(host.textContent).not.toContain(NO_FACTS_NOTE)
    // The cited fact shows as a chip: short id, full text on hover, one click copies the citation marker.
    const chip = cards(host)[0].querySelector<HTMLButtonElement>('.dc-decide-fact')!
    expect(chip.textContent).toBe('[1]')
    expect(chip.title).toBe('上次谈价让了 5%')
    await act(async () => { chip.click() })
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('[fact-000001]')
    expect(host.querySelector('.dc-decide-note[role="status"]')?.textContent).toBe('已复制引用 [fact-000001]')
    expect(s.onPhase.mock.calls).toEqual([['thinking', 0], ['ready', 3, 'options']])
    expect(s.onInsert).not.toHaveBeenCalled()
    expect(s.onTask).not.toHaveBeenCalled()
    expect(s.onAskClaude).not.toHaveBeenCalled()
  })

  it('shows the quote and a progress line while thinking, and only then the cards', async () => {
    const pending = deferred<api.DecideOut>()
    vi.mocked(api.decide).mockReturnValueOnce(pending.promise)
    const s = spies()
    const { host } = await mount(panel(selection(), s))
    expect(host.querySelector('.dc-decide-text')?.textContent).toBe(TEXT)
    expect(host.querySelector('.dc-decide-progress')).toBeTruthy()
    expect(cards(host)).toHaveLength(0)
    expect(host.querySelector('input[aria-label="补一句背景"]')).toBeNull()
    expect(s.onPhase).toHaveBeenLastCalledWith('thinking', 0)
    await act(async () => { pending.resolve(options()) })
    expect(host.querySelector('.dc-decide-progress')).toBeNull()
    expect(cards(host)).toHaveLength(3)
    expect(host.querySelector('input[aria-label="补一句背景"]')).toBeTruthy()
    expect(s.onPhase).toHaveBeenLastCalledWith('ready', 3, 'options')
  })

  it('moves the highlight with the arrows, opens the action row on Enter and hands Escape to the island', async () => {
    const s = spies()
    const { host } = await mount(panel(selection(), s))
    await key(stage(host), 'ArrowDown')
    expect(highlighted(host)).toBe(1)
    expect(document.activeElement).toBe(cards(host)[1].querySelector('.dc-decide-pick'))
    await key(stage(host), 'ArrowDown')
    await key(stage(host), 'ArrowDown')
    expect(highlighted(host)).toBe(0)
    await key(stage(host), 'ArrowUp')
    expect(highlighted(host)).toBe(2)
    expect(host.querySelector('.dc-decide-actions')).toBeNull()
    await key(stage(host), 'Enter')
    const actions = cards(host)[2].querySelector('.dc-decide-actions')!
    expect(actions).toBeTruthy()
    expect([...actions.querySelectorAll('button')].map((b) => b.textContent)).toEqual(['记下来', '变成待办', '问 Claude 展开', '复制'])
    expect(document.activeElement).toBe(actions.querySelector('button'))
    expect(cards(host)[2].querySelector('.dc-decide-pick')?.getAttribute('aria-expanded')).toBe('true')
    // Moving on folds the row again; nothing was acted on.
    await key(stage(host), 'ArrowDown')
    expect(host.querySelector('.dc-decide-actions')).toBeNull()
    expect(s.onInsert).not.toHaveBeenCalled()
    expect(s.onEscape).not.toHaveBeenCalled()
    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    await act(async () => { stage(host).dispatchEvent(escape) })
    expect(s.onEscape).toHaveBeenCalledTimes(1)
    expect(escape.defaultPrevented).toBe(true)
    expect(api.decide).toHaveBeenCalledTimes(1)
  })

  it('gives each action the text it needs, and never acts on its own', async () => {
    const s = spies()
    const { host } = await mount(panel(selection(), s))
    await act(async () => { cards(host)[0].querySelector<HTMLButtonElement>('.dc-decide-pick')!.click() })
    expect(cards(host)[0].querySelector('.dc-decide-actions')).toBeTruthy()
    await click(host, '记下来')
    expect(s.onInsert).toHaveBeenCalledExactlyOnceWith('> 这批货报价比上次高了 8%，交期却提前了一周…\n\n**决定：** 谈价\n上次报价还有余地 [fact-000001]')
    await click(host, '变成待办')
    expect(s.onTask).toHaveBeenCalledExactlyOnceWith('谈价')
    await click(host, '问 Claude 展开')
    const asked = s.onAskClaude.mock.calls[0][0] as string
    expect(asked).toContain('这批货要不要压价')
    expect(asked).toContain('> 这批货报价比上次高了 8%，交期却提前了一周')
    expect(asked).toContain('1. 谈价（62%） — 上次报价还有余地')
    expect(asked).toContain('2. 接受（28%） — 交期更要紧')
    expect(asked).toContain('3. 换供应商（10%） — 备选还没验过')
    expect(asked).toContain('「谈价」')
    await click(host, '复制')
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('谈价\n上次报价还有余地')
    expect(host.querySelector('.dc-decide-note[role="status"]')?.textContent).toBe('已复制')
    await act(async () => { await vi.advanceTimersByTimeAsync(2100) })
    expect(host.querySelector('.dc-decide-note[role="status"]')).toBeNull()
    // Clicking the open card again folds the row.
    await act(async () => { cards(host)[0].querySelector<HTMLButtonElement>('.dc-decide-pick')!.click() })
    expect(host.querySelector('.dc-decide-actions')).toBeNull()
    expect(api.decide).toHaveBeenCalledTimes(1)
  })

  it('turns information into questions, and choosing one re-runs in options mode with that question', async () => {
    vi.mocked(api.decide).mockResolvedValueOnce(questions())
    const s = spies()
    const { host } = await mount(panel(selection(), s))
    expect(host.querySelector('.dc-decide-frame')?.textContent).toBe(QUESTIONS_LEAD)
    expect(host.querySelector('.dc-decide-list')?.getAttribute('aria-label')).toBe('你可能想问的')
    expect(labels(host)).toEqual(['要不要接受这个报价', '交期提前值不值得多花钱', '什么时候答复'])
    expect(percents(host)).toEqual(['50%', '35%', '15%'])
    expect(host.querySelector('.dc-decide-bar')).toBeNull()
    expect(host.textContent).toContain(NO_FACTS_NOTE)
    // Enter on a question row does not open an action row: it asks that question.
    await key(stage(host), 'ArrowDown')
    await key(stage(host), 'Enter')
    expect(host.querySelector('.dc-decide-actions')).toBeNull()
    expect(api.decide).toHaveBeenLastCalledWith({ text: TEXT, source: 'Safari', question: '交期提前值不值得多花钱', mode: 'options' }, expect.any(AbortSignal))
    expect(host.querySelector('.dc-decide-frame')?.textContent).toBe('这批货要不要压价')
    expect(labels(host)).toEqual(['谈价', '接受', '换供应商'])
    expect(s.onPhase.mock.calls).toEqual([['thinking', 0], ['ready', 3, 'questions'], ['thinking', 0], ['ready', 3, 'options']])
  })

  it('re-runs with a sentence of background, keeping the chosen question; Escape clears the field before leaving', async () => {
    vi.mocked(api.decide).mockResolvedValueOnce(questions())
    const s = spies()
    const { host } = await mount(panel(selection(), s))
    await act(async () => { cards(host)[0].querySelector<HTMLButtonElement>('.dc-decide-pick')!.click() })
    expect(api.decide).toHaveBeenCalledTimes(2)
    const input = await typeContext(host, '预算只有两万')
    await key(input, 'Enter')
    expect(api.decide).toHaveBeenCalledTimes(3)
    expect(api.decide).toHaveBeenLastCalledWith({ text: TEXT, source: 'Safari', question: '要不要接受这个报价', mode: 'options', context: '预算只有两万' }, expect.any(AbortSignal))
    expect(host.querySelector('.dc-decide-list')?.getAttribute('aria-busy')).toBe('false')
    // While a re-run thinks, the previous cards stay (marked busy, no skeleton) instead of vanishing.
    const pendingRerun = deferred<api.DecideOut>()
    vi.mocked(api.decide).mockReturnValueOnce(pendingRerun.promise)
    await typeContext(host, '再补一句')
    await key(input, 'Enter')
    expect(host.querySelector('.dc-decide-list')?.getAttribute('aria-busy')).toBe('true')
    expect(cards(host)).toHaveLength(3)
    expect(host.querySelector('.dc-decide-skeleton')).toBeNull()
    expect(host.querySelector('.dc-decide-progress')).toBeTruthy()
    await act(async () => { pendingRerun.resolve(options()) })
    expect(host.querySelector('.dc-decide-list')?.getAttribute('aria-busy')).toBe('false')
    await typeContext(host, '还有一句')
    await key(input, 'Escape')
    expect(input.value).toBe('')
    expect(s.onEscape).not.toHaveBeenCalled()
    await key(input, 'Escape')
    expect(s.onEscape).toHaveBeenCalledTimes(1)
    // An empty field never re-runs.
    await key(input, 'Enter')
    expect(api.decide).toHaveBeenCalledTimes(4)
  })

  it('hides every number when there is no scorer, and labels a model estimate honestly', async () => {
    vi.mocked(api.decide).mockResolvedValueOnce(options({ scorer: 'none', grounded: false, facts: [], items: options().items.map((item) => ({ ...item, probability: 0, factIds: [] })) }))
    const s = spies()
    const { host, root } = await mount(panel(selection(), s))
    expect(labels(host)).toEqual(['谈价', '接受', '换供应商'])
    expect(host.querySelector('.dc-decide-pct')).toBeNull()
    expect(host.querySelector('.dc-decide-bar')).toBeNull()
    expect(host.querySelector('.dc-decide-scorer')).toBeNull()
    expect(host.querySelector('.dc-decide-fact')).toBeNull()
    expect(host.textContent).toContain(NO_FACTS_NOTE)
    vi.mocked(api.decide).mockResolvedValueOnce(options({ scorer: 'model', model: 'test-gemini' }))
    await act(async () => { root.render(panel(selection({ at: '2026-09-22T12:01:00' }), s)) })
    expect(host.querySelector('.dc-decide-scorer')?.textContent).toBe('模型估计')
    expect(percents(host)).toEqual(['62%', '28%', '10%'])
    vi.mocked(api.decide).mockResolvedValueOnce(options({ items: [] }))
    await act(async () => { root.render(panel(selection({ at: '2026-09-22T12:02:00' }), s)) })
    expect(host.textContent).toContain(NO_CHOICE_NOTE)
    expect(cards(host)).toHaveLength(0)
    expect(s.onPhase).toHaveBeenLastCalledWith('ready', 0, 'options')
  })

  it('takes an image from the clipboard: the thumbnail at once, the digest once Gemini has read it, and every action quotes the digest', async () => {
    const pending = deferred<api.DecideOut>()
    vi.mocked(api.decide).mockReturnValueOnce(pending.promise)
    const s = spies()
    const { host } = await mount(panel(clipboardImage(), s))
    // An empty text with an image is a real request, not an empty one.
    expect(api.decide).toHaveBeenCalledExactlyOnceWith({ text: '', image: IMAGE, source: 'Safari', mode: 'auto' }, expect.any(AbortSignal))
    expect(host.textContent).not.toContain(EMPTY_NOTE)
    const img = host.querySelector<HTMLImageElement>('.dc-decide-quote .dc-decide-image')!
    expect(img.getAttribute('src')).toBe(IMAGE)
    expect(img.alt).toBe('剪贴板里的图片')
    expect(host.querySelector('.dc-decide-text')).toBeNull()
    // While thinking the digest is unknown: nothing is written under the image.
    expect(host.querySelector('.dc-decide-digest')).toBeNull()
    expect(host.querySelector('.dc-decide-source')?.textContent).toBe('来自剪贴板 · Safari')
    expect(host.querySelector('.dc-decide-progress')).toBeTruthy()
    expect(s.onPhase).toHaveBeenLastCalledWith('thinking', 0)
    await act(async () => { pending.resolve(options({ digest: DIGEST, frame: '先做哪个端' })) })
    expect(host.querySelector('.dc-decide-image')).toBeTruthy()
    expect(host.querySelector('.dc-decide-digest')?.textContent).toBe(`图里说的是${DIGEST}`)
    expect(host.querySelector('.dc-decide-digest-lead')?.textContent).toBe('图里说的是')
    expect(host.querySelector('.dc-decide-frame')?.textContent).toBe('先做哪个端')
    expect(labels(host)).toEqual(['谈价', '接受', '换供应商'])
    expect(s.onPhase.mock.calls).toEqual([['thinking', 0], ['ready', 3, 'options']])
    // The note quotes the first line of the digest; the ask text says where the "original" came from.
    await act(async () => { cards(host)[0].querySelector<HTMLButtonElement>('.dc-decide-pick')!.click() })
    await click(host, '记下来')
    expect(s.onInsert).toHaveBeenCalledExactlyOnceWith('> 白板上两条路线：先做 iOS，或先做网页版…\n\n**决定：** 谈价\n上次报价还有余地 [fact-000001]')
    await click(host, '问 Claude 展开')
    const asked = s.onAskClaude.mock.calls[0][0] as string
    expect(asked).toContain('原文（剪贴板图片，Gemini 读出）：\n> 白板上两条路线：先做 iOS，或先做网页版\n> 下面写着 10 月上线')
    expect(asked).not.toContain('来自 Safari')
    expect(asked).toContain('先做哪个端')
    expect(asked).toContain('1. 谈价（62%） — 上次报价还有余地')
    // A sentence of background re-runs with the same image; the old digest stays until the new one lands.
    const rerun = deferred<api.DecideOut>()
    vi.mocked(api.decide).mockReturnValueOnce(rerun.promise)
    const input = await typeContext(host, '团队只有两个前端')
    await key(input, 'Enter')
    expect(api.decide).toHaveBeenLastCalledWith({ text: '', image: IMAGE, source: 'Safari', mode: 'auto', context: '团队只有两个前端' }, expect.any(AbortSignal))
    expect(host.querySelector('.dc-decide-digest')?.textContent).toBe(`图里说的是${DIGEST}`)
    await act(async () => { rerun.resolve(options({ digest: '白板上只剩一条路线：先做网页版' })) })
    expect(host.querySelector('.dc-decide-digest')?.textContent).toBe('图里说的是白板上只剩一条路线：先做网页版')
    expect(api.decide).toHaveBeenCalledTimes(2)
  })

  it('reads an image as questions first, and asking one keeps the image on the re-run', async () => {
    vi.mocked(api.decide).mockResolvedValueOnce(questions()).mockResolvedValueOnce(options({ digest: DIGEST }))
    const s = spies()
    const { host } = await mount(panel(clipboardImage({ source: '' }), s))
    expect(api.decide).toHaveBeenCalledExactlyOnceWith({ text: '', image: IMAGE, mode: 'auto' }, expect.any(AbortSignal))
    // No front app worth naming: the source line is just the clipboard.
    expect(host.querySelector('.dc-decide-source')?.textContent).toBe('来自剪贴板')
    expect(host.querySelector('.dc-decide-frame')?.textContent).toBe(QUESTIONS_LEAD)
    // A questions answer without a digest writes nothing under the image rather than inventing one.
    expect(host.querySelector('.dc-decide-digest')).toBeNull()
    await key(stage(host), 'Enter')
    expect(api.decide).toHaveBeenLastCalledWith({ text: '', image: IMAGE, question: '要不要接受这个报价', mode: 'options' }, expect.any(AbortSignal))
    expect(labels(host)).toEqual(['谈价', '接受', '换供应商'])
    expect(host.querySelector('.dc-decide-digest')?.textContent).toBe(`图里说的是${DIGEST}`)
    expect(host.querySelector('.dc-decide-image')?.getAttribute('src')).toBe(IMAGE)
  })

  it('labels clipboard text as such and runs it through the same pipeline, ignoring any digest', async () => {
    vi.mocked(api.decide).mockResolvedValueOnce(options({ digest: '文字请求不该显示这句' }))
    const s = spies()
    const { host, root } = await mount(panel(selection({ origin: 'clipboard' }), s))
    expect(api.decide).toHaveBeenCalledExactlyOnceWith({ text: TEXT, source: 'Safari', mode: 'auto' }, expect.any(AbortSignal))
    expect(host.querySelector('.dc-decide-text')?.textContent).toBe(TEXT)
    expect(host.querySelector('.dc-decide-image')).toBeNull()
    expect(host.querySelector('.dc-decide-digest')).toBeNull()
    expect(host.querySelector('.dc-decide-source')?.textContent).toBe('来自剪贴板 · Safari')
    expect(labels(host)).toEqual(['谈价', '接受', '换供应商'])
    await act(async () => { cards(host)[0].querySelector<HTMLButtonElement>('.dc-decide-pick')!.click() })
    await click(host, '记下来')
    expect(s.onInsert).toHaveBeenCalledExactlyOnceWith('> 这批货报价比上次高了 8%，交期却提前了一周…\n\n**决定：** 谈价\n上次报价还有余地 [fact-000001]')
    await click(host, '问 Claude 展开')
    expect(s.onAskClaude.mock.calls[0][0]).toContain('原文（来自剪贴板 · Safari）：\n> 这批货报价比上次高了 8%，交期却提前了一周')
    // Without a front app name the line is just 来自剪贴板; a selection still names the app.
    await act(async () => { root.render(panel(selection({ origin: 'clipboard', source: '', at: '2026-09-22T12:01:00' }), s)) })
    expect(host.querySelector('.dc-decide-source')?.textContent).toBe('来自剪贴板')
    await act(async () => { root.render(panel(selection({ origin: 'selection', at: '2026-09-22T12:02:00' }), s)) })
    expect(host.querySelector('.dc-decide-source')?.textContent).toBe('来自 Safari')
  })

  it('explains a missing permission or an empty selection without calling the API', async () => {
    // The empty note now mentions the clipboard: a copied text or image is enough.
    expect(EMPTY_NOTE).toBe('先选中一段文字，或先复制一段文字 / 一张图片，再按 ⌥D')
    const s = spies()
    const { host, root } = await mount(panel(selection({ text: '', error: 'accessibility' }), s))
    expect(host.textContent).toContain(PERMISSION_NOTE)
    expect(host.querySelector('.dc-decide-quote')).toBeNull()
    expect(api.decide).not.toHaveBeenCalled()
    expect(s.onPhase.mock.calls).toEqual([['idle', 0]])
    // 'empty' now means nothing selected AND nothing usable on the clipboard.
    await act(async () => { root.render(panel(selection({ text: '', error: 'empty', origin: 'clipboard', at: '2026-09-22T12:01:00' }), s)) })
    expect(host.textContent).toContain(EMPTY_NOTE)
    expect(host.textContent).not.toContain(PERMISSION_NOTE)
    expect(host.querySelector('.dc-decide-image')).toBeNull()
    await act(async () => { root.render(panel(selection({ text: '   \n ', at: '2026-09-22T12:02:00' }), s)) })
    expect(host.textContent).toContain(EMPTY_NOTE)
    expect(api.decide).not.toHaveBeenCalled()
    expect(host.querySelector('input[aria-label="补一句背景"]')).toBeNull()
    // A real selection after that clears the note and runs.
    await act(async () => { root.render(panel(selection({ at: '2026-09-22T12:03:00' }), s)) })
    expect(host.textContent).not.toContain(EMPTY_NOTE)
    expect(api.decide).toHaveBeenCalledTimes(1)
    expect(cards(host)).toHaveLength(3)
  })

  it('aborts a superseded request and ignores its late answer', async () => {
    const first = deferred<api.DecideOut>()
    const second = deferred<api.DecideOut>()
    vi.mocked(api.decide).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const s = spies()
    const { host, root } = await mount(panel(selection({ text: '第一段' }), s))
    const firstSignal = vi.mocked(api.decide).mock.calls[0][1]!
    expect(firstSignal.aborted).toBe(false)
    await act(async () => { root.render(panel(selection({ text: '第二段', at: '2026-09-22T12:01:00' }), s)) })
    expect(firstSignal.aborted).toBe(true)
    expect(host.querySelector('.dc-decide-text')?.textContent).toBe('第二段')
    await act(async () => { second.resolve(options({ frame: '第二段的题' })) })
    expect(host.querySelector('.dc-decide-frame')?.textContent).toBe('第二段的题')
    await act(async () => { first.resolve(options({ frame: '第一段的题', items: [{ id: 'z', label: '过期的候选', why: '', probability: 1, factIds: [] }] })) })
    expect(host.querySelector('.dc-decide-frame')?.textContent).toBe('第二段的题')
    expect(labels(host)).toEqual(['谈价', '接受', '换供应商'])
    expect(s.onPhase.mock.calls).toEqual([['thinking', 0], ['thinking', 0], ['ready', 3, 'options']])
    // A rejection from the aborted call is ignored too.
    const third = deferred<api.DecideOut>()
    const fourth = deferred<api.DecideOut>()
    vi.mocked(api.decide).mockReturnValueOnce(third.promise).mockReturnValueOnce(fourth.promise)
    await act(async () => { root.render(panel(selection({ text: '第三段', at: '2026-09-22T12:02:00' }), s)) })
    await act(async () => { root.render(panel(selection({ text: '第四段', at: '2026-09-22T12:03:00' }), s)) })
    await act(async () => { third.reject(new DOMException('The user aborted a request.', 'AbortError')) })
    expect(host.querySelector('[role="alert"]')).toBeNull()
    expect(host.querySelector('.dc-decide-progress')).toBeTruthy()
    await act(async () => { fourth.resolve(options()) })
    expect(host.querySelector('.dc-decide-progress')).toBeNull()
  })

  it('shows the failure with a retry that repeats the same request, and reports the phases', async () => {
    vi.mocked(api.decide).mockRejectedValueOnce(new Error('529 Jev 正忙，请稍后重试'))
    const s = spies()
    const { host, root } = await mount(panel(selection(), s))
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('529 Jev 正忙，请稍后重试')
    expect(cards(host)).toHaveLength(0)
    expect(s.onPhase.mock.calls).toEqual([['thinking', 0], ['error', 0]])
    await click(host, '重试')
    expect(api.decide).toHaveBeenCalledTimes(2)
    expect(api.decide).toHaveBeenLastCalledWith({ text: TEXT, source: 'Safari', mode: 'auto' }, expect.any(AbortSignal))
    expect(host.querySelector('[role="alert"]')).toBeNull()
    expect(cards(host)).toHaveLength(3)
    expect(s.onPhase.mock.calls).toEqual([['thinking', 0], ['error', 0], ['thinking', 0], ['ready', 3, 'options']])
    vi.mocked(api.decide).mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await act(async () => { root.render(panel(selection({ at: '2026-09-22T12:01:00' }), s)) })
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('笔记服务暂时不可用')
    await act(async () => { root.unmount(); roots.splice(roots.indexOf(root), 1) })
    expect(s.onPhase).toHaveBeenLastCalledWith('idle', 0)
  })
})
