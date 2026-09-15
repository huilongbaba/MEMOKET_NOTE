// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { usePoll } from '../../util/poll'

/**
 * 这个 hook 的每一条规矩都对着一个具体的浪费：屏幕活动那一页会整天开着
 * （背后那功能本来就在持续截屏），知识库浏览器在摄入跑着时每 3 秒拉三个接口
 * （一次摄入可能十几分钟）。所以**真跑它**，不是看代码长什么样。
 */
let hidden = false
Object.defineProperty(document, 'hidden', { get: () => hidden, configurable: true })
const setHidden = (v: boolean) => {
  hidden = v
  document.dispatchEvent(new Event('visibilitychange'))
}

function mount(fn: () => void, ms = 1000, on = true) {
  const el = document.createElement('div')
  const root = createRoot(el)
  function Probe({ on: o }: { on: boolean }) { usePoll(fn, ms, o); return null }
  act(() => { root.render(<Probe on={on} />) })
  return {
    rerender: (o: boolean) => act(() => { root.render(<Probe on={o} />) }),
    unmount: () => act(() => { root.unmount() }),
  }
}

afterEach(() => { hidden = false; vi.useRealTimers() })

describe('usePoll 真跑', () => {
  it('看得见的时候按周期做', () => {
    vi.useFakeTimers()
    const fn = vi.fn()
    const h = mount(fn)
    act(() => { vi.advanceTimersByTime(3500) })
    expect(fn).toHaveBeenCalledTimes(3)
    h.unmount()
  })

  it('**窗口看不见就不做**——这是整件事的理由', () => {
    vi.useFakeTimers()
    const fn = vi.fn()
    const h = mount(fn)
    act(() => { setHidden(true) })
    act(() => { vi.advanceTimersByTime(10_000) })
    expect(fn).toHaveBeenCalledTimes(0)
    h.unmount()
  })

  it('**回到前台立刻做一次**，不等下一个周期', () => {
    vi.useFakeTimers()
    const fn = vi.fn()
    const h = mount(fn)
    act(() => { setHidden(true) })
    act(() => { vi.advanceTimersByTime(5000) })
    expect(fn).toHaveBeenCalledTimes(0)
    act(() => { setHidden(false) })
    expect(fn).toHaveBeenCalledTimes(1)      // 一回来就做，没等那 1000ms
    h.unmount()
  })

  it('on=false 整个停掉', () => {
    vi.useFakeTimers()
    const fn = vi.fn()
    const h = mount(fn, 1000, false)
    act(() => { vi.advanceTimersByTime(5000) })
    expect(fn).toHaveBeenCalledTimes(0)
    h.rerender(true)
    act(() => { vi.advanceTimersByTime(2500) })
    expect(fn).toHaveBeenCalledTimes(2)
    h.unmount()
  })

  it('卸载之后不再做，也不留监听', () => {
    vi.useFakeTimers()
    const fn = vi.fn()
    const h = mount(fn)
    h.unmount()
    act(() => { vi.advanceTimersByTime(10_000); setHidden(false) })
    expect(fn).toHaveBeenCalledTimes(0)
  })

  it('每次渲染传新闭包也不会把周期重置——定时器不跟着回调重建', () => {
    vi.useFakeTimers()
    let calls = 0
    const el = document.createElement('div')
    const root = createRoot(el)
    function Probe({ n }: { n: number }) { usePoll(() => { calls += 1; void n }, 1000); return null }
    act(() => { root.render(<Probe n={0} />) })
    for (let i = 1; i <= 9; i++) {
      act(() => { vi.advanceTimersByTime(100) })
      act(() => { root.render(<Probe n={i} />) })   // 每 100ms 重渲染一次，闭包每次都是新的
    }
    act(() => { vi.advanceTimersByTime(150) })
    expect(calls).toBe(1)                            // 周期没被重置，1000ms 到了就该有一次
    act(() => { root.unmount() })
  })
})
