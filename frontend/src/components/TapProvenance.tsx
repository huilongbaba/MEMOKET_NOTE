import { useState } from 'react'
import { factSources } from '../api'
import type { SourceLine, TapMeta } from '../api'

/**
 * Magic-tap's grounding claim ("引用知识库") is worth nothing if it can't be
 * checked -- competitor research kept surfacing "AI says it found something
 * but I can't tell if it's right" as the trust-killer. Each cited fact here
 * expands to the actual source dialogue line it came from (same data
 * /api/memory/facts/{id}/sources already serves for the facts table), not
 * just the paraphrased fact text.
 */
export default function TapProvenance({ meta }: { meta: TapMeta }) {
  const [openId, setOpenId] = useState<string | null>(null)
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
      <p className="muted" style={{ fontSize: 12 }}>
        <span className="badge">自由续写</span> 知识库中没有相关记录
      </p>
    )
  }

  return (
    <div className="muted" style={{ fontSize: 12 }}>
      <p style={{ margin: '0 0 4px' }}>
        <span className="badge ok">引用知识库</span> 检索到 {meta.facts} 条事实（{meta.recall_ms} ms），点击查看原文：
      </p>
      {meta.sources.slice(0, 6).map((s, i) => {
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
    </div>
  )
}
