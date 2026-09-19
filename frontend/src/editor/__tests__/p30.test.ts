/**
 * P30 #1：把「引用」那一格换成有意义的指标。
 *
 * 前端这一侧只有一件事要守住，但它是这个换法成不成立的全部：
 * **「没有出处可引」和「有出处、一句都没贴」不许混成同一句话。**
 * 旧那格（「这次跑写进终稿的引用处数」）坏就坏在这两件事在它那儿都是 0。
 */
import { describe, expect, it } from 'vitest'

import { citeCoverLine } from '../../components/AgentActivity'

describe('引用覆盖那一行（P30 #1）', () => {
  it('分母 0 说的是「没有出处可引」，不是 0%', () => {
    // `a941efecd390` 那篇（整篇英文、材料跟正文零逐字重合）四批里三批是这一档
    expect(citeCoverLine(0, 0, 0)).toBe('这次写的内容在材料里找不到逐字出处，所以没有可直接引的编号')
    // 措辞里不许出现任何一个能被读成「比例」的东西
    expect(citeCoverLine(0, 0, 0)).not.toMatch(/%|0 句|比例/)
  })

  it('有出处、一句都没贴，是另一句话', () => {
    expect(citeCoverLine(8, 0, 0)).toBe('有出处可引的 8 句里贴了 0 句，一句都没贴')
  })

  it('贴了和贴对了分开说', () => {
    expect(citeCoverLine(8, 3, 1)).toBe('有出处可引的 8 句里贴了 3 句，其中 1 句贴的编号对得上、2 句对不上')
    // 全贴对就不啰嗦
    expect(citeCoverLine(8, 3, 3)).toBe('有出处可引的 8 句里贴了 3 句')
  })

  it('两句话真的不一样——同一个 0 在两边读出来的东西相反', () => {
    expect(citeCoverLine(0, 0, 0)).not.toBe(citeCoverLine(8, 0, 0))
  })
})
