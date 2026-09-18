import { useState } from 'react'
import { factSources } from '../api'
import type { SourceLine, TapMeta } from '../api'
import Icon from './Icon'

/**
 * Magic-tap's grounding claim ("引用知识库") is worth nothing if it can't be
 * checked -- competitor research kept surfacing "AI says it found something
 * but I can't tell if it's right" as the trust-killer. Each cited fact here
 * expands to the actual source dialogue line it came from (same data
 * /api/memory/facts/{id}/sources already serves for the facts table), not
 * just the paraphrased fact text.
 */
/** 刚写的那一段的确定性体检结果（后端 `harness/checks/tap.py`，计划 8.1）。
 *  **判了不拦**：magic tap 的定位是「点一下几秒出一段」，套完整闭环就变成
 *  智能续写了。所以这几条只是摆在来源行下面，重不重来由用户自己定。 */
function TapNotes({ notes }: { notes: string[] }) {
  if (notes.length === 0) return null
  return (
    <ul className="tap-notes">
      {notes.map((n, i) => (
        <li key={i} style={{ marginBottom: i === notes.length - 1 ? 0 : 4 }}>{n}</li>
      ))}
    </ul>
  )
}

export default function TapProvenance(
  { meta, notes = [], onDismiss }: { meta: TapMeta; notes?: string[]; onDismiss?: () => void },
) {
  const [openId, setOpenId] = useState<string | null>(null)
  // 默认折成一行：六条来源摊开在正文上方会把标题挤到屏幕外（r3 实拍），
  // 用户点一下「来源」再展开。
  const [expanded, setExpanded] = useState(false)
  const [lines, setLines] = useState<SourceLine[]>([])
  const [loading, setLoading] = useState(false)

  async function toggle(id: string) {
    if (openId === id) { setOpenId(null); return }
    setOpenId(id)
    setLoading(true)
    try { setLines(await factSources(id)) } catch { setLines([]) } finally { setLoading(false) }
  }

  if (!meta.grounded) {
    return (
      <div className="muted tap-prov" style={{ fontSize: 'var(--t-sm)' }}>
        <p style={{ margin: 0 }}>
          <span className="badge">自由续写</span> 知识库中没有相关记录
          {onDismiss && <button className="icon-btn sm" title="关闭" onClick={onDismiss}><Icon n="bx-x" /></button>}
        </p>
        <TapNotes notes={notes} />
      </div>
    )
  }

  return (
    <div className="muted tap-prov" style={{ fontSize: 'var(--t-sm)' }}>
      <p style={{ margin: '0 0 4px', display: 'flex', alignItems: 'center', gap: 6 }}>
        <span className="badge ok">引用知识库</span> 检索到 {meta.facts} 条事实（{Math.round(meta.recall_ms)} ms）
        <a className="link" onClick={() => setExpanded((v) => !v)}>
          {expanded ? '收起来源' : '查看来源'} <Icon n={(expanded ? 'bx-chevron-up' : 'bx-chevron-down')} />
        </a>
        <span style={{ flex: 1 }} />
        {onDismiss && <button className="icon-btn sm" title="关闭" onClick={onDismiss}><Icon n="bx-x" /></button>}
      </p>
      {expanded && meta.sources.slice(0, 6).map((s, i) => {
        const id = meta.fact_ids[i]
        return (
          <div key={id || i} style={{ marginBottom: 4 }}>
            <a className="link" onClick={() => id && toggle(id)}>{s}</a>
            {openId === id && (
              <div className="card" style={{ marginTop: 4 }}>
                {loading ? <span className="spinner" /> : lines.length === 0 ? (
                  <span>找不到原文</span>
                ) : lines.map((l) => (
                  <p key={l.id} style={{ margin: '2px 0' }}>
                    {l.who && <strong>{l.who}：</strong>}{l.text}
                  </p>
                ))}
              </div>
            )}
          </div>
        )
      })}
      <TapNotes notes={notes} />
    </div>
  )
}
