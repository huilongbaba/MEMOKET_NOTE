import { describe, expect, it } from 'vitest'
import { sectionEnd } from '../../util/sectionEnd'

const doc = '# 复盘\n\n## 时间线\n\n### APP\n\nAPP 正文。\n\n### 硬件\n\n硬件正文。\n\n## 团队\n\n团队正文。\n'

describe('sectionEnd（跟后端 outline.section_end 同一条规则）', () => {
  it('取到下一个不深于它的标题之前', () => {
    expect(sectionEnd(doc, '硬件')).toBe(doc.indexOf('## 团队'))
    expect(sectionEnd(doc, '时间线')).toBe(doc.indexOf('## 团队'))
    expect(sectionEnd(doc, '团队')).toBe(doc.length)
    expect(sectionEnd(doc, '不存在')).toBeNull()
  })
  it('围栏代码块里的 # 不算标题', () => {
    const d = '## 甲\n\n```sh\n# 注释\n```\n\n## 乙\n'
    expect(sectionEnd(d, '甲')).toBe(d.indexOf('## 乙'))
    expect(sectionEnd(d, '注释')).toBeNull()
  })
})
