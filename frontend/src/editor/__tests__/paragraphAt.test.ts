import { describe, expect, it } from 'vitest'
import { Text } from '@codemirror/state'
import { paragraphAt } from '../../components/MarkdownEditor'

describe('paragraphAt', () => {
  const doc = Text.of(['# 标题', '', '第一段第一行', '第一段第二行', '', '第二段', ''])
  it('光标在段内：整段（空行之间）', () => {
    expect(paragraphAt(doc, doc.line(3).from + 2)).toBe('第一段第一行\n第一段第二行')
  })
  it('标题单独算一段；空行给空串', () => {
    expect(paragraphAt(doc, 1)).toBe('# 标题')
    expect(paragraphAt(doc, doc.line(2).from)).toBe('')
  })
})
