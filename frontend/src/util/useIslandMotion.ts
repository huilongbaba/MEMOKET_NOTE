import { useLayoutEffect, useRef, type RefObject } from 'react'

export type SpringAxis = { position: number; velocity: number }
export const ISLAND_COLLAPSED = { width: 240, height: 44 } as const
export const ISLAND_RESPONSE = { open: 0.34, close: 0.28 } as const

/** Exact solution of a critically damped spring, with seconds as the time unit. */
export function advanceIslandSpring(axis: SpringAxis, target: number, seconds: number, response: number): SpringAxis {
  if (seconds <= 0) return { ...axis }
  const omega = 2 * Math.PI / response
  const displacement = axis.position - target
  const coefficient = axis.velocity + omega * displacement
  const decay = Math.exp(-omega * seconds)
  return {
    position: target + (displacement + coefficient * seconds) * decay,
    velocity: (axis.velocity - omega * coefficient * seconds) * decay,
  }
}

export function islandSpringSettled(axis: SpringAxis, target: number): boolean {
  return Math.abs(axis.position - target) < 0.4 && Math.abs(axis.velocity) < 3
}

type Controller = { retarget: (expanded: boolean) => void; nudge: () => void }

/** 收起时窗口比药丸宽（拿主意时药丸要长到 320）：视口不超过这个尺寸都算「原生收起」，不拿它当台面的尺寸。 */
export const ISLAND_COLLAPSED_VIEWPORT = { width: 320, height: 44 } as const

/** Geometry springs live outside React. Content remains at the stable stage dimensions.
 *  `collapsedWidth`：收起时药丸的目标宽度——平时 240，拿主意在读 / 在想时 320，同一根弹簧长过去、缩回来。 */
export function useIslandMotion(ref: RefObject<HTMLElement | null>, expanded: boolean, onCollapsed?: (width: number) => void, collapsedWidth: number = ISLAND_COLLAPSED.width) {
  const latestExpanded = useRef(expanded)
  latestExpanded.current = expanded
  const latestCollapsedWidth = useRef(collapsedWidth)
  latestCollapsedWidth.current = collapsedWidth
  const collapsedCallback = useRef(onCollapsed)
  collapsedCallback.current = onCollapsed
  const controller = useRef<Controller | null>(null)

  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    const parent = element.parentElement
    const screenWidth = window.screen.availWidth || window.innerWidth || 664
    let stageWidth = Math.max(1, Math.min(640, screenWidth - 24))
    let stageHeight = 460
    let width: SpringAxis = { position: ISLAND_COLLAPSED.width, velocity: 0 }
    let height: SpringAxis = { position: ISLAND_COLLAPSED.height, velocity: 0 }
    let progress: SpringAxis = { position: 0, velocity: 0 }
    let targetExpanded = latestExpanded.current
    let frame: number | null = null
    let lastTime = 0
    let disposed = false
    let collapseNotified = false
    const media = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    let reducedMotion = media?.matches ?? false

    function measureStage() {
      if (!parent) return
      const rect = parent.getBoundingClientRect()
      const nextWidth = parent.clientWidth || rect.width
      const nextHeight = parent.clientHeight || rect.height
      // Native collapse resizes the viewport itself. Do not replace the remembered stage.
      const compactViewport = nextWidth <= ISLAND_COLLAPSED_VIEWPORT.width + 1 && nextHeight <= ISLAND_COLLAPSED_VIEWPORT.height + 1
      if (nextWidth > 0 && nextHeight > 0 && !compactViewport) {
        stageWidth = nextWidth
        stageHeight = nextHeight
      }
      element!.style.setProperty('--dc-stage-width', `${stageWidth}px`)
      element!.style.setProperty('--dc-stage-height', `${stageHeight}px`)
    }

    function render() {
      element!.style.setProperty('--dc-width', `${width.position}px`)
      element!.style.setProperty('--dc-height', `${height.position}px`)
      element!.style.setProperty('--dc-progress', String(Math.max(0, Math.min(1, progress.position))))
      element!.style.setProperty('--dc-stage-width', `${stageWidth}px`)
      element!.style.setProperty('--dc-stage-height', `${stageHeight}px`)
    }

    function notifyCollapsed() {
      if (!disposed && !targetExpanded && !collapseNotified) {
        collapseNotified = true
        // 报一下停在多宽：主进程据此决定收起的窗口是 240 还是留 320。
        collapsedCallback.current?.(latestCollapsedWidth.current)
      }
    }

    function snap() {
      width = { position: targetExpanded ? stageWidth : latestCollapsedWidth.current, velocity: 0 }
      height = { position: targetExpanded ? stageHeight : ISLAND_COLLAPSED.height, velocity: 0 }
      progress = { position: targetExpanded ? 1 : 0, velocity: 0 }
      render()
      notifyCollapsed()
    }

    function tick(now: number) {
      frame = null
      if (disposed) return
      const seconds = Math.max(0, (now - lastTime) / 1000)
      lastTime = now
      const targetWidth = targetExpanded ? stageWidth : latestCollapsedWidth.current
      const targetHeight = targetExpanded ? stageHeight : ISLAND_COLLAPSED.height
      const response = targetExpanded ? ISLAND_RESPONSE.open : ISLAND_RESPONSE.close
      width = advanceIslandSpring(width, targetWidth, seconds, response)
      height = advanceIslandSpring(height, targetHeight, seconds, response)
      progress = advanceIslandSpring(progress, targetExpanded ? 1 : 0, seconds, response)
      if (islandSpringSettled(width, targetWidth) && islandSpringSettled(height, targetHeight)) {
        snap()
        return
      }
      render()
      frame = requestAnimationFrame(tick)
    }

    function wake() {
      if (disposed) return
      if (reducedMotion) {
        if (frame !== null) cancelAnimationFrame(frame)
        frame = null
        snap()
      } else if (frame === null) {
        // Only a resting spring gets a new clock. Retargeting preserves the running frame.
        lastTime = performance.now()
        frame = requestAnimationFrame(tick)
      }
    }

    function retarget(nextExpanded: boolean) {
      if (targetExpanded !== nextExpanded) collapseNotified = false
      targetExpanded = nextExpanded
      measureStage()
      wake()
    }

    const onResize = () => { measureStage(); wake() }
    const onReducedMotion = (event: MediaQueryListEvent) => { reducedMotion = event.matches; wake() }
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(onResize)
    if (parent) observer?.observe(parent)
    window.addEventListener('resize', onResize)
    media?.addEventListener('change', onReducedMotion)
    // 目标宽度变了（拿主意开始 / 结束）：重新报一次 settle，320 ↔ 240 之间的那一段弹簧停下来主进程才知道。
    controller.current = { retarget, nudge: () => { collapseNotified = false; wake() } }
    measureStage()
    render()
    wake()

    return () => {
      disposed = true
      if (frame !== null) cancelAnimationFrame(frame)
      observer?.disconnect()
      window.removeEventListener('resize', onResize)
      media?.removeEventListener('change', onReducedMotion)
      controller.current = null
    }
  }, [ref])

  // 药丸的目标宽度变了（拿主意开始 / 结束）：弹簧醒来长过去或缩回来。
  useLayoutEffect(() => { controller.current?.nudge() }, [collapsedWidth])

  useLayoutEffect(() => { controller.current?.retarget(expanded) }, [expanded])
}
