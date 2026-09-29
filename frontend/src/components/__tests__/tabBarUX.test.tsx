// @vitest-environment jsdom
import { act, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import TabBar, { type Tab } from '../TabBar'

const tabs: Tab[] = [
  { id: 'tab-a', noteId: 'note-a', title: '项目计划' },
  { id: 'tab-b', noteId: 'note-b', title: '会议记录' },
  { id: 'tab-c', noteId: 'note-c', title: '待办事项' },
]

class TestResizeObserver implements ResizeObserver {
  static instances: TestResizeObserver[] = []
  readonly targets = new Set<Element>()
  constructor(private callback: ResizeObserverCallback) { TestResizeObserver.instances.push(this) }
  observe(target: Element) { this.targets.add(target) }
  unobserve(target: Element) { this.targets.delete(target) }
  disconnect() { this.targets.clear() }
  static notify(target: Element) {
    for (const observer of [...TestResizeObserver.instances]) {
      if (observer.targets.has(target)) observer.callback([], observer)
    }
  }
}

describe('TabBar desktop interactions', () => {
  let host: HTMLDivElement
  let root: Root
  let rowWidth: number
  let stripWidth: number
  let stripScrollWidth: number
  let captureWidth: number
  const originalScrollIntoView = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView')
  const onSelect = vi.fn()
  const onClose = vi.fn()

  beforeEach(() => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
    vi.stubGlobal('ResizeObserver', TestResizeObserver)
    TestResizeObserver.instances = []
    Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() })
    rowWidth = 1200
    stripWidth = 730
    stripScrollWidth = 730
    captureWidth = 120
    // jsdom has no layout. Keep parent and strip geometry independent to reproduce
    // the old flex layout: a narrowed strip stays small until its tabs grow again.
    vi.spyOn(Element.prototype, 'clientWidth', 'get').mockImplementation(function (this: Element) {
      return this.classList.contains('tab-row') ? rowWidth : this.classList.contains('tab-strip') ? stripWidth : 0
    })
    vi.spyOn(Element.prototype, 'scrollWidth', 'get').mockImplementation(function (this: Element) {
      return this.classList.contains('tab-strip') ? stripScrollWidth : 0
    })
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
      const width = this.classList.contains('test-navigation') ? 80
        : this.classList.contains('test-capture') ? captureWidth
          : this.classList.contains('note-new-tab') ? 36
            : this.classList.contains('tab-scroll') ? 28 : 0
      return { x: 0, y: 0, left: 0, top: 0, right: width, bottom: 40, width, height: 40, toJSON: () => ({}) }
    })
    onSelect.mockClear()
    onClose.mockClear()
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
  })

  afterEach(() => {
    act(() => root.unmount())
    expect(TestResizeObserver.instances.every(observer => observer.targets.size === 0)).toBe(true)
    host.remove()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    if (originalScrollIntoView) Object.defineProperty(Element.prototype, 'scrollIntoView', originalScrollIntoView)
    else Reflect.deleteProperty(Element.prototype, 'scrollIntoView')
  })

  function Harness({ initialActiveId }: { initialActiveId: string | null }) {
    const [activeId, setActiveId] = useState(initialActiveId)
    return <div className="tab-row" style={{ columnGap: '8px', paddingLeft: 0, paddingRight: 0 }}>
      <button className="test-navigation">上一页</button>
      <button className="test-capture">快速捕捉</button>
      <TabBar tabs={tabs} activeId={activeId} onSelect={(id) => { onSelect(id); setActiveId(id) }} onClose={onClose} onNew={() => {}} onListTabs={() => {}} />
    </div>
  }
  function render(activeId: string | null = 'tab-a') {
    act(() => root.render(<Harness initialActiveId={activeId} />))
  }
  function tabElements() { return [...host.querySelectorAll<HTMLElement>('[role="tab"]')] }
  function strip() { return host.querySelector<HTMLDivElement>('.tab-strip')! }
  function row() { return host.querySelector<HTMLDivElement>('.tab-row')! }
  function key(element: HTMLElement, value: string) {
    const event = new KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true })
    act(() => { element.dispatchEvent(event) })
    return event
  }
  function expectSelected(index: number) {
    const elements = tabElements()
    expect(elements.filter(element => element.tabIndex === 0)).toEqual([elements[index]])
    expect(elements.filter(element => element.getAttribute('aria-selected') === 'true')).toEqual([elements[index]])
    expect(document.activeElement).toBe(elements[index])
    expect(onSelect).toHaveBeenLastCalledWith(tabs[index].id)
  }

  it('grows tabs again after the window narrows, even while the strip retains its narrow width', () => {
    render()
    expect(strip().style.getPropertyValue('--tab-w')).toBe('240px')
    act(() => {
      rowWidth = 560
      stripWidth = 380
      stripScrollWidth = 394
      TestResizeObserver.notify(row())
      TestResizeObserver.notify(strip())
    })
    expect(strip().style.getPropertyValue('--tab-w')).toBe('128px')
    expect(strip().dataset.size).toBe('narrow')
    expect(host.querySelector('button[title="往右看"]')).not.toBeNull()

    act(() => {
      rowWidth = 1200
      TestResizeObserver.notify(row())
    })
    expect(strip().clientWidth).toBe(380)
    expect(strip().style.getPropertyValue('--tab-w')).toBe('240px')
    expect(strip().dataset.size).toBe('')
    act(() => {
      stripWidth = 730
      stripScrollWidth = 730
      TestResizeObserver.notify(strip())
    })
    expect(host.querySelector('button[title="往右看"]')).toBeNull()
    expect(strip().style.getPropertyValue('--tab-w')).toBe('240px')
  })

  it('remeasures available space when a sibling control changes width', () => {
    render()
    const capture = host.querySelector('.test-capture')!
    act(() => { captureWidth = 420; TestResizeObserver.notify(capture) })
    const narrower = parseInt(strip().style.getPropertyValue('--tab-w'))
    expect(narrower).toBeGreaterThan(128)
    expect(narrower).toBeLessThan(240)
    act(() => { captureWidth = 120; TestResizeObserver.notify(capture) })
    expect(strip().style.getPropertyValue('--tab-w')).toBe('240px')
  })

  it('selects and focuses tabs with arrows, Home and End, keeping one roving tab stop', () => {
    render()
    tabElements()[0].focus()
    expect(key(tabElements()[0], 'ArrowRight').defaultPrevented).toBe(true)
    expectSelected(1)
    key(tabElements()[1], 'End')
    expectSelected(2)
    key(tabElements()[2], 'ArrowRight')
    expectSelected(0)
    key(tabElements()[0], 'ArrowLeft')
    expectSelected(2)
    key(tabElements()[2], 'Home')
    expectSelected(0)
  })

  it.each(['Enter', ' '])('activates a focused tab with %j', (activationKey) => {
    render()
    const target = tabElements()[2]
    target.focus()
    expect(key(target, activationKey).defaultPrevented).toBe(true)
    expectSelected(2)
    expect(onSelect).toHaveBeenCalledOnce()
  })

  it.each([null, 'removed-tab'])('provides one reachable tab when activeId is %j', (activeId) => {
    render(activeId)
    expect(tabElements().map(element => element.tabIndex)).toEqual([0, -1, -1])
    tabElements()[0].focus()
    key(tabElements()[0], 'Enter')
    expectSelected(0)
  })

  it('closes an inactive tab without selecting it or responding to its close button keydown', () => {
    render()
    const close = tabElements()[1].querySelector<HTMLButtonElement>('button[aria-label="关闭 会议记录"]')!
    close.focus()
    key(close, 'Enter')
    expect(onSelect).not.toHaveBeenCalled()
    act(() => close.click())
    expect(onClose).toHaveBeenCalledExactlyOnceWith('tab-b')
    expect(onSelect).not.toHaveBeenCalled()
    expect(tabElements()[0].getAttribute('aria-selected')).toBe('true')
    expect(tabElements().map(element => element.tabIndex)).toEqual([0, -1, -1])
  })
})
