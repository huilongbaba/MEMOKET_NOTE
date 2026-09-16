/**
 * 通用右键菜单 —— 对标 Trilium 的 context menu service。
 *
 * 做成通用的（而不是给树写死一个）是因为它要被树、标签页、编辑器选区
 * 三处复用，那三处的菜单项完全不同、但打开/定位/关闭/键盘操作是同一套。
 *
 * 几个容易被忽略但必须处理的点：
 * · **贴边钳制**：在窗口右下角右键时，菜单要往里挪，不然一半在屏幕外。
 *   Trilium 主菜单是钳制（距边 5px），只有子菜单才翻转——一致。
 * · **Esc 和点空白都要关**，且关闭时焦点还回去——不然键盘用户会被困住。
 *   （Trilium 的菜单**完全没有键盘支持**，这条是我们比它强的地方，不对齐。）
 * · **连续分隔线去重**（context_menu.ts:277-280）：条件渲染的项一消失就会
 *   出现两条线连着。
 * · `hint` 是说明文字（禁用时说为什么），`shortcut` 是快捷键——两者分开，
 *   混用一个槽位以后加快捷键就撞了。
 * · **挂到 `document.body`（portal），不留在调用处的 DOM 里。**
 *   它是 `position: fixed` + 视口坐标，而 `fixed` 的包含块**会被祖先抢走**——
 *   `backdrop-filter` / `filter` / `transform` / `will-change` 任意一个都会。
 *   第 738 轮真出过：composer 那条玻璃胶囊有 `backdrop-filter`，
 *   菜单于是按胶囊定位，量出来在 `x=1175 y=763`（视口 1280×860）——
 *   **95% 在屏幕外**，用户报「没有一个功能是正常可以点击的」。
 *   portal 之后它挂在哪儿都一样。（React 的事件冒泡仍走组件树，
 *   `ref.current.contains()` 也照常，因为 ref 指的是真实 DOM 节点。）
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useRestoreFocus } from '../util/restoreFocus'
import { fmtShortcut } from '../util/keys'
import Icon from './Icon'

export type MenuItem =
  | { kind: 'sep' }
  | { kind: 'header'; label: string }
  | {
      kind?: 'item'
      label: string
      icon?: string
      hint?: string          // 右侧的说明（禁用时说为什么）
      shortcut?: string      // 快捷键，<kbd> 样式
      danger?: boolean
      disabled?: boolean
      onSelect: () => void
    }

export type MenuAt = { x: number; y: number }

/** 能点的那一类（不是分隔线、不是小标题）。 */
export type MenuAction = Extract<MenuItem, { onSelect: () => void }>

/** 这一项现在能不能被选中（键盘走位和回车都用它）。
 *  写成类型谓词而不是 `as any`：**「禁用项不能被回车触发」这条规矩
 *  由编译器一起看着**，而不是靠调用处记得先问一句（第 709 轮）。 */
export function selectableItem(it: MenuItem | undefined): it is MenuAction {
  return !!it && it.kind !== 'sep' && it.kind !== 'header' && !it.disabled
}

/** 去掉连续的、开头的、结尾的分隔线。 */
export function tidyMenu(items: MenuItem[]): MenuItem[] {
  const out: MenuItem[] = []
  for (const it of items) {
    const sep = 'kind' in it && it.kind === 'sep'
    const prevSep = out.length === 0 || out[out.length - 1].kind === 'sep'
    if (sep && prevSep) continue
    out.push(it)
  }
  while (out.length && out[out.length - 1].kind === 'sep') out.pop()
  return out
}

export default function ContextMenu({
  at, items, onClose,
}: { at: MenuAt; items: MenuItem[]; onClose: () => void }) {
  useRestoreFocus()   // 关掉之后焦点回到打开之前的地方（编辑器 / 树行）
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<MenuAt>(at)
  const [hi, setHi] = useState(-1)
  const list = tidyMenu(items)

  // 先按原位渲染再量尺寸——菜单项数量不定，高度只能量出来，算不出来。
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const { width, height } = el.getBoundingClientRect()
    const pad = 5
    setPos({
      x: Math.max(pad, Math.min(at.x, window.innerWidth - width - pad)),
      // 比窗口还高的菜单（50 个标签的列表）：贴顶，靠 CSS 的 max-height 内部滚，别把头顶到窗口外面
      y: Math.max(pad, Math.min(at.y, window.innerHeight - height - pad)),
    })
  }, [at.x, at.y, list.length])

  // 高亮项滚进视野：菜单比窗口高时内部滚（50 个标签的列表），↑↓ 走到看不见的地方要跟着滚
  useEffect(() => {
    if (hi < 0) return
    const el = ref.current?.querySelector('.context-menu-item.hi') as HTMLElement | null
    el?.scrollIntoView({ block: 'nearest' })
  }, [hi])

  useEffect(() => {
    const selectable = (k: number) => selectableItem(list[k])
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); onClose(); return }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        const step = e.key === 'ArrowDown' ? 1 : -1
        let k = hi
        for (let n = 0; n < list.length; n++) {
          k = (k + step + list.length) % list.length
          if (selectable(k)) { setHi(k); break }
        }
      } else if (e.key === 'Enter') {
        const it = list[hi]
        if (!selectableItem(it)) return
        e.preventDefault(); onClose(); it.onSelect()
      }
    }
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) onClose()
    }
    window.addEventListener('keydown', onKey)
    // capture：菜单项自己的 onClick 先跑完，再由它关掉菜单
    window.addEventListener('mousedown', onDown, true)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onDown, true)
    }
  }, [onClose, hi, list])

  return createPortal((
    <div
      ref={ref}
      className="context-menu"
      role="menu"
      style={{ left: pos.x, top: pos.y }}
    >
      {list.map((it, i) => {
        if ('kind' in it && it.kind === 'sep') return <div key={i} className="context-menu-sep" />
        if ('kind' in it && it.kind === 'header') return <div key={i} className="context-menu-header">{it.label}</div>
        const item = it as Extract<MenuItem, { label: string; onSelect: () => void }>
        return (
          <button
            key={i}
            role="menuitem"
            className={'context-menu-item' + (item.danger ? ' danger' : '') + (hi === i ? ' hi' : '')}
            disabled={item.disabled}
            onMouseEnter={() => setHi(i)}
            onClick={() => { onClose(); item.onSelect() }}
          >
            <span className="cm-icon">{item.icon?.startsWith('bx-') ? <Icon n={item.icon} /> : (item.icon ?? '')}</span>
            <span className="cm-label">{item.label}</span>
            {/* 提示只显示一行（CSS 打省略号），全文进 title——菜单要的是可扫 */}
            {item.hint && <span className="cm-hint" title={item.hint}>{item.hint}</span>}
            {item.shortcut && <kbd className="cm-kbd">{fmtShortcut(item.shortcut)}</kbd>}
          </button>
        )
      })}
    </div>
  ), document.body)
}
