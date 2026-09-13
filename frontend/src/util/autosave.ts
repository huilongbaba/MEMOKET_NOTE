/** 防抖自动保存（分屏第二栏用）。
 *
 *  规则：改动之后停 `delay` 毫秒再存；存的过程中又改了，存完紧接着再存一次（不丢最后
 *  一笔，也不并发两个 PUT 互相覆盖）；`flush()` 立刻存（关分屏 / 切笔记前）；`dispose()`
 *  丢掉没存的（探针模式、笔记已经不在了）。存失败不吞：交给 `onError`，内容留在内存里，
 *  下次改动会再试。 */
export type Autosave = {
  change(content: string): void
  flush(): Promise<void>
  dispose(): void
  /** 有没有还没落库的改动 */
  dirty(): boolean
}

export function createAutosave(opts: {
  delay: number
  save: (content: string) => Promise<void>
  onError?: (e: unknown) => void
  setTimer?: (fn: () => void, ms: number) => unknown
  clearTimer?: (t: unknown) => void
}): Autosave {
  const setT = opts.setTimer ?? ((fn, ms) => setTimeout(fn, ms))
  const clearT = opts.clearTimer ?? ((t) => clearTimeout(t as ReturnType<typeof setTimeout>))
  let pending: string | null = null
  let timer: unknown = null
  let inflight: Promise<void> | null = null
  let disposed = false

  async function run(): Promise<void> {
    if (inflight) return inflight
    inflight = (async () => {
      while (pending !== null && !disposed) {
        const c = pending
        pending = null
        try { await opts.save(c) }
        catch (e) {
          // 失败的那一笔放回去等下次；没有更新的改动就不再自动重试（避免坏网络下打个不停）
          if (pending === null) pending = c
          opts.onError?.(e)
          break
        }
      }
    })().finally(() => { inflight = null })
    return inflight
  }

  return {
    change(content) {
      if (disposed) return
      pending = content
      if (timer !== null) clearT(timer)
      timer = setT(() => { timer = null; void run() }, opts.delay)
    },
    async flush() {
      if (timer !== null) { clearT(timer); timer = null }
      if (pending === null && !inflight) return
      await run()
    },
    dispose() {
      disposed = true
      if (timer !== null) { clearT(timer); timer = null }
      pending = null
    },
    dirty() { return pending !== null || inflight !== null },
  }
}
