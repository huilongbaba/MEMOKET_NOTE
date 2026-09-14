/** 三栏 + 分屏的宽度裁决：窗口窄的时候正文优先。从 App.tsx 挪出来（第 475 轮），纯函数好测。
 *
 * 两侧栏保持用户设的宽度会把编辑器挤到 300px（900×600 实拍：ribbon 折三行、工具栏溢出）。
 * 中栏不够 520px 就先收右栏（用户的开关不动，窗口拉宽自动回来）；左栏最多占窗口 30%。
 * 分屏也算进去：1000×700 开分屏实拍，中栏被挤到 250px，ribbon 折两行、工具栏只剩 B。
 * 分屏最多占窗口 45%；右栏先收，还不够就连左栏也收（关掉分屏自动回来）。 */
export const LAUNCHER_W = 80
export const MIN_EDITOR_W = 520

export interface PaneLayoutIn {
  winW: number
  panes: { leftW: number; rightW: number; leftOn: boolean; rightOn: boolean }
  /** 分屏用户设的宽度；没开分屏 null */
  splitW: number | null
  focusMode: boolean
}

export function layoutPanes({ winW, panes, splitW: wantSplit, focusMode }: PaneLayoutIn) {
  const leftW = Math.min(panes.leftW, Math.floor(winW * 0.3))
  const splitW = wantSplit != null ? Math.min(wantSplit, Math.floor(winW * 0.45)) : 0
  const tooNarrowForRight = panes.leftOn && winW - LAUNCHER_W - leftW - panes.rightW - splitW < MIN_EDITOR_W
  const tooNarrowForLeft = wantSplit != null && winW - LAUNCHER_W - leftW - splitW < MIN_EDITOR_W
  return {
    leftW, splitW,
    leftShown: !focusMode && panes.leftOn && !tooNarrowForLeft,
    rightShown: !focusMode && panes.rightOn && !tooNarrowForRight,
  }
}


/** 左栏最窄能到多少（跟 Gutter 的下限同一个数）。 */
export const MIN_LEFT_W = 150

/** 用户**明确要**打开右栏时，把它打开——不够宽就腾地方。
 *
 * 上面那条「中栏不够 520px 就先收右栏」是**被动布局**：窗口一窄先保正文，用户的
 * 开关不动、拉宽自动回来。但它原来连用户的**主动**动作也一起否决了：
 * 左栏拖到 289px、窗口 1200 时 `1200-80-289-340=491 < 520`，右栏被判放不下；
 * 而「展开右栏」那个按钮只是把 `rightOn` 置 true——它本来就是 true，
 * **于是点了等于没点，还没有任何解释**（用户实拍：「右侧栏打不开了？」）。
 *
 * 明确的动作应该赢。腾地方的顺序是「先让左栏窄一点，实在不行才收左栏」——
 * 右栏是你刚要的，左栏是你可以再拉回来的。
 */
export function makeRoomForRight(
  panes: PaneLayoutIn['panes'], winW: number, splitW = 0,
): PaneLayoutIn['panes'] {
  const next = { ...panes, rightOn: true }
  if (!next.leftOn) return next
  const leftW = Math.min(next.leftW, Math.floor(winW * 0.3))
  const short = MIN_EDITOR_W - (winW - LAUNCHER_W - leftW - next.rightW - splitW)
  if (short <= 0) return next
  const shrunk = leftW - short
  return shrunk >= MIN_LEFT_W ? { ...next, leftW: shrunk } : { ...next, leftOn: false }
}
