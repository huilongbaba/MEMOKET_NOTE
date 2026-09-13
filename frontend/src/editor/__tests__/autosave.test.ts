import { describe, expect, it, vi } from 'vitest'
import { createAutosave } from '../../util/autosave'

describe('createAutosave', () => {
  it('停手之后只存最后一版', async () => {
    vi.useFakeTimers()
    const save = vi.fn(async () => {})
    const a = createAutosave({ delay: 500, save })
    a.change('a'); a.change('ab'); a.change('abc')
    expect(a.dirty()).toBe(true)
    await vi.advanceTimersByTimeAsync(499)
    expect(save).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(save).toHaveBeenCalledTimes(1)
    expect(save).toHaveBeenCalledWith('abc')
    expect(a.dirty()).toBe(false)
    vi.useRealTimers()
  })

  it('存的过程中又改了：存完紧接着再存，不并发', async () => {
    vi.useFakeTimers()
    let release: () => void = () => {}
    const calls: string[] = []
    const save = vi.fn((c: string) => { calls.push(c); return new Promise<void>((r) => { release = r }) })
    const a = createAutosave({ delay: 100, save })
    a.change('v1')
    await vi.advanceTimersByTimeAsync(100)
    expect(calls).toEqual(['v1'])
    a.change('v2')
    await vi.advanceTimersByTimeAsync(100)
    expect(calls).toEqual(['v1'])          // v1 还没回来，v2 排队
    release()
    await vi.advanceTimersByTimeAsync(0)
    expect(calls).toEqual(['v1', 'v2'])
    release()
    await vi.advanceTimersByTimeAsync(0)
    expect(a.dirty()).toBe(false)
    vi.useRealTimers()
  })

  it('flush 立刻存；dispose 丢掉没存的', async () => {
    vi.useFakeTimers()
    const save = vi.fn(async () => {})
    const a = createAutosave({ delay: 10_000, save })
    a.change('x')
    await a.flush()
    expect(save).toHaveBeenCalledWith('x')
    const b = createAutosave({ delay: 10_000, save })
    b.change('y'); b.dispose()
    await vi.advanceTimersByTimeAsync(20_000)
    expect(save).toHaveBeenCalledTimes(1)
    expect(b.dirty()).toBe(false)
    vi.useRealTimers()
  })

  it('存失败：报错、内容留着、下次改动再试', async () => {
    vi.useFakeTimers()
    let fail = true
    const save = vi.fn(async () => { if (fail) throw new Error('boom') })
    const onError = vi.fn()
    const a = createAutosave({ delay: 100, save, onError })
    a.change('z')
    await vi.advanceTimersByTimeAsync(100)
    expect(onError).toHaveBeenCalledTimes(1)
    expect(a.dirty()).toBe(true)
    await vi.advanceTimersByTimeAsync(5_000)
    expect(save).toHaveBeenCalledTimes(1)     // 不自动重试
    fail = false
    a.change('z2')
    await vi.advanceTimersByTimeAsync(100)
    expect(save).toHaveBeenLastCalledWith('z2')
    expect(a.dirty()).toBe(false)
    vi.useRealTimers()
  })
})
