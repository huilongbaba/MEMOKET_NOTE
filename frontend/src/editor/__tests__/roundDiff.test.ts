/**
 * 一轮改动的 diff 和它切出来的 hunk。
 *
 * 这是前端**第一批**测试。挑这里开头不是因为它最容易，是因为它最要紧：
 * 用户在面板上点「接受」和「撤回」，作用的就是 toHunks() 算出来的东西。
 * 一个 hunk 的 `del` 算错，撤回还原的就是错的文字——而这在界面上看起来
 * 一切正常。
 *
 * 这两个函数是纯的（只用到 @codemirror/state 里的类型，不碰 DOM），所以
 * 不需要 jsdom。
 */
import { describe, expect, it } from 'vitest'

import { diffParts, toHunks } from '../roundDiff'

describe('diffParts', () => {
  it('没改动时整段都是 keep', () => {
    expect(diffParts('一样的文字', '一样的文字'))
      .toEqual([{ type: 'keep', text: '一样的文字' }])
  })

  it('中文按单字切，只标出真正动了的那个字', () => {
    // 按整句切的话，改一个字整段都会标红标绿，看不出动了哪里
    const parts = diffParts('四月中旬交付', '三月中旬交付')
    expect(parts.filter((p) => p.type === 'del').map((p) => p.text)).toEqual(['四'])
    expect(parts.filter((p) => p.type === 'ins').map((p) => p.text)).toEqual(['三'])
    expect(parts.map((p) => p.text).join('')).toContain('月中旬交付')
  })

  it('英文按词切', () => {
    const parts = diffParts('ship in April', 'ship in March')
    expect(parts.find((p) => p.type === 'del')?.text).toBe('April')
    expect(parts.find((p) => p.type === 'ins')?.text).toBe('March')
  })

  it('纯新增时旧文字一个字都不该被标成删除', () => {
    const parts = diffParts('原来的话。', '原来的话。又加了一句。')
    expect(parts.some((p) => p.type === 'del')).toBe(false)
    expect(parts.find((p) => p.type === 'ins')?.text).toBe('又加了一句。')
  })

  it('改动太大时整段标删+增而不是逐词比', () => {
    // 真实场景里这意味着这一轮几乎重写了全文，逐词对比没有阅读价值，
    // 还会卡住 UI
    const before = '甲'.repeat(700)
    const after = '乙'.repeat(700)
    const parts = diffParts(before, after)
    expect(parts).toEqual([{ type: 'del', text: before },
                           { type: 'ins', text: after }])
  })

  it('拼回去要能还原两边', () => {
    const before = '第一批 200 台机器发出去两周，退货率 6%。'
    const after = '第一批 200 台机器发出去三周，退货率 8%。'
    const parts = diffParts(before, after)
    const old = parts.filter((p) => p.type !== 'ins').map((p) => p.text).join('')
    const now = parts.filter((p) => p.type !== 'del').map((p) => p.text).join('')
    expect(old).toBe(before)
    expect(now).toBe(after)
  })
})

describe('toHunks', () => {
  it('没有改动就没有 hunk', () => {
    expect(toHunks(null)).toEqual([])
    expect(toHunks([{ type: 'keep', text: '不变' }])).toEqual([])
  })

  it('相邻的删+增合成一处，因为那是一次替换', () => {
    // 拆成两处的话，点了接受还剩半截删除线挂在那儿
    const hunks = toHunks(diffParts('交付在四月', '交付在三月'))
    expect(hunks).toHaveLength(1)
    expect(hunks[0].del).toBe('四')
  })

  it('隔得近的两处合并，且 del 带上中间没动过的字', () => {
    // 中文逐字 diff 的代价：「四月中旬」→「三月上旬」会切成两处、各盖一个
    // 字，悬停粒度太碎。合并后 del 必须带上中间那段，撤回才能精确还原。
    const hunks = toHunks(diffParts('四月中旬', '三月上旬'))
    expect(hunks).toHaveLength(1)
    expect(hunks[0].del).toBe('四月中')
  })

  it('隔得远的两处不合并', () => {
    const before = '开头改这里。' + '中间隔着很长一段完全没有动过的文字。'.repeat(3) + '结尾也改。'
    const after = '开头改那里。' + '中间隔着很长一段完全没有动过的文字。'.repeat(3) + '结尾也变。'
    expect(toHunks(diffParts(before, after)).length).toBeGreaterThan(1)
  })

  it('每个 hunk 的区间落在新文本上，且 id 唯一', () => {
    const after = '交付在三月，价格改成 199。'
    const hunks = toHunks(diffParts('交付在四月，价格改成 179。', after))
    expect(new Set(hunks.map((h) => h.id)).size).toBe(hunks.length)
    for (const h of hunks) {
      expect(h.from).toBeGreaterThanOrEqual(0)
      expect(h.to).toBeLessThanOrEqual(after.length)
      expect(h.from).toBeLessThanOrEqual(h.to)
    }
  })
})

import { diffParts as _dp } from '../roundDiff'
describe('只差空白不算改动', () => {
  it('补空格 / 空行的位置不标绿', () => {
    const parts = _dp('中文English混排。\n段落', '中文 English 混排。\n\n段落')
    expect(parts.every((p) => p.type === 'keep')).toBe(true)
    const real = _dp('甲乙丙', '甲丁丙')
    expect(real.some((p) => p.type === 'ins')).toBe(true)
  })
})

describe('大文档按行再逐词', () => {
  it('八千字只补空格：几乎没有绿', () => {
    const lines = Array.from({ length: 400 }, (_, i) => `第${i}段：中文English混排，讨论了排期和样机${i}。`)
    const before = lines.join('\n')
    const after = lines.map((l) => l.replace('中文English混排', '中文 English 混排')).join('\n')
    const parts = _dp(before, after)
    const changed = parts.filter((p) => p.type !== 'keep').map((p) => p.text).join('')
    expect(changed.trim()).toBe('')
  })
  it('八千字里真改了一个词：只标那个词', () => {
    const lines = Array.from({ length: 400 }, (_, i) => `第${i}段：中文English混排，讨论了排期和样机${i}。`)
    const before = lines.join('\n')
    const after = lines.map((l, i) => (i === 123 ? l.replace('排期', '预算') : l)).join('\n')
    const parts = _dp(before, after)
    expect(parts.filter((p) => p.type === 'ins').map((p) => p.text)).toEqual(['预算'])
    expect(parts.filter((p) => p.type === 'del').map((p) => p.text)).toEqual(['排期'])
  })
})
