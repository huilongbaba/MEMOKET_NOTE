// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Note } from '../../api'
import WorkspaceLibrary from '../WorkspaceLibrary'

const roots: Root[] = []
const key = (user = 'library-test') => `memoket-workspace:${encodeURIComponent(user)}:library`
const notes: Note[] = [
  { id: 'a', user_id: 'library-test', title: 'Alpha', content: '设计需求', pinned: false, spine: '', beats: [], created_at: '2026-09-20T12:00:00Z', updated_at: '2026-09-20T12:00:00Z' },
  { id: 'b', user_id: 'library-test', title: 'Beta', content: '客户反馈', pinned: true, spine: '', beats: [], created_at: '2026-09-22T12:00:00Z', updated_at: '2026-09-22T12:00:00Z' },
]
const props = { notes, onOpen: () => {}, onNew: () => {}, onImport: () => {}, onPin: async () => {} }

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('memoket-note-user', 'library-test')
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
})
afterEach(async () => {
  await act(async () => { for (const root of roots.splice(0)) root.unmount() })
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

async function mount() {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  await act(async () => { root.render(<WorkspaceLibrary {...props} />) })
  return { host, root }
}
async function click(host: HTMLElement, label: string) {
  const button = [...host.querySelectorAll('button')].find((node) => node.getAttribute('aria-label') === label || node.textContent?.includes(label))!
  await act(async () => { button.click() })
}
async function search(host: HTMLElement, value: string) {
  const input = host.querySelector('input')!
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function sortBy(host: HTMLElement, value: 'recent' | 'name') {
  const select = host.querySelector('select')!
  await act(async () => { select.value = value; select.dispatchEvent(new Event('change', { bubbles: true })) })
}
const rowTitles = (host: HTMLElement) => [...host.querySelectorAll('.ws-library-note h2')].map((node) => node.textContent)

describe('Library preferences survive navigation without keeping temporary searches', () => {
  it('restores view and sort after remount while resetting search and the pinned filter', async () => {
    const { host, root } = await mount()
    expect(rowTitles(host)).toEqual(['Beta', 'Alpha'])
    await click(host, '列表视图')
    await sortBy(host, 'name')
    expect(rowTitles(host)).toEqual(['Alpha', 'Beta'])
    await click(host, '已固定')
    await search(host, '客户')
    expect(JSON.parse(localStorage.getItem(key())!)).toEqual({ view: 'list', sort: 'name' })
    await act(async () => { root.render(null) })
    await act(async () => { root.render(<WorkspaceLibrary {...props} />) })
    expect(host.querySelector('.ws-library-list')).not.toBeNull()
    expect(host.querySelector('select')!.value).toBe('name')
    expect(host.querySelector('input')!.value).toBe('')
    expect(rowTitles(host)).toEqual(['Alpha', 'Beta'])
    expect(host.querySelector('.ws-library-summary')!.textContent).toBe('显示 2 篇笔记')
  })

  it('keeps each user preferences separate, including a user switch on the mounted page', async () => {
    const { host, root } = await mount()
    await click(host, '列表视图')
    await sortBy(host, 'name')
    localStorage.setItem('memoket-note-user', 'another-user')
    await act(async () => { root.render(<WorkspaceLibrary {...props} />) })
    expect(host.querySelector('.ws-library-grid')).not.toBeNull()
    expect(host.querySelector('select')!.value).toBe('recent')
    await sortBy(host, 'name')
    expect(JSON.parse(localStorage.getItem(key('another-user'))!)).toEqual({ view: 'grid', sort: 'name' })
    expect(JSON.parse(localStorage.getItem(key())!)).toEqual({ view: 'list', sort: 'name' })
    localStorage.setItem('memoket-note-user', 'library-test')
    await act(async () => { root.render(<WorkspaceLibrary {...props} />) })
    expect(host.querySelector('.ws-library-list')).not.toBeNull()
  })

  it.each(['{broken', 'null', '[]', '{"view":"invalid","sort":7}'])('falls back safely for malformed preferences: %s', async (stored) => {
    localStorage.setItem(key(), stored)
    const { host } = await mount()
    expect(host.querySelector('.ws-library-grid')).not.toBeNull()
    expect(host.querySelector('select')!.value).toBe('recent')
    expect(rowTitles(host)).toEqual(['Beta', 'Alpha'])
  })

  it('keeps usable in-memory settings when storage cannot be read', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new DOMException('Blocked', 'SecurityError') })
    const { host } = await mount()
    expect(host.textContent).toContain('本机视图偏好暂不可用')
    await click(host, '列表视图')
    await sortBy(host, 'name')
    expect(host.querySelector('.ws-library-list')).not.toBeNull()
    expect(rowTitles(host)).toEqual(['Alpha', 'Beta'])
  })

  it('reports a failed preference write while applying both choices for the current session', async () => {
    const { host } = await mount()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('Full', 'QuotaExceededError') })
    await click(host, '列表视图')
    await sortBy(host, 'name')
    expect(host.querySelector('.ws-library-list')).not.toBeNull()
    expect(rowTitles(host)).toEqual(['Alpha', 'Beta'])
    expect(host.querySelector('.ws-library-preferences-error')!.textContent).toContain('本次设置仍然有效')
  })

  it('explains an empty pinned search, preserves its query when broadening scope, and counts results', async () => {
    const { host } = await mount()
    await click(host, '已固定')
    await search(host, '设计')
    expect(host.querySelector('.ws-library-summary')!.textContent).toContain('找到 0 篇已固定的笔记')
    expect(host.querySelector('.ws-library-empty')!.textContent).toContain('已固定的笔记中没有“设计”')
    await click(host, '搜索全部笔记')
    expect(host.querySelector('input')!.value).toBe('设计')
    expect(rowTitles(host)).toEqual(['Alpha'])
    expect(host.querySelector('.ws-library-summary')!.textContent).toContain('找到 1 篇笔记')
  })

  it('Escape clears search, retains focus, and never reaches the underlying key handler', async () => {
    const { host } = await mount()
    await search(host, '不存在')
    const underlying = vi.fn()
    window.addEventListener('keydown', underlying)
    const input = host.querySelector('input')!
    input.focus()
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    try {
      await act(async () => { input.dispatchEvent(event) })
      expect(event.defaultPrevented).toBe(true)
      expect(underlying).not.toHaveBeenCalled()
      expect(input.value).toBe('')
      expect(document.activeElement).toBe(input)
      expect(rowTitles(host)).toHaveLength(2)
    } finally { window.removeEventListener('keydown', underlying) }
  })
})
