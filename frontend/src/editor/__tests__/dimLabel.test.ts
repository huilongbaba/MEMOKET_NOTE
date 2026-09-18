import { describe, expect, it } from 'vitest'
import { dimLabel } from '../dimLabel'

describe('dimLabel', () => {
  it('写死的那几维有中文名', () => {
    expect(dimLabel('non_repetition')).toBe('不重复')
    expect(dimLabel('follows_prompt')).toBe('照你的指令做')
  })

  it('现场生成的那几条不许露出 checklist_1 这种字样', () => {
    // 后端 `harness/checklist.py` 按 `checklist_<n>` 命名（维度名是打分器要
    // 逐字复现的 JSON 键，中文长句当键太容易被改写）——好看的名字在这一层加。
    expect(dimLabel('checklist_1')).toBe('你的要求 1')
    expect(dimLabel('checklist_12')).toBe('你的要求 12')
  })

  it('判据的兜底桶有自己的名字，不许借用 coherence', () => {
    // 计划 4.4：`mechanics` 不是评分维度，是「代码判据抓到了一个机械缺陷」。
    // 借 `coherence` 当兜底的后果是界面上说「连贯自洽 0 分」，而那一轮
    // 打分器一次都没跑过。
    expect(dimLabel('mechanics')).toBe('机械缺陷')
  })

  it('不认识的维度原样显示，不是空白', () => {
    expect(dimLabel('future_dimension')).toBe('future_dimension')
  })
})
