import { describe, expect, it } from 'vitest'
import { factsLabel, isKnownVirtual, previewLine, VIRTUAL_LABELS } from '../../util/virtual'

describe('virtual 页的纯规则', () => {
  it('factsLabel：带筛选的事实表叫「事实表 · 值」', () => {
    expect(factsLabel('kb:facts')).toBe('事实表')
    expect(factsLabel('kb:facts?topic=work')).toBe('事实表 · work')
    expect(factsLabel('kb:facts?kind=plan&who=speaker%20b')).toBe('事实表 · plan · speaker b')
    expect(factsLabel('kb:topic:work')).toBeUndefined()
  })
  it('isKnownVirtual：固定页 / 知识库节点 / 带查询串的事实表 / app:*', () => {
    for (const id of Object.keys(VIRTUAL_LABELS)) expect(isKnownVirtual(id)).toBe(true)
    for (const id of ['kb:topic:work', 'kb:entity:acme', 'kb:facts?topic=work', 'kb:material:u1', 'app:trash']) expect(isKnownVirtual(id)).toBe(true)
    for (const id of ['kb:overview', 'kb:nope:x', 'note:123', '']) expect(isKnownVirtual(id)).toBe(false)
  })
  it('previewLine：跳过跟标题一样的首行、剥记号、整篇缩进也剥', () => {
    expect(previewLine('# 会议纪要 10\n- 第一条', '会议纪要 10')).toBe('第一条')
    expect(previewLine('    ## 时间线\n正文', '')).toBe('时间线')
    expect(previewLine('', '')).toBe('')
  })
})
