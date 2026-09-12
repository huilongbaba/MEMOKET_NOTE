/** 快捷键怎么写给人看：mac 用 ⌘⌥⇧⌃ 符号，Windows / Linux 用 Ctrl+ / Alt+ / Shift+。
 *  键表和菜单里的写法统一从 mac 符号出发，显示时按平台翻译。 */
export const isMac = typeof navigator !== 'undefined' && /Mac/.test(navigator.platform)

export function fmtShortcut(s: string, mac: boolean = isMac): string {
  if (mac) return s
  return s
    .replace(/⌘/g, 'Ctrl+')
    .replace(/⌥/g, 'Alt+')
    .replace(/⇧/g, 'Shift+')
    .replace(/⌃/g, 'Ctrl+')
    .replace(/⌫/g, 'Del')
    .replace(/↩/g, 'Enter')
    .replace(/\+\+/g, '+')
}
