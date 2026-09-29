/** 灵动岛 · 待办：今天要做的几件事，与工作台首页「今日重点」是同一份本机列表。
 *  没有标题、没有说明：一列能勾掉的事，底部一行「添加」。没做完的在上，做完的沉到下面变淡。 */
import { useEffect, useRef, useState } from 'react'
import type { TodayTasks } from '../util/useTodayTasks'
import Icon from './Icon'
import '../companion-tasks.css'

type Props = {
  store: TodayTasks
  /** Bumped by the island when the panel was entered from the keyboard: put the caret in the add line. */
  focusRequested: number
  /** Escape on an empty add line hands over to the island (which collapses). */
  onEscape: () => void
}

export default function CompanionTasks({ store, focusRequested, onEscape }: Props) {
  const [text, setText] = useState('')
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => { if (focusRequested) input.current?.focus() }, [focusRequested])
  const { tasks, open, pending, error } = store
  const ordered = [...open, ...tasks.filter(task => task.done)]
  const allDone = tasks.length > 0 && open.length === 0

  function submit() {
    const value = text.trim()
    if (!value) return
    store.add(value)
    setText('')
    input.current?.focus()
  }

  return <section className="dc-tasks" aria-label="待办">
    {allDone && <p className="dc-tasks-done" role="status"><Icon n="bx-check" />今天的事都做完了</p>}
    {tasks.length > 0 ? <ul className="dc-tasks-list" aria-label="今天的待办">
      {ordered.map(task => <li key={task.id} className={'dc-task' + (task.done ? ' dc-task-done' : '')}>
        <button type="button" role="checkbox" aria-checked={task.done} className="dc-task-check" aria-label={task.done ? `恢复：${task.text}` : `完成：${task.text}`} title={task.done ? '恢复为未完成' : '标记完成'} onClick={() => store.toggle(task.id)}><Icon n="bx-check" /></button>
        <span className="dc-task-text">{task.text}</span>
        <button type="button" className="dc-task-remove" aria-label={`删除待办：${task.text}`} title="删除" onClick={() => store.remove(task.id)}><Icon n="bx-x" /></button>
      </li>)}
    </ul> : <div className="dc-tasks-empty"><span className="dc-tasks-empty-ring" aria-hidden="true" /><p>今天还没有待办</p><small>写下一件要做的事。收起以后，下一件会留在岛上。</small></div>}
    {pending.length > 0 && <button type="button" className="dc-tasks-carry" aria-label={`前几天还有 ${pending.length} 件没做完，移到今天`} title="把前几天没做完的移到今天" onClick={store.carryAll}><span>前几天还有 {pending.length} 件没做完</span><span className="dc-tasks-carry-action">移到今天<Icon n="bx-right-arrow-alt" /></span></button>}
    {error && <p className="dc-tasks-error" role="alert"><Icon n="bx-error" />{error}</p>}
    <form className="dc-tasks-add" onSubmit={event => { event.preventDefault(); submit() }}>
      <Icon n="bx-plus" />
      <input ref={input} aria-label="添加待办" placeholder="添加一件要做的事…" maxLength={240} value={text} onChange={event => setText(event.target.value)}
        onKeyDown={event => {
          if (event.key !== 'Escape' || event.nativeEvent.isComposing) return
          event.preventDefault()
          event.stopPropagation()
          if (text) setText('')
          else onEscape()
        }} />
    </form>
  </section>
}
