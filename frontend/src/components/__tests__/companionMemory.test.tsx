// @vitest-environment jsdom
import { act, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../../api'
import type { Fact } from '../../api'
import CompanionMemory from '../CompanionMemory'

vi.mock('../../api', () => ({
  getUser: () => localStorage.getItem('memoket-note-user') || 'kb-test',
  recall: vi.fn(),
}))

const recall = vi.mocked(api.recall)
type RecallOut = Awaited<ReturnType<typeof api.recall>>

const roots: Root[] = []
const f1: Fact = { id: 'kailun-1872-5F8', text: '供应商上次报价 12 万，含税。', when: '2026-09-18', kind: '决定', sources: ['u1'] }
const f2: Fact = { id: 'kailun-1873-5F9', text: '交期改到十月中旬，物流另算。', when: '2026-09-19', kind: '进展', sources: ['u1'] }
const hits = (facts: Fact[], terms = ['报价']): RecallOut => ({ facts, took_ms: 12, terms })

beforeEach(() => {
  vi.useFakeTimers()
  localStorage.clear()
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  recall.mockReset()
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
async function tick(ms: number) { await act(async () => { await vi.advanceTimersByTimeAsync(ms) }) }
async function click(host: HTMLElement, label: string) {
  const button = [...host.querySelectorAll<HTMLButtonElement>('button')].find((b) => (b.getAttribute('aria-label') || b.textContent) === label)
  expect(button, `button ${label}`).toBeTruthy()
  await act(async () => { button!.click() })
}
async function key(el: Element, k: string) {
  await act(async () => { el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true })) })
}

function Memory({ content, enabled = true, onCite = () => {} }: { content: string; enabled?: boolean; onCite?: (f: Fact) => void }) {
  const [expanded, setExpanded] = useState(false)
  return <CompanionMemory content={content} enabled={enabled} expanded={expanded} onExpandedChange={setExpanded} onCite={onCite} />
}

describe('CompanionMemory', () => {
  const draft = '下周三和供应商确认报价，顺便问交期。'

  it('stays hidden while the base is empty, then surfaces facts after 900ms idle and cites on demand', async () => {
    recall.mockResolvedValue({ facts: [], took_ms: 1, terms: [], kb_empty: true })
    const onCite = vi.fn()
    const { host, root } = await mount(<Memory content={draft} onCite={onCite} />)
    await tick(900)
    await tick(0)
    expect(recall).toHaveBeenCalledTimes(1)
    expect(recall.mock.calls[0][1]).toBe(5)
    expect(host.querySelector('.dc-memory-strip')).toBeNull()
    recall.mockResolvedValue(hits([f1, f2]))
    await act(async () => { root.render(<Memory content={draft + '\n\n物流谁来出？'} onCite={onCite} />) })
    await tick(899)
    expect(recall).toHaveBeenCalledTimes(1)
    await tick(1)
    await tick(0)
    expect(recall).toHaveBeenCalledTimes(2)
    const head = host.querySelector<HTMLButtonElement>('button[aria-label="相关记忆"]')!
    expect(head.getAttribute('aria-expanded')).toBe('false')
    expect(host.querySelector('.dc-memory-count')?.textContent).toBe('2 条相关记忆')
    expect(host.querySelector('.dc-memory-lead')?.textContent).toBe(f1.text)
    expect(host.querySelector('.dc-memory-strip')?.getAttribute('data-expanded')).toBe('false')
    expect(document.activeElement).toBe(document.body)
    await click(host, '相关记忆')
    expect(head.getAttribute('aria-expanded')).toBe('true')
    expect(host.querySelector('.dc-memory-strip')?.getAttribute('data-expanded')).toBe('true')
    expect(host.querySelectorAll('.dc-memory-fact')).toHaveLength(2)
    await click(host, '引用')
    expect(onCite).toHaveBeenCalledWith(f1)
    await key(host.querySelector('.dc-memory-cite')!, 'Escape')
    expect(head.getAttribute('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(head)
  })

  it('renders nothing for short drafts, drops facts already cited or written, and keeps results across a disabled spell', async () => {
    recall.mockResolvedValue(hits([f1, f2]))
    const { host, root } = await mount(<Memory content="报价。" />)
    await tick(1000)
    expect(recall).not.toHaveBeenCalled()
    expect(host.querySelector('.dc-memory-strip')).toBeNull()
    await act(async () => { root.render(<Memory content={draft} />) })
    await tick(900)
    await tick(0)
    expect(host.querySelector('.dc-memory-count')?.textContent).toBe('2 条相关记忆')
    await act(async () => { root.render(<Memory content={draft} enabled={false} />) })
    expect(host.querySelector('.dc-memory-strip')).toBeNull()
    await act(async () => { root.render(<Memory content={draft} />) })
    await tick(1000)
    expect(recall).toHaveBeenCalledTimes(1)
    expect(host.querySelector('.dc-memory-count')?.textContent).toBe('2 条相关记忆')
    await act(async () => { root.render(<Memory content={`${draft} ${f1.text} [${f2.id}]`} />) })
    expect(host.querySelector('.dc-memory-strip')).toBeNull()
  })
})
