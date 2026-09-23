// @vitest-environment jsdom
/**
 * P14（产品就绪计划 §2 C2，`docs/TRACELOG-product.md` P14 节）：材料托盘的前端一半（`docs/agent-native-editor.md` §3.4）。
 *
 *   `util/tray`：纯函数——同一条不重复放（note / fact 按 ref_id、import / selection 按内容）、拖序 / 上下移、
 *     笔记摘要（去井号、内链折回标题）、「从托盘写」的空托盘门槛（读缓存，不发请求）
 *   `TrayPanel`：空态说清从哪儿放进来；三项各带种类标 / 标题 / 摘要、上下移 / 打开 / 移除四个按钮都有 title；
 *     `tray-add` 事件 → PUT 整份 → 广播 `tray-changed`；托盘不是新页签（App.tsx 的 tabs 里没有 id: 'tray'）
 *   `slashMenu`：「从托盘写」在 AI 组里、能按「托盘」过滤；它不是新的 block mode（`BLOCK_MODES` 里没有 tray）
 *   `RelatedMemory`：记忆卡上有「放进托盘」；`noteLink`：右键链接标记发 `note-link-menu`
 *
 * 每条的量程写在 it 名字里（撤掉哪一处它红）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { renderToStaticMarkup } from 'react-dom/server'
import appSrc from '../../App.tsx?raw'
import relatedMemorySrc from '../../components/RelatedMemory.tsx?raw'
import noteLinkSrc from '../noteLink.ts?raw'

import { alreadyInTray, moveItem, noteExcerpt, setTrayCache, trayCount, trayKey, trayPrecondition, withItem, TRAY_EXCERPT_MAX } from '../../util/tray'
import { BLOCK_MODES, type TrayItem } from '../../api'
import { SLASH_ITEMS, filtered } from '../slashMenu'
import TrayPanel from '../../components/TrayPanel'

const ITEMS: TrayItem[] = [
  { id: 'a', kind: 'note', ref_id: '0eecee3d7b94', title: '创业反思', excerpt: '我写这篇反思不是为了复盘流水账', position: 0, added_at: '2026-09-19T00:00:00' },
  { id: 'b', kind: 'note', ref_id: '92d07b760f1e', title: '产品当前的挑战', excerpt: '四项核心挑战归纳为验证框架', position: 1, added_at: '2026-09-19T00:00:00' },
  { id: 'c', kind: 'fact', ref_id: 'terrence-1238-7F4', title: '2026-03', excerpt: '3月10号上众筹', position: 2, added_at: '2026-09-19T00:00:00' },
]

describe('util/tray：纯函数', () => {
  it('同一条不重复放：note / fact 按 ref_id，import / selection 按内容（量程：trayKey）', () => {
    expect(trayKey({ kind: 'note', ref_id: 'x', excerpt: 'a' })).toBe(trayKey({ kind: 'note', ref_id: 'x', excerpt: 'b' }))
    expect(trayKey({ kind: 'selection', excerpt: 'a' })).not.toBe(trayKey({ kind: 'selection', excerpt: 'b' }))
    expect(alreadyInTray(ITEMS, { kind: 'fact', ref_id: 'terrence-1238-7F4' })).toBe(true)
    expect(alreadyInTray(ITEMS, { kind: 'fact', ref_id: 'terrence-1238-7F5' })).toBe(false)
    expect(withItem(ITEMS, { kind: 'note', ref_id: '0eecee3d7b94' })).toHaveLength(3)     // 已在 → 原样
    const added = withItem(ITEMS, { kind: 'selection', excerpt: 'x'.repeat(TRAY_EXCERPT_MAX + 50) })
    expect(added).toHaveLength(4)
    expect(added[3].excerpt).toHaveLength(TRAY_EXCERPT_MAX)                                  // 跟后端同一个封顶
    expect(added.slice(0, 3).map((i) => i.id)).toEqual(['a', 'b', 'c'])                     // 顺序 = 数组顺序，id 保留
  })
  it('拖序 / 上下移：moveItem 是纯函数，越界原样返回', () => {
    expect(moveItem(ITEMS, 2, 0).map((i) => i.id)).toEqual(['c', 'a', 'b'])
    expect(moveItem(ITEMS, 0, 2).map((i) => i.id)).toEqual(['b', 'c', 'a'])
    expect(moveItem(ITEMS, 1, 1)).toBe(ITEMS)
    expect(moveItem(ITEMS, -1, 0)).toBe(ITEMS)
    expect(moveItem(ITEMS, 0, 3)).toBe(ITEMS)
  })
  it('笔记摘要：去掉标题井号、内链折回标题、空行折成单换行、封顶加省略号', () => {
    const s = noteExcerpt('# 创业反思\n\n\n第一段 [产品挑战](note://92d07b760f1e) 结尾\n\n## 二\n正文')
    expect(s).toBe('创业反思\n第一段 产品挑战 结尾\n二\n正文')
    expect(noteExcerpt('x'.repeat(1000))).toHaveLength(TRAY_EXCERPT_MAX + 1)
    expect(noteExcerpt('x'.repeat(1000)).endsWith('…')).toBe(true)
  })
  it('「用本篇材料写」的门槛读缓存：没有材料给一句话、有东西放行（量程：trayPrecondition / setTrayCache）', () => {
    setTrayCache('n1', [])
    expect(trayPrecondition('n1')).toContain('还没有本篇材料')
    expect(trayPrecondition('never-loaded')).toContain('还没有本篇材料')
    const heard: unknown[] = []
    const on = (e: Event) => heard.push((e as CustomEvent).detail)
    window.addEventListener('tray-changed', on)
    setTrayCache('n1', ITEMS)
    window.removeEventListener('tray-changed', on)
    expect(trayCount('n1')).toBe(3)
    expect(trayPrecondition('n1')).toBe('')
    expect(heard).toEqual([{ noteId: 'n1', count: 3 }])
  })
})

describe('/ 菜单「用本篇材料写」', () => {
  it('在 AI 组里、能按「材料」过滤、留空也能跑（promptOptional）', () => {
    const it_ = SLASH_ITEMS.find((i) => i.key === 'tray')
    expect(it_?.group).toBe('AI')
    expect(it_?.label).toBe('用本篇材料写')
    expect(it_?.needsPrompt && it_?.promptOptional).toBe(true)
    expect(filtered('材料').map((i) => i.key)).toContain('tray')
  })
  it('不是新的 block mode：BLOCK_MODES 里没有 tray（App.runBlock 映射成 prompt + from_tray）', () => {
    expect((BLOCK_MODES as readonly string[]).includes('tray')).toBe(false)
    const app = appSrc
    expect(app).toContain("item.key === 'tray' ? 'prompt' : item.key")
    expect(app).toContain("from_tray: item.key === 'tray'")
    expect(app).toContain("trayPrecondition(current.id)")
  })
})

describe('TrayPanel：右栏「记忆」的第一格，不是新页签', () => {
  const fetchMock = vi.fn()
  let root: Root | null = null
  let host: HTMLDivElement
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
    host = document.createElement('div')
    document.body.append(host)
  })
  afterEach(() => { act(() => root?.unmount()); root = null; host.remove(); vi.unstubAllGlobals() })
  const ok = (items: TrayItem[]) => Promise.resolve(new Response(JSON.stringify({ items }), { status: 200, headers: { 'Content-Type': 'application/json' } }))

  it('App.tsx 的右栏页签里没有 id: \'tray\'；托盘挂在 memory 页签 body 里（量程：App.tsx）', () => {
    const app = appSrc
    expect(app).not.toMatch(/id:\s*'tray'/)
    const memoryTab = app.slice(app.indexOf("id: 'memory', title: '记忆'"), app.indexOf("title: '改动'"))
    expect(memoryTab).toContain('<TrayPanel')
    expect(memoryTab).toContain('<RelatedMemory')
    expect(memoryTab.indexOf('<TrayPanel')).toBeLessThan(memoryTab.indexOf('<RelatedMemory'))
  })

  it('空态：用用户语言说清从哪儿添加；「用材料写」只在有东西时出现', async () => {
    fetchMock.mockImplementation(() => ok([]))
    root = createRoot(host)
    await act(async () => { root!.render(createElement(TrayPanel, { noteId: 'n1', onWrite: () => {} })) })
    await act(async () => { await Promise.resolve() })
    const text = host.textContent ?? ''
    expect(text).toContain('本篇材料')
    expect(text).toContain('还没有本篇材料')
    expect(text).toContain('记忆卡')
    expect(text).toContain('右键正文里的笔记链接')
    expect(text).not.toContain('托盘')
    expect(host.querySelector('.tray-write')).toBeNull()
    expect(host.querySelector('.tray-panel')?.getAttribute('data-count')).toBe('0')
  })

  it('三项：种类标 / 标题 / 摘要，上下移 / 打开 / 移除都有 title，第一条「上移」禁用并说明', async () => {
    fetchMock.mockImplementation(() => ok(ITEMS))
    root = createRoot(host)
    await act(async () => { root!.render(createElement(TrayPanel, { noteId: 'n1', onWrite: () => {} })) })
    await act(async () => { await Promise.resolve() })
    const rows = host.querySelectorAll('.tray-item')
    expect(rows).toHaveLength(3)
    expect(host.querySelector('.tray-panel')?.getAttribute('data-count')).toBe('3')
    expect(Array.from(host.querySelectorAll('.tray-kind')).map((e) => e.textContent?.trim())).toEqual(['笔记', '笔记', '事实'])
    expect(Array.from(host.querySelectorAll('.tray-title')).map((e) => e.textContent)).toEqual(['创业反思', '产品当前的挑战', '2026-03'])
    expect(host.querySelector('.tray-excerpt')?.textContent).toBe('我写这篇反思不是为了复盘流水账')
    for (const b of host.querySelectorAll('.tray-actions button')) expect(b.getAttribute('title')).toBeTruthy()
    expect((rows[0].querySelector('button[title="上移"]') as HTMLButtonElement).disabled).toBe(true)
    expect((rows[2].querySelector('button[title="下移"]') as HTMLButtonElement).disabled).toBe(true)
    expect(host.querySelector('.tray-write')).not.toBeNull()
    expect(rows[0].getAttribute('draggable')).toBe('true')
  })

  it('tray-add 事件 → PUT 整份（顺序 = 原来 + 新的一条）→ 广播 tray-changed；已在托盘里的不再 PUT', async () => {
    fetchMock.mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { items: TrayItem[] }
        return ok(body.items.map((i, k) => ({ ...i, id: i.id || 'new', position: k, added_at: 't' })))
      }
      return ok(ITEMS.slice(0, 2))
    })
    root = createRoot(host)
    await act(async () => { root!.render(createElement(TrayPanel, { noteId: 'n1' })) })
    await act(async () => { await Promise.resolve() })
    const heard: unknown[] = []
    window.addEventListener('tray-changed', (e) => heard.push((e as CustomEvent).detail))
    await act(async () => {
      window.dispatchEvent(new CustomEvent('tray-add', { detail: { kind: 'fact', ref_id: 'terrence-1238-7F4', title: '2026-03', excerpt: '3月10号上众筹' } }))
      await Promise.resolve(); await Promise.resolve()
    })
    const put = fetchMock.mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === 'PUT')
    expect(String(put?.[0])).toMatch(/\/notes\/n1\/tray$/)   // 字面路径不写全：后端 test_api_contract 会把它当成前端在调的端点
    const sent = JSON.parse(String((put![1] as RequestInit).body)) as { items: { kind: string; ref_id: string }[] }
    expect(sent.items.map((i) => `${i.kind}:${i.ref_id}`)).toEqual(['note:0eecee3d7b94', 'note:92d07b760f1e', 'fact:terrence-1238-7F4'])
    expect(host.querySelectorAll('.tray-item')).toHaveLength(3)
    expect(heard.at(-1)).toEqual({ noteId: 'n1', count: 3 })
    // 再放同一条：不再 PUT
    const puts = fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'PUT').length
    await act(async () => {
      window.dispatchEvent(new CustomEvent('tray-add', { detail: { kind: 'fact', ref_id: 'terrence-1238-7F4' } }))
      await Promise.resolve()
    })
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'PUT').length).toBe(puts)
    // 别的笔记的 tray-add 不收
    await act(async () => {
      window.dispatchEvent(new CustomEvent('tray-add', { detail: { noteId: 'other', kind: 'selection', excerpt: 'x' } }))
      await Promise.resolve()
    })
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'PUT').length).toBe(puts)
  })

  it('移除走 DELETE /api/notes/{id}/tray/{item}；「下移」PUT 整份、顺序换了', async () => {
    fetchMock.mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === 'DELETE') return ok(ITEMS.slice(1))
      if (init?.method === 'PUT') { const b = JSON.parse(String(init.body)) as { items: TrayItem[] }; return ok(b.items.map((i, k) => ({ ...i, position: k, added_at: 't' }))) }
      return ok(ITEMS)
    })
    root = createRoot(host)
    await act(async () => { root!.render(createElement(TrayPanel, { noteId: 'n1' })) })
    await act(async () => { await Promise.resolve() })
    await act(async () => { (host.querySelector('.tray-item button[title="下移"]') as HTMLButtonElement).click(); await Promise.resolve() })
    const put = fetchMock.mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === 'PUT')
    expect(JSON.parse(String((put![1] as RequestInit).body)).items.map((i: { id: string }) => i.id)).toEqual(['b', 'a', 'c'])
    await act(async () => { (host.querySelector('.tray-item button[title="从本篇材料移除（原文不动）"]') as HTMLButtonElement).click(); await Promise.resolve() })
    const del = fetchMock.mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === 'DELETE')
    expect(String(del?.[0])).toMatch(/\/notes\/n1\/tray\/b$/)
    expect(host.querySelectorAll('.tray-item')).toHaveLength(2)
  })
})

describe('入口：记忆卡「加入本篇材料」、`[[` 链接右键', () => {
  it('RelatedMemory 的记忆卡和关系卡都能加入本篇材料（量程：RelatedMemory.tsx）', () => {
    const src = relatedMemorySrc
    expect(src).toContain("requestTrayAdd({ kind: 'fact', ref_id: f.id")
    expect(src.match(/加入本篇材料/g)?.length ?? 0).toBeGreaterThanOrEqual(2)
  })
  it('noteLink 标记右键发 note-link-menu（id / title / x / y），左键照旧 open-note', () => {
    const src = noteLinkSrc
    expect(src).toContain("addEventListener('contextmenu'")
    expect(src).toContain("'note-link-menu'")
    expect(src).toContain('e.stopPropagation()')
    const app = appSrc
    expect(app).toContain("window.addEventListener('note-link-menu', on)")
    expect(app).toContain("label: '加入本篇材料'")
  })
  it('renderToStaticMarkup 也能画（没有 window 依赖的首屏）', () => {
    const html = renderToStaticMarkup(createElement(TrayPanel, { noteId: 'n1' }))
    expect(html).toContain('tray-panel')
    expect(html).toContain('本篇材料')
  })
})
