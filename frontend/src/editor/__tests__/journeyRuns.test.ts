import { describe, expect, it } from 'vitest'

import { groupRuns, RUN_SIM, similar } from '../../util/journeyRuns'

/** 时间轴上「连着说同一件事」的段并成一块——判据是在**真实产出**上量出来的
 *  （第 752 轮）：真的同一件事的相邻对 .60 / .58 / .52 / .40 / .32，
 *  真换了事的 .07 / .06。门槛 .45 靠上取，误伤比漏报贵。 */

const at = (m: number) => new Date(Date.parse('2026-09-17T07:00:00Z') + m * 60_000).toISOString()
const seg = (m0: number, m1: number, app: string, desc: string) =>
  ({ start: at(m0), end: at(m1), app, desc })

describe('similar', () => {
  it('同一件事的两种说法给高分，两件事给低分', () => {
    const a = '查看「查看Firebase用户行为数据」标签页中 PRD.md#70-81 的日本 Android 崩溃分析'
    const b = '阅读 查看Firebase用户行为数据 页签中 PRD.md#70-81 的日本 Android 崩溃分析结论'
    const c = '改需求文档中 [项目名称] 的 #1.背景与问题 模板并查看右侧记忆卡片'
    expect(similar(a, b)).toBeGreaterThan(RUN_SIM)
    expect(similar(a, c)).toBeLessThan(0.15)
  })

  it('空串不给分，别让两条空描述靠 similar 并到一起', () => {
    expect(similar('', '什么东西')).toBe(0)
  })
})

describe('groupRuns', () => {
  it('连着说同一件事的并成一块，块的时间范围是首尾', () => {
    const runs = groupRuns([
      seg(0, 5, 'Code', '查看 PRD.md#70-81 的日本 Android 崩溃分析'),
      seg(5, 11, 'Code', '阅读 PRD.md#70-81 的日本 Android 崩溃分析结论'),
      seg(11, 20, 'Code', '查看 PRD.md#70-81 的日本 Android 崩溃信息'),
    ])
    expect(runs).toHaveLength(1)
    expect(runs[0].segs).toHaveLength(3)
    expect(runs[0].start).toBe(at(0))
    expect(runs[0].end).toBe(at(20))
  })

  it('换了件事就断开', () => {
    const runs = groupRuns([
      seg(0, 5, 'Code', '查看 PRD.md#70-81 的日本 Android 崩溃分析'),
      seg(5, 9, 'Code', '改需求文档中 [项目名称] 的背景与问题模板'),
    ])
    expect(runs).toHaveLength(2)
  })

  it('换了应用就断开，哪怕描述像', () => {
    const d = '查看 PRD.md#70-81 的日本 Android 崩溃分析'
    expect(groupRuns([seg(0, 5, 'Code', d), seg(5, 9, 'Safari', d)])).toHaveLength(2)
  })

  it('中间隔了很久不并——那段空白本身是信息', () => {
    const d = '查看 PRD.md#70-81 的日本 Android 崩溃分析'
    expect(groupRuns([seg(0, 5, 'Code', d), seg(120, 125, 'Code', d)])).toHaveLength(2)
  })

  it('跟块首比不跟上一条比：一条一条传下去会飘', () => {
    // b 像 a、c 像 b，但 c 跟 a 已经是两件事。按「跟上一条比」会把三条并成一块。
    const a = '查看 PRD.md 的日本 Android 崩溃分析'
    const b = '查看 PRD.md 的日本 Android 崩溃分析，打开 Crashlytics 按机型筛选导出 CSV'
    const c = '打开 Crashlytics 按机型筛选导出 CSV 并写进周报'
    expect(similar(a, b)).toBeGreaterThan(RUN_SIM)
    expect(similar(b, c)).toBeGreaterThan(RUN_SIM)
    expect(similar(a, c)).toBeLessThan(RUN_SIM)
    const runs = groupRuns([seg(0, 5, 'Code', a), seg(5, 9, 'Code', b), seg(9, 14, 'Code', c)])
    expect(runs).toHaveLength(2)
    expect(runs[0].segs).toHaveLength(2)
  })

  it('两条都还没描述就并——那两行长得一模一样', () => {
    const runs = groupRuns([seg(0, 5, 'Code', ''), seg(5, 9, 'Code', ''), seg(9, 14, 'Code', '')])
    expect(runs).toHaveLength(1)
  })

  it('一条有描述一条没有，不并——没描述的那条还等着被描述', () => {
    const runs = groupRuns([seg(0, 5, 'Code', '查看 PRD.md 的崩溃分析'), seg(5, 9, 'Code', '')])
    expect(runs).toHaveLength(2)
  })

  it('块上显示信息最多的那一句', () => {
    const runs = groupRuns([
      seg(0, 5, 'Code', '查看 PRD.md 的崩溃分析'),
      seg(5, 9, 'Code', '查看 PRD.md#70-81 的崩溃分析，Crashlytics 匹配到 4 条'),
    ])
    expect(runs[0].desc).toContain('Crashlytics')
  })

  it('空数组不炸', () => {
    expect(groupRuns([])).toEqual([])
  })
})
