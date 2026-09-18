/** P7（P4 #7 / #8）：记忆列表按光标段召回、已在正文里的折叠。 */
import { describe, expect, it } from 'vitest'

import { factInBody, recallQuery } from '../../util/recallContext'

const 笔记 = [
  '# 国际高中', '',
  '陈校从招生策略延伸到课程本土化，午餐会要谈师资协作。', '',
  '决策节奏需要收束。午餐会要把方向共识转化为可落地的闭环方案，并以6月末/7月销售上市窗口为验收边界。', '',
  '尾段讲 Memocad 前提和 Discord 讨论板块，Speaker A 说在 Discord 上建一个 MemoCad 的账号。',
].join('\n')

describe('recallQuery', () => {
  it('光标在一段上：查这段 + 前一段，不是末 500 字', () => {
    const q = recallQuery(笔记, '决策节奏需要收束。午餐会要把方向共识转化为可落地的闭环方案，并以6月末/7月销售上市窗口为验收边界。')
    expect(q.mode).toBe('cursor')
    expect(q.query).toContain('6月末/7月')
    expect(q.query).toContain('陈校从招生策略')       // 前一段
    expect(q.query).not.toContain('Discord')          // 不带末尾
  })
  it('前一段是标题就不带', () => {
    const q = recallQuery(笔记, '陈校从招生策略延伸到课程本土化，午餐会要谈师资协作。')
    expect(q.query.startsWith('陈校')).toBe(true)
  })
  it('光标不在正文里（空 / 标题 / 太短）→ 退回末 500 字', () => {
    expect(recallQuery(笔记, '').mode).toBe('tail')
    expect(recallQuery(笔记, '# 国际高中').mode).toBe('tail')
    expect(recallQuery(笔记, '短句').mode).toBe('tail')
    expect(recallQuery(笔记, '').query).toContain('Discord')
  })
  it('引用标记 / 图片从查询里剥掉', () => {
    const q = recallQuery('x\n\n这一段有引用 [terrence-12-AB] 和图 ![a](/api/assets/a.png) 够长了吧', '这一段有引用 [terrence-12-AB] 和图 ![a](/api/assets/a.png) 够长了吧')
    expect(q.query).not.toContain('terrence-12-AB')
    expect(q.query).not.toContain('assets')
  })
})

describe('factInBody', () => {
  it('正文逐字引过的原话 → 已在正文', () => {
    expect(factInBody('Speaker A 说在 Discord 上建一个 MemoCad 的账号', 笔记)).toBe(true)
  })
  it('标点 / 空格不同也认', () => {
    expect(factInBody('陈校从招生策略延伸到课程本土化 午餐会要谈师资协作', 笔记)).toBe(true)
  })
  it('多了几个字的近似原话（走双字重合那条路，不是子串）→ 已在正文', () => {
    // 跟第一段比：多出「和课程安排」，双字重合约 0.87——子串比对认不出，靠 IN_BODY_MIN_OVERLAP 那条
    expect(factInBody('陈校从招生策略延伸到课程本土化，午餐会要谈师资协作和课程安排。', 笔记)).toBe(true)
  })
  it('只是同一个话题、不是原话 → 不算', () => {
    expect(factInBody('Speaker B 说 应该在 6 月末或 7 月会在网站上开始销售产品', 笔记)).toBe(false)
    expect(factInBody('They have the AI in their DNA. They are obsessed by AI.', 笔记)).toBe(false)
  })
  it('太短的不判（避免「好的」这种撞上）', () => {
    expect(factInBody('午餐会', 笔记)).toBe(false)
  })
})
