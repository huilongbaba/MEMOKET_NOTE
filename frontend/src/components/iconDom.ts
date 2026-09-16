/** 在**手写 DOM** 的地方放一个 lucide 图标。
 *
 * CM6 的 tooltip 和 widget 都不是 React——它们自己 `document.createElement`。
 * 第 713 轮把字体图标换成 SVG 之后，这些地方还写着 `<i class="bx bx-note">`，
 * **渲染出来是空的**（用户第 741 轮：「/ 里的功能呢，怎么没有图标了，显得好空」）。
 * 我那次的机械替换只扫了 JSX，漏了手写 DOM 的两处。
 *
 * 用 React 根挂进去，再把卸载函数交回调用方——CM6 的 tooltip 有 `destroy`、
 * widget 有 `destroy()`，都接得住，不会漏根。
 */
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'

import Icon from './Icon'

export function mountIcon(el: HTMLElement, name: string): () => void {
  const root = createRoot(el)
  root.render(createElement(Icon, { n: name }))
  // 卸载要推迟一拍：CM6 销毁 widget 时可能正处在 React 的渲染过程里，
  // 同步 unmount 会拿到 "Attempted to synchronously unmount" 的警告。
  return () => setTimeout(() => root.unmount(), 0)
}
