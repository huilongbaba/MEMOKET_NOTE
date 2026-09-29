// @vitest-environment jsdom
import { act, useRef } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useIslandMotion } from '../useIslandMotion'

let root: Root | undefined
let host: HTMLDivElement
let now: number
let frameId: number
let frames: Map<number, FrameRequestCallback>
let mediaListener: ((event: MediaQueryListEvent) => void) | undefined
let resizeListener: (() => void) | undefined
let reduced = false
const disconnect = vi.fn()
const removeMediaListener = vi.fn()

beforeEach(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  now = 0; frameId = 0; frames = new Map(); reduced = false
  mediaListener = undefined; resizeListener = undefined
  disconnect.mockClear(); removeMediaListener.mockClear()
  vi.spyOn(performance, 'now').mockImplementation(() => now)
  vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => { frames.set(++frameId, callback); return frameId }))
  vi.stubGlobal('cancelAnimationFrame', vi.fn((id: number) => { frames.delete(id) }))
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    get matches() { return reduced },
    addEventListener: (_: string, listener: (event: MediaQueryListEvent) => void) => { mediaListener = listener },
    removeEventListener: removeMediaListener,
  })))
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: () => void) { resizeListener = callback }
    observe() {}
    disconnect() { disconnect() }
  })
  host = document.createElement('div')
  Object.defineProperty(host, 'clientWidth', { configurable: true, value: 640 })
  Object.defineProperty(host, 'clientHeight', { configurable: true, value: 460 })
  document.body.append(host)
  root = createRoot(host)
})

afterEach(async () => {
  await act(async () => { root?.unmount() })
  root = undefined
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function Motion({ expanded, onCollapsed }: { expanded: boolean; onCollapsed?: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  useIslandMotion(ref, expanded, onCollapsed)
  return <div ref={ref} />
}
async function render(expanded: boolean, onCollapsed?: () => void) {
  await act(async () => { root!.render(<Motion expanded={expanded} onCollapsed={onCollapsed} />) })
  return host.firstElementChild as HTMLElement
}
async function frame(milliseconds: number) {
  now += milliseconds
  const callbacks = [...frames.values()]
  frames.clear()
  await act(async () => { callbacks.forEach((callback) => callback(now)) })
}
function value(element: HTMLElement, property: string) { return parseFloat(element.style.getPropertyValue(property)) }

describe('island motion lifecycle', () => {
  it('retargets its existing frame and never delivers a stale collapse callback after reopening', async () => {
    const collapsed = vi.fn()
    const element = await render(true, collapsed)
    await frame(120)
    const width = value(element, '--dc-width')
    const pending = [...frames.keys()]
    await render(false, collapsed)
    expect(value(element, '--dc-width')).toBe(width)
    expect([...frames.keys()]).toEqual(pending)
    await frame(20)
    await render(true, collapsed)
    await frame(900)
    expect(value(element, '--dc-width')).toBe(640)
    expect(value(element, '--dc-height')).toBe(460)
    expect(collapsed).not.toHaveBeenCalled()
    await render(false, collapsed)
    await frame(900)
    expect(collapsed).toHaveBeenCalledTimes(1)
    await act(async () => { resizeListener?.() })
    await frame(30)
    expect(collapsed).toHaveBeenCalledTimes(1)
  })

  it('keeps stage size through native compact resize and responds to expanded viewport changes', async () => {
    const element = await render(true)
    await frame(1000)
    Object.defineProperty(host, 'clientWidth', { configurable: true, value: 580 })
    await act(async () => { resizeListener?.() })
    await frame(1000)
    expect(value(element, '--dc-width')).toBe(580)
    await render(false)
    await frame(1000)
    Object.defineProperty(host, 'clientWidth', { configurable: true, value: 240 })
    Object.defineProperty(host, 'clientHeight', { configurable: true, value: 44 })
    await act(async () => { resizeListener?.() })
    expect(value(element, '--dc-stage-width')).toBe(580)
    expect(value(element, '--dc-stage-height')).toBe(460)
    expect(value(element, '--dc-width')).toBe(240)
  })

  it('snaps immediately when reduced motion changes and removes every scheduled resource on unmount', async () => {
    const collapsed = vi.fn()
    const element = await render(true, collapsed)
    await frame(40)
    expect(value(element, '--dc-width')).toBeLessThan(640)
    await act(async () => { reduced = true; mediaListener?.({ matches: true } as MediaQueryListEvent) })
    expect(value(element, '--dc-width')).toBe(640)
    expect(value(element, '--dc-progress')).toBe(1)
    expect(frames.size).toBe(0)
    await render(false, collapsed)
    expect(value(element, '--dc-height')).toBe(44)
    expect(collapsed).toHaveBeenCalledTimes(1)
    await act(async () => { reduced = false; mediaListener?.({ matches: false } as MediaQueryListEvent) })
    await render(true, collapsed)
    expect(frames.size).toBe(1)
    await act(async () => { root!.unmount() })
    root = undefined
    expect(frames.size).toBe(0)
    expect(disconnect).toHaveBeenCalledTimes(1)
    expect(removeMediaListener).toHaveBeenCalledTimes(1)
    await frame(1000)
    expect(collapsed).toHaveBeenCalledTimes(1)
  })
})
