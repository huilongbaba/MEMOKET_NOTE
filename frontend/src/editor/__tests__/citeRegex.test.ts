import { describe, expect, it } from 'vitest'
import { CITE_RE_SOURCE } from '../factCite'

describe('引用 id 的形状', () => {
  const re = () => new RegExp(CITE_RE_SOURCE, 'g')
  it('KITE 的 <用户>-<数字>-<hex> 和笔记摄入的 note-<12hex>-<块>F<n> 都认', () => {
    const ids = [...'据 [terrence-1872-5F8] 和 [note-f5e34e385aac-0F1] 所述'.matchAll(re())].map((m) => m[1])
    expect(ids).toEqual(['terrence-1872-5F8', 'note-f5e34e385aac-0F1'])
  })
  it('普通方括号 / 日期 / 不是 12 位 hex 的不算', () => {
    expect([...'[a-b-c] [2026-01-01] [note-xyz-0F1] [见附录]'.matchAll(re())]).toEqual([])
  })
})
