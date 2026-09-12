import { describe, expect, it } from 'vitest'
import { readingMinutes, wordCount } from '../../util/wordCount'

describe('wordCount', () => {
  it('不算空白、井号、引用标记、强调星号', () => {
    expect(wordCount('# 标题\n\n正文 **重点** 句 [terrence-12-AB]。\n- 一条')).toBe('标题正文重点句。一条'.length)
  })
  it('英文也按字符数（跟状态栏口径一致）', () => {
    expect(wordCount('hello world')).toBe(10)
  })
  it('表格分隔行不算字', () => {
    const t = '| a | b |\n|---|:---:|\n| 1 | 2 |'
    expect(wordCount(t)).toBe(4)
    expect(wordCount('| a | b |\n|------|------------|\n| 1 | 2 |')).toBe(4)
  })
  it('阅读时间至少 1 分钟', () => {
    expect(readingMinutes(0)).toBe(1)
    expect(readingMinutes(4000)).toBe(10)
  })
})
