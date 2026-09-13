import { describe, expect, it } from 'vitest'
import { resolveDraft } from '../../util/draft'

const note = { title: '题', content: '库里的', updated_at: '2026-09-14T10:00:00Z' }
const later = Date.parse('2026-09-14T10:05:00Z')
const earlier = Date.parse('2026-09-14T09:00:00Z')

describe('resolveDraft', () => {
  it('草稿比库里新且内容不同：放回来，题目空就用库里的', () => {
    expect(resolveDraft(note, { title: '', content: '草稿', at: later }, false))
      .toEqual({ title: '题', content: '草稿', restored: true, clear: false })
  })
  it('探针模式下放回来也顺手清掉（第 136 轮：探针文案混进真笔记）', () => {
    expect(resolveDraft(note, { title: '草题', content: '草稿', at: later }, true)).toMatchObject({ title: '草题', restored: true, clear: true })
  })
  it('草稿旧了 / 内容一样：用库里的，草稿清掉；没草稿就什么都不清', () => {
    expect(resolveDraft(note, { title: 'x', content: '草稿', at: earlier }, false)).toEqual({ title: '题', content: '库里的', restored: false, clear: true })
    expect(resolveDraft(note, { title: 'x', content: '库里的', at: later }, false)).toMatchObject({ restored: false, clear: true })
    expect(resolveDraft(note, null, false)).toEqual({ title: '题', content: '库里的', restored: false, clear: false })
  })
})
