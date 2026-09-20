/**
 * P45 #2：「我连的是谁」的自检（`util/backendIdentity`）。
 *
 * P44 实拍：同机第二份 app，窗口的 `location.origin` 还钉在 47231 上，
 * 而这份实例的后端在 47232——屏幕上摆的是**另一份实例的库**，一个字都看不出来。
 * 这里钉的是那把尺子本身：**对不上要吵，「不知道」不许当「不一样」**。
 */
import { describe, expect, it } from 'vitest'
import { compareIdentity } from '../../util/backendIdentity'

const shell = { port: 47232, pid: 8811, dataDir: '/Users/x/Library/Application Support/app/data' }

describe('compareIdentity', () => {
  it('端口和 pid 都对上了：一句话都不说', () => {
    expect(compareIdentity(shell, 'http://127.0.0.1:47232', { pid: 8811 })).toEqual([])
  })

  it('P44 那一屏：窗口指着 47231、自己的后端在 47232 → 吵', () => {
    const bad = compareIdentity(shell, 'http://127.0.0.1:47231', { pid: 9999 })
    expect(bad.map((m) => m.kind)).toEqual(['port', 'pid'])
    expect(bad[0].text).toContain('47231')
    expect(bad[0].text).toContain('47232')
  })

  it('端口对了但坐着别人的进程：单独一条 pid', () => {
    // 抢端口那一档（`freePort` 先 listen 再 close 的竞态）：地址没错，进程不是我的。
    const bad = compareIdentity(shell, 'http://127.0.0.1:47232', { pid: 9999 })
    expect(bad.map((m) => m.kind)).toEqual(['pid'])
    expect(bad[0].text).toContain('9999')
  })

  it('网页版没有壳：不吵', () => {
    expect(compareIdentity(null, 'http://localhost:5173', { pid: 1 })).toEqual([])
    expect(compareIdentity(undefined, 'http://localhost:5173', { pid: 1 })).toEqual([])
  })

  it('后端没报 pid（旧版 / 别人的服务）：那一格跳过，不当成不一样', () => {
    // **「不知道」不是「不一样」**（§21 判据宁可窄）。端口那一格照样核。
    expect(compareIdentity(shell, 'http://127.0.0.1:47232', {})).toEqual([])
    expect(compareIdentity(shell, 'http://127.0.0.1:47232', null)).toEqual([])
    expect(compareIdentity(shell, 'http://127.0.0.1:47231', null).map((m) => m.kind))
      .toEqual(['port'])
  })

  it('壳还没报出端口 / pid（启动那一瞬）：那一格也跳过', () => {
    expect(compareIdentity({ port: 0, pid: 0, dataDir: '' }, 'http://127.0.0.1:47231',
                           { pid: 9999 })).toEqual([])
  })

  it('开发时 vite 的 5173 不该被读成「连错了」', () => {
    // 开发模式下界面跑在 vite 上、`/api` 走代理，壳的 `backendInfo` 回 null
    // （那时窗口根本不是壳开的）——这一条钉的是「没有壳就没有这个概念」。
    expect(compareIdentity(null, 'http://localhost:5173', { pid: 8811 })).toEqual([])
  })
})
