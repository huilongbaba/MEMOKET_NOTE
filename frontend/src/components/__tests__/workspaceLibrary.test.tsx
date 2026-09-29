// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Note } from '../../api'
import { dismissToast, getSnapshot } from '../../toast'
import Toaster from '../Toaster'
import WorkspaceLibrary from '../WorkspaceLibrary'
import type { WorkspaceNotesStatusProps } from '../WorkspaceNotesStatus'

const note = (id: string, pinned = false): Note => ({
  id, title: `笔记 ${id}`, content: '正文', pinned, user_id: 'test-user', spine: '', beats: [],
  created_at: '2026-09-22T12:00:00+00:00', updated_at: '2026-09-22T12:00:00+00:00',
})

describe('library pinning', () => {
  let host: HTMLDivElement
  let root: Root
  beforeEach(() => {
    vi.useFakeTimers()
    getSnapshot().forEach(item => dismissToast(item.id))
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
  })
  afterEach(() => {
    act(() => root.unmount())
    host.remove()
    getSnapshot().forEach(item => dismissToast(item.id))
    vi.useRealTimers()
  })
  function render(notes: Note[], onPin: (note: Note) => Promise<void>, status: WorkspaceNotesStatusProps = {}) {
    act(() => root.render(<><WorkspaceLibrary notes={notes} onOpen={vi.fn()} onNew={vi.fn()} onImport={vi.fn()} onPin={onPin} {...status} /><Toaster /></>))
  }
  function pinButton(index = 0) { return host.querySelectorAll<HTMLButtonElement>('.ws-library-pin')[index] }

  it('does not present an unreceived notes list as an empty library while loading', () => {
    render([], vi.fn().mockResolvedValue(undefined), { notesLoading: true })
    expect(host.querySelector('.ws-notes-status')?.textContent).toContain('正在读取笔记')
    expect(host.querySelector('.ws-library-empty')).toBeNull()
    expect(host.querySelector('.ws-library-summary')).toBeNull()
    expect(host.querySelector('.ws-library-filters')?.textContent).not.toContain('0')
  })

  it('keeps cached notes after an update failure and makes retry available for empty or populated lists', () => {
    const onRetry = vi.fn()
    const onPin = vi.fn().mockResolvedValue(undefined)
    render([note('cached')], onPin, { notesError: '应用后台暂不可达', onRetry })
    expect(host.querySelector('.ws-library-note h2')?.textContent).toContain('cached')
    expect(host.querySelector('.ws-notes-status')?.textContent).toContain('仍显示上次加载的笔记')
    act(() => host.querySelector<HTMLButtonElement>('.ws-notes-status button')!.click())
    expect(onRetry).toHaveBeenCalledOnce()
    render([], onPin, { notesError: '应用后台暂不可达', onRetry })
    expect(host.querySelector('.ws-library-empty')).toBeNull()
    expect(host.querySelector('.ws-notes-status')?.textContent).toContain('暂时无法读取笔记')
  })

  it('offers the empty-library action once loading has succeeded', () => {
    const onPin = vi.fn().mockResolvedValue(undefined)
    render([], onPin, { notesLoading: true })
    render([], onPin, { notesLoading: false })
    expect(host.querySelector('.ws-notes-status')).toBeNull()
    expect(host.querySelector('.ws-library-empty')?.textContent).toContain('写下第一篇笔记')
    expect(host.querySelector('.ws-library-summary')?.textContent).toContain('显示 0 篇笔记')
  })

  it('deduplicates same-frame double clicks, shows progress, and reflects confirmed props', async () => {
    let finish: () => void = () => {}
    const onPin = vi.fn(() => new Promise<void>(resolve => { finish = resolve }))
    render([note('a')], onPin)
    const button = pinButton()
    act(() => { button.click(); button.click() })
    expect(onPin).toHaveBeenCalledOnce()
    expect(button.disabled).toBe(true)
    expect(button.getAttribute('aria-busy')).toBe('true')
    expect(button.getAttribute('aria-pressed')).toBe('false')
    expect(button.querySelector('.spinner')).not.toBeNull()
    await act(async () => { finish() })
    render([note('a', true)], onPin)
    expect(pinButton().disabled).toBe(false)
    expect(pinButton().getAttribute('aria-pressed')).toBe('true')
  })

  it('keeps the original pin state on failure, reports the error visibly, and allows retry', async () => {
    const onPin = vi.fn().mockRejectedValueOnce(new Error('Failed to fetch')).mockResolvedValue(undefined)
    render([note('a', true)], onPin)
    await act(async () => { pinButton().click() })
    expect(pinButton().getAttribute('aria-pressed')).toBe('true')
    expect(pinButton().disabled).toBe(false)
    expect(host.querySelector('.toast.error')?.textContent).toContain('未能取消固定「笔记 a」')
    expect(host.querySelector('.toast.error')?.textContent).toContain('连不上应用后台')
    await act(async () => { pinButton().click() })
    expect(onPin).toHaveBeenCalledTimes(2)
    expect(pinButton().disabled).toBe(false)
  })

  it('tracks pending requests per note without blocking another note', async () => {
    const finish = new Map<string, () => void>()
    const onPin = vi.fn((item: Note) => new Promise<void>(resolve => { finish.set(item.id, resolve) }))
    render([note('a'), note('b')], onPin)
    act(() => pinButton(0).click())
    expect(pinButton(1).disabled).toBe(false)
    act(() => pinButton(1).click())
    expect(onPin).toHaveBeenCalledTimes(2)
    expect(pinButton(0).disabled).toBe(true)
    expect(pinButton(1).disabled).toBe(true)
    await act(async () => { finish.get('a')!() })
    expect(pinButton(0).disabled).toBe(false)
    expect(pinButton(1).disabled).toBe(true)
    await act(async () => { finish.get('b')!() })
    expect(pinButton(1).disabled).toBe(false)
  })
})
