// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AgentBridge, AgentTurnEvent, CompanionBridge, CompanionItem, CompanionState, CompanionSurface, DecideBridge, DecideSelection } from '../../desktop'
import type { Note } from '../../api'
import * as api from '../../api'
import { readWorkspaceTasks, workspaceStorageKey } from '../../util/workspaceState'
import DesktopCompanion from '../DesktopCompanion'
import { EditorView } from '@codemirror/view'

vi.mock('../../api', () => ({
  getUser: () => localStorage.getItem('memoket-note-user') || 'companion-test',
  createNote: vi.fn(), desktopAIStatus: vi.fn(), composeDesktopNote: vi.fn(), uploadNoteAttachment: vi.fn(),
  recall: vi.fn(), kbDashboard: vi.fn(), syncNoteToKb: vi.fn(), jobStatus: vi.fn(), decide: vi.fn(),
}))

const roots: Root[] = []
const note: Note = { id: 'n1', user_id: 'companion-test', title: '供应商会议', content: '下周三确认报价。', spine: '', beats: [], pinned: false, created_at: '2026-09-22', updated_at: '2026-09-22' }
const fileItem: CompanionItem = { id: 'f1', kind: 'file', title: '报价.pdf', path: '/tmp/报价.pdf', createdAt: '2026-09-22' }

/** 附件的地址走后端的 /api/assets/{name}：写成模板，后端契约检查（test_api_contract）才认得出参数段。 */
const assetUrl = (name: string) => `/api/assets/${name}`
function attachmentAsset(file: File, url?: string): api.NoteAttachmentAsset {
  const assetName = Array.from(file.name).map(character => character.codePointAt(0)!.toString(36)).join('-')
  return { url: url || `/api/assets/${assetName}.${file.type.startsWith('image/') ? 'png' : 'pdf'}`, name: file.name, kind: file.type.startsWith('image/') ? 'image' : 'file', bytes: file.size, content_type: file.type }
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('memoket-note-user', 'companion-test')
  delete window.memoketDesktop
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.mocked(api.createNote).mockResolvedValue(note)
  vi.mocked(api.uploadNoteAttachment).mockImplementation(async (file) => attachmentAsset(file))
  vi.mocked(api.desktopAIStatus).mockResolvedValue({ configured: true, provider: 'gemini', model: 'test-gemini' })
  vi.mocked(api.composeDesktopNote).mockResolvedValue({ title: '生成后的笔记', content: '## 后续\n明天继续核对。', sourceCount: 1, model: 'test-gemini' })
  // An empty knowledge base by default: the ambient memory strip stays hidden unless a test provides facts.
  vi.mocked(api.recall).mockResolvedValue({ facts: [], took_ms: 0, terms: [], kb_empty: true })
  vi.mocked(api.syncNoteToKb).mockResolvedValue({ job_id: 'job-1', status: 'queued' })
  vi.mocked(api.jobStatus).mockResolvedValue(ingestJob('done', 0))
  vi.mocked(api.kbDashboard).mockResolvedValue({ stats: { facts: 0, topics: 0, entities: 0, units: 0, lines: 0, start_date: '', end_date: '' }, months: [], top_topics: [], top_entities: [], recent_units: [], kinds: [], speakers: [] } as unknown as api.KbDashboard)
})
afterEach(async () => {
  await act(async () => { for (const root of roots.splice(0)) root.unmount() })
  document.body.innerHTML = ''
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.clearAllMocks()
})

/** A knowledge-base ingest job as the island polls it. */
const ingestJob = (status: string, facts: number, detail = '') => ({ job_id: 'job-1', status, facts, detail, items: [] }) as unknown as Awaited<ReturnType<typeof api.jobStatus>>

function native(surface: CompanionSurface, items: CompanionItem[] = [], expanded = true) {
  let state: CompanionState = { surface: 'top', expanded, panel: surface === 'top' ? 'capture' : 'clipboard', items, storageError: '' }
  let listener: ((next: CompanionState) => void) | undefined
  const emit = (next: CompanionState) => { state = next; listener?.(state) }
  const bridge: CompanionBridge = {
    getState: vi.fn(async () => state),
    onState: vi.fn((fn) => { listener = fn; return () => { listener = undefined } }),
    setExpanded: vi.fn(async (expanded, panel) => { state = { ...state, expanded, panel: panel || state.panel }; return state }),
    settleCollapsed: vi.fn(async () => {}),
    isPointerInside: vi.fn(async () => true),
    show: vi.fn(async () => {}), openWorkspace: vi.fn(async () => {}),
    addFiles: vi.fn(async () => ({ ok: true, state })),
    addText: vi.fn(async () => ({ ok: true, state })),
    peekClipboard: vi.fn(async () => ({ text: '', truncated: false })),
    pasteClipboard: vi.fn(async () => ({ ok: true, state })),
    refreshPreview: vi.fn(async () => ({ ok: true })),
    revealRemoved: vi.fn(async () => ({ ok: true })),
    remove: vi.fn(async (id) => { state = { ...state, items: state.items.filter((item) => item.id !== id) }; return { ok: true, state } }),
    open: vi.fn(async () => ({ ok: true })), reveal: vi.fn(async () => ({ ok: true })), startDrag: vi.fn(async () => ({ ok: true })), copy: vi.fn(async () => ({ ok: true })),
    listWindows: vi.fn(async () => ({ ok: true, candidates: [] })), addWindow: vi.fn(async () => ({ ok: true, state })), recallWindow: vi.fn(async () => ({ ok: true })),
  }
  // The island's Claude Code session: a logged-in CLI with one model, and an emitter for its turn events.
  const agentListeners = new Set<(event: AgentTurnEvent) => void>()
  const agent: AgentBridge = {
    status: vi.fn(async () => ({ available: true, loggedIn: true, version: '2.1.278', reason: '', cwd: '/tmp/companion/agent', models: [{ id: 'sonnet', label: 'Sonnet' }], runningTurnId: null })),
    sessions: vi.fn(async () => []),
    transcript: vi.fn(async () => []),
    send: vi.fn(async () => ({ ok: true, turnId: 'turn-1', sessionId: null })),
    interrupt: vi.fn(async () => ({ ok: true })),
    attach: vi.fn(async (files: File[]) => ({ ok: true, attachments: files.map((file) => ({ path: `/tmp/agent/workspace/附件/${file.name}`, name: file.name, action: 'attach' as const })) })),
    shelve: vi.fn(async () => ({ ok: true, state })),
    onEvent: vi.fn((callback: (event: AgentTurnEvent) => void) => { agentListeners.add(callback); return () => { agentListeners.delete(callback) } }),
  }
  const emitAgent = (event: AgentTurnEvent) => { agentListeners.forEach((listener) => listener(event)) }
  // The global 拿主意 hotkey: the main process expands the island to the decide stage, then broadcasts the selection.
  const decideListeners = new Set<(selection: DecideSelection) => void>()
  const decide: DecideBridge = {
    status: vi.fn(async () => ({ accelerator: 'Alt+D', registered: true, tap: false, reason: '', accessibility: true })),
    onSelection: vi.fn((callback: (selection: DecideSelection) => void) => { decideListeners.add(callback); return () => { decideListeners.delete(callback) } }),
    onPending: vi.fn(() => () => {}),
  }
  const emitDecide = (selection: DecideSelection) => { emit({ ...state, expanded: true, panel: 'decide' }); decideListeners.forEach((listener) => listener(selection)) }
  window.memoketDesktop = { setTheme: () => {}, companion: bridge, agent, decide }
  return { bridge, agent, decide, emit, emitAgent, emitDecide, state: () => state }
}

/** A finished 拿主意 answer: three scored options, one grounded in a recalled fact. */
const decideOut = (): api.DecideOut => ({
  mode: 'options', frame: '这批货要不要压价', isDecision: 0.93, grounded: true, scorer: 'jev', model: 'jev-1.13.0', tookMs: 900,
  items: [
    { id: 'a', label: '谈价', why: '上次报价还有余地', probability: 0.62, factIds: ['fact-1'] },
    { id: 'b', label: '接受', why: '交期更要紧', probability: 0.28, factIds: [] },
    { id: 'c', label: '换供应商', why: '备选还没验过', probability: 0.1, factIds: [] },
  ],
  facts: [{ id: 'fact-1', text: '上次谈价让了 5%', when: '2026-09-01' }],
})

async function mount(props: Parameters<typeof DesktopCompanion>[0]) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  await act(async () => { root.render(<DesktopCompanion {...props} />) })
  return { host, root }
}

/** The island body is a CodeMirror editor now; tests read and drive it through the view. */
function editorView(host: HTMLElement): EditorView {
  return EditorView.findFromDOM(host.querySelector<HTMLElement>('.dc-draft-editor .cm-editor')!)!
}
function body(host: HTMLElement): string {
  return editorView(host).state.doc.toString()
}

async function input(host: HTMLElement, label: string, value: string) {
  if (label === '随手记正文') {
    const view = editorView(host)
    await act(async () => { view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value }, selection: { anchor: value.length } }) })
    return
  }
  if (label === '查找暂存内容' && !host.querySelector('[aria-label="查找暂存内容"]')) await click(host, '搜索暂存内容')
  const element = host.querySelector<HTMLInputElement | HTMLTextAreaElement>(`[aria-label="${label}"]`)!
  const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  await act(async () => {
    Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(element, value)
    element.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

async function click(host: HTMLElement, text: string) {
  const buttons = [...host.querySelectorAll('button')]
  const button = buttons.find((candidate) => candidate.getAttribute('aria-label') === text) || buttons.find((candidate) => candidate.textContent?.includes(text))!
  expect(button, `button ${text}`).toBeTruthy()
  await act(async () => { button.click() })
}

async function addToShelf(host: HTMLElement, label: string) {
  await click(host, '添加暂存内容')
  const menu = host.querySelector('[role="menu"][aria-label="添加暂存内容"]')!
  expect(menu).toBeTruthy()
  const item = [...menu.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find((candidate) => candidate.textContent?.includes(label))!
  expect(item, `shelf menu item ${label}`).toBeTruthy()
  await act(async () => { item.click() })
}

function dragEvent(type: string, dataTransfer: Partial<DataTransfer>, clientX = 0, options: { clientY?: number; relatedTarget?: EventTarget | null } = {}) {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'dataTransfer', { value: dataTransfer })
  Object.defineProperty(event, 'clientX', { value: clientX })
  Object.defineProperty(event, 'clientY', { value: options.clientY || 0 })
  Object.defineProperty(event, 'relatedTarget', { value: options.relatedTarget ?? null })
  return event
}

async function hoverNav(host: HTMLElement, label: string) {
  const button = host.querySelector<HTMLButtonElement>(`nav button[aria-label="${label}"]`)!
  expect(button).toBeTruthy()
  await act(async () => { button.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, relatedTarget: document.body })) })
}

async function beginFileDrag(host: HTMLElement, files: File[]) {
  const transfer = { files: files as unknown as FileList, types: ['Files'], getData: () => '' }
  await act(async () => { host.querySelector('.dc-companion')!.dispatchEvent(dragEvent('dragenter', transfer)) })
  expect(host.querySelector('[aria-label="选择文件用途"]')).toBeTruthy()
  return transfer
}

async function dropFiles(host: HTMLElement, destination: 'note' | 'agent' | 'shelf', files: File[]) {
  const transfer = await beginFileDrag(host, files)
  const region = host.querySelector(`[data-drop-destination="${destination}"]`)!
  expect(region).toBeTruthy()
  await act(async () => { region.dispatchEvent(dragEvent('drop', transfer)) })
}

describe('Desktop companion preserves real work in its local surface', () => {
  it('opens the body editor by default and keeps empty AI menu actions disabled without an implicit request', async () => {
    native('top')
    const { host } = await mount({ surface: 'top' })
    expect(host.querySelector('[aria-label="随手记正文"]')).toBeTruthy()
    expect(host.querySelector('[aria-label="随手记标题"]')).toBeTruthy()
    expect(host.querySelector('[aria-label="AI 快捷动作"]')).toBeNull()
    expect(host.querySelector('[role="menu"]')).toBeNull()
    await click(host, 'AI 操作')
    const menu = host.querySelector('[role="menu"][aria-label="AI 操作"]')!
    const actions = [...menu.querySelectorAll<HTMLButtonElement>('[role="menuitem"][aria-label]')]
    expect(actions).toHaveLength(6)
    expect(actions.every((button) => button.disabled)).toBe(true)
    await act(async () => { actions.forEach((button) => button.click()) })
    expect(api.composeDesktopNote).not.toHaveBeenCalled()
    expect(api.createNote).not.toHaveBeenCalled()
    expect(api.desktopAIStatus).not.toHaveBeenCalled()
  })

  it('uses the clipboard snapshot only for an empty body, without silently inserting or saving it', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-23T12:01:00Z'))
    const { bridge } = native('top', [{ id: 'unselected', kind: 'text', title: '无关材料', text: '不发送这段', createdAt: '2026-09-22' }])
    const draftKey = 'memoket.companion.draft.companion-test'
    vi.mocked(bridge.peekClipboard).mockResolvedValue({ text: '刚复制的开头 A', truncated: false })
    const { host } = await mount({ surface: 'top' })
    expect(host.querySelector('.dc-draft-ghost-text')?.textContent).toContain('刚复制的开头 A')
    expect(body(host)).toBe('')
    expect(api.composeDesktopNote).not.toHaveBeenCalled()
    expect(localStorage.getItem(draftKey)).toBeNull()
    await click(host, 'AI 操作')
    expect(host.querySelector('[role="menu"]')?.textContent).toContain('刚刚复制')
    // The action uses the displayed snapshot, not a subsequent clipboard read.
    vi.mocked(bridge.peekClipboard).mockResolvedValue({ text: '随后复制的 B', truncated: false })
    await act(async () => { await vi.advanceTimersByTimeAsync(1250) })
    expect(host.querySelector('.dc-draft-ghost-text')?.textContent).toContain('随后复制的 B')
    await click(host, '一键续写')
    expect(api.composeDesktopNote).toHaveBeenCalledTimes(1)
    expect(api.composeDesktopNote).toHaveBeenCalledWith([
      expect.objectContaining({ kind: 'text', text: '刚复制的开头 A' }),
    ], '', expect.any(AbortSignal), 'continue')
    expect(bridge.peekClipboard).toHaveBeenCalledTimes(2)
    expect(bridge.addText).not.toHaveBeenCalled()
    expect(bridge.pasteClipboard).not.toHaveBeenCalled()
    expect(api.createNote).not.toHaveBeenCalled()
    // Finishing writes straight into the draft: no result panel, nothing saved as a note, and one undo.
    expect(host.querySelector('[aria-label="生成结果预览"]')).toBeNull()
    expect(body(host)).toBe('## 后续\n明天继续核对。')
    expect(JSON.parse(localStorage.getItem(draftKey)!).content).toBe('## 后续\n明天继续核对。')
    expect(api.createNote).not.toHaveBeenCalled()
    await click(host, '撤销这次写入')
    expect(body(host)).toBe('')
    expect(localStorage.getItem(draftKey)).toBeNull()
  })

  it('sends only the selected body text and preserves the rest of the draft, clipboard and shelf materials', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-23T12:02:00Z'))
    const { bridge } = native('top', [{ id: 'other', kind: 'text', title: '其他资料', text: '不要混入', createdAt: '2026-09-22' }])
    const original = { title: '会议计划', content: '前文不要发送\n只处理这一段。\n后文也不要发送' }
    const selected = '只处理这一段。'
    localStorage.setItem('memoket.companion.draft.companion-test', JSON.stringify(original))
    vi.mocked(bridge.peekClipboard).mockResolvedValue({ text: '不发送的剪贴板内容', truncated: false })
    const { host } = await mount({ surface: 'top' })
    const view = editorView(host)
    const field = view.contentDOM
    field.focus()
    view.dispatch({ selection: { anchor: original.content.indexOf(selected), head: original.content.indexOf(selected) + selected.length } })
    await act(async () => { field.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true })) })
    expect(host.querySelector('[role="menu"]')?.textContent).toContain('选中文字')
    await click(host, '提取待办')
    expect(api.composeDesktopNote).toHaveBeenCalledWith([
      expect.objectContaining({ kind: 'text', title: '选中文字', text: selected }),
    ], '', expect.any(AbortSignal), 'tasks')
    expect(api.createNote).not.toHaveBeenCalled()
    expect(host.querySelector('[aria-label="生成结果预览"]')).toBeNull()
    // The result lands right after the selection; the text around it is untouched.
    const written = '前文不要发送\n只处理这一段。\n\n## 后续\n明天继续核对。\n\n后文也不要发送'
    expect(body(host)).toBe(written)
    expect(JSON.parse(localStorage.getItem('memoket.companion.draft.companion-test')!)).toEqual({ ...original, content: written })
  })

  it('uses the whole current body when no text is selected, even when a clipboard suggestion exists', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-23T12:02:30Z'))
    const { bridge } = native('top')
    const original = { title: '会议计划', content: '第一行原文\n第二行待办  ' }
    localStorage.setItem('memoket.companion.draft.companion-test', JSON.stringify(original))
    vi.mocked(bridge.peekClipboard).mockResolvedValue({ text: '不要混入剪贴板', truncated: false })
    const { host } = await mount({ surface: 'top' })
    const view = editorView(host)
    const field = view.contentDOM
    field.focus()
    view.dispatch({ selection: { anchor: 2, head: 2 } })
    await click(host, 'AI 操作')
    expect(host.querySelector('[role="menu"]')?.textContent).toContain('当前笔记')
    await click(host, '整理表格')
    expect(api.composeDesktopNote).toHaveBeenCalledWith([
      expect.objectContaining({ kind: 'text', title: original.title, text: original.content }),
    ], '', expect.any(AbortSignal), 'table')
    expect(api.createNote).not.toHaveBeenCalled()
    expect(JSON.parse(localStorage.getItem('memoket.companion.draft.companion-test')!)).toEqual({ ...original, content: original.content + '\n\n## 后续\n明天继续核对。' })
  })

  it('closes only the context menu on Escape and restores the body selection without collapsing the island', async () => {
    vi.useFakeTimers()
    const { bridge } = native('top')
    const { host } = await mount({ surface: 'top' })
    await input(host, '随手记正文', '保留我的这段选区')
    const view = editorView(host)
    const field = view.contentDOM
    field.focus()
    view.dispatch({ selection: { anchor: 6, head: 2 } })
    const context = new MouseEvent('contextmenu', { bubbles: true, cancelable: true })
    await act(async () => { field.dispatchEvent(context) })
    expect(context.defaultPrevented).toBe(true)
    const menu = host.querySelector('[role="menu"][aria-label="AI 操作"]')!
    expect(menu).toBeTruthy()
    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    await act(async () => { menu.dispatchEvent(escape); await vi.advanceTimersByTimeAsync(32) })
    expect(escape.defaultPrevented).toBe(true)
    expect(host.querySelector('[role="menu"]')).toBeNull()
    expect(document.activeElement).toBe(field)
    expect([view.state.selection.main.from, view.state.selection.main.to]).toEqual([2, 6])
    expect(bridge.setExpanded).not.toHaveBeenCalled()
    expect(api.composeDesktopNote).not.toHaveBeenCalled()
    expect(view.state.doc.toString()).toBe('保留我的这段选区')
  })

  it('opens the AI menu from keyboard context commands and navigates its actions without editing the body', async () => {
    vi.useFakeTimers()
    native('top')
    const { host } = await mount({ surface: 'top' })
    await input(host, '随手记正文', '键盘操作的原始内容')
    const view = editorView(host)
    const field = view.contentDOM
    const press = async (target: Element, key: string, shiftKey = false) => {
      const event = new KeyboardEvent('keydown', { key, shiftKey, bubbles: true, cancelable: true })
      await act(async () => { target.dispatchEvent(event); await vi.advanceTimersByTimeAsync(32) })
      return event
    }
    for (const [key, shift] of [['F10', true], ['ContextMenu', false]] as const) {
      field.focus()
      view.dispatch({ selection: { anchor: 1, head: 4 } })
      expect((await press(field, key, shift)).defaultPrevented).toBe(true)
      const menu = host.querySelector('[role="menu"][aria-label="AI 操作"]')!
      const actions = [...menu.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')]
      expect(document.activeElement).toBe(actions[0])
      await press(document.activeElement!, 'ArrowDown')
      expect(document.activeElement).toBe(actions[1])
      await press(document.activeElement!, 'End')
      expect(document.activeElement).toBe(actions.at(-1))
      await press(document.activeElement!, 'ArrowDown')
      expect(document.activeElement).toBe(actions[0])
      await press(document.activeElement!, 'ArrowUp')
      expect(document.activeElement).toBe(actions.at(-1))
      await press(document.activeElement!, 'Home')
      expect(document.activeElement).toBe(actions[0])
      await press(document.activeElement!, 'Escape')
      expect(document.activeElement).toBe(field)
      expect([view.state.selection.main.from, view.state.selection.main.to]).toEqual([1, 4])
    }
    expect(view.state.doc.toString()).toBe('键盘操作的原始内容')
    expect(api.composeDesktopNote).not.toHaveBeenCalled()
    expect(api.createNote).not.toHaveBeenCalled()
  })

  it('keeps generation alive while editing, using the shelf or focus, and collapsing the island', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-23T12:03:00Z'))
    const { bridge } = native('top', [fileItem])
    let finish!: (value: api.DesktopComposeResult) => void
    vi.mocked(api.composeDesktopNote).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    const { host } = await mount({ surface: 'top' })
    await input(host, '随手记正文', '原始段落')
    await click(host, 'AI 操作')
    await click(host, '一键续写')
    const signal = vi.mocked(api.composeDesktopNote).mock.calls[0][2]!
    expect(signal.aborted).toBe(false)
    expect(editorView(host).state.facet(EditorView.editable)).toBe(true)
    expect(host.querySelector<HTMLButtonElement>('[aria-label="收起浮条"]')?.disabled).toBe(false)
    expect(host.querySelector('[aria-label="生成结果预览"]')).toBeNull()
    await input(host, '随手记正文', '原始段落\n生成期间新写的内容')
    await click(host, '暂存架')
    expect(host.querySelector('[aria-label="预览 报价.pdf"]')).toBeTruthy()
    await act(async () => { host.querySelector('.dc-item')!.dispatchEvent(dragEvent('dragstart', { setData: vi.fn() })) })
    expect(bridge.startDrag).toHaveBeenCalledWith('f1')
    expect(signal.aborted).toBe(false)
    await click(host, '待办')
    expect(host.querySelector('.dc-tasks')).toBeTruthy()
    expect(signal.aborted).toBe(false)
    await act(async () => {
      host.querySelector('section')!.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body }))
      await vi.advanceTimersByTimeAsync(260)
    })
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(false, 'tasks', false)
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(host.querySelector('.dc-panel')?.hasAttribute('hidden')).toBe(true)
    expect(host.querySelector('.dc-panel')?.hasAttribute('inert')).toBe(true)
    expect(signal.aborted).toBe(false)
    await click(host, '展开桌面口袋')
    expect(host.querySelector('.dc-tasks')).toBeTruthy()
    await click(host, '随手记')
    expect(body(host)).toBe('原始段落\n生成期间新写的内容')
    expect(api.composeDesktopNote).toHaveBeenCalledTimes(1)
    await click(host, '暂存架')
    const transitions = vi.mocked(bridge.setExpanded).mock.calls.length
    await act(async () => { finish({ title: '续写结果', content: '新的续写段落。', sourceCount: 1, model: 'test-gemini' }) })
    // Completion leaves the user in the feature they are currently using.
    expect(bridge.setExpanded).toHaveBeenCalledTimes(transitions)
    expect(host.querySelector('[aria-label="预览 报价.pdf"]')).toBeTruthy()
    expect(host.querySelector('[aria-label="生成结果预览"]')).toBeNull()
    expect(api.createNote).not.toHaveBeenCalled()
    await click(host, '随手记')
    expect(host.querySelector('[aria-label="生成结果预览"]')).toBeNull()
    // The continuation was appended to the draft as it stood at completion, after the words typed meanwhile.
    expect(body(host)).toBe('原始段落\n生成期间新写的内容\n\n新的续写段落。')
    expect(host.textContent).toContain('已写入')
    expect(api.composeDesktopNote).toHaveBeenCalledTimes(1)
    expect(api.createNote).not.toHaveBeenCalled()
  })

  it('inserts an AI result only on request and appends to the latest user draft without overwriting it', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-23T12:03:15Z'))
    native('top')
    let finish!: (value: api.DesktopComposeResult) => void
    vi.mocked(api.composeDesktopNote).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    const { host } = await mount({ surface: 'top' })
    await input(host, '随手记标题', '用户自己的标题')
    await input(host, '随手记正文', '发送给 AI 的原文')
    await click(host, 'AI 操作')
    await click(host, '一键续写')
    await input(host, '随手记正文', '用户已经改写，并补上了新想法。')
    await act(async () => { finish({ title: 'AI 生成的标题', content: '接在正文后的续写内容。', sourceCount: 1, model: 'test-gemini' }) })
    const expected = { title: '用户自己的标题', content: '用户已经改写，并补上了新想法。\n\n接在正文后的续写内容。' }
    expect(host.querySelector<HTMLInputElement>('[aria-label="随手记标题"]')?.value).toBe(expected.title)
    expect(body(host)).toBe(expected.content)
    expect(JSON.parse(localStorage.getItem('memoket.companion.draft.companion-test')!)).toEqual(expected)
    expect(api.createNote).not.toHaveBeenCalled()
    expect(api.composeDesktopNote).toHaveBeenCalledTimes(1)
  })

  it('cancels only the AI task and ignores its late response without saving or changing the draft', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-23T12:03:30Z'))
    const { bridge } = native('top')
    vi.mocked(bridge.peekClipboard).mockResolvedValue({ text: '尚未处理的材料', truncated: false })
    let finish!: (value: api.DesktopComposeResult) => void
    vi.mocked(api.composeDesktopNote).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    const { host } = await mount({ surface: 'top' })
    await click(host, 'AI 操作')
    await click(host, '整理笔记')
    const signal = vi.mocked(api.composeDesktopNote).mock.calls[0][2]!
    expect(signal.aborted).toBe(false)
    expect(body(host)).toBe('')
    await click(host, '取消生成')
    expect(signal.aborted).toBe(true)
    await act(async () => { finish({ title: '迟到的响应', content: '不要加入草稿', sourceCount: 1, model: 'test-gemini' }) })
    expect(host.querySelector('[aria-label="整理笔记标题"]')).toBeNull()
    expect(host.textContent).not.toContain('迟到的响应')
    expect(host.querySelector('[aria-label="生成结果预览"]')).toBeNull()
    expect(api.createNote).not.toHaveBeenCalled()
    expect(host.querySelector('[aria-label="随手记正文"]')).toBeTruthy()
    expect(api.composeDesktopNote).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem('memoket.companion.draft.companion-test')).toBeNull()
  })

  it('saves directly without opening the workspace; a failed save preserves the user draft', async () => {
    const { bridge } = native('top')
    vi.mocked(api.createNote).mockRejectedValueOnce(new Error('暂时离线'))
    const { host } = await mount({ surface: 'top' })
    await input(host, '随手记正文', '稍后确认交期\n下午三点回复')
    await click(host, '存入笔记')
    expect(api.createNote).toHaveBeenCalledWith('稍后确认交期', '稍后确认交期\n下午三点回复')
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('文字已保留')
    expect(localStorage.getItem('memoket.companion.draft.companion-test')).toContain('下午三点回复')
    await click(host, '存入笔记')
    expect(localStorage.getItem('memoket.companion.draft.companion-test')).toBeNull()
    expect(body(host)).toBe('')
    expect(host.querySelector('.dc-stage [role="status"]')?.textContent).toContain('已存入笔记')
    expect(bridge.openWorkspace).not.toHaveBeenCalled()
  })

  it('hands dropped files to Claude: the session panel gets them as attachments and the pill says so', async () => {
    vi.useFakeTimers()
    const { agent } = native('top')
    const { host } = await mount({ surface: 'top' })
    const files = [new File(['x'], '报价.pdf')]
    await dropFiles(host, 'agent', files)
    await act(async () => { await vi.advanceTimersByTimeAsync(50) })
    expect(agent.attach).toHaveBeenCalledWith(files)
    expect(host.querySelector('.dc-session-host')).toBeTruthy()
    expect(host.querySelector('.dc-session-chip-name')?.textContent).toBe('报价.pdf')
    expect(host.querySelector('.dc-feedback')?.textContent).toContain('已交给 Claude')
    expect(host.querySelector('.dc-island-hint')?.textContent).toBe('已交给 Claude · 1 个文件')
    expect(host.querySelector('[aria-label="选择文件用途"]')).toBeNull()
  })

  it('sends a saved note into the knowledge base while the session panel stays mounted behind the notes', async () => {
    vi.useFakeTimers()
    native('top')
    vi.mocked(api.jobStatus).mockResolvedValueOnce(ingestJob('running', 0)).mockResolvedValueOnce(ingestJob('done', 3))
    const { host } = await mount({ surface: 'top' })
    expect(host.querySelector('.dc-session-host')).toBeNull()
    await click(host, '会话')
    expect(host.querySelector('.dc-session-host')).toBeTruthy()
    expect(host.querySelector('.dc-session-host')?.hasAttribute('hidden')).toBe(false)
    expect(host.querySelector('[aria-label="问 Claude"]')).toBeTruthy()
    await click(host, '随手记')
    expect(host.querySelector('.dc-session-host')?.hasAttribute('hidden')).toBe(true)
    await input(host, '随手记正文', '供应商把交期改到十月中旬')
    await click(host, '存入笔记')
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(api.createNote).toHaveBeenCalledTimes(1)
    expect(api.syncNoteToKb).toHaveBeenCalledExactlyOnceWith(note.id)
    expect(body(host)).toBe('')
    expect(host.querySelector('.dc-feedback')?.textContent).toContain('正在进入知识库')
    expect(host.querySelector('.dc-island-hint')?.textContent).toBe('正在进入知识库')
    await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
    expect(api.jobStatus).toHaveBeenCalledTimes(1)
    expect(host.querySelector('.dc-island-hint')?.textContent).toBe('正在进入知识库')
    await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
    expect(api.jobStatus).toHaveBeenCalledTimes(2)
    expect(host.querySelector('.dc-feedback')?.textContent).toContain('已进入知识库 · 3 条事实')
    expect(host.querySelector('.dc-island-hint')?.textContent).toBe('随手记')
    // The session panel is still mounted behind the notes, ready to be switched back to.
    expect(host.querySelector('.dc-session-host')).toBeTruthy()
    expect(host.querySelector('.dc-session-host')?.hasAttribute('hidden')).toBe(true)
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })
    expect(api.jobStatus).toHaveBeenCalledTimes(2)
  })

  it('mounts the session panel on hover without focus and keeps a running turn on the collapsed pill', async () => {
    vi.useFakeTimers()
    const { agent, emitAgent } = native('top')
    const { host } = await mount({ surface: 'top' })
    expect(host.querySelector('.dc-session-host')).toBeNull()
    await hoverNav(host, '会话')
    expect(host.querySelector('.dc-session-host')).toBeTruthy()
    expect(agent.status).toHaveBeenCalledTimes(1)
    expect(agent.onEvent).toHaveBeenCalledTimes(1)
    expect(host.querySelector('.dc-session-empty-title')?.textContent).toBe('和 Claude 直接对话')
    expect(host.contains(document.activeElement)).toBe(false)
    await input(host, '问 Claude', '交期说明怎么写')
    await act(async () => { host.querySelector('[aria-label="问 Claude"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })) })
    expect(agent.send).toHaveBeenCalledExactlyOnceWith({ sessionId: null, text: '交期说明怎么写', model: '' })
    await act(async () => { emitAgent({ type: 'delta', turnId: 'turn-1', text: '可以这样' }) })
    expect(host.querySelector('.dc-turn-live .dc-turn-text')?.textContent).toBe('可以这样')
    await act(async () => { host.querySelector<HTMLButtonElement>('[aria-label="收起浮条"]')!.click() })
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(host.querySelector('.dc-panel')?.hasAttribute('hidden')).toBe(true)
    expect(host.querySelector('.dc-island-hint')?.textContent).toBe('Claude 思考中')
    expect(host.querySelector('.dc-presence')?.getAttribute('data-live')).toBe('true')
    // The panel stays mounted while collapsed, so the reply lands where it was streaming.
    await act(async () => { emitAgent({ type: 'turn-end', turnId: 'turn-1', sessionId: 'sess-1', message: { id: 'm1', role: 'assistant', text: '可以这样写。', at: '2026-09-22T12:00:00' } }) })
    expect(host.querySelector('.dc-island-hint')?.textContent).toBe('随手记')
    expect(host.querySelector('.dc-presence')?.getAttribute('data-live')).toBeNull()
    expect(host.querySelector('.dc-session-host .dc-turn-text')?.textContent).toBe('可以这样写。')
    expect(api.createNote).not.toHaveBeenCalled()
  })

  it('expands into the decide stage on a hotkey selection and keeps the outcome on the collapsed pill', async () => {
    vi.useFakeTimers()
    const { bridge, decide, emitDecide, state } = native('top', [], false)
    let answer!: (out: api.DecideOut) => void
    vi.mocked(api.decide).mockReturnValueOnce(new Promise<api.DecideOut>((resolve) => { answer = resolve }))
    const { host } = await mount({ surface: 'top' })
    expect(decide.onSelection).toHaveBeenCalledTimes(1)
    expect(host.querySelector('.dc-decide')).toBeNull()
    expect(host.querySelector('.dc-island-hint')?.textContent).toBe('随手记')
    await act(async () => { emitDecide({ text: '这批货报价比上次高了 8%，要不要压价', source: 'Safari', at: '2026-09-22T12:00:00' }) })
    expect(state().panel).toBe('decide')
    expect(state().expanded).toBe(true)
    expect(host.querySelector('.dc-decide')).toBeTruthy()
    expect(host.querySelector('.dc-decide-text')?.textContent).toBe('这批货报价比上次高了 8%，要不要压价')
    expect(host.querySelector('.dc-decide-source')?.textContent).toBe('来自 Safari')
    expect(host.querySelector('.dc-decide-progress')).toBeTruthy()
    expect(api.decide).toHaveBeenCalledExactlyOnceWith({ text: '这批货报价比上次高了 8%，要不要压价', source: 'Safari', mode: 'auto' }, expect.any(AbortSignal))
    // No tab is the decide stage: every nav button is quiet and the thumb hides in place.
    expect(host.querySelector('nav.dc-nav')?.classList.contains('dc-nav-quiet')).toBe(true)
    expect(host.querySelector('.dc-nav-active')).toBeNull()
    expect(host.querySelector('.dc-capture')).toBeNull()
    expect(host.querySelector('.dc-tasks')).toBeNull()
    // 在想的时候药丸里是那句摘录本身（长到 320 装下它），不是一句「正在拿主意」。
    expect(host.querySelector('.dc-island-hint')?.textContent).toBe('这批货报价比上次高了 8%，要不要压价')
    expect(host.querySelector('.dc-island-hint')?.classList.contains('dc-live-text')).toBe(true)
    expect(host.querySelector('.dc-presence')?.getAttribute('data-live')).toBe('true')
    await act(async () => { answer(decideOut()) })
    expect(host.querySelector('.dc-live-text')).toBeNull()
    expect(host.querySelectorAll('.dc-decide-card')).toHaveLength(3)
    expect([...host.querySelectorAll('.dc-decide-pct')].map((node) => node.textContent)).toEqual(['62%', '28%', '10%'])
    expect(host.querySelector('.dc-island-hint')?.textContent).toBe('随手记')
    expect(host.querySelector('.dc-presence')?.getAttribute('data-live')).toBeNull()
    await act(async () => { host.querySelector<HTMLButtonElement>('[aria-label="收起浮条"]')!.click() })
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(false, 'decide', true)
    expect(host.querySelector('.dc-panel')?.hasAttribute('hidden')).toBe(true)
    expect(host.querySelector('.dc-island-hint')?.textContent).toBe('选项已备好 · 3 个')
    expect(host.querySelector('.dc-presence')?.getAttribute('data-live')).toBe('ready')
    await act(async () => { await vi.advanceTimersByTimeAsync(6000) })
    expect(host.querySelector('.dc-island-hint')?.textContent).toBe('随手记')
    expect(host.querySelector('.dc-presence')?.getAttribute('data-live')).toBeNull()
    // The stage kept its result while collapsed; nothing was written anywhere on its own.
    expect(host.querySelectorAll('.dc-decide-card')).toHaveLength(3)
    expect(api.createNote).not.toHaveBeenCalled()
    expect(readWorkspaceTasks(localStorage.getItem(workspaceStorageKey('companion-test', 'tasks', '2026-09-22')))).toEqual([])
  })

  it('offers 拿主意 in the note AI menu and routes each outcome to to-dos, the session or the note', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-22T12:00:00Z'))
    const { state } = native('top')
    vi.mocked(api.decide).mockResolvedValue(decideOut())
    const { host } = await mount({ surface: 'top' })
    await input(host, '随手记正文', '这批货报价比上次高了 8%，要不要压价')
    const decideFromMenu = async () => {
      await click(host, 'AI 操作')
      const menu = host.querySelector('[role="menu"][aria-label="AI 操作"]')!
      const item = [...menu.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find((button) => button.textContent === '拿主意')!
      expect(item).toBeTruthy()
      await act(async () => { item.click() })
      expect(state().panel).toBe('decide')
      expect(host.querySelector('[role="menu"]')).toBeNull()
      expect(host.querySelectorAll('.dc-decide-card')).toHaveLength(3)
      await act(async () => { host.querySelector<HTMLButtonElement>('.dc-decide-pick')!.click() })
    }
    await decideFromMenu()
    expect(host.querySelector('.dc-decide-source')?.textContent).toBe('来自 笔记')
    expect(api.decide).toHaveBeenCalledExactlyOnceWith({ text: '这批货报价比上次高了 8%，要不要压价', source: '笔记', mode: 'auto' }, expect.any(AbortSignal))
    // 变成待办: today's list grows by one and the stage stays put.
    await click(host, '变成待办')
    expect(readWorkspaceTasks(localStorage.getItem(workspaceStorageKey('companion-test', 'tasks', '2026-09-22'))).map((task) => task.text)).toEqual(['谈价'])
    expect(host.querySelector('.dc-feedback')?.textContent).toContain('已加入待办')
    expect(state().panel).toBe('decide')
    // 问 Claude 展开: the session panel was never mounted, so the text waits and lands in its box once it is.
    await click(host, '问 Claude 展开')
    expect(state().panel).toBe('agent')
    const asked = host.querySelector<HTMLTextAreaElement>('textarea[aria-label="问 Claude"]')?.value || ''
    expect(asked).toContain('题目：这批货要不要压价')
    expect(asked).toContain('1. 谈价（62%） — 上次报价还有余地')
    // The stage stays mounted behind the session (its cards are worth keeping), just hidden.
    expect(host.querySelector('.dc-decide-host')?.hasAttribute('hidden')).toBe(true)
    // 记下来: back to the note, the quote and conclusion follow the existing body, and the island says so.
    await click(host, '随手记')
    await decideFromMenu()
    await click(host, '记下来')
    expect(state().panel).toBe('capture')
    expect(body(host)).toBe('这批货报价比上次高了 8%，要不要压价\n\n> 这批货报价比上次高了 8%，要不要压价\n\n**决定：** 谈价\n上次报价还有余地 [fact-1]')
    expect(host.querySelector('.dc-feedback')?.textContent).toContain('已记到笔记')
    expect(api.createNote).not.toHaveBeenCalled()
    expect(api.composeDesktopNote).not.toHaveBeenCalled()
  })

  it('keeps the saved note and says so when the knowledge base cannot take it', async () => {
    vi.useFakeTimers()
    native('top')
    vi.mocked(api.jobStatus).mockResolvedValueOnce(ingestJob('error', 0, 'OpenAIError: OPENAI_API_KEY is required'))
    const { host } = await mount({ surface: 'top' })
    await input(host, '随手记正文', '抽不进去也要存好')
    await click(host, '存入笔记')
    await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
    expect(body(host)).toBe('')
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('没能进入知识库')
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('OPENAI_API_KEY is required')
    expect(host.querySelector('.dc-island-hint')?.textContent).toBe('随手记')
    // The sync request itself failing reads the same way, and the note is still saved.
    vi.mocked(api.syncNoteToKb).mockRejectedValueOnce(new Error('后端离线'))
    await input(host, '随手记正文', '第二篇')
    await click(host, '存入笔记')
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(api.createNote).toHaveBeenCalledTimes(2)
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('没能进入知识库')
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('后端离线')
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(api.jobStatus).toHaveBeenCalledTimes(1)
  })

  it('restores only this user draft and prevents repeated save shortcuts while pending', async () => {
    native('top')
    localStorage.setItem('memoket.companion.draft.somebody-else', JSON.stringify({ content: '别人私有内容' }))
    localStorage.setItem('memoket.companion.draft.companion-test', JSON.stringify({ title: '', content: '我的草稿' }))
    let complete!: (value: Note) => void
    vi.mocked(api.createNote).mockImplementationOnce(() => new Promise((resolve) => { complete = resolve }))
    const { host } = await mount({ surface: 'top' })
    expect(body(host)).toBe('我的草稿')
    const field = editorView(host).contentDOM
    await act(async () => {
      field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true }))
      field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true }))
    })
    expect(api.createNote).toHaveBeenCalledTimes(1)
    expect(api.composeDesktopNote).not.toHaveBeenCalled()
    await act(async () => { complete(note) })
    expect(localStorage.getItem('memoket.companion.draft.somebody-else')).toContain('别人私有内容')
  })

  it('shares today’s to-dos with the Home window and keeps the next open one on the collapsed pill', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-22T12:00:00Z'))
    const { bridge } = native('top')
    const key = workspaceStorageKey('companion-test', 'tasks', '2026-09-22')
    const otherKey = workspaceStorageKey('someone-else', 'tasks', '2026-09-22')
    localStorage.setItem(key, JSON.stringify([{ id: 't1', text: '核对报价单', done: false }, { id: 't2', text: '回复供应商', done: false }]))
    localStorage.setItem(otherKey, JSON.stringify([{ id: 'o1', text: '别人的事', done: false }]))
    const { host } = await mount({ surface: 'top' })
    expect(host.querySelector('button[aria-label="找一下"]')).toBeNull()
    expect(host.querySelector('nav [aria-label="待办"] .dc-count')?.textContent).toBe('2')
    await click(host, '待办')
    expect([...host.querySelectorAll('.dc-task-text')].map(node => node.textContent)).toEqual(['核对报价单', '回复供应商'])
    await click(host, '完成：核对报价单')
    expect(readWorkspaceTasks(localStorage.getItem(key)).map(task => task.done)).toEqual([true, false])
    expect(host.querySelector('.dc-task-done .dc-task-text')?.textContent).toBe('核对报价单')
    // A Home window writes the same key; the island observes the storage event.
    await act(async () => {
      localStorage.setItem(key, JSON.stringify([{ id: 't1', text: '核对报价单', done: true }, { id: 't2', text: '回复供应商', done: false }, { id: 't3', text: '整理会议纪要', done: false }]))
      window.dispatchEvent(new StorageEvent('storage', { key }))
    })
    expect(host.querySelectorAll('.dc-task')).toHaveLength(3)
    expect(host.querySelector('nav [aria-label="待办"] .dc-count')?.textContent).toBe('2')
    await act(async () => { host.querySelector<HTMLButtonElement>('[aria-label="收起浮条"]')!.click() })
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(host.querySelector('.dc-panel')?.hasAttribute('hidden')).toBe(true)
    expect(host.querySelector('.dc-panel')?.hasAttribute('inert')).toBe(true)
    expect(host.querySelector('.dc-island-hint')?.textContent).toBe('回复供应商')
    expect(host.querySelector('.dc-island-hint .dc-hint-ring')).toBeTruthy()
    expect(host.querySelector<HTMLElement>('.dc-island-trigger')?.style.getPropertyValue('--dc-done')).toBe(String(1 / 3))
    expect(readWorkspaceTasks(localStorage.getItem(otherKey))).toEqual([{ id: 'o1', text: '别人的事', done: false }])
    expect(bridge.openWorkspace).not.toHaveBeenCalled()
  })

  it('previews a multiline clipboard snapshot inline without persistence, then accepts it at the end with Tab', async () => {
    vi.useFakeTimers()
    const { bridge } = native('top')
    const draftKey = 'memoket.companion.draft.companion-test'
    const original = { title: '已有标题', content: '已经写下的正文' }
    const snapshot = '刚复制的材料 A\n第二行需要原样保留'
    localStorage.setItem(draftKey, JSON.stringify(original))
    const persist = vi.spyOn(Storage.prototype, 'setItem')
    vi.mocked(bridge.peekClipboard).mockResolvedValue({ text: snapshot, truncated: false })
    const { host } = await mount({ surface: 'top' })
    const view = editorView(host)
    const field = view.contentDOM
    await act(async () => {
      field.focus()
      view.dispatch({ selection: { anchor: original.content.length, head: original.content.length } })
      field.dispatchEvent(new KeyboardEvent('keyup', { key: 'End', bubbles: true }))
    })
    expect(host.querySelector('.dc-clipboard-candidate')).toBeNull()
    expect(host.querySelector('.dc-draft-ghost')?.getAttribute('aria-hidden')).toBe('true')
    expect(host.querySelector('.dc-draft-ghost-text')?.textContent).toBe(snapshot)
    expect(view.state.doc.toString()).toBe(original.content)
    expect(JSON.parse(localStorage.getItem(draftKey)!)).toEqual(original)
    expect(persist).not.toHaveBeenCalled()
    expect(bridge.addText).not.toHaveBeenCalled()
    expect(bridge.pasteClipboard).not.toHaveBeenCalled()
    expect(api.createNote).not.toHaveBeenCalled()
    // Accept the displayed snapshot, even if the system clipboard has since changed.
    vi.mocked(bridge.peekClipboard).mockResolvedValue({ text: '稍后复制的材料 B', truncated: false })
    const tab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    await act(async () => { field.dispatchEvent(tab) })
    expect(tab.defaultPrevented).toBe(true)
    expect(view.state.doc.toString()).toBe(`${original.content}\n\n${snapshot}`)
    expect(JSON.parse(localStorage.getItem(draftKey)!)).toEqual({ title: original.title, content: view.state.doc.toString() })
    expect(bridge.peekClipboard).toHaveBeenCalledTimes(1)
    expect(host.querySelector('.dc-draft-ghost-text')).toBeNull()
    expect(api.createNote).not.toHaveBeenCalled()
    expect(bridge.addText).not.toHaveBeenCalled()
  })

  it('hides ghost text for a middle caret or selection and leaves Tab navigation intact without replacing text', async () => {
    vi.useFakeTimers()
    const { bridge } = native('top')
    const draftKey = 'memoket.companion.draft.companion-test'
    const original = { title: '保留标题', content: '前文和后文都保留' }
    localStorage.setItem(draftKey, JSON.stringify(original))
    vi.mocked(bridge.peekClipboard).mockResolvedValue({ text: '只在末尾建议的内容', truncated: false })
    const { host } = await mount({ surface: 'top' })
    const view = editorView(host)
    const field = view.contentDOM
    for (const [start, end] of [[2, 2], [2, 5], [2, original.content.length]]) {
      await act(async () => {
        field.focus()
        view.dispatch({ selection: { anchor: start, head: end } })
        field.dispatchEvent(new KeyboardEvent('keyup', { key: 'ArrowLeft', bubbles: true }))
      })
      expect(host.querySelector('.dc-draft-ghost-text')).toBeNull()
      expect(host.querySelector('[aria-label="接入剪贴板内容"]')).toBeNull()
      const tab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
      await act(async () => { field.dispatchEvent(tab) })
      expect(tab.defaultPrevented).toBe(false)
      expect(view.state.doc.toString()).toBe(original.content)
    }
    expect(JSON.parse(localStorage.getItem(draftKey)!)).toEqual(original)
    await act(async () => {
      view.dispatch({ selection: { anchor: original.content.length, head: original.content.length } })
      field.dispatchEvent(new KeyboardEvent('keyup', { key: 'End', bubbles: true }))
    })
    expect(host.querySelector('.dc-draft-ghost-text')?.textContent).toBe('只在末尾建议的内容')
    expect(api.createNote).not.toHaveBeenCalled()
  })

  it('retires the current clipboard ghost when typing starts, without resurfacing it on the next poll', async () => {
    vi.useFakeTimers()
    const { bridge } = native('top')
    vi.mocked(bridge.peekClipboard).mockResolvedValue({ text: '这条建议不应打断写作', truncated: false })
    const { host } = await mount({ surface: 'top' })
    expect(host.querySelector('.dc-draft-ghost-text')?.textContent).toBe('这条建议不应打断写作')
    await input(host, '随手记正文', '我自己开始写了')
    expect(host.querySelector('.dc-draft-ghost-text')).toBeNull()
    await act(async () => { await vi.advanceTimersByTimeAsync(1250) })
    expect(host.querySelector('.dc-draft-ghost-text')).toBeNull()
    expect(body(host)).toBe('我自己开始写了')
    expect(JSON.parse(localStorage.getItem('memoket.companion.draft.companion-test')!)).toEqual({ title: '', content: '我自己开始写了' })
    expect(api.createNote).not.toHaveBeenCalled()
    expect(bridge.addText).not.toHaveBeenCalled()
  })

  it('dismisses only the ghost on Escape without collapsing the island or mutating the note', async () => {
    vi.useFakeTimers()
    const { bridge } = native('top')
    vi.mocked(bridge.peekClipboard).mockResolvedValue({ text: '先不要接入这段内容', truncated: false })
    const { host } = await mount({ surface: 'top' })
    const view = editorView(host)
    const field = view.contentDOM
    expect(host.querySelector('.dc-draft-ghost-text')).toBeTruthy()
    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    await act(async () => { field.focus(); field.dispatchEvent(escape) })
    expect(escape.defaultPrevented).toBe(true)
    expect(host.querySelector('.dc-draft-ghost-text')).toBeNull()
    expect(bridge.setExpanded).not.toHaveBeenCalled()
    expect(view.state.doc.toString()).toBe('')
    expect(localStorage.getItem('memoket.companion.draft.companion-test')).toBeNull()
    expect(api.createNote).not.toHaveBeenCalled()
  })

  it('keeps IME composition in control and never accepts the clipboard on Tab while composing', async () => {
    vi.useFakeTimers()
    const { bridge } = native('top')
    vi.mocked(bridge.peekClipboard).mockResolvedValue({ text: '不要插入中文组词中', truncated: false })
    const { host } = await mount({ surface: 'top' })
    const view = editorView(host)
    const field = view.contentDOM
    await act(async () => { field.focus(); field.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true })) })
    expect(host.querySelector('.dc-draft-ghost-text')).toBeNull()
    const tab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    await act(async () => { field.dispatchEvent(tab) })
    expect(tab.defaultPrevented).toBe(false)
    expect(view.state.doc.toString()).toBe('')
    await input(host, '随手记正文', '中文')
    await act(async () => { field.dispatchEvent(new CompositionEvent('compositionend', { data: '中文', bubbles: true })) })
    expect(host.querySelector('.dc-draft-ghost-text')).toBeNull()
    expect(view.state.doc.toString()).toBe('中文')
    expect(api.createNote).not.toHaveBeenCalled()
  })

  it('preserves normal Tab navigation for modifiers, composition, other fields, and absent suggestions', async () => {
    vi.useFakeTimers()
    const { bridge } = native('top')
    vi.mocked(bridge.peekClipboard).mockResolvedValue({ text: '待接入的材料', truncated: false })
    const { host } = await mount({ surface: 'top' })
    const view = editorView(host)
    const field = view.contentDOM
    for (const modifiers of [{ shiftKey: true }, { altKey: true }, { ctrlKey: true }, { metaKey: true }, { isComposing: true }]) {
      const tab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true, ...modifiers })
      await act(async () => { field.dispatchEvent(tab) })
      expect(tab.defaultPrevented).toBe(false)
    }
    const titleTab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    await act(async () => { host.querySelector('[aria-label="随手记标题"]')!.dispatchEvent(titleTab) })
    expect(titleTab.defaultPrevented).toBe(false)
    await act(async () => { host.querySelector<HTMLButtonElement>('[aria-label="忽略这次剪贴板建议"]')!.click() })
    const plainTab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    await act(async () => { field.dispatchEvent(plainTab) })
    expect(plainTab.defaultPrevented).toBe(false)
    expect(view.state.doc.toString()).toBe('')
    expect(localStorage.getItem('memoket.companion.draft.companion-test')).toBeNull()
    vi.mocked(bridge.peekClipboard).mockResolvedValue({ text: '很长内容的预览片段', truncated: true })
    await act(async () => { await vi.advanceTimersByTimeAsync(1250) })
    expect(host.querySelector('[aria-label="接入剪贴板内容"]')).toBeNull()
    expect(host.querySelector('.dc-draft-ghost-text')?.textContent).toBe('很长内容的预览片段')
    expect(host.textContent).toContain('内容较长，粘贴全文')
    const truncatedTab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    await act(async () => { field.dispatchEvent(truncatedTab) })
    expect(truncatedTab.defaultPrevented).toBe(false)
    expect(view.state.doc.toString()).toBe('')
  })

  it('shows a previously ignored clipboard text again after another copied value was observed', async () => {
    vi.useFakeTimers()
    const { bridge } = native('top')
    vi.mocked(bridge.peekClipboard).mockResolvedValue({ text: '材料 A', truncated: false })
    const { host } = await mount({ surface: 'top' })
    expect(host.querySelector('.dc-draft-ghost-text')?.textContent).toContain('材料 A')
    await act(async () => { host.querySelector<HTMLButtonElement>('[aria-label="忽略这次剪贴板建议"]')!.click() })
    await act(async () => { await vi.advanceTimersByTimeAsync(1200) })
    expect(host.querySelector('.dc-draft-ghost-text')).toBeNull()
    vi.mocked(bridge.peekClipboard).mockResolvedValue({ text: '材料 B', truncated: false })
    await act(async () => { await vi.advanceTimersByTimeAsync(1200) })
    expect(host.querySelector('.dc-draft-ghost-text')?.textContent).toContain('材料 B')
    vi.mocked(bridge.peekClipboard).mockResolvedValue({ text: '材料 A', truncated: false })
    await act(async () => { await vi.advanceTimersByTimeAsync(1200) })
    expect(host.querySelector('.dc-draft-ghost-text')?.textContent).toContain('材料 A')
    expect(body(host)).toBe('')
    expect(localStorage.getItem('memoket.companion.draft.companion-test')).toBeNull()
  })

  it('stops clipboard polling while collapsed and ignores a late response from the previous expansion', async () => {
    vi.useFakeTimers()
    const { bridge } = native('top')
    let completeOldRead!: (value: { text: string; truncated: boolean }) => void
    let completeFreshRead!: (value: { text: string; truncated: boolean }) => void
    vi.mocked(bridge.peekClipboard)
      .mockResolvedValueOnce({ text: '第一次预览', truncated: false })
      .mockImplementationOnce(() => new Promise(resolve => { completeOldRead = resolve }))
      .mockImplementationOnce(() => new Promise(resolve => { completeFreshRead = resolve }))
    const { host } = await mount({ surface: 'top' })
    await act(async () => { await vi.advanceTimersByTimeAsync(1250) })
    expect(bridge.peekClipboard).toHaveBeenCalledTimes(2)
    await act(async () => { host.querySelector<HTMLButtonElement>('[aria-label="收起浮条"]')!.click() })
    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(bridge.peekClipboard).toHaveBeenCalledTimes(2)
    expect(host.querySelector('.dc-draft-ghost-text')).toBeNull()
    await act(async () => { host.querySelector<HTMLButtonElement>('[aria-label="展开桌面口袋"]')!.click() })
    expect(host.querySelector('.dc-draft-ghost-text')).toBeNull()
    await act(async () => { completeOldRead({ text: '已失效的迟到结果', truncated: false }) })
    expect(host.querySelector('.dc-draft-ghost-text')).toBeNull()
    await act(async () => { completeFreshRead({ text: '重新展开后的材料', truncated: false }) })
    expect(host.querySelector('.dc-draft-ghost-text')?.textContent).toContain('重新展开后的材料')
    expect(host.textContent).not.toContain('已失效的迟到结果')
    expect(localStorage.getItem('memoket.companion.draft.companion-test')).toBeNull()
    expect(api.createNote).not.toHaveBeenCalled()
  })

  it('reads native clipboard only after an explicit click and displays the returned real failure', async () => {
    const { bridge, state } = native('shelf')
    vi.mocked(bridge.pasteClipboard).mockResolvedValue({ ok: false, error: '剪贴板里没有可暂存的文字或图片。', state: state() })
    const { host } = await mount({ surface: 'top' })
    expect(bridge.pasteClipboard).not.toHaveBeenCalled()
    await addToShelf(host, '暂存剪贴板')
    expect(bridge.pasteClipboard).toHaveBeenCalledTimes(1)
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('没有可暂存')
    expect(host.querySelectorAll('.dc-item')).toHaveLength(0)
  })

  it('file picker and drop both pass the actual Files to preload; drop captures them before async resize', async () => {
    const { bridge, state } = native('shelf')
    const { host } = await mount({ surface: 'top' })
    const file = new File(['real content'], '实际文件.txt', { type: 'text/plain' })
    const field = host.querySelector<HTMLInputElement>('[aria-label="选择要暂存的文件"]')!
    const openPicker = vi.spyOn(field, 'click')
    await addToShelf(host, '选择文件')
    expect(openPicker).toHaveBeenCalledTimes(1)
    Object.defineProperty(field, 'files', { configurable: true, value: [file] })
    await act(async () => { field.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(bridge.addFiles).toHaveBeenCalledWith([file])
    let finishResize!: (value: CompanionState) => void
    vi.mocked(bridge.setExpanded).mockImplementationOnce(() => new Promise((resolve) => { finishResize = resolve }))
    const transfer = await beginFileDrag(host, [file])
    await act(async () => { host.querySelector('[data-drop-destination="shelf"]')!.dispatchEvent(dragEvent('drop', transfer)) })
    transfer.files = [] as unknown as FileList
    await act(async () => { finishResize(state()) })
    expect(bridge.addFiles).toHaveBeenCalledTimes(2)
    expect(bridge.addFiles).toHaveBeenLastCalledWith([file])
  })

  it('shows two file destinations during external drag, and leaving without a drop changes no feature or data', async () => {
    vi.useFakeTimers()
    const { bridge, state } = native('shelf')
    const { host } = await mount({ surface: 'top' })
    const file = new File(['draft'], '未放下.txt', { type: 'text/plain' })
    const transfer = await beginFileDrag(host, [file])
    const overlay = host.querySelector('[aria-label="选择文件用途"]')!
    expect(overlay.querySelector('[data-drop-destination="note"]')).toBeTruthy()
    expect(overlay.querySelector('[data-drop-destination="shelf"]')).toBeTruthy()
    await act(async () => { overlay.querySelector('[data-drop-destination="note"]')!.dispatchEvent(dragEvent('dragover', transfer)) })
    expect(state().panel).toBe('clipboard')
    expect(api.uploadNoteAttachment).not.toHaveBeenCalled()
    expect(bridge.addFiles).not.toHaveBeenCalled()
    vi.mocked(bridge.isPointerInside!).mockResolvedValue(false)
    await act(async () => {
      host.querySelector('.dc-companion')!.dispatchEvent(dragEvent('dragleave', transfer))
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(host.querySelector('[aria-label="选择文件用途"]')).toBeNull()
    expect(state().panel).toBe('clipboard')
    expect(api.uploadNoteAttachment).not.toHaveBeenCalled()
    expect(bridge.addFiles).not.toHaveBeenCalled()
    expect(api.createNote).not.toHaveBeenCalled()
  })

  it('routes note drops exclusively to uploaded attachments and shows the real image while retaining the editable body', async () => {
    const { bridge, state } = native('shelf')
    const { host } = await mount({ surface: 'top' })
    const image = new File(['image bytes'], '草图.png', { type: 'image/png' })
    const documentFile = new File(['proposal'], '方案.pdf', { type: 'application/pdf' })
    await dropFiles(host, 'note', [image, documentFile])
    expect(state().panel).toBe('capture')
    expect(api.uploadNoteAttachment).toHaveBeenCalledTimes(2)
    expect(api.uploadNoteAttachment).toHaveBeenCalledWith(image, expect.any(AbortSignal))
    expect(api.uploadNoteAttachment).toHaveBeenCalledWith(documentFile, expect.any(AbortSignal))
    expect(bridge.addFiles).not.toHaveBeenCalled()
    expect(api.createNote).not.toHaveBeenCalled()
    const rail = host.querySelector('[aria-label="笔记附件"]')!
    expect(rail).toBeTruthy()
    expect(rail.textContent).toContain('草图.png')
    expect(rail.textContent).toContain('方案.pdf')
    expect(rail.querySelector('img')?.getAttribute('src')).toBe(attachmentAsset(image).url)
    expect(host.querySelector('[aria-label="随手记正文"]')).toBeTruthy()
    expect(host.querySelector('[aria-label="选择文件用途"]')).toBeNull()
  })

  it('routes shelf drops exclusively to native copies and never uploads or adds note attachments', async () => {
    const { bridge, state } = native('top')
    const { host } = await mount({ surface: 'top' })
    await input(host, '随手记正文', '保留当前笔记')
    const file = new File(['contents'], '暂放.txt', { type: 'text/plain' })
    await dropFiles(host, 'shelf', [file])
    expect(state().panel).toBe('clipboard')
    expect(bridge.addFiles).toHaveBeenCalledExactlyOnceWith([file])
    expect(api.uploadNoteAttachment).not.toHaveBeenCalled()
    expect(api.createNote).not.toHaveBeenCalled()
    await click(host, '随手记')
    expect(host.querySelector('[aria-label="笔记附件"]')).toBeNull()
    expect(body(host)).toBe('保留当前笔记')
  })

  it('allows browser note attachments but reports native-only shelf drops without silently rerouting them', async () => {
    const { host } = await mount({ surface: 'top' })
    await click(host, '展开桌面口袋')
    const noteFile = new File(['browser attachment'], '浏览器附件.pdf', { type: 'application/pdf' })
    await dropFiles(host, 'note', [noteFile])
    expect(api.uploadNoteAttachment).toHaveBeenCalledExactlyOnceWith(noteFile, expect.any(AbortSignal))
    expect(host.querySelector('[aria-label="笔记附件"]')?.textContent).toContain(noteFile.name)
    const shelfFile = new File(['native shelf only'], '仅供暂存.txt', { type: 'text/plain' })
    await dropFiles(host, 'shelf', [shelfFile])
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('需要桌面版')
    expect(api.uploadNoteAttachment).toHaveBeenCalledTimes(1)
    expect(api.createNote).not.toHaveBeenCalled()
    await click(host, '随手记')
    expect(host.querySelector('[aria-label="笔记附件"]')?.textContent).toContain(noteFile.name)
    expect(host.querySelector('[aria-label="笔记附件"]')?.textContent).not.toContain(shelfFile.name)
  })

  it('captures note-drop Files before asynchronous native resizing clears the drag payload', async () => {
    const { bridge, state } = native('shelf')
    const { host } = await mount({ surface: 'top' })
    let finishResize!: (value: CompanionState) => void
    vi.mocked(bridge.setExpanded).mockImplementationOnce(() => new Promise(resolve => { finishResize = resolve }))
    const file = new File(['kept'], '异步附件.txt', { type: 'text/plain' })
    const transfer = await beginFileDrag(host, [file])
    await act(async () => { host.querySelector('[data-drop-destination="note"]')!.dispatchEvent(dragEvent('drop', transfer)) })
    transfer.files = [] as unknown as FileList
    await act(async () => { finishResize({ ...state(), panel: 'capture', expanded: true }) })
    expect(api.uploadNoteAttachment).toHaveBeenCalledExactlyOnceWith(file, expect.any(AbortSignal))
    expect(bridge.addFiles).not.toHaveBeenCalled()
    expect(host.querySelector('[aria-label="笔记附件"]')?.textContent).toContain('异步附件.txt')
  })

  it('uses pointer position for a root drop and never sends a file to both destinations', async () => {
    const { bridge } = native('top')
    const { host } = await mount({ surface: 'top' })
    const section = host.querySelector<HTMLElement>('.dc-companion')!
    vi.spyOn(section, 'getBoundingClientRect').mockReturnValue({ left: 100, right: 700, top: 0, bottom: 460, x: 100, y: 0, width: 600, height: 460, toJSON() {} })
    const left = new File(['note'], '左侧.txt', { type: 'text/plain' })
    let transfer = await beginFileDrag(host, [left])
    await act(async () => { section.dispatchEvent(dragEvent('drop', transfer, 250)) })
    expect(api.uploadNoteAttachment).toHaveBeenCalledExactlyOnceWith(left, expect.any(AbortSignal))
    expect(bridge.addFiles).not.toHaveBeenCalled()
    const right = new File(['shelf'], '右侧.txt', { type: 'text/plain' })
    transfer = await beginFileDrag(host, [right])
    await act(async () => { section.dispatchEvent(dragEvent('drop', transfer, 550)) })
    expect(bridge.addFiles).toHaveBeenCalledExactlyOnceWith([right])
    expect(api.uploadNoteAttachment).toHaveBeenCalledTimes(1)
  })

  it('retains successful attachments and current text across a failed upload, and retries only the failed file', async () => {
    native('top')
    const image = new File(['image'], '已上传.png', { type: 'image/png' })
    const failed = new File(['document'], '需重试.pdf', { type: 'application/pdf' })
    vi.mocked(api.uploadNoteAttachment).mockImplementation(async file => {
      if (file === failed) throw new Error('附件上传暂时失败')
      return attachmentAsset(file, assetUrl('retained.png'))
    })
    const { host } = await mount({ surface: 'top' })
    await input(host, '随手记正文', '上传失败也不能丢的正文')
    await dropFiles(host, 'note', [image, failed])
    const rail = host.querySelector('[aria-label="笔记附件"]')!
    expect(rail.textContent).toContain('已上传.png')
    expect(rail.textContent).toContain('需重试.pdf')
    expect(rail.textContent).toContain('失败')
    expect(rail.querySelector('img')?.getAttribute('src')).toBe(assetUrl('retained.png'))
    expect(body(host)).toBe('上传失败也不能丢的正文')
    expect(api.createNote).not.toHaveBeenCalled()
    vi.mocked(api.uploadNoteAttachment).mockResolvedValueOnce(attachmentAsset(failed, assetUrl('retried.pdf')))
    await click(host, '重试附件 需重试.pdf')
    expect(api.uploadNoteAttachment).toHaveBeenCalledTimes(3)
    expect(api.uploadNoteAttachment).toHaveBeenLastCalledWith(failed, expect.any(AbortSignal))
    expect(host.querySelector('[aria-label="笔记附件"]')?.textContent).not.toContain('上传暂时失败')
    expect(host.querySelector('[aria-label="笔记附件"] img')?.getAttribute('src')).toBe(assetUrl('retained.png'))
  })

  it('shows upload progress without saving prematurely, then saves attachment references with the latest text', async () => {
    native('top')
    let complete!: (value: Awaited<ReturnType<typeof api.uploadNoteAttachment>>) => void
    vi.mocked(api.uploadNoteAttachment).mockImplementationOnce(() => new Promise(resolve => { complete = resolve }))
    const { host } = await mount({ surface: 'top' })
    await input(host, '随手记标题', '自己的标题')
    await input(host, '随手记正文', '开始上传时的正文')
    const file = new File(['pending'], '正在上传.pdf', { type: 'application/pdf' })
    await dropFiles(host, 'note', [file])
    expect(host.querySelector('[aria-label="笔记附件"] [role="status"]')?.textContent).toBe('正在附加 正在上传.pdf…')
    await input(host, '随手记正文', '上传期间补上的最新正文')
    await click(host, '存入笔记')
    expect(api.createNote).not.toHaveBeenCalled()
    await act(async () => { complete(attachmentAsset(file, assetUrl('attached.pdf'))) })
    vi.mocked(api.createNote).mockRejectedValueOnce(new Error('保存暂时失败'))
    await click(host, '存入笔记')
    expect(api.createNote).toHaveBeenCalledWith('自己的标题', `上传期间补上的最新正文\n\n[正在上传.pdf](${assetUrl('attached.pdf')})`)
    expect(host.querySelector('[aria-label="笔记附件"]')?.textContent).toContain(file.name)
    expect(body(host)).toBe('上传期间补上的最新正文')
    await click(host, '存入笔记')
    expect(api.createNote).toHaveBeenCalledTimes(2)
    expect(host.querySelector('[aria-label="笔记附件"]')).toBeNull()
    expect(localStorage.getItem('memoket.companion.draft.companion-test')).toBeNull()
  })

  it('keeps attachment uploads alive across features and collapse, and cancellation ignores late upload receipts', async () => {
    vi.useFakeTimers()
    const { bridge } = native('top', [fileItem])
    let complete!: (value: Awaited<ReturnType<typeof api.uploadNoteAttachment>>) => void
    vi.mocked(api.uploadNoteAttachment).mockImplementationOnce(() => new Promise(resolve => { complete = resolve }))
    const { host } = await mount({ surface: 'top' })
    const file = new File(['pending'], '待取消附件.txt', { type: 'text/plain' })
    await dropFiles(host, 'note', [file])
    const signal = vi.mocked(api.uploadNoteAttachment).mock.calls[0][1]!
    expect(signal.aborted).toBe(false)
    await click(host, '暂存架')
    await act(async () => { host.querySelector('.dc-item')!.dispatchEvent(dragEvent('dragstart', { setData: vi.fn() })) })
    expect(bridge.startDrag).toHaveBeenCalledWith('f1')
    await click(host, '收起浮条')
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(host.querySelector('.dc-panel')?.hasAttribute('hidden')).toBe(true)
    expect(signal.aborted).toBe(false)
    await click(host, '展开桌面口袋')
    await click(host, '随手记')
    expect(api.uploadNoteAttachment).toHaveBeenCalledTimes(1)
    await click(host, '取消附件 待取消附件.txt')
    expect(signal.aborted).toBe(true)
    await act(async () => { complete(attachmentAsset(file, assetUrl('late.txt'))) })
    expect(host.querySelector('[aria-label="笔记附件"]')).toBeNull()
    expect(localStorage.getItem('memoket.companion.draft.companion-test')).toBeNull()
    expect(api.createNote).not.toHaveBeenCalled()
  })

  it('restores uploaded attachments without uploading twice and permits saving an attachment-only note', async () => {
    native('top')
    const { host, root } = await mount({ surface: 'top' })
    const file = new File(['image'], '只放图片.png', { type: 'image/png' })
    await dropFiles(host, 'note', [file])
    const stored = JSON.parse(localStorage.getItem('memoket.companion.draft.companion-test')!)
    expect(stored.title).toBe('')
    expect(stored.content).toBe('')
    expect(stored.attachments).toEqual([expect.objectContaining({ name: file.name, kind: 'image', url: attachmentAsset(file).url })])
    await act(async () => { root.unmount() })
    roots.splice(roots.indexOf(root), 1)
    const reopened = await mount({ surface: 'top' })
    expect(api.uploadNoteAttachment).toHaveBeenCalledTimes(1)
    expect(reopened.host.querySelector('[aria-label="笔记附件"] img')?.getAttribute('src')).toBe(attachmentAsset(file).url)
    await click(reopened.host, '存入笔记')
    expect(api.createNote).toHaveBeenCalledWith(expect.any(String), `![${file.name}](${attachmentAsset(file).url})`)
    expect(reopened.host.querySelector('[aria-label="笔记附件"]')).toBeNull()
  })

  it('removes only the chosen attachment from the draft without touching the shelf or saving a note', async () => {
    const { bridge } = native('top')
    const { host } = await mount({ surface: 'top' })
    const first = new File(['first'], '删除这一张.png', { type: 'image/png' })
    const second = new File(['second'], '保留这个.pdf', { type: 'application/pdf' })
    await dropFiles(host, 'note', [first, second])
    await click(host, '移除附件 删除这一张.png')
    expect(host.querySelector('[aria-label="笔记附件"]')?.textContent).not.toContain(first.name)
    expect(host.querySelector('[aria-label="笔记附件"]')?.textContent).toContain(second.name)
    expect(JSON.parse(localStorage.getItem('memoket.companion.draft.companion-test')!).attachments).toHaveLength(1)
    expect(bridge.remove).not.toHaveBeenCalled()
    expect(api.createNote).not.toHaveBeenCalled()
  })

  it('native drag-out uses the item id; removing calls only remove and keeps failure state visible', async () => {
    const { bridge, state } = native('shelf', [fileItem])
    const { host } = await mount({ surface: 'top' })
    await act(async () => { host.querySelector('.dc-item')!.dispatchEvent(dragEvent('dragstart', { setData: vi.fn() })) })
    expect(bridge.startDrag).toHaveBeenCalledWith('f1')
    vi.mocked(bridge.remove).mockResolvedValueOnce({ ok: false, error: '暂存清单无法写入。', state: state() })
    const remove = host.querySelector<HTMLButtonElement>('[aria-label="从暂存架移除 报价.pdf"]')!
    await act(async () => { remove.click() })
    expect(host.querySelectorAll('.dc-item')).toHaveLength(1)
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('无法写入')
    await act(async () => { remove.click() })
    expect(host.querySelectorAll('.dc-item')).toHaveLength(0)
    expect(bridge.open).not.toHaveBeenCalled()
    expect(bridge.reveal).not.toHaveBeenCalled()
  })

  it('missing paths cannot open or drag, and window permission failures do not fabricate candidates', async () => {
    const { bridge } = native('shelf', [{ ...fileItem, missing: true }])
    vi.mocked(bridge.listWindows).mockResolvedValueOnce({ ok: false, error: '需要屏幕录制权限才能读取窗口预览。' })
    const { host } = await mount({ surface: 'top' })
    expect(host.querySelector('.dc-item')?.getAttribute('draggable')).toBe('false')
    expect(host.querySelector<HTMLButtonElement>('.dc-item-actions button')?.disabled).toBe(true)
    expect(host.textContent).toContain('原文件已移动或无法访问')
    await addToShelf(host, '暂存窗口')
    expect(bridge.listWindows).toHaveBeenCalledTimes(1)
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('需要屏幕录制权限')
    expect(host.querySelectorAll('.dc-window-choice')).toHaveLength(0)
  })

  it('browser preview opens notes first without faking native items or clipboard support', async () => {
    const expanded = vi.fn()
    const { host, root } = await mount({ surface: 'top', onExpandedChange: expanded })
    expect(host.querySelector('.dc-panel')?.hasAttribute('hidden')).toBe(true)
    expect(host.querySelector('.dc-panel')?.hasAttribute('inert')).toBe(true)
    await click(host, '展开桌面口袋')
    expect(host.querySelector('[aria-label="随手记正文"]')).toBeTruthy()
    expect(host.querySelector('nav button')?.getAttribute('aria-label')).toBe('随手记')
    expect(host.querySelectorAll('.dc-item')).toHaveLength(0)
    await act(async () => { root.render(<DesktopCompanion surface="top" onExpandedChange={expanded} openRequested={1} />) })
    expect(expanded).toHaveBeenLastCalledWith(true)
    await click(host, '暂存架')
    await click(host, '添加暂存内容')
    const menu = host.querySelector('[role="menu"][aria-label="添加暂存内容"]')!
    const clipboard = [...menu.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find((button) => button.textContent?.includes('暂存剪贴板'))!
    expect(clipboard.disabled).toBe(true)
    expect(clipboard.title).toContain('桌面版')
    expect(host.querySelectorAll('.dc-item')).toHaveLength(0)
  })

  it('keeps shelf controls compact and exposes native additions through the add menu, without an AI entry', async () => {
    const { bridge } = native('shelf', [fileItem])
    const { host } = await mount({ surface: 'top' })
    expect(host.querySelector('[aria-label="添加暂存内容"]')).toBeTruthy()
    expect(host.querySelector('[aria-label="搜索暂存内容"]')).toBeTruthy()
    expect(host.querySelector('[aria-label="查找暂存内容"]')).toBeNull()
    expect(host.querySelector('[aria-label="要暂存的文字或链接"]')).toBeNull()
    expect(host.querySelector('[aria-label="暂存类型"]')).toBeNull()
    expect(host.querySelector('[aria-label="AI 操作"]')).toBeNull()
    expect(host.querySelector('button[aria-label="整理成笔记"]')).toBeNull()
    expect(host.querySelector('[role="menu"]')).toBeNull()
    await click(host, '添加暂存内容')
    const menu = host.querySelector('[role="menu"][aria-label="添加暂存内容"]')!
    expect([...menu.querySelectorAll('[role="menuitem"]')].map((item) => item.textContent?.trim())).toEqual(['选择文件', '暂存剪贴板', '暂存窗口', '文字或链接'])
    expect(bridge.addFiles).not.toHaveBeenCalled()
    expect(bridge.pasteClipboard).not.toHaveBeenCalled()
    expect(bridge.listWindows).not.toHaveBeenCalled()
    expect(bridge.addText).not.toHaveBeenCalled()
    expect(api.desktopAIStatus).not.toHaveBeenCalled()
  })

  it('shows shelf search only on request and matches real paths, text and URLs', async () => {
    native('shelf', [
      { ...fileItem, path: '/projects/发票/报价.pdf' },
      { id: 't1', kind: 'text', title: '待办', text: '下午处理发票', createdAt: '2026-09-22' },
      { id: 'l1', kind: 'link', title: '项目资料', url: 'https://example.com/release', createdAt: '2026-09-22' },
    ])
    const { host } = await mount({ surface: 'top' })
    expect(host.querySelector('[aria-label="查找暂存内容"]')).toBeNull()
    await click(host, '搜索暂存内容')
    await input(host, '查找暂存内容', '发票')
    expect(host.querySelectorAll('.dc-item')).toHaveLength(2)
    await input(host, '查找暂存内容', '不存在的材料')
    expect(host.querySelectorAll('.dc-item')).toHaveLength(0)
    await click(host, '查看全部')
    expect(host.querySelectorAll('.dc-item')).toHaveLength(3)
    await input(host, '查找暂存内容', 'release')
    expect(host.querySelectorAll('.dc-item')).toHaveLength(1)
    expect(host.querySelector('.dc-item')?.textContent).toContain('项目资料')
  })

  it('opens text entry from the add menu, preserves a failed submission and hides it only after success', async () => {
    const { bridge, state } = native('shelf', [fileItem])
    const { host } = await mount({ surface: 'top' })
    await addToShelf(host, '文字或链接')
    expect(host.querySelector('[role="menu"]')).toBeNull()
    await input(host, '要暂存的文字或链接', '稍后回复这个链接 https://example.com')
    vi.mocked(bridge.addText).mockResolvedValueOnce({ ok: false, error: '暂存失败，请重试。', state: state() })
    await click(host, '暂存文字')
    expect(bridge.addText).toHaveBeenCalledWith('稍后回复这个链接 https://example.com')
    expect(host.querySelector<HTMLInputElement>('[aria-label="要暂存的文字或链接"]')?.value).toBe('稍后回复这个链接 https://example.com')
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('暂存失败')
    const text: CompanionItem = { id: 'new-text', kind: 'text', title: '稍后回复', text: '稍后回复这个链接 https://example.com', createdAt: '2026-09-23' }
    vi.mocked(bridge.addText).mockResolvedValueOnce({ ok: true, state: { ...state(), items: [...state().items, text] } })
    await click(host, '暂存文字')
    expect(host.querySelector('[aria-label="要暂存的文字或链接"]')).toBeNull()
    expect(host.querySelectorAll('.dc-item')).toHaveLength(2)
    expect(host.querySelector('.dc-item')?.textContent).toContain(text.title)
    expect(host.querySelector('.dc-item-arrived')?.textContent).toContain(text.title)
    expect(api.createNote).not.toHaveBeenCalled()
  })

  it('reveals newly added files despite an old query, without retaining the large empty drop zone', async () => {
    const { bridge, state } = native('shelf', [
      fileItem,
      { id: 't1', kind: 'text', title: '待办', text: '处理旧材料', createdAt: '2026-09-22' },
      { id: 'l1', kind: 'link', title: '项目网址', url: 'https://example.com', createdAt: '2026-09-22' },
    ])
    const { host } = await mount({ surface: 'top' })
    expect(host.querySelector('.dc-drop-zone')).toBeNull()
    await input(host, '查找暂存内容', '待办')
    expect(host.querySelectorAll('.dc-item')).toHaveLength(1)
    const list = host.querySelector<HTMLElement>('[aria-label="已暂存的内容"]')!
    list.scrollTop = 100
    const added: CompanionItem = { ...fileItem, id: 'new-file', title: '新方案.pdf', path: '/tmp/新方案.pdf', createdAt: '2026-09-23' }
    vi.mocked(bridge.addFiles).mockResolvedValueOnce({ ok: true, state: { ...state(), items: [...state().items, added] } })
    const file = new File(['new content'], added.title, { type: 'application/pdf' })
    const picker = host.querySelector<HTMLInputElement>('input[type="file"]')!
    Object.defineProperty(picker, 'files', { configurable: true, value: [file] })
    await act(async () => { picker.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(bridge.addFiles).toHaveBeenCalledWith([file])
    expect(host.querySelector<HTMLInputElement>('[aria-label="查找暂存内容"]')?.value).toBe('')
    expect(host.querySelector('[aria-label="暂存类型"]')).toBeNull()
    expect(host.querySelectorAll('.dc-item')).toHaveLength(4)
    expect(host.querySelector('.dc-item')?.textContent).toContain(added.title)
    expect(host.querySelector('.dc-item-arrived')?.textContent).toContain(added.title)
    expect(list.scrollTop).toBe(0)
    expect(host.querySelector('.dc-count')?.textContent).toBe('4')
    expect(host.querySelector('.dc-drop-zone')).toBeNull()
  })

  it('keeps the persistence failure visible when a successful ingest only added the item in memory', async () => {
    const { bridge, state } = native('shelf')
    const storageError = '暂存清单写入失败，当前内容尚未持久保存。'
    const item: CompanionItem = { id: 'unsaved-text', kind: 'text', title: '待处理资料', text: '明天继续核对', createdAt: '2026-09-22' }
    vi.mocked(bridge.pasteClipboard).mockResolvedValueOnce({ ok: true, state: { ...state(), items: [item], storageError } })
    const { host } = await mount({ surface: 'top' })
    await addToShelf(host, '暂存剪贴板')
    expect(host.querySelector('.dc-item')?.textContent).toContain(item.text)
    expect(host.querySelector('[role="alert"]')?.textContent).toContain(storageError)
    expect(host.querySelector('.dc-feedback')?.textContent).not.toContain('已暂存')
    await act(async () => { host.querySelector<HTMLButtonElement>('.dc-item-actions button')!.click() })
    expect(bridge.copy).toHaveBeenCalledWith(item.id)
    expect(host.querySelector('[role="alert"]')?.textContent).toContain(storageError)
    expect(host.querySelector('.dc-feedback')?.textContent).not.toContain('已复制')
  })

  it('reveals an existing file after a duplicate add without creating a new item or leaving the old query active', async () => {
    const { bridge, state } = native('shelf', [
      fileItem,
      { id: 't1', kind: 'text', title: '待办', text: '处理旧材料', createdAt: '2026-09-22' },
    ])
    const { host } = await mount({ surface: 'top' })
    await input(host, '查找暂存内容', '待办')
    expect(host.querySelectorAll('.dc-item')).toHaveLength(1)
    expect(host.querySelector('.dc-item')?.textContent).not.toContain(fileItem.title)
    const list = host.querySelector<HTMLElement>('[aria-label="已暂存的内容"]')!
    list.scrollTop = 100
    // Native deduplication succeeds but returns precisely the same item ids.
    vi.mocked(bridge.addFiles).mockResolvedValueOnce({ ok: true, state: state() })
    const file = new File(['same file'], fileItem.title, { type: 'application/pdf' })
    const picker = host.querySelector<HTMLInputElement>('input[type="file"]')!
    Object.defineProperty(picker, 'files', { configurable: true, value: [file] })
    await act(async () => { picker.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(bridge.addFiles).toHaveBeenCalledWith([file])
    expect(host.querySelector<HTMLInputElement>('[aria-label="查找暂存内容"]')?.value).toBe('')
    expect(host.querySelector('[aria-label="暂存类型"]')).toBeNull()
    expect(host.querySelectorAll('.dc-item')).toHaveLength(2)
    expect(list.textContent).toContain(fileItem.title)
    expect(list.scrollTop).toBe(0)
    expect(host.querySelector('.dc-count')?.textContent).toBe('2')
    expect(host.querySelector('.dc-item-arrived')).toBeNull()
    expect(host.querySelector('.dc-feedback[role="status"]')?.textContent).toContain('已在暂存架中，已显示全部内容。')
  })

  it('collapses an idle shelf on pointer leave but keeps a pinned shelf open', async () => {
    vi.useFakeTimers()
    const { bridge, emit, state } = native('shelf')
    const { host } = await mount({ surface: 'top' })
    const leave = () => host.querySelector('section')!.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body }))
    await act(async () => { leave(); await vi.advanceTimersByTimeAsync(450) })
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(false, 'clipboard', false)
    await act(async () => { emit({ ...state(), expanded: true }) })
    const pin = host.querySelector<HTMLButtonElement>('[aria-label="固定展开"]')!
    await act(async () => { pin.click() })
    expect(pin.getAttribute('aria-pressed')).toBe('true')
    vi.mocked(bridge.setExpanded).mockClear()
    await act(async () => { leave(); await vi.advanceTimersByTimeAsync(450) })
    expect(bridge.setExpanded).not.toHaveBeenCalled()
    expect(host.querySelector('.dc-panel')).toBeTruthy()
  })

  it('hover can be interrupted, expands without focus, and keeps an inert panel for its exit animation', async () => {
    vi.useFakeTimers()
    vi.spyOn(document, 'hasFocus').mockReturnValue(true)
    const { bridge, emit, state } = native('top', [], false)
    vi.mocked(bridge.setExpanded).mockImplementation(async (expanded, panel) => {
      const next = { ...state(), expanded, panel: panel || state().panel }
      emit(next)
      return next
    })
    const { host } = await mount({ surface: 'top' })
    const section = host.querySelector('section')!
    const enter = () => section.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, relatedTarget: document.body }))
    const leave = () => section.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body }))
    await act(async () => { enter(); await vi.advanceTimersByTimeAsync(100); leave(); await vi.advanceTimersByTimeAsync(100) })
    expect(bridge.setExpanded).not.toHaveBeenCalled()
    await act(async () => { enter(); await vi.advanceTimersByTimeAsync(120) })
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(true, 'capture', false)
    expect(document.activeElement).not.toBe(host.querySelector('textarea'))
    await act(async () => { await vi.advanceTimersByTimeAsync(800) })
    vi.mocked(bridge.settleCollapsed).mockClear()
    await act(async () => { leave(); await vi.advanceTimersByTimeAsync(260) })
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(false, 'capture', false)
    expect(host.querySelector('.dc-stage')?.getAttribute('aria-hidden')).toBe('true')
    expect(host.querySelector('.dc-stage')?.hasAttribute('inert')).toBe(true)
    await act(async () => { await vi.advanceTimersByTimeAsync(180) })
    expect(host.querySelector('.dc-panel')).toBeTruthy()
    expect(bridge.settleCollapsed).not.toHaveBeenCalled()
    await act(async () => { await vi.advanceTimersByTimeAsync(800) })
    expect(host.querySelector('.dc-panel')?.hasAttribute('hidden')).toBe(true)
    expect(host.querySelector('.dc-panel')?.hasAttribute('inert')).toBe(true)
    expect(bridge.settleCollapsed).toHaveBeenCalledTimes(1)
  })

  it('collapses a focused editor with a selected draft on pointer leave and preserves both fields on reopening', async () => {
    vi.useFakeTimers()
    vi.spyOn(document, 'hasFocus').mockReturnValue(true)
    const { bridge } = native('top')
    const { host } = await mount({ surface: 'top' })
    await input(host, '随手记标题', '刚粘贴的标题')
    await input(host, '随手记正文', '系统粘贴后尚未保存的正文')
    const bodyView = editorView(host)
    bodyView.focus()
    bodyView.dispatch({ selection: { anchor: 0, head: 4 } })
    expect(document.activeElement).toBe(bodyView.contentDOM)
    await act(async () => {
      host.querySelector('section')!.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body }))
      await vi.advanceTimersByTimeAsync(259)
    })
    expect(bridge.setExpanded).not.toHaveBeenCalled()
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(false, 'capture', false)
    expect(host.querySelector('.dc-stage')?.getAttribute('aria-hidden')).toBe('true')
    expect(JSON.parse(localStorage.getItem('memoket.companion.draft.companion-test')!)).toEqual({ title: '刚粘贴的标题', content: '系统粘贴后尚未保存的正文' })
    await act(async () => { host.querySelector<HTMLButtonElement>('[aria-label="展开桌面口袋"]')!.click() })
    expect(host.querySelector<HTMLInputElement>('[aria-label="随手记标题"]')?.value).toBe('刚粘贴的标题')
    expect(body(host)).toBe('系统粘贴后尚未保存的正文')
    expect(api.createNote).not.toHaveBeenCalled()
  })

  it('collapses unsubmitted shelf text after blur and preserves it without submitting on reopening', async () => {
    vi.useFakeTimers()
    const hasFocus = vi.spyOn(document, 'hasFocus').mockReturnValue(true)
    const { bridge } = native('shelf')
    const { host } = await mount({ surface: 'top' })
    await addToShelf(host, '文字或链接')
    await input(host, '要暂存的文字或链接', '还没点暂存的文字')
    hasFocus.mockReturnValue(false)
    await act(async () => { window.dispatchEvent(new Event('blur')); await vi.advanceTimersByTimeAsync(260) })
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(false, 'clipboard', false)
    expect(host.querySelector('.dc-stage')?.getAttribute('aria-hidden')).toBe('true')
    expect(bridge.addText).not.toHaveBeenCalled()
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(host.querySelector('.dc-panel')?.hasAttribute('hidden')).toBe(true)
    expect(host.querySelector('.dc-panel')?.hasAttribute('inert')).toBe(true)
    await act(async () => { host.querySelector<HTMLButtonElement>('[aria-label="展开桌面口袋"]')!.click() })
    expect(host.querySelector<HTMLInputElement>('[aria-label="要暂存的文字或链接"]')?.value).toBe('还没点暂存的文字')
  })

  it('does not treat an unrelated document selection as a reason to keep the shelf open', async () => {
    vi.useFakeTimers()
    const { bridge } = native('shelf')
    const { host } = await mount({ surface: 'top' })
    const outside = document.createElement('p')
    outside.textContent = '其他区域仍然选中的文字'
    document.body.append(outside)
    const range = document.createRange()
    range.selectNodeContents(outside)
    window.getSelection()!.removeAllRanges()
    window.getSelection()!.addRange(range)
    expect(window.getSelection()?.toString()).toBe(outside.textContent)
    await act(async () => {
      host.querySelector('section')!.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: outside }))
      await vi.advanceTimersByTimeAsync(260)
    })
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(false, 'clipboard', false)
    window.getSelection()!.removeAllRanges()
  })

  it('retries a pending pointer-leave collapse after a native operation completes without another mouse event', async () => {
    vi.useFakeTimers()
    const { bridge } = native('shelf', [fileItem])
    let finish!: (result: { ok: boolean }) => void
    vi.mocked(bridge.reveal).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const { host } = await mount({ surface: 'top' })
    await click(host, '位置')
    expect(bridge.reveal).toHaveBeenCalledWith(fileItem.id)
    await act(async () => {
      host.querySelector('section')!.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body }))
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(bridge.setExpanded).not.toHaveBeenCalled()
    await act(async () => { finish({ ok: true }); await vi.advanceTimersByTimeAsync(520) })
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(false, 'clipboard', false)
  })

  it('cancels a blocked leave when the pointer returns before the native operation completes', async () => {
    vi.useFakeTimers()
    const { bridge } = native('shelf', [fileItem])
    let finish!: (result: { ok: boolean }) => void
    vi.mocked(bridge.reveal).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const { host } = await mount({ surface: 'top' })
    const section = host.querySelector('section')!
    await click(host, '位置')
    await act(async () => {
      section.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body }))
      await vi.advanceTimersByTimeAsync(520)
      section.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, relatedTarget: document.body }))
      finish({ ok: true })
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(bridge.setExpanded).not.toHaveBeenCalled()
    await act(async () => {
      section.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body }))
      await vi.advanceTimersByTimeAsync(260)
    })
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(false, 'clipboard', false)
  })

  it('retries the pending leave after the file chooser is canceled without saving an item', async () => {
    vi.useFakeTimers()
    const { bridge } = native('shelf')
    const { host } = await mount({ surface: 'top' })
    await addToShelf(host, '选择文件')
    await act(async () => {
      host.querySelector('section')!.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body }))
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(bridge.setExpanded).not.toHaveBeenCalled()
    await act(async () => {
      host.querySelector('input[type="file"]')!.dispatchEvent(new Event('cancel'))
      await vi.advanceTimersByTimeAsync(520)
    })
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(false, 'clipboard', false)
    expect(bridge.addFiles).not.toHaveBeenCalled()
  })

  it('clears the file-destination overlay on pointer exit and completes the leave collapse without waiting for dragleave', async () => {
    vi.useFakeTimers()
    const { bridge } = native('shelf')
    const { host } = await mount({ surface: 'top' })
    const section = host.querySelector('section')!
    await beginFileDrag(host, [new File(['not dropped'], '未投放.txt')])
    vi.mocked(bridge.isPointerInside!).mockResolvedValue(false)
    await act(async () => {
      section.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body }))
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(host.querySelector('[aria-label="选择文件用途"]')).toBeNull()
    expect(host.querySelector('.dc-panel')?.getAttribute('aria-hidden')).toBe('true')
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(false, 'clipboard', false)
    expect(bridge.addFiles).not.toHaveBeenCalled()
    expect(api.uploadNoteAttachment).not.toHaveBeenCalled()
  })

  it('keeps file destinations during child transitions and cancels on a real boundary exit even when pinned', async () => {
    vi.useFakeTimers()
    const { bridge } = native('top')
    const { host } = await mount({ surface: 'top' })
    await click(host, '固定展开')
    const section = host.querySelector<HTMLElement>('.dc-companion')!
    vi.spyOn(section, 'getBoundingClientRect').mockReturnValue({ left: 100, right: 700, top: 0, bottom: 460, x: 100, y: 0, width: 600, height: 460, toJSON() {} })
    const transfer = await beginFileDrag(host, [new File(['kept'], '仍在拖动.txt')])
    const left = host.querySelector<HTMLElement>('[data-drop-destination="note"]')!
    const right = host.querySelector<HTMLElement>('[data-drop-destination="shelf"]')!
    await act(async () => {
      left.dispatchEvent(dragEvent('dragleave', transfer, 450, { relatedTarget: right, clientY: 100 }))
      await vi.advanceTimersByTimeAsync(300)
    })
    expect(host.querySelector('[aria-label="选择文件用途"]')).toBeTruthy()
    vi.mocked(bridge.isPointerInside!).mockResolvedValue(false)
    await act(async () => {
      section.dispatchEvent(dragEvent('dragleave', transfer, 750, { relatedTarget: document.body, clientY: 100 }))
      await vi.advanceTimersByTimeAsync(300)
    })
    expect(host.querySelector('[aria-label="选择文件用途"]')).toBeNull()
    expect(host.querySelector('[aria-label="固定展开"]')?.getAttribute('aria-pressed')).toBe('true')
    expect(host.querySelector('.dc-panel')?.getAttribute('aria-hidden')).toBe('false')
    expect(bridge.addFiles).not.toHaveBeenCalled()
    expect(api.uploadNoteAttachment).not.toHaveBeenCalled()
  })

  it('expires a root dragleave with stale inside coordinates, but cancels that expiry when dragover returns', async () => {
    vi.useFakeTimers()
    const { bridge } = native('top')
    delete bridge.isPointerInside
    const { host } = await mount({ surface: 'top' })
    const section = host.querySelector<HTMLElement>('.dc-companion')!
    vi.spyOn(section, 'getBoundingClientRect').mockReturnValue({ left: 100, right: 700, top: 0, bottom: 460, x: 100, y: 0, width: 600, height: 460, toJSON() {} })
    const transfer = await beginFileDrag(host, [new File(['outside'], '坐标过期.txt')])
    await act(async () => {
      section.dispatchEvent(dragEvent('dragleave', transfer, 300, { clientY: 100 }))
      await vi.advanceTimersByTimeAsync(40)
    })
    expect(host.querySelector('[aria-label="选择文件用途"]')).toBeTruthy()
    await act(async () => {
      section.dispatchEvent(dragEvent('dragover', transfer, 320, { clientY: 120 }))
      await vi.advanceTimersByTimeAsync(100)
    })
    expect(host.querySelector('[aria-label="选择文件用途"]')).toBeTruthy()
    await act(async () => {
      section.dispatchEvent(dragEvent('dragleave', transfer, 320, { clientY: 120 }))
      await vi.advanceTimersByTimeAsync(100)
    })
    expect(host.querySelector('[aria-label="选择文件用途"]')).toBeNull()
    expect(api.uploadNoteAttachment).not.toHaveBeenCalled()
  })

  it.each(['dragend', 'drop', 'pointerup', 'escape'] as const)('clears abandoned file destinations after a global %s without storing anything', async (exit) => {
    vi.useFakeTimers()
    const { bridge } = native('top')
    const { host } = await mount({ surface: 'top' })
    await click(host, '固定展开')
    const transfer = await beginFileDrag(host, [new File(['cancelled'], '取消投放.txt')])
    await act(async () => {
      if (exit === 'escape') window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
      else if (exit === 'pointerup') window.dispatchEvent(new MouseEvent('pointermove', { bubbles: true, buttons: 0 }))
      else window.dispatchEvent(dragEvent(exit, transfer))
      await vi.advanceTimersByTimeAsync(300)
    })
    expect(host.querySelector('[aria-label="选择文件用途"]')).toBeNull()
    expect(host.querySelector('.dc-panel')?.getAttribute('aria-hidden')).toBe('false')
    expect(bridge.addFiles).not.toHaveBeenCalled()
    expect(api.uploadNoteAttachment).not.toHaveBeenCalled()
    expect(api.createNote).not.toHaveBeenCalled()
  })

  it('polls native pointer presence only during file drags and releases an orphan overlay when the pointer is outside', async () => {
    vi.useFakeTimers()
    const { bridge } = native('top')
    vi.mocked(bridge.isPointerInside!).mockResolvedValue(false)
    const { host } = await mount({ surface: 'top' })
    await act(async () => { await vi.advanceTimersByTimeAsync(500) })
    expect(bridge.isPointerInside).not.toHaveBeenCalled()
    await click(host, '固定展开')
    await beginFileDrag(host, [new File(['outside'], '原生检测.txt')])
    await act(async () => { await vi.advanceTimersByTimeAsync(160) })
    expect(bridge.isPointerInside).toHaveBeenCalled()
    expect(host.querySelector('[aria-label="选择文件用途"]')).toBeNull()
    const polls = vi.mocked(bridge.isPointerInside!).mock.calls.length
    await act(async () => { await vi.advanceTimersByTimeAsync(600) })
    expect(bridge.isPointerInside).toHaveBeenCalledTimes(polls)
    expect(bridge.addFiles).not.toHaveBeenCalled()
    expect(api.uploadNoteAttachment).not.toHaveBeenCalled()
  })

  it('ignores an old native outside reply after a fresh dragover and after a new drag session', async () => {
    vi.useFakeTimers()
    const { bridge } = native('top')
    let oldReply!: (inside: boolean) => void
    vi.mocked(bridge.isPointerInside!).mockImplementationOnce(() => new Promise(resolve => { oldReply = resolve }))
    const { host } = await mount({ surface: 'top' })
    const transfer = await beginFileDrag(host, [new File(['drag'], '继续拖动.txt')])
    await act(async () => { await vi.advanceTimersByTimeAsync(160) })
    await act(async () => {
      host.querySelector('.dc-companion')!.dispatchEvent(dragEvent('dragover', transfer))
      oldReply(false)
    })
    expect(host.querySelector('[aria-label="选择文件用途"]')).toBeTruthy()
    await act(async () => { window.dispatchEvent(new Event('dragend')) })
    let previousSession!: (inside: boolean) => void
    vi.mocked(bridge.isPointerInside!).mockImplementationOnce(() => new Promise(resolve => { previousSession = resolve }))
    await beginFileDrag(host, [new File(['old'], '旧拖动.txt')])
    await act(async () => { await vi.advanceTimersByTimeAsync(160) })
    await act(async () => { window.dispatchEvent(new Event('dragend')) })
    await beginFileDrag(host, [new File(['new'], '新拖动.txt')])
    await act(async () => { previousSession(false) })
    expect(host.querySelector('[aria-label="选择文件用途"]')).toBeTruthy()
    expect(bridge.addFiles).not.toHaveBeenCalled()
    expect(api.uploadNoteAttachment).not.toHaveBeenCalled()
  })

  it('does not let a late native outside reply undo a successful note drop', async () => {
    vi.useFakeTimers()
    const { bridge } = native('shelf')
    let reply!: (inside: boolean) => void
    vi.mocked(bridge.isPointerInside!).mockImplementationOnce(() => new Promise(resolve => { reply = resolve }))
    const { host } = await mount({ surface: 'top' })
    const file = new File(['document'], '已经附加.pdf', { type: 'application/pdf' })
    const transfer = await beginFileDrag(host, [file])
    await act(async () => { await vi.advanceTimersByTimeAsync(160) })
    await act(async () => { host.querySelector('[data-drop-destination="note"]')!.dispatchEvent(dragEvent('drop', transfer)) })
    const transitions = vi.mocked(bridge.setExpanded).mock.calls.length
    await act(async () => { reply(false); await vi.advanceTimersByTimeAsync(500) })
    expect(host.querySelector('[aria-label="选择文件用途"]')).toBeNull()
    expect(host.querySelector('[aria-label="笔记附件"]')?.textContent).toContain(file.name)
    expect(host.querySelector('.dc-panel')?.getAttribute('aria-hidden')).toBe('false')
    expect(bridge.setExpanded).toHaveBeenCalledTimes(transitions)
    expect(api.uploadNoteAttachment).toHaveBeenCalledExactlyOnceWith(file, expect.any(AbortSignal))
    expect(bridge.addFiles).not.toHaveBeenCalled()
  })

  it('switches features on navigation hover without focus or clicks and preserves the current draft', async () => {
    vi.useFakeTimers()
    vi.spyOn(document, 'hasFocus').mockReturnValue(true)
    const { bridge } = native('top')
    const { host } = await mount({ surface: 'top' })
    await input(host, '随手记标题', '悬停切页前的标题')
    await input(host, '随手记正文', '切换功能时保留这段草稿')
    const outside = document.createElement('input')
    document.body.append(outside)
    outside.focus()
    await hoverNav(host, '暂存架')
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(true, 'clipboard', false)
    expect(host.querySelector('.dc-shelf-panel')).toBeTruthy()
    expect(document.activeElement).toBe(outside)
    const calls = vi.mocked(bridge.setExpanded).mock.calls.length
    await hoverNav(host, '暂存架')
    expect(bridge.setExpanded).toHaveBeenCalledTimes(calls)
    await hoverNav(host, '待办')
    expect(host.querySelector('.dc-tasks')).toBeTruthy()
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(true, 'tasks', false)
    await hoverNav(host, '随手记')
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(true, 'capture', false)
    expect(document.activeElement).toBe(outside)
    expect(host.querySelector<HTMLInputElement>('[aria-label="随手记标题"]')?.value).toBe('悬停切页前的标题')
    expect(body(host)).toBe('切换功能时保留这段草稿')
    await click(host, '待办')
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(true, 'tasks', true)
    expect(api.createNote).not.toHaveBeenCalled()
  })

  it('honors a hover back to notes before the earlier shelf IPC finishes and ignores its late response', async () => {
    vi.useFakeTimers()
    vi.spyOn(document, 'hasFocus').mockReturnValue(true)
    const { bridge, state } = native('top')
    const { host } = await mount({ surface: 'top' })
    await input(host, '随手记正文', '快速掠过导航也不能丢失这段正文')
    const outside = document.createElement('input')
    document.body.append(outside)
    outside.focus()
    let finishShelf!: (next: CompanionState) => void
    let finishNotes!: (next: CompanionState) => void
    vi.mocked(bridge.setExpanded)
      .mockImplementationOnce(() => new Promise(resolve => { finishShelf = resolve }))
      .mockImplementationOnce(() => new Promise(resolve => { finishNotes = resolve }))
    await hoverNav(host, '暂存架')
    expect(bridge.setExpanded).toHaveBeenCalledExactlyOnceWith(true, 'clipboard', false)
    // The acknowledged panel is still capture, but the pending intent is shelf.
    await hoverNav(host, '随手记')
    expect(bridge.setExpanded).toHaveBeenCalledTimes(2)
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(true, 'capture', false)
    await act(async () => {
      finishNotes({ ...state(), expanded: true, panel: 'capture' })
      await vi.advanceTimersByTimeAsync(32)
    })
    await act(async () => {
      finishShelf({ ...state(), expanded: true, panel: 'clipboard' })
      await vi.advanceTimersByTimeAsync(32)
    })
    expect(host.querySelector('nav [aria-label="随手记"]')?.classList.contains('dc-nav-active')).toBe(true)
    expect(host.querySelector('.dc-shelf-panel')).toBeNull()
    expect(body(host)).toBe('快速掠过导航也不能丢失这段正文')
    expect(document.activeElement).toBe(outside)
    expect(api.createNote).not.toHaveBeenCalled()
  })

  it('ignores navigation hover during a file drag or file chooser, then resumes normal hover navigation', async () => {
    vi.useFakeTimers()
    const { bridge } = native('top')
    const { host } = await mount({ surface: 'top' })
    await beginFileDrag(host, [new File(['drag'], '不要切走.txt')])
    await hoverNav(host, '暂存架')
    await hoverNav(host, '待办')
    expect(bridge.setExpanded).not.toHaveBeenCalled()
    expect(host.querySelector('[aria-label="选择文件用途"]')).toBeTruthy()
    await act(async () => { window.dispatchEvent(new Event('dragend')) })
    await click(host, '添加笔记附件')
    await hoverNav(host, '待办')
    expect(bridge.setExpanded).not.toHaveBeenCalled()
    await act(async () => { host.querySelector('[aria-label="选择笔记附件"]')!.dispatchEvent(new Event('cancel')) })
    await hoverNav(host, '待办')
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(true, 'tasks', false)
    expect(api.uploadNoteAttachment).not.toHaveBeenCalled()
    expect(bridge.addFiles).not.toHaveBeenCalled()
  })

  it('keeps AI work alive while the user hovers between features, without opening its result or switching on completion', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-23T12:08:00Z'))
    const { bridge } = native('top')
    let finish!: (value: api.DesktopComposeResult) => void
    vi.mocked(api.composeDesktopNote).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const { host } = await mount({ surface: 'top' })
    await input(host, '随手记正文', '在后台续写这一段')
    await click(host, 'AI 操作')
    await click(host, '一键续写')
    const signal = vi.mocked(api.composeDesktopNote).mock.calls[0][2]!
    await hoverNav(host, '暂存架')
    await hoverNav(host, '待办')
    await hoverNav(host, '随手记')
    expect(signal.aborted).toBe(false)
    expect(body(host)).toBe('在后台续写这一段')
    await hoverNav(host, '暂存架')
    const transitions = vi.mocked(bridge.setExpanded).mock.calls.length
    await act(async () => { finish({ title: '后台已完成', content: '续写结果', sourceCount: 1, model: 'test-gemini' }) })
    expect(bridge.setExpanded).toHaveBeenCalledTimes(transitions)
    expect(host.querySelector('.dc-shelf-panel')).toBeTruthy()
    expect(host.querySelector('[aria-label="生成结果预览"]')).toBeNull()
    expect(api.composeDesktopNote).toHaveBeenCalledTimes(1)
    expect(api.createNote).not.toHaveBeenCalled()
  })

  it('arms the leave delay when a pinned panel is unpinned while the pointer is already outside', async () => {
    vi.useFakeTimers()
    const { bridge } = native('shelf')
    const { host } = await mount({ surface: 'top' })
    await click(host, '固定展开')
    await act(async () => {
      host.querySelector('section')!.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body }))
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(bridge.setExpanded).not.toHaveBeenCalled()
    // A keyboard activation can unpin without any pointer movement.
    await click(host, '固定展开')
    await act(async () => { await vi.advanceTimersByTimeAsync(259) })
    expect(bridge.setExpanded).not.toHaveBeenCalled()
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(false, 'clipboard', false)
  })

  it('focuses the body on a native shortcut without stealing focus for later item updates', async () => {
    vi.useFakeTimers()
    vi.spyOn(document, 'hasFocus').mockReturnValue(true)
    const { emit, state } = native('top', [], false)
    const { host } = await mount({ surface: 'top' })
    await act(async () => { emit({ ...state(), expanded: true, panel: 'capture' }) })
    await act(async () => { await vi.advanceTimersByTimeAsync(20) })
    expect(document.activeElement).toBe(host.querySelector('[aria-label="随手记正文"]'))
    const title = host.querySelector<HTMLInputElement>('[aria-label="随手记标题"]')!
    title.focus()
    await act(async () => { emit({ ...state(), items: [fileItem] }) })
    expect(document.activeElement).toBe(title)
  })

  it('focuses a keyboard-opened native editor but keeps an inactive initial editor passive', async () => {
    const hasFocus = vi.spyOn(document, 'hasFocus').mockReturnValue(true)
    native('top')
    const focused = await mount({ surface: 'top' })
    expect(document.activeElement).toBe(focused.host.querySelector('[aria-label="随手记正文"]'))
    await act(async () => { focused.root.unmount() })
    roots.splice(roots.indexOf(focused.root), 1)
    hasFocus.mockReturnValue(false)
    native('top')
    const inactive = await mount({ surface: 'top' })
    expect(inactive.host.querySelector('[aria-label="随手记正文"]')).toBeTruthy()
    expect(inactive.host.contains(document.activeElement)).toBe(false)
  })

  it('starts selected shelf materials as a background task and keeps the shelf usable', async () => {
    vi.useFakeTimers()
    const source: CompanionItem = { id: 't1', kind: 'text', title: '待办', text: '明天回复方案', createdAt: '2026-09-22' }
    const { bridge } = native('shelf', [source])
    let finish!: (value: api.DesktopComposeResult) => void
    vi.mocked(api.composeDesktopNote).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    const { host } = await mount({ surface: 'top' })
    expect(host.querySelector('button[aria-label="整理成笔记"]')).toBeNull()
    await click(host, '随手记')
    await click(host, 'AI 操作')
    await click(host, '从暂存架选择')
    await act(async () => { host.querySelector<HTMLInputElement>('[aria-label="选择 待办"]')!.click() })
    expect(host.querySelector<HTMLSelectElement>('select[aria-label="AI 操作"]')?.value).toBe('organize')
    await click(host, '执行')
    const signal = vi.mocked(api.composeDesktopNote).mock.calls[0][2]!
    expect(api.composeDesktopNote).toHaveBeenCalledWith([expect.objectContaining({ id: 't1', text: '明天回复方案' })], '', signal, 'organize')
    expect(host.querySelector('[aria-label="随手记正文"]')).toBeTruthy()
    await click(host, '暂存架')
    expect(host.querySelector('[aria-label="预览 待办"]')).toBeTruthy()
    expect(signal.aborted).toBe(false)
    await addToShelf(host, '文字或链接')
    await input(host, '要暂存的文字或链接', '另一条独立暂存内容')
    await click(host, '暂存文字')
    expect(bridge.addText).toHaveBeenCalledWith('另一条独立暂存内容')
    expect(signal.aborted).toBe(false)
    await act(async () => { finish({ title: '整理结果', content: '明天回复方案', sourceCount: 1, model: 'test-gemini' }) })
    expect(host.querySelector('[aria-label="预览 待办"]')).toBeTruthy()
    expect(host.querySelector('[aria-label="生成结果预览"]')).toBeNull()
    expect(api.createNote).not.toHaveBeenCalled()
    expect(bridge.show).not.toHaveBeenCalled()
  })

  it('renders the actual document thumbnail and opens it inside the island; Escape returns focus before collapsing', async () => {
    vi.useFakeTimers()
    const png = 'data:image/png;base64,cmVhbC1kb2N1bWVudC1wYWdl'
    const { bridge } = native('shelf', [{ ...fileItem, thumbnail: png, previewStatus: 'ready' }])
    const { host } = await mount({ surface: 'top' })
    const preview = host.querySelector<HTMLButtonElement>('[aria-label="预览 报价.pdf"]')!
    expect(preview.querySelector('img')?.getAttribute('src')).toBe(png)
    expect(preview.querySelector('.bx')).toBeNull()
    await act(async () => { preview.click() })
    expect(host.querySelector('[aria-label="内容预览"] img')?.getAttribute('src')).toBe(png)
    expect(host.querySelector('.dc-shelf-panel')?.hasAttribute('hidden')).toBe(true)
    expect(bridge.open).not.toHaveBeenCalled()
    expect(bridge.openWorkspace).not.toHaveBeenCalled()
    await act(async () => {
      host.querySelector('[aria-label="内容预览"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
      await vi.advanceTimersByTimeAsync(32)
    })
    expect(host.querySelector('[aria-label="内容预览"]')).toBeNull()
    expect(document.activeElement).toBe(preview)
    expect(bridge.setExpanded).not.toHaveBeenCalled()
    await act(async () => { preview.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })) })
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(false, 'clipboard', true)
  })

  it('does not implicitly pin an opened file preview and restores it after pointer-leave collapse', async () => {
    vi.useFakeTimers()
    const { bridge } = native('shelf', [{ ...fileItem, previewText: '真实文件内容', previewStatus: 'ready' }])
    const { host } = await mount({ surface: 'top' })
    await click(host, '预览 报价.pdf')
    expect(host.querySelector('[aria-label="内容预览"]')).toBeTruthy()
    expect(host.querySelector('[aria-label="固定展开"]')?.getAttribute('aria-pressed')).toBe('false')
    await act(async () => {
      host.querySelector('section')!.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body }))
      await vi.advanceTimersByTimeAsync(260)
    })
    expect(bridge.setExpanded).toHaveBeenLastCalledWith(false, 'clipboard', false)
    await act(async () => { host.querySelector<HTMLButtonElement>('[aria-label="展开桌面口袋"]')!.click() })
    expect(host.querySelector('[aria-label="内容预览"]')?.textContent).toContain('真实文件内容')
    expect(bridge.open).not.toHaveBeenCalled()
  })

  it('previews actual plain-file text safely, including empty files and truncated content', async () => {
    const previewText = '<img src=x onerror=alert(1)>\nActual file contents'
    const item: CompanionItem = { ...fileItem, title: 'notes.txt', previewStatus: 'ready', previewText, previewTextTruncated: true }
    const { emit, state } = native('shelf', [item])
    const { host } = await mount({ surface: 'top' })
    const preview = host.querySelector<HTMLButtonElement>('[aria-label="预览 notes.txt"]')!
    expect(preview.textContent).toBe(previewText)
    expect(preview.querySelector('img')).toBeNull()
    await act(async () => { preview.click() })
    expect(host.querySelector('.dc-content-file-text-full')?.textContent).toContain(previewText)
    expect(host.querySelector('.dc-file-text-boundary')?.textContent).toContain('打开原文件')
    await act(async () => { emit({ ...state(), items: [{ ...item, previewText: '', previewTextTruncated: false }] }) })
    expect(host.querySelector('.dc-content-file-text-full')?.textContent).toBe('空文件')
    expect(host.querySelector('.dc-file-text-boundary')).toBeNull()
  })

  it('keeps missing previews honest and retries only the selected saved file', async () => {
    const { bridge, emit, state } = native('shelf', [{ ...fileItem, previewStatus: 'loading' }])
    const { host } = await mount({ surface: 'top' })
    expect(host.querySelector('.dc-item-preview')?.textContent).toContain('正在生成预览')
    expect(host.querySelector('.dc-item-preview img, .dc-item-preview .bx')).toBeNull()
    await act(async () => { emit({ ...state(), items: [{ ...fileItem, previewStatus: 'unavailable', previewError: '系统没有提供页面缩略图' }] }) })
    expect(host.querySelector('.dc-item-preview')?.textContent).toContain('系统没有提供页面缩略图')
    await act(async () => { host.querySelector<HTMLButtonElement>('[aria-label="预览 报价.pdf"]')!.click() })
    await click(host, '重试预览')
    expect(bridge.refreshPreview).toHaveBeenCalledWith(fileItem.id)
    expect(bridge.open).not.toHaveBeenCalled()
    await act(async () => { emit({ ...state(), items: [] }) })
    expect(host.querySelector('[aria-label="内容预览"]')?.textContent).toContain('已经移除')
  })

  it('dragging the real preview keeps native file drag-out and does not accidentally open the large preview', async () => {
    const { bridge } = native('shelf', [fileItem])
    const { host } = await mount({ surface: 'top' })
    const preview = host.querySelector<HTMLButtonElement>('[aria-label="预览 报价.pdf"]')!
    await act(async () => { preview.dispatchEvent(dragEvent('dragstart', { setData: vi.fn() })) })
    expect(bridge.startDrag).toHaveBeenCalledWith(fileItem.id)
    await act(async () => { preview.click() })
    expect(host.querySelector('[aria-label="内容预览"]')).toBeNull()
  })

  it('shows an actual window snapshot before saving; empty snapshots explain their state without type icons', async () => {
    const { bridge } = native('shelf')
    const png = 'data:image/png;base64,d2luZG93LXNuYXBzaG90'
    vi.mocked(bridge.listWindows).mockResolvedValue({ ok: true, candidates: [
      { id: 'window:12:0', title: 'Calculator', preview: png },
      { id: 'window:13:0', title: 'Protected document', previewError: '这个窗口没有提供可读取的截图。' },
    ] })
    const { host } = await mount({ surface: 'top' })
    await addToShelf(host, '暂存窗口')
    const preview = host.querySelector<HTMLButtonElement>('[aria-label="预览窗口 Calculator"]')!
    expect(preview.querySelector('img')?.getAttribute('src')).toBe(png)
    const empty = host.querySelector('[aria-label="预览窗口 Protected document"]')!
    expect(empty.textContent).toContain('没有提供可读取的截图')
    expect(empty.querySelector('img, .bx')).toBeNull()
    await act(async () => { preview.click() })
    expect(host.querySelector('[aria-label="内容预览"] img')?.getAttribute('src')).toBe(png)
    expect(host.querySelector('[aria-label="内容预览"]')?.textContent).toContain('不会实时更新')
    const save = host.querySelector<HTMLButtonElement>('.dc-preview-actions button')!
    await act(async () => { save.click() })
    expect(bridge.addWindow).toHaveBeenCalledWith('window:12:0')
  })

})


describe('shelf copy ownership and removal recovery', () => {
  const copiedFile: CompanionItem = {
    ...fileItem, storage: 'copy', sourcePath: '/original/报价.md', path: '/profile/companion/files/f1/报价.md',
    title: '报价.md', previewStatus: 'ready', previewText: '这份内容来自暂存副本。', previewTextTruncated: true,
  }

  it('shows copy progress before acknowledgement, then announces the copy and uses copy-specific preview actions', async () => {
    const { bridge, state } = native('shelf')
    let finish!: (value: Awaited<ReturnType<CompanionBridge['addFiles']>>) => void
    vi.mocked(bridge.addFiles).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const { host } = await mount({ surface: 'top' })
    const file = new File(['original file data'], copiedFile.title, { type: 'text/markdown' })
    const picker = host.querySelector<HTMLInputElement>('input[type="file"]')!
    Object.defineProperty(picker, 'files', { configurable: true, value: [file] })
    await act(async () => { picker.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(host.querySelector('.dc-shelf-toolbar [role="status"]')?.textContent).toBe('正在复制到暂存架…')
    expect(host.querySelector('.dc-feedback')?.textContent || '').not.toContain('已保留')
    expect(host.querySelectorAll('.dc-item')).toHaveLength(0)
    await act(async () => { finish({ ok: true, state: { ...state(), items: [copiedFile] } }) })
    expect(host.querySelector('.dc-feedback')?.textContent).toBe('已保留「报价.md」的副本')
    expect(host.querySelector('.dc-item')?.getAttribute('title')).toContain('已保留独立副本')
    expect(host.querySelector('.dc-shelf-footer')?.textContent).toContain('独立副本 · 原件保留')
    await click(host, '预览 报价.md')
    const preview = host.querySelector('[aria-label="内容预览"]')!
    expect(preview.querySelector('.dc-preview-footer')?.textContent).toContain('独立副本 · 原件保留')
    expect(preview.querySelector('.dc-file-text-boundary')?.textContent).toContain('打开副本查看完整内容')
    const actions = [...preview.querySelectorAll<HTMLButtonElement>('.dc-preview-actions button')]
    const open = actions.find(button => button.textContent === '打开副本')!
    const reveal = actions.find(button => button.textContent === '副本位置')!
    expect(open.title).toBe('用默认应用打开暂存副本')
    expect(reveal.title).toBe('在文件管理器中显示暂存副本')
    expect(actions.some(button => button.textContent === '打开原文件')).toBe(false)
    await act(async () => { open.click() })
    await act(async () => { reveal.click() })
    expect(bridge.open).toHaveBeenCalledWith(copiedFile.id)
    expect(bridge.reveal).toHaveBeenCalledWith(copiedFile.id)
    expect(bridge.revealRemoved).not.toHaveBeenCalled()
    expect(api.createNote).not.toHaveBeenCalled()
  })

  it.each([undefined, 'reference'] as const)('keeps legacy storage=%s clearly identified as an original-path reference', async storage => {
    const { bridge } = native('shelf', [{ ...fileItem, storage }])
    const { host } = await mount({ surface: 'top' })
    expect(host.querySelector('.dc-item')?.getAttribute('title')).toContain('旧版原位置引用')
    expect(host.querySelector('.dc-shelf-footer')?.textContent).toContain('含旧版引用')
    expect(host.querySelector<HTMLButtonElement>('[aria-label="从暂存架移除 报价.pdf"]')?.title).toBe('仅移出暂存架，不删除原文件')
    await click(host, '预览 报价.pdf')
    const preview = host.querySelector('[aria-label="内容预览"]')!
    expect(preview.querySelector('.dc-preview-footer')?.textContent).toContain('原位置引用 · 尚未复制')
    expect(preview.textContent).not.toContain('打开副本')
    expect(preview.textContent).not.toContain('副本位置')
    const open = [...preview.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === '打开原文件')!
    expect(open.title).toBe('用默认应用打开原文件')
    await act(async () => { open.click() })
    expect(bridge.open).toHaveBeenCalledWith(fileItem.id)
    expect(bridge.addFiles).not.toHaveBeenCalled()
  })

  it('describes a missing managed copy without claiming the original file was moved or removed', async () => {
    const { bridge } = native('shelf', [{ ...copiedFile, missing: true }])
    const { host } = await mount({ surface: 'top' })
    expect(host.querySelector('.dc-item-preview')?.textContent).toContain('暂存副本无法访问')
    expect(host.querySelector('.dc-item-preview')?.textContent).not.toContain('原文件已移动')
    expect(host.querySelector('.dc-item')?.getAttribute('draggable')).toBe('false')
    await click(host, '预览 报价.md')
    const preview = host.querySelector('[aria-label="内容预览"]')!
    expect(preview.querySelector('.dc-preview-footer')?.textContent).toContain('暂存副本不可用')
    const fileActions = [...preview.querySelectorAll<HTMLButtonElement>('.dc-preview-actions button')]
    expect(fileActions.every(button => button.disabled)).toBe(true)
    await act(async () => { fileActions.forEach(button => button.click()) })
    expect(bridge.open).not.toHaveBeenCalled()
    expect(bridge.reveal).not.toHaveBeenCalled()
  })

  it('offers removal recovery only after the bridge returns a recovery path and opens it on explicit click', async () => {
    const { bridge, state } = native('shelf', [copiedFile])
    vi.mocked(bridge.remove).mockResolvedValueOnce({ ok: true, state: { ...state(), items: [] }, recoveryPath: '/profile/companion/removed/f1' })
    const { host } = await mount({ surface: 'top' })
    const remove = host.querySelector<HTMLButtonElement>('[aria-label="从暂存架移除 报价.md"]')!
    expect(remove.title).toBe('移除暂存副本，原件不受影响')
    expect(host.querySelector('.dc-feedback button')).toBeNull()
    await act(async () => { remove.click() })
    expect(bridge.remove).toHaveBeenCalledWith(copiedFile.id)
    expect(host.querySelectorAll('.dc-item')).toHaveLength(0)
    expect(host.querySelector('.dc-feedback')?.textContent).toContain('已移出暂存架')
    expect(host.querySelector('.dc-feedback button')?.textContent).toBe('找回副本')
    expect(bridge.revealRemoved).not.toHaveBeenCalled()
    expect(bridge.reveal).not.toHaveBeenCalled()
    await click(host, '找回副本')
    expect(bridge.revealRemoved).toHaveBeenCalledExactlyOnceWith()
    expect(bridge.addFiles).not.toHaveBeenCalled()
    expect(host.querySelectorAll('.dc-item')).toHaveLength(0)
  })

  it('does not imply recovery for a legacy removal or a failed removal, even if failure includes a path', async () => {
    const { bridge, state } = native('shelf', [fileItem])
    vi.mocked(bridge.remove).mockResolvedValueOnce({ ok: false, error: '无法移除，记录仍保留。', state: state(), recoveryPath: '/ignored-path' })
    const { host } = await mount({ surface: 'top' })
    await click(host, '从暂存架移除 报价.pdf')
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('记录仍保留')
    expect(host.querySelectorAll('.dc-item')).toHaveLength(1)
    expect(host.querySelector('.dc-feedback button')).toBeNull()
    await click(host, '从暂存架移除 报价.pdf')
    expect(host.querySelectorAll('.dc-item')).toHaveLength(0)
    expect(host.querySelector('.dc-feedback button')).toBeNull()
    expect(bridge.revealRemoved).not.toHaveBeenCalled()
  })

  it('surfaces the actual recovery-open failure without claiming an item was restored', async () => {
    const { bridge, state } = native('shelf', [copiedFile])
    vi.mocked(bridge.remove).mockResolvedValueOnce({ ok: true, state: { ...state(), items: [] }, recoveryPath: '/profile/companion/removed/f1' })
    vi.mocked(bridge.revealRemoved).mockResolvedValueOnce({ ok: false, error: '无法打开已移除副本目录。' })
    const { host } = await mount({ surface: 'top' })
    await click(host, '从暂存架移除 报价.md')
    await click(host, '找回副本')
    expect(bridge.revealRemoved).toHaveBeenCalledOnce()
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('无法打开已移除副本目录')
    expect(host.querySelectorAll('.dc-item')).toHaveLength(0)
    expect(bridge.addFiles).not.toHaveBeenCalled()
  })
})
