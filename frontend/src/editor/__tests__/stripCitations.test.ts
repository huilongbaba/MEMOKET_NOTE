import { describe, expect, it } from 'vitest'
import { stripCitations, stripForRecall, wordCount } from '../../util/wordCount'

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

describe('召回前剥掉图片和链接地址', () => {
  it('整条图片去掉、链接只留文字', () => {
    expect(stripForRecall('![probe](/api/assets/52dd.png)').trim()).toBe('')
    expect(stripForRecall('见 [年报](https://x.com/assets/a.pdf) 第 3 页 [terrence-1-A1]').trim()).toBe('见 年报 第 3 页')
  })
})
