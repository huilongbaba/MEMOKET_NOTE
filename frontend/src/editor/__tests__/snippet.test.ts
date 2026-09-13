import { describe, expect, it } from 'vitest'
import { matchSnippet } from '../../util/snippet'

describe('搜索摘要', () => {
  it('前面留得短，命中不会被一行省略号吃掉', () => {
    const content = '# 标题\n\n' + '前面很长很长的一段废话'.repeat(5) + '4月16日EVT准备4台主机' + '后面的内容'.repeat(5)
    const s = matchSnippet(content, 'EVT', 40, 8)!
    expect(s.hit).toBe('EVT')
    expect(s.before.replace(/^…/, '').length).toBeLessThanOrEqual(8)
    expect(s.after.length).toBeGreaterThan(20)
  })
  it('没命中给 null，井号和列表符不进摘要', () => {
    expect(matchSnippet('# 标题\n- 一条', 'zzz')).toBeNull()
    expect(matchSnippet('# 标题 EVT', 'evt')!.before).toBe('标题 ')
  })
})
