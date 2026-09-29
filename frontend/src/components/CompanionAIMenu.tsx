import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { DesktopAIAction } from '../api'
import { DESKTOP_AI_ACTIONS } from '../util/companionActions'
import Icon from './Icon'

type Props = {
  x: number; y: number; scope: string; characters: number; disabledReason: string
  onAction: (action: DesktopAIAction) => void
  onClose: (restoreFocus: boolean) => void
  onMaterials: () => void
  onResume?: () => void
  /** 拿主意：把选中的文字（没选就是整篇草稿）交给岛的「拿主意」台面。 */
  onDecide?: () => void
}

/** Lives inside the island so its hit area, theme and native window remain aligned. */
export default function CompanionAIMenu({ x, y, scope, characters, disabledReason, onAction, onClose, onMaterials, onResume, onDecide }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState({ left: x, top: y })
  useLayoutEffect(() => {
    const menu = ref.current
    if (!menu) return
    const bounds = menu.parentElement!.getBoundingClientRect()
    const width = bounds.width || 640
    const height = bounds.height || 460
    menu.style.maxHeight = `${height - 16}px`
    menu.style.maxWidth = `${width - 16}px`
    setPosition({ left: Math.max(8, Math.min(x, width - menu.offsetWidth - 8)), top: Math.max(8, Math.min(y, height - menu.offsetHeight - 8)) })
    menu.querySelector<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')?.focus()
  }, [x, y])
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      const target = event.target as HTMLElement
      if (!ref.current?.contains(target) && !target.closest('[data-companion-ai-trigger]')) onClose(false)
    }
    const blur = () => onClose(false)
    document.addEventListener('pointerdown', outside)
    window.addEventListener('blur', blur)
    window.addEventListener('resize', blur)
    return () => { document.removeEventListener('pointerdown', outside); window.removeEventListener('blur', blur); window.removeEventListener('resize', blur) }
  }, [onClose])

  return <div ref={ref} className="dc-ai-menu" role="menu" aria-label="AI 操作" style={position} onContextMenu={event => event.preventDefault()} onKeyDown={event => {
    event.stopPropagation()
    if (event.key === 'Escape' || event.key === 'Tab') { event.preventDefault(); onClose(true); return }
    const items = [...ref.current!.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')]
    const current = items.indexOf(document.activeElement as HTMLButtonElement)
    const next = event.key === 'ArrowDown' ? (current + 1) % items.length : event.key === 'ArrowUp' ? (current - 1 + items.length) % items.length : event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : -1
    if (next >= 0) { event.preventDefault(); items[next]?.focus() }
  }}>
    <div className="dc-ai-menu-scope"><span>{scope}</span><span>{characters.toLocaleString()} 字</span></div>
    {disabledReason && <p className="dc-ai-menu-hint">{disabledReason}</p>}
    {DESKTOP_AI_ACTIONS.map(action => <button key={action.id} type="button" role="menuitem" tabIndex={-1} aria-label={action.label} disabled={!!disabledReason} title={disabledReason || action.description} onClick={() => onAction(action.id)}><Icon n={action.icon} /><span>{action.label}</span></button>)}
    <div className="dc-ai-menu-divider" role="separator" />
    {onDecide && <button type="button" role="menuitem" tabIndex={-1} title="从这段文字里列出可选项，各给一个概率" onClick={onDecide}><Icon n="bx-bulb" /><span>拿主意</span></button>}
    <button type="button" role="menuitem" tabIndex={-1} onClick={onMaterials}><Icon n="bx-layer-plus" /><span>从暂存架选择</span></button>
    {onResume && <button type="button" role="menuitem" tabIndex={-1} onClick={onResume}><Icon n="bx-history" /><span>继续生成稿</span></button>}
    <span className="dc-ai-menu-provider">由 Gemini 处理所选内容</span>
  </div>
}
