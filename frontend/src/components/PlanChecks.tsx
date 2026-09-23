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
          还没有设置写作任务里的「必须满足」。这是可选项；AI 会按这些要求写，可自动检查的会显示结果，其余由你确认。
          {onEdit && <> <a href="#" onClick={(e) => { e.preventDefault(); onEdit() }}>去填</a></>}
        </p>
      </div>
    )
  }
  const MARK: Record<string, { glyph: string; title: string }> = {
    pass: { glyph: '✓', title: '自动检查：已满足' },
    fail: { glyph: '✗', title: '自动检查：还没满足' },
  }
  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
        <h2 style={{ margin: 0 }}>完成标准</h2>
        <span className={'plan-check-sum' + (sum.failing ? ' fail' : sum.ok === sum.total ? ' ok' : '')} title="已确认几条 / 一共几条。自动检查通过和你确认过的都算完成。">
          {sum.ok}/{sum.total}
        </span>
      </div>
      <ul className="plan-checks">
        {items.map((it) => (
          <li key={it.text} className={'plan-check ' + it.status}>
            {it.status === 'manual' ? (
              <label className="plan-check-row">
                <input type="checkbox" checked={it.checked} onChange={(e) => onToggle(it.text, e.target.checked)}
                       title="AI 写作时会参考这条，但系统无法可靠判断是否做到；请你确认后勾选" />
                <span className="plan-check-text">{it.text}</span>
                <span className="badge">需你确认</span>
              </label>
            ) : (
              <div className="plan-check-row" title={MARK[it.status].title}>
                <span className={'plan-check-mark ' + it.status} aria-label={MARK[it.status].title}>{MARK[it.status].glyph}</span>
                <span className="plan-check-text">{it.text}</span>
              </div>
            )}
            {it.why && <div className="plan-check-why muted">{it.why}</div>}
            {it.status === 'manual' && !it.checked && <div className="plan-check-why muted">AI 会按这条写；系统无法可靠验收，完成后请你确认</div>}
          </li>
        ))}
      </ul>
    </div>
  )
}
