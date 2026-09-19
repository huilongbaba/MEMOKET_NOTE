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

/** 卡跟正文之间留一条缝：`below` / `above` 时卡就压在正文上，没有这条缝看上去像是「粘在字上」。 */
const SEAM = 6

export function placeCard(anchor: Rect, bounds: Rect, cardH: number, winH: number, want = CARD_WIDTH): { left: number; top: number; width: number; side: 'right' | 'below' | 'above' } {
  // **卡从来不许伸出正文栏**（P19 #3 / P17 #7）：P10 那版只夹了右缘，900px 窄栏下
  // `anchor.left - width + 4` 算出来的左缘比栏左边还小 16px，`Math.min` 又只往小了取——
  // 于是 ⌥ 卡从正文栏**左边**探出去 16px（实拍 `p17-11c-new-light-900-althover`）。
  // 夹两头：先按栏右缘夹上限，再按栏左缘夹下限（顺序反了就还是会漏出左边）。
  const width = Math.max(200, Math.min(want, bounds.width - EDGE * 2))
  const clampTop = (t: number) => Math.max(EDGE, Math.min(t, winH - EDGE - cardH))
  const clampLeft = (l: number) => Math.max(bounds.left + EDGE, Math.min(l, bounds.right - EDGE - width))
  if (anchor.right + GAP + width <= bounds.right - EDGE) {
    return { left: anchor.right + GAP, top: clampTop(anchor.top - 8), width, side: 'right' }
  }
  const left = clampLeft(anchor.left - width + 4)
  if (anchor.bottom + SEAM + cardH <= winH - EDGE) return { left, top: anchor.bottom + SEAM, width, side: 'below' }
  return { left, top: clampTop(anchor.top - SEAM - cardH), width, side: 'above' }
}

/** 悬停卡挂在段落**之间**要空出多少行（P19 #3 / P17 #7）。
 *
 *  P17 实拍：圆点悬停卡「挂在这一行下面」正好盖住**下一段的前半行**（`p17-3b-old-light-hover`：
 *  「众筹页面定在 3月12号 上线，EVT 样品 4月10…」后半截被卡盖掉）。悬停即走，所以 P17 判「能忍」，
 *  但读到一半被盖住的那半行确实读不下去了。
 *
 *  修法不是挪卡（挪到哪儿都会盖住别的字），是**把正文推开**：卡出现时给锚点那一行下面
 *  临时垫出卡的高度，卡收起就还原。`MarginCard` / `TraceCard` 把这个值写进 CSS 变量，
 *  编辑器那一行的 `padding-bottom` 读它——纯视觉，不动文档内容、不动光标位置。
 *
 *  返回 0 = 不用垫（卡贴在圆点右边，或挂在上面，都没盖住下文）。 */
export function seamPush(side: 'right' | 'below' | 'above', cardH: number): number {
  return side === 'below' ? cardH + SEAM * 2 : 0
}


/** 把卡底下那一行正文推开，卡收起时还原（P19 #3）。
 *
 *  `at` 是卡锚定的那个位置（圆点 / 词）的矩形，按它找到所在的 `.cm-line`，给它临时加
 *  `padding-bottom`——CodeMirror 的行是普通 DOM，加内边距只是把后面的行往下挪，
 *  **文档一个字都没动**（不进 undo 历史、不动光标、不触发 `docChanged`）。
 *
 *  返回还原函数。`px = 0` 时什么都不做（卡贴在右边 / 挂在上面，没盖住下文）。 */
export function pushLineBelow(at: { left: number; top: number; bottom: number }, px: number): () => void {
  if (px <= 0 || typeof document === 'undefined') return () => {}
  // 锚点可能落在页边栏（圆点）上，那儿不是 .cm-line：往正文里挪一点再取
  const probeX = at.left + 40
  const probeY = (at.top + at.bottom) / 2
  const el = (document.elementFromPoint(probeX, probeY) as HTMLElement | null)?.closest('.cm-line') as HTMLElement | null
  if (!el) return () => {}
  const before = el.style.paddingBottom
  el.style.paddingBottom = `${px}px`
  el.dataset.cardSeam = '1'
  return () => {
    el.style.paddingBottom = before
    delete el.dataset.cardSeam
  }
}
