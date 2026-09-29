/** Local workspace state is scoped to the current API identity. It never implies cloud sync. */
export type WorkspaceTask = { id: string; text: string; done: boolean; noteId?: string; origin?: string; carriedTo?: string }
export type PendingWorkspaceTask = { day: string; task: WorkspaceTask }

export function workspaceStorageKey(user: string, kind: 'tasks' | 'home-capture', day?: string): string {
  return `memoket-workspace:${encodeURIComponent(user)}:${kind}${day ? `:${day}` : ''}`
}

export function readWorkspaceTasks(value: string | null): WorkspaceTask[] {
  if (!value) return []
  const parsed: unknown = JSON.parse(value)
  if (!Array.isArray(parsed)) throw new Error('重点列表格式有误')
  const valid = (item: unknown): item is WorkspaceTask => typeof item === 'object' && item !== null
    && 'id' in item && 'text' in item && 'done' in item
    && typeof item.id === 'string' && typeof item.text === 'string' && typeof item.done === 'boolean'
    && (!('noteId' in item) || item.noteId === undefined || typeof item.noteId === 'string')
    && (!('origin' in item) || item.origin === undefined || typeof item.origin === 'string')
    && (!('carriedTo' in item) || item.carriedTo === undefined || typeof item.carriedTo === 'string')
  if (!parsed.every(valid)) throw new Error('重点列表格式有误，原始数据已保留')
  return parsed
}

type TaskStorage = Pick<Storage, 'getItem' | 'setItem' | 'key' | 'length'>
const taskOrigin = (task: WorkspaceTask, day: string) => task.origin ?? `${day}:${task.id}`

function pastTaskDays(storage: TaskStorage, user: string, today: string): string[] {
  const prefix = workspaceStorageKey(user, 'tasks') + ':'
  const days: string[] = []
  for (let i = 0; i < storage.length; i++) {
    const key = storage.key(i)
    if (!key?.startsWith(prefix)) continue
    const day = key.slice(prefix.length)
    if (/^\d{4}-\d{2}-\d{2}$/.test(day) && day < today) days.push(day)
  }
  return days.sort().reverse()
}

/** Newest copies win even if marking an older copy failed, including completed copies. */
export function pendingWorkspaceTasks(storage: TaskStorage, user: string, today: string, todayTasks: WorkspaceTask[]) {
  let days: string[]
  let error = ''
  try { days = pastTaskDays(storage, user, today) }
  catch { return { tasks: [] as PendingWorkspaceTask[], error: '无法读取过往重点，原始数据已保留。' } }
  const seen = new Set(todayTasks.map(task => taskOrigin(task, today)))
  const pending: PendingWorkspaceTask[] = []
  for (const day of days) {
    try {
      for (const task of readWorkspaceTasks(storage.getItem(workspaceStorageKey(user, 'tasks', day)))) {
        const origin = taskOrigin(task, day)
        if (seen.has(origin)) continue
        seen.add(origin)
        if (!task.done && !task.carriedTo) pending.push({ day, task })
      }
    } catch { error = '部分过往重点无法读取，原始数据已保留。' }
  }
  return { tasks: pending, error }
}

/** Keep the newest historical copy marked before removing the copy that currently hides it. */
export function prepareWorkspaceTaskDeletion(storage: TaskStorage, user: string, today: string, task: WorkspaceTask): void {
  if (!task.origin) return
  for (const day of pastTaskDays(storage, user, today)) {
    const key = workspaceStorageKey(user, 'tasks', day)
    const history = readWorkspaceTasks(storage.getItem(key))
    const source = history.find(item => taskOrigin(item, day) === task.origin)
    if (!source) continue
    if (!source.done && !source.carriedTo) {
      storage.setItem(key, JSON.stringify(history.map(item => item.id === source.id ? { ...item, carriedTo: today } : item)))
    }
    return
  }
}

/** Commit today's copy before annotating history. A failed first write never touches the source. */
export function carryWorkspaceTask(storage: TaskStorage, user: string, today: string, pending: PendingWorkspaceTask) {
  if (pending.day >= today) throw new Error('只能延续过去日期的重点')
  const todayKey = workspaceStorageKey(user, 'tasks', today)
  const sourceKey = workspaceStorageKey(user, 'tasks', pending.day)
  const todayTasks = readWorkspaceTasks(storage.getItem(todayKey))
  const sourceTasks = readWorkspaceTasks(storage.getItem(sourceKey))
  const source = sourceTasks.find(task => task.id === pending.task.id)
  const origin = taskOrigin(pending.task, pending.day)
  if (!source || source.done || source.carriedTo || todayTasks.some(task => taskOrigin(task, today) === origin)) {
    return { tasks: todayTasks, error: '' }
  }
  const { carriedTo: _oldTarget, ...copy } = source
  const next = [...todayTasks, { ...copy, id: crypto.randomUUID(), origin }]
  storage.setItem(todayKey, JSON.stringify(next))
  try {
    storage.setItem(sourceKey, JSON.stringify(sourceTasks.map(task => task.id === source.id ? { ...task, carriedTo: today } : task)))
    return { tasks: next, error: '' }
  } catch {
    return { tasks: next, error: '已移入今天；旧日期的存档未能标记。删除今天的任务时会先重试更新历史记录。' }
  }
}
