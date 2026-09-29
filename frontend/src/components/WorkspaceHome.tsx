import { useEffect, useMemo, useRef, useState } from 'react'
import * as api from '../api'
import type { Note } from '../api'
import { displayTitle } from '../util/displayTitle'
import { fmtDate, fmtWhen } from '../util/time'
import { carryWorkspaceTask, pendingWorkspaceTasks, prepareWorkspaceTaskDeletion, readWorkspaceTasks, workspaceStorageKey } from '../util/workspaceState'
import type { PendingWorkspaceTask, WorkspaceTask } from '../util/workspaceState'
import Icon from './Icon'
import WorkspaceNotesStatus, { type WorkspaceNotesStatusProps } from './WorkspaceNotesStatus'
import '../workspace-home.css'

export type WorkspaceHomeProps = WorkspaceNotesStatusProps & {
  notes: Note[]
  onOpenNote: (id: string) => void
  onNewNote: () => void
  onOpenToday: () => void
  onOpenDestination: (id: string) => void
  onSearch: (query: string) => void
  onCapture: (title: string, content: string) => Promise<void>
  onRefresh: () => void
}

/** The key prevents one account's local tasks from carrying into another account. */
export default function WorkspaceHome(props: WorkspaceHomeProps) {
  const user = api.getUser()
  const [day, setDay] = useState(() => fmtDate(new Date().toISOString()))
  useEffect(() => {
    const timer = window.setInterval(() => setDay(fmtDate(new Date().toISOString())), 30_000)
    return () => window.clearInterval(timer)
  }, [])
  return <WorkspaceHomeContent key={user} {...props} user={user} day={day} />
}

function WorkspaceHomeContent({ notes, notesLoading, notesError, onRetry, onRefresh, onOpenNote, onNewNote, onOpenToday, onOpenDestination, user, day }: WorkspaceHomeProps & { user: string; day: string }) {
  const [newTask, setNewTask] = useState('')
  const [taskNote, setTaskNote] = useState('')
  const [showCarryover, setShowCarryover] = useState(false)
  const taskInput = useRef<HTMLInputElement>(null)
  const taskKey = workspaceStorageKey(user, 'tasks', day)
  const [taskStore, setTaskStore] = useState<{ key: string; tasks: WorkspaceTask[]; error: string }>(() => {
    try { return { key: taskKey, tasks: readWorkspaceTasks(localStorage.getItem(taskKey)), error: '' } }
    catch { return { key: taskKey, tasks: [], error: '无法读取本机重点列表。新添加的内容仍可在当前窗口使用。' } }
  })
  // A new day resets only the daily list, preserving any capture the user is still writing.
  useEffect(() => {
    if (taskStore.key === taskKey) return
    try { setTaskStore({ key: taskKey, tasks: readWorkspaceTasks(localStorage.getItem(taskKey)), error: '' }) }
    catch { setTaskStore({ key: taskKey, tasks: [], error: '无法读取本机重点列表。新添加的内容仍可在当前窗口使用。' }) }
  }, [taskKey, taskStore.key])
  const tasks = taskStore.key === taskKey ? taskStore.tasks : []
  const pastTasks = useMemo(() => {
    try { return pendingWorkspaceTasks(localStorage, user, day, taskStore.key === taskKey ? taskStore.tasks : []) }
    catch { return { tasks: [], error: '无法读取过往重点，原始数据已保留。' } }
  }, [user, day, taskKey, taskStore])
  const completed = tasks.filter(task => task.done).length
  const recentNotes = useMemo(() => [...notes].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)).slice(0, 4), [notes])
  const dateLabel = new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }).format(new Date(`${day}T12:00:00`))

  function updateTasks(next: WorkspaceTask[], removedTask?: WorkspaceTask): boolean {
    try {
      // Never overwrite an unreadable record with the empty-state fallback.
      const latest = readWorkspaceTasks(localStorage.getItem(taskKey))
      if (JSON.stringify(latest) !== JSON.stringify(tasks)) {
        setTaskStore({ key: taskKey, tasks: latest, error: '另一窗口已更新今日重点，已加载最新内容。你的输入仍保留，请重试刚才的操作。' })
        return false
      }
      if (removedTask) {
        try { prepareWorkspaceTaskDeletion(localStorage, user, day, removedTask) }
        catch {
          setTaskStore(previous => ({ ...previous, error: '无法更新这项重点的历史记录，已保留今天的任务，避免旧任务再次出现。请稍后重试删除。' }))
          return false
        }
      }
      localStorage.setItem(taskKey, JSON.stringify(next))
      setTaskStore({ key: taskKey, tasks: next, error: '' })
      return true
    } catch {
      setTaskStore(previous => ({ ...previous, error: '无法保存重点修改，原任务已保留。请稍后重试。' }))
      return false
    }
  }

  function addTask() {
    if (!newTask.trim()) return
    if (!updateTasks([...tasks, { id: crypto.randomUUID(), text: newTask.trim(), done: false, ...(taskNote ? { noteId: taskNote } : {}) }])) return
    setNewTask('')
    setTaskNote('')
    taskInput.current?.focus()
  }

  function carryTask(pending: PendingWorkspaceTask) {
    try {
      const moved = carryWorkspaceTask(localStorage, user, day, pending)
      setTaskStore({ key: taskKey, ...moved })
    } catch {
      setTaskStore(previous => ({ ...previous, error: '未能移入今天，原任务仍在待延续列表中。请稍后重试。' }))
    }
  }

  return <div className="ws-home">
    <div className="ws-home-inner">
      <header className="ws-home-heading">
        <div className="ws-home-date"><span className="ws-eyebrow">TODAY</span><span className="ws-date-separator" />{dateLabel}</div>
        <h1>把注意力，留给重要的事。</h1>
      </header>


      <div className="ws-home-columns">
        <div className="ws-home-main">
          <section className="ws-priorities" aria-labelledby="ws-priorities-heading">
            <div className="ws-section-heading"><div><h2 id="ws-priorities-heading">今日重点{tasks.length > 0 && <span className="ws-task-count">{completed}/{tasks.length}</span>}</h2><span>不用做完所有事，先做好重要的事</span></div><div className="ws-priority-actions">{pastTasks.tasks.length > 0 && <button className="ws-text-button ws-carryover-toggle" type="button" aria-expanded={showCarryover} aria-controls="ws-carryover-list" onClick={() => setShowCarryover(open => !open)}><Icon n="bx-history" />待延续 <span>{pastTasks.tasks.length}</span></button>}<span className="ws-local-label"><Icon n="bx-desktop" />仅存于本机</span></div></div>
            {showCarryover && pastTasks.tasks.length > 0 && <ul id="ws-carryover-list" className="ws-carryover-list" aria-label="过往未完成的重点">{pastTasks.tasks.map(item => <li key={`${item.day}:${item.task.id}`}><span><time dateTime={item.day}>{item.day.slice(5).replace('-', '/')}</time><span>{item.task.text}</span></span><button className="ws-text-button" type="button" aria-label={`移入今天：${item.task.text}`} onClick={() => carryTask(item)}>移入今天<Icon n="bx-right-arrow-alt" /></button></li>)}</ul>}
            <div className="ws-task-panel">
              {tasks.length > 0 ? <ul className="ws-task-list">{tasks.map(task => {
                const linkedNote = task.noteId ? notes.find(note => note.id === task.noteId) : undefined
                return <li className={`ws-task ${task.done ? 'ws-task-done' : ''}`} key={task.id}>
                  <label className="ws-task-label"><input type="checkbox" checked={task.done} onChange={() => updateTasks(tasks.map(item => item.id === task.id ? { ...item, done: !item.done } : item))} /><span className="ws-task-check"><Icon n="bx-check" /></span><span className="ws-task-text">{task.text}</span></label>
                  {linkedNote && <button type="button" className="ws-task-note" title={`打开关联笔记：${displayTitle(linkedNote)}`} onClick={() => onOpenNote(linkedNote.id)}><Icon n="bx-link-alt" /><span>{displayTitle(linkedNote)}</span></button>}
                  <button type="button" className="ws-icon-button ws-task-delete" aria-label={`删除重点：${task.text}`} onClick={() => updateTasks(tasks.filter(item => item.id !== task.id), task)}><Icon n="bx-x" /></button>
                </li>
              })}</ul> : <div className="ws-tasks-empty"><Icon n="bx-check-circle" /><p>给今天选一件值得投入的事。</p></div>}
              <form className="ws-task-add" onSubmit={event => { event.preventDefault(); addTask() }}>
                <div className="ws-task-add-line"><Icon n="bx-plus" /><input ref={taskInput} aria-label="添加今日重点" value={newTask} onChange={event => setNewTask(event.target.value)} placeholder="添加一件重要的事…" maxLength={240} /><button className="ws-text-button" type="submit" disabled={!newTask.trim()} title="输入一件要做的事后添加">添加</button></div>
                {newTask.trim() && notes.length > 0 && <div className="ws-task-link-field"><Icon n="bx-link-alt" /><select aria-label="关联笔记（可选）" value={taskNote} onChange={event => setTaskNote(event.target.value)}><option value="">关联笔记（可选）</option>{notes.map(note => <option key={note.id} value={note.id}>{displayTitle(note)}</option>)}</select></div>}
              </form>
            </div>
            {taskStore.error && <p className="ws-storage-error" role="alert">{taskStore.error}</p>}
            {pastTasks.error && <p className="ws-storage-error" role="alert">{pastTasks.error}</p>}
          </section>

          <section className="ws-recent" aria-labelledby="ws-recent-heading">
            <div className="ws-section-heading"><div><h2 id="ws-recent-heading">继续工作</h2><span>从上次停下的地方继续</span></div><div className="ws-section-actions"><button className="ws-icon-button" type="button" title="刷新最近笔记" aria-label="刷新最近笔记" onClick={onRefresh}><Icon n="bx-refresh" /></button><button className="ws-text-button" type="button" onClick={() => onOpenDestination('app:notes')}>查看全部<Icon n="bx-right-arrow-alt" /></button></div></div>
            <WorkspaceNotesStatus notesLoading={notesLoading} notesError={notesError} onRetry={onRetry ?? onRefresh} hasNotes={recentNotes.length > 0} />
            {recentNotes.length ? <div className="ws-recent-grid">{recentNotes.map(note => <button type="button" className="ws-note-card" key={note.id} onClick={() => onOpenNote(note.id)}>
              <span className="ws-note-card-top"><span className="ws-note-icon"><Icon n={note.icon || 'bx-file'} /></span>{note.pinned && <Icon n="bx-pin" className="ws-note-pin" />}<Icon n="bx-link-external" className="ws-note-open" /></span>
              <strong>{displayTitle(note)}</strong>
              <span className="ws-note-preview">{note.content.replace(/^#+\s*/gm, '').replace(/[*`>]/g, '').replace(/\n+/g, ' ').trim() || '留一页空白，等一个好想法。'}</span>
              <span className="ws-note-meta"><span>{note.source ? '导入笔记' : '笔记'}</span><span>{fmtWhen(note.updated_at)}</span></span>
            </button>)}</div> : notesLoading || notesError ? null : <div className="ws-notes-empty"><div className="ws-empty-note-mark"><Icon n="bx-notepad" /><span /></div><div><h3>下一件重要的事，从一页笔记开始。</h3><p>记录灵感、整理项目，让散落的信息有处可寻。</p><button className="ws-text-button" type="button" onClick={onNewNote}>写下第一篇笔记<Icon n="bx-right-arrow-alt" /></button></div></div>}
          </section>
        </div>

        <aside className="ws-home-aside" aria-label="快捷入口">
          <section className="ws-quick-access" aria-labelledby="ws-quick-heading">
            <h2 id="ws-quick-heading">触手可及</h2>
            <button type="button" className="ws-quick-link" onClick={onOpenToday}><span className="ws-quick-icon"><Icon n="bx-calendar-event" /></span><span><strong>今日笔记</strong><small>把今天的想法放在一起</small></span><Icon n="bx-chevron-right" /></button>
            <button type="button" className="ws-quick-link" onClick={() => onOpenDestination('app:journey')}><span className="ws-quick-icon"><Icon n="bx-desktop" /></span><span><strong>屏幕活动</strong><small>找回刚刚工作的上下文</small></span><Icon n="bx-chevron-right" /></button>
            <button type="button" className="ws-quick-link" onClick={() => onOpenDestination('app:import')}><span className="ws-quick-icon"><Icon n="bx-import" /></span><span><strong>导入已有内容</strong><small>让散落的资料回到一处</small></span><Icon n="bx-chevron-right" /></button>
          </section>
          <p className="ws-home-footnote"><Icon n="bx-leaf" />少一点切换，多一点心流。</p>
        </aside>
      </div>
    </div>
  </div>
}
