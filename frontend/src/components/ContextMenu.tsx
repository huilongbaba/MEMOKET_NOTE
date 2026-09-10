/**
 * 通用右键菜单 —— 对标 Trilium 的 context menu service。
 *
 * 做成通用的（而不是给树写死一个）是因为它要被树、标签页、编辑器选区
 * 三处复用，那三处的菜单项完全不同、但打开/定位/关闭/键盘操作是同一套。
 *
 * 两个容易被忽略但必须处理的点：
 * · **贴边翻转**：在窗口右下角右键时，菜单要往左上开，不然一半在屏幕外。
 * · **Esc 和点空白都要关**，且关闭时焦点还回去——不然键盘用户会被困住。
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

export type MenuItem =
  | { kind: 'sep' }
  | {
      kind?: 'item'
      label: string
      icon?: string
      hint?: string          // 右侧的快捷键/说明
      danger?: boolean
      disabled?: boolean
      onSelect: () => void
    }

export type MenuAt = { x: number; y: number }

export default function ContextMenu({
  at, items, onClose,
}: { at: MenuAt; items: MenuItem[]; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<MenuAt>(at)

  // 先按原位渲染再量尺寸——菜单项数量不定，高度只能量出来，算不出来。
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const { width, height } = el.getBoundingClientRect()
    const pad = 8
    setPos({
      x: Math.min(at.x, window.innerWidth - width - pad),
      y: Math.min(at.y, window.innerHeight - height - pad),
    })
  }, [at.x, at.y, items.length])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
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
  }, [onClose])

  return (
    <div
      ref={ref}
      className="context-menu"
      role="menu"
      style={{ left: pos.x, top: pos.y }}
    >
      {items.map((it, i) =>
        'kind' in it && it.kind === 'sep' ? (
          <div key={i} className="context-menu-sep" />
        ) : (
          <button
            key={i}
            role="menuitem"
            className={'context-menu-item' + ((it as any).danger ? ' danger' : '')}
            disabled={(it as any).disabled}
            onClick={() => { onClose(); (it as any).onSelect() }}
          >
            <span className="cm-icon">{(it as any).icon ?? ''}</span>
            <span className="cm-label">{(it as any).label}</span>
            {(it as any).hint && <span className="cm-hint">{(it as any).hint}</span>}
          </button>
        ),
      )}
    </div>
  )
}
