import { describe, expect, it } from 'vitest'

import { NEUTRAL_ENTITY_ICON, entityIcon } from '../../util/entityIcon'

/** 实拍（第 658 轮）：实体页上 Facebook / Canada / iphone / Russia / Apple Watch
 *  全都戴着 `bx-user`。**图标是一句断言**，而全库 1239 个实体的 etype 一个都没有值。 */
describe('不知道类型就别用人形图标', () => {
  it('不认识的一律中性，不说它是人', () => {
    for (const n of ['Facebook', 'Canada', 'iphone', 'Russia', 'Apple Watch', 'app', 'cloud', '郭磊'])
      expect(entityIcon(n)).toBe(NEUTRAL_ENTITY_ICON)
  })

  it('两条窄后缀规则：覆盖率低，但 100% 不会错', () => {
    expect(entityIcon('浩敏科技')).toBe('bx-buildings')
    expect(entityIcon('普发银行')).toBe('bx-buildings')
    expect(entityIcon('北京大学')).toBe('bx-book')
    expect(entityIcon('维多利亚国际学校')).toBe('bx-book')
  })

  it('索引层将来真填了 etype 就听它的', () => {
    expect(entityIcon('郭磊', 'person')).toBe('bx-user')
    expect(entityIcon('广州', 'place')).toBe('bx-map')
    expect(entityIcon('广汽集团', 'org')).toBe('bx-buildings')
    expect(entityIcon('iphone', 'product')).toBe('bx-package')
    expect(entityIcon('说不清', 'whatever')).toBe(NEUTRAL_ENTITY_ICON)
  })

  it('空的不炸', () => {
    expect(entityIcon('')).toBe(NEUTRAL_ENTITY_ICON)
  })
})
