import { describe, expect, it } from 'vitest'
import { stripCitations, wordCount } from '../../util/wordCount'

describe('引用标记不算字数、不撑门槛', () => {
  it('去掉 [user-n-hex]', () => {
    expect(stripCitations('据 [terrence-1872-5F8] 所述。').trim()).toBe('据 所述。')
    expect(stripCitations('据 [note-5f65df10cad6-0A1] 所述').trim()).toBe('据 所述')
    expect(wordCount('据 [terrence-1872-5F8] 所述。')).toBe(4)
  })
  it('普通中括号不动', () => {
    expect(stripCitations('[待定] 方案')).toBe('[待定] 方案')
  })
})
