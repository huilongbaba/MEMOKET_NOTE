// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AgentBridge, AgentMessage, AgentSession, AgentStatus, AgentTurnEvent } from '../../desktop'
import CompanionSession, { ATTACH_ONLY_PROMPT, LOGIN_HINT, LOGIN_NOTE, LOGIN_TITLE, MISSING_TITLE, WEB_ONLY_NOTE, type CompanionSessionHandle } from '../CompanionSession'

const roots: Root[] = []
const CWD = '/Users/kailun/Library/Application Support/MEMOKET/companion/agent'
const okStatus = (patch: Partial<AgentStatus> = {}): AgentStatus => ({ available: true, loggedIn: true, version: '2.1.278', reason: '', cwd: CWD, models: [{ id: 'opus', label: 'Opus' }, { id: 'sonnet', label: 'Sonnet' }], runningTurnId: null, ...patch })
const session = (id: string, title: string, updatedAt = '2026-09-22T09:30:00'): AgentSession => ({ id, title, model: '', createdAt: updatedAt, updatedAt, turns: 2 })
const reply = (id: string, text: string, patch: Partial<AgentMessage> = {}): AgentMessage => ({ id, role: 'assistant', text, at: '2026-09-22T09:30:00', ...patch })

/** A bridge whose every method is a spy, plus a hand-cranked emitter for `agent:event`. */
function fakeBridge(status: AgentStatus = okStatus(), sessions: AgentSession[] = [], transcript: AgentMessage[] = []) {
  const listeners = new Set<(event: AgentTurnEvent) => void>()
  const bridge: AgentBridge = {
    status: vi.fn(async () => status),
    sessions: vi.fn(async () => sessions),
    transcript: vi.fn(async () => transcript),
    send: vi.fn(async () => ({ ok: true, turnId: 'turn-1', sessionId: null })),
    interrupt: vi.fn(async () => ({ ok: true })),
    attach: vi.fn(async (files: File[]) => ({ ok: true, attachments: files.map((file) => ({ path: `${CWD}/workspace/附件/${file.name}`, name: file.name, action: 'attach' as const })) })),
    shelve: vi.fn(async () => ({ ok: true, state: { surface: 'top' as const, expanded: true, panel: 'agent' as const, items: [], storageError: '' } })),
    onEvent: vi.fn((callback: (event: AgentTurnEvent) => void) => { listeners.add(callback); return () => { listeners.delete(callback) } }),
  }
  const emit = async (event: AgentTurnEvent) => { await act(async () => { listeners.forEach((listener) => listener(event)) }) }
  return { bridge, emit, listeners }
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-09-22T12:00:00'))
  localStorage.clear()
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
})
afterEach(async () => {
  await act(async () => { roots.splice(0).forEach((root) => root.unmount()) })
  document.body.innerHTML = ''
  vi.restoreAllMocks()
  vi.useRealTimers()
})

type PanelProps = Partial<Parameters<typeof CompanionSession>[0]> & { bridge: AgentBridge | undefined }
function Panel({ bridge, active = true, focusRequested = 0, onEscape = () => {}, onInsert = () => {}, onSaveNote = async () => true, onRunningChange = () => {}, handleRef }: PanelProps) {
  return <CompanionSession bridge={bridge} active={active} focusRequested={focusRequested} onEscape={onEscape} onInsert={onInsert} onSaveNote={onSaveNote} onRunningChange={onRunningChange} handleRef={handleRef} />
}

async function mount(node: React.ReactNode) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  await act(async () => { root.render(node) })
  return { host, root }
}
async function tick(ms: number) { await act(async () => { await vi.advanceTimersByTimeAsync(ms) }) }
async function click(host: HTMLElement, label: string) {
  const button = [...host.querySelectorAll<HTMLButtonElement>('button')].find((b) => (b.getAttribute('aria-label') || b.textContent) === label)
  expect(button, `button ${label}`).toBeTruthy()
  await act(async () => { button!.click() })
}
const field = (host: HTMLElement) => host.querySelector<HTMLTextAreaElement>('textarea[aria-label="问 Claude"]')!
async function type(host: HTMLElement, text: string) {
  const el = field(host)
  const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!
  await act(async () => { set.call(el, text); el.dispatchEvent(new Event('input', { bubbles: true })) })
}
async function key(el: Element, k: string, init: KeyboardEventInit = {}) {
  await act(async () => { el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...init })) })
}
async function pickModel(host: HTMLElement, value: string) {
  const select = host.querySelector<HTMLSelectElement>('select[aria-label="模型"]')!
  await act(async () => { select.value = value; select.dispatchEvent(new Event('change', { bubbles: true })) })
}
const capsules = (host: HTMLElement) => [...host.querySelectorAll('.dc-turn-capsule')].map((n) => n.textContent)
const replies = (host: HTMLElement) => [...host.querySelectorAll('.dc-turn-assistant:not(.dc-turn-live) .dc-turn-text')].map((n) => n.textContent)
const live = (host: HTMLElement) => host.querySelector('.dc-turn-live')

describe('CompanionSession', () => {
  it('says so quietly when there is no bridge at all', async () => {
    const { host } = await mount(<Panel bridge={undefined} />)
    expect(host.querySelector('.dc-session-web')?.textContent).toBe(WEB_ONLY_NOTE)
    expect(field(host)).toBeNull()
  })

  it('shows the missing-CLI block with the bridge’s reason and re-reads status on 重试', async () => {
    const { bridge } = fakeBridge(okStatus({ available: false, reason: 'PATH 里没有 claude，装好后重试。', models: [] }))
    const { host } = await mount(<Panel bridge={bridge} />)
    await tick(0)
    expect(host.querySelector('.dc-session-state-title')?.textContent).toBe(MISSING_TITLE)
    expect(host.querySelector('.dc-session-state-note')?.textContent).toBe('PATH 里没有 claude，装好后重试。')
    expect(field(host)).toBeNull()
    vi.mocked(bridge.status).mockResolvedValueOnce(okStatus())
    await click(host, '重试')
    await tick(0)
    expect(bridge.status).toHaveBeenCalledTimes(2)
    expect(host.querySelector('.dc-session-state')).toBeNull()
    expect(host.querySelector('.dc-session-empty-title')?.textContent).toBe('和 Claude 直接对话')
  })

  it('opens on the empty state with the working directory, the model list and the remembered choice', async () => {
    localStorage.setItem('memoket.companion.agent.model', 'sonnet')
    const { bridge } = fakeBridge()
    const { host } = await mount(<Panel bridge={bridge} />)
    await tick(0)
    expect(bridge.onEvent).toHaveBeenCalledTimes(1)
    expect(bridge.sessions).toHaveBeenCalledTimes(1)
    expect(host.querySelector('.dc-session-empty')?.textContent).toContain('回复可以一键进笔记，产出的文件可以放进暂存箱。')
    expect(host.querySelector('.dc-session-cwd')?.textContent).toBe('工作目录 · agent')
    expect(host.querySelector('.dc-session-title')?.textContent).toBe('新会话')
    const select = host.querySelector<HTMLSelectElement>('select[aria-label="模型"]')!
    expect([...select.options].map((o) => [o.value, o.textContent])).toEqual([['', '默认'], ['opus', 'Opus'], ['sonnet', 'Sonnet']])
    expect(select.value).toBe('sonnet')
    expect(host.querySelector<HTMLButtonElement>('button[aria-label="发送"]')?.disabled).toBe(true)
    // Hover-expansion must not steal focus: nothing is focused until the island asks.
    expect(document.activeElement).toBe(document.body)
  })

  it('sends on Enter, streams the reply, lists a produced file and finalizes on turn-end', async () => {
    const { bridge, emit } = fakeBridge()
    const onRunningChange = vi.fn()
    const { host } = await mount(<Panel bridge={bridge} onRunningChange={onRunningChange} />)
    await tick(0)
    await pickModel(host, 'opus')
    expect(localStorage.getItem('memoket.companion.agent.model')).toBe('opus')
    await type(host, '写一段关于交期的说明')
    expect(host.querySelector<HTMLButtonElement>('button[aria-label="发送"]')?.disabled).toBe(false)
    await key(field(host), 'Enter', { shiftKey: true })
    expect(bridge.send).not.toHaveBeenCalled()
    await key(field(host), 'Enter')
    expect(bridge.send).toHaveBeenCalledExactlyOnceWith({ sessionId: null, text: '写一段关于交期的说明', model: 'opus' })
    expect(field(host).value).toBe('')
    expect(capsules(host)).toEqual(['写一段关于交期的说明'])
    expect(onRunningChange).toHaveBeenLastCalledWith(true)
    expect(host.querySelector('button[aria-label="停止"]')).toBeTruthy()
    expect(host.querySelector('.dc-session-empty')).toBeNull()
    await emit({ type: 'turn-start', turnId: 'turn-1', sessionId: null, model: 'opus' })
    await emit({ type: 'session', turnId: 'turn-1', sessionId: 'sess-1', model: 'claude-opus-4-1' })
    expect(bridge.sessions).toHaveBeenCalledTimes(2)
    await emit({ type: 'delta', turnId: 'turn-1', text: '交期改到' })
    await emit({ type: 'delta', turnId: 'other-turn', text: '不是这一轮的' })
    await emit({ type: 'delta', turnId: 'turn-1', text: '十月中旬。' })
    expect(live(host)?.querySelector('.dc-turn-text')?.textContent).toBe('交期改到十月中旬。')
    expect(live(host)?.querySelector('.dc-turn-activity')?.textContent).toBe('正在思考')
    await emit({ type: 'activity', turnId: 'turn-1', tool: 'Write', path: `${CWD}/交期说明.md`, label: '正在写 交期说明.md' })
    expect(live(host)?.querySelector('.dc-turn-activity')?.textContent).toBe('正在写 交期说明.md')
    expect(live(host)?.querySelector('.dc-turn-dot')).toBeTruthy()
    await emit({ type: 'artifact', turnId: 'turn-1', artifact: { path: `${CWD}/交期说明.md`, name: '交期说明.md', action: 'write' } })
    expect(live(host)?.querySelector('.dc-turn-file-name')?.textContent).toBe('交期说明.md')
    expect(replies(host)).toEqual([])
    const final = reply('m-2', '交期改到十月中旬。', { artifacts: [{ path: `${CWD}/交期说明.md`, name: '交期说明.md', action: 'write' }], costUsd: 0.01 })
    await emit({ type: 'turn-end', turnId: 'turn-1', sessionId: 'sess-1', message: final })
    expect(live(host)).toBeNull()
    expect(replies(host)).toEqual(['交期改到十月中旬。'])
    expect(host.textContent).not.toContain('0.01')
    expect(onRunningChange).toHaveBeenLastCalledWith(false)
    expect(host.querySelector('button[aria-label="发送"]')).toBeTruthy()
    // The next question continues the same session.
    await type(host, '再短一点')
    await key(field(host), 'Enter')
    expect(bridge.send).toHaveBeenLastCalledWith({ sessionId: 'sess-1', text: '再短一点', model: 'opus' })
    // A produced file goes to the shelf by path, and the row says so afterwards.
    await click(host, '放入暂存箱')
    expect(bridge.shelve).toHaveBeenCalledExactlyOnceWith([`${CWD}/交期说明.md`])
    expect(host.querySelector('.dc-turn-file-state')?.textContent).toBe('已放入')
    expect([...host.querySelectorAll('button')].some((b) => b.textContent === '放入暂存箱')).toBe(false)
  })

  it('keeps the shelf failure on the file row and lets the user try again', async () => {
    const { bridge, emit } = fakeBridge()
    vi.mocked(bridge.shelve).mockResolvedValueOnce({ ok: false, error: '暂存箱正在处理上一项。', state: { surface: 'top', expanded: true, panel: 'agent', items: [], storageError: '' } })
    const { host } = await mount(<Panel bridge={bridge} />)
    await tick(0)
    await type(host, '写文件')
    await key(field(host), 'Enter')
    await emit({ type: 'turn-end', turnId: 'turn-1', sessionId: 's', message: reply('m', '写好了。', { artifacts: [{ path: '/a/b.md', name: 'b.md', action: 'write' }] }) })
    await click(host, '放入暂存箱')
    expect(host.querySelector('.dc-turn-file-error')?.textContent).toBe('暂存箱正在处理上一项。')
    expect(host.querySelector('.dc-turn-file-state')).toBeNull()
    await click(host, '放入暂存箱')
    expect(bridge.shelve).toHaveBeenCalledTimes(2)
    expect(host.querySelector('.dc-turn-file-error')).toBeNull()
    expect(host.querySelector('.dc-turn-file-state')?.textContent).toBe('已放入')
  })

  it('offers 引用到笔记 / 存为笔记 / 复制 under a reply and reports each briefly', async () => {
    const { bridge } = fakeBridge(okStatus(), [session('sess-1', '交期说明')], [{ id: 'u1', role: 'user', text: '交期？', at: '2026-09-22T09:29:00' }, reply('m1', '十月中旬。')])
    const onInsert = vi.fn()
    const onSaveNote = vi.fn(async () => true)
    const writeText = vi.fn(() => Promise.resolve())
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    const { host } = await mount(<Panel bridge={bridge} onInsert={onInsert} onSaveNote={onSaveNote} />)
    await tick(0)
    await click(host, '最近会话')
    const menu = host.querySelector('[role="menu"][aria-label="最近会话"]')!
    expect(menu).toBeTruthy()
    expect(bridge.sessions).toHaveBeenCalledTimes(2)
    expect(menu.querySelector('.dc-session-recent-title')?.textContent).toBe('交期说明')
    expect(menu.querySelector('.dc-session-recent-date')?.textContent).toBe('9:30')
    await act(async () => { menu.querySelector<HTMLButtonElement>('[role="menuitem"]')!.click() })
    expect(bridge.transcript).toHaveBeenCalledExactlyOnceWith('sess-1')
    expect(host.querySelector('[role="menu"]')).toBeNull()
    expect(host.querySelector('.dc-session-title')?.textContent).toBe('交期说明')
    expect(capsules(host)).toEqual(['交期？'])
    expect(replies(host)).toEqual(['十月中旬。'])
    await click(host, '引用到笔记')
    expect(onInsert).toHaveBeenCalledExactlyOnceWith('十月中旬。')
    await click(host, '存为笔记')
    expect(onSaveNote).toHaveBeenCalledExactlyOnceWith('十月中旬。')
    expect(host.querySelector('.dc-turn-note')?.textContent).toBe('已存为笔记')
    await tick(3000)
    expect(host.querySelector('.dc-turn-note')).toBeNull()
    await click(host, '复制')
    await tick(0)
    expect(writeText).toHaveBeenCalledExactlyOnceWith('十月中旬。')
    expect(host.querySelector('.dc-turn-note')?.textContent).toBe('已复制')
    await tick(2000)
    expect(host.querySelector('.dc-turn-note')).toBeNull()
    // A failed save shows nothing here: the island already reported it.
    onSaveNote.mockResolvedValueOnce(false)
    await click(host, '存为笔记')
    expect(host.querySelector('.dc-turn-note')).toBeNull()
    // 新会话 clears the transcript and starts from null again.
    await click(host, '新会话')
    expect(capsules(host)).toEqual([])
    expect(host.querySelector('.dc-session-empty')).toBeTruthy()
    await type(host, '新问题')
    await key(field(host), 'Enter')
    expect(bridge.send).toHaveBeenLastCalledWith({ sessionId: null, text: '新问题', model: '' })
  })

  it('turns the send button into 停止 while a turn runs and interrupts through the bridge', async () => {
    const { bridge, emit } = fakeBridge()
    const { host } = await mount(<Panel bridge={bridge} />)
    await tick(0)
    await type(host, '慢慢想')
    await key(field(host), 'Enter')
    expect(host.querySelector('button[aria-label="发送"]')).toBeNull()
    await click(host, '停止')
    expect(bridge.interrupt).toHaveBeenCalledTimes(1)
    // The bridge answers with a turn-error once the process is gone; the partial text stays.
    await emit({ type: 'delta', turnId: 'turn-1', text: '想到一半' })
    await emit({ type: 'turn-error', turnId: 'turn-1', sessionId: 'sess-1', message: '已停止。' })
    expect(live(host)).toBeNull()
    expect(replies(host)).toEqual(['想到一半'])
    expect(host.querySelector('.dc-turn-error')?.textContent).toBe('已停止。')
    expect(host.querySelector('button[aria-label="发送"]')).toBeTruthy()
  })

  it('shows the login block on a not-logged-in turn error and comes back after 重试', async () => {
    const { bridge, emit } = fakeBridge()
    const onRunningChange = vi.fn()
    const { host } = await mount(<Panel bridge={bridge} onRunningChange={onRunningChange} />)
    await tick(0)
    await type(host, '你好')
    await key(field(host), 'Enter')
    await emit({ type: 'turn-error', turnId: 'turn-1', sessionId: null, message: 'Not logged in · Please run /login', notLoggedIn: true })
    expect(host.querySelector('.dc-session-state-title')?.textContent).toBe(LOGIN_TITLE)
    expect(host.querySelector('.dc-session-state-note')?.textContent).toBe(LOGIN_NOTE)
    expect(onRunningChange).toHaveBeenLastCalledWith(false)
    expect(field(host)).toBeNull()
    await click(host, '重试')
    await tick(0)
    expect(bridge.status).toHaveBeenCalledTimes(2)
    expect(host.querySelector('.dc-session-state')).toBeNull()
    expect(capsules(host)).toEqual(['你好'])
    expect(host.querySelector('.dc-turn-error')?.textContent).toBe('Not logged in · Please run /login')
    // Status itself can say the CLI is logged out.
    vi.mocked(bridge.status).mockResolvedValueOnce(okStatus({ loggedIn: false, reason: '未登录' }))
    const second = await mount(<Panel bridge={bridge} />)
    await tick(0)
    expect(second.host.querySelector('.dc-session-state-title')?.textContent).toBe(LOGIN_TITLE)
  })

  it('shows a refused send as one line and gives the text back', async () => {
    const { bridge } = fakeBridge()
    vi.mocked(bridge.send).mockResolvedValueOnce({ ok: false, error: '上一轮还没结束。' })
    const onRunningChange = vi.fn()
    const { host } = await mount(<Panel bridge={bridge} onRunningChange={onRunningChange} />)
    await tick(0)
    await type(host, '再问一个')
    await key(field(host), 'Enter')
    expect(host.querySelector('.dc-session-problem')?.textContent).toBe('上一轮还没结束。')
    expect(field(host).value).toBe('再问一个')
    expect(capsules(host)).toEqual([])
    expect(onRunningChange).toHaveBeenLastCalledWith(false)
    expect(host.querySelector('button[aria-label="发送"]')).toBeTruthy()
  })

  it('clears the draft on Escape first, then hands Escape to the island, and focuses only when asked', async () => {
    const { bridge } = fakeBridge()
    const onEscape = vi.fn()
    const outer = vi.fn()
    const { host, root } = await mount(<div onKeyDown={outer}><Panel bridge={bridge} onEscape={onEscape} /></div>)
    await tick(0)
    expect(document.activeElement).toBe(document.body)
    await act(async () => { root.render(<div onKeyDown={outer}><Panel bridge={bridge} onEscape={onEscape} focusRequested={1} /></div>) })
    expect(document.activeElement).toBe(field(host))
    await type(host, '半句')
    await key(field(host), 'Escape')
    expect(field(host).value).toBe('')
    expect(onEscape).not.toHaveBeenCalled()
    await key(field(host), 'Escape')
    expect(onEscape).toHaveBeenCalledOnce()
    expect(outer).not.toHaveBeenCalled()
    expect(bridge.send).not.toHaveBeenCalled()
  })

  it('keeps the question ahead of a reply that lands before send() answers, and never leaves that turn running', async () => {
    const { bridge, emit } = fakeBridge()
    let answer!: (value: Awaited<ReturnType<AgentBridge['send']>>) => void
    vi.mocked(bridge.send).mockImplementationOnce(() => new Promise((resolve) => { answer = resolve }))
    const onRunningChange = vi.fn()
    const { host } = await mount(<Panel bridge={bridge} onRunningChange={onRunningChange} />)
    await tick(0)
    await type(host, '你好')
    await key(field(host), 'Enter')
    expect(capsules(host)).toEqual(['你好'])
    await emit({ type: 'turn-start', turnId: 'turn-1', sessionId: null, model: '' })
    await emit({ type: 'turn-error', turnId: 'turn-1', sessionId: null, message: '进程退出了。' })
    await act(async () => { answer({ ok: true, turnId: 'turn-1', sessionId: null }) })
    expect(live(host)).toBeNull()
    expect(onRunningChange).toHaveBeenLastCalledWith(false)
    expect(host.querySelector('button[aria-label="发送"]')).toBeTruthy()
    expect([...host.querySelectorAll('.dc-turn')].map((n) => n.className)).toEqual(['dc-turn dc-turn-user', 'dc-turn dc-turn-assistant'])
    expect(host.querySelector('.dc-turn-error')?.textContent).toBe('进程退出了。')
  })

  it('unsubscribes from events on unmount', async () => {
    const { bridge, listeners } = fakeBridge()
    const { root } = await mount(<Panel bridge={bridge} />)
    await tick(0)
    expect(listeners.size).toBe(1)
    await act(async () => { root.unmount() })
    roots.splice(roots.indexOf(root), 1)
    expect(listeners.size).toBe(0)
  })

  it('carries dropped files as chips, sends them with the next question and lists them on the capsule', async () => {
    const { bridge, emit } = fakeBridge()
    const handle: { current: CompanionSessionHandle | null } = { current: null }
    const { host } = await mount(<Panel bridge={bridge} handleRef={handle} />)
    const files = [new File(['x'], '报价.pdf'), new File(['y'], '纪要.png')]
    let attached = false
    await act(async () => { attached = await handle.current!.attach(files) })
    expect(attached).toBe(true)
    expect(bridge.attach).toHaveBeenCalledWith(files)
    expect([...host.querySelectorAll('.dc-session-chip-name')].map((n) => n.textContent)).toEqual(['报价.pdf', '纪要.png'])
    expect(field(host).placeholder).toBe('问 Claude 关于这 2 个文件…')
    await click(host, '不带上 纪要.png')
    expect(host.querySelectorAll('.dc-session-chip')).toHaveLength(1)
    await type(host, '这份报价合理吗')
    await key(field(host), 'Enter')
    expect(bridge.send).toHaveBeenCalledWith(expect.objectContaining({ text: '这份报价合理吗', attachments: [`${CWD}/workspace/附件/报价.pdf`] }))
    expect(host.querySelector('.dc-session-chip')).toBeNull()
    expect(host.querySelector('.dc-turn-attached')?.textContent).toContain('报价.pdf')
    await emit({ type: 'turn-end', turnId: 'turn-1', sessionId: 's1', message: reply('a1', '合理。') })
    // A dropped piece of text lands in the composer; files alone send a default question.
    await act(async () => { handle.current!.draft('拖来的一段话') })
    expect(field(host).value).toBe('拖来的一段话')
    await type(host, '')
    await act(async () => { await handle.current!.attach([new File(['z'], '合同.pdf')]) })
    await key(field(host), 'Enter')
    expect(bridge.send).toHaveBeenLastCalledWith(expect.objectContaining({ text: ATTACH_ONLY_PROMPT, attachments: [`${CWD}/workspace/附件/合同.pdf`] }))
  })

  it('gives the composer back after 重试 on a logged-out status, with a hint instead of a wall', async () => {
    const { bridge } = fakeBridge(okStatus({ loggedIn: false }))
    const { host } = await mount(<Panel bridge={bridge} />)
    expect(host.textContent).toContain(LOGIN_TITLE)
    await click(host, '重试')
    expect(host.querySelector('textarea[aria-label="问 Claude"]')).toBeTruthy()
    expect(host.textContent).toContain(LOGIN_HINT)
    expect(host.textContent).not.toContain(LOGIN_TITLE)
  })

  it('keeps a file that was shelved during the turn marked as shelved when the turn ends', async () => {
    const { bridge, emit } = fakeBridge()
    const { host } = await mount(<Panel bridge={bridge} />)
    await type(host, '写个文件')
    await key(field(host), 'Enter')
    const artifact = { path: `${CWD}/workspace/交期说明.md`, name: '交期说明.md', action: 'write' as const }
    await emit({ type: 'artifact', turnId: 'turn-1', artifact })
    await click(host, '放入暂存箱')
    expect(host.querySelector('.dc-turn-file-state')?.textContent).toBe('已放入')
    await emit({ type: 'turn-end', turnId: 'turn-1', sessionId: 's1', message: reply('a1', '写好了。', { artifacts: [artifact] }) })
    expect(host.querySelector('.dc-turn-file-state')?.textContent).toBe('已放入')
    expect(host.querySelectorAll('.dc-turn-file button')).toHaveLength(0)
  })

  it('drops a remembered model the bridge no longer offers, so the request matches the select', async () => {
    localStorage.setItem('memoket.companion.agent.model', 'haiku')
    const { bridge } = fakeBridge()
    const { host } = await mount(<Panel bridge={bridge} />)
    expect(host.querySelector<HTMLSelectElement>('select[aria-label="模型"]')?.value).toBe('')
    expect(localStorage.getItem('memoket.companion.agent.model')).toBeNull()
    await type(host, '你好')
    await key(field(host), 'Enter')
    expect(bridge.send).toHaveBeenCalledWith(expect.objectContaining({ model: '' }))
  })
})
