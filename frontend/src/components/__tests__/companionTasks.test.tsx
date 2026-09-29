// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CompanionTasks from '../CompanionTasks'
import { useTodayTasks } from '../../util/useTodayTasks'
import { readWorkspaceTasks, workspaceStorageKey } from '../../util/workspaceState'

const roots: Root[] = []
const key = (user = 'island-a', day = '2026-09-22') => workspaceStorageKey(user, 'tasks', day)
function Panel({ user = 'island-a', onEscape = () => {} }: { user?: string; onEscape?: () => void }) {
  const store = useTodayTasks(user)
  return <CompanionTasks store={store} focusRequested={1} onEscape={onEscape} />
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-09-22T12:00:00'))
  localStorage.clear()
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
})
afterEach(async () => {
  await act(async () => { roots.splice(0).forEach((root) => root.unmount()) })
  document.body.innerHTML = ''
  vi.restoreAllMocks()
  vi.useRealTimers()
})

async function mount(node: React.ReactNode) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  await act(async () => { root.render(node) })
  return { host, root }
}
async function click(host: HTMLElement, label: string) {
  const button = [...host.querySelectorAll<HTMLButtonElement>('button')].find((b) => (b.getAttribute('aria-label') || b.textContent) === label)
  expect(button, `button ${label}`).toBeTruthy()
  await act(async () => { button!.click() })
}
const field = (host: HTMLElement) => host.querySelector<HTMLInputElement>('input[aria-label="添加待办"]')!
async function type(host: HTMLElement, text: string) {
  const input = field(host)
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, text)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function submit(host: HTMLElement) {
  await act(async () => { host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
}
const stored = (k = key()) => readWorkspaceTasks(localStorage.getItem(k))
const texts = (host: HTMLElement) => [...host.querySelectorAll('.dc-task-text')].map((node) => node.textContent)

describe('companion tasks', () => {
  it('adds, completes and removes today’s to-dos in the list Home shares', async () => {
    const { host } = await mount(<Panel />)
    expect(host.textContent).toContain('今天还没有待办')
    expect(document.activeElement).toBe(field(host))
    await type(host, '  核对报价单 ')
    await submit(host)
    expect(stored().map((task) => task.text)).toEqual(['核对报价单'])
    expect(field(host).value).toBe('')
    await type(host, '回复供应商')
    await submit(host)
    await click(host, '完成：核对报价单')
    expect(stored().map((task) => [task.text, task.done])).toEqual([['核对报价单', true], ['回复供应商', false]])
    // Done items sink below the open ones and can be restored.
    expect(texts(host)).toEqual(['回复供应商', '核对报价单'])
    expect(host.querySelector('[role="checkbox"][aria-checked="true"]')?.getAttribute('aria-label')).toBe('恢复：核对报价单')
    await click(host, '删除待办：回复供应商')
    expect(stored().map((task) => task.text)).toEqual(['核对报价单'])
    expect(host.textContent).toContain('今天的事都做完了')
    await click(host, '恢复：核对报价单')
    expect(stored()[0].done).toBe(false)
    expect(host.textContent).not.toContain('今天的事都做完了')
  })

  it('applies each change to the latest stored list instead of overwriting another window', async () => {
    localStorage.setItem(key(), JSON.stringify([{ id: 'a', text: '第一件', done: false }]))
    const { host } = await mount(<Panel />)
    expect(texts(host)).toEqual(['第一件'])
    // Home adds a task; this window has not received the storage event yet.
    localStorage.setItem(key(), JSON.stringify([{ id: 'a', text: '第一件', done: false }, { id: 'b', text: '首页加的', done: false }]))
    await click(host, '完成：第一件')
    expect(stored().map((task) => [task.text, task.done])).toEqual([['第一件', true], ['首页加的', false]])
    expect(texts(host)).toEqual(['首页加的', '第一件'])
    // The storage event from the other window is what normally refreshes the list.
    localStorage.setItem(key(), JSON.stringify([{ id: 'b', text: '首页加的', done: false }]))
    await act(async () => { window.dispatchEvent(new StorageEvent('storage', { key: key() })) })
    expect(texts(host)).toEqual(['首页加的'])
    expect(stored(key('someone-else'))).toEqual([])
  })

  it('carries unfinished tasks from earlier days into today on one click', async () => {
    localStorage.setItem(key('island-a', '2026-09-20'), JSON.stringify([{ id: 'old', text: '上周没做完', done: false }, { id: 'done', text: '做完了', done: true }]))
    localStorage.setItem(key('island-b', '2026-09-20'), JSON.stringify([{ id: 'x', text: '别人的', done: false }]))
    const { host } = await mount(<Panel />)
    expect(host.querySelector('.dc-tasks-carry')?.textContent).toContain('前几天还有 1 件没做完')
    await click(host, '前几天还有 1 件没做完，移到今天')
    expect(stored().map((task) => task.text)).toEqual(['上周没做完'])
    expect(stored(key('island-a', '2026-09-20'))[0].carriedTo).toBe('2026-09-22')
    expect(stored(key('island-b', '2026-09-20'))).toEqual([{ id: 'x', text: '别人的', done: false }])
    expect(host.querySelector('.dc-tasks-carry')).toBeNull()
    expect(texts(host)).toEqual(['上周没做完'])
  })

  it('keeps the list usable in this window and says so when the record cannot be written', async () => {
    const { host } = await mount(<Panel />)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
    await type(host, '写不进去的事')
    await submit(host)
    expect(texts(host)).toEqual(['写不进去的事'])
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('暂未保存')
  })

  it('clears the draft on Escape first, then hands Escape to the island', async () => {
    const onEscape = vi.fn()
    const { host } = await mount(<Panel onEscape={onEscape} />)
    await type(host, '半句')
    const input = field(host)
    await act(async () => { input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })) })
    expect(input.value).toBe('')
    expect(onEscape).not.toHaveBeenCalled()
    await act(async () => { input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })) })
    expect(onEscape).toHaveBeenCalledOnce()
  })
})
