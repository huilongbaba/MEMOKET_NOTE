import { describe, expect, it } from 'vitest'
import { imageInsertion } from '../imagePaste'

describe('imageInsertion', () => {
  it('光标在标题行中间：插到这一行末尾之后，标题不被切开', () => {
    // "# 创业一年回顾" 从 0 开始，光标在 "# " 之后（pos 2），行尾 8
    const r = imageInsertion('# 创业一年回顾', 8, 2, '![p](u)')
    expect(r).toEqual({ at: 8, text: '\n\n![p](u)\n' })
  })
  it('空行原地放', () => {
    expect(imageInsertion('', 10, 10, '![p](u)')).toEqual({ at: 10, text: '![p](u)' })
  })
})
