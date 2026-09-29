/** 灵动岛 · 会话：在岛上直接和 Claude Code 说话。
 *
 *  CLI 在主进程里无头地跑，这里只看 companion-types 里归一化过的 `AgentTurnEvent`：
 *  一次只有一轮在进行，事件按 turnId 认领，别的轮一概不理。回复可以一键引用到正在写的笔记、
 *  存成一篇新笔记或复制；智能体写出的文件一行一个，可以放进暂存箱。
 *
 *  焦点纪律与待办面板相同：**只在 `focusRequested` 变化时**把光标放进输入框——悬停展开不许抢焦点。
 *  Esc：有字先清字，没字交给岛收起；两条路都不让岛的 Esc 再跑一遍。 */
import { useCallback, useEffect, useImperativeHandle, useRef, useState, type KeyboardEvent, type RefObject } from 'react'
import type { AgentArtifact, AgentBridge, AgentMessage, AgentSession, AgentStatus, AgentTurnEvent } from '../desktop'
import Icon from './Icon'
import { fmtShortcut } from '../util/keys'
import '../companion-session.css'

type Props = {
  bridge: AgentBridge | undefined
  /** 面板正在岛上显示（不是藏在别的标签后面）。 */
  active: boolean
  /** 岛在键盘进入这个面板时递增：把光标放进输入框。 */
  focusRequested: number
  /** 输入框为空时按 Esc：交给岛收起。 */
  onEscape: () => void
  /** 把一段回复插进正在写的笔记。 */
  onInsert: (text: string) => void
  /** 把一段回复存成新笔记；成功返回 true。 */
  onSaveNote: (text: string) => Promise<boolean>
  /** 一轮开始 / 结束：收起后岛上要显示「Claude 思考中」。 */
  onRunningChange: (running: boolean) => void
  /** 岛把拖进来的文件、拖进来的文字交给这块面板。 */
  handleRef?: RefObject<CompanionSessionHandle | null>
}

/** 岛能对这块面板做的两件事：把文件带上（复制进工作目录，随下一句一起发），把一段文字放进输入框。 */
export type CompanionSessionHandle = {
  attach(files: File[]): Promise<boolean>
  draft(text: string): void
}

/** 正在进行的那一轮：正文一段段流进来，工具活动只留最新一行。 */
type Pending = { turnId: string; text: string; artifacts: AgentArtifact[]; activity: string; claimed: boolean }
type RowNote = { id: string; text: string }

const MODEL_KEY = 'memoket.companion.agent.model'
const SAVED_NOTE_MS = 3000
const COPIED_MS = 2000
export const MISSING_TITLE = '没找到 Claude Code'
export const LOGIN_TITLE = 'Claude Code 还没登录'
export const LOGIN_NOTE = '在终端运行 claude 并完成登录，然后回来重试。'
export const LOGIN_HINT = '上次没登录成功。登录好了，直接发一句试试。'
export const ATTACH_ONLY_PROMPT = '看看这些附件，告诉我里面有什么。'
export const WEB_ONLY_NOTE = '会话只在桌面版可用。'

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error || '')) || '操作没有完成，请重试。'
const lastSegment = (path: string) => path.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || path
const emptyPending = (turnId: string, claimed = false): Pending => ({ turnId, text: '', artifacts: [], activity: '', claimed })
function readModel() { try { return localStorage.getItem(MODEL_KEY) || '' } catch { return '' } }
function writeModel(model: string) {
  try { if (model) localStorage.setItem(MODEL_KEY, model); else localStorage.removeItem(MODEL_KEY) }
  catch { /* 记不住就下次再选：不值得打断对话 */ }
}
/** 「14:05」「9月21日」「2025/12/3」：够认出是哪一场就行。 */
export function shortDate(iso: string, now = new Date()): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  if (d.toDateString() === now.toDateString()) return `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
  if (d.getFullYear() === now.getFullYear()) return `${d.getMonth() + 1}月${d.getDate()}日`
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`
}
const withShelved = (artifacts: AgentArtifact[] | undefined, path: string) => artifacts?.map(a => a.path === path ? { ...a, shelved: true } : a)

export default function CompanionSession({ bridge, active, focusRequested, onEscape, onInsert, onSaveNote, onRunningChange, handleRef }: Props) {
  const [status, setStatus] = useState<AgentStatus | null>(null)
  const [statusError, setStatusError] = useState('')
  const [loginRequired, setLoginRequired] = useState(false)
  const [sessions, setSessions] = useState<AgentSession[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [pending, setPending] = useState<Pending | null>(null)
  const [sending, setSending] = useState(false)
  const [draft, setDraft] = useState('')
  const [model, setModel] = useState(readModel)
  const [recentOpen, setRecentOpen] = useState(false)
  const [problem, setProblem] = useState('')
  const [rowNote, setRowNote] = useState<RowNote | null>(null)
  const [shelving, setShelving] = useState('')
  const [shelveErrors, setShelveErrors] = useState<Record<string, string>>({})
  /** 要带上的文件：已经复制进工作目录，随下一句一起发。 */
  const [attachments, setAttachments] = useState<AgentArtifact[]>([])
  const [savingId, setSavingId] = useState('')
  /** 只给读屏器听的一行：临时提示都从这里播报一遍。 */
  const [announce, setAnnounce] = useState('')
  /** 用户在「没登录」那块点过重试：先把输入框还给他，登录成功与否由下一轮说了算。 */
  const retriedLogin = useRef(false)
  const modelRef = useRef('')
  const live = useRef(false)
  const pendingRef = useRef<Pending | null>(null)
  /** send() 还没回来时先到的事件按它的 turnId 认领——只有这块面板会发起一轮。 */
  const awaitingTurn = useRef(false)
  /** 最近结束的那一轮：一轮在 send() 回来之前就跑完了（比如当场报「未登录」），不能再给它开一个等不到头的进行中。 */
  const finishedTurn = useRef('')
  const sessionIdRef = useRef<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const recentRef = useRef<HTMLDivElement>(null)
  const recentTrigger = useRef<HTMLButtonElement>(null)
  /** 读者还贴着底部才跟着滚；往上翻着看的时候，流进来的字不许把视线拽走。 */
  const stickToBottom = useRef(true)
  const noteTimer = useRef(0)
  const onRunningRef = useRef(onRunningChange)
  onRunningRef.current = onRunningChange
  const running = sending || pending !== null

  const patchPending = useCallback((fn: (current: Pending | null) => Pending | null) => {
    pendingRef.current = fn(pendingRef.current)
    setPending(pendingRef.current)
  }, [])

  const refreshSessions = useCallback(async () => {
    if (!bridge) return
    try {
      const list = await bridge.sessions()
      if (live.current) setSessions(list)
    } catch { /* 列表读不到不影响正在进行的对话 */ }
  }, [bridge])

  const loadStatus = useCallback(async () => {
    if (!bridge) return
    setStatusError('')
    try {
      const next = await bridge.status()
      if (!live.current) return
      setStatus(next)
      if (next.loggedIn === false) { if (!retriedLogin.current) setLoginRequired(true) }
      else setLoginRequired(false)
      // 记住的模型这台桥不认了：清掉，别让每一句都被「无效的模型」挡回来。
      if (modelRef.current && !next.models.some(m => m.id === modelRef.current)) { setModel(''); writeModel('') }
      // 渲染层重载时主进程可能还有一轮在跑：认领它，事件继续流进来，停止按钮也在。
      if (next.runningTurnId && !pendingRef.current) patchPending(() => emptyPending(next.runningTurnId!, true))
    } catch (error) {
      if (live.current) setStatusError(errorText(error))
    }
  }, [bridge, patchPending])

  const handleEvent = useCallback((event: AgentTurnEvent) => {
    if (pendingRef.current?.turnId !== event.turnId) {
      if (!awaitingTurn.current || pendingRef.current) return
      patchPending(() => emptyPending(event.turnId))
    }
    switch (event.type) {
      case 'session':
        sessionIdRef.current = event.sessionId
        setSessionId(event.sessionId)
        void refreshSessions()
        break
      case 'delta':
        patchPending(p => p && { ...p, text: p.text + event.text })
        break
      case 'activity':
        patchPending(p => p && { ...p, activity: event.label })
        break
      case 'artifact':
        patchPending(p => p && { ...p, artifacts: [...p.artifacts.filter(a => a.path !== event.artifact.path), event.artifact] })
        break
      case 'turn-end': {
        awaitingTurn.current = false
        finishedTurn.current = event.turnId
        const finished = pendingRef.current
        patchPending(() => null)
        // 这一轮进行中就放进暂存箱的文件，落定后仍然是「已放入」。
        const shelvedPaths = new Set((finished?.artifacts ?? []).filter(a => a.shelved).map(a => a.path))
        const message = shelvedPaths.size ? { ...event.message, artifacts: event.message.artifacts?.map(a => shelvedPaths.has(a.path) ? { ...a, shelved: true } : a) } : event.message
        sessionIdRef.current = event.sessionId
        setSessionId(event.sessionId)
        if (finished?.claimed && bridge) {
          // 重载后认领来的一轮：本地没有它的问题和更早的对话，整份记录从主进程拿。
          bridge.transcript(event.sessionId)
            .then(list => { if (live.current) setMessages(list.length ? list : [message]) })
            .catch(() => { if (live.current) setMessages(prev => [...prev, message]) })
        } else setMessages(prev => [...prev, message])
        void refreshSessions()
        break
      }
      case 'turn-error': {
        awaitingTurn.current = false
        finishedTurn.current = event.turnId
        const partial = pendingRef.current
        patchPending(() => null)
        // 能拿到的部分留下，原因写在它底下；没拿到一个字也留一条，不然这一轮像没发生过。
        setMessages(prev => [...prev, { id: `${event.turnId}-error`, role: 'assistant', text: partial?.text ?? '', at: new Date().toISOString(), ...(partial?.artifacts.length ? { artifacts: partial.artifacts } : {}), error: event.message }])
        if (event.sessionId) { sessionIdRef.current = event.sessionId; setSessionId(event.sessionId) }
        if (event.notLoggedIn) { setLoginRequired(true); setStatus(s => s && { ...s, loggedIn: false, reason: event.message }) }
        break
      }
      default:
        break
    }
  }, [bridge, patchPending, refreshSessions])

  useEffect(() => {
    if (!bridge) return
    live.current = true
    void loadStatus()
    void refreshSessions()
    const unsubscribe = bridge.onEvent(handleEvent)
    return () => { live.current = false; unsubscribe() }
  }, [bridge, loadStatus, refreshSessions, handleEvent])

  useEffect(() => { onRunningRef.current(running) }, [running])
  useEffect(() => { modelRef.current = model }, [model])
  useEffect(() => { setAnnounce(problem || rowNote?.text || Object.values(shelveErrors).at(-1) || '') }, [problem, rowNote, shelveErrors])

  const attach = useCallback(async (files: File[]) => {
    if (!bridge || !files.length) return false
    try {
      const result = await bridge.attach(files)
      if (!live.current) return false
      if (result.attachments?.length) setAttachments(list => [...list, ...result.attachments!.filter(a => !list.some(x => x.path === a.path))])
      if (!result.ok) { setProblem(result.error || '没能带上这些文件。'); return false }
      setProblem('')
      return true
    } catch (error) {
      if (live.current) setProblem(errorText(error))
      return false
    }
  }, [bridge])
  useImperativeHandle(handleRef, () => ({
    attach,
    draft: text => { setDraft(current => current ? `${current}\n${text}` : text); textareaRef.current?.focus() },
  }), [attach])
  useEffect(() => () => window.clearTimeout(noteTimer.current), [])
  useEffect(() => { if (focusRequested) textareaRef.current?.focus() }, [focusRequested])

  // 新字流进来、回复落定、切回这个面板：贴着底部的读者跟到底。
  useEffect(() => {
    const log = logRef.current
    if (log && stickToBottom.current) log.scrollTop = log.scrollHeight
  }, [messages, pending, active])

  useEffect(() => {
    if (!recentOpen) return
    ;(recentRef.current?.querySelector<HTMLElement>('[role="menuitem"]') ?? recentRef.current)?.focus()
    const outside = (event: PointerEvent) => {
      if (!recentRef.current?.contains(event.target as Node) && !recentTrigger.current?.contains(event.target as Node)) setRecentOpen(false)
    }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [recentOpen])

  function note(id: string, text: string, ms: number) {
    window.clearTimeout(noteTimer.current)
    setRowNote({ id, text })
    noteTimer.current = window.setTimeout(() => setRowNote(null), ms)
  }

  /** 发出去的模型 id：记住的那个不在列表里就算「默认」，界面上显示的和请求里的是同一个。 */
  function resolvedModel() {
    return model === '' || (status?.models ?? []).some(m => m.id === model) ? model : ''
  }

  async function send() {
    const typed = draft.trim()
    const files = attachments
    const text = typed || (files.length ? ATTACH_ONLY_PROMPT : '')
    if (!bridge || !text || running) return
    setDraft('')
    setAttachments([])
    setProblem('')
    setSending(true)
    awaitingTurn.current = true
    stickToBottom.current = true
    // 问题先上屏，回复才能排在它后面——哪怕这一轮在 send() 回来之前就结束了。发不出去再撤。
    const asked: AgentMessage = { id: `user-${Date.now()}`, role: 'user', text, at: new Date().toISOString(), ...(files.length ? { artifacts: files } : {}) }
    setMessages(prev => [...prev, asked])
    const undo = () => {
      awaitingTurn.current = false
      patchPending(() => null)
      setMessages(prev => prev.filter(m => m !== asked))
      setDraft(typed)
      setAttachments(files)
    }
    try {
      const result = await bridge.send({ sessionId: sessionIdRef.current, text, model: resolvedModel(), ...(files.length ? { attachments: files.map(a => a.path) } : {}) })
      if (!live.current) return
      if (!result.ok) { undo(); setProblem(result.error || '没能发出去，请重试。'); return }
      if (result.sessionId) { sessionIdRef.current = result.sessionId; setSessionId(result.sessionId) }
      const turnId = result.turnId
      if (turnId && turnId !== finishedTurn.current && pendingRef.current?.turnId !== turnId) patchPending(() => emptyPending(turnId))
    } catch (error) {
      if (live.current) { undo(); setProblem(errorText(error)) }
    } finally {
      if (live.current) setSending(false)
    }
  }

  function interrupt() {
    if (!bridge) return
    bridge.interrupt().then(result => { if (live.current && !result.ok && result.error) setProblem(result.error) })
      .catch(error => { if (live.current) setProblem(errorText(error)) })
  }

  function newSession() {
    if (running) return
    sessionIdRef.current = null
    setSessionId(null)
    setMessages([])
    setProblem('')
    setRecentOpen(false)
    stickToBottom.current = true
    textareaRef.current?.focus()
  }

  async function openSession(id: string) {
    if (!bridge) return
    setRecentOpen(false)
    if (running) { setProblem('这一轮还在进行，等它结束再切换会话。'); return }
    try {
      const list = await bridge.transcript(id)
      if (!live.current) return
      sessionIdRef.current = id
      setSessionId(id)
      setMessages(list)
      setProblem('')
      stickToBottom.current = true
    } catch (error) {
      if (live.current) setProblem(errorText(error))
    }
    recentTrigger.current?.focus()
  }

  function toggleRecent() {
    if (!recentOpen) void refreshSessions()
    setRecentOpen(open => !open)
  }

  async function saveNote(message: AgentMessage) {
    if (savingId) return
    setSavingId(message.id)
    try {
      const ok = await onSaveNote(message.text)
      if (live.current && ok) note(message.id, '已存为笔记', SAVED_NOTE_MS)
    } finally {
      if (live.current) setSavingId('')
    }
  }

  function copy(message: AgentMessage) {
    const clip = typeof navigator === 'undefined' ? undefined : navigator.clipboard
    if (!clip || typeof clip.writeText !== 'function') return
    clip.writeText(message.text)
      .then(() => { if (live.current) note(message.id, '已复制', COPIED_MS) })
      .catch(() => { /* 剪贴板不可用：什么都不改 */ })
  }

  async function shelve(path: string) {
    if (!bridge || shelving) return
    setShelving(path)
    try {
      const result = await bridge.shelve([path])
      if (!live.current) return
      if (result.ok) {
        setShelveErrors(errors => { const next = { ...errors }; delete next[path]; return next })
        setMessages(prev => prev.map(m => m.artifacts?.some(a => a.path === path) ? { ...m, artifacts: withShelved(m.artifacts, path) } : m))
        patchPending(p => p && { ...p, artifacts: withShelved(p.artifacts, path)! })
      } else setShelveErrors(errors => ({ ...errors, [path]: result.error || '没能放进暂存箱。' }))
    } catch (error) {
      if (live.current) setShelveErrors(errors => ({ ...errors, [path]: errorText(error) }))
    } finally {
      if (live.current) setShelving('')
    }
  }

  function onComposeKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.nativeEvent.isComposing) return
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send(); return }
    if (event.key !== 'Escape') return
    event.preventDefault()
    event.stopPropagation()
    if (draft) setDraft('')
    else if (attachments.length) setAttachments([])
    else onEscape()
  }

  function onRecentKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== 'Escape' || event.nativeEvent.isComposing) return
    event.preventDefault()
    event.stopPropagation()
    setRecentOpen(false)
    recentTrigger.current?.focus()
  }

  function onModelChange(next: string) {
    setModel(next)
    writeModel(next)
  }

  if (!bridge) return <section className="dc-session" aria-label="会话"><p className="dc-session-web">{WEB_ONLY_NOTE}</p></section>

  const unavailable = status ? !status.available : !!statusError
  const needsLogin = !unavailable && loginRequired
  if (unavailable || needsLogin) {
    return (
      <section className="dc-session" aria-label="会话">
        <div className="dc-session-state">
          <p className="dc-session-state-title">{needsLogin ? LOGIN_TITLE : MISSING_TITLE}</p>
          <p className="dc-session-state-note">{needsLogin ? LOGIN_NOTE : status?.reason || statusError}</p>
          <button type="button" className="dc-session-retry" onClick={() => { retriedLogin.current = true; setLoginRequired(false); void loadStatus() }}>重试</button>
        </div>
      </section>
    )
  }

  const models = status?.models.some(m => m.id === '') ? status.models : [{ id: '', label: '默认' }, ...(status?.models ?? [])]
  const selectedModel = models.some(m => m.id === model) ? model : ''
  const current = sessionId ? sessions.find(s => s.id === sessionId) : undefined
  const title = current?.title || (sessionId || messages.length ? '会话' : '新会话')
  const empty = messages.length === 0 && !pending

  const artifactRows = (artifacts: AgentArtifact[] | undefined) => !!artifacts?.length && (
    <ul className="dc-turn-files" aria-label="产出的文件">
      {artifacts.map(artifact => (
        <li key={artifact.path} className="dc-turn-file">
          <Icon n="bx-file" />
          <span className="dc-turn-file-name" title={artifact.path}>{artifact.name}</span>
          {artifact.shelved
            ? <span className="dc-turn-file-state">已放入</span>
            : <button type="button" className="dc-turn-act" disabled={shelving === artifact.path} title="复制一份到暂存箱，原文件留在工作目录" onClick={() => void shelve(artifact.path)}>{shelving === artifact.path ? '正在放入…' : '放入暂存箱'}</button>}
          {shelveErrors[artifact.path] && <span className="dc-turn-file-error" title={shelveErrors[artifact.path]}>{shelveErrors[artifact.path]}</span>}
        </li>
      ))}
    </ul>
  )

  return (
    <section className="dc-session" aria-label="会话">
      <div className="dc-session-head">
        <select className="dc-session-model" aria-label="模型" title="这一轮用哪个模型" value={selectedModel} onChange={event => onModelChange(event.target.value)}>
          {models.map(m => <option key={m.id || 'default'} value={m.id}>{m.label}</option>)}
        </select>
        <span className="dc-session-title" title={title}>{title}</span>
        <div className="dc-session-tools">
          <button ref={recentTrigger} type="button" className="dc-session-recent" aria-label="最近会话" aria-haspopup="menu" aria-expanded={recentOpen} title="回到最近的会话" onClick={toggleRecent}>最近</button>
          <button type="button" className="dc-icon" aria-label="新会话" title={running ? '这一轮结束后才能开新会话' : '开一个新会话'} disabled={running} onClick={newSession}><Icon n="bx-plus" /></button>
        </div>
        {recentOpen && (
          <div ref={recentRef} className="dc-session-recent-menu" role="menu" aria-label="最近会话" tabIndex={-1} onKeyDown={onRecentKeyDown}>
            {sessions.length === 0 && <p className="dc-session-recent-empty">还没有会话</p>}
            {sessions.map(session => (
              <button key={session.id} type="button" role="menuitem" className="dc-session-recent-item" title={session.title || session.id} onClick={() => void openSession(session.id)}>
                <span className="dc-session-recent-title">{session.title || '未命名会话'}</span>
                <span className="dc-session-recent-date">{shortDate(session.updatedAt || session.createdAt)}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {empty ? (
        <div className="dc-session-empty">
          <p className="dc-session-empty-title">和 Claude 直接对话</p>
          <small>回复可以一键进笔记，产出的文件可以放进暂存箱。</small>
          {status?.cwd && <span className="dc-session-cwd" title={status.cwd}>工作目录 · {lastSegment(status.cwd)}</span>}
        </div>
      ) : (
        <div ref={logRef} className="dc-session-log" aria-label="会话记录" onScroll={event => { const log = event.currentTarget; stickToBottom.current = log.scrollHeight - log.scrollTop - log.clientHeight < 40 }}>
          {messages.map(message => message.role === 'user' ? (
            <div key={message.id} className="dc-turn dc-turn-user">
              <p className="dc-turn-capsule">{message.text}</p>
              {!!message.artifacts?.length && <ul className="dc-turn-attached" aria-label="带上的文件">{message.artifacts.map(a => <li key={a.path} className="dc-turn-attached-item" title={a.path}><Icon n="bx-file" />{a.name}</li>)}</ul>}
            </div>
          ) : (
            <div key={message.id} className="dc-turn dc-turn-assistant">
              {message.text && <p className="dc-turn-text">{message.text}</p>}
              {artifactRows(message.artifacts)}
              {message.error && <p className="dc-turn-error">{message.error}</p>}
              {message.text && (
                <div className="dc-turn-actions">
                  <button type="button" className="dc-turn-act" title="插到正在写的笔记里" onClick={() => onInsert(message.text)}>引用到笔记</button>
                  <button type="button" className="dc-turn-act" title="存成一篇新笔记" disabled={savingId === message.id} onClick={() => void saveNote(message)}>存为笔记</button>
                  <button type="button" className="dc-turn-act" title="复制这段回复" onClick={() => copy(message)}>复制</button>
                  {rowNote?.id === message.id && <span className="dc-turn-note">{rowNote.text}</span>}
                </div>
              )}
            </div>
          ))}
          {pending && (
            <div className="dc-turn dc-turn-assistant dc-turn-live">
              {pending.text && <p className="dc-turn-text">{pending.text}</p>}
              {artifactRows(pending.artifacts)}
              <p className="dc-turn-activity" aria-live="polite"><i className="dc-turn-dot" aria-hidden="true" />{pending.activity || '正在思考'}</p>
            </div>
          )}
        </div>
      )}

      {problem && <p className="dc-session-problem">{problem}</p>}
      {status?.loggedIn === false && <p className="dc-session-hint">{LOGIN_HINT}</p>}
      {attachments.length > 0 && (
        <ul className="dc-session-attachments" aria-label="要带上的文件">
          {attachments.map(a => (
            <li key={a.path} className="dc-session-chip">
              <Icon n="bx-file" /><span className="dc-session-chip-name" title={a.path}>{a.name}</span>
              <button type="button" className="dc-session-chip-remove" aria-label={`不带上 ${a.name}`} title="这次不带上它" onClick={() => setAttachments(list => list.filter(x => x.path !== a.path))}><Icon n="bx-x" /></button>
            </li>
          ))}
        </ul>
      )}
      <p className="dc-session-live" role="status" aria-live="polite">{announce}</p>
      <form className="dc-session-compose" onSubmit={event => { event.preventDefault(); void send() }}>
        <textarea ref={textareaRef} aria-label="问 Claude" placeholder={attachments.length ? `问 Claude 关于这 ${attachments.length} 个文件…` : '问 Claude…'} rows={1} value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={onComposeKeyDown} />
        {running
          ? <button type="button" className="dc-icon dc-session-send" aria-label="停止" title="停下这一轮" onClick={interrupt}><Icon n="bx-stop" /></button>
          : <button type="submit" className="dc-icon dc-session-send" aria-label="发送" title={`发送 · ${fmtShortcut('↩')}，换行 · ${fmtShortcut('⇧↩')}`} disabled={!draft.trim() && !attachments.length}><Icon n="bx-paper-plane" /></button>}
      </form>
    </section>
  )
}
