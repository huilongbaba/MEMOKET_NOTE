import { describe, expect, it } from 'vitest'

import { parseInline, parseMini } from '../../util/miniMarkdown'

describe('日报那一小块 markdown', () => {
  it('认小标题、列表、段落', () => {
    const b = parseMini('## 推进了什么\n\n- 改了 a.py\n- 改了 b.py\n\n就这些。')
    expect(b.map((x) => x.kind)).toEqual(['h', 'ul', 'p'])
    expect(b[1].kind === 'ul' && b[1].items).toHaveLength(2)
  })

  it('连着的列表项并进同一个 ul，隔开的另起一个', () => {
    const b = parseMini('- a\n- b\n\n## 卡在哪\n\n- c')
    expect(b.map((x) => x.kind)).toEqual(['ul', 'h', 'ul'])
  })

  it('粗体和行内代码切得出来，两边的普通文字不丢', () => {
    expect(parseInline('**Code** 花了 `4 小时`，剩下的')).toEqual([
      { t: 'b', s: 'Code' },
      { t: 'text', s: ' 花了 ' },
      { t: 'code', s: '4 小时' },
      { t: 'text', s: '，剩下的' },
    ])
  })

  it('没有标记的一行原样就是一段文字', () => {
    expect(parseInline('今天没什么特别的')).toEqual([{ t: 'text', s: '今天没什么特别的' }])
  })

  it('中文段落的软换行不补空格，英文之间补', () => {
    const [zh] = parseMini('第一行\n第二行')
    expect(zh.kind === 'p' && zh.parts[0].s).toBe('第一行第二行')
    const [en] = parseMini('first line\nsecond line')
    expect(en.kind === 'p' && en.parts[0].s).toBe('first line second line')
  })

  it('空正文不炸', () => {
    expect(parseMini('')).toEqual([])
  })
})
