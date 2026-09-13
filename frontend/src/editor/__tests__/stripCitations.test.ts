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

import { citationRanges } from '../../util/wordCount'

describe('citationRanges', () => {
  it('只圈指定 id 的引用，连同前面那个空格', () => {
    const t = '据 [u-1-A] 和 [u-2-B] 所述。再看 [u-1-A]。'
    const r = citationRanges(t, ['u-1-A'])
    expect(r.map(({ from, to }) => t.slice(from, to))).toEqual([' [u-1-A]', ' [u-1-A]'])
    expect(r[0].from).toBeLessThan(r[1].from)
  })
  it('不在名单里的不动；开头没有空格也能删', () => {
    const t = '[u-9-F]开头 [u-2-B] 尾'     // 末段是十六进制，Z 不算引用
    expect(citationRanges(t, ['u-9-F']).map(({ from, to }) => t.slice(from, to))).toEqual(['[u-9-F]'])
    expect(citationRanges(t, ['nope'])).toEqual([])
  })
})
