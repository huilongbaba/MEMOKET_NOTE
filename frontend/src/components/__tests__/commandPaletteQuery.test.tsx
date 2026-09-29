// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CommandPalette from '../CommandPalette'
import ShortcutsPanel from '../ShortcutsPanel'

const roots: Root[] = []
const requests: { url: string; init?: RequestInit }[] = []

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('memoket-note-user', 'palette-query-test')
  requests.length = 0
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  Element.prototype.scrollIntoView = () => {}
  vi.useFakeTimers()
  // Keep the real API wrappers and their request serialization. Only the network boundary is replaced.
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    requests.push({ url, init })
    if (url.startsWith('/api/notes/brief')) {
      const query = new URL(url, 'http://localhost').searchParams.get('q')
      return new Response(JSON.stringify({ total: query ? 1 : 0, notes: query ? [{ id: `note-${query}`, title: `${query} 未摄入的笔记`, updated_at: '2026-09-22T10:00:00Z', pinned: false, preview: '', has_body: true, snippet: null }] : [] }))
    }
    if (url === '/api/memory/recall') {
      const query = JSON.parse(String(init?.body)).query as string
      return new Response(JSON.stringify({ facts: [{ id: `fact-${query}`, text: `${query} 知识库中的事实`, when: '2026-09-22', kind: 'fact', sources: [] }], took_ms: 1, terms: [query] }))
    }
    throw new Error(`Unexpected request: ${url}`)
  }))
})

afterEach(async () => {
  await act(async () => { for (const root of roots.splice(0)) root.unmount() })
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

async function mount(node = <CommandPalette onOpenNote={() => {}} onOpenFact={() => {}} onInsertFact={() => {}} canInsertFact={false} />) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  await act(async () => { root.render(node) })
  return host
}
async function openWithQuery(query?: string) {
  await act(async () => { window.dispatchEvent(new CustomEvent('open-command-palette', query === undefined ? undefined : { detail: { query } })) })
  await act(async () => { await vi.advanceTimersByTimeAsync(250) })
}
async function key(key: string, metaKey = false) {
  await act(async () => { window.dispatchEvent(new KeyboardEvent('keydown', { key, metaKey, bubbles: true, cancelable: true })) })
  await act(async () => { await vi.advanceTimersByTimeAsync(250) })
}

describe('Home search uses both real API request paths', () => {
  it('prefills the query, requests ordinary notes and knowledge facts, and opens a returned note', async () => {
    const openNote = vi.fn()
    const host = await mount(<CommandPalette onOpenNote={openNote} onOpenFact={() => {}} onInsertFact={() => {}} canInsertFact={false} />)
    await openWithQuery('  项目灵感  ')
    expect(host.querySelector('input')!.value).toBe('项目灵感')
    expect(requests.some(({ url }) => url === '/api/notes/brief?q=' + encodeURIComponent('项目灵感'))).toBe(true)
    const recall = requests.find(({ url }) => url === '/api/memory/recall')!
    expect(recall.init?.method).toBe('POST')
    expect(JSON.parse(String(recall.init?.body))).toMatchObject({ query: '项目灵感', limit: 6 })
    expect(host.textContent).toContain('项目灵感 未摄入的笔记')
    expect(host.textContent).toContain('项目灵感 知识库中的事实')
    const note = [...host.querySelectorAll<HTMLElement>('.palette-item')].find((row) => row.textContent?.includes('未摄入的笔记'))!
    await act(async () => { note.click() })
    expect(openNote).toHaveBeenCalledWith('note-项目灵感')
  })

  it('replaces an already-open query and searches both sources again', async () => {
    const host = await mount()
    await openWithQuery('项目甲')
    const dialog = host.querySelector('[role="dialog"]')
    await openWithQuery('项目乙')
    expect(host.querySelector('[role="dialog"]')).toBe(dialog)
    expect(host.querySelector('input')!.value).toBe('项目乙')
    expect(host.textContent).not.toContain('项目甲 未摄入的笔记')
    expect(host.textContent).toContain('项目乙 未摄入的笔记')
    expect(host.textContent).toContain('项目乙 知识库中的事实')
    expect(requests.filter(({ url }) => url === '/api/memory/recall').map(({ init }) => JSON.parse(String(init?.body)).query)).toEqual(['项目甲', '项目乙'])
  })

  it('opens a fact source from Home and offers no insertion into a missing editor', async () => {
    const openFact = vi.fn()
    const insertFact = vi.fn()
    const host = await mount(<CommandPalette onOpenNote={() => {}} onOpenFact={openFact} onInsertFact={insertFact} canInsertFact={false} />)
    await openWithQuery('项目来源')
    expect(host.textContent).toContain('知识库 · 查看来源')
    expect(host.querySelector('button[aria-label^="插入引用："]')).toBeNull()
    const source = host.querySelector<HTMLButtonElement>('button[aria-label="查看来源：项目来源 知识库中的事实"]')!
    await act(async () => { source.click() })
    expect(openFact).toHaveBeenCalledExactlyOnceWith('fact-项目来源')
    expect(insertFact).not.toHaveBeenCalled()
    expect(host.querySelector('[role="dialog"]')).toBeNull()
  })

  it('uses Enter on a selected fact to view its source even while editing a note', async () => {
    const openFact = vi.fn()
    const insertFact = vi.fn()
    const openNote = vi.fn()
    const host = await mount(<CommandPalette onOpenNote={openNote} onOpenFact={openFact} onInsertFact={insertFact} canInsertFact />)
    await openWithQuery('工作结论')
    const input = host.querySelector('input')!
    await act(async () => { input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true })) })
    expect(host.querySelector('.palette-fact.active')).not.toBeNull()
    await act(async () => { input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })) })
    expect(openFact).toHaveBeenCalledExactlyOnceWith('fact-工作结论')
    expect(insertFact).not.toHaveBeenCalled()
    expect(openNote).not.toHaveBeenCalled()
    expect(host.querySelector('[role="dialog"]')).toBeNull()
  })

  it('inserts a citation only through the explicit editor action without opening its source', async () => {
    const openFact = vi.fn()
    const insertFact = vi.fn()
    const host = await mount(<CommandPalette onOpenNote={() => {}} onOpenFact={openFact} onInsertFact={insertFact} canInsertFact />)
    await openWithQuery('产品决定')
    const insert = host.querySelector<HTMLButtonElement>('button[aria-label="插入引用：产品决定 知识库中的事实"]')!
    expect(insert.textContent).toBe('插入引用')
    await act(async () => { insert.click() })
    expect(insertFact).toHaveBeenCalledExactlyOnceWith('产品决定 知识库中的事实 [fact-产品决定]')
    expect(openFact).not.toHaveBeenCalled()
    expect(host.querySelector('[role="dialog"]')).toBeNull()
  })

  it('removes the insert action if the current editor disappears while search stays open', async () => {
    const openFact = vi.fn()
    const insertFact = vi.fn()
    const props = { onOpenNote: () => {}, onOpenFact: openFact, onInsertFact: insertFact }
    const host = await mount(<CommandPalette {...props} canInsertFact />)
    await openWithQuery('持续搜索')
    expect(host.querySelector('button[aria-label^="插入引用："]')).not.toBeNull()
    await act(async () => { roots.at(-1)!.render(<CommandPalette {...props} canInsertFact={false} />) })
    expect(host.querySelector('input')!.value).toBe('持续搜索')
    expect(host.querySelector('button[aria-label^="插入引用："]')).toBeNull()
    await act(async () => { host.querySelector<HTMLButtonElement>('button[aria-label^="查看来源："]')!.click() })
    expect(openFact).toHaveBeenCalledExactlyOnceWith('fact-持续搜索')
    expect(insertFact).not.toHaveBeenCalled()
  })

  it('reopens empty with Cmd+K and preserves the ordinary event opening behavior', async () => {
    const host = await mount()
    await openWithQuery('旧查询')
    await key('Escape')
    expect(host.querySelector('input')).toBeNull()
    await key('k', true)
    expect(host.querySelector('input')!.value).toBe('')
    await openWithQuery('新的查询')
    await openWithQuery()
    expect(host.querySelector('input')!.value).toBe('')
    expect(host.textContent).toContain('前往')
  })

  it('lists quick capture and keeps the shortcut panel open when a native modal is above it', async () => {
    const close = vi.fn()
    const host = await mount(<ShortcutsPanel onClose={close} />)
    expect(host.textContent).toContain('快速捕捉')
    const dialog = document.createElement('dialog')
    dialog.open = true
    document.body.append(dialog)
    await key('Escape')
    expect(close).not.toHaveBeenCalled()
    dialog.remove()
    await key('Escape')
    expect(close).toHaveBeenCalledTimes(1)
  })
})
