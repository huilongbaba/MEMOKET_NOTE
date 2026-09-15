/** 快捷键怎么写给人看：mac 用 ⌘⌥⇧⌃ 符号，Windows / Linux 用 Ctrl+ / Alt+ / Shift+。
 *  键表和菜单里的写法统一从 mac 符号出发，显示时按平台翻译。 */
export const isMac = typeof navigator !== 'undefined' && /Mac/.test(navigator.platform)

/** 一串修饰符翻成 Windows / Linux 的写法。
 *
 *  **顺序要重排，不能直译**：mac 的规矩是 ⌃⌥⇧⌘（Command 在最后），
 *  Windows 的规矩是 Ctrl+Alt+Shift（Ctrl 在最前）。原来是逐个字符替换的，
 *  于是 `⇧⌘K` 直译成 `Shift+Ctrl+K`——两边都对不上（第 706 轮）。
 *  ⌃ 和 ⌘ 在这边都是 Ctrl，同一个和弦里不会两个都出现（现有的键没有这种）。 */
function winChord(mods: string): string {
  const out: string[] = []
  if (/[⌘⌃]/.test(mods)) out.push('Ctrl')
  if (mods.includes('⌥')) out.push('Alt')
  if (mods.includes('⇧')) out.push('Shift')
  return out.length ? out.join('+') + '+' : ''
}

export function fmtShortcut(s: string, mac: boolean = isMac): string {
  if (mac) return s
  return s
    .replace(/[⌘⌥⇧⌃]+/g, winChord)
    .replace(/⌫/g, 'Del')
    .replace(/↩/g, 'Enter')
}
