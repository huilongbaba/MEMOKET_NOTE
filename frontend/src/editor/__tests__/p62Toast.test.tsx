// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

/**
 * P62（第 778 轮）：**「同一条 toast 连出两遍」不是产品的，是量具的选择器多选了一个。**
 *
 * P58 / P60 两批的走查日志里都躺着这两行（实拍）：
 *
 *   toast: ["已切换到本地模型：fake-p52 @ http://127.0.0.1:18260/v1",
 *           "已切换到本地模型：fake-p52 @ http://127.0.0.1:18260/v1"]
 *   toast: ["没删成 2026-09-19，这一天还在：…", "没删成 2026-09-19，这一天还在：…"]
 *
 * 两批都把它记成「同一条 toast 连出两遍，下一批去找是哪一层重复派发」。
 * 根因在量具那一侧：`$S/p60/steps/lib52.mjs` 的 `toasts()` 读的是
 *
 *   document.querySelectorAll('[class*="toast"]')
 *
 * 而 `<Toaster/>` 的**外层容器**叫 `toaster` —— 这个串里含 `toast`，
 * 所以通配选择器**同时选中了外层容器和里面那一条**。容器的 `textContent`
 * 正好是里面那一条的正文，于是「一条」读回来是两条一模一样的字。
 *
 * **这是「选不到 ≠ 没有」的镜像**：**「选到两个 ≠ 真有两个」**。
 * 通配选择器（`[class*=…]`）既会漏也会多，多出来的那一份**长得跟真的一模一样**，
 * 比漏更难看出来 —— 漏了是空数组，多了是一段看着像 bug 的证据。
 *
 * 这一份闸把四件事钉死（判据宁可窄）：
 *  ① 一条真 toast + 那个通配选择器 = **2**（复现两批日志里的那个数）
 *  ② 一条真 toast + 精确选择器 `.toaster > .toast` = **1**
 *  ③ **两条真 toast**（用户真连点两次）+ 精确选择器 = **2**
 *     —— 修的是读法，不是给产品加去重；用户连点两次的反馈一条都不许吞
 *  ④ 源码里 `.toaster` 只挂一个、`<Toaster/>` 全仓只挂一处
 *     —— 把「容器被渲染了两遍」这条另一种可能当场排除，不靠推断
 */

const { toast, dismissToast, getSnapshot } = await import('../../toast')
const { default: Toaster } = await import('../../components/Toaster')

/** P58 / P60 两批量具里那个通配读法，逐字照抄（`lib52.mjs` / `lib.mjs` 的 `toasts()`）。 */
const WILDCARD = '[class*="toast"]'
/** 精确读法：容器直属的那几条。 */
const EXACT = '.toaster > .toast'

const read = (el: HTMLElement, sel: string) =>
  Array.from(el.querySelectorAll(sel)).map((e) => (e.textContent ?? '').trim()).filter(Boolean)

async function mount() {
  const el = document.createElement('div')
  document.body.append(el)
  const root = createRoot(el)
  await act(async () => { root.render(<Toaster />) })
  return el
}

beforeEach(() => { for (const t of getSnapshot()) dismissToast(t.id) })
afterEach(() => { document.body.innerHTML = '' })

describe('P62 · 那两遍 toast 是选择器多选的，不是派发了两次', () => {
  it('① 一条真 toast，通配选择器读回来是 2 条一模一样的 —— 两批日志里的那个数', async () => {
    const el = await mount()
    await act(async () => { toast('已切换到本地模型：fake-p52 @ http://127.0.0.1:18260/v1') })

    // 库里**只有一条**：重复派发这条可能性在这里就断掉了
    expect(getSnapshot()).toHaveLength(1)
    // DOM 里也只有一个 .toast
    expect(el.querySelectorAll('.toast')).toHaveLength(1)

    const wild = read(el, WILDCARD)
    expect(wild).toHaveLength(2)
    expect(wild[0]).toBe(wild[1])   // 两条逐字相同 —— 因为其中一条是外层容器
    expect(wild[0]).toBe('已切换到本地模型：fake-p52 @ http://127.0.0.1:18260/v1')
  })

  it('② 同一条 toast，精确选择器读回来是 1 条', async () => {
    const el = await mount()
    await act(async () => { toast('没删成 2026-09-19，这一天还在：Permission denied') })
    expect(read(el, EXACT)).toEqual(['没删成 2026-09-19，这一天还在：Permission denied'])
  })

  it('③ 用户真连点两次 → 两条真 toast，精确选择器照样读回 2 条（不许吞）', async () => {
    const el = await mount()
    await act(async () => { toast('没删成 2026-09-19，这一天还在：Permission denied') })
    await act(async () => { toast('没删成 2026-09-19，这一天还在：Permission denied') })

    expect(getSnapshot()).toHaveLength(2)
    expect(read(el, EXACT)).toHaveLength(2)
    // 通配那份这时候是 3（容器 1 + 真的 2）——「多出来一个容器」这件事在这里再钉一次
    expect(read(el, WILDCARD)).toHaveLength(3)
  })

  it('④ 一条 toast 只渲染一个 `.toast` 节点 —— 「容器渲染了两遍」这条路一并排除', async () => {
    const el = await mount()
    await act(async () => { toast('只此一条') })
    // 整个文档里 `.toaster` 只有一个（这一份自己只挂了一个 <Toaster/>）
    expect(document.querySelectorAll('.toaster')).toHaveLength(1)
    expect(document.querySelectorAll('.toaster > .toast')).toHaveLength(1)
    expect(el.querySelectorAll('.toast')).toHaveLength(1)
  })
})
// 源码那两条（`<Toaster/>` 全仓只挂一处 / toast 存储里没有按 message 的去重）
// 在 `frontend/scripts/check-toast-single.mts` 里 —— vitest 这一侧读不了文件
// （前端的 tsconfig 不带 node 类型，同 `check-margin-dots.mts` 抬头记的那条）。
