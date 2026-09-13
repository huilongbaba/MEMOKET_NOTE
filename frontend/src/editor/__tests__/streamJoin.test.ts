import { describe, expect, it } from 'vitest'
import { insertStreamed } from '../streamJoin'

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
