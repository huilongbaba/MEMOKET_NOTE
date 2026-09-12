import { useEffect } from 'react'
import { SHORTCUT_GROUPS } from '../shortcuts'
import { fmtShortcut } from '../util/keys'

/** ⌘/ 弹出的快捷键一览（Trilium 的 Options → Shortcuts 那张表的只读版）。 */
export default function ShortcutsPanel({ onClose }: { onClose: () => void }) {
  // Esc 关掉（capture 阶段，别让编辑器先吃掉）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose])
  return (
    <div className="palette-backdrop" onClick={onClose}>
      <div className="palette shortcuts" onClick={(e) => e.stopPropagation()}>
        <div className="row" style={{ justifyContent: 'space-between', padding: '14px 16px 6px' }}>
          <h3 style={{ margin: 0 }}><i className="bx bx-command" /> 快捷键</h3>
          <button className="icon-btn" title="关闭（Esc）" onClick={onClose}><i className="bx bx-x" /></button>
        </div>
        <div className="palette-results shortcuts-body">
          {SHORTCUT_GROUPS.map((g) => (
            <section key={g.title}>
              <p className="muted palette-group">{g.title}</p>
              {g.items.map((it) => (
                <div key={it.keys} className="shortcut-row">
                  <kbd>{fmtShortcut(it.keys)}</kbd><span>{it.what}</span>
                </div>
              ))}
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}
