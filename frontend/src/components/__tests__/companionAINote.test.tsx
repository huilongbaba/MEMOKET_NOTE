// @vitest-environment jsdom
import { act, type ComponentProps } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../../api'
import type { CompanionItem } from '../../desktop'
import CompanionAINote, { type CompanionAIRequest } from '../CompanionAINote'
import { DESKTOP_AI_ACTIONS, eligibleDesktopSource, hasCompanionAIDraft } from '../../util/companionActions'

vi.mock('../../api', () => ({
  getUser: () => localStorage.getItem('memoket-note-user') || 'ai-note-test',
  desktopAIStatus: vi.fn(), composeDesktopNote: vi.fn(), createNote: vi.fn(),
}))

vi.mock('../MarkdownEditor', () => ({ default: ({ content, readOnly, scrollPad }: { content: string; readOnly: boolean; scrollPad: boolean }) => <div data-rendered-markdown data-readonly={String(readOnly)} data-scrollpad={String(scrollPad)}>{content}</div> }))

const roots: Root[] = []
const result: api.DesktopComposeResult = { title: '项目后续', content: '## 待办\n明天确认报价。\n\n## 来源\n- 会议摘录', sourceCount: 1, model: 'test-gemini' }
const textItem: CompanionItem = { id: 'text-1', kind: 'text', title: '会议摘录', text: '明天确认报价。', createdAt: '2026-09-22' }
const linkItem: CompanionItem = { id: 'link-1', kind: 'link', title: '项目链接', text: '交付日期为周五。', url: 'https://example.com/project', createdAt: '2026-09-22' }
const excluded: CompanionItem[] = [
  { id: 'f1', kind: 'file', title: '财务文件.pdf', path: '/tmp/private.pdf', createdAt: '2026-09-22' },
  { id: 'i1', kind: 'image', title: '照片.png', thumbnail: 'data:image/png;base64,fixture', createdAt: '2026-09-22' },
  { id: 'w1', kind: 'window', title: '窗口', windowId: '42', createdAt: '2026-09-22' },
]
const key = (user = 'ai-note-test') => `memoket.companion.ai-note.${encodeURIComponent(user)}`

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('memoket-note-user', 'ai-note-test')
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.mocked(api.desktopAIStatus).mockResolvedValue({ configured: true, provider: 'gemini', model: 'test-gemini' })
  vi.mocked(api.composeDesktopNote).mockResolvedValue(result)
  vi.mocked(api.createNote).mockResolvedValue({ id: 'saved-note' } as api.Note)
})
afterEach(async () => {
  await act(async () => { for (const root of roots.splice(0)) root.unmount() })
  document.body.innerHTML = ''
  vi.restoreAllMocks()
  vi.clearAllMocks()
})

async function mount(items = [textItem, linkItem], onClose = vi.fn(), onStateChange = vi.fn(), initialRequest?: CompanionAIRequest, options: Partial<ComponentProps<typeof CompanionAINote>> = {}) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  await act(async () => { root.render(<CompanionAINote items={items} onClose={onClose} onStateChange={onStateChange} initialRequest={initialRequest} {...options} />) })
  return { host, root, onClose, onStateChange }
}

async function click(host: HTMLElement, text: string) {
  const element = [...host.querySelectorAll('button')].find((button) => button.textContent?.includes(text))!
  expect(element, text).toBeTruthy()
  await act(async () => { element.click() })
}
async function select(host: HTMLElement, title: string) {
  await act(async () => { host.querySelector<HTMLInputElement>(`[aria-label="选择 ${title}"]`)!.click() })
}
async function input(host: HTMLElement, label: string, value: string) {
  if ((label === '整理笔记正文' || label === '整理笔记标题') && !host.querySelector('input[aria-label="整理笔记标题"]')) await click(host, '编辑')
  const field = host.querySelector<HTMLInputElement | HTMLTextAreaElement>(`[aria-label="${label}"]`)!
  const prototype = field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  await act(async () => {
    Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(field, value)
    field.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
const generateButton = (host: HTMLElement) => [...host.querySelectorAll('button')].find((button) => button.textContent?.includes('执行'))!

describe('AI note uses explicit text selection and preserves unsaved work', () => {
  it('sends only the manually chosen text/link excerpt and instruction; generation never saves automatically', async () => {
    const { host, onStateChange } = await mount([textItem, linkItem, ...excluded])
    expect(api.composeDesktopNote).not.toHaveBeenCalled()
    expect(host.querySelectorAll('input[type=checkbox]')).toHaveLength(2)
    expect(host.textContent).not.toContain('财务文件.pdf')
    expect(host.querySelector('.dc-ai-disclosure')?.getAttribute('title')).toContain('不读取其他文件、照片或网页全文')
    await select(host, '项目链接')
    await input(host, '整理要求', '列出下一步，保留来源')
    await click(host, '执行')
    expect(api.composeDesktopNote).toHaveBeenCalledWith([
      { id: 'link-1', kind: 'link', title: '项目链接', text: '交付日期为周五。', url: 'https://example.com/project' },
    ], '列出下一步，保留来源', expect.any(AbortSignal), 'organize')
    expect(onStateChange).toHaveBeenCalledWith(expect.objectContaining({ busy: true, hasDraft: true, storageError: false, phase: 'generating' }))
    expect(api.createNote).not.toHaveBeenCalled()
    expect(host.querySelector('[aria-label="生成结果预览"]')?.textContent).toBe(result.content)
    expect(localStorage.getItem(key())).toContain('项目后续')
    expect(host.querySelector('h3[aria-label="整理笔记标题"]')?.textContent).toBe(result.title)
    expect(host.querySelector('input[aria-label="整理笔记标题"]')).toBeNull()
    expect(host.querySelector('.dc-ai-review-meta [role="tablist"]')).toBeTruthy()
    expect(host.querySelector('.dc-ai-footer details summary')?.textContent).toContain('这次使用的来源')
    expect(host.querySelector('.dc-ai-notice')).toBeNull()
  })

  it('saves the edited title/body only after confirmation, retaining the result on save failure', async () => {
    vi.mocked(api.createNote).mockRejectedValueOnce(new Error('后台暂时不可用'))
    const original = structuredClone([textItem])
    const { host } = await mount(original)
    await select(host, '会议摘录')
    await click(host, '执行')
    await input(host, '整理笔记标题', '修改后的标题')
    await input(host, '整理笔记正文', '人工核对后的结论\n\n原来源仍保留。')
    await click(host, '保存笔记')
    expect(api.createNote).toHaveBeenCalledWith('修改后的标题', '人工核对后的结论\n\n原来源仍保留。')
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('生成稿仍保留')
    expect(localStorage.getItem(key())).toContain('修改后的标题')
    await click(host, '保存笔记')
    expect(localStorage.getItem(key())).toBeNull()
    expect(host.textContent).toContain('原暂存材料保留')
    expect(original).toEqual([textItem])
  })

  it('cancel aborts the request, preserves selection and ignores a late response without fake output', async () => {
    let resolve!: (value: api.DesktopComposeResult) => void
    vi.mocked(api.composeDesktopNote).mockImplementationOnce(() => new Promise((done) => { resolve = done }))
    const { host, onStateChange } = await mount([textItem])
    await select(host, '会议摘录')
    await click(host, '执行')
    const signal = vi.mocked(api.composeDesktopNote).mock.calls[0][2]!
    await act(async () => {
      host.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true }))
    })
    expect(api.composeDesktopNote).toHaveBeenCalledTimes(1)
    await click(host, '取消生成')
    expect(signal.aborted).toBe(true)
    expect(onStateChange).toHaveBeenLastCalledWith(expect.objectContaining({ busy: false, hasDraft: true, storageError: false, phase: 'idle' }))
    await act(async () => { resolve(result) })
    expect(host.querySelector('[aria-label="整理笔记正文"]')).toBeNull()
    expect(host.querySelector<HTMLInputElement>('input[type=checkbox]')?.checked).toBe(true)
    expect(host.textContent).toContain('材料和已有草稿仍保留')
    expect(api.createNote).not.toHaveBeenCalled()
  })

  it('retains the previous review and requirements if regeneration fails', async () => {
    const { host } = await mount([textItem])
    await select(host, '会议摘录')
    await click(host, '执行')
    await input(host, '整理笔记正文', '我已手动编辑的版本')
    await click(host, '修改选材')
    await input(host, '整理要求', '再短一点')
    vi.mocked(api.composeDesktopNote).mockRejectedValueOnce(new Error('429 Gemini 暂时繁忙'))
    await click(host, '执行')
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('Gemini 暂时繁忙')
    expect(host.querySelector<HTMLTextAreaElement>('[aria-label="整理要求"]')?.value).toBe('再短一点')
    await click(host, '返回已有生成稿')
    expect(host.querySelector<HTMLTextAreaElement>('[aria-label="整理笔记正文"]')?.value).toBe('我已手动编辑的版本')
  })

  it('restores per-user selection and edited review after closing, without reading another user draft', async () => {
    localStorage.setItem(key('another-user'), JSON.stringify({ selectedIds: [], instruction: '别人的内容', result: { ...result, title: '别人私有标题', sources: [] }, stage: 'review' }))
    const first = await mount([textItem])
    await select(first.host, '会议摘录')
    await click(first.host, '执行')
    await input(first.host, '整理笔记标题', '还未保存')
    await act(async () => { first.root.unmount() })
    roots.splice(roots.indexOf(first.root), 1)
    const second = await mount([])
    expect(second.host.querySelector('[aria-label="整理笔记标题"]')?.textContent).toBe('还未保存')
    expect(second.host.textContent).not.toContain('别人私有标题')
    expect(second.host.textContent).toContain('已恢复本机整理草稿')
    await click(second.host, '修改选材')
    expect(second.host.textContent).toContain('之前选择的 1 项已不在暂存架')
    expect(generateButton(second.host).disabled).toBe(true)
  })

  it('blocks unconfigured and unsupported material without attempting an AI request', async () => {
    vi.mocked(api.desktopAIStatus).mockResolvedValueOnce({ configured: false, provider: 'gemini', model: '' })
    const { host } = await mount(excluded)
    expect(host.textContent).toContain('Gemini 尚未配置')
    expect(host.textContent).toContain('先暂存一段文字或链接')
    expect(host.querySelectorAll('input[type=checkbox]')).toHaveLength(0)
    expect(generateButton(host).disabled).toBe(true)
    await click(host, '执行')
    expect(api.composeDesktopNote).not.toHaveBeenCalled()
  })

  it('enforces 12 sources and counts title, text, URL and instruction using Unicode codepoints', async () => {
    const many = Array.from({ length: 13 }, (_, i) => ({ ...textItem, id: String(i), title: `材料${i}` }))
    const { host } = await mount(many)
    for (let i = 0; i < 12; i++) await select(host, `材料${i}`)
    expect(host.querySelector<HTMLInputElement>('[aria-label="选择 材料12"]')?.disabled).toBe(true)
    const chosen = many.slice(0, 12).reduce((total, source) => total + Array.from(source.title + source.text).length, 0)
    await input(host, '整理要求', '😀'.repeat(30_000 - chosen))
    expect(generateButton(host).disabled).toBe(false)
    await input(host, '整理要求', '😀'.repeat(30_001 - chosen))
    expect(generateButton(host).disabled).toBe(true)
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('超过 30,000 字')
    expect(api.composeDesktopNote).not.toHaveBeenCalled()
  })

  it('reports a storage failure and keeps the generated result recoverable without trapping navigation', async () => {
    const { host, onClose, onStateChange } = await mount([textItem])
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
    await select(host, '会议摘录')
    await click(host, '执行')
    expect(host.querySelector('[aria-label="生成结果预览"]')?.textContent).toBe(result.content)
    expect(host.textContent).toContain('本机草稿未保存')
    expect(onStateChange).toHaveBeenLastCalledWith(expect.objectContaining({ busy: false, hasDraft: true, storageError: true, phase: 'ready' }))
    await click(host, '返回笔记')
    expect(onClose).toHaveBeenCalledTimes(1)
    await click(host, '保存笔记')
    expect(api.createNote).toHaveBeenCalledTimes(1)
  })
})

describe('desktop actions use existing material and render recoverable results', () => {
  it.each(DESKTOP_AI_ACTIONS)('runs $id directly from the selected material', async ({ id }) => {
    localStorage.setItem('memoket-note-user', `action-${id}`)
    const { host } = await mount([textItem])
    await select(host, textItem.title)
    const actionSelect = host.querySelector<HTMLSelectElement>('select[aria-label="AI 操作"]')!
    expect(actionSelect.options).toHaveLength(6)
    await act(async () => { actionSelect.value = id; actionSelect.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(api.composeDesktopNote).not.toHaveBeenCalled()
    expect(host.querySelectorAll('.dc-ai-action-control button')).toHaveLength(1)
    await click(host, '执行')
    expect(api.composeDesktopNote).toHaveBeenLastCalledWith([
      { id: textItem.id, kind: 'text', title: textItem.title, text: textItem.text },
    ], '', expect.any(AbortSignal), id)
    expect(host.querySelector('[data-rendered-markdown]')?.getAttribute('data-readonly')).toBe('true')
    expect(host.querySelector('[data-rendered-markdown]')?.getAttribute('data-scrollpad')).toBe('false')
    expect(host.querySelector('[aria-label="整理笔记正文"]')).toBeNull()
    expect(api.createNote).not.toHaveBeenCalled()
  })

  it('accepts ready file text excerpts only, without sending a path, image or unready document', () => {
    const file = { ...excluded[0], previewStatus: 'ready' as const, previewText: '真实提取的一段正文' }
    expect(eligibleDesktopSource(file)).toEqual({ id: 'f1', kind: 'text', title: '财务文件.pdf（文字节选）', text: '真实提取的一段正文' })
    expect(eligibleDesktopSource({ ...file, previewStatus: 'loading' })).toBeNull()
    expect(eligibleDesktopSource({ ...file, missing: true })).toBeNull()
    expect(eligibleDesktopSource({ ...excluded[1], previewStatus: 'ready', previewText: '不是允许的文件节选' })).toBeNull()
  })

  it('automatically runs an explicit request once and restores it without regenerating on reopen', async () => {
    localStorage.setItem('memoket-note-user', 'initial-once')
    const request: CompanionAIRequest = { id: 'request-1', action: 'diagram', sources: [{ id: 'snapshot', title: '剪贴板', kind: 'text', text: 'A → B → C' }] }
    const first = await mount([], vi.fn(), vi.fn(), request)
    expect(api.composeDesktopNote).toHaveBeenCalledTimes(1)
    expect(api.composeDesktopNote).toHaveBeenLastCalledWith(request.sources, '', expect.any(AbortSignal), 'diagram')
    expect(first.host.querySelector('[aria-label="生成结果预览"]')).toBeTruthy()
    await act(async () => { first.root.render(<CompanionAINote items={[]} onClose={vi.fn()} initialRequest={{ ...request }} />) })
    expect(api.composeDesktopNote).toHaveBeenCalledTimes(1)
    await act(async () => { first.root.unmount() })
    roots.splice(roots.indexOf(first.root), 1)
    const second = await mount([], vi.fn(), vi.fn(), request)
    expect(second.host.querySelector('[aria-label="生成结果预览"]')?.textContent).toBe(result.content)
    expect(api.composeDesktopNote).toHaveBeenCalledTimes(1)
    expect(hasCompanionAIDraft()).toBe(true)
  })

  it('keeps separate requests recoverable and opens the latest unsaved result by default', async () => {
    localStorage.setItem('memoket-note-user', 'request-history')
    const firstRequest: CompanionAIRequest = { id: 'old', action: 'continue', sources: [{ id: 'source-a', title: '第一份草稿', kind: 'text', text: '原来的正文' }] }
    const secondRequest: CompanionAIRequest = { id: 'new', action: 'tasks', sources: [{ id: 'source-b', title: '新摘录', kind: 'text', text: '明天交付' }] }
    const first = await mount([], vi.fn(), vi.fn(), firstRequest)
    await input(first.host, '整理笔记标题', '第一份未保存结果')
    await act(async () => { first.root.render(<CompanionAINote items={[]} onClose={vi.fn()} initialRequest={secondRequest} />) })
    expect(api.composeDesktopNote).toHaveBeenCalledTimes(2)
    expect(localStorage.getItem(`${key('request-history')}::request::old`)).toContain('第一份未保存结果')
    expect(first.host.querySelector('[aria-label="恢复其他生成稿"]')?.textContent).toContain('第一份未保存结果')
    await act(async () => { first.root.unmount() })
    roots.splice(roots.indexOf(first.root), 1)
    const restored = await mount([])
    expect(restored.host.querySelector('[aria-label="生成结果预览"]')?.textContent).toBe(result.content)
    const selector = restored.host.querySelector<HTMLSelectElement>('[aria-label="恢复其他生成稿"]')!
    await act(async () => {
      selector.value = `${key('request-history')}::request::old`
      selector.dispatchEvent(new Event('change', { bubbles: true }))
    })
    expect(restored.host.querySelector('[aria-label="整理笔记标题"]')?.textContent).toBe('第一份未保存结果')
    expect(api.composeDesktopNote).toHaveBeenCalledTimes(2)
  })

  it('shows a compact direct progress state and ignores a cancelled response across reopen', async () => {
    localStorage.setItem('memoket-note-user', 'direct-cancel')
    let finish!: (value: api.DesktopComposeResult) => void
    vi.mocked(api.composeDesktopNote).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    const request: CompanionAIRequest = { id: 'cancelled', action: 'table', sources: [{ id: 'source', kind: 'text', title: '报价单', text: 'A: 10, B: 20' }] }
    const first = await mount([], vi.fn(), vi.fn(), request)
    expect(first.host.querySelector('[aria-label="正在处理材料"]')).toBeTruthy()
    expect(first.host.querySelector('[aria-label="AI 操作"]')).toBeNull()
    const signal = vi.mocked(api.composeDesktopNote).mock.calls[0][2]!
    await click(first.host, '取消生成')
    expect(signal.aborted).toBe(true)
    await act(async () => { finish(result) })
    expect(first.host.querySelector('[aria-label="生成结果预览"]')).toBeNull()
    await act(async () => { first.root.unmount() })
    roots.splice(roots.indexOf(first.root), 1)
    const restored = await mount([], vi.fn(), vi.fn(), request)
    expect(api.composeDesktopNote).toHaveBeenCalledTimes(1)
    expect(restored.host.querySelector<HTMLInputElement>('input[type=checkbox]')?.checked).toBe(true)
  })

  it('copies a generated result without creating a note', async () => {
    localStorage.setItem('memoket-note-user', 'copy-result')
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    const { host } = await mount([textItem])
    await select(host, textItem.title)
    await click(host, '执行')
    await click(host, '复制')
    expect(writeText).toHaveBeenCalledWith(result.content)
    expect(api.createNote).not.toHaveBeenCalled()
  })
})

describe('request storage boundaries', () => {
  it('isolates dotted user names from request namespaces and active pointers', async () => {
    const victim = 'alice.request.b'
    const victimKey = key(victim)
    localStorage.setItem(victimKey, JSON.stringify({ selectedIds: [], instruction: '', action: 'organize', result: { ...result, title: '另一个用户的私有内容', sources: [] }, stage: 'review' }))
    localStorage.setItem('memoket-note-user', 'alice')
    expect(hasCompanionAIDraft()).toBe(false)
    const { host } = await mount([])
    expect(host.textContent).not.toContain('另一个用户的私有内容')
    const pointerVictim = 'alice.active-request'
    localStorage.setItem(key(pointerVictim), 'other-user-private-draft')
    const request: CompanionAIRequest = { id: 'new', action: 'organize', sources: [{ id: 'a', kind: 'text', title: '自己的内容', text: '自己的文字' }] }
    await mount([], vi.fn(), vi.fn(), request)
    expect(localStorage.getItem(key(pointerVictim))).toBe('other-user-private-draft')
    expect(localStorage.getItem(victimKey)).toContain('另一个用户的私有内容')
  })

  it('persists an explicit source snapshot before configuration succeeds and restores it without sending', async () => {
    localStorage.setItem('memoket-note-user', 'configuration-failed')
    vi.mocked(api.desktopAIStatus).mockRejectedValueOnce(new Error('Failed to fetch'))
    const request: CompanionAIRequest = { id: 'pending-config', action: 'summarize', sources: [{ id: 'clipboard', kind: 'text', title: '当时的剪贴板', text: '需要保留的原始内容 A' }] }
    const first = await mount([], vi.fn(), vi.fn(), request)
    expect(api.composeDesktopNote).not.toHaveBeenCalled()
    expect(hasCompanionAIDraft()).toBe(true)
    await act(async () => { first.root.unmount() })
    roots.splice(roots.indexOf(first.root), 1)
    const reopened = await mount([{ ...textItem, id: 'clipboard', text: '剪贴板已经变成 B' }])
    expect(reopened.host.textContent).toContain('需要保留的原始内容 A')
    expect(api.composeDesktopNote).not.toHaveBeenCalled()
  })

  it('does not regenerate an already saved explicit request reopened after a recovery session', async () => {
    localStorage.setItem('memoket-note-user', 'saved-recovery')
    const request: CompanionAIRequest = { id: 'saved-once', action: 'table', sources: [{ id: 'a', kind: 'text', title: '数据', text: '甲10，乙20' }] }
    const first = await mount([], vi.fn(), vi.fn(), request)
    await act(async () => { first.root.unmount() })
    roots.splice(roots.indexOf(first.root), 1)
    const recovery = await mount([])
    await click(recovery.host, '保存笔记')
    await act(async () => { recovery.root.unmount() })
    roots.splice(roots.indexOf(recovery.root), 1)
    await mount([], vi.fn(), vi.fn(), request)
    expect(api.composeDesktopNote).toHaveBeenCalledTimes(1)
    expect(hasCompanionAIDraft()).toBe(false)
  })
})


describe('inline AI tasks leave the editor in control', () => {
  const request = (id: string): CompanionAIRequest => ({ id, action: 'continue', sources: [{ id: 'note', kind: 'text', title: '当前笔记', text: '已经写下的内容' }] })

  it('stays in a taskbar while working and on completion; inserts only after an explicit click', async () => {
    localStorage.setItem('memoket-note-user', 'compact-ready')
    let finish!: (value: api.DesktopComposeResult) => void
    vi.mocked(api.composeDesktopNote).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    const editor = document.createElement('textarea')
    document.body.append(editor)
    editor.focus()
    const onInsert = vi.fn()
    const onExpandedChange = vi.fn()
    const { host, onStateChange } = await mount([], vi.fn(), vi.fn(), request('inline'), { compact: true, onInsert, onExpandedChange })
    expect(host.querySelector('.dc-ai-taskbar')?.getAttribute('data-phase')).toBe('generating')
    expect(host.querySelector('.dc-ai-drawer')).toBeNull()
    expect(document.activeElement).toBe(editor)
    expect(onExpandedChange).toHaveBeenCalledWith(false)
    expect(onStateChange).toHaveBeenLastCalledWith(expect.objectContaining({ busy: true, phase: 'generating', actionLabel: '一键续写' }))
    await act(async () => { finish(result) })
    expect(host.querySelector('.dc-ai-taskbar')?.getAttribute('data-phase')).toBe('ready')
    expect(host.querySelector('.dc-ai-drawer')).toBeNull()
    expect(document.activeElement).toBe(editor)
    expect(onInsert).not.toHaveBeenCalled()
    expect(api.createNote).not.toHaveBeenCalled()
    await click(host, '查看结果')
    expect(host.querySelector('[aria-label="生成结果预览"]')?.textContent).toBe(result.content)
    await click(host, '插入正文')
    expect(onInsert).toHaveBeenCalledExactlyOnceWith(result.content)
    expect(host.querySelector('.dc-ai-drawer')).toBeNull()
    expect(hasCompanionAIDraft()).toBe(true)
    expect(api.createNote).not.toHaveBeenCalled()
  })


  it('inserts only the new continuation after an exact complete source prefix, keeping the full result preview', async () => {
    localStorage.setItem('memoket-note-user', 'compact-continuation-prefix')
    const original = request('prefix')
    const continuation = '下一段新的内容。'
    const fullContent = `${original.sources[0].text}\n\n${continuation}`
    vi.mocked(api.composeDesktopNote).mockResolvedValueOnce({ ...result, content: fullContent })
    const onInsert = vi.fn()
    const { host } = await mount([], vi.fn(), vi.fn(), original, { compact: true, onInsert })
    await click(host, '查看结果')
    expect(host.querySelector('[aria-label="生成结果预览"]')?.textContent).toBe(fullContent)
    await click(host, '插入正文')
    expect(onInsert).toHaveBeenCalledExactlyOnceWith(continuation)
    expect(localStorage.getItem(`${key('compact-continuation-prefix')}::request::prefix`)).toContain(original.sources[0].text)
  })

  it('collapses manually selected materials when generation starts, without losing the selected snapshot', async () => {
    localStorage.setItem('memoket-note-user', 'compact-manual')
    const { host } = await mount([textItem], vi.fn(), vi.fn(), undefined, { compact: true })
    await click(host, '查看材料')
    await select(host, textItem.title)
    await click(host, '执行')
    expect(host.querySelector('.dc-ai-drawer')).toBeNull()
    expect(host.querySelector('.dc-ai-taskbar')?.getAttribute('data-phase')).toBe('ready')
    await click(host, '查看结果')
    expect(host.querySelector('.dc-ai-source-proof')?.textContent).toContain(textItem.title)
    await click(host, '收起')
    expect(hasCompanionAIDraft()).toBe(true)
  })

  it('can cancel from the taskbar and ignores late output; an explicit retry succeeds without opening details', async () => {
    localStorage.setItem('memoket-note-user', 'compact-cancel')
    let finish!: (value: api.DesktopComposeResult) => void
    vi.mocked(api.composeDesktopNote).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    const { host } = await mount([], vi.fn(), vi.fn(), request('cancel'), { compact: true })
    const signal = vi.mocked(api.composeDesktopNote).mock.calls[0][2]!
    await act(async () => { host.querySelector<HTMLButtonElement>('[aria-label="取消生成"]')!.click() })
    expect(signal.aborted).toBe(true)
    expect(host.querySelector('.dc-ai-taskbar')?.getAttribute('data-phase')).toBe('idle')
    await act(async () => { finish(result) })
    expect(host.textContent).not.toContain('结果已就绪')
    await click(host, '重试')
    expect(api.composeDesktopNote).toHaveBeenCalledTimes(2)
    expect(host.querySelector('.dc-ai-taskbar')?.getAttribute('data-phase')).toBe('ready')
    expect(host.querySelector('.dc-ai-drawer')).toBeNull()
  })

  it('cancels the connecting phase before a provider call and prevents an aborted configuration response from starting it', async () => {
    localStorage.setItem('memoket-note-user', 'compact-connecting')
    let finish!: (value: api.DesktopAIStatus) => void
    vi.mocked(api.desktopAIStatus).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    const { host, onStateChange } = await mount([], vi.fn(), vi.fn(), request('connecting'), { compact: true })
    expect(onStateChange).toHaveBeenLastCalledWith(expect.objectContaining({ busy: true, phase: 'connecting' }))
    const signal = vi.mocked(api.desktopAIStatus).mock.calls[0][0]!
    await act(async () => { host.querySelector<HTMLButtonElement>('[aria-label="取消生成"]')!.click() })
    expect(signal.aborted).toBe(true)
    await act(async () => { finish({ configured: true, provider: 'gemini', model: 'test' }) })
    expect(api.composeDesktopNote).not.toHaveBeenCalled()
    expect(host.querySelector('.dc-ai-taskbar')?.getAttribute('data-phase')).toBe('idle')
    await click(host, '重试')
    expect(api.composeDesktopNote).toHaveBeenCalledTimes(1)
    expect(host.querySelector('.dc-ai-drawer')).toBeNull()
  })

  it('offers retry after failure and can be collapsed even if local draft persistence fails', async () => {
    localStorage.setItem('memoket-note-user', 'compact-error')
    vi.mocked(api.composeDesktopNote).mockRejectedValueOnce(new Error('429 Gemini 暂时繁忙'))
    const { host } = await mount([], vi.fn(), vi.fn(), request('error'), { compact: true })
    expect(host.querySelector('.dc-ai-taskbar')?.getAttribute('data-phase')).toBe('error')
    expect(host.querySelector('.dc-ai-drawer')).toBeNull()
    await click(host, '重试')
    await click(host, '查看结果')
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
    await input(host, '整理笔记正文', '仍保留在内存中的结果')
    expect(host.textContent).toContain('本机草稿未保存')
    await click(host, '收起')
    expect(host.querySelector('.dc-ai-drawer')).toBeNull()
    await click(host, '查看结果')
    expect(host.querySelector<HTMLTextAreaElement>('[aria-label="整理笔记正文"]')?.value).toBe('仍保留在内存中的结果')
  })
})
