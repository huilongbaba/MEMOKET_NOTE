import { describe, expect, it } from 'vitest'
import { matchSnippet } from '../../util/snippet'

describe('matchSnippet', () => {
  it('命中处前后各截一段，保留原大小写', () => {
    const s = matchSnippet('a'.repeat(50) + ' Startup 回顾 ' + 'b'.repeat(50), 'startup', 10)
    expect(s).not.toBeNull()
    expect(s!.hit).toBe('Startup')
    expect(s!.before.startsWith('…')).toBe(true)
    expect(s!.after.endsWith('…')).toBe(true)
    expect(s!.before.length).toBe(11)
  })
  it('换行折成空格，开头命中不加省略号', () => {
    const s = matchSnippet('创业\n一年', '创业', 5)
    expect(s).toEqual({ before: '', hit: '创业', after: ' 一年' })
  })
  it('去掉标题井号和列表符号', () => {
    expect(matchSnippet('# 创业一年\n- 第一条', '创业')).toEqual({ before: '', hit: '创业', after: '一年 第一条' })
  })
  it('没命中 / 空查询给 null', () => {
    expect(matchSnippet('abc', 'z')).toBeNull()
    expect(matchSnippet('abc', '  ')).toBeNull()
  })
})
