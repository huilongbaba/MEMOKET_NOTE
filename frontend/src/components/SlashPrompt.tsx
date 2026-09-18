import { useEffect, useRef, useState } from 'react'
import { useRestoreFocus } from '../util/restoreFocus'
import { blockPrecondition, MAX_PROMPT_CHARS, type SlashItem } from '../editor/slashMenu'
import Icon from './Icon'

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
  useRestoreFocus()   // 关掉之后焦点回到打开之前的地方（编辑器 / 树行）
  const [value, setValue] = useState('')
  // 空着按 Enter 的那句提示（P1-2-B1）：原来 `onRun('')` 直接放行——右键「自定义提示」
  // 什么都不写按确认，选中的那段被清掉、请求照发。现在输入框自己先拦：不关、不发、说一句。
  const [hint, setHint] = useState('')
  const ref = useRef<HTMLInputElement>(null)

  useEffect(() => { ref.current?.focus() }, [])

  function run() {
    // 选区 / 正文这两个条件由上层 `runBlock` 再判一次（它手上有编辑器）；这里只判输入框自己的
    const why = blockPrecondition(item, value, 'x', 'x')
    if (why) { setHint(why); ref.current?.focus(); return }
    onRun(value)
  }

  const left = Math.min(Math.max(8, x), window.innerWidth - 420)
  const top = Math.min(y, window.innerHeight - 140)

  return (
    <div
      className="palette"
      role="dialog" aria-label="AI 块生成"
      style={{ position: 'fixed', left, top, width: 400, padding: 10, zIndex: 260 }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="row" style={{ gap: 6, alignItems: 'center', marginBottom: 6 }}>
        <Icon n={item.icon} />
        <strong style={{ fontSize: 'var(--t-md)' }}>{item.label}</strong>
        <span className="muted" style={{ fontSize: 'var(--t-xs)' }}>{item.hint}</span>
      </div>
      <input aria-label="给 AI 的指令"
        ref={ref}
        value={value}
        disabled={busy}
        placeholder={item.placeholder ?? '想让它做什么？'}
        maxLength={MAX_PROMPT_CHARS}
        aria-invalid={hint ? true : undefined}
        onChange={(e) => { setValue(e.target.value); if (hint) setHint('') }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); run() }
          if (e.key === 'Escape') { e.preventDefault(); onCancel() }
        }}
        style={{ width: '100%', boxSizing: 'border-box' }}
      />
      <div className="row" style={{ justifyContent: 'space-between', marginTop: 6, fontSize: 'var(--t-xs)' }}>
        <span className={hint ? '' : 'muted'} role={hint ? 'alert' : undefined} style={hint ? { color: 'var(--del)' } : undefined}>
          {busy ? <><span className="spinner" /> {phase || '在跑…'}</> : hint || 'Enter 开始 · Esc 取消'}
        </span>
        {busy
          ? <button onClick={onCancel}>停止</button>
          : <button onClick={run}>开始</button>}
      </div>
    </div>
  )
}
