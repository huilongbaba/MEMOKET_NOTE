import { describe, expect, it } from 'vitest'
import { MIN_LEFT_W, layoutPanes, makeRoomForRight } from '../../util/layoutPanes'

/** 用户实拍：「右侧栏打不开了？」——`rightOn` 本来就是 true，是被动布局规则
 *  （中栏不够 520 就收右栏）把它盖掉的，所以那个按钮点了等于没点。
 *  明确的动作应该赢。 */
const shown = (p: ReturnType<typeof makeRoomForRight>, winW: number) =>
  layoutPanes({ winW, panes: p, splitW: null, focusMode: false }).rightShown

describe('明确要开右栏', () => {
  it('本来就够宽：什么都不动', () => {
    const p = { leftW: 260, rightW: 340, leftOn: true, rightOn: false }
    const next = makeRoomForRight(p, 1440)
    expect(next).toEqual({ ...p, rightOn: true })
    expect(shown(next, 1440)).toBe(true)
  })

  it('不够宽：把左栏收窄到刚好放得下，而不是默默不开', () => {
    // 实拍那一档：左栏 289、窗口 1200 → 1200-80-289-340 = 491 < 520
    const p = { leftW: 289, rightW: 340, leftOn: true, rightOn: true }
    expect(shown(p, 1200)).toBe(false)          // 改之前：点了也开不出来
    const next = makeRoomForRight(p, 1200)
    expect(shown(next, 1200)).toBe(true)
    expect(next.leftOn).toBe(true)
    expect(next.leftW).toBeLessThan(289)
  })

  it('左栏已经到最窄还放不下：收左栏，而不是放弃右栏', () => {
    const p = { leftW: 300, rightW: 340, leftOn: true, rightOn: false }
    const next = makeRoomForRight(p, 900)
    expect(next.rightOn).toBe(true)
    expect(next.leftOn).toBe(false)
    expect(shown(next, 900)).toBe(true)
  })

  it('腾出来的左栏不会比下限还窄', () => {
    for (const winW of [900, 1000, 1100, 1200, 1366]) {
      const next = makeRoomForRight({ leftW: 400, rightW: 340, leftOn: true, rightOn: false }, winW)
      if (next.leftOn) expect(next.leftW).toBeGreaterThanOrEqual(MIN_LEFT_W)
      expect(shown(next, winW)).toBe(true)
    }
  })

  it('左栏本来就收着：只开右栏，不去动它', () => {
    const p = { leftW: 400, rightW: 340, leftOn: false, rightOn: false }
    expect(makeRoomForRight(p, 900)).toEqual({ ...p, rightOn: true })
  })
})
