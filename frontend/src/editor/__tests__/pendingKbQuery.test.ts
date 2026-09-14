import { beforeEach, describe, expect, it } from 'vitest'
import { setPendingKbQuery, takePendingKbQuery } from '../../util/pendingKbQuery'

describe('「到知识库里搜这个词」带过去的那个词', () => {
  beforeEach(() => { takePendingKbQuery() })

  it('取走之后就清掉——再开一次知识库不该又自己填上上次的词', () => {
    setPendingKbQuery('严亚')
    expect(takePendingKbQuery()).toBe('严亚')
    expect(takePendingKbQuery()).toBe('')
  })

  it('没人放过词就是空的', () => {
    expect(takePendingKbQuery()).toBe('')
  })
})
