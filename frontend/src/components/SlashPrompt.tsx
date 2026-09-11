import { useEffect, useRef, useState } from 'react'
import type { SlashItem } from '../editor/slashMenu'

/** `/` 选中一个需要提示词的功能之后，就地弹出的输入框。
 *
 * 位置由调用方按编辑器里那个 `/` 的屏幕坐标给——**不跟着页面滚动重算**：
 * 它出现之后用户下一步就是打字或者按 Esc，中间不会去滚页面，为这点加一套
 * 监听不值得。 */
export default function SlashPrompt({ item, x, y, busy, phase, onRun, onCancel }: {
  item: SlashItem
  x: number
  y: number
  busy: boolean
  phase: string
  onRun: (prompt: string) => void
  onCancel: () => void
}) {
  const [value, setValue] = useState('')
  const ref = useRef<HTMLInputElement>(null)

  useEffect(() => { ref.current?.focus() }, [])

  const left = Math.min(Math.max(8, x), window.innerWidth - 420)
  const top = Math.min(y, window.innerHeight - 140)

  return (
    <div
      className="palette"
      style={{ position: 'fixed', left, top, width: 400, padding: 10, zIndex: 260 }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="row" style={{ gap: 6, alignItems: 'center', marginBottom: 6 }}>
        <i className={'bx ' + item.icon} />
        <strong style={{ fontSize: 13 }}>{item.label}</strong>
        <span className="muted" style={{ fontSize: 11 }}>{item.hint}</span>
      </div>
      <input
        ref={ref}
        value={value}
        disabled={busy}
        placeholder={item.placeholder ?? '想让它做什么？'}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); onRun(value) }
          if (e.key === 'Escape') { e.preventDefault(); onCancel() }
        }}
        style={{ width: '100%', boxSizing: 'border-box' }}
      />
      <div className="row" style={{ justifyContent: 'space-between', marginTop: 6, fontSize: 11 }}>
        <span className="muted">
          {busy ? <><span className="spinner" /> {phase || '在跑…'}</> : 'Enter 开始 · Esc 取消'}
        </span>
        {busy
          ? <button onClick={onCancel}>停止</button>
          : <button onClick={() => onRun(value)}>开始</button>}
      </div>
    </div>
  )
}
