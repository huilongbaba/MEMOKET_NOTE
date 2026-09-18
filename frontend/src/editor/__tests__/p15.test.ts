// @vitest-environment jsdom
/**
 * P15（`docs/TRACELOG-product.md` P15 节）：导入 / 录音 / 网页剪藏默认进托盘 + 托盘项标题回退（前端一半）。
 *
 *   `util/trayDefaults`：开关默认开、存 localStorage、改了广播 `tray-default-changed`
 *   `util/tray`：一批一起放（`withItems`：已在的跳过、封顶 24）、`landNotesInTray` 一次 PUT
 *   `TrayPanel`：托盘格里有开关和剪藏框；`tray-add` 带 `items` 一批只 PUT 一次；笔记项标题「未命名」显示成正文首行；
 *     import 项 ref_id 是网址时「打开原网页」
 *   `AudioRecorder`：开关开着且有笔记 → 菜单第一项「录音 → 进托盘」；关了排最后；没笔记不给
 *   `MemoryPanel`：导入跑完只收落成了笔记的（`note_id`）、同一篇只一条；App 的 .md 导入也走 `landNotesInTray`
 *
 * 每条的量程写在 it 名字里（撤掉哪一处它红）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import appSrc from '../../App.tsx?raw'
import recorderSrc from '../../components/AudioRecorder.tsx?raw'

import { recordingTitle, setTrayByDefault, trayByDefault } from '../../util/trayDefaults'
import { landNotesInTray, TRAY_MAX_ITEMS, withItems } from '../../util/tray'
import type { TrayItem } from '../../api'
import TrayPanel, { trayItemTitle } from '../../components/TrayPanel'
import { recordMenuOrder } from '../../components/AudioRecorder'
import { importedTrayItems } from '../../components/MemoryPanel'

const ITEMS: TrayItem[] = [
  { id: 'a', kind: 'note', ref_id: '0eecee3d7b94', title: '创业反思', excerpt: '我写这篇反思不是为了复盘流水账', position: 0, added_at: 't' },
  { id: 'b', kind: 'note', ref_id: '92d07b760f1e', title: '未命名', excerpt: '我们产品当前遇到的挑战：四项核心挑战归纳为验证框架\n第二行', position: 1, added_at: 't' },
  { id: 'c', kind: 'import', ref_id: 'https://example.com/post', title: 'Kickstarter 上线复盘', excerpt: '3 月 10 日上众筹', position: 2, added_at: 't' },
]
const ok = (items: TrayItem[]) => Promise.resolve(new Response(JSON.stringify({ items }), { status: 200, headers: { 'Content-Type': 'application/json' } }))

describe('util/trayDefaults：开关', () => {
  beforeEach(() => localStorage.clear())
  it('默认开；改了落 localStorage 并广播（量程：trayByDefault / setTrayByDefault）', () => {
    expect(trayByDefault()).toBe(true)
    const heard: unknown[] = []
    window.addEventListener('tray-default-changed', (e) => heard.push((e as CustomEvent).detail))
    setTrayByDefault(false)
    expect(trayByDefault()).toBe(false)
    expect(localStorage.getItem('memoket.tray.default')).toBe('0')
    setTrayByDefault(true)
    expect(heard).toEqual([false, true])
  })
  it('录音项的标题带时间', () => {
    expect(recordingTitle(new Date(2026, 8, 19, 9, 5))).toBe('录音 09:05')
  })
})

describe('util/tray：一批一起放', () => {
  it('withItems：已在的跳过、顺序 = 原来 + 新的、封顶 24（量程：withItems）', () => {
    const next = withItems(ITEMS, [{ kind: 'note', ref_id: '0eecee3d7b94' }, { kind: 'note', ref_id: 'n-new', title: '新篇', excerpt: 'x' }])
    expect(next.map((i) => i.ref_id)).toEqual(['0eecee3d7b94', '92d07b760f1e', 'https://example.com/post', 'n-new'])
    const many = Array.from({ length: 30 }, (_, k) => ({ kind: 'note' as const, ref_id: `n${k}` }))
    expect(withItems([], many)).toHaveLength(TRAY_MAX_ITEMS)
  })
  it('landNotesInTray：GET 一次 PUT 一次、自己那篇不放、没新东西不 PUT（量程：landNotesInTray）', async () => {
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { items: TrayItem[] }
        return ok(body.items.map((i, k) => ({ ...i, id: i.id || `id${k}`, position: k, added_at: 't' })))
      }
      return ok(ITEMS.slice(0, 1))
    })
    vi.stubGlobal('fetch', fetchMock)
    const n = await landNotesInTray('target', [
      { id: 'target', title: '自己', content: 'x' },
      { id: 'imp1', title: '周会', content: '# 周会\n\n4 月 10 日拿到手板' },
      { id: '0eecee3d7b94', title: '创业反思', content: '已在' },
    ])
    expect(n).toBe(1)
    const puts = fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'PUT')
    expect(puts).toHaveLength(1)
    const sent = JSON.parse(String((puts[0][1] as RequestInit).body)) as { items: { kind: string; ref_id: string; excerpt: string }[] }
    expect(sent.items.map((i) => i.ref_id)).toEqual(['0eecee3d7b94', 'imp1'])
    expect(sent.items[1].excerpt).toBe('周会\n4 月 10 日拿到手板')
    fetchMock.mockClear()
    expect(await landNotesInTray('target', [{ id: '0eecee3d7b94', title: '创业反思', content: '已在' }])).toBe(0)
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'PUT')).toHaveLength(0)
    vi.unstubAllGlobals()
  })
})

describe('TrayPanel：开关 / 剪藏 / 标题回退 / 一批一次 PUT', () => {
  const fetchMock = vi.fn()
  let root: Root | null = null
  let host: HTMLDivElement
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
    localStorage.clear()
    host = document.createElement('div')
    document.body.append(host)
  })
  afterEach(() => { act(() => root?.unmount()); root = null; host.remove(); vi.unstubAllGlobals() })

  it('托盘格里有「默认进托盘」开关（默认勾着）和剪藏输入框 + 按钮（量程：TrayPanel 的 .tray-tools）', async () => {
    fetchMock.mockImplementation(() => ok([]))
    root = createRoot(host)
    await act(async () => { root!.render(createElement(TrayPanel, { noteId: 'n1' })) })
    await act(async () => { await Promise.resolve() })
    const box = host.querySelector<HTMLInputElement>('.tray-default input')
    expect(box?.checked).toBe(true)
    expect(host.textContent).toContain('导入 / 录音 / 剪藏默认进托盘')
    expect(host.querySelector('.tray-clip-url')?.getAttribute('placeholder')).toContain('网址')
    expect((host.querySelector('.tray-clip-go') as HTMLButtonElement).disabled).toBe(true)     // 没贴网址不能点
    await act(async () => { box!.click() })
    expect(trayByDefault()).toBe(false)
  })

  it('剪藏：贴网址 → POST …/tray/clip → 托盘里多一条 import 项、「打开原网页」（量程：clip() + openOriginal 的 import 分支）', async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (init?.method === 'POST' && /\/tray\/clip$/.test(url)) {
        expect(JSON.parse(String(init.body))).toEqual({ url: 'https://example.com/post' })
        return ok(ITEMS.slice(2))
      }
      return ok([])
    })
    root = createRoot(host)
    await act(async () => { root!.render(createElement(TrayPanel, { noteId: 'n1' })) })
    await act(async () => { await Promise.resolve() })
    const input = host.querySelector<HTMLInputElement>('.tray-clip-url')!
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    await act(async () => { setter.call(input, 'https://example.com/post'); input.dispatchEvent(new Event('input', { bubbles: true })) })
    await act(async () => { host.querySelector('form.tray-clip')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await Promise.resolve(); await Promise.resolve() })
    expect(host.querySelectorAll('.tray-item')).toHaveLength(1)
    expect(host.querySelector('.tray-kind')?.textContent?.trim()).toBe('导入')
    expect(host.querySelector('.tray-title')?.textContent).toBe('Kickstarter 上线复盘')
    expect(host.querySelector('button[title="打开原网页"]')).not.toBeNull()
    const opened: string[] = []
    vi.stubGlobal('open', (u: string) => { opened.push(u); return null })
    await act(async () => { (host.querySelector('button[title="打开原网页"]') as HTMLButtonElement).click() })
    expect(opened).toEqual(['https://example.com/post'])
  })

  it('笔记项标题是「未命名」时显示正文首行（量程：trayItemTitle / displayTitle）', async () => {
    fetchMock.mockImplementation(() => ok(ITEMS))
    root = createRoot(host)
    await act(async () => { root!.render(createElement(TrayPanel, { noteId: 'n1' })) })
    await act(async () => { await Promise.resolve() })
    expect(Array.from(host.querySelectorAll('.tray-title')).map((e) => e.textContent)).toEqual(['创业反思', '我们产品当前遇到的挑战', 'Kickstarter 上线复盘'])
    expect(trayItemTitle({ kind: 'note', title: '', excerpt: '' })).toBe('未命名')
    expect(trayItemTitle({ kind: 'import', title: '未命名', excerpt: 'x' })).toBe('未命名')        // 只有笔记项回退
  })

  it('tray-add 带 items：一批只 PUT 一次，已在的不算（量程：TrayPanel 的 tray-add 处理器）', async () => {
    fetchMock.mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { items: TrayItem[] }
        return ok(body.items.map((i, k) => ({ ...i, id: i.id || 'new', position: k, added_at: 't' })))
      }
      return ok(ITEMS.slice(0, 1))
    })
    root = createRoot(host)
    await act(async () => { root!.render(createElement(TrayPanel, { noteId: 'n1' })) })
    await act(async () => { await Promise.resolve() })
    await act(async () => {
      window.dispatchEvent(new CustomEvent('tray-add', { detail: { items: [
        { kind: 'note', ref_id: '0eecee3d7b94' }, { kind: 'note', ref_id: 'x1', title: '甲' }, { kind: 'note', ref_id: 'x2', title: '乙' }, { kind: 'note', ref_id: 'n1', title: '自己' },
      ] } }))
      await Promise.resolve(); await Promise.resolve()
    })
    const puts = fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'PUT')
    expect(puts).toHaveLength(1)
    const sent = JSON.parse(String((puts[0][1] as RequestInit).body)) as { items: { ref_id: string }[] }
    expect(sent.items.map((i) => i.ref_id)).toEqual(['0eecee3d7b94', 'x1', 'x2'])
    expect(host.querySelectorAll('.tray-item')).toHaveLength(3)
  })
})

describe('AudioRecorder：录音的默认去处', () => {
  it('开关开着且有笔记 → 「进托盘」排第一；关了排最后；没笔记不给（量程：recordMenuOrder）', () => {
    expect(recordMenuOrder('n1', true)).toEqual(['tray', 'insert', 'memory'])
    expect(recordMenuOrder('n1', false)).toEqual(['insert', 'memory', 'tray'])
    expect(recordMenuOrder(undefined, true)).toEqual(['insert', 'memory'])
  })
  it('进托盘那条路：转写后 requestTrayAdd(kind import) 不 onTranscript；App 把 current.id 传进去（量程：源码接线）', () => {
    expect(recorderSrc).toContain("target.current === 'tray') requestTrayAdd({ kind: 'import'")
    expect(recorderSrc).toContain("label: '录音 → 进托盘'")
    expect(appSrc).toContain('<AudioRecorder onTranscript={insertAtCursor} onIngested={setJob} offline={asrOffline} noteId={current?.id} />')
  })
})

describe('MemoryPanel / App：导入跑完进托盘', () => {
  it('只收落成了笔记的、状态 done 的，同一篇只一条，封顶 24（量程：importedTrayItems）', () => {
    const got = importedTrayItems([
      { status: 'done', note_id: 'a', filename: 'a.md' }, { status: 'done', note_id: 'a', filename: 'a2.md' },
      { status: 'done', note_id: '', filename: 'kb-only.md' }, { status: 'failed', note_id: 'b', filename: 'b.md' },
      { status: 'done', note_id: 'c', filename: 'c.md' },
    ])
    expect(got).toEqual([{ note_id: 'a', filename: 'a.md' }, { note_id: 'c', filename: 'c.md' }])
    expect(importedTrayItems(Array.from({ length: 40 }, (_, k) => ({ status: 'done', note_id: `n${k}`, filename: 'x' })))).toHaveLength(TRAY_MAX_ITEMS)
  })
  it('五条导入路（Obsidian / Evernote / Apple / Notion / 飞书 + 继续）跑完都 landImportInTray；.md 导入走 landNotesInTray；目标是最近开着的那篇（量程：源码接线）', async () => {
    const src = (await import('../../components/MemoryPanel.tsx?raw')).default as string
    expect((src.match(/landImportInTray\(r\.job_id, trayNoteId\)/g) ?? []).length).toBe(5)
    expect(appSrc).toContain('<MemoryPanel pendingJob={job} trayNoteId={trayTarget} />')
    expect(appSrc).toContain("if (current?.id) { setTrayTarget(current.id); trayTargetRef.current = current.id }")
    expect(appSrc).toContain('await toTray([{ id: n.id, title: n.title, content: text }])')
    expect(appSrc).toContain('await toTray(made)')
    expect(appSrc).toContain('if (!trayByDefault() || !target) return')
  })
})
