// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import QuickCapture from '../QuickCapture'

const roots: Root[] = []
const draftKey = (user: string) => `memoket.quick-capture.${encodeURIComponent(user)}`

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('memoket-note-user', 'capture-test')
  delete window.memoketDesktop
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  HTMLDialogElement.prototype.showModal = function () { this.open = true }
  HTMLDialogElement.prototype.close = function () { this.open = false }
})
afterEach(async () => {
  await act(async () => { for (const root of roots.splice(0)) root.unmount() })
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

async function mount(onSave = vi.fn(async (_title: string, _content: string) => {}), onClose = vi.fn()) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  await act(async () => { root.render(<QuickCapture onSave={onSave} onClose={onClose} />) })
  return { host, root, onSave, onClose }
}

async function input(host: HTMLElement, label: string, value: string) {
  const element = host.querySelector<HTMLInputElement | HTMLTextAreaElement>(`[aria-label="${label}"]`)!
  const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  await act(async () => {
    Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(element, value)
    element.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function click(host: HTMLElement, text: string) {
  const button = [...host.querySelectorAll('button')].find((node) => node.textContent?.includes(text))!
  await act(async () => { button.click() })
}

describe('Quick capture keeps real input safe', () => {
  it('opens a native modal, focuses the body, and keeps a per-user draft after Escape', async () => {
    const { host, onClose } = await mount()
    expect(host.querySelector('dialog')!.open).toBe(true)
    expect(document.activeElement).toBe(host.querySelector('textarea'))
    await input(host, '捕捉标题', '会议后跟进')
    await input(host, '捕捉正文', '明天发方案')
    expect(JSON.parse(localStorage.getItem(draftKey('capture-test'))!)).toEqual({ title: '会议后跟进', content: '明天发方案' })
    await act(async () => { host.querySelector('dialog')!.dispatchEvent(new Event('cancel', { cancelable: true })) })
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(draftKey('capture-test'))).toContain('明天发方案')
  })

  it('restores the current user draft without exposing another user draft', async () => {
    localStorage.setItem(draftKey('someone-else'), JSON.stringify({ title: 'Private title', content: 'Private content' }))
    localStorage.setItem(draftKey('capture-test'), JSON.stringify({ title: '我自己的', content: '未完成的想法' }))
    const { host } = await mount()
    expect(host.querySelector('input')!.value).toBe('我自己的')
    expect(host.querySelector('textarea')!.value).toBe('未完成的想法')
    expect(host.textContent).toContain('已恢复本机草稿')
    expect(host.textContent).not.toContain('Private')
  })

  it('preserves text and draft on a failed save, then clears the draft only after success', async () => {
    const save = vi.fn(async (_title: string, _content: string) => {}).mockRejectedValueOnce(new Error('后端离线'))
    const { host, onClose } = await mount(save)
    await input(host, '捕捉正文', '第一行成为标题\n完整正文保留')
    await click(host, '存入笔记')
    expect(save).toHaveBeenCalledWith('第一行成为标题', '第一行成为标题\n完整正文保留')
    expect(onClose).not.toHaveBeenCalled()
    expect(host.querySelector('[role="alert"]')!.textContent).toContain('后端离线')
    expect(host.querySelector('textarea')!.value).toBe('第一行成为标题\n完整正文保留')
    expect(localStorage.getItem(draftKey('capture-test'))).toContain('完整正文保留')
    await click(host, '存入笔记')
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(draftKey('capture-test'))).toBeNull()
  })

  it('saves on Cmd+Enter once while a request is pending and does not close on Escape mid-save', async () => {
    let resolveSave!: () => void
    const save = vi.fn((_title: string, _content: string) => new Promise<void>((resolve) => { resolveSave = resolve }))
    const { host, onClose } = await mount(save)
    await input(host, '捕捉正文', '不能重复创建')
    const body = host.querySelector('textarea')!
    await act(async () => {
      body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true }))
      body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true }))
      host.querySelector('dialog')!.dispatchEvent(new Event('cancel', { cancelable: true }))
    })
    expect(save).toHaveBeenCalledTimes(1)
    expect(onClose).not.toHaveBeenCalled()
    await act(async () => { resolveSave() })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('reads the clipboard only after the paste button and shows denied access without losing input', async () => {
    const readClipboard = vi.fn(async () => '复制的链接').mockRejectedValueOnce(new Error('denied'))
    window.memoketDesktop = {
      setTheme: () => {},
      quickCapture: { ready: () => {}, status: async () => ({ accelerator: 'CommandOrControl+Shift+N', registered: false, reason: '快捷键被占用' }), readClipboard },
    }
    const { host } = await mount()
    expect(readClipboard).not.toHaveBeenCalled()
    expect(host.textContent).toContain('快捷键被占用')
    await input(host, '捕捉正文', '已有内容')
    await click(host, '粘贴剪贴板')
    expect(host.querySelector('[role="alert"]')!.textContent).toContain('无法读取剪贴板')
    expect(host.querySelector('textarea')!.value).toBe('已有内容')
    await click(host, '粘贴剪贴板')
    expect(readClipboard).toHaveBeenCalledTimes(2)
    expect(host.querySelector('textarea')!.value).toBe('已有内容\n\n复制的链接')
  })

  it('wraps Tab between enabled controls and restores the previous focus on unmount', async () => {
    const trigger = document.createElement('button')
    document.body.append(trigger)
    trigger.focus()
    const { host, root } = await mount()
    await input(host, '捕捉正文', '有正文可保存')
    const first = host.querySelector('button')!
    const last = host.querySelector<HTMLButtonElement>('[type="submit"]')!
    last.focus()
    await act(async () => { last.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })) })
    expect(document.activeElement).toBe(first)
    await act(async () => { first.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true })) })
    expect(document.activeElement).toBe(last)
    await act(async () => { root.unmount() })
    roots.splice(roots.indexOf(root), 1)
    expect(document.activeElement).toBe(trigger)
  })

  it('does not save a stale draft while an explicit clipboard read is pending', async () => {
    let finishPaste!: (value: string) => void
    window.memoketDesktop = {
      setTheme: () => {},
      quickCapture: {
        ready: () => {},
        status: async () => ({ accelerator: 'CommandOrControl+Shift+N', registered: true, reason: '' }),
        readClipboard: () => new Promise<string>((resolve) => { finishPaste = resolve }),
      },
    }
    const { host, onSave } = await mount()
    await input(host, '捕捉正文', '先前内容')
    await click(host, '粘贴剪贴板')
    await act(async () => { host.querySelector('textarea')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true })) })
    expect(onSave).not.toHaveBeenCalled()
    await act(async () => { finishPaste('刚复制的内容') })
    await click(host, '存入笔记')
    expect(onSave).toHaveBeenCalledWith('先前内容', '先前内容\n\n刚复制的内容')
  })
})
