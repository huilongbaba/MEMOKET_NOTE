import { describe, expect, it } from 'vitest'

import { frontmatterEnd } from '../frontmatter'

/**
 * 判据必须**严**：判错了就会把正文第一段当成元数据压暗。
 * 所以每条都写成「这一篇该不该算」。
 */
describe('front-matter 判定', () => {
  it('幻灯片笔记开头那一段算（实拍来源）', () => {
    expect(frontmatterEnd('---\nmarp: true\nslides: true\n---\n\n# 创业一年回顾')).toBe(4)
  })

  it('空的 front-matter 也算', () => {
    expect(frontmatterEnd('---\n---\n正文')).toBe(2)
  })

  it('第一行不是 --- 就不算', () => {
    expect(frontmatterEnd('# 标题\n\n---\nmarp: true\n---')).toBe(0)
  })

  it('**没有闭合的 --- 不算**——否则整篇都会被压暗', () => {
    expect(frontmatterEnd('---\nmarp: true\n\n# 正文\n\n后面再也没有横线')).toBe(0)
  })

  it('中间夹着正常句子就不算——那是一条分隔线加一段正文', () => {
    expect(frontmatterEnd('---\n这是一句正常的话，不是 key: value\n---')).toBe(0)
  })

  it('列表项和缩进续行算 YAML 的一部分', () => {
    expect(frontmatterEnd('---\ntags:\n  - a\n  - b\n---\n正文')).toBe(5)
  })

  it('超长的不算（front-matter 不该有 30 行以上）', () => {
    const long = '---\n' + Array.from({ length: 40 }, (_, i) => `k${i}: v`).join('\n') + '\n---'
    expect(frontmatterEnd(long)).toBe(0)
  })

  it('空文档 / 普通文档不算', () => {
    expect(frontmatterEnd('')).toBe(0)
    expect(frontmatterEnd('就是一段普通的话。')).toBe(0)
  })
})
