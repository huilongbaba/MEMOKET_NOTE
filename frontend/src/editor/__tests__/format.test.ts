import { describe, expect, it } from 'vitest'
import { fixBoldPunct, formatMarkdown } from '../format'

describe('fixBoldPunct', () => {
  it('把粗体里的标点挪到外面', () => {
    expect(fixBoldPunct('**依赖链：**容量确认')).toBe('**依赖链**：容量确认')
    expect(fixBoldPunct('- **提出变更的人**：记录')).toBe('- **提出变更的人**：记录')
  })
  it('格式化整篇时生效，代码块不动', () => {
    const out = formatMarkdown('**依赖链：**容量\n\n```\n**a：**\n```\n')
    expect(out).toContain('**依赖链**：容量')
    expect(out).toContain('**a：**')
  })
})
