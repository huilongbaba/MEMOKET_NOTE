import { useEffect, useRef } from 'react'

/**
 * 每隔一会儿做一次，**窗口看不见的时候不做**。
 *
 * 抽出来是因为这条规矩要在两个地方成立，而两处都容易写漏一半：
 *
 * · 屏幕活动那一页会整天开着，背后那个功能本来就在持续截屏——后台还每半分钟
 *   发两个请求纯属白费；
 * · 知识库浏览器在摄入跑着时每 3 秒拉三个接口，而一次摄入可能跑十几分钟。
 *
 * **回到前台立刻做一次**，不等下一个周期：不然切回来看到的是上一轮的旧状态，
 * 而「切回来看一眼」正是用户切回来的原因。
 *
 * `on` 为 false 时整个停掉（调用方用它表达「现在不需要轮询」）。
 */
export function usePoll(fn: () => void, ms: number, on = true): void {
  // 把回调放 ref 里：调用方几乎总是传一个每次渲染都新建的闭包，
  // 进依赖数组会让定时器每渲染一次就重建一次（等于周期永远重新开始）。
  const cb = useRef(fn)
  cb.current = fn

  useEffect(() => {
    if (!on) return
    let timer: number | null = null
    const tick = () => { if (!document.hidden) cb.current() }
    const start = () => { if (timer === null) timer = window.setInterval(tick, ms) }
    const stop = () => { if (timer !== null) { window.clearInterval(timer); timer = null } }
    const onVis = () => { if (document.hidden) stop(); else { cb.current(); start() } }
    start()
    document.addEventListener('visibilitychange', onVis)
    return () => { stop(); document.removeEventListener('visibilitychange', onVis) }
  }, [ms, on])
}
