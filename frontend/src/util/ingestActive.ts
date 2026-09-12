import { useEffect, useState } from 'react'

/** 「现在有没有摄入任务在跑」——知识库那些页面只在这时才需要每 3 秒轮询
 *  （事实是分块落库的，边抽边刷出来）；平时库不会自己变，轮询是白打后端。
 *  App 在任务开始 / 结束时设一次，页面用 hook 读。 */
let active = false
const listeners = new Set<(v: boolean) => void>()

export function setIngestActive(v: boolean) {
  if (active === v) return
  active = v
  for (const l of listeners) l(v)
}

export function useIngestActive(): boolean {
  const [v, setV] = useState(active)
  useEffect(() => { listeners.add(setV); return () => { listeners.delete(setV) } }, [])
  return v
}
