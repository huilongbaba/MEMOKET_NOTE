import { describe, expect, it } from 'vitest'
import { insertStreamed, applyScrub, prepareInsert } from '../streamJoin'

describe('insertStreamed', () => {
  it('增量里三个以上换行压成段落分隔', () => {
    const r = insertStreamed('前文。\n\n', 5, '确认。\n\n\n\n还要把')
    expect(r.next).toBe('前文。\n\n确认。\n\n还要把')
    expect(r.cursor).toBe(r.next.length)
  })
  it('跨块拆开的换行也压：上一块结尾两个、这一块开头两个', () => {
    let s = '前文。\n\n'; let cur: number | null = s.length
    for (const chunk of ['一段\n\n', '\n\n二段']) { const r = insertStreamed(s, cur, chunk); s = r.next; cur = r.cursor }
    expect(s).toBe('前文。\n\n一段\n\n二段')
  })
  it('没有多余换行的原样插入，游标停在增量末尾', () => {
    const r = insertStreamed('abc', 1, 'XY')
    expect(r.next).toBe('aXYbc')
    expect(r.cursor).toBe(3)
  })
  it('游标为空 / 越界就追加到末尾', () => {
    expect(insertStreamed('abc', null, 'd').next).toBe('abcd')
    expect(insertStreamed('abc', 99, 'd').next).toBe('abcd')
  })
  it('只动接缝附近：正文别处的连续空行不碰', () => {
    const r = insertStreamed('x\n\n\n\ny', 6, 'z')
    expect(r.next).toBe('x\n\n\n\nyz')
  })
})

import { tidyBlankLines } from '../streamJoin'

describe('tidyBlankLines（照抄后端）', () => {
  it('三个空行压成一个，行尾空白剥掉', () => {
    expect(tidyBlankLines('a  \n\n\n\nb')).toBe('a\n\nb')
  })
  it('代码块里的空行和空白原样', () => {
    const s = 'x\n```\nline  \n\n\n\nend\n```\ny'
    expect(tidyBlankLines(s)).toBe(s)
  })
  it('没有多余空行的不动', () => {
    expect(tidyBlankLines('a\n\nb\nc')).toBe('a\n\nb\nc')
  })
})

describe('applyScrub（照服务端 scrub_meta_sentences_v）', () => {
  it('删那句，同段其它句子首尾空格一起吃掉，整篇 trim', () => {
    const c = '前言。\n\nDVT 节点调整。 [t-1-A] 这一步不能据此判断已经完成。 后面继续。\n\n# 标题\n\n尾巴。\n'
    // 服务端按「。！？」切句，引用 id 跟在上一句句号后面就归到下一句里——发来的句子是「[t-1-A] 这一步…」
    expect(applyScrub(c, '[t-1-A] 这一步不能据此判断已经完成。')).toBe('前言。\n\nDVT 节点调整。后面继续。\n\n# 标题\n\n尾巴。')
    // 对不上整句（只是子串）就不动
    expect(applyScrub(c, '这一步不能据此判断已经完成。')).toBe(c)
  })
  it('找不到那句 / 在表格代码块里就原样', () => {
    expect(applyScrub('a。 b。', '没有')).toBe('a。 b。')
    expect(applyScrub('| x | 不能据此。 |', '不能据此。')).toBe('| x | 不能据此。 |')
  })
})

describe('prepareInsert（照服务端 outline.insert_into）', () => {
  it('前后各收成一个空行；文末预留的空行先收回；紧跟插入点的孤立标点去掉', () => {
    expect(prepareInsert('## A\n正文。\n\n\n## B\n乙\n\n\n', 9)).toEqual({ next: '## A\n正文。\n\n\n\n## B\n乙\n', cursor: 10 })
    expect(prepareInsert('甲。，后半句', 2)).toEqual({ next: '甲。\n\n\n\n后半句', cursor: 4 })
  })
})
