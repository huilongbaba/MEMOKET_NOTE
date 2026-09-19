// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * P23 #8：临界条件表（`docs/edge-cases.md`）剩下的 ？ 里，前端这三格。
 *
 *   · 写作计划 · 「生成写作计划」× 超时 —— 转起来没有「停止」（D 组）
 *   · 引用 · 补一条 × 空输入 —— 什么都没写点「加上」，**一声不吭地关掉那个框**（E 组）
 *   · 引用 · 改 × 空文本 —— 清空之后点「保存」，同样一声不吭，正文原样留着（E 组）
 *
 * 三格都先在真 app 上复现过（`p23-fact-add-empty-before-light` / `p23-fact-edit-empty-*`），
 * 这里钉的是**用户看得见的结果**：钮点不点得动、那个框还在不在、停了说不说一句。
 */

const toasts: { text: string; kind?: string }[] = []
vi.mock('../../toast', () => ({
  toast: (text: string, kind?: string) => { toasts.push({ text, kind }) },
  toastAction: (text: string) => { toasts.push({ text }) },
}))

let planSignal: AbortSignal | undefined
const added: string[] = []
const updated: string[] = []

vi.mock('../../api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../api')
  return {
    ...actual,
    getWritingPlan: () => Promise.resolve({ plan: null, sections: [] }),
    // 挂着不回，直到被 abort——这就是「模型收下请求不回」那一列
    startWritingPlan: (_f: string, _g: string, signal?: AbortSignal) => {
      planSignal = signal
      return new Promise((_res, rej) => {
        signal?.addEventListener('abort', () => {
          const e = new Error('aborted'); e.name = 'AbortError'; rej(e)
        })
      })
    },
    noteKb: () => Promise.resolve({ facts: [{ id: 'f-1', text: '4月10日定了三条标准', when: '2026-04-10', who: '', kind: '', manual: true }], stale: false, ingested_at: '2026-09-15T00:00:00Z' }),
    noteGraph: () => Promise.resolve({ topics: [], entities: [], links: [] }),
    addFact: (_n: string, t: string) => { added.push(t); return Promise.resolve({ id: 'f-2', text: t }) },
    updateFact: (id: string, t: string) => { updated.push(`${id}=${t}`); return Promise.resolve({ id, text: t }) },
    deleteFact: () => Promise.resolve({}),
    factPeek: () => Promise.resolve(null),
    notesCiting: () => Promise.resolve([]),
  }
})

const { default: WritingPlanPanel } = await import('../../components/WritingPlanPanel')
const { default: NoteKbPanel } = await import('../../components/NoteKbPanel')

async function mount(node: React.ReactNode) {
  const el = document.createElement('div')
  document.body.append(el)
  const root = createRoot(el)
  await act(async () => { root.render(node) })
  await act(async () => { await Promise.resolve() })
  await act(async () => { await Promise.resolve() })
  return { el, unmount: () => act(() => root.unmount()) }
}

const click = async (el: Element) => { await act(async () => { (el as HTMLElement).click() }) }
const type = async (el: Element, v: string) => {
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, v)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
const byText = (el: HTMLElement, t: string) =>
  Array.from(el.querySelectorAll('button')).find((b) => (b.textContent ?? '').replace(/\s+/g, '').includes(t.replace(/\s+/g, '')))

Element.prototype.scrollIntoView = function scrollIntoView() { /* jsdom 里没有 */ }

beforeEach(() => { toasts.length = 0; added.length = 0; updated.length = 0; planSignal = undefined })
afterEach(() => { document.body.innerHTML = '' })

const ROW = { note_id: 'folder-1', parent_note_id: 'root', title: '创业一年', child_count: 3 } as never

describe('#8 写作计划 · 「生成写作计划」转起来要能停', () => {
  const panel = () => (
    <WritingPlanPanel parent={ROW} onClose={() => {}} onNoteChanged={() => {}}
                      harness={null} onRun={() => {}} onToggleFollow={() => {}}
                      confirm={() => Promise.resolve(true)} />
  )

  it('第二下 = 停止，而且停了要说一句', async () => {
    const { el } = await mount(panel())
    await type(el.querySelector('textarea[aria-label="写作目标"]')!, '把三条线各写一篇')
    await click(byText(el, '生成写作计划')!)
    // 转起来之后**不禁用**：那一下是出口，禁了这次跑就没有出口了
    const stop = byText(el, '停止')!
    expect(stop).toBeTruthy()
    expect(stop.disabled).toBe(false)
    expect(planSignal).toBeTruthy()
    expect(planSignal!.aborted).toBe(false)
    await click(stop)
    expect(planSignal!.aborted).toBe(true)
    await act(async () => { await Promise.resolve() })
    expect(toasts.map((t) => t.text).join(' ')).toContain('已停止')
    // 目标留在框里，能直接再来一次
    expect((el.querySelector('textarea[aria-label="写作目标"]') as HTMLTextAreaElement).value)
      .toBe('把三条线各写一篇')
  })

  it('目标是空的时候还是点不动（原来那条规矩没被「停止」顶掉）', async () => {
    const { el } = await mount(panel())
    expect(byText(el, '生成写作计划')!.disabled).toBe(true)
  })
})

describe('#8 引用 · 补一条 / 改 的空文本', () => {
  const panel = () => (
    <NoteKbPanel citedIds={[]} row={{ note_id: 'n-1', parent_note_id: 'root', title: 'x',
                                      ingested_at: '2026-09-15T00:00:00Z', updated_at: '2026-09-15T00:00:00Z' } as never}
                 noteId="n-1" onOpenNote={() => {}} onIngest={() => {}} onSync={() => {}}
                 ingesting={false} empty={false} />
  )

  it('补一条：什么都没写，「加上」点不动，那个框也不会一声不吭地关掉', async () => {
    const { el } = await mount(panel())
    await click(byText(el, '补一条')!)
    const add = byText(el, '加上')!
    expect(add.disabled).toBe(true)
    expect(add.title).toContain('先写一句')
    await click(add)
    expect(added).toEqual([])
    expect(el.querySelector('textarea[aria-label="新增一条事实"]')).toBeTruthy()   // 框还在
  })

  it('补一条：写了字就点得动', async () => {
    const { el } = await mount(panel())
    await click(byText(el, '补一条')!)
    await type(el.querySelector('textarea[aria-label="新增一条事实"]')!, '4月16日 EVT 4 台主板')
    expect(byText(el, '加上')!.disabled).toBe(false)
    await click(byText(el, '加上')!)
    expect(added).toEqual(['4月16日 EVT 4 台主板'])
  })

  it('改：清空之后「保存」点不动，并说清「要去掉就用删」', async () => {
    const { el } = await mount(panel())
    await click(el.querySelector('.icon-btn[title="改"]')!)
    const box = el.querySelector('textarea[aria-label="改这条事实"]')!
    await type(box, '   ')                       // 全是空白也算空
    const save = byText(el, '保存')!
    expect(save.disabled).toBe(true)
    expect(save.title).toContain('删掉这条')
    await click(save)
    expect(updated).toEqual([])
    expect(el.querySelector('textarea[aria-label="改这条事实"]')).toBeTruthy()      // 框还在
  })

  it('改：改成别的字照样存得下去', async () => {
    const { el } = await mount(panel())
    await click(el.querySelector('.icon-btn[title="改"]')!)
    await type(el.querySelector('textarea[aria-label="改这条事实"]')!, '改过的一句话')
    await click(byText(el, '保存')!)
    expect(updated).toEqual(['f-1=改过的一句话'])
  })
})
