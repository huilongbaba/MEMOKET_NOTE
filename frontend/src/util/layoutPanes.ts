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
