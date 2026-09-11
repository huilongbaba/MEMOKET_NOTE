/** 外观：跟随系统 / 浅色 / 深色。
 *
 * 界面暗色全靠 CSS 的 `prefers-color-scheme`；桌面壳里那个值由主进程的
 * nativeTheme 决定，所以这里只是把选择存下来、再通过 preload 递给主进程。
 * 纯浏览器里没有这条通道，只能跟随系统——设置页会说明。 */
export type Theme = 'system' | 'light' | 'dark'

const KEY = 'memoket.theme'

declare global {
  interface Window { memoketDesktop?: { setTheme(theme: Theme): void } }
}

export function getTheme(): Theme {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch { return 'system' }
}

export function applyTheme(theme: Theme) {
  try { localStorage.setItem(KEY, theme) } catch { /* 私密窗口等：不存也能用 */ }
  window.memoketDesktop?.setTheme(theme)
}

export const canSwitchTheme = () => !!window.memoketDesktop

/** 启动时把上次的选择再递一遍——主进程每次冷启动都是「跟随系统」。 */
export function restoreTheme() {
  const t = getTheme()
  if (t !== 'system') applyTheme(t)
}
