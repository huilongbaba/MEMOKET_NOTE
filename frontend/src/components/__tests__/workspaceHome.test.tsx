// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import WorkspaceHome, { type WorkspaceHomeProps } from '../WorkspaceHome'
import * as api from '../../api'
import { carryWorkspaceTask, pendingWorkspaceTasks, prepareWorkspaceTaskDeletion, readWorkspaceTasks, workspaceStorageKey } from '../../util/workspaceState'

vi.mock('../../api', () => ({ getUser: vi.fn(() => 'workspace-a') }))

describe('workspace home interactions', () => {
  let host: HTMLDivElement
  let root: Root
  let props: WorkspaceHomeProps
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-22T12:00:00'))
    localStorage.clear()
    vi.mocked(api.getUser).mockReturnValue('workspace-a')
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
    props = { notes: [], onOpenNote: vi.fn(), onNewNote: vi.fn(), onOpenToday: vi.fn(), onOpenDestination: vi.fn(), onSearch: vi.fn(), onCapture: vi.fn().mockResolvedValue(undefined), onRefresh: vi.fn() }
  })
  afterEach(() => {
    act(() => root.unmount())
    host.remove()
    vi.restoreAllMocks()
    vi.useRealTimers()
  })
  function render() { act(() => root.render(<WorkspaceHome {...props} />)) }
  function click(label: string) {
    const button = [...host.querySelectorAll('button')].find(item => item.textContent?.trim() === label)
    expect(button).toBeTruthy()
    act(() => button!.click())
  }
  function type(selector: string, text: string) {
    const input = host.querySelector(selector) as HTMLInputElement | HTMLTextAreaElement
    const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
    act(() => {
      Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(input, text)
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
  }

  it('routes search and quick entries to real parent actions without adding example notes', () => {
    render()
    expect(host.querySelectorAll('.ws-note-card')).toHaveLength(0)
    expect(host.querySelector('textarea')).toBeNull()
    const journey = host.querySelectorAll<HTMLButtonElement>('.ws-quick-link')[1]
    act(() => journey.click())
    expect(props.onOpenDestination).toHaveBeenCalledWith('app:journey')
    click('写下第一篇笔记')
    expect(props.onNewNote).toHaveBeenCalledOnce()
  })

  it('shows loading only in recent notes while local priorities remain usable', () => {
    localStorage.setItem(workspaceStorageKey('workspace-a', 'tasks', '2026-09-22'), JSON.stringify([{ id: 'local', text: '本机重点仍可用', done: false }]))
    props.notesLoading = true
    render()
    expect(host.querySelector('.ws-recent')?.textContent).toContain('正在读取笔记')
    expect(host.querySelector('.ws-notes-empty')).toBeNull()
    expect(host.querySelector('.ws-task')?.textContent).toContain('本机重点仍可用')
    expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')?.disabled).toBe(false)
  })

  it('shows a retryable notes error without hiding cached notes or claiming an empty library', () => {
    props.notesError = '应用后台暂不可达'
    props.onRetry = vi.fn()
    props.notes = [{ id: 'cached', title: '已加载的笔记', content: '正文', pinned: false, user_id: 'workspace-a', spine: '', beats: [], created_at: '2026-09-22T01:00:00Z', updated_at: '2026-09-22T01:00:00Z' }]
    render()
    expect(host.querySelector('.ws-note-card')?.textContent).toContain('已加载的笔记')
    expect(host.querySelector('.ws-notes-status')?.textContent).toContain('仍显示上次加载的笔记')
    click('重试')
    expect(props.onRetry).toHaveBeenCalledOnce()
    props.notes = []
    render()
    expect(host.querySelector('.ws-notes-status')?.textContent).toContain('暂时无法读取笔记')
    expect(host.querySelector('.ws-notes-empty')).toBeNull()
  })

  it('shows the first-note action only after an empty notes request has completed successfully', () => {
    props.notesLoading = true
    render()
    expect(host.querySelector('.ws-notes-empty')).toBeNull()
    props.notesLoading = false
    render()
    expect(host.querySelector('.ws-notes-status')).toBeNull()
    expect(host.querySelector('.ws-notes-empty')?.textContent).toContain('写下第一篇笔记')
  })

  it('persists checked tasks and isolates them from another user', () => {
    render()
    type('input[aria-label="添加今日重点"]', '准备设计评审')
    const form = host.querySelector('form')!
    act(() => { form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
    act(() => host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click())
    const stored = JSON.parse(localStorage.getItem(workspaceStorageKey('workspace-a', 'tasks', '2026-09-22'))!)
    expect(stored).toEqual([expect.objectContaining({ text: '准备设计评审', done: true })])
    vi.mocked(api.getUser).mockReturnValue('workspace-b')
    render()
    expect(host.querySelector('.ws-task')).toBeNull()
    vi.mocked(api.getUser).mockReturnValue('workspace-a')
    render()
    expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked).toBe(true)
    act(() => host.querySelector<HTMLButtonElement>('button[aria-label="删除重点：准备设计评审"]')!.click())
    expect(host.querySelector('.ws-task')).toBeNull()
  })

  it('offers only this account’s past unfinished tasks and moves them only after an explicit click', () => {
    const sourceKey = workspaceStorageKey('workspace-a', 'tasks', '2026-09-21')
    localStorage.setItem(sourceKey, JSON.stringify([{ id: 'old', text: '延续评审准备', done: false, noteId: 'linked-note' }, { id: 'done', text: '已经完成', done: true }]))
    localStorage.setItem(workspaceStorageKey('workspace-b', 'tasks', '2026-09-21'), JSON.stringify([{ id: 'other', text: '其他账号的重点', done: false }]))
    render()
    expect(host.querySelector('.ws-task')).toBeNull()
    expect(host.querySelector('.ws-carryover-toggle')?.textContent).toContain('待延续 1')
    expect(host.querySelector('.ws-carryover-list')).toBeNull()
    act(() => host.querySelector<HTMLButtonElement>('.ws-carryover-toggle')!.click())
    expect(host.querySelector('.ws-carryover-list')?.textContent).toContain('延续评审准备')
    expect(host.textContent).not.toContain('其他账号的重点')
    const move = host.querySelector<HTMLButtonElement>('[aria-label="移入今天：延续评审准备"]')!
    act(() => { move.click(); move.click() })
    const today = readWorkspaceTasks(localStorage.getItem(workspaceStorageKey('workspace-a', 'tasks', '2026-09-22')))
    expect(today).toHaveLength(1)
    expect(today[0]).toMatchObject({ text: '延续评审准备', done: false, noteId: 'linked-note', origin: '2026-09-21:old' })
    expect(readWorkspaceTasks(localStorage.getItem(sourceKey))[0]).toMatchObject({ text: '延续评审准备', carriedTo: '2026-09-22' })
    expect(host.querySelector('.ws-task')?.textContent).toContain('延续评审准备')
    expect(host.querySelector('.ws-carryover-toggle')).toBeNull()
    expect(props.onCapture).not.toHaveBeenCalled()
  })

  it('keeps the historical task when saving its move fails', () => {
    const sourceKey = workspaceStorageKey('workspace-a', 'tasks', '2026-09-21')
    const original = JSON.stringify([{ id: 'old', text: '不能丢失的重点', done: false }])
    localStorage.setItem(sourceKey, original)
    render()
    act(() => host.querySelector<HTMLButtonElement>('.ws-carryover-toggle')!.click())
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('Quota exceeded') })
    act(() => host.querySelector<HTMLButtonElement>('[aria-label="移入今天：不能丢失的重点"]')!.click())
    expect(localStorage.getItem(sourceKey)).toBe(original)
    expect(host.querySelector('.ws-task')).toBeNull()
    expect(host.querySelector('.ws-carryover-list')?.textContent).toContain('不能丢失的重点')
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('原任务仍在待延续列表')
  })

  it('does not remove a visible task or clear a new task draft when storage fails', () => {
    localStorage.setItem(workspaceStorageKey('workspace-a', 'tasks', '2026-09-22'), JSON.stringify([{ id: 'existing', text: '已有重点', done: false }]))
    render()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('Quota exceeded') })
    act(() => host.querySelector<HTMLButtonElement>('[aria-label="删除重点：已有重点"]')!.click())
    expect(host.querySelector('.ws-task')?.textContent).toContain('已有重点')
    type('input[aria-label="添加今日重点"]', '新的重点草稿')
    act(() => { host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
    expect(host.querySelector<HTMLInputElement>('[aria-label="添加今日重点"]')!.value).toBe('新的重点草稿')
    expect(host.querySelectorAll('.ws-task')).toHaveLength(1)
  })

  it('loads concurrent changes before retrying a task update instead of overwriting another window', () => {
    const key = workspaceStorageKey('workspace-a', 'tasks', '2026-09-22')
    const existing = { id: 'existing', text: '原有重点', done: false }
    const remote = { id: 'remote', text: '另一窗口新增', done: false }
    localStorage.setItem(key, JSON.stringify([existing]))
    render()
    localStorage.setItem(key, JSON.stringify([existing, remote]))
    act(() => host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click())
    expect(readWorkspaceTasks(localStorage.getItem(key))).toEqual([existing, remote])
    expect(host.querySelectorAll('.ws-task')).toHaveLength(2)
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('另一窗口已更新')
    expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false)
    act(() => host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click())
    expect(readWorkspaceTasks(localStorage.getItem(key))).toEqual([{ ...existing, done: true }, remote])
    localStorage.setItem(key, JSON.stringify([{ ...existing, done: true }, { ...remote, done: true }]))
    act(() => host.querySelector<HTMLButtonElement>('[aria-label="删除重点：原有重点"]')!.click())
    expect(readWorkspaceTasks(localStorage.getItem(key))).toHaveLength(2)
    act(() => host.querySelector<HTMLButtonElement>('[aria-label="删除重点：原有重点"]')!.click())
    expect(readWorkspaceTasks(localStorage.getItem(key))).toEqual([{ ...remote, done: true }])
  })

  it('preserves a new task draft during a concurrent update and saves it on retry', () => {
    const key = workspaceStorageKey('workspace-a', 'tasks', '2026-09-22')
    render()
    type('input[aria-label="添加今日重点"]', '当前窗口的输入')
    const remote = { id: 'remote', text: '另一窗口新增', done: false }
    localStorage.setItem(key, JSON.stringify([remote]))
    click('添加')
    expect(readWorkspaceTasks(localStorage.getItem(key))).toEqual([remote])
    expect(host.querySelector<HTMLInputElement>('[aria-label="添加今日重点"]')!.value).toBe('当前窗口的输入')
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('请重试刚才的操作')
    click('添加')
    expect(readWorkspaceTasks(localStorage.getItem(key))).toEqual([remote, expect.objectContaining({ text: '当前窗口的输入', done: false })])
    expect(host.querySelector<HTMLInputElement>('[aria-label="添加今日重点"]')!.value).toBe('')
  })

  it('keeps a carried task until its source can be marked, then deletes it without offering it again', () => {
    const sourceKey = workspaceStorageKey('workspace-a', 'tasks', '2026-09-21')
    const todayKey = workspaceStorageKey('workspace-a', 'tasks', '2026-09-22')
    const source = { id: 'source', text: '延续的重点', done: false }
    localStorage.setItem(sourceKey, JSON.stringify([source]))
    const setItem = Storage.prototype.setItem
    const write = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key, value) {
      if (key === sourceKey) throw new DOMException('Cannot update history')
      setItem.call(this, key, value)
    })
    const moved = carryWorkspaceTask(localStorage, 'workspace-a', '2026-09-22', { day: '2026-09-21', task: source })
    render()
    act(() => host.querySelector<HTMLButtonElement>('[aria-label="删除重点：延续的重点"]')!.click())
    expect(readWorkspaceTasks(localStorage.getItem(todayKey))).toEqual(moved.tasks)
    expect(host.querySelector('.ws-task')?.textContent).toContain('延续的重点')
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('已保留今天的任务')
    write.mockRestore()
    act(() => host.querySelector<HTMLButtonElement>('[aria-label="删除重点：延续的重点"]')!.click())
    expect(readWorkspaceTasks(localStorage.getItem(sourceKey))).toEqual([{ ...source, carriedTo: '2026-09-22' }])
    expect(readWorkspaceTasks(localStorage.getItem(todayKey))).toEqual([])
    expect(host.querySelector('.ws-task')).toBeNull()
    expect(host.querySelector('.ws-carryover-toggle')).toBeNull()
    expect(pendingWorkspaceTasks(localStorage, 'workspace-a', '2026-09-23', []).tasks).toHaveLength(0)
  })

  it('shows four recent notes and opens the full library', () => {
    props.notes = Array.from({ length: 7 }, (_, i) => ({ id: `note-${i}`, title: `笔记 ${i}`, content: '正文', pinned: false, user_id: 'workspace-a', spine: '', beats: [], created_at: '2026-09-22T01:00:00Z', updated_at: `2026-09-22T0${i}:00:00Z` }))
    render()
    expect(host.querySelectorAll('.ws-note-card')).toHaveLength(4)
    expect(host.querySelector('.ws-note-card strong')?.textContent).toBe('笔记 6')
    click('查看全部')
    expect(props.onOpenDestination).toHaveBeenCalledWith('app:notes')
    const main = host.querySelector('.ws-home-main')!
    expect(main.firstElementChild?.className).toBe('ws-priorities')
  })

  it('starts a fresh daily task list at midnight', () => {
    vi.setSystemTime(new Date('2026-09-22T23:59:50'))
    render()
    type('input[aria-label="添加今日重点"]', '昨天的重点')
    act(() => { host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
    act(() => { vi.advanceTimersByTime(30_000) })
    expect(host.querySelector('.ws-task')).toBeNull()
    expect(localStorage.getItem(workspaceStorageKey('workspace-a', 'tasks', '2026-09-22'))).toContain('昨天的重点')
  })
})

describe('safe task carryover', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.restoreAllMocks())

  it('deduplicates an unmarked source after a partial write and follows the latest completed copy', () => {
    const sourceKey = workspaceStorageKey('a', 'tasks', '2026-09-20')
    const original = JSON.stringify([{ id: 'old', text: '评审准备', done: false }])
    localStorage.setItem(sourceKey, original)
    const setItem = Storage.prototype.setItem
    const write = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key, value) {
      if (key === sourceKey) throw new DOMException('Cannot update history')
      setItem.call(this, key, value)
    })
    const moved = carryWorkspaceTask(localStorage, 'a', '2026-09-21', { day: '2026-09-20', task: { id: 'old', text: '评审准备', done: false } })
    expect(moved.tasks).toHaveLength(1)
    expect(moved.error).toContain('旧日期的存档未能标记')
    expect(localStorage.getItem(sourceKey)).toBe(original)
    expect(pendingWorkspaceTasks(localStorage, 'a', '2026-09-21', moved.tasks).tasks).toHaveLength(0)
    const nextDay = pendingWorkspaceTasks(localStorage, 'a', '2026-09-22', [])
    expect(nextDay.tasks).toHaveLength(1)
    expect(nextDay.tasks[0].day).toBe('2026-09-21')
    write.mockRestore()
    localStorage.setItem(workspaceStorageKey('a', 'tasks', '2026-09-21'), JSON.stringify(moved.tasks.map(task => ({ ...task, done: true }))))
    expect(pendingWorkspaceTasks(localStorage, 'a', '2026-09-22', []).tasks).toHaveLength(0)
  })

  it('leaves malformed historical data untouched while offering other valid dates', () => {
    const malformedKey = workspaceStorageKey('a', 'tasks', '2026-09-20')
    const malformed = '[{"id":"bad","text":42,"done":false}]'
    localStorage.setItem(malformedKey, malformed)
    localStorage.setItem(workspaceStorageKey('a', 'tasks', '2026-09-21'), JSON.stringify([{ id: 'good', text: '可以继续', done: false }]))
    const result = pendingWorkspaceTasks(localStorage, 'a', '2026-09-22', [])
    expect(result.tasks).toHaveLength(1)
    expect(result.error).toContain('原始数据已保留')
    expect(localStorage.getItem(malformedKey)).toBe(malformed)
  })

  it('marks the newest source across repeated partial carries without touching another account', () => {
    const original = { id: 'original', text: '多日延续', done: false }
    const yesterday = { ...original, id: 'yesterday', origin: '2026-09-20:original' }
    const today = { ...yesterday, id: 'today' }
    const oldestKey = workspaceStorageKey('a', 'tasks', '2026-09-20')
    const yesterdayKey = workspaceStorageKey('a', 'tasks', '2026-09-21')
    const otherUserKey = workspaceStorageKey('a:other', 'tasks', '2026-09-21')
    localStorage.setItem(oldestKey, JSON.stringify([original]))
    localStorage.setItem(yesterdayKey, JSON.stringify([yesterday]))
    localStorage.setItem(otherUserKey, JSON.stringify([yesterday]))
    prepareWorkspaceTaskDeletion(localStorage, 'a', '2026-09-22', today)
    expect(readWorkspaceTasks(localStorage.getItem(yesterdayKey))).toEqual([{ ...yesterday, carriedTo: '2026-09-22' }])
    expect(readWorkspaceTasks(localStorage.getItem(oldestKey))).toEqual([original])
    expect(readWorkspaceTasks(localStorage.getItem(otherUserKey))).toEqual([yesterday])
    expect(pendingWorkspaceTasks(localStorage, 'a', '2026-09-22', []).tasks).toHaveLength(0)
    expect(pendingWorkspaceTasks(localStorage, 'a', '2026-09-23', []).tasks).toHaveLength(0)
  })
})
