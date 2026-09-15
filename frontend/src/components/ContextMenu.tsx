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
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useRestoreFocus } from '../util/restoreFocus'
import { fmtShortcut } from '../util/keys'

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

/** 去掉连续的、开头的、结尾的分隔线。 */
export function tidyMenu(items: MenuItem[]): MenuItem[] {
  const out: MenuItem[] = []
  for (const it of items) {
    const sep = 'kind' in it && it.kind === 'sep'
    const prevSep = out.length === 0 || ('kind' in out[out.length - 1] && (out[out.length - 1] as any).kind === 'sep')
    if (sep && prevSep) continue
    out.push(it)
  }
  while (out.length && 'kind' in out[out.length - 1] && (out[out.length - 1] as any).kind === 'sep') out.pop()
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
    const selectable = (k: number) => {
      const it = list[k] as any
      return it && it.kind !== 'sep' && it.kind !== 'header' && !it.disabled
    }
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
      } else if (e.key === 'Enter' && selectable(hi)) {
        e.preventDefault(); onClose(); (list[hi] as any).onSelect()
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

  return (
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
            <span className="cm-icon">{item.icon?.startsWith('bx-') ? <i className={'bx ' + item.icon} /> : (item.icon ?? '')}</span>
            <span className="cm-label">{item.label}</span>
            {/* 提示只显示一行（CSS 打省略号），全文进 title——菜单要的是可扫 */}
            {item.hint && <span className="cm-hint" title={item.hint}>{item.hint}</span>}
            {item.shortcut && <kbd className="cm-kbd">{fmtShortcut(item.shortcut)}</kbd>}
          </button>
        )
      })}
    </div>
  )
}
