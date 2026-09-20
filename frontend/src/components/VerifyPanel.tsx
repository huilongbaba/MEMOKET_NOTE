import { useState } from 'react'
import { factSources } from '../api'
import type { SourceLine, VerifyFinding } from '../api'
import Icon from './Icon'

const VERDICT_STYLE: Record<VerifyFinding['verdict'], string> = {
  矛盾: 'badge', // reuse the plain badge styling but color via inline style below
  支持: 'badge ok',
  无法判断: 'badge',
}

/** 一条 finding 都没有时说哪一句（P37 #2 / P35 #3）。
 *
 * **原来只有一句**：「没有找到能支持或反驳这段内容的记录——不代表内容没问题，
 * 只是知识库里没有相关信息。」P35 实拍它在满库下说了假话：terrence 20417 条事实，
 * 词法召回**真的回了 1 条**，模型答得不合形状，界面却说「知识库里没有相关信息」。
 *
 * 三种来历，各说各的。**说不清的那一档宁可说「不知道」，不许替对方背锅**：
 *   · `unparsed` —— 模型没按格式答。查了几条要说出来，不然又成了「知识库里没有」。
 *   · `checked === 0` —— 真的一条沾边的记录都没有。原来那句话在这一档是对的。
 *   · 其余 —— 翻过 N 条，模型逐条看完没话说。这是个正当答案，但也不是「没有记录」。
 *
 * 纯函数，导出是为了能不挂 DOM 直接钉住这三句（`__tests__/p37.test.ts`）。 */
export function emptyVerifyLine(checked: number, unparsed: boolean): string {
  if (unparsed) {
    return checked > 0
      ? `模型这次没按要求的格式答，这一段没能核成——知识库里有 ${checked} 条相关记录，再点一次「校验」试试。`
      : '模型这次没按要求的格式答，这一段没能核成——再点一次「校验」试试。'
  }
  if (checked <= 0) {
    return '没有找到能支持或反驳这段内容的记录——不代表内容没问题，只是知识库里没有相关信息。'
  }
  return `翻过知识库里 ${checked} 条相关记录，没有一条能支持或反驳这段内容——不代表内容没问题。`
}

/** 校验结果：跟 TapProvenance 一样的"点击展开原文"模式，判断没有可回溯的
 * 证据就只是模型的又一句自称——尤其是"矛盾"这种会让用户重新怀疑自己写的
 * 内容的判断，必须能让用户自己核实，不能只信一句话结论。 */
export default function VerifyPanel({ findings, checked = 0, unparsed = false, onClose }: {
  findings: VerifyFinding[]
  checked?: number
  unparsed?: boolean
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
        <button className="icon-btn" title="关闭（Esc）" aria-label="关闭" onClick={onClose}><Icon n="bx-x" /></button>
      </div>
      {findings.length === 0 && (
        <p className="muted">{emptyVerifyLine(checked, unparsed)}</p>
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
              <a className="link" style={{ fontSize: 'var(--t-sm)' }} onClick={() => toggle(f.fact_id)}>
                依据：{f.fact_text} {openId === f.fact_id ? '（收起原文）' : '（查看原文）'}
              </a>
              {openId === f.fact_id && (
                <div className="card" style={{ marginTop: 4 }}>
                  {loading ? <span className="spinner" /> : lines.length === 0 ? (
                    <span className="muted">找不到原文</span>
                  ) : lines.map((l) => (
                    <p key={l.id} style={{ margin: '2px 0', fontSize: 'var(--t-sm)' }}>
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
