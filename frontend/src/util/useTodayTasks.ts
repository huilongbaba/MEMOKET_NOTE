/** 今天的待办：灵动岛和工作台首页读写同一份本机列表（workspaceStorageKey(user, 'tasks', day)）。
 *  同一扇窗口里的改动靠自定义事件通知，另一扇窗口靠 storage 事件；每 30 秒看一眼日期有没有翻篇。
 *  每次改动都先读一遍最新存档再按 id 增删改，不会把另一扇窗口刚写的东西盖掉。 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fmtDate } from './time'
import { carryWorkspaceTask, pendingWorkspaceTasks, prepareWorkspaceTaskDeletion, readWorkspaceTasks, workspaceStorageKey } from './workspaceState'
import type { PendingWorkspaceTask, WorkspaceTask } from './workspaceState'

const CHANGE_EVENT = 'workspace-tasks-changed'
export const TASKS_READ_ERROR = '无法读取本机待办，新添加的内容仍可在当前窗口使用。'
export const TASKS_WRITE_ERROR = '待办暂未保存到本机，关闭窗口后可能丢失。'
export const TASKS_HISTORY_ERROR = '无法更新这件事的历史记录，先保留它，稍后再试删除。'
export const TASKS_CARRY_ERROR = '未能移入今天，原来的待办仍在。'

/** raw is the stored string the list was read from (undefined when storage could not be read). */
type Store = { day: string; key: string; raw: string | null | undefined; tasks: WorkspaceTask[]; error: string }
const today = () => fmtDate(new Date().toISOString())
function read(user: string, fallback?: Store): Store {
  const day = today()
  const key = workspaceStorageKey(user, 'tasks', day)
  try { const raw = localStorage.getItem(key); return { day, key, raw, tasks: readWorkspaceTasks(raw), error: '' } }
  catch { return { day, key, raw: undefined, tasks: fallback?.key === key ? fallback.tasks : [], error: TASKS_READ_ERROR } }
}

export type TodayTasks = {
  day: string
  tasks: WorkspaceTask[]
  /** 还没做完的，按原顺序；第一件就是收起后岛上显示的那件。 */
  open: WorkspaceTask[]
  /** 前几天没做完、还没移到今天的。 */
  pending: PendingWorkspaceTask[]
  error: string
  add(text: string): void
  toggle(id: string): void
  remove(id: string): void
  carryAll(): void
}

export function useTodayTasks(user: string): TodayTasks {
  const [store, setStore] = useState<Store>(() => read(user))
  const live = useRef(store)
  live.current = store

  const refresh = useCallback(() => {
    const next = read(user, live.current)
    // A change that could not be written stays in this window as long as the stored record has not moved on.
    if (live.current.error === TASKS_WRITE_ERROR && next.key === live.current.key && next.raw === live.current.raw) return
    setStore(previous => previous.key === next.key && previous.error === next.error && JSON.stringify(previous.tasks) === JSON.stringify(next.tasks) ? previous : next)
  }, [user])

  useEffect(() => {
    refresh()
    const prefix = workspaceStorageKey(user, 'tasks') + ':'
    const onStorage = (event: StorageEvent) => { if (event.key === null || event.key.startsWith(prefix)) refresh() }
    const onChange = (event: Event) => { const detail = (event as CustomEvent<{ user: string }>).detail; if (!detail || detail.user === user) refresh() }
    const onVisibility = () => { if (document.visibilityState === 'visible') refresh() }
    const interval = window.setInterval(refresh, 30_000)
    window.addEventListener('storage', onStorage)
    window.addEventListener(CHANGE_EVENT, onChange)
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener('storage', onStorage)
      window.removeEventListener(CHANGE_EVENT, onChange)
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [user, refresh])

  const announce = useCallback(() => window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: { user } })), [user])

  const commit = useCallback((mutate: (current: WorkspaceTask[]) => WorkspaceTask[], removed?: WorkspaceTask) => {
    const current = read(user, live.current)
    const next = mutate(current.tasks)
    // An unreadable record is never overwritten with the in-memory fallback; the change lives on in this window only.
    if (current.error) { setStore({ ...current, tasks: next, error: TASKS_WRITE_ERROR }); return }
    if (removed) {
      try { prepareWorkspaceTaskDeletion(localStorage, user, current.day, removed) }
      catch { setStore({ ...current, error: TASKS_HISTORY_ERROR }); return }
    }
    const raw = JSON.stringify(next)
    try { localStorage.setItem(current.key, raw) }
    catch { setStore({ ...current, tasks: next, error: TASKS_WRITE_ERROR }); return }
    setStore({ ...current, raw, tasks: next, error: '' })
    announce()
  }, [user, announce])

  const pending = useMemo(() => {
    try { return pendingWorkspaceTasks(localStorage, user, store.day, store.tasks).tasks }
    catch { return [] }
  }, [user, store.day, store.tasks])

  const carryAll = useCallback(() => {
    const current = read(user, live.current)
    let tasks = current.tasks
    let error = current.error
    for (const item of pending) {
      try {
        const moved = carryWorkspaceTask(localStorage, user, current.day, item)
        tasks = moved.tasks
        if (moved.error) error = moved.error
      } catch { error = TASKS_CARRY_ERROR }
    }
    setStore({ ...read(user, current), tasks, error })
    announce()
  }, [user, pending, announce])

  return useMemo<TodayTasks>(() => ({
    day: store.day,
    tasks: store.tasks,
    open: store.tasks.filter(task => !task.done && !task.carriedTo),
    pending,
    error: store.error,
    add: (text) => { const value = text.trim(); if (value) commit(current => [...current, { id: crypto.randomUUID(), text: value, done: false }]) },
    toggle: (id) => commit(current => current.map(task => task.id === id ? { ...task, done: !task.done } : task)),
    remove: (id) => {
      const removed = live.current.tasks.find(task => task.id === id)
      commit(current => current.filter(task => task.id !== id), removed)
    },
    carryAll,
  }), [store, pending, commit, carryAll])
}
