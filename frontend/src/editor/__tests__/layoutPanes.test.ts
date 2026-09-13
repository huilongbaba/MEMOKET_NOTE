import { describe, expect, it } from 'vitest'
import { layoutPanes } from '../../util/layoutPanes'

const panes = { leftW: 260, rightW: 340, leftOn: true, rightOn: true }

describe('layoutPanes', () => {
  it('宽窗口：两侧都在，宽度照用户设的', () => {
    expect(layoutPanes({ winW: 1440, panes, splitW: null, focusMode: false }))
      .toEqual({ leftW: 260, splitW: 0, leftShown: true, rightShown: true })
  })
  it('900×600（实拍 ribbon 折三行）：右栏先收，左栏留着且不超窗口 30%', () => {
    const r = layoutPanes({ winW: 900, panes, splitW: null, focusMode: false })
    expect(r.rightShown).toBe(false)
    expect(r.leftShown).toBe(true)
    expect(r.leftW).toBe(260)   // 900*0.3 = 270 > 260
    expect(layoutPanes({ winW: 800, panes, splitW: null, focusMode: false }).leftW).toBe(240)
  })
  it('1000×700 开分屏（实拍中栏 250px）：分屏封顶 45%，右栏收，左栏也收', () => {
    const r = layoutPanes({ winW: 1000, panes, splitW: 600, focusMode: false })
    expect(r.splitW).toBe(450)
    expect(r.rightShown).toBe(false)
    expect(r.leftShown).toBe(false)
  })
  it('用户关了左栏就不把它算进去；专注模式两边都收', () => {
    expect(layoutPanes({ winW: 900, panes: { ...panes, leftOn: false }, splitW: null, focusMode: false }))
      .toMatchObject({ leftShown: false, rightShown: true })
    expect(layoutPanes({ winW: 1440, panes, splitW: null, focusMode: true })).toMatchObject({ leftShown: false, rightShown: false })
  })
})
