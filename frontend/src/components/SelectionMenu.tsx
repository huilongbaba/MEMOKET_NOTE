import { useEffect, useRef } from 'react'

export type SelectionAction = 'verify' | 'rewrite' | 'polish' | 'expand' | 'trace' | 'custom'

/**
 * Right-click-with-a-selection context menu. Standard AI-editor actions
 * (Notion/Craft-style "ask AI about this selection") scoped to whatever
 * text is highlighted, rather than the whole note -- verify/rewrite/polish/
 * expand all need "what did the user select", which magic-tap/edit (whole-
 * document actions) don't.
 */
export default function SelectionMenu({ x, y, busy, onAction, onClose }: {
  x: number
  y: number
  busy: boolean
  onAction: (action: SelectionAction) => void
  onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onDocMouseDown(e: MouseEvent) {
      // **右键不算「点了外面」**。右键的 mousedown 后面紧跟着 contextmenu，
      // 那次 contextmenu 会自己决定要不要换个位置重开菜单；在这里先关掉的话，
      // 如果新位置没有选区，就变成"菜单被关了、也没新菜单"——用户看到的是
      // 右键之后什么都没有。
      if (e.button === 2) return
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    // capture-phase mousedown so this closes before a click elsewhere (e.g.
    // re-selecting text) does anything else with that click.
    document.addEventListener('mousedown', onDocMouseDown, true)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onDocMouseDown, true)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [onClose])

  const left = Math.min(x, window.innerWidth - 180)
  const top = Math.min(y, window.innerHeight - 200)

  return (
    <div
      ref={ref}
      className="palette"
      style={{ position: 'fixed', left, top, width: 160, padding: 4, zIndex: 250 }}
    >
      {busy ? (
        <div style={{ padding: 10, textAlign: 'center' }}><span className="spinner" /></div>
      ) : (
        <div className="palette-results" style={{ padding: 0 }}>
          <div className="palette-item" onClick={() => onAction('verify')}>🔍 校验</div>
          <div className="palette-item" onClick={() => onAction('rewrite')}>✏️ 重写</div>
          <div className="palette-item" onClick={() => onAction('polish')}>✨ 润色</div>
          <div className="palette-item" onClick={() => onAction('expand')}>↔️ 扩展上下文</div>
          {/* 来龙去脉：这段涉及的事情按时间怎么演进的。**用户不写问题**——
              问题由后端拼（判据 1）。对应痛点 13：汇总零散笔记时 AI 捋不清
              时间线，而 KITE 的 planning 恰好擅长时序。 */}
          <div className="palette-item" onClick={() => onAction('trace')}>🕘 来龙去脉</div>
          {/* 跟 `/` 的「用 AI 写」是同一套 harness，差别在**作用域**：那个是
              「在光标这里插一块」，这个是「对我选中的这段做点什么」。 */}
          <div className="palette-item" onClick={() => onAction('custom')}>💬 自定义提示…</div>
        </div>
      )}
    </div>
  )
}
