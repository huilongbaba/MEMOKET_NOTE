/** 弹层关掉之后把焦点还给打开它之前的那个元素。
 *
 *  确认框 / 选择器 / 快速查看 / 快捷键表都是「从某个钮或菜单进来，关掉回去」，之前关掉后焦点掉到 body，
 *  键盘用户得重新 Tab 到原位。挂载时记下 activeElement，卸载时它还在页面上就 focus 回去。 */
import { useEffect } from 'react'

export function useRestoreFocus(): void {
  useEffect(() => {
    const prev = document.activeElement instanceof HTMLElement ? document.activeElement : null
    return () => {
      if (prev && prev.isConnected && typeof prev.focus === 'function') prev.focus()
    }
  }, [])
}
