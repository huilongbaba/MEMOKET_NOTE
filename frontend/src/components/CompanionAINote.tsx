import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import * as api from '../api'
import type { CompanionItem } from '../desktop'
import { DESKTOP_AI_ACTIONS, eligibleDesktopSource, listCompanionAIDrafts } from '../util/companionActions'
import Icon from './Icon'
import '../desktop-ai-note.css'

const MarkdownEditor = lazy(() => import('./MarkdownEditor'))
export type CompanionAIRequest = { id: string; action: api.DesktopAIAction; sources: api.DesktopComposeSource[] }
export type CompanionAINoteState = {
  busy: boolean; hasDraft: boolean; storageError: boolean
  phase: 'idle' | 'connecting' | 'generating' | 'saving' | 'ready' | 'error'; actionLabel?: string
}
type SourceLabel = Pick<api.DesktopComposeSource, 'id' | 'title' | 'kind' | 'url'>
type Review = api.DesktopComposeResult & { sources: SourceLabel[]; action?: api.DesktopAIAction; continuationPrefix?: string }
type Draft = {
  selectedIds: string[]; instruction: string; result: Review | null; stage: 'select' | 'review'
  action: api.DesktopAIAction; snapshot?: api.DesktopComposeSource[]; autoStarted?: boolean
}
type Props = {
  items: CompanionItem[]; onClose: () => void; onStateChange?: (state: CompanionAINoteState) => void
  initialRequest?: CompanionAIRequest; closeLabel?: string
  compact?: boolean; expanded?: boolean; onExpandedChange?: (expanded: boolean) => void
  onInsert?: (content: string) => void
  /** Editor-triggered actions deliver straight into the draft: no review stage, the parent owns undo. */
  direct?: boolean
}
const EMPTY: Draft = { selectedIds: [], instruction: '', result: null, stage: 'select', action: 'organize' }
const MAX_SOURCES = 12
const MAX_CHARACTERS = 30_000
const characterCount = (value: string) => Array.from(value).length
const hasDraft = (draft: Draft) => !!(draft.selectedIds.length || draft.instruction || draft.result)
// Retain sessions even when localStorage is unavailable, including when a new explicit action replaces this panel.
const liveDrafts = new Map<string, Draft>()
const validAction = (value: unknown): value is api.DesktopAIAction => DESKTOP_AI_ACTIONS.some(({ id }) => id === value)
const validSource = (value: unknown): value is api.DesktopComposeSource => {
  if (!value || typeof value !== 'object') return false
  const source = value as Partial<api.DesktopComposeSource>
  return typeof source.id === 'string' && typeof source.title === 'string' && typeof source.text === 'string'
    && (source.kind === 'text' || (source.kind === 'link' && typeof source.url === 'string' && /^https?:\/\//i.test(source.url)))
}

function baseKey() { return `memoket.companion.ai-note.${encodeURIComponent(api.getUser())}` }
function sessionKey(request?: CompanionAIRequest) {
  const base = baseKey()
  if (request) return `${base}::request::${encodeURIComponent(request.id)}`
  const pending = listCompanionAIDrafts()
  try {
    const active = localStorage.getItem(`${base}::active-request`)
    if (active && pending.some(({ key }) => key === active)) return active
  } catch { /* Keep the default session usable. */ }
  return pending[0]?.key || base
}

function readSession(key: string, request?: CompanionAIRequest) {
  const fresh: Draft = request
    ? { ...EMPTY, action: request.action, snapshot: request.sources.map((source) => ({ ...source })), selectedIds: request.sources.map(({ id }) => id) }
    : { ...EMPTY }
  try {
    const memory = liveDrafts.get(key)
    const raw = localStorage.getItem(key)
    if (!memory && !raw) return { key, draft: fresh, error: '', restored: false }
    const value: unknown = memory || JSON.parse(raw!)
    if (!value || typeof value !== 'object') throw new Error('Invalid draft')
    const saved = value as Partial<Draft>
    const result = saved.result && typeof saved.result.title === 'string' && typeof saved.result.content === 'string'
      ? {
        title: saved.result.title, content: saved.result.content,
        sourceCount: typeof saved.result.sourceCount === 'number' ? saved.result.sourceCount : 0,
        model: typeof saved.result.model === 'string' ? saved.result.model : '',
        action: validAction(saved.result.action) ? saved.result.action : undefined,
        continuationPrefix: typeof saved.result.continuationPrefix === 'string' ? saved.result.continuationPrefix : undefined,
        sources: Array.isArray(saved.result.sources) ? saved.result.sources.filter((source) => source && typeof source.id === 'string' && typeof source.title === 'string') : [],
      } : null
    const draft: Draft = {
      selectedIds: Array.isArray(saved.selectedIds) ? [...new Set(saved.selectedIds.filter((id): id is string => typeof id === 'string'))] : [],
      instruction: typeof saved.instruction === 'string' ? saved.instruction : '',
      action: validAction(saved.action) ? saved.action : 'organize',
      snapshot: Array.isArray(saved.snapshot) ? saved.snapshot.filter(validSource) : fresh.snapshot,
      autoStarted: saved.autoStarted === true,
      result, stage: saved.stage === 'review' && result ? 'review' : 'select',
    }
    return { key, draft, error: '', restored: hasDraft(draft) }
  } catch {
    return { key, draft: liveDrafts.get(key) || fresh, error: '无法读取整理草稿。当前内容保留在本次会话，可复制或保存笔记。', restored: !!liveDrafts.get(key) }
  }
}

function errorMessage(error: unknown) {
  const text = error instanceof Error ? error.message : String(error || '')
  if (/Failed to fetch|NetworkError|Load failed/i.test(text)) return '无法连接整理服务。材料和草稿已保留，请稍后重试。'
  return text.replace(/^\d{3}\s+/, '') || '这次没有生成成功，请重试。'
}

export default function CompanionAINote(props: Props) {
  const requestIdentity = props.initialRequest?.id || ''
  const [choice, setChoice] = useState(() => ({ requestIdentity, key: sessionKey(props.initialRequest) }))
  const [, refresh] = useState(0)
  useEffect(() => {
    const changed = () => refresh((value) => value + 1)
    window.addEventListener('memoket-ai-draft-changed', changed)
    return () => window.removeEventListener('memoket-ai-draft-changed', changed)
  }, [])
  // Each explicit request has its own recoverable draft. A new action cannot overwrite an older result.
  const key = choice.requestIdentity === requestIdentity ? choice.key : sessionKey(props.initialRequest)
  const others = [...listCompanionAIDrafts(), ...[...liveDrafts].filter(([key, draft]) => (key === baseKey() || key.startsWith(`${baseKey()}::request::`)) && hasDraft(draft)).map(([key, draft]) => ({ key, title: draft.result?.title || '未完成的材料草稿' }))]
    .filter((entry, index, all) => entry.key !== key && all.findIndex(({ key }) => key === entry.key) === index)
  return <AINoteSession key={key} {...props} initialRequest={props.initialRequest && key === sessionKey(props.initialRequest) ? props.initialRequest : undefined} sessionId={key} otherDrafts={others} onResume={(nextKey) => {
    try { localStorage.setItem(`${baseKey()}::active-request`, nextKey) } catch { /* The live selection still works. */ }
    setChoice({ requestIdentity, key: nextKey })
  }} />
}

function AINoteSession({ items, onClose, onStateChange, initialRequest, closeLabel = '返回笔记', compact = false, expanded, onExpandedChange, onInsert, direct = false, sessionId, otherDrafts, onResume }: Props & { sessionId: string; otherDrafts: Array<{ key: string; title: string }>; onResume: (key: string) => void }) {
  const [session] = useState(() => readSession(sessionId, initialRequest))
  const [draft, setDraft] = useState<Draft>(session.draft)
  const [storageError, setStorageError] = useState(session.error)
  const [status, setStatus] = useState<api.DesktopAIStatus | null>(null)
  const [statusError, setStatusError] = useState('')
  const [statusRevision, setStatusRevision] = useState(0)
  const [statusLoading, setStatusLoading] = useState(true)
  const [activity, setActivity] = useState<'generating' | 'saving' | ''>('')
  const [localExpanded, setLocalExpanded] = useState(false)
  const [retryPending, setRetryPending] = useState(false)
  const [cancelled, setCancelled] = useState(false)
  const detailExpanded = expanded ?? localExpanded
  function changeExpanded(next: boolean) { setLocalExpanded(next); onExpandedChange?.(next) }
  const [reviewMode, setReviewMode] = useState<'preview' | 'edit'>('preview')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState(session.restored ? '已恢复本机整理草稿。' : '')
  const draftRef = useRef(draft)
  const activityRef = useRef(activity)
  const mountedRef = useRef(false)
  const controllerRef = useRef<AbortController | null>(null)
  const statusControllerRef = useRef<AbortController | null>(null)
  const requestSeq = useRef(0)
  const notifyRef = useRef(onStateChange)
  notifyRef.current = onStateChange
  const storageErrorRef = useRef(storageError)
  storageErrorRef.current = storageError
  const generateRef = useRef<(action: api.DesktopAIAction) => Promise<void>>(async () => {})
  const persistRef = useRef<(next: Draft) => boolean>(() => false)
  const initializedRef = useRef(false)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      controllerRef.current?.abort()
      notifyRef.current?.({ busy: false, hasDraft: hasDraft(draftRef.current), storageError: !!storageErrorRef.current, phase: 'idle' })
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    statusControllerRef.current = controller
    let live = true
    setStatusLoading(true)
    setStatusError('')
    void api.desktopAIStatus(controller.signal).then((result) => {
      if (live && !controller.signal.aborted) setStatus(result)
    }).catch((failure: unknown) => {
      if (live && !controller.signal.aborted) { setStatus(null); setStatusError(errorMessage(failure)) }
    }).finally(() => { if (live) setStatusLoading(false) })
    return () => { live = false; controller.abort() }
  }, [statusRevision])


  function updateDraft(next: Draft) {
    draftRef.current = next
    liveDrafts.set(session.key, next)
    setDraft(next)
    try {
      // Keep the attempted-request marker after save/cancel: reopening never makes another provider call.
      if (hasDraft(next) || session.key.startsWith(`${baseKey()}::request::`)) localStorage.setItem(session.key, JSON.stringify(next))
      else localStorage.removeItem(session.key)
      liveDrafts.delete(session.key)
      if (hasDraft(next)) localStorage.setItem(`${baseKey()}::active-request`, session.key)
      else if (localStorage.getItem(`${baseKey()}::active-request`) === session.key) localStorage.removeItem(`${baseKey()}::active-request`)
      window.dispatchEvent(new Event('memoket-ai-draft-changed'))
      setStorageError('')
      return true
    } catch {
      liveDrafts.set(session.key, next)
      window.dispatchEvent(new Event('memoket-ai-draft-changed'))
      setStorageError('本机草稿未保存，当前会话保留，可复制或保存笔记。')
      return false
    }
  }

  persistRef.current = updateDraft
  useEffect(() => {
    if (initialRequest && !initializedRef.current) {
      initializedRef.current = true
      persistRef.current(draftRef.current)
    }
  }, [initialRequest])

  function setBusy(next: typeof activity) {
    activityRef.current = next
    setActivity(next)
    onStateChange?.({ busy: !!next, hasDraft: hasDraft(draftRef.current), storageError: !!storageError, phase: next || (draftRef.current.result ? 'ready' : 'idle'), actionLabel: DESKTOP_AI_ACTIONS.find(({ id }) => id === draftRef.current.action)?.label })
  }

  function updateResult(patch: Partial<Pick<Review, 'title' | 'content'>>) {
    const current = draftRef.current
    if (current.result) updateDraft({ ...current, result: { ...current.result, ...patch } })
  }

  const available = [...new Map([
    ...items.map(eligibleDesktopSource).filter((source): source is api.DesktopComposeSource => !!source),
    ...(draft.snapshot || []),
  ].map((source) => [source.id, source])).values()]
  const sources = available.filter((source) => draft.selectedIds.includes(source.id))
  const characters = sources.reduce((total, source) => total + characterCount(source.title) + characterCount(source.text) + characterCount(source.url || ''), characterCount(draft.instruction))
  const missingCount = draft.selectedIds.filter((id) => !available.some((source) => source.id === id)).length
  const limitError = sources.length > MAX_SOURCES ? '一次最多选择 12 项材料。'
    : characters > MAX_CHARACTERS ? '材料与要求合计超过 30,000 字，请减少选择或缩短要求。' : ''
  const canGenerate = !!status?.configured && !statusLoading && !activity && sources.length > 0 && !limitError
  const result = draft.result
  const originalSource = result?.sources.length === 1 ? draft.snapshot?.find(({ id }) => id === result.sources[0].id) : undefined
  const continuationPrefix = result?.continuationPrefix || originalSource?.text
  // The continuation endpoint prepends the exact input; preserve the full preview, insert only its new tail.
  const insertContent = result && (result.action || draft.action) === 'continue' && continuationPrefix && result.content.startsWith(continuationPrefix)
    ? result.content.slice(continuationPrefix.length).replace(/^(?:[ \t]*\r?\n)+/, '') : result?.content || ''
  const actionLabel = DESKTOP_AI_ACTIONS.find(({ id }) => id === draft.action)?.label || '整理笔记'
  const backLabel = closeLabel.startsWith('返回') ? closeLabel : `返回${closeLabel}`
  const directRunning = !!initialRequest && !result && (statusLoading || activity === 'generating' || (!draft.autoStarted && canGenerate))
  const connecting = statusLoading && ((!!initialRequest && !draft.autoStarted && !result) || retryPending)
  const phase: CompanionAINoteState['phase'] = activity || (connecting ? 'connecting' : error || statusError || (!cancelled && !statusLoading && !status?.configured) ? 'error' : result ? 'ready' : 'idle')
  const taskBusy = !!activity || connecting
  const taskMessage = phase === 'connecting' ? '正在连接…' : phase === 'generating' ? '正在生成…' : phase === 'saving' ? '正在保存…'
    : phase === 'ready' ? '结果已就绪' : phase === 'error' ? '未完成，可重试' : notice || '材料已保留'

  useEffect(() => {
    onStateChange?.({ busy: taskBusy, hasDraft: hasDraft(draft), storageError: !!storageError, phase, actionLabel })
  }, [taskBusy, draft, storageError, phase, actionLabel, onStateChange])


  function toggleSource(id: string) {
    if (activityRef.current) return
    const current = draftRef.current
    const selectedIds = current.selectedIds.includes(id) ? current.selectedIds.filter((value) => value !== id) : [...current.selectedIds, id]
    updateDraft({ ...current, selectedIds })
    setError('')
    setNotice('')
  }

  async function generate(action = draftRef.current.action) {
    if (activityRef.current || !canGenerate) return
    if (compact) changeExpanded(false)
    setCancelled(false)
    setRetryPending(false)
    const request = ++requestSeq.current
    const controller = new AbortController()
    controllerRef.current = controller
    updateDraft({ ...draftRef.current, action, autoStarted: true })
    setBusy('generating')
    setError('')
    setNotice('')
    try {
      const response = await api.composeDesktopNote(sources, draftRef.current.instruction, controller.signal, action)
      if (!mountedRef.current || request !== requestSeq.current || controller.signal.aborted) return
      if (!response.title?.trim() || !response.content?.trim()) throw new Error('Gemini 没有返回完整笔记，原草稿已保留。')
      if (direct && onInsert) {
        // The continuation endpoint echoes the exact input first; only the new tail belongs in the draft.
        const prefix = action === 'continue' ? sources.filter(({ text }) => text).map(({ text }) => text).join('\n\n') : ''
        const tail = action === 'continue' && prefix && response.content.startsWith(prefix) ? response.content.slice(prefix.length).replace(/^(?:[ \t]*\r?\n)+/, '') : response.content
        updateDraft({ ...EMPTY, autoStarted: true, action, snapshot: draftRef.current.snapshot })
        onInsert(tail)
        return
      }
      updateDraft({
        ...draftRef.current, stage: 'review',
        result: { ...response, action, sources: sources.map(({ id, title, kind, url }) => ({ id, title, kind, url })), continuationPrefix: action === 'continue' ? sources.filter(({ text }) => text).map(({ text }) => text).join('\n\n') : undefined },
      })
      setReviewMode('preview')
    } catch (failure) {
      if (mountedRef.current && request === requestSeq.current && !controller.signal.aborted) setError(errorMessage(failure))
    } finally {
      if (mountedRef.current && request === requestSeq.current) { controllerRef.current = null; setBusy('') }
    }
  }
  generateRef.current = generate

  useEffect(() => {
    if (canGenerate && (retryPending || (initialRequest && !draftRef.current.autoStarted && !draftRef.current.result))) {
      void generateRef.current(initialRequest?.action || draftRef.current.action)
    }
  }, [initialRequest, canGenerate, retryPending])

  function retryGeneration() {
    if (activityRef.current) return
    if (canGenerate) void generate()
    else if (!statusLoading && sources.length > 0 && !limitError) {
      setCancelled(false)
      setRetryPending(true)
      setStatusRevision((value) => value + 1)
    } else changeExpanded(true)
  }

  function cancelGeneration() {
    requestSeq.current++
    setCancelled(true)
    setRetryPending(false)
    if (connecting) {
      statusControllerRef.current?.abort()
      setStatusLoading(false)
      updateDraft({ ...draftRef.current, autoStarted: true })
    }
    controllerRef.current?.abort()
    controllerRef.current = null
    setBusy('')
    setNotice('已停止等待。材料和已有草稿仍保留。')
    setError('')
  }

  async function copyResult() {
    if (!draftRef.current.result) return
    try {
      await navigator.clipboard.writeText(draftRef.current.result.content)
      if (mountedRef.current) setNotice('已复制结果。')
    } catch {
      if (mountedRef.current) setError('无法写入剪贴板，请切换到编辑后手动复制。')
    }
  }

  async function save() {
    const current = draftRef.current
    if (activityRef.current || !current.result?.title.trim() || !current.result.content.trim()) return
    setBusy('saving')
    setError('')
    setNotice('')
    try {
      await api.createNote(current.result.title.trim(), current.result.content)
      if (!mountedRef.current) return
      const cleared = updateDraft({ ...EMPTY, autoStarted: current.autoStarted, action: current.action, snapshot: current.snapshot })
      setNotice(cleared ? '已保存笔记，原暂存材料保留。' : '笔记已保存，但本机旧草稿未能清除。')
    } catch (failure) {
      if (mountedRef.current) setError(`未保存，生成稿仍保留。${errorMessage(failure)}`)
    } finally {
      if (mountedRef.current) setBusy('')
    }
  }

  return (
    <section className={'dc-ai-note' + (compact ? ' dc-ai-note-compact' : '')} aria-label="整理成笔记" onKeyDown={(event) => {
      if (event.key === 'Escape' && compact && detailExpanded) { event.preventDefault(); event.stopPropagation(); changeExpanded(false) }
      else if (event.key === 'Escape' && !compact && activityRef.current) { event.preventDefault(); event.stopPropagation() }
      if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && !event.nativeEvent.isComposing) {
        event.preventDefault(); event.stopPropagation()
        if (draft.stage === 'review') void save()
        else void generate()
      }
    }}>
      {compact && <div className="dc-ai-taskbar" data-phase={phase}>
        <span className="dc-ai-task-mark" aria-hidden="true"><Icon n={phase === 'ready' ? 'bx-check' : phase === 'error' ? 'bx-info-circle' : taskBusy ? 'bx-loader-circle' : 'bx-brain'} /></span>
        <div className="dc-ai-task-label"><strong>{actionLabel}</strong><span role="status" aria-live="polite" title={error || statusError || storageError || taskMessage}>{taskMessage}</span></div>
        {taskBusy && phase !== 'saving' && <button className="dc-ai-task-cancel" aria-label="取消生成" title="停止这次生成，保留材料" onClick={cancelGeneration}><Icon n="bx-stop-circle" /></button>}
        {!taskBusy && (phase === 'error' || (!result && draft.autoStarted)) && <button onClick={retryGeneration}>重试</button>}
        <button aria-expanded={detailExpanded} aria-label={detailExpanded ? '收起 AI 详情' : result ? '查看结果' : '查看 AI 详情'} onClick={() => changeExpanded(!detailExpanded)}>{detailExpanded ? '收起' : result ? '查看结果' : taskBusy ? '详情' : '查看材料'}</button>
      </div>}
      {(!compact || detailExpanded) && <div className={compact ? 'dc-ai-drawer' : 'dc-ai-detail'}>
      {(!compact || otherDrafts.length > 0) && <header className="dc-ai-header">
        {!compact && <><button type="button" title={`${backLabel}，保留整理草稿`} onClick={onClose}><Icon n="bx-left-arrow-alt" />{backLabel}</button>
        <h2>{draft.stage === 'review' ? actionLabel : '处理已有材料'}</h2></>}
        {otherDrafts.length > 0 && <select className="dc-ai-drafts" aria-label="恢复其他生成稿" value="" disabled={!!activity} onChange={(event) => { if (event.target.value) onResume(event.target.value) }}><option value="">其他草稿 · {otherDrafts.length}</option>{otherDrafts.map((entry) => <option key={entry.key} value={entry.key}>{entry.title}</option>)}</select>}
        <span className="dc-ai-provider">Gemini</span>
      </header>}

      {draft.stage === 'review' && result ? (
        <div className="dc-ai-review">
          <div className="dc-ai-review-meta">
            <div className="dc-ai-review-tabs" role="tablist" aria-label="结果显示方式">
              <button role="tab" aria-selected={reviewMode === 'preview'} onClick={() => setReviewMode('preview')}>预览</button>
              <button role="tab" aria-selected={reviewMode === 'edit'} onClick={() => setReviewMode('edit')}>编辑</button>
            </div>
            <span>{result.sourceCount} 项来源 · 待保存</span>
            <button disabled={!!activity} title="调整材料，保留当前生成稿" onClick={() => updateDraft({ ...draftRef.current, stage: 'select' })}>修改选材</button>
          </div>
          {reviewMode === 'preview'
            ? <h3 className="dc-ai-preview-title" aria-label="整理笔记标题" title={result.title}>{result.title}</h3>
            : <input className="dc-ai-title" aria-label="整理笔记标题" value={result.title} maxLength={180} disabled={!!activity} onChange={(event) => updateResult({ title: event.target.value })} />}
          {reviewMode === 'preview' ? <div className="dc-ai-rendered" role="tabpanel" aria-label="生成结果预览"><Suspense fallback={<pre className="dc-ai-fallback">{result.content}</pre>}><MarkdownEditor content={result.content} readOnly scrollPad={false} /></Suspense></div>
            : <textarea className="dc-ai-body" aria-label="整理笔记正文" value={result.content} disabled={!!activity} onChange={(event) => updateResult({ content: event.target.value })} />}
          <footer className="dc-ai-footer"><details className="dc-ai-source-proof"><summary title={storageError ? '草稿暂未保存在本机' : '草稿保留在本机；展开查看使用的材料'}>这次使用的来源</summary><ul>{result.sources.map((source) => <li key={source.id}>{source.title}{source.kind === 'link' && <span> · 链接摘录</span>}</li>)}</ul></details><div className="dc-ai-result-actions">{onInsert && <button className="dc-primary" disabled={!!activity || !insertContent.trim()} title={!insertContent.trim() ? '没有新的续写内容可插入' : '将这份结果插入当前正文，保留生成稿'} onClick={() => { onInsert(insertContent); changeExpanded(false); setNotice('已插入正文，生成稿保留。') }}>插入正文<Icon n="bx-plus" /></button>}<button disabled={!!activity} title="复制生成的 Markdown 内容" onClick={() => void copyResult()}><Icon n="bx-copy" />复制</button><button className="dc-primary" disabled={!!activity || !result.title.trim() || !result.content.trim()} title={!result.title.trim() || !result.content.trim() ? '填写标题和正文后即可保存' : '保存这份笔记，保留原暂存材料'} onClick={() => void save()}>{activity === 'saving' ? '正在保存…' : '保存笔记'}<Icon n="bx-check" /></button></div></footer>
        </div>
      ) : directRunning ? (
        <div className="dc-ai-running" aria-label="正在处理材料">
          <span className="dc-ai-running-mark"><Icon n={DESKTOP_AI_ACTIONS.find(({ id }) => id === draft.action)?.icon || 'bx-note'} /></span>
          <h3>{actionLabel}</h3>
          <p role="status">{statusLoading ? '正在连接 Gemini…' : '正在处理已选材料…'}</p>
          <div className="dc-ai-running-source"><strong>{sources[0]?.title || '已选材料'}{sources.length > 1 && ` 等 ${sources.length} 项`}</strong><p>{sources[0]?.text || sources[0]?.url}</p><span>{characters.toLocaleString()} 字 · 仅发送这些材料</span></div>
          {activity === 'generating' && <button className="dc-ai-cancel" onClick={cancelGeneration}><Icon n="bx-stop-circle" />取消生成</button>}
        </div>
      ) : (
        <div className="dc-ai-selection">
          <p className="dc-ai-disclosure" title="仅发送所选文字、链接摘录与文件文字节选，不读取其他文件、照片或网页全文。">所选内容将发送给 Gemini。</p>
          <div className="dc-ai-status" role="status">
            {statusLoading ? '正在确认 Gemini 配置…' : statusError ? <><span>{statusError}</span><button disabled={!!activity} title={activity ? '请等待当前操作完成' : '重新检查 Gemini 配置'} onClick={() => setStatusRevision((value) => value + 1)}>重试</button></> : !status?.configured ? <><span>Gemini 尚未配置，配置完成后可刷新。</span><button disabled={!!activity} title={activity ? '请等待当前操作完成' : '重新检查 Gemini 配置'} onClick={() => setStatusRevision((value) => value + 1)}>刷新</button></> : <span title={status.model}>Gemini 已就绪</span>}
          </div>
          {available.length ? (
            <div className="dc-ai-sources" aria-label="选择要处理的材料">
              {available.map((source) => <label className={'dc-ai-source' + (draft.selectedIds.includes(source.id) ? ' dc-ai-source-selected' : '')} key={source.id}>
                <input type="checkbox" aria-label={`选择 ${source.title}`} checked={draft.selectedIds.includes(source.id)} disabled={!!activity || (!draft.selectedIds.includes(source.id) && sources.length >= MAX_SOURCES)} title={sources.length >= MAX_SOURCES && !draft.selectedIds.includes(source.id) ? '一次最多选择 12 项，请先取消一项' : '仅发送勾选的材料'} onChange={() => toggleSource(source.id)} />
                <span><strong>{source.title}</strong><small>{source.text || source.url}</small><em>{source.kind === 'link' ? '链接摘录' : '文字'} · {characterCount(source.text)} 字</em></span>
              </label>)}
            </div>
          ) : <div className="dc-ai-empty"><Icon n="bx-note" /><strong>先暂存一段文字或链接</strong><p>也可以选用已提取文字的文件节选。</p><button title="返回并添加材料" onClick={onClose}>{backLabel}</button></div>}
          {!!missingCount && <p className="dc-ai-hint">之前选择的 {missingCount} 项已不在暂存架，本次不会发送。</p>}
          <details className="dc-ai-options"><summary>补充要求{draft.instruction.trim() ? ' · 已填写' : '（可选）'}</summary><label className="dc-ai-instruction">整理要求（会一同发送）<textarea aria-label="整理要求" placeholder="例如：保留数字，突出下一步。" value={draft.instruction} maxLength={MAX_CHARACTERS * 2} rows={2} disabled={!!activity} onChange={(event) => updateDraft({ ...draftRef.current, instruction: event.target.value })} /></label></details>
          <div className="dc-ai-action-control">
            <select aria-label="AI 操作" value={draft.action} disabled={!!activity} title={activity ? '请等待当前操作完成' : '选择如何处理这些材料'} onChange={(event) => { if (validAction(event.target.value)) updateDraft({ ...draftRef.current, action: event.target.value }) }}>
              {DESKTOP_AI_ACTIONS.map((action) => <option key={action.id} value={action.id}>{action.label}</option>)}
            </select>
            <button className="dc-primary" disabled={!canGenerate} title={!status?.configured ? '请先配置 Gemini' : !sources.length ? '先选择至少一项材料' : limitError || `执行${actionLabel}`} onClick={() => void generate()}>执行<Icon n="bx-right-arrow-alt" /></button>
          </div>
          {limitError && <p className="dc-ai-error" role="alert">{limitError}</p>}
          <footer className="dc-ai-footer"><span>已选 {sources.length}/{MAX_SOURCES} · {characters.toLocaleString()} 字</span>{activity === 'generating' && <button className="dc-ai-cancel" onClick={cancelGeneration}><Icon n="bx-stop-circle" />取消生成</button>}</footer>
          {activity === 'generating' && <p className="dc-ai-hint" role="status">Gemini 正在{actionLabel}…</p>}
          {result && <button className="dc-ai-return" disabled={!!activity} title={activity ? '请先取消生成或等待完成' : '继续编辑之前保留的生成稿'} onClick={() => updateDraft({ ...draftRef.current, stage: 'review' })}>返回已有生成稿</button>}
        </div>
      )}
      {(error || storageError) && <p className="dc-ai-error" role="alert"><Icon n="bx-info-circle" />{error || storageError}</p>}
      {notice && <p className="dc-ai-notice" role="status">{notice}</p>}
      </div>}
    </section>
  )
}
