/**
 * 右栏「计划」顶上的「完成标准」清单（P12，docs/agent-native-editor.md §3.1「完成标准是可检查的」）。
 *
 * 标题下那一行写的「完成标准」在这里变成一条条能打勾的：代码判得了的（字数、每条有日期 / 出处、各有一节…）
 * 当场判、写清为什么；判不了的给一个勾，你来判，勾了落库（`notes.intent.checked`）。
 * 判据 3「每一轮的判据要看得见」——写作的判据就摆在计划的第一格，不是 prompt 里的一句话。
 * 正文永远 `--fg`：条目原文是 `--fg`，「为什么」是元信息（灰）。
 */
import { useMemo } from 'react'
import { checkDone, doneSummary } from '../util/doneChecks'

export default function PlanChecks({ done, content, checked, onToggle, onEdit }: {
  done: string
  content: string
  /** 用户勾过的条目原文 */
  checked: string[]
  onToggle: (text: string, on: boolean) => void
  /** 「完成标准」还是空的：点一下去标题下面填 */
  onEdit?: () => void
}) {
  const items = useMemo(() => checkDone(done, content, checked), [done, content, checked])
  const sum = doneSummary(items)
  if (items.length === 0) {
    return (
      <div>
        <h2>完成标准</h2>
        <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: 0 }}>
          标题下面「这篇要干什么」里的「完成标准」还是空的。填上（分号隔开几条），这里会逐条核：字数、每条有日期 / 出处这类代码能判的当场判，其余你来勾。
          {onEdit && <> <a href="#" onClick={(e) => { e.preventDefault(); onEdit() }}>去填</a></>}
        </p>
      </div>
    )
  }
  const MARK: Record<string, { glyph: string; title: string }> = {
    pass: { glyph: '✓', title: '代码判的：达标' },
    fail: { glyph: '✗', title: '代码判的：还没达标' },
  }
  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
        <h2 style={{ margin: 0 }}>完成标准</h2>
        <span className={'plan-check-sum' + (sum.failing ? ' fail' : sum.ok === sum.total ? ' ok' : '')} title="过了几条 / 一共几条。代码判过的、你勾过的都算过。">
          {sum.ok}/{sum.total}
        </span>
      </div>
      <ul className="plan-checks">
        {items.map((it) => (
          <li key={it.text} className={'plan-check ' + it.status}>
            {it.status === 'manual' ? (
              <label className="plan-check-row">
                <input type="checkbox" checked={it.checked} onChange={(e) => onToggle(it.text, e.target.checked)}
                       title="代码判不了这条，你来判：勾了算过，记在这篇的意图里" />
                <span className="plan-check-text">{it.text}</span>
              </label>
            ) : (
              <div className="plan-check-row" title={MARK[it.status].title}>
                <span className={'plan-check-mark ' + it.status} aria-label={MARK[it.status].title}>{MARK[it.status].glyph}</span>
                <span className="plan-check-text">{it.text}</span>
              </div>
            )}
            {it.why && <div className="plan-check-why muted">{it.why}</div>}
            {it.status === 'manual' && !it.checked && <div className="plan-check-why muted">代码判不了，你来判</div>}
          </li>
        ))}
      </ul>
    </div>
  )
}
