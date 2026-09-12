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

describe('formatMarkdown 幂等', () => {
  it('格式化两次结果不变', () => {
    const src = '# 标题\n段落中文English混排。\n- 列表1\n- 列表2\n|a|b|\n|-|-|\n|1|2|\n```py\nx=1\n```\n> 引用\n**粗体：**后面'
    const once = formatMarkdown(src)
    expect(formatMarkdown(once)).toBe(once)
  })
})

import { stripCommonIndent } from '../format'
describe('stripCommonIndent', () => {
  it('整篇缩进 4 格的去掉公共缩进', () => {
    expect(stripCommonIndent('    # 标题\n\n    ## 二级\n        - 子项')).toBe('# 标题\n\n## 二级\n    - 子项')
  })
  it('有围栏或缩进不一致就不动', () => {
    expect(stripCommonIndent('    a\nb')).toBe('    a\nb')
    expect(stripCommonIndent('    ```\n    x\n    ```')).toBe('    ```\n    x\n    ```')
  })
  it('格式化整篇时生效', () => {
    expect(formatMarkdown('    ## 标题\n    正文')).toBe('## 标题\n\n正文\n')
  })
})
