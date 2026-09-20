// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import {
  JOURNEY_TICK_SEC, OVERLONG_DAY_EXCESS_SEC, OVERLONG_MIN_EXCESS_SEC, OVERLONG_RATIO,
  overlongExcess, saySpan,
} from '../../components/JourneyPage'

/**
 * P62（第 778 轮）：**「合计 20 小时 42 分钟」那句提示**（P52 遗留 ③，P58 / P59 / P60 三批挂着没做）。
 *
 * 做了。但**判的不是「这是旧版本采的」**——段里根本没有版本 / 写入方标记
 * （盘上的键就那十个，一个版本字段都没有），所以「旧版本」这件事**不可知**。
 * 判的是**段内自相矛盾**：这一段跨了多久 vs 它采到几个样本。
 *
 * 为什么这个判据成立，在源码里是钉死的（`desktop/src/capture.ts` 的 tick 循环）：
 *
 *     } else {
 *       cur.end = now
 *       cur.n += 1
 *     }
 *
 * 睡眠 / 锁屏醒来的那一下走的正是这一支：**`end` 跳几个小时，`n` 只涨 1**。
 * 所以「时长 ≫ n × 采样周期」当场量得出来，跟哪一版采的无关。
 *
 * **日级比值没用，必须逐段看**：整天大部分 `n` 是真在 tick，
 * 被吞掉的空白只压在少数几段上，日级一平均就看不见了。⑤ 钉的就是这件事。
 *
 * 判据宁可窄：倍数**和**绝对时长两头都要够，一天合计还得多出半小时才说话。
 */

const TICK = JOURNEY_TICK_SEC
/** 造一段：跨 `durSec` 秒，采到 `n` 个样本。 */
const seg = (durSec: number, n: number, startMs = 0) => ({
  start: new Date(startMs).toISOString(),
  end: new Date(startMs + durSec * 1000).toISOString(),
  n,
})
/** 健康的一段：时长正好等于 n 个采样周期。 */
const healthy = (n: number, startMs = 0) => seg(n * TICK, n, startMs)

describe('P62 · 合计偏长：判的是段内自相矛盾，不是版本', () => {
  it('① 健康的一天（每段时长 = n × 采样周期）一个字都不说', () => {
    const day = [healthy(240), healthy(120, 9e6), healthy(21, 2e7)]
    expect(overlongExcess(day)).toEqual({ segs: 0, excess: 0 })
  })

  it('② 被吞掉空白的那一段挑得出来：跨 3 小时、只采到 21 个样本', () => {
    // 实拍那一类：`end` 跳了 3 小时，`n` 只涨了 1
    const bad = seg(185 * 60, 21)
    const { segs, excess } = overlongExcess([bad])
    expect(segs).toBe(1)
    expect(excess).toBe(185 * 60 - 21 * TICK)      // 11100 - 315 = 10785 秒
    expect(saySpan(excess)).toBe('3 小时')          // 10785 秒 ≈ 180 分钟
  })

  it('③ 门槛两头都要够 —— 只差一点的不算（判据宁可窄）', () => {
    // 倍数够（3 倍）但绝对量不够（只多出 300 秒 < 600）
    expect(overlongExcess([seg(450, 10)])).toEqual({ segs: 0, excess: 0 })
    // 绝对量够（多出 900 秒）但倍数不够（1.6 倍 < 2）
    expect(overlongExcess([seg(2400, 100)])).toEqual({ segs: 0, excess: 0 })
    // 两头都够
    const both = overlongExcess([seg(3600, 60)])   // 3600 vs 900：4 倍、多 2700 秒
    expect(both).toEqual({ segs: 1, excess: 2700 })
  })

  it('④ 常数没被悄悄放宽', () => {
    expect(OVERLONG_MIN_EXCESS_SEC).toBe(600)
    expect(OVERLONG_DAY_EXCESS_SEC).toBe(1800)
    expect(OVERLONG_RATIO).toBe(2)
    expect(JOURNEY_TICK_SEC).toBe(15)
  })

  it('⑤ 日级比值救不了这件事 —— 所以判据必须逐段（这是这个设计的理由）', () => {
    // 一整天真在 tick（18 小时的样本）+ 两段各吞掉 1 小时空白。
    // 日级：合计 20 小时 vs 采样 18 小时 = 1.11 倍，**够不着任何合理的日级门槛**。
    const day = [
      ...Array.from({ length: 8 }, (_, i) => healthy(540, i * 9e6)),   // 8 × 2h15 = 18h
      seg(3600 + 15, 1, 1e8), seg(3600 + 15, 1, 2e8),                  // 两段各吞 1 小时
    ]
    const total = day.reduce((a, s) =>
      a + (Date.parse(s.end) - Date.parse(s.start)) / 1000, 0)
    const sampled = day.reduce((a, s) => a + s.n * TICK, 0)
    expect(total / sampled).toBeLessThan(1.15)        // 日级比值：看不见
    // 逐段：两段都挑得出来，合计多出 2 小时，过得了日级门槛
    const got = overlongExcess(day)
    expect(got.segs).toBe(2)
    expect(got.excess).toBe(7200)
    expect(got.excess).toBeGreaterThanOrEqual(OVERLONG_DAY_EXCESS_SEC)
  })

  it('⑥ 空的一天 / 没有 n 的老段不许炸', () => {
    expect(overlongExcess([])).toEqual({ segs: 0, excess: 0 })
    // n 缺失（老后端）时当 0 算：一段跨 1 小时、一个样本都没有 → 确实该挑出来
    expect(overlongExcess([{ ...seg(3600, 0) }])).toEqual({ segs: 1, excess: 3600 })
    // 负数 n 不许把 excess 算大
    expect(overlongExcess([{ ...seg(3600, -99) }])).toEqual({ segs: 1, excess: 3600 })
  })
})
