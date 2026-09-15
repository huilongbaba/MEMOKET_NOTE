// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

/**
 * 空知识库上的两页：总览和事实表。
 *
 * 起因是第 673 轮拿一个全新用户把每一页走了一遍——空库总览上那个
 * 「看看事实表长什么样」按钮点进去，是五个空下拉 + 「0 条 · 没有事实。」。
 * **按钮承诺给你看，给出来的是空的。** 现在改成当场把样子摆出来。
 *
 * 所以这两条测的是**用户看得见什么**：示例在不在、假事实点不点得动、
 * 空库时那排筛选器有没有摆出来。不看源码长什么样。
 */
vi.mock('../../api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../api')
  return {
    ...actual,
    kbDashboard: () => Promise.resolve({
      stats: { facts: 0, topics: 0, entities: 0, units: 0, start_date: '', end_date: '' },
      kinds: [], speakers: [], topics: [], entities: [], months: [], recent: [],
    }),
    memoryFacts: () => Promise.resolve({ total: 0, facts: [], limit: 50, offset: 0 }),
    recall: () => Promise.resolve({ facts: [], terms: [], took: 0 }),
  }
})

const { default: FactsTable } = await import('../../components/kb/FactsTable')
const { ExampleFacts } = await import('../../components/kb/KbBits')

const ACTIONS = { onOpen: () => {}, onOpenNote: () => {}, onCite: null }

async function mount(node: React.ReactNode) {
  const el = document.createElement('div')
  document.body.append(el)
  const root = createRoot(el)
  await act(async () => { root.render(node) })
  await act(async () => { await Promise.resolve() })
  return { el, unmount: () => act(() => root.unmount()) }
}

afterEach(() => { document.body.innerHTML = '' })

describe('空知识库的两页', () => {
  it('示例事实是看得见的真行，但点不动也 tab 不进去', async () => {
    const { el, unmount } = await mount(<ExampleFacts />)
    const rows = el.querySelectorAll('.fact-row')
    expect(rows.length).toBe(2)
    expect(el.textContent).toContain('示例')
    // 假 id 点开只会是 404：整块必须是 inert。
    // jsdom 没实现 inert 的行为（属性读出来是 undefined），所以这里断言浏览器真正
    // 看的那个东西——属性在不在。**行为在真 Chromium 里量过**：`openclick` 探针
    // 对这一行 `focus()`，`document.activeElement` 不是它（而 clickable() 给它挂了
    // tabIndex=0，没有 inert 就该能聚焦）——第 673 轮。
    const list = el.querySelector('.fact-list') as HTMLElement
    expect(list.hasAttribute('inert')).toBe(true)
    // 而且要长得像真的：日期、说话人、类型、来源角标都在
    expect(el.textContent).toContain('2026-03-04')
    expect(el.textContent).toContain('李工')
    expect(el.textContent).toContain('来自笔记')
    unmount()
  })

  it('库是空的时候，事实表不摆那排筛不出东西的筛选器，而是给出口', async () => {
    const { el, unmount } = await mount(<FactsTable query="" actions={ACTIONS} />)
    expect(el.querySelector('.filter-row')).toBeNull()
    expect(el.textContent).not.toContain('按类型 / 说话人 / 主题 / 实体 / 置信度筛')
    expect(el.textContent).toContain('导入')
    expect(el.textContent).toContain('回知识库总览')
    // 空表也要让人看见它长什么样——这正是原来那个按钮欠下的
    expect(el.querySelectorAll('.kb-example .fact-row').length).toBe(2)
    unmount()
  })
})
