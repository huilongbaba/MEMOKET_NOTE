import { describe, expect, it } from 'vitest'
import { minimalChange } from '../minimalChange'

function apply(s: string, c: { from: number; to: number; insert: string } | null) {
  return c ? s.slice(0, c.from) + c.insert + s.slice(c.to) : s
}

describe('minimalChange', () => {
  it('追加只改末尾', () => {
    const c = minimalChange('甲\n\n乙', '甲\n\n乙丙')
    expect(c).toEqual({ from: 4, to: 4, insert: '丙' })
  })
  it('中间插入只改中间', () => {
    const c = minimalChange('甲\n\n丙', '甲\n\n乙\n\n丙')!
    expect(c.from).toBe(3)
    expect(apply('甲\n\n丙', c)).toBe('甲\n\n乙\n\n丙')
  })
  it('替换 / 删除 / 相同', () => {
    expect(apply('abcXYZdef', minimalChange('abcXYZdef', 'abc12def'))).toBe('abc12def')
    expect(apply('abcXYZdef', minimalChange('abcXYZdef', 'abcdef'))).toBe('abcdef')
    expect(minimalChange('same', 'same')).toBeNull()
  })
  it('不把 emoji 的代理对切开', () => {
    const old = 'a😀b'; const next = 'a😁b'
    const c = minimalChange(old, next)!
    expect(apply(old, c)).toBe(next)
    expect(c.from).toBe(1)
  })
})
