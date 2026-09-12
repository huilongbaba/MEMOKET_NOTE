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

it('图片不算字数、链接只算显示文字', () => {
  const img = '![' + '为一篇公司汇报制作一张插图'.repeat(50) + '](/api/assets/abc.png)'
  expect(wordCount('正文十个字正文十个字' + img)).toBe(10)
  expect(wordCount('看[官网](https://example.com/very/long/path)')).toBe(3)
})
