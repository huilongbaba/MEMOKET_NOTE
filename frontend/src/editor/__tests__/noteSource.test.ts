import { describe, expect, it } from 'vitest'
import { sourceIcon, sourceLabel } from '../../util/noteSource'

describe('树上的来源图标', () => {
  it('导进来的和机器生成的各有自己的图标', () => {
    expect(sourceIcon('feishu')).toBe('bx-paper-plane')
    expect(sourceIcon('plan')).toBe('bx-rocket')
    expect(sourceLabel('plan')).toBe('无限续写生成的')
  })

  it('自己写的没有来源图标——「正常」不需要解释，也不该占一个字形', () => {
    expect(sourceIcon('')).toBe('')
    expect(sourceIcon(undefined)).toBe('')
    expect(sourceLabel('')).toBe('')
  })

  it('不认识的来源不乱给图标：宁可用默认的 note，也别给个看不懂的符号', () => {
    expect(sourceIcon('某个以后才有的来源')).toBe('')
  })

  it('每个有图标的来源都得有说明——悬停说不清的图标等于噪声', () => {
    for (const s of ['obsidian', 'notion', 'feishu', 'apple', 'evernote', 'import', 'plan']) {
      expect(sourceIcon(s), s).not.toBe('')
      expect(sourceLabel(s), s).not.toBe('')
    }
  })
})
