// @vitest-environment jsdom
/**
 * P85 A（第 810 轮）：**`components/` 下第一条跑得起来的前端闸。**
 *
 * ── 为什么这个文件在这儿，而不是在 `src/editor/__tests__/` ────────────────
 * P81 ⑤ / P82 ④ 连着两批留着同一句话：
 *
 *     「`components/kb/` 今天跑不起来前端测试，全部靠后端源码对拍钉」
 *
 * **这句话的形状记错了，这一批量清楚了**（数见 `docs/TRACELOG-product.md` P85 A）：
 *
 *   - `src/components/` 底下 **70 个文件**（顶层 59 + `kb/` 11），**0 个测试文件**；
 *     96 个测试文件**全部**在 `src/editor/__tests__/`。这一条是真的。
 *   - 但**不是「跑不起来」**：vitest 这个仓没有 `test.include` 覆盖，走的是默认那条
 *     `{test,spec}.?(c|m)[jt]s?(x)` 通配。开工时在 `src/components/__tests__/` 放了一个
 *     一行的探针，`vitest run` 当场 **96 → 97 文件 / 854 → 855 条**——**收得到**。
 *   - 真正缺的是**东西**，不是路：`src/editor/__tests__` 里 import 到 `components/` 的
 *     有 **29/70** 个文件，`kb/` 那 11 个里只有 **2 个**（`FactsTable` / `KbBits`），
 *     而 **`KbDashboard.tsx` 一条测试都没有** —— P79 ② / P81 ③ / P82 ③ 三批点名的
 *     那一行正好就长在它身上。
 *
 * 所以这一批开的不是「搬家」，是**在 `components/` 底下摆第一条真闸**，
 * 靶子挑那条被点名了三批的：**0 条结果时那几个词叫「找过」，不叫「命中词」。**
 *
 * ── 这条测试核的是哪一行（`components/kb/KbDashboard.tsx`）──────────────
 *
 *     {hits.terms.length ? (hits.facts.length ? ' · 命中词：' : ' · 找过：')
 *                          + hits.terms.slice(0, 6).join('、') : ''}
 *
 * 三件事，一件一条：
 *   ① 有结果 → `命中词：`，**并且 `找过：` 一个字都不许出现**；
 *   ② 0 条结果 → `找过：`，**并且 `命中词：` 一个字都不许出现**（P81 ③ 落的那一刀）；
 *   ③ `terms` 空 → **整段不渲染**（P82 ③ 判「不修」的那条路：后端确实什么都没找过，
 *      摆哪一串都是替一次没发生过的检索编说法）。
 * 外加 ④ `slice(0, 6)`：**摆出来的串数钉死 6**。这个 6 `kb_search_ruler.SHOW` 抄着，
 * 而 P79 第 ⑤ 刀实拍过「把它 6 → 3，**那把尺自己量不到**」——现在产品这一侧自己有闸了。
 *
 * ⚠️ **「看到 ≠ 真在正文里」**：判据不看 `el.textContent` 里有没有那个串，
 * 而是**只读那一行自己那个节点**（`.kb-section-title` 的下一个兄弟 = `KbSection` 的 `extra`）。
 * 整页搜串会把图例、空态文案、事实正文一起算进来。
 */
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { setPendingKbQuery } from '../../util/pendingKbQuery'

type Fact = { id: string; text: string; when: string; kind: string }

/** 这一趟 `recall()` 该回什么。每条用例自己摆。 */
let reply: { facts: Fact[]; took_ms: number; terms: string[] } = { facts: [], took_ms: 0, terms: [] }

vi.mock('../../api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../api')
  return {
    ...actual,
    // **非空库**：空库那一支不摆搜索框，也就不会摆那一行（`stats.facts === 0` 的分支）。
    kbDashboard: () => Promise.resolve({
      stats: { facts: 1234, topics: 12, entities: 34, units: 5, lines: 9999,
               start_date: '2026-01-01', end_date: '2026-09-01' },
      months: [], top_topics: [], top_entities: [], recent_units: [], kinds: [], speakers: [],
    }),
    kbConflicts: () => Promise.resolve({ conflicts: [], open: 0 }),
    recall: () => Promise.resolve(reply),
  }
})

const { default: KbDashboard } = await import('../kb/KbDashboard')

const ACTIONS = { onOpen: () => {}, onOpenNote: () => {}, onCite: null }
const fact = (i: number): Fact => ({ id: `f${i}`, text: `第 ${i} 条事实`, when: '2026-07-0' + (i % 9 + 1), kind: '' })

/** 挂上去，等过那 250ms 的防抖 + 那一问回来。 */
async function mountWithQuery(q: string) {
  setPendingKbQuery(q)
  const el = document.createElement('div')
  document.body.append(el)
  const root = createRoot(el)
  await act(async () => { root.render(<KbDashboard actions={ACTIONS} />) })
  await act(async () => { await new Promise((r) => setTimeout(r, 320)) })
  return el
}

/** 屏幕上**那一行**自己那个节点（`KbSection` 的 `extra`），不是整页。 */
function termsLine(el: HTMLElement): string {
  const title = el.querySelector('.kb-section-title')
  if (!title) throw new Error('那一节没渲染出来——先看 hits 是不是 null，而不是改判据')
  const extra = title.nextElementSibling
  if (!extra) throw new Error('那一节有标题没有 extra——那一行整个没了')
  return extra.textContent ?? ''
}

afterEach(() => { document.body.innerHTML = ''; setPendingKbQuery('') })

describe('P85 A：知识库搜索框那一行（`components/` 下第一条前端闸）', () => {
  it('① 有结果 → 说「命中词：」，「找过：」一个字都不出现', async () => {
    reply = { facts: [fact(1), fact(2)], took_ms: 7, terms: ['潜水艇', '排期'] }
    const el = await mountWithQuery('潜水艇 排期')
    const line = termsLine(el)
    expect(line).toContain('命中词：')
    expect(line).not.toContain('找过：')
    expect(line).toContain('潜水艇、排期')
    // 标题那一格也得对上，不然「2 条结果」和「命中词」说的不是同一批东西
    expect(el.querySelector('.kb-section-title')?.textContent).toBe('2 条结果')
  })

  it('② 0 条结果 → 说「找过：」，「命中词：」一个字都不出现（P81 ③ 那一刀）', async () => {
    reply = { facts: [], took_ms: 3, terms: ['潜水艇'] }
    const el = await mountWithQuery('潜水艇')
    const line = termsLine(el)
    expect(line).toContain('找过：')
    expect(line).not.toContain('命中词：')
    expect(line).toContain('潜水艇')
    expect(el.querySelector('.kb-section-title')?.textContent).toBe('0 条结果')
  })

  it('③ terms 空 → 那一段整个不渲染（既不说「找过」也不说「命中词」）', async () => {
    reply = { facts: [], took_ms: 2, terms: [] }
    const el = await mountWithQuery('zzzz')
    const line = termsLine(el)
    expect(line).not.toContain('找过：')
    expect(line).not.toContain('命中词：')
    // 毫秒数还在——**空的是那几个词，不是整个 extra**
    expect(line).toContain('ms')
  })

  it('④ 摆出来的串数钉死 6（`slice(0, 6)`，`kb_search_ruler.SHOW` 抄的就是它）', async () => {
    const terms = ['一', '二', '三', '四', '五', '六', '七', '八']
    reply = { facts: [], took_ms: 1, terms }
    const el = await mountWithQuery('一二三四五六七八')
    const line = termsLine(el)
    const shown = line.slice(line.indexOf('找过：') + '找过：'.length).split('、')
    expect(shown).toEqual(['一', '二', '三', '四', '五', '六'])
    expect(line).not.toContain('七')
    expect(line).not.toContain('八')
  })
})
