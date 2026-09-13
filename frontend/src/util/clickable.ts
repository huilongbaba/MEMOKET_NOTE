/** 把一个 div / span 变成键盘也能按的「按钮」：role + tabIndex + Enter / 空格触发（第 506 轮横扫：
 *  8 处可点的卡片 / 行只有 onClick，Tab 走不到、屏幕阅读器也不认）。真按钮还是用 <button>。 */
import type { KeyboardEvent, MouseEvent } from 'react'

export function clickable<T extends HTMLElement>(onClick: (e: MouseEvent<T> | KeyboardEvent<T>) => void) {
  return {
    role: 'button' as const,
    tabIndex: 0,
    onClick,
    onKeyDown: (e: KeyboardEvent<T>) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(e) }
    },
  }
}
