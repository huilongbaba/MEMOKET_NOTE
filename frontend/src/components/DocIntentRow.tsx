/**
 * 标题下面的「写作任务」（Doc Intent，docs/agent-native-editor.md §3.1）。
 *
 * 它是智能续写的可选上下文，不是新建笔记的必填表单：默认只显示一行摘要，
 * 用户需要 agent 按明确目标执行时再展开。三个字段就地可编辑，不根据标题
 * 或文体猜任务；填写后才成为 agent 的执行约束。
 * 正文永远 `--fg`：这里三个值是正文级的内容，标签才是元信息（灰）。
 */
import { useEffect, useRef, useState } from 'react'
import { INTENT_FIELD_MAX, INTENT_LABEL, INTENT_PLACEHOLDER, WRITING_SCENARIOS, isEmptyIntent, type DocIntent, type WritingScenario } from '../util/docIntent'

const KEYS = ['goal', 'reader', 'done'] as const
const UI_LABEL = { goal: '想得到什么', reader: '给谁看', done: '必须满足' } as const

export default function DocIntentRow({ intent, onChange, checks, onOpenChecks, promptForGoal = false }: {
  intent: DocIntent
  /** 用户改了任何一个字段（已经标成 source=user） */
  onChange: (next: DocIntent) => void
  /** 「完成标准」逐条核的结果（P12 §3.1）：过了几条 / 一共几条 / 几条没过。有就在字段后面挂一个角标 */
  checks?: { ok: number; total: number; failing: number }
  /** 点角标：右栏切到「计划」看逐条 */
  onOpenChecks?: () => void
  /** 点智能续写时页面信息不足：就地展开并把光标放进目标，不弹窗、不打开聊天框。 */
  promptForGoal?: boolean
}) {
  // 本地一份：输入时逐键更新本地，失焦 / 停 800ms 才往上报（上层会落库）
  const [draft, setDraft] = useState<DocIntent>(intent)
  const [open, setOpen] = useState(promptForGoal)
  const goalRef = useRef<HTMLInputElement>(null)
  useEffect(() => { setDraft(intent) }, [intent])
  useEffect(() => {
    if (!promptForGoal) return
    setOpen(true)
    const t = setTimeout(() => goalRef.current?.focus(), 0)
    return () => clearTimeout(t)
  }, [promptForGoal])
  const [dirty, setDirty] = useState(false)
  useEffect(() => {
    if (!dirty) return
    const t = setTimeout(() => { setDirty(false); onChange({ ...draft, source: 'user' }) }, 800)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, dirty])
  const edit = (k: typeof KEYS[number], v: string) => { setDraft((d) => ({ ...d, [k]: v.slice(0, INTENT_FIELD_MAX) })); setDirty(true) }
  const commit = () => { if (dirty) { setDirty(false); onChange({ ...draft, source: 'user' }) } }
  const applyScenario = (scenario: WritingScenario) => {
    const next: DocIntent = { ...scenario.intent, source: 'user', checked: [] }
    setDirty(false)
    setDraft(next)
    onChange(next)
    setTimeout(() => goalRef.current?.focus(), 0)
  }

  const empty = isEmptyIntent(draft)

  if (!open) {
    return (
      <div className={'doc-intent doc-intent-collapsed' + (empty ? ' empty' : '')} role="group" aria-label="写作任务">
        {/* 只兼容尚未经过 resolveIntent 的旧数据；新数据不会产生 prefill。 */}
        {draft.source === 'prefill' && <span className="doc-intent-src" hidden />}
        <button type="button" className="doc-intent-toggle" onClick={() => setOpen(true)}
          title="可选。只有需要智能续写按明确目标执行时才设置；普通笔记可以直接写正文。">
          <span className="doc-intent-head">写作任务{empty ? '（可选）' : ''}</span>
          {!empty && <span className="doc-intent-summary">{draft.goal || draft.done || draft.reader}</span>}
          <span className="doc-intent-edit">{empty ? '设置' : '编辑'}</span>
        </button>
        {checks && checks.total > 0 && draft.source === 'user' && (
          <button type="button"
            className={'doc-intent-check' + (checks.failing ? ' fail' : checks.ok === checks.total ? ' ok' : '')}
            title={`完成标准 ${checks.total} 条，过了 ${checks.ok} 条。点一下在右栏「计划」逐条看。`}
            onClick={onOpenChecks}>{checks.ok}/{checks.total}</button>
        )}
      </div>
    )
  }

  return (
    <div className="doc-intent doc-intent-expanded" role="group" aria-label="写作任务">
      {draft.source === 'prefill' && <span className="doc-intent-src" hidden />}
      <div className="doc-intent-intro">
        <span className="doc-intent-head">写作任务</span>
        <span className="doc-intent-help">可选；智能续写会按这里执行，普通笔记不用填。</span>
        <button type="button" className="doc-intent-close" onClick={() => { commit(); setOpen(false) }}>收起</button>
      </div>
      {promptForGoal && !draft.goal.trim() && (
        <div className="doc-intent-guidance" role="status">
          智能续写还不知道最终要写成什么。写一句“想得到什么”，或选择一个常用工作流；其余两项可以不填。
        </div>
      )}
      <div className="doc-intent-scenarios" aria-label="常用写作工作流">
        <span className="doc-intent-scenario-label">常用工作流</span>
        {WRITING_SCENARIOS.map((scenario) => (
          <button key={scenario.id} type="button" className="doc-intent-scenario"
            title={`套用${scenario.label}约束；套用后可以继续修改`}
            onClick={() => applyScenario(scenario)}>{scenario.label}</button>
        ))}
      </div>
      <div className="doc-intent-fields">
      {KEYS.map((k) => (
        <span key={k} className="doc-intent-field">
          <label className="doc-intent-field">
            <span className="doc-intent-label">{UI_LABEL[k]}</span>
            <input
              ref={k === 'goal' ? goalRef : undefined}
              className="doc-intent-input"
              value={draft[k]}
              placeholder={INTENT_PLACEHOLDER[k]}
              aria-label={INTENT_LABEL[k]}
              onChange={(e) => edit(k, e.target.value)}
              onBlur={commit}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); (e.target as HTMLInputElement).blur() } }}
            />
          </label>
          {/* 完成标准后面挂「过了几条」：一眼知道这篇离「算完」还差什么，点一下去右栏「计划」看逐条（P12）。
              放在 label 外面：label 里的按钮会跟输入框抢点击。 */}
          {k === 'done' && checks && checks.total > 0 && !dirty && draft.source === 'user' && (
            <button type="button"
              className={'doc-intent-check' + (checks.failing ? ' fail' : checks.ok === checks.total ? ' ok' : '')}
              title={`完成标准 ${checks.total} 条，过了 ${checks.ok} 条${checks.failing ? `，${checks.failing} 条代码判了没过` : ''}。点一下在右栏「计划」逐条看。`}
              onClick={onOpenChecks}>
              {checks.ok}/{checks.total}
            </button>
          )}
        </span>
      ))}
      </div>
    </div>
  )
}
