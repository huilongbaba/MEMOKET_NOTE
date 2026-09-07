import { useState } from 'react'
import { factSources } from '../api'
import type { SourceLine, VerifyFinding } from '../api'

const VERDICT_STYLE: Record<VerifyFinding['verdict'], string> = {
  矛盾: 'badge', // reuse the plain badge styling but color via inline style below
  支持: 'badge ok',
  无法判断: 'badge',
}

/** 校验结果：跟 TapProvenance 一样的"点击展开原文"模式，判断没有可回溯的
 * 证据就只是模型的又一句自称——尤其是"矛盾"这种会让用户重新怀疑自己写的
 * 内容的判断，必须能让用户自己核实，不能只信一句话结论。 */
export default function VerifyPanel({ findings, onClose }: {
  findings: VerifyFinding[]
  onClose: () => void
}) {
  const [openId, setOpenId] = useState<string | null>(null)
  const [lines, setLines] = useState<SourceLine[]>([])
  const [loading, setLoading] = useState(false)

  async function toggle(factId: string) {
    if (openId === factId) { setOpenId(null); return }
    setOpenId(factId)
    setLoading(true)
    try { setLines(await factSources(factId)) } catch { setLines([]) } finally { setLoading(false) }
  }

  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2 style={{ margin: 0 }}>校验结果</h2>
        <button onClick={onClose}>✕</button>
      </div>
      {findings.length === 0 && (
        <p className="muted">没有找到能支持或反驳这段内容的记录——不代表内容没问题，只是知识库里没有相关信息。</p>
      )}
      {findings.map((f, i) => (
        <div className="card" key={i}>
          <span
            className={VERDICT_STYLE[f.verdict]}
            style={f.verdict === '矛盾' ? { background: 'var(--del-bg)', color: 'var(--del)' } : undefined}
          >
            {f.verdict}
          </span>
          <p style={{ margin: '6px 0 0' }}>{f.reason}</p>
          {f.fact_id && (
            <>
              <a className="link" style={{ fontSize: 12 }} onClick={() => toggle(f.fact_id)}>
                依据：{f.fact_text} {openId === f.fact_id ? '（收起原文）' : '（查看原文）'}
              </a>
              {openId === f.fact_id && (
                <div className="card" style={{ marginTop: 4 }}>
                  {loading ? <span className="spinner" /> : lines.length === 0 ? (
                    <span className="muted">找不到原文</span>
                  ) : lines.map((l) => (
                    <p key={l.id} style={{ margin: '2px 0', fontSize: 12 }}>
                      {l.who && <strong>{l.who}：</strong>}{l.text}
                    </p>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      ))}
    </div>
  )
}
