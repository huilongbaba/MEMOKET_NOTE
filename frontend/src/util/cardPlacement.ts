/** 页边关系卡放哪（P10，修 P9 的「卡压住右栏」）。
 *
 *  P9 只按**窗口**宽度判「右边放不放得下」，正文栏右边紧挨着右栏，于是卡贴着圆点向右伸出去
 *  压在右栏的记忆卡上（`p9-margin-after-light`：右栏那张冲突卡的头被盖住）。卡属于正文这一栏，
 *  边界应该是**正文栏**：
 *    1. 圆点右边、栏内放得下 → 贴在圆点右边（宽栏 / 右栏收起时）
 *    2. 放不下 → 挂在这一行**下面**，右缘对齐栏的右缘（盖住的是下面几行正文，不是另一栏的卡）
 *    3. 下面也放不下 → 挂在这一行上面
 *  卡宽跟着栏走：栏比 340 窄就缩。 */
export type Rect = { left: number; top: number; right: number; bottom: number; width: number; height: number }

export const CARD_WIDTH = 340
const GAP = 10
const EDGE = 8

export function placeCard(anchor: Rect, bounds: Rect, cardH: number, winH: number, want = CARD_WIDTH): { left: number; top: number; width: number; side: 'right' | 'below' | 'above' } {
  const width = Math.max(200, Math.min(want, bounds.width - EDGE * 2))
  const clampTop = (t: number) => Math.max(EDGE, Math.min(t, winH - EDGE - cardH))
  if (anchor.right + GAP + width <= bounds.right - EDGE) {
    return { left: anchor.right + GAP, top: clampTop(anchor.top - 8), width, side: 'right' }
  }
  const left = Math.max(bounds.left + EDGE, Math.min(anchor.left - width + 4, bounds.right - EDGE - width))
  if (anchor.bottom + 6 + cardH <= winH - EDGE) return { left, top: anchor.bottom + 6, width, side: 'below' }
  return { left, top: clampTop(anchor.top - 6 - cardH), width, side: 'above' }
}
