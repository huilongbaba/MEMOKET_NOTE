import { useCallback, useEffect, useId, useRef, useState, type CSSProperties, type DragEvent } from 'react'
import * as api from '../api'
import type { CompanionActionResult, CompanionItem, CompanionMutationResult, CompanionPanel, CompanionState, CompanionSurface, CompanionWindowCandidate, DecideSelection } from '../desktop'
import { useClipboardSuggestion } from '../util/useClipboardSuggestion'
import { useTodayTasks } from '../util/useTodayTasks'
import CompanionTasks from './CompanionTasks'
import CompanionDraftEditor, { type CompanionEditorHandle } from './CompanionDraftEditor'
import { useIslandMotion } from '../util/useIslandMotion'
import Icon from './Icon'
import CompanionAINote, { type CompanionAINoteState, type CompanionAIRequest } from './CompanionAINote'
import CompanionAIMenu from './CompanionAIMenu'
import CompanionSession, { type CompanionSessionHandle } from './CompanionSession'
import CompanionMemory from './CompanionMemory'
import CompanionDecide, { hotkeyLabel, type DecidePhase } from './CompanionDecide'
import type { Fact } from '../api'
import { DESKTOP_AI_ACTIONS, hasCompanionAIDraft } from '../util/companionActions'
import { attachmentSize, noteContentWithAttachments, readNoteAttachments, type NoteAttachment } from '../util/noteAttachments'
import '../desktop-companion.css'

type Draft = { title: string; content: string; attachments?: NoteAttachment[] }
type AttachmentJob = { id: string; file: File; status: 'uploading' | 'error'; error?: string }
type DropDestination = 'note' | 'agent' | 'shelf'
type Notice = { text: string; error: boolean; recovery?: boolean }
/** The background extraction job that carries a just-saved note into the knowledge base. */
type KbSync = { noteId: string; jobId: string; status: 'running' | 'done' | 'error'; facts: number }
const KB_SYNC_POLL_MS = 2000
const KB_SYNC_GIVE_UP_MS = 10 * 60_000
type AITarget = { action: api.DesktopAIAction; kind: 'selection' | 'draft' | 'clipboard'; start: number; end: number; text: string }
type AIApplied = { label: string; lines: number; text: string; before: Draft }
type ActionMenu = { x: number; y: number; scope: string; source: api.DesktopComposeSource; disabledReason: string; start: number; end: number }
/** 会话面板可能还没挂上：拖来的文件、要它展开的一段话，先排着，挂上就交过去。 */
type AgentQueue = { kind: 'files'; files: File[] } | { kind: 'text'; text: string }
/** 拿主意的阶段；`seq` 让同一种阶段再来一次也算新的（收起后的「选项已备好」只播一次）。 */
type DecideState = { phase: DecidePhase; count: number; mode?: 'options' | 'questions'; seq: number }
const DECIDE_READY_HINT_MS = 6000
/** 拿主意在读 / 在想时药丸的宽度：装得下一句摘录。 */
const ISLAND_LIVE_WIDTH = 320
/** 被动展开的台面没人理多久自己收起：答案还在，药丸会说「选项已备好」，再按 ⌥D 就带回来。 */
const DECIDE_PASSIVE_MS = 12000
/** 药丸里那句摘录：第一行非空的字，多了让省略号收尾（CSS 截）。 */
const liveExcerpt = (text: string) => text.split('\n').map(line => line.trim()).find(Boolean) ?? ''
type Props = {
  surface: CompanionSurface
  onExpandedChange?: (expanded: boolean) => void
  onShowShelf?: () => void
  openRequested?: number
}

const KIND_LABEL: Record<CompanionItem['kind'], string> = { file: '文件', image: '图片', text: '文字', link: '链接', window: '窗口' }
type PreviewTarget = { source: 'shelf' | 'window'; id: string }
type PreviewContent = Pick<CompanionItem, 'kind' | 'title' | 'text' | 'url' | 'thumbnail' | 'previewText' | 'previewTextTruncated' | 'missing' | 'previewStatus' | 'previewError' | 'storage'>

function AttachmentThumbnail({ attachment }: { attachment: NoteAttachment }) {
  const [failed, setFailed] = useState(false)
  if (attachment.kind === 'image' && !failed) return <img src={attachment.url} alt={attachment.name} draggable={false} onError={() => setFailed(true)} />
  return <span className="dc-attachment-extension" title={failed ? '缩略图无法显示，点击可打开附件' : attachment.name}>{failed ? '无预览' : attachment.name.includes('.') ? attachment.name.split('.').pop()?.slice(0, 6).toUpperCase() : 'FILE'}</span>
}

/** Only real local content is rendered. A missing image is a status, never a file-type icon. */
function ContentPreview({ item, enlarged = false, snapshotLabel = '暂存时的窗口截图' }: { item: PreviewContent; enlarged?: boolean; snapshotLabel?: string }) {
  const [failedImage, setFailedImage] = useState('')
  if (item.kind === 'file' && item.previewText !== undefined && !item.missing && item.previewStatus === 'ready') return <span className={'dc-content-file-text' + (enlarged ? ' dc-content-file-text-full' : '')}>
    <span>{item.previewText || '空文件'}</span>
    {enlarged && item.previewTextTruncated && <span className="dc-file-text-boundary">预览文件开头，打开{item.storage === 'copy' ? '副本' : '原文件'}查看完整内容。</span>}
  </span>
  if (item.kind === 'text' || item.kind === 'link') return <span className={'dc-content-excerpt' + (enlarged ? ' dc-content-excerpt-full' : '')}>
    <span className="dc-content-eyebrow">{item.kind === 'link' ? '网页链接' : '文字摘录'}</span>
    <span className="dc-content-text">{item.text || item.url || '这条内容没有正文。'}</span>
    {item.kind === 'link' && item.text && item.url && <span className="dc-content-url">{item.url}</span>}
    {enlarged && item.kind === 'link' && <span className="dc-content-boundary">仅显示暂存的链接与摘录，未读取网页全文。</span>}
  </span>
  const image = item.thumbnail?.startsWith('data:image/') && item.thumbnail !== failedImage ? item.thumbnail : ''
  const unavailable = item.missing ? item.storage === 'copy' ? '暂存副本无法访问' : '原文件已移动或无法访问' : failedImage && failedImage === item.thumbnail ? '预览图片无法显示' : item.previewError || '此内容暂时没有可用预览'
  return <span className={'dc-content-image' + (image ? item.kind === 'file' ? ' dc-content-document' : '' : ' dc-content-no-image')}>
    {image ? <img src={image} alt={item.title} draggable={false} onError={() => setFailedImage(image)} />
      : <span className="dc-preview-placeholder"><strong>{item.previewStatus === 'loading' && !item.missing ? '正在生成预览' : '暂无预览'}</strong><span>{item.previewStatus === 'loading' && !item.missing ? item.title : unavailable}</span></span>}
    {image && (item.previewStatus === 'loading' || item.previewStatus === 'unavailable' || item.missing || (item.kind === 'window' && enlarged)) && <span className="dc-preview-caption" title={item.previewError}>{item.missing ? `${item.storage === 'copy' ? '暂存副本' : '原文件'}不可用 · 已保留预览` : item.previewStatus === 'loading' ? '正在更新预览' : item.previewStatus === 'unavailable' ? '更新失败 · 显示上次预览' : snapshotLabel}</span>}
  </span>
}

function emptyState(): CompanionState {
  return { surface: 'top', expanded: false, panel: 'capture', items: [], storageError: '' }
}

function initialDraft() {
  let key = 'memoket.companion.draft.anonymous'
  try {
    key = `memoket.companion.draft.${encodeURIComponent(api.getUser())}`
    const raw = localStorage.getItem(key)
    const value: unknown = raw ? JSON.parse(raw) : null
    const stored = value && typeof value === 'object' ? value as Partial<Draft> : null
    const attachments = readNoteAttachments(stored?.attachments)
    return { key, title: typeof stored?.title === 'string' ? stored.title : '', content: typeof stored?.content === 'string' ? stored.content : '', ...(attachments.length ? { attachments } : {}), error: '' }
  } catch {
    return { key, title: '', content: '', error: '无法读取本机草稿，请在离开前保存笔记。' }
  }
}

function errorText(error: unknown) {
  const message = error instanceof Error ? error.message : String(error || '')
  if (/Failed to fetch|NetworkError|Load failed/i.test(message)) return '笔记服务暂时不可用，请稍后重试。'
  return message || '操作没有完成，请重试。'
}

/** The same surface is used in native companion windows and the honest browser preview. */
/** What fits after the mark in a 240px pill: twelve characters, then an ellipsis. */
const clipHint = (text: string, max = 12) => { const chars = Array.from(text.trim()); return chars.length > max ? chars.slice(0, max - 1).join('') + '…' : chars.join('') }

export default function DesktopCompanion({ surface, onExpandedChange, openRequested = 0 }: Props) {
  const bridge = window.memoketDesktop?.companion
  const agent = window.memoketDesktop?.agent
  const decideBridge = window.memoketDesktop?.decide
  const [state, setState] = useState<CompanionState>(emptyState)
  const [panelMounted, setPanelMounted] = useState(false)
  const [aiOpen, setAIOpen] = useState(false)
  const [aiMounted, setAIMounted] = useState(false)
  // The session panel stays mounted after its first visit so the transcript and a running turn survive collapse and hover-switching.
  const [sessionMounted, setSessionMounted] = useState(false)
  const [sessionFocusRequested, setSessionFocusRequested] = useState(0)
  const sessionRef = useRef<CompanionSessionHandle | null>(null)
  /** 拖到「交给 Claude」的文件：面板可能还没挂上，先排着，挂上就交过去。 */
  const [agentQueue, setAgentQueue] = useState<AgentQueue | null>(null)
  /** 拿主意：热键（或笔记里的 AI 菜单）送来的选区；每次都是新对象，同一段也会重跑。 */
  const [decideRequest, setDecideRequest] = useState<DecideSelection | null>(null)
  /** 主进程实际注册成功的热键，空态那句要说对。 */
  const [decideHotkey, setDecideHotkey] = useState('')
  const [decideState, setDecideState] = useState<DecideState>({ phase: 'idle', count: 0, seq: 0 })
  const decideSeq = useRef(0)
  /** 收起后药丸上的「选项已备好 · N 个」，几秒后自己退下。 */
  const [decideHint, setDecideHint] = useState('')
  /** 热键刚按下、还在读：药丸先亮起「正在拿主意」，不等读选区那几百毫秒。 */
  const [decidePending, setDecidePending] = useState<false | 'reading' | 'screenshot'>(false)
  const decidePendingTimer = useRef(0)
  /** 热键按了却什么都没读到：药丸上说一句，不展开。 */
  const [decideEmptyHint, setDecideEmptyHint] = useState('')
  const decideEmptyTimer = useRef(0)
  /** 这一次是热键发起的：答案出来时再展开岛（笔记里的 AI 菜单发起的已经展开着）。 */
  const decideFromHotkey = useRef(false)
  const decideHasResult = useRef(false)
  const decideThinking = useRef(false)
  const decidePassiveTimer = useRef(0)
  const hintId = useId()
  const decideHotkeyRef = useRef('')
  /** 读到了、在想：药丸长到 320，里面是那句摘录（或缩略图 + 来处），答案到了才展开。 */
  const [decideLive, setDecideLive] = useState<{ text: string; image?: string; source: string; origin?: DecideSelection['origin'] } | null>(null)
  const [decideTap, setDecideTap] = useState(false)
  const decideHintTimer = useRef(0)
  const decideHintShown = useRef(0)
  /** 拿主意不是标签：滑块停在上一个标签的位置上并隐去，回来时不用跳。 */
  const lastTab = useRef(0)
  const expandRef = useRef<(expanded: boolean, panel?: CompanionPanel, focus?: boolean) => void>(() => {})
  const [agentRunning, setAgentRunning] = useState(false)
  const [tasksFocusRequested, setTasksFocusRequested] = useState(0)
  const [memoryOpen, setMemoryOpen] = useState(false)
  const [aiRequest, setAIRequest] = useState<CompanionAIRequest>()
  const [actionMenu, setActionMenu] = useState<ActionMenu | null>(null)
  const [pendingAI, setPendingAI] = useState(hasCompanionAIDraft)
  // Where the running editor action should land, and what it wrote (so one 撤销 can take it back).
  const aiTargetRef = useRef<AITarget | null>(null)
  const [aiApplied, setAIApplied] = useState<AIApplied | null>(null)
  const aiRequestSequence = useRef(0)
  const [aiState, setAIState] = useState<CompanionAINoteState>({ busy: false, hasDraft: false, storageError: false, phase: 'idle' })
  const [session] = useState(initialDraft)
  const [draft, setDraft] = useState<Draft>({ title: session.title, content: session.content, ...(session.attachments?.length ? { attachments: session.attachments } : {}) })
  const [draftError, setDraftError] = useState(session.error)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [kbSync, setKbSync] = useState<KbSync | null>(null)
  const kbSyncTimer = useRef(0)
  const [busy, setBusy] = useState('')
  const [dragging, setDragging] = useState(false)
  const [fileDrag, setFileDrag] = useState(false)
  const fileDragActive = useRef(false)
  const [dropDestination, setDropDestination] = useState<DropDestination | null>(null)
  const [dragSummary, setDragSummary] = useState('')
  const [attachmentJobs, setAttachmentJobs] = useState<AttachmentJob[]>([])
  const attachmentControllers = useRef(new Map<string, AbortController>())
  const attachmentJobsRef = useRef(attachmentJobs)
  attachmentJobsRef.current = attachmentJobs
  const attachmentSequence = useRef(0)
  const [keepOpen, setKeepOpen] = useState(false)
  const [shelfQuery, setShelfQuery] = useState('')
  const [shelfAddOpen, setShelfAddOpen] = useState(false)
  const [shelfSearchOpen, setShelfSearchOpen] = useState(false)
  const [shelfEntryOpen, setShelfEntryOpen] = useState(false)
  const shelfAddRef = useRef<HTMLDivElement>(null)
  const shelfAddTrigger = useRef<HTMLButtonElement>(null)
  const shelfSearchRef = useRef<HTMLInputElement>(null)
  const shelfEntryRef = useRef<HTMLInputElement>(null)
  const [textToHold, setTextToHold] = useState('')
  const [candidates, setCandidates] = useState<CompanionWindowCandidate[]>([])
  const [windowError, setWindowError] = useState('')
  const [windowsLoaded, setWindowsLoaded] = useState(false)
  const [preview, setPreview] = useState<PreviewTarget | null>(null)
  const previewRef = useRef(preview)
  previewRef.current = preview
  const previewTrigger = useRef<HTMLButtonElement | null>(null)
  const previewBack = useRef<HTMLButtonElement | null>(null)
  const suppressPreviewClick = useRef(false)
  const rootRef = useRef<HTMLElement>(null)
  const editorRef = useRef<CompanionEditorHandle>(null)
  // What the last drop did, kept on the collapsed pill for a few seconds so a drop is never silent.
  const [dropOutcome, setDropOutcome] = useState('')
  const dropOutcomeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const itemsRef = useRef<HTMLDivElement>(null)
  const [arrivedIds, setArrivedIds] = useState<string[]>([])
  const filesRef = useRef<HTMLInputElement>(null)
  const noteFilesRef = useRef<HTMLInputElement>(null)
  const draftRef = useRef(draft)
  const busyRef = useRef('')
  const mountedRef = useRef(false)
  const expansionSeq = useRef(0)
  const dragDepth = useRef(0)
  const dragRevision = useRef(0)
  const dragExitTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pickingFiles = useRef(false)
  const showArrivalUntil = useRef(0)
  const collapseRequested = useRef(false)
  // The input method's candidate panel can take window focus mid-word; that blur must not fold the stage away
  // under a half-composed sentence. Pointer leave still collapses as before.
  const composingRef = useRef(false)
  const leaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const focusIntent = useRef<CompanionPanel | null>(null)
  const localExpansion = useRef<{ seq: number; expanded: boolean; panel: CompanionPanel; focus: boolean } | null>(null)
  const collapseRef = useRef<() => void>(() => {})
  const stateRef = useRef(state)
  stateRef.current = state
  const keepOpenRef = useRef(keepOpen)
  keepOpenRef.current = keepOpen
  const resetDrag = useCallback(() => {
    dragRevision.current++
    if (dragExitTimer.current) clearTimeout(dragExitTimer.current)
    dragExitTimer.current = null
    dragDepth.current = 0
    fileDragActive.current = false
    setDragging(false)
    setFileDrag(false)
    setDropDestination(null)
    setDragSummary('')
  }, [])
  const cancelDragOutside = useCallback(() => {
    resetDrag()
    collapseRef.current()
  }, [resetDrag])
  const aiGuard = useRef(aiState)
  const onAIState = useCallback((next: CompanionAINoteState) => { aiGuard.current = next; setAIState(next) }, [])
  const modifier = /Mac/.test(navigator.platform) ? '⌘' : 'Ctrl'
  // Today's to-dos are the same local list as the workspace Home; the first open one is what the collapsed pill shows.
  const today = useTodayTasks(api.getUser())
  const nextTask = today.open[0]
  const clipboard = useClipboardSuggestion(bridge, state.expanded && state.panel === 'capture', draft.content)
  useIslandMotion(rootRef, state.expanded, width => {
    if (stateRef.current.expanded) return
    setPanelMounted(false)
    void bridge?.settleCollapsed(width).catch(() => {})
  }, decideLive ? ISLAND_LIVE_WIDTH : undefined)

  useEffect(() => {
    mountedRef.current = true
    const controllers = attachmentControllers.current
    let live = true
    const accept = (next: CompanionState) => {
      if (!live || next.surface !== surface) return
      const previous = stateRef.current
      if (!next.expanded || next.panel !== previous.panel) { setActionMenu(null); setShelfAddOpen(false) }
      const requested = localExpansion.current
      const localTransition = requested?.expanded === next.expanded && requested.panel === next.panel
      // Native shortcuts arrive as state broadcasts, without a renderer click.
      // An unfocused hover expansion must still remain passive, including its broadcast.
      if (bridge && next.expanded && (!previous.expanded || previous.panel !== next.panel)
          && document.hasFocus() && (!localTransition || requested?.focus)) focusIntent.current = next.panel
      stateRef.current = next
      setState(next)
    }
    const unsubscribe = bridge?.onState(accept)
    void bridge?.getState().then(accept).catch((error: unknown) => {
      if (live) setNotice({ text: errorText(error), error: true })
    })
    return () => {
      live = false
      mountedRef.current = false
      window.clearTimeout(kbSyncTimer.current)
      window.clearTimeout(decideHintTimer.current)
      unsubscribe?.()
      if (leaveTimer.current) clearTimeout(leaveTimer.current)
      if (hoverTimer.current) clearTimeout(hoverTimer.current)
      if (dragExitTimer.current) clearTimeout(dragExitTimer.current)
      for (const controller of controllers.values()) controller.abort()
    }
  }, [bridge, surface])

  useEffect(() => { onExpandedChange?.(state.expanded) }, [onExpandedChange, state.expanded])
  useEffect(() => {
    const refresh = () => setPendingAI(hasCompanionAIDraft())
    window.addEventListener('memoket-ai-draft-changed', refresh)
    return () => window.removeEventListener('memoket-ai-draft-changed', refresh)
  }, [])

  useEffect(() => {
    if (state.expanded) setPanelMounted(true)
  }, [state.expanded])
  useEffect(() => {
    if (state.expanded && state.panel === 'agent') setSessionMounted(true)
  }, [state.expanded, state.panel])
  // One drawer under the editor at a time: the AI result and the related memory share that space.
  useEffect(() => { if (aiOpen) setMemoryOpen(false) }, [aiOpen])

  useEffect(() => { setPreview(null) }, [state.panel])
  useEffect(() => { if (preview) previewBack.current?.focus() }, [preview])

  useEffect(() => {
    if (!shelfAddOpen) return
    shelfAddRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')?.focus()
    const outside = (event: PointerEvent) => {
      if (!shelfAddRef.current?.contains(event.target as Node) && !shelfAddTrigger.current?.contains(event.target as Node)) setShelfAddOpen(false)
    }
    const blur = () => setShelfAddOpen(false)
    document.addEventListener('pointerdown', outside)
    window.addEventListener('blur', blur)
    return () => { document.removeEventListener('pointerdown', outside); window.removeEventListener('blur', blur) }
  }, [shelfAddOpen])
  useEffect(() => { if (shelfSearchOpen) shelfSearchRef.current?.focus() }, [shelfSearchOpen])
  useEffect(() => { if (shelfEntryOpen) shelfEntryRef.current?.focus() }, [shelfEntryOpen])

  useEffect(() => {
    const onBlur = () => { if (composingRef.current) return; collapseRef.current() }
    window.addEventListener('blur', onBlur)
    return () => window.removeEventListener('blur', onBlur)
  }, [])

  useEffect(() => {
    if (!fileDrag || !state.expanded || !bridge?.isPointerInside) return
    let live = true
    let pending = false
    const check = async () => {
      if (pending) return
      pending = true
      const revision = dragRevision.current
      try {
        const inside = await bridge.isPointerInside!()
        if (live && fileDragActive.current && revision === dragRevision.current && !inside) cancelDragOutside()
      } catch { /* DOM boundary events still handle exits while native IPC is unavailable. */ }
      finally { pending = false }
    }
    // Finder owns the drag session; the target renderer may never receive dragend.
    const timer = window.setInterval(() => { void check() }, 120)
    return () => { live = false; window.clearInterval(timer) }
  }, [bridge, fileDrag, state.expanded, cancelDragOutside])

  useEffect(() => {
    const end = (event: Event) => {
      if (!fileDragActive.current && !dragDepth.current) return
      if (event.target instanceof Node && rootRef.current?.contains(event.target)) resetDrag()
      else cancelDragOutside()
    }
    const outsideDrop = (event: Event) => {
      if (!(event.target instanceof Node) || !rootRef.current?.contains(event.target)) end(event)
    }
    const resumePointer = (event: MouseEvent) => {
      // Ordinary pointer events resume when an OS drag is released or canceled.
      if (fileDragActive.current && event.buttons === 0) end(event)
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.isComposing || !fileDragActive.current) return
      event.preventDefault()
      event.stopPropagation()
      resetDrag()
      if (collapseRequested.current) collapseRef.current()
    }
    window.addEventListener('dragend', end)
    window.addEventListener('drop', outsideDrop)
    window.addEventListener('pointermove', resumePointer)
    window.addEventListener('mousemove', resumePointer)
    window.addEventListener('keydown', escape, true)
    return () => {
      window.removeEventListener('dragend', end)
      window.removeEventListener('drop', outsideDrop)
      window.removeEventListener('pointermove', resumePointer)
      window.removeEventListener('mousemove', resumePointer)
      window.removeEventListener('keydown', escape, true)
    }
  }, [resetDrag, cancelDragOutside])

  useEffect(() => { if (!state.expanded) resetDrag() }, [state.expanded, resetDrag])

  useEffect(() => {
    if (!keepOpen && collapseRequested.current) collapseRef.current()
  }, [keepOpen])

  useEffect(() => {
    const input = filesRef.current
    const noteInput = noteFilesRef.current
    const onCancel = () => { pickingFiles.current = false }
    input?.addEventListener('cancel', onCancel)
    noteInput?.addEventListener('cancel', onCancel)
    return () => { input?.removeEventListener('cancel', onCancel); noteInput?.removeEventListener('cancel', onCancel) }
  }, [state.expanded, state.panel, surface])

  useEffect(() => {
    if (!openRequested) return
    if (!bridge) { setState((old) => ({ ...old, expanded: true, panel: 'clipboard' })); return }
    void bridge.setExpanded(true, 'clipboard').then((next) => {
      if (mountedRef.current && next.surface === surface) setState(next)
    }).catch((error: unknown) => {
      if (mountedRef.current) setNotice({ text: errorText(error), error: true })
    })
  }, [openRequested, bridge, surface])

  useEffect(() => {
    if (!state.expanded || !panelMounted || surface !== 'top' || !document.hasFocus() || focusIntent.current !== state.panel) return
    if (state.panel === 'capture') editorRef.current?.focus()
    else if (state.panel === 'agent') setSessionFocusRequested(value => value + 1)
    else if (state.panel === 'tasks') setTasksFocusRequested(value => value + 1)
    focusIntent.current = null
  }, [state.expanded, state.panel, panelMounted, surface, aiOpen])

  useEffect(() => {
    if (!agentQueue || !sessionMounted || !sessionRef.current) return
    setAgentQueue(null)
    if (agentQueue.kind === 'text') { sessionRef.current.draft(agentQueue.text); return }
    const { files } = agentQueue
    void sessionRef.current.attach(files).then(ok => { if (ok && mountedRef.current) announceDrop(files, 'agent') })
  }, [agentQueue, sessionMounted])

  // 拿主意：热键按下的一瞬间主进程先说 pending（药丸亮起来），读到选区后送过来（那一小段飞进药丸），
  // 岛不在这时展开——台面在后台去问后端，答案出来（onDecidePhase）才展开。什么都没读到就只在药丸上说一句。
  useEffect(() => {
    if (!decideBridge || surface !== 'top') return
    decideBridge.status().then(status => { if (mountedRef.current) { setDecideTap(!!status.tap); if (status.accelerator) { const label = hotkeyLabel(status.accelerator); decideHotkeyRef.current = label; setDecideHotkey(label) } } }).catch(() => {})
    const offPending = decideBridge.onPending(event => {
      if (!mountedRef.current) return
      window.clearTimeout(decidePendingTimer.current)
      if (event.phase === 'cancelled') { setDecidePending(false); return }
      setDecidePending(event.phase === 'screenshot' ? 'screenshot' : 'reading')
      // 读选区最多亮 6 秒（读不到也会有 selection 来收尾）；框屏幕的人可以想很久，跟着 cancelled / selection 走。
      if (event.phase !== 'screenshot') decidePendingTimer.current = window.setTimeout(() => { if (mountedRef.current) setDecidePending(false) }, 6000)
    })
    const offSelection = decideBridge.onSelection(selection => {
      if (!mountedRef.current) return
      const open = stateRef.current.expanded && stateRef.current.panel === 'decide'
      if (selection.error === 'accessibility') { setDecideRequest(selection); if (!open) expandRef.current(true, 'decide'); return }
      window.clearTimeout(decidePendingTimer.current)
      setDecidePending(false)
      if (selection.error === 'empty') {
        // 上次的结果还在就照旧展开给他看；否则药丸上说一句就够了。
        if (decideHasResult.current) { setDecideRequest(selection); if (!open) expandRef.current(true, 'decide'); return }
        // 上一次还在想：这次空按不送去台面，免得把正在等的答案作废（答案到了照样展开）。
        if (!decideThinking.current) setDecideRequest(selection)
        setDecideEmptyHint('没读到 · 先选中或复制')
        window.clearTimeout(decideEmptyTimer.current)
        decideEmptyTimer.current = window.setTimeout(() => { if (mountedRef.current) setDecideEmptyHint('') }, DECIDE_READY_HINT_MS)
        return
      }
      setDecideRequest(selection)
      decideFromHotkey.current = true
      setDecideLive({ text: liveExcerpt(selection.text), ...(selection.image ? { image: selection.image } : {}), source: selection.source, origin: selection.origin })
    })
    return () => { offPending(); offSelection() }
  }, [decideBridge, surface])

  // 收起之后药丸上说一声「选项已备好 · N 个」，几秒后退回平时的样子；每一次结果只播一次。
  useEffect(() => {
    if (decideState.phase !== 'ready' || !decideState.count) { window.clearTimeout(decideHintTimer.current); setDecideHint(''); return }
    if (state.expanded || decideHintShown.current === decideState.seq) return
    decideHintShown.current = decideState.seq
    setDecideHint(decideState.mode === 'questions' ? `先反问 · ${decideState.count} 个问题` : `选项已备好 · ${decideState.count} 个`)
    window.clearTimeout(decideHintTimer.current)
    decideHintTimer.current = window.setTimeout(() => { if (mountedRef.current) setDecideHint('') }, DECIDE_READY_HINT_MS)
  }, [decideState, state.expanded])
  useEffect(() => { if (state.panel !== 'decide') lastTab.current = state.panel === 'capture' ? 0 : state.panel === 'agent' ? 2 : state.panel === 'tasks' ? 3 : 1 }, [state.panel])
  const onDecidePhase = useCallback((phase: DecidePhase, count: number, mode?: 'options' | 'questions') => {
    if (!mountedRef.current) return
    setDecideState({ phase, count, mode, seq: ++decideSeq.current })
    decideHasResult.current = phase === 'ready' && count > 0
    decideThinking.current = phase === 'thinking'
    if (phase !== 'thinking') setDecideLive(null)
    // 热键发起的：答案（或错误）到了才展开——之前药丸一直亮着「正在拿主意」。
    if ((phase === 'ready' || phase === 'error') && decideFromHotkey.current) {
      decideFromHotkey.current = false
      if (!stateRef.current.expanded || stateRef.current.panel !== 'decide') {
        // 几秒后才到的答案不能抢别的应用的焦点（focus=true 时主进程 show() 会 activateIgnoringOtherApps）：被动展开，
        // 人挪过来再接管键盘。expand() 只在 focus=true 时清 collapseRequested，被动展开要先清掉，不然 260 ms 后就被收起。
        collapseRequested.current = false
        const passive = !document.hasFocus()
        expandRef.current(true, 'decide', !passive)
        window.clearTimeout(decidePassiveTimer.current)
        if (passive) decidePassiveTimer.current = window.setTimeout(() => {
          // 没得到焦点、指针也没进来过的台面不能一直压在别的应用上：到点自己收起。
          if (!mountedRef.current || !stateRef.current.expanded || stateRef.current.panel !== 'decide') return
          if (document.hasFocus() || rootRef.current?.matches(':hover')) return
          collapseRef.current()
        }, DECIDE_PASSIVE_MS)
      }
    }
  }, [])

  useEffect(() => {
    if (!arrivedIds.length) return
    if (itemsRef.current) itemsRef.current.scrollTop = 0
    const timer = window.setTimeout(() => setArrivedIds([]), 2600)
    return () => window.clearTimeout(timer)
  }, [arrivedIds])

  function updateDraft(next: Draft) {
    draftRef.current = next
    setDraft(next)
    try {
      if (next.title || next.content || next.attachments?.length) localStorage.setItem(session.key, JSON.stringify(next))
      else localStorage.removeItem(session.key)
      setDraftError('')
    } catch {
      setDraftError('本机草稿未保存，请先存入笔记。')
    }
  }

  function updateAttachmentJobs(next: AttachmentJob[]) {
    attachmentJobsRef.current = next
    setAttachmentJobs(next)
  }

  async function uploadAttachment(job: AttachmentJob) {
    if (!attachmentJobsRef.current.some(item => item.id === job.id)) return
    const controller = new AbortController()
    attachmentControllers.current.set(job.id, controller)
    updateAttachmentJobs(attachmentJobsRef.current.map(item => item.id === job.id ? { ...item, status: 'uploading', error: undefined } : item))
    try {
      const asset = await api.uploadNoteAttachment(job.file, controller.signal)
      if (!mountedRef.current || controller.signal.aborted) return
      const attachment: NoteAttachment = { id: job.id, name: asset.name, url: asset.url, kind: asset.kind, bytes: asset.bytes }
      updateDraft({ ...draftRef.current, attachments: [...(draftRef.current.attachments || []), attachment] })
      updateAttachmentJobs(attachmentJobsRef.current.filter(item => item.id !== job.id))
    } catch (error) {
      if (!mountedRef.current || controller.signal.aborted) return
      updateAttachmentJobs(attachmentJobsRef.current.map(item => item.id === job.id ? { ...item, status: 'error', error: errorText(error) } : item))
    } finally {
      if (attachmentControllers.current.get(job.id) === controller) attachmentControllers.current.delete(job.id)
    }
  }

  function attachFiles(files: File[]) {
    if (!files.length) return
    if (busyRef.current === 'save') { setNotice({ text: '这篇笔记正在保存，请保存完成后再添加附件。', error: true }); return }
    const jobs: AttachmentJob[] = files.map(file => ({ id: `attachment-${Date.now()}-${++attachmentSequence.current}`, file, status: 'uploading' }))
    updateAttachmentJobs([...attachmentJobsRef.current, ...jobs])
    let next = 0
    // Keep large multi-file drops bounded without blocking the editor or other panels.
    void Promise.all(Array.from({ length: Math.min(3, jobs.length) }, async () => {
      while (next < jobs.length && mountedRef.current) await uploadAttachment(jobs[next++])
    }))
  }

  function removeAttachment(id: string) {
    const attachments = (draftRef.current.attachments || []).filter(item => item.id !== id)
    const next = { ...draftRef.current }
    if (attachments.length) next.attachments = attachments
    else delete next.attachments
    updateDraft(next)
  }

  function cancelAttachment(id: string) {
    attachmentControllers.current.get(id)?.abort()
    attachmentControllers.current.delete(id)
    updateAttachmentJobs(attachmentJobsRef.current.filter(item => item.id !== id))
  }

  function openPreview(target: PreviewTarget, trigger: HTMLButtonElement) {
    if (suppressPreviewClick.current) { suppressPreviewClick.current = false; return }
    previewTrigger.current = trigger
    previewRef.current = target
    setPreview(target)
  }

  function closePreview() {
    const target = previewTrigger.current
    previewRef.current = null
    setPreview(null)
    requestAnimationFrame(() => {
      if (target?.isConnected) target.focus()
      else rootRef.current?.querySelector<HTMLButtonElement>('.dc-item-preview, .dc-window-preview, .dc-nav-active')?.focus()
    })
  }

  async function expand(expanded: boolean, panel = stateRef.current.panel, focus = true) {
    if (!expanded && busyRef.current) return
    if (!expanded || focus) collapseRequested.current = false
    setActionMenu(null)
    setShelfAddOpen(false)
    if (leaveTimer.current) clearTimeout(leaveTimer.current)
    if (hoverTimer.current) clearTimeout(hoverTimer.current)
    focusIntent.current = expanded && focus ? panel : null
    if (expanded && panel !== stateRef.current.panel) setNotice(null)
    const seq = ++expansionSeq.current
    if (!bridge) {
      setState((old) => ({ ...old, expanded, panel }))
      if (expanded && collapseRequested.current) scheduleCollapse()
      return
    }
    localExpansion.current = { seq, expanded, panel, focus }
    try {
      const next = await bridge.setExpanded(expanded, panel, focus)
      if (mountedRef.current && seq === expansionSeq.current) { stateRef.current = next; setState(next) }
    } catch (error) {
      if (mountedRef.current) setNotice({ text: errorText(error), error: true })
    } finally {
      if (localExpansion.current?.seq === seq) localExpansion.current = null
      if (mountedRef.current && expanded && collapseRequested.current) scheduleCollapse()
    }
  }

  async function action(name: string, work: () => Promise<CompanionActionResult | CompanionMutationResult>, success?: string): Promise<boolean | undefined> {
    if (busyRef.current) return undefined
    busyRef.current = name
    setBusy(name)
    setNotice(null)
    const previousIds = new Set(stateRef.current.items.map((item) => item.id))
    try {
      const result = await work()
      if (!mountedRef.current) return
      if ('state' in result && result.state.surface === surface) {
        stateRef.current = result.state
        setState(result.state)
        const added = result.state.items.filter((item) => !previousIds.has(item.id))
        const received = ['files', 'drop', 'clipboard', 'hold-text', 'add-window'].includes(name)
        if (received && result.ok) {
          setShelfQuery('')
          if (itemsRef.current) itemsRef.current.scrollTop = 0
          showArrivalUntil.current = Date.now() + 3000
          if (!added.length) success = '已在暂存架中，已显示全部内容。'
        }
        if (added.length) {
          setShelfQuery('')
          setArrivedIds(added.map((item) => item.id))
          showArrivalUntil.current = Date.now() + 3000
          if (result.ok) success = added.every(item => item.storage === 'copy') ? added.length === 1 ? `已保留「${added[0].title}」的副本` : `已复制 ${added.length} 项到暂存架` : added.length === 1 ? `已暂存「${added[0].title || KIND_LABEL[added[0].kind]}」` : `已暂存 ${added.length} 项，新内容已放在最前面。`
        }
      }
      if (!result.ok) setNotice({ text: result.error || '操作没有完成，请重试。', error: true })
      else if (success) setNotice({ text: success, error: false, recovery: !!('recoveryPath' in result && result.recoveryPath) })
      return result.ok
    } catch (error) {
      if (mountedRef.current) setNotice({ text: errorText(error), error: true })
    } finally {
      busyRef.current = ''
      if (mountedRef.current) setBusy('')
    }
  }

  async function saveDraft() {
    if (busyRef.current || attachmentJobsRef.current.length) return
    const value = draftRef.current
    if (!value.title.trim() && !value.content.trim() && !value.attachments?.length) return
    busyRef.current = 'save'
    setBusy('save')
    setNotice(null)
    try {
      const title = value.title.trim() || value.content.trim().split('\n')[0].replace(/^#+\s*/, '').slice(0, 80) || value.attachments?.[0]?.name || '附件笔记'
      const saved = await api.createNote(title, noteContentWithAttachments(value.content, value.attachments))
      if (!mountedRef.current) return
      updateDraft({ title: '', content: '' })
      setAIApplied(null)
      setNotice({ text: '已存入笔记。', error: false })
      editorRef.current?.focus()
      void enterKnowledge(saved.id)
    } catch (error) {
      if (mountedRef.current) setNotice({ text: `未保存，文字已保留。${errorText(error)}`, error: true })
    } finally {
      busyRef.current = ''
      if (mountedRef.current) setBusy('')
    }
  }

  /** A saved note goes into the knowledge base on its own: the backend re-reads the note and extracts facts in a
   *  background job; the island only watches that job so the 知识库 tab and the memory strip can pick the note up.
   *  Nothing here blocks the next capture, and the note itself is already safe when this starts. */
  async function enterKnowledge(noteId: string) {
    window.clearTimeout(kbSyncTimer.current)
    let jobId = ''
    try { jobId = (await api.syncNoteToKb(noteId)).job_id }
    catch (error) {
      if (mountedRef.current) setNotice({ text: `已存入笔记，但没能进入知识库。${errorText(error)}`, error: true })
      return
    }
    if (!mountedRef.current) return
    setKbSync({ noteId, jobId, status: 'running', facts: 0 })
    setNotice({ text: '已存入笔记 · 正在进入知识库', error: false })
    const startedAt = Date.now()
    const poll = async () => {
      if (!mountedRef.current) return
      try {
        const job = await api.jobStatus(jobId)
        if (!mountedRef.current) return
        if (job.status === 'done') {
          setKbSync({ noteId, jobId, status: 'done', facts: job.facts ?? 0 })
          setNotice({ text: job.facts ? `已进入知识库 · ${job.facts} 条事实` : `已存入笔记 · 知识库没有新内容${job.detail ? `：${job.detail}` : ''}`, error: false })
          window.dispatchEvent(new Event('kb-changed'))
          return
        }
        if (job.status === 'error' || job.status === 'cancelled') {
          setKbSync({ noteId, jobId, status: 'error', facts: 0 })
          setNotice({ text: `已存入笔记，但没能进入知识库。${(job.detail || '').slice(0, 160)}`, error: true })
          return
        }
      } catch { /* a missed poll is not a failed job; ask again */ }
      if (Date.now() - startedAt > KB_SYNC_GIVE_UP_MS) { setKbSync(null); return }
      kbSyncTimer.current = window.setTimeout(() => void poll(), KB_SYNC_POLL_MS)
    }
    kbSyncTimer.current = window.setTimeout(() => void poll(), KB_SYNC_POLL_MS)
  }

  async function pasteIntoDraft() {
    if (busyRef.current) return
    busyRef.current = 'paste-note'
    setBusy('paste-note')
    setNotice(null)
    try {
      const text = window.memoketDesktop?.quickCapture
        ? await window.memoketDesktop.quickCapture.readClipboard()
        : await navigator.clipboard.readText()
      if (!mountedRef.current) return
      if (!text.trim()) { setNotice({ text: '剪贴板里没有文字。图片和文件可放进暂存架。', error: false }); return }
      const current = draftRef.current
      updateDraft({ ...current, content: current.content ? `${current.content}\n\n${text}` : text })
      editorRef.current?.focus()
    } catch {
      if (mountedRef.current) setNotice({ text: `无法读取剪贴板，可直接按 ${modifier}V 粘贴。`, error: true })
    } finally {
      busyRef.current = ''
      if (mountedRef.current) setBusy('')
    }
  }

  /** Insert at the caret with blank-line padding; a selection is replaced, its neighbours never are. Returns the caret after the insertion.
   *  A field that is not focused has no live caret (a click elsewhere just blurred it), so the text goes to the end instead of position 0. */
  function insertAtCaret(text: string) {
    const current = draftRef.current
    const editor = editorRef.current
    const live = !!editor && editor.hasFocus()
    const { start, end } = live ? editor.getSelection() : { start: current.content.length, end: current.content.length }
    const before = current.content.slice(0, start)
    const after = current.content.slice(end)
    const prefix = before && !/\s$/.test(before) ? '\n\n' : ''
    const suffix = after && !/^\s/.test(after) ? '\n\n' : ''
    const insertion = prefix + text + suffix
    updateDraft({ ...current, content: before + insertion + after })
    return start + insertion.length
  }

  function acceptClipboardSuggestion() {
    const candidate = clipboard.candidate
    if (!candidate || candidate.truncated || busyRef.current) return
    clipboard.dismiss()
    const caret = insertAtCaret(candidate.text)
    requestAnimationFrame(() => {
      editorRef.current?.focus()
      editorRef.current?.setSelection(caret)
    })
  }

  /** A fact enters the draft as its text plus the `[id]` marker the workspace resolves into provenance. */
  function citeFact(fact: Fact) {
    if (busyRef.current === 'save') { setNotice({ text: '这篇笔记正在保存，稍后再引用。', error: true }); return }
    const caret = insertAtCaret(`${fact.text} [${fact.id}]`)
    setMemoryOpen(false)
    setNotice({ text: '已引用到笔记，原文与来源一并保留。', error: false })
    void expand(true, 'capture').then(() => requestAnimationFrame(() => {
      editorRef.current?.focus()
      editorRef.current?.setSelection(caret)
    }))
  }

  /** A Claude reply goes into the draft at the caret, and the island turns to the notes so the insertion is seen. */
  function insertReply(text: string) {
    if (busyRef.current === 'save') { setNotice({ text: '这篇笔记正在保存，稍后再引用。', error: true }); return }
    const caret = insertAtCaret(text)
    setNotice({ text: '已引用到笔记。', error: false })
    void expand(true, 'capture').then(() => requestAnimationFrame(() => {
      editorRef.current?.focus()
      editorRef.current?.setSelection(caret)
    }))
  }

  /** A Claude reply becomes a note of its own, titled by its first line, and enters the knowledge base like any saved note. */
  async function saveReplyAsNote(text: string) {
    try {
      const title = text.split('\n').map(line => line.trim()).find(Boolean)?.replace(/^#+\s*/, '').slice(0, 80) || '会话摘录'
      const saved = await api.createNote(title, text)
      if (!mountedRef.current) return false
      setNotice({ text: '已存为笔记。', error: false })
      void enterKnowledge(saved.id)
      return true
    } catch (error) {
      if (mountedRef.current) setNotice({ text: `没能存为笔记。${errorText(error)}`, error: true })
      return false
    }
  }

  function selectAIMaterials() {
    if (busyRef.current) return
    if (!aiMounted) setAIRequest(undefined)
    setAIMounted(true)
    setNotice(null)
    setActionMenu(null)
    setAIOpen(true)
  }

  function openActionMenu(clientX: number, clientY: number) {
    if (busyRef.current) return
    if (leaveTimer.current) clearTimeout(leaveTimer.current)
    const bounds = rootRef.current!.getBoundingClientRect()
    const current = draftRef.current
    const { start, end } = editorRef.current?.getSelection() ?? { start: 0, end: 0 }
    const selection = current.content.slice(start, end)
    const useSelection = !!selection.trim()
    const useClipboard = !useSelection && !current.content.trim() && !!clipboard.candidate
    const text = useSelection ? selection : useClipboard ? clipboard.candidate!.text : current.content
    const scope = useSelection ? '选中文字' : useClipboard ? '刚刚复制' : '当前笔记'
    const source: api.DesktopComposeSource = { id: useSelection ? 'capture-selection' : useClipboard ? 'capture-clipboard' : 'capture-draft', kind: 'text', title: useSelection ? '选中文字' : useClipboard ? '刚刚复制的内容' : current.title.trim() || '当前草稿', text }
    const tooLong = Array.from(text).length + Array.from(source.title).length > 30_000
    const disabledReason = !text.trim() ? '先写下或复制一段内容' : useClipboard && clipboard.candidate?.truncated ? '剪贴板仅有节选，请先粘贴全文' : tooLong ? '材料较长，请选中需要处理的部分' : ''
    setActionMenu({ x: clientX - bounds.left, y: clientY - bounds.top, scope, source, disabledReason, start, end })
  }

  function closeActionMenu(restoreFocus: boolean) {
    const selection = actionMenu
    setActionMenu(null)
    if (restoreFocus && selection) {
      editorRef.current?.focus()
      editorRef.current?.setSelection(selection.start, selection.end)
    }
  }

  function runAIAction(action: api.DesktopAIAction) {
    if (!actionMenu || actionMenu.disabledReason || busyRef.current || aiGuard.current.busy) return
    aiTargetRef.current = { action, kind: actionMenu.source.id === 'capture-selection' ? 'selection' : actionMenu.source.id === 'capture-clipboard' ? 'clipboard' : 'draft', start: actionMenu.start, end: actionMenu.end, text: actionMenu.source.text }
    setAIApplied(null)
    setAIRequest({ id: `capture-${Date.now()}-${++aiRequestSequence.current}`, action, sources: [actionMenu.source] })
    setAIMounted(true)
    setNotice(null)
    closeActionMenu(true)
    setAIOpen(false)
  }

  /** Keep the first `max` non-empty lines: a continuation should read like a few more lines, not a new section. */
  function limitLines(text: string, max: number) {
    const kept: string[] = []
    let count = 0
    for (const line of text.split('\n')) {
      if (line.trim()) { if (count === max) break; count++ }
      kept.push(line)
    }
    return kept.join('\n').trimEnd()
  }

  /** Editor-triggered AI writes straight into the draft. 整理 replaces what it was given; everything else is inserted after it. */
  function applyAIResult(raw: string) {
    const target = aiTargetRef.current
    const action = target?.action ?? 'continue'
    const text = (action === 'continue' ? limitLines(raw, 5) : raw).trim()
    if (!text) return
    const before = draftRef.current
    const content = before.content
    const selectionValid = !!target && target.kind === 'selection' && content.slice(target.start, target.end) === target.text
    let next: string
    let caret: number
    if (action === 'organize' && (selectionValid || target?.kind !== 'selection')) {
      next = selectionValid ? content.slice(0, target!.start) + text + content.slice(target!.end) : text
      caret = selectionValid ? target!.start + text.length : text.length
    } else {
      const at = selectionValid ? target!.end : content.length
      const head = content.slice(0, at)
      const tail = content.slice(at)
      const gapBefore = !head ? '' : head.endsWith('\n\n') ? '' : head.endsWith('\n') ? '\n' : '\n\n'
      const gapAfter = !tail ? '' : tail.startsWith('\n\n') ? '' : tail.startsWith('\n') ? '\n' : '\n\n'
      next = head + gapBefore + text + gapAfter + tail
      caret = (head + gapBefore + text).length
    }
    updateDraft({ ...before, content: next })
    setAIApplied({ label: DESKTOP_AI_ACTIONS.find(({ id }) => id === action)?.label || 'AI', lines: text.split('\n').filter(line => line.trim()).length, text, before })
    aiTargetRef.current = null
    setAIRequest(undefined)
    setAIOpen(false)
    setAIMounted(false)
    if (document.hasFocus()) requestAnimationFrame(() => {
      editorRef.current?.focus()
      editorRef.current?.setSelection(caret)
    })
  }

  /** Take back exactly what the AI wrote when it is still there verbatim; otherwise restore the draft as it was before. */
  function undoAIResult() {
    if (!aiApplied || busyRef.current === 'save') return
    const current = draftRef.current
    const at = current.content.indexOf(aiApplied.text)
    if (at >= 0 && !aiApplied.before.content.includes(aiApplied.text)) {
      const head = current.content.slice(0, at).replace(/\n{1,2}$/, '')
      const tail = current.content.slice(at + aiApplied.text.length).replace(/^\n{1,2}/, '')
      updateDraft({ ...current, content: head && tail ? `${head}\n\n${tail}` : head + tail })
    } else updateDraft(aiApplied.before)
    setAIApplied(null)
    requestAnimationFrame(() => editorRef.current?.focus())
  }

  function insertAIResult(content: string) {
    if (busyRef.current === 'save' || !content.trim()) return
    const current = draftRef.current
    const separator = current.content && !current.content.endsWith('\n\n') ? current.content.endsWith('\n') ? '\n' : '\n\n' : ''
    updateDraft({ ...current, content: current.content + separator + content })
    setAIOpen(false)
    requestAnimationFrame(() => {
      editorRef.current?.focus()
      editorRef.current?.setSelection(draftRef.current.content.length)
    })
  }

  async function listWindows() {
    await expand(true, 'windows')
    if (!bridge || busyRef.current) return
    setWindowsLoaded(false)
    setWindowError('')
    busyRef.current = 'windows'
    setBusy('windows')
    try {
      const result = await bridge.listWindows()
      if (!mountedRef.current) return
      setCandidates(result.candidates || [])
      setWindowError(result.ok ? '' : result.error || '暂时无法读取窗口。')
      setWindowsLoaded(true)
    } catch (error) {
      if (mountedRef.current) { setWindowError(errorText(error)); setWindowsLoaded(true) }
    } finally {
      busyRef.current = ''
      if (mountedRef.current) setBusy('')
    }
  }

  function scheduleCollapse() {
    if (leaveTimer.current) clearTimeout(leaveTimer.current)
    leaveTimer.current = setTimeout(() => {
      leaveTimer.current = null
      if (!collapseRequested.current || !stateRef.current.expanded || keepOpenRef.current) return
      // Leaving hides the surface, never its retained draft, preview or AI task.
      // Short native interactions can defer closing, but must not consume the exit.
      if (Date.now() < showArrivalUntil.current || busyRef.current || pickingFiles.current || dragDepth.current > 0) { scheduleCollapse(); return }
      void expand(false, stateRef.current.panel, false)
    }, Math.max(260, showArrivalUntil.current - Date.now()))
  }
  collapseRef.current = () => { collapseRequested.current = true; scheduleCollapse() }
  expandRef.current = (expanded, panel, focus) => { void expand(expanded, panel, focus) }

  /** 拿主意 · 记下来：引文与结论进正在写的笔记，岛转到笔记让人看见落在哪。 */
  function insertDecision(text: string) {
    if (busyRef.current === 'save') { setNotice({ text: '这篇笔记正在保存，稍后再记。', error: true }); return }
    const caret = insertAtCaret(text)
    void expand(true, 'capture').then(() => {
      if (!mountedRef.current) return
      setNotice({ text: '已记到笔记。', error: false })
      requestAnimationFrame(() => {
        editorRef.current?.focus()
        editorRef.current?.setSelection(caret)
      })
    })
  }

  /** 拿主意 · 变成待办：进今天的待办，台面留在原地。 */
  function decisionToTask(text: string) {
    today.add(text)
    setNotice({ text: '已加入待办', error: false })
  }

  /** 拿主意 · 问 Claude 展开：题目与候选放进会话的输入框；面板还没挂上就先排着。 */
  function askClaude(text: string) {
    if (sessionRef.current) sessionRef.current.draft(text)
    else setAgentQueue({ kind: 'text', text })
    void expand(true, 'agent')
  }

  /** 笔记里的 AI 菜单也能拿主意：选中的文字，没选就是整篇草稿。 */
  function decideFromEditor() {
    if (!actionMenu) return
    const text = actionMenu.source.id === 'capture-selection' ? actionMenu.source.text : draftRef.current.content
    closeActionMenu(false)
    if (!text.trim()) { setNotice({ text: '先写下或选中一段文字，再拿主意。', error: true }); return }
    setDecideRequest({ text, source: '笔记', at: new Date().toISOString() })
    void expand(true, 'decide')
  }

  function dragDestination(event: DragEvent<HTMLElement>): DropDestination | null {
    const target = (event.target as HTMLElement).closest<HTMLElement>('[data-drop-destination]')?.dataset.dropDestination
    if (target === 'note' || target === 'agent' || target === 'shelf') return target
    const rect = rootRef.current?.getBoundingClientRect()
    if (!rect?.width) return null
    // 三等分：左 笔记、中 会话、右 暂存箱——左右两个位置不动，新来的放中间。
    const third = (event.clientX - rect.left) / rect.width
    return third < 1 / 3 ? 'note' : third < 2 / 3 ? 'agent' : 'shelf'
  }

  /** What is being dragged, as far as the browser tells us before the drop: a count and, when uniform, a kind. */
  function describeDrag(transfer: DataTransfer) {
    const items = Array.from(transfer.items || []).filter(item => item.kind === 'file')
    const count = items.length || transfer.files?.length || 0
    if (!count) return ''
    const images = items.filter(item => item.type.startsWith('image/')).length
    const pdfs = items.filter(item => item.type === 'application/pdf').length
    return `${count} ${count === images ? '张图片' : count === pdfs ? '份 PDF' : '个文件'}`
  }

  /** Say what a drop did, in the feedback line and on the collapsed pill, so releasing a file is never a silent act. */
  function announceDrop(files: File[], where: DropDestination) {
    const label = `${files.length} ${files.every(file => file.type.startsWith('image/')) ? '张图片' : '个文件'}`
    const text = where === 'note' ? `已附加 ${label}` : where === 'agent' ? `已交给 Claude · ${label}` : `已暂存 ${label}`
    if (where === 'note') setNotice({ text: `${text}到当前笔记，随笔记一起保存。`, error: false })
    if (where === 'agent') setNotice({ text: `${text}，随下一句一起发。`, error: false })
    setDropOutcome(text)
    if (dropOutcomeTimer.current) clearTimeout(dropOutcomeTimer.current)
    dropOutcomeTimer.current = setTimeout(() => { dropOutcomeTimer.current = null; if (mountedRef.current) setDropOutcome('') }, 4000)
  }

  function renewDragPresence() {
    dragRevision.current++
    if (dragExitTimer.current) clearTimeout(dragExitTimer.current)
    dragExitTimer.current = null
  }

  function scheduleDragExit() {
    if (dragExitTimer.current) clearTimeout(dragExitTimer.current)
    const revision = dragRevision.current
    dragExitTimer.current = setTimeout(() => {
      dragExitTimer.current = null
      if (revision !== dragRevision.current || !fileDragActive.current) return
      if (!bridge?.isPointerInside) { cancelDragOutside(); return }
      // Event coordinates can still be the last in-window point on native exits.
      void bridge.isPointerInside().then(inside => {
        if (mountedRef.current && fileDragActive.current && revision === dragRevision.current && !inside) cancelDragOutside()
      }).catch(() => {
        if (mountedRef.current && fileDragActive.current && revision === dragRevision.current) cancelDragOutside()
      })
    }, 80)
  }

  function hoverPanel(panel: CompanionPanel) {
    const currentPanel = localExpansion.current?.expanded ? localExpansion.current.panel : stateRef.current.panel
    if (!stateRef.current.expanded || currentPanel === panel || fileDragActive.current || dragDepth.current || pickingFiles.current) return
    // 拿主意的台面不因为鼠标掠过标签就换掉：那几张卡是刚算出来的，要点一下才离开。
    if (currentPanel === 'decide') return
    void expand(true, panel, false)
  }

  function incomingDrag(event: DragEvent<HTMLElement>) {
    // Internal drags are handled by the native drag-out bridge, never re-added.
    if (event.dataTransfer.types.includes('application/x-memoket-shelf-item')) return
    if (!event.dataTransfer.types.includes('Files') && (event.target as HTMLElement).matches('input, textarea')) return
    if (!event.dataTransfer.types.includes('Files') && !event.dataTransfer.types.includes('text/plain') && !event.dataTransfer.types.includes('text/uri-list')) return
    event.preventDefault()
    renewDragPresence()
    collapseRequested.current = false
    if (leaveTimer.current) clearTimeout(leaveTimer.current)
    if (event.dataTransfer.types.includes('Files')) {
      dragDepth.current = 1
      fileDragActive.current = true
      setFileDrag(true)
      setDragSummary(describeDrag(event.dataTransfer))
      setDropDestination(dragDestination(event))
      setDragging(true)
      setActionMenu(null)
      setShelfAddOpen(false)
      // Expose destinations without choosing one or changing the current panel.
      if (!stateRef.current.expanded) void expand(true, stateRef.current.panel, false)
      return
    }
    dragDepth.current++
    setDragging(true)
    if (!stateRef.current.expanded || stateRef.current.panel !== 'clipboard') void expand(true, 'clipboard', false)
  }

  async function drop(event: DragEvent<HTMLElement>) {
    if (!event.dataTransfer.types.includes('Files') && (event.target as HTMLElement).matches('input, textarea')) return
    event.preventDefault()
    const destination = dragDestination(event)
    resetDrag()
    if (event.dataTransfer.types.includes('application/x-memoket-shelf-item')) return
    // DataTransfer is only readable during the original drop event.
    const files = Array.from(event.dataTransfer.files)
    const text = event.dataTransfer.getData('text/plain') || event.dataTransfer.getData('text/uri-list')
    if (event.dataTransfer.types.includes('Files')) {
      if (!files.length) { setNotice({ text: '未收到可读取的文件，请拖入文件，或使用附件按钮选择。', error: true }); return }
      if (!destination) { setNotice({ text: '请把文件放到左侧笔记区、中间的会话，或右侧暂存箱。', error: true }); return }
      if (destination === 'note') {
        await expand(true, 'capture', false)
        attachFiles(files)
        announceDrop(files, 'note')
        return
      }
      if (destination === 'agent') {
        if (!agent) { setNotice({ text: '交给 Claude 需要桌面版。', error: true }); return }
        await expand(true, 'agent', false)
        setAgentQueue({ kind: 'files', files })
        return
      }
      if (busyRef.current) { setNotice({ text: '暂存箱正在处理上一项操作，请稍后再放入。', error: true }); return }
      await expand(true, 'clipboard', false)
      if (!bridge) { setNotice({ text: '暂存文件需要桌面版；附加到笔记可直接在这里使用。', error: true }); return }
      if (await action('drop', () => bridge.addFiles(files), '已复制到暂存箱。')) announceDrop(files, 'shelf')
      return
    }
    await expand(true, 'clipboard', false)
    if (!bridge) { setNotice({ text: '文件和文字暂存需要桌面版。浏览器预览不会读取或保存拖入的文件。', error: true }); return }
    if (text.trim()) await action('drop', () => bridge.addText(text), '已暂存。')
    else setNotice({ text: '没有收到可暂存的文件或文字。', error: true })
  }

  function dragOut(event: DragEvent<HTMLElement>, item: CompanionItem) {
    const button = (event.target as HTMLElement).closest('button')
    if (button && !button.classList.contains('dc-item-preview')) { event.preventDefault(); return }
    suppressPreviewClick.current = true
    if (item.kind === 'text' || item.kind === 'link') {
      event.dataTransfer.setData('application/x-memoket-shelf-item', item.id)
      event.dataTransfer.setData('text/plain', item.text || item.url || '')
      if (item.url) event.dataTransfer.setData('text/uri-list', item.url)
      return
    }
    event.preventDefault()
    if (bridge && !item.missing) void action(`drag-${item.id}`, () => bridge.startDrag(item.id))
  }

  const shelfTerms = shelfQuery.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
  const items = [...state.items].sort((a, b) => b.createdAt.localeCompare(a.createdAt)).filter((item) => {
    const searchable = [item.title, item.text, item.url, item.path].filter(Boolean).join('\n').toLocaleLowerCase()
    return shelfTerms.every((term) => searchable.includes(term))
  })
  const feedback = state.storageError || notice?.text
  const feedbackError = notice?.error || !!state.storageError
  const isShelfPanel = surface === 'shelf' || state.panel === 'clipboard' || state.panel === 'windows'
  const tabIndex = state.panel === 'capture' ? 0 : state.panel === 'agent' ? 2 : state.panel === 'tasks' ? 3 : state.panel === 'decide' ? lastTab.current : 1
  // The collapsed pill says one thing: what is happening (a drop, AI, an upload) or, failing that, the next to-do.
  const uploading = attachmentJobs.some(job => job.status === 'uploading')
  const entering = kbSync?.status === 'running'
  const doneCount = today.tasks.filter(task => task.done).length
  const deciding = decideState.phase === 'thinking' || !!decidePending
  const liveText = decideLive ? (decideLive.text || `${decideLive.origin === 'screenshot' ? '截图' : '剪贴板里的图片'}${decideLive.source ? ` · ${decideLive.source}` : ''}`) : ''
  const hint = dropOutcome ? dropOutcome : aiState.busy ? 'AI 处理中' : deciding ? (decidePending === 'screenshot' ? '框一块屏幕' : '正在拿主意') : decideEmptyHint ? decideEmptyHint : agentRunning ? 'Claude 思考中' : uploading ? '正在附加' : entering ? '正在进入知识库' : decideHint ? decideHint : aiState.phase === 'ready' ? 'AI 已完成' : nextTask ? clipHint(nextTask.text) : today.tasks.length ? '今天的事都做完了' : '随手记'
  const hintTone = aiState.busy || deciding || agentRunning || uploading || entering ? 'true' : aiState.phase === 'ready' || dropOutcome || decideHint || decideEmptyHint ? 'ready' : undefined
  const previewItem = preview?.source === 'shelf' ? state.items.find(item => item.id === preview.id) : undefined
  const previewWindow = preview?.source === 'window' ? candidates.find(candidate => candidate.id === preview.id) : undefined
  const previewContent: PreviewContent | undefined = previewItem || (previewWindow ? { kind: 'window', title: previewWindow.title, thumbnail: previewWindow.preview, previewStatus: previewWindow.preview ? 'ready' : 'unavailable', previewError: previewWindow.previewError } : undefined)

  return (
    <section ref={rootRef} className={'dc-companion ' + (surface === 'top' ? 'dc-top' : 'dc-shelf') + (state.expanded ? ' dc-expanded' : '') + (dragging ? ' dc-dragging' : '')}
      aria-label={surface === 'top' ? '桌面浮条' : '桌面暂存架'}
      onMouseEnter={() => {
        collapseRequested.current = false
        if (leaveTimer.current) clearTimeout(leaveTimer.current)
        if (hoverTimer.current) clearTimeout(hoverTimer.current)
        if (!stateRef.current.expanded) hoverTimer.current = setTimeout(() => { void expand(true, stateRef.current.panel, false) }, 120)
      }}
      onMouseLeave={() => {
        if (hoverTimer.current) clearTimeout(hoverTimer.current)
        if (fileDragActive.current) scheduleDragExit()
        collapseRef.current()
      }}
      onDragEnter={incomingDrag}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes('application/x-memoket-shelf-item')) return
        if (!event.dataTransfer.types.includes('Files') && (event.target as HTMLElement).matches('input, textarea')) return
        event.preventDefault()
        event.dataTransfer.dropEffect = 'copy'
        if (event.dataTransfer.types.includes('Files')) {
          if (!fileDragActive.current) incomingDrag(event)
          renewDragPresence()
          collapseRequested.current = false
          if (leaveTimer.current) clearTimeout(leaveTimer.current)
          setDropDestination(dragDestination(event))
        }
      }}
      onDragLeave={(event) => {
        event.preventDefault()
        if (fileDragActive.current) {
          if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return
          scheduleDragExit()
        } else {
          dragDepth.current = Math.max(0, dragDepth.current - 1)
          if (!dragDepth.current) { resetDrag(); collapseRef.current() }
        }
      }}
      onDragEnd={() => { resetDrag(); if (collapseRequested.current) scheduleCollapse() }}
      onCompositionStart={() => { composingRef.current = true }}
      onCompositionEnd={() => { composingRef.current = false }}
      onDrop={(event) => void drop(event)}
      onKeyDown={(event) => {
        if (event.nativeEvent.isComposing) return
        if (event.key === 'Escape') { event.preventDefault(); if (fileDragActive.current) resetDrag(); else if (actionMenu) closeActionMenu(true); else if (shelfAddOpen) { setShelfAddOpen(false); shelfAddTrigger.current?.focus() } else if (previewRef.current) closePreview(); else if (shelfEntryOpen) { setShelfEntryOpen(false); shelfAddTrigger.current?.focus() } else if (shelfSearchOpen) { setShelfSearchOpen(false); setShelfQuery('') } else if (memoryOpen && state.panel === 'capture') setMemoryOpen(false); else if (aiOpen && state.panel === 'capture') setAIOpen(false); else void expand(false) }
        if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && state.panel === 'capture') { event.preventDefault(); if (!actionMenu) void saveDraft() }
        if ((event.metaKey || event.ctrlKey) && !event.shiftKey && !event.altKey && /^[1-4]$/.test(event.key)) { event.preventDefault(); void expand(true, (['capture', 'clipboard', 'agent', 'tasks'] as const)[Number(event.key) - 1]) }
      }}>
        <button className="dc-island-trigger" style={{ '--dc-done': today.tasks.length ? doneCount / today.tasks.length : 0 } as CSSProperties} inert={state.expanded} aria-hidden={state.expanded} tabIndex={state.expanded ? -1 : 0} aria-label="展开桌面口袋" aria-describedby={hintId} title="悬停展开，也可点击或按 Enter" onClick={() => void expand(true)}>
          <span className="dc-mark"><Icon n="bx-layer-plus" /></span>
          {decideLive?.image && <img className="dc-live-thumb" src={decideLive.image} alt="" />}
          <span id={hintId} role="status" className={'dc-island-hint' + (deciding ? ' dc-hint-thinking' : '') + (decideLive ? ' dc-live-text' : '')} title={decideLive ? liveText : undefined}>{!hintTone && !decideLive && nextTask && <i className="dc-hint-ring" aria-hidden="true" />}{decideLive ? liveText : hint}</span><i className="dc-presence" data-live={decideLive ? 'true' : hintTone} />
        </button>
      <div className="dc-stage" inert={!state.expanded} aria-hidden={!state.expanded}>
        <header className="dc-topbar">
          <button type="button" className="dc-mark dc-mark-button" aria-label="打开完整笔记库" title="打开完整笔记库" onClick={() => { if (bridge) void bridge.openWorkspace().catch(() => setNotice({ text: '暂时无法打开完整笔记库。', error: true })); else window.open(`/?user=${encodeURIComponent(api.getUser())}`, '_blank', 'noopener') }}><Icon n="bx-layer-plus" /></button>
          <nav className={'dc-nav' + (state.panel === 'decide' ? ' dc-nav-quiet' : '')} aria-label="浮条快捷操作" style={{ '--dc-tab': tabIndex } as CSSProperties}>
            <button className={state.expanded && state.panel === 'capture' ? 'dc-nav-active' : ''} title="悬停进入笔记 · 右键调用 AI · ⌘1" aria-label="随手记" onMouseEnter={() => hoverPanel('capture')} onClick={() => void expand(true, 'capture')}><span className="dc-action-label">笔记</span>{aiMounted && (aiState.busy || aiState.phase === 'ready' || aiState.phase === 'error') && <span className="dc-ai-nav-status" role="status" data-state={aiState.busy ? 'busy' : aiState.phase === 'ready' ? 'ready' : 'error'} aria-label={aiState.busy ? 'AI 正在后台处理' : aiState.phase === 'ready' ? 'AI 结果已就绪' : 'AI 任务需要处理'} title={aiState.busy ? 'AI 正在后台处理' : aiState.phase === 'ready' ? '结果已就绪，返回笔记查看' : '返回笔记查看任务状态'} />}</button>
            <button className={state.panel === 'clipboard' || state.panel === 'windows' ? 'dc-nav-active' : ''} title="悬停进入暂存箱 · ⌘2" aria-label="暂存架" onMouseEnter={() => hoverPanel('clipboard')} onClick={() => void expand(true, 'clipboard')}><span className="dc-action-label">暂存箱</span>{state.items.length > 0 && <span className="dc-count">{state.items.length}</span>}</button>
            <button className={state.expanded && state.panel === 'agent' ? 'dc-nav-active' : ''} title="悬停进入会话 · 和 Claude 直接对话，回复可引用到笔记 · ⌘3" aria-label="会话" onMouseEnter={() => hoverPanel('agent')} onClick={() => void expand(true, 'agent')}><span className="dc-action-label">会话</span></button>
            <button className={state.expanded && state.panel === 'tasks' ? 'dc-nav-active' : ''} title={nextTask ? `下一件：${nextTask.text} · ⌘4` : '悬停进入待办 · ⌘4'} aria-label="待办" onMouseEnter={() => hoverPanel('tasks')} onClick={() => void expand(true, 'tasks')}><span className="dc-action-label">待办</span>{today.open.length > 0 && <span className="dc-count">{today.open.length}</span>}</button>
          </nav>
          <div className="dc-head-tools">
          <button className="dc-icon dc-keep-open" aria-label="固定展开" aria-pressed={keepOpen} title={keepOpen ? '取消固定，鼠标离开后自动收起' : '固定展开，鼠标离开时保留'} onClick={() => setKeepOpen((value) => !value)}><Icon n="bx-pin" /></button>
          <button className="dc-icon" title="收起浮条 · Esc，AI 任务会继续" aria-label="收起浮条" disabled={!!busy} onClick={() => void expand(false)}><Icon n="bx-chevron-up" /></button>
          </div>
        </header>

      <div className="dc-panel" hidden={!panelMounted} inert={!state.expanded || fileDrag} aria-hidden={!state.expanded || fileDrag}>
          {surface === 'top' && state.panel === 'capture' && (
            <form className="dc-capture" onSubmit={(event) => { event.preventDefault(); void saveDraft() }}>
              <input className="dc-title-input" aria-label="随手记标题" placeholder="标题" value={draft.title} maxLength={180} disabled={!!busy} onChange={(event) => updateDraft({ ...draftRef.current, title: event.target.value })} />
              <CompanionDraftEditor editorRef={editorRef} value={draft.content} disabled={busy === 'save'} busy={!!busy}
                candidate={clipboard.candidate} modifier={modifier} onAccept={acceptClipboardSuggestion} onDismiss={clipboard.dismiss}
                onChange={content => updateDraft({ ...draftRef.current, content })}
                onContextMenu={(x, y) => openActionMenu(x, y)} />
              {(!!draft.attachments?.length || attachmentJobs.length > 0) && <div className="dc-note-attachments" role="region" aria-label="笔记附件">
                {draft.attachments?.map(attachment => <div className="dc-note-attachment" key={attachment.id}>
                  <a href={attachment.url} target="_blank" rel="noreferrer" title={`打开附件 ${attachment.name}`}>
                    <AttachmentThumbnail attachment={attachment} />
                    <span><strong>{attachment.name}</strong><small>{attachmentSize(attachment.bytes)} · 已附加</small></span>
                  </a>
                  <button className="dc-icon" type="button" aria-label={`移除附件 ${attachment.name}`} title="从当前草稿移除，原文件不受影响" disabled={busy === 'save'} onClick={() => removeAttachment(attachment.id)}><Icon n="bx-x" /></button>
                </div>)}
                {attachmentJobs.map(job => <div className={'dc-note-attachment dc-attachment-pending' + (job.status === 'error' ? ' dc-attachment-failed' : '')} key={job.id}>
                  <span className="dc-attachment-extension"><Icon n={job.status === 'error' ? 'bx-info-circle' : 'bx-loader-circle'} /></span>
                  <span className="dc-attachment-job-text"><strong>{job.file.name}</strong><small role={job.status === 'error' ? 'alert' : 'status'} title={job.error}>{job.status === 'error' ? `附加失败：${job.error}` : `正在附加 ${job.file.name}…`}</small></span>
                  {job.status === 'error' && <button className="dc-icon" type="button" aria-label={`重试附件 ${job.file.name}`} title="重试这个附件" onClick={() => void uploadAttachment(job)}><Icon n="bx-refresh" /></button>}
                  <button className="dc-icon" type="button" aria-label={`${job.status === 'error' ? '移除失败附件' : '取消附件'} ${job.file.name}`} title={job.status === 'error' ? '移除失败项' : '取消附加'} onClick={() => cancelAttachment(job.id)}><Icon n="bx-x" /></button>
                </div>)}
              </div>}
              {draftError && <p className="dc-draft-error" role="alert">{draftError}</p>}
              <CompanionMemory content={draft.content} enabled={state.expanded && state.panel === 'capture'} expanded={memoryOpen} onExpandedChange={(open) => { setMemoryOpen(open); if (open) setAIOpen(false) }} onCite={citeFact} />
              <footer className="dc-editor-footer">
                <button type="button" className="dc-editor-ai-trigger" data-companion-ai-trigger aria-label="AI 操作" aria-haspopup="menu" aria-expanded={!!actionMenu} disabled={!!busy} title="选中文字后右键，也可从这里调用 AI" onMouseDown={event => event.preventDefault()} onClick={event => { if (actionMenu) { closeActionMenu(true); return }; const rect = event.currentTarget.getBoundingClientRect(); openActionMenu(rect.left, rect.bottom + 4) }}><Icon n="bx-brain" />AI</button>
                <button type="button" className="dc-icon" aria-label="粘贴文字" disabled={!!busy} title="粘贴剪贴板文字" onClick={() => void pasteIntoDraft()}><Icon n="bx-copy" /></button>
                <button type="button" className="dc-icon" aria-label="添加笔记附件" disabled={busy === 'save'} title="添加附件，也可拖入浮条左侧" onClick={() => { pickingFiles.current = true; noteFilesRef.current?.click() }}><Icon n="bx-paperclip" /></button>
                <span className="dc-editor-status">{attachmentJobs.some(job => job.status === 'error') ? '附件未完成 · 可重试' : attachmentJobs.length ? '正在附加 · 可继续编辑' : draft.attachments?.length ? `${draft.attachments.length} 个附件` : ''}</span>
                <button className="dc-primary" type="submit" disabled={!!busy || !!attachmentJobs.length || (!draft.title.trim() && !draft.content.trim() && !draft.attachments?.length)} title={attachmentJobs.length ? '请等待附件完成，或重试／移除失败项' : `存入笔记 · ${modifier} ↵`}>{busy === 'save' ? '正在保存…' : '存入笔记'}</button>
              </footer>
              {aiApplied && <div className="dc-ai-applied" aria-live="polite">
                <Icon n="bx-check" /><strong>{aiApplied.label}</strong><span>已写入 {aiApplied.lines} 行</span>
                <button type="button" aria-label="撤销这次写入" title="把这次写进正文的内容拿掉，其余保留" disabled={busy === 'save'} onClick={undoAIResult}>撤销</button>
                <button type="button" className="dc-icon" aria-label="收起这条提示" title="收起，保留写入的内容" onClick={() => setAIApplied(null)}><Icon n="bx-x" /></button>
              </div>}
            </form>
          )}

          {surface === 'top' && state.panel === 'tasks' && <CompanionTasks store={today} focusRequested={tasksFocusRequested} onEscape={() => void expand(false)} />}

          {surface === 'top' && decideRequest && <div className="dc-decide-host" hidden={state.panel !== 'decide'} inert={state.panel !== 'decide'} aria-hidden={state.panel !== 'decide'}>
            <CompanionDecide request={decideRequest} active={state.expanded && state.panel === 'decide'} onInsert={insertDecision} onTask={decisionToTask} onAskClaude={askClaude} onEscape={() => void expand(false)} onPhase={onDecidePhase} hotkey={decideHotkey} tap={decideTap} />
          </div>}

          {surface === 'top' && sessionMounted && <div className="dc-session-host" hidden={state.panel !== 'agent'} inert={state.panel !== 'agent'} aria-hidden={state.panel !== 'agent'}>
            <CompanionSession handleRef={sessionRef} bridge={agent} active={state.expanded && state.panel === 'agent'} focusRequested={sessionFocusRequested} onEscape={() => void expand(false)}
              onInsert={insertReply} onSaveNote={saveReplyAsNote} onRunningChange={setAgentRunning} />
          </div>}

          {aiMounted && <div className="dc-ai-host" hidden={state.panel !== 'capture'} inert={state.panel !== 'capture'}>
            <CompanionAINote compact direct={!!aiRequest} expanded={aiOpen} onExpandedChange={setAIOpen} items={state.items} initialRequest={aiRequest} onStateChange={onAIState} onClose={() => setAIOpen(false)} onInsert={busy === 'save' ? undefined : aiRequest ? applyAIResult : insertAIResult} />
          </div>}

          {isShelfPanel && (
            <>
            {preview && <div className="dc-preview-panel" role="region" aria-label="内容预览">
              <header className="dc-preview-header"><button ref={previewBack} type="button" aria-label={preview.source === 'window' ? '返回窗口列表' : '返回暂存架'} onClick={closePreview}><Icon n="bx-left-arrow-alt" />返回</button><div><h2>{previewContent?.title || '内容已移除'}</h2><span>{previewContent?.kind === 'window' ? '窗口截图 · 不会实时更新' : previewContent ? KIND_LABEL[previewContent.kind] : '这个项目已不在当前列表中'}</span></div><kbd>Esc</kbd></header>
              <div className="dc-preview-stage" draggable={!!bridge && !!previewItem && !previewItem.missing && (previewItem.kind === 'file' || previewItem.kind === 'image')} onDragStart={(event) => { if (previewItem && (previewItem.kind === 'file' || previewItem.kind === 'image')) dragOut(event, previewItem) }}>{previewContent ? <ContentPreview item={previewContent} enlarged snapshotLabel={preview.source === 'window' ? '最近读取的窗口截图' : undefined} /> : <p className="dc-empty">这条内容已经移除，可以返回继续查看。</p>}</div>
              <footer className="dc-preview-footer">
                <span>{!previewContent ? '可返回选择其他内容' : previewItem?.missing ? previewItem.storage === 'copy' ? '暂存副本不可用' : '原文件路径已失效' : previewContent?.kind === 'link' ? '链接与摘录保留在本机' : previewContent?.kind === 'window' ? '截图保留的是当时的画面' : previewContent?.kind === 'text' ? '已暂存的完整文字' : previewItem?.storage === 'copy' ? '独立副本 · 原件保留' : '原位置引用 · 尚未复制'}</span>
                <div className="dc-preview-actions">
                  {previewWindow && <button type="button" className="dc-primary" disabled={!!busy || !bridge} title={bridge ? '暂存这个窗口，稍后唤回' : '桌面版支持暂存窗口'} onClick={() => { if (bridge) void action('add-window', () => bridge.addWindow(previewWindow.id), '已暂存窗口。') }}><Icon n="bx-plus" />暂存窗口</button>}
                  {previewItem && <>
                    {(previewItem.kind === 'text' || previewItem.kind === 'link') && <button type="button" disabled={!!busy || !bridge} title="复制暂存的完整内容" onClick={() => { if (bridge) void action(`copy-${previewItem.id}`, () => bridge.copy(previewItem.id), '已复制。') }}><Icon n="bx-copy" />复制</button>}
                    {previewItem.kind === 'window' && <button type="button" disabled={!!busy || !bridge} title="回到这个实际窗口" onClick={() => { if (bridge) void action(`recall-${previewItem.id}`, () => bridge.recallWindow(previewItem.id), '已请求唤回窗口。') }}><Icon n="bx-window-open" />唤回窗口</button>}
                    {(previewItem.kind === 'file' || previewItem.kind === 'image') && <button type="button" disabled={!!busy || !bridge || !!previewItem.missing} title={previewItem.missing ? '文件路径失效' : previewItem.storage === 'copy' ? '在文件管理器中显示暂存副本' : '在文件管理器中显示原文件'} onClick={() => { if (bridge) void action(`reveal-${previewItem.id}`, () => bridge.reveal(previewItem.id)) }}>{previewItem.storage === 'copy' ? '副本位置' : '位置'}</button>}
                    {(previewItem.kind === 'file' || previewItem.kind === 'image') && !previewItem.missing && <button type="button" disabled={!!busy || !bridge || previewItem.previewStatus === 'loading'} title={previewItem.previewStatus === 'loading' ? '正在生成内容预览' : '重新生成这个文件的内容预览'} onClick={() => { if (bridge) void action(`preview-${previewItem.id}`, () => bridge.refreshPreview(previewItem.id)) }}>{previewItem.previewStatus === 'unavailable' ? '重试预览' : '刷新预览'}</button>}
                    {(previewItem.kind === 'file' || previewItem.kind === 'image' || previewItem.kind === 'link') && <button type="button" disabled={!!busy || !bridge || !!previewItem.missing} title={previewItem.missing ? '文件路径失效' : previewItem.kind === 'link' ? '用浏览器打开原网页' : previewItem.storage === 'copy' ? '用默认应用打开暂存副本' : '用默认应用打开原文件'} onClick={() => { if (bridge) void action(`open-${previewItem.id}`, () => bridge.open(previewItem.id)) }}><Icon n="bx-link-external" />{previewItem.kind === 'link' ? '打开网页' : previewItem.storage === 'copy' ? '打开副本' : '打开原文件'}</button>}
                  </>}
                </div>
              </footer>
            </div>}
            <div className={'dc-shelf-panel' + (state.items.length ? ' dc-shelf-populated' : '')} hidden={!!preview}>
              {state.panel !== 'windows' && <div className="dc-shelf-toolbar">
                <div><strong>{state.items.length ? `${state.items.length} 件` : '暂存箱'}</strong><span role="status">{busy === 'drop' || busy === 'files' ? '正在复制到暂存架…' : busy.startsWith('drag-') ? '正在准备拖出…' : shelfQuery ? `找到 ${items.length} 件` : ''}</span></div>
                <div>
                  {state.items.length > 0 && <button className="dc-icon" type="button" aria-label="搜索暂存内容" aria-expanded={shelfSearchOpen} title="搜索暂存的物品" onClick={() => { setShelfSearchOpen(value => !value); setShelfQuery('') }}><Icon n="bx-search" /></button>}
                  <button ref={shelfAddTrigger} type="button" aria-label="添加暂存内容" aria-haspopup="menu" aria-expanded={shelfAddOpen} disabled={!!busy} title="选择文件、剪贴板或窗口，也可以直接拖入" onClick={() => setShelfAddOpen(value => !value)}><Icon n="bx-plus" />添加</button>
                </div>
                {shelfAddOpen && <div ref={shelfAddRef} className="dc-shelf-add-menu" role="menu" aria-label="添加暂存内容" onKeyDown={event => {
                  event.stopPropagation()
                  if (event.key === 'Escape' || event.key === 'Tab') { event.preventDefault(); setShelfAddOpen(false); shelfAddTrigger.current?.focus(); return }
                  const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')]
                  const current = buttons.indexOf(document.activeElement as HTMLButtonElement)
                  const next = event.key === 'ArrowDown' ? (current + 1) % buttons.length : event.key === 'ArrowUp' ? (current - 1 + buttons.length) % buttons.length : event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : -1
                  if (next >= 0) { event.preventDefault(); buttons[next]?.focus() }
                }}>
                  <button type="button" role="menuitem" tabIndex={-1} disabled={!bridge || !!busy} title={bridge ? '选择要暂存的本机文件' : '选择文件需要桌面版'} onClick={() => { setShelfAddOpen(false); pickingFiles.current = true; filesRef.current?.click() }}><Icon n="bx-folder-open" />选择文件</button>
                  <button type="button" role="menuitem" tabIndex={-1} disabled={!bridge || !!busy} title={bridge ? '暂存剪贴板的文字或图片' : '暂存剪贴板需要桌面版'} onClick={() => { setShelfAddOpen(false); if (bridge) void action('clipboard', () => bridge.pasteClipboard(), '已暂存剪贴板内容。') }}><Icon n="bx-copy" />暂存剪贴板</button>
                  <button type="button" role="menuitem" tabIndex={-1} disabled={!bridge || !!busy} title={bridge ? '暂存窗口，稍后回到它' : '暂存窗口需要桌面版'} onClick={() => { setShelfAddOpen(false); void listWindows() }}><Icon n="bx-window-open" />暂存窗口</button>
                  <button type="button" role="menuitem" tabIndex={-1} disabled={!bridge || !!busy} title={bridge ? '暂时保留一段文字或链接' : '暂存文字需要桌面版'} onClick={() => { setShelfAddOpen(false); setShelfEntryOpen(true) }}><Icon n="bx-link" />文字或链接</button>
                </div>}
              </div>}
              {state.panel === 'windows' ? (
                <div className="dc-window-picker">
                  <div className="dc-list-caption"><button onClick={() => void expand(true, 'clipboard')}><Icon n="bx-left-arrow-alt" />返回暂存架</button><button disabled={!!busy} title="重新读取可用窗口" onClick={() => void listWindows()}>刷新</button></div>
                  {busy === 'windows' && <p className="dc-empty">正在读取可用窗口…</p>}
                  {windowError && <p className="dc-browser-note" role="alert">{windowError}</p>}
                  {windowsLoaded && !windowError && !candidates.length && <p className="dc-empty">暂时没有可暂存的窗口。</p>}
                  <div className="dc-window-grid">{candidates.map((candidate) => <article className="dc-window-choice" key={candidate.id}>
                    <button type="button" className="dc-window-preview" aria-label={`预览窗口 ${candidate.title}`} title="在口袋中放大这张窗口截图" onPointerDown={() => { suppressPreviewClick.current = false }} onClick={(event) => openPreview({ source: 'window', id: candidate.id }, event.currentTarget)}><ContentPreview item={{ kind: 'window', title: candidate.title, thumbnail: candidate.preview, previewStatus: candidate.preview ? 'ready' : 'unavailable', previewError: candidate.previewError }} snapshotLabel="最近读取的窗口截图" /></button>
                    <div className="dc-window-meta"><strong title={candidate.title}>{candidate.title}</strong><button type="button" disabled={!!busy || !bridge} title={bridge ? '暂存这个窗口，稍后唤回' : '桌面版支持暂存窗口'} aria-label={`暂存窗口 ${candidate.title}`} onClick={() => { if (bridge) void action('add-window', () => bridge.addWindow(candidate.id), '已暂存窗口。稍后可从这里唤回。') }}><Icon n="bx-plus" /></button></div>
                  </article>)}</div>
                </div>
              ) : (
                <>
                  <input ref={filesRef} className="dc-file-input" type="file" multiple aria-label="选择要暂存的文件" disabled={!bridge || !!busy} onChange={(event) => { pickingFiles.current = false; const files = Array.from(event.target.files || []); event.target.value = ''; if (bridge && files.length) void action('files', () => bridge.addFiles(files), '已放进暂存架。') }} />
                  {(!state.items.length || (dragging && !fileDrag)) && <div className={'dc-drop-zone' + (state.items.length ? ' dc-drop-zone-compact' : '')}><Icon n={dragging ? 'bx-plus' : 'bx-layer-plus'} /><span>{dragging ? '松开即可暂存文字' : '拖入文件、图片或窗口'}</span><small>拖入时放到右侧 · 也可从「添加」选择</small><button disabled={!bridge || !!busy} title={bridge ? '选择要暂存的本机文件' : '选择文件需要桌面版'} onClick={() => { pickingFiles.current = true; filesRef.current?.click() }}>选择文件</button></div>}
                  {shelfSearchOpen && <label className="dc-search-field dc-shelf-search"><Icon n="bx-search" /><input ref={shelfSearchRef} aria-label="查找暂存内容" placeholder="搜索名称或内容" value={shelfQuery} onChange={event => setShelfQuery(event.target.value)} /><button type="button" className="dc-icon" aria-label="关闭暂存搜索" title="关闭搜索，显示全部物品" onClick={() => { setShelfSearchOpen(false); setShelfQuery('') }}><Icon n="bx-x" /></button></label>}
                  <div ref={itemsRef} className="dc-items" hidden={!state.items.length} aria-label="已暂存的内容" aria-busy={busy === 'drop' || busy === 'files'}>
                    {!items.length && state.items.length > 0 && <div className="dc-empty"><p>没有找到匹配的暂存内容。</p><button onClick={() => setShelfQuery('')}>查看全部</button></div>}
                    {items.map((item) => (
                      <article className={'dc-item' + (item.missing ? ' dc-item-missing' : '') + (arrivedIds.includes(item.id) ? ' dc-item-arrived' : '')} key={item.id}
                        draggable={!!bridge && !item.missing && item.kind !== 'window'} onDragStart={(event) => dragOut(event, item)}
                        title={item.missing ? `${item.storage === 'copy' ? '暂存副本' : '原文件'}不可用，可从暂存架移除` : item.kind === 'file' || item.kind === 'image' ? item.storage === 'copy' ? '已保留独立副本，拖到其他应用使用' : '旧版原位置引用；重新拖入可保留独立副本' : item.kind === 'window' ? '点唤回返回这个窗口' : '拖动文字到其他应用，或点击复制'}>
                        <button type="button" className="dc-item-preview" aria-label={`预览 ${item.title || KIND_LABEL[item.kind]}`} title="点击放大查看，也可拖到其他应用" draggable={!!bridge && !item.missing && item.kind !== 'window'} onPointerDown={() => { suppressPreviewClick.current = false }} onClick={(event) => openPreview({ source: 'shelf', id: item.id }, event.currentTarget)}><ContentPreview item={item} /></button>
                        <div className="dc-item-content"><strong title={item.title}>{item.title || KIND_LABEL[item.kind]}</strong>
                          <div className="dc-item-actions">
                            {item.kind === 'window' ? <button disabled={!!busy || !bridge} onClick={() => { if (bridge) void action(`recall-${item.id}`, () => bridge.recallWindow(item.id), '已请求唤回窗口。') }}><Icon n="bx-window-open" />唤回</button>
                              : item.kind === 'text' || item.kind === 'link' ? <button disabled={!!busy || !bridge} onClick={() => { if (bridge) void action(`copy-${item.id}`, () => bridge.copy(item.id), '已复制。') }}><Icon n="bx-copy" />复制</button>
                              : <button disabled={!!busy || !bridge || !!item.missing} title={item.missing ? '文件无法访问' : item.storage === 'copy' ? '用默认应用打开暂存副本' : '用默认应用打开原文件'} onClick={() => { if (bridge) void action(`open-${item.id}`, () => bridge.open(item.id)) }}><Icon n="bx-link-external" />打开</button>}
                            {(item.kind === 'file' || item.kind === 'image') && <button disabled={!!busy || !bridge || !!item.missing} title={item.missing ? '文件无法访问' : item.storage === 'copy' ? '在文件管理器中显示暂存副本' : '在文件管理器中显示原文件'} onClick={() => { if (bridge) void action(`reveal-${item.id}`, () => bridge.reveal(item.id)) }}>位置</button>}
                            {item.kind === 'link' && <button disabled={!!busy || !bridge} title="打开原网页" onClick={() => { if (bridge) void action(`open-${item.id}`, () => bridge.open(item.id)) }}>打开</button>}
                          </div>
                        </div>
                        <button className="dc-icon dc-item-remove" aria-label={`从暂存架移除 ${item.title || KIND_LABEL[item.kind]}`} title={item.storage === 'copy' ? '移除暂存副本，原件不受影响' : '仅移出暂存架，不删除原文件'} disabled={!!busy || !bridge} onClick={() => { if (bridge) void action(`remove-${item.id}`, () => bridge.remove(item.id), '已移出暂存架。') }}><Icon n="bx-x" /></button>
                      </article>
                    ))}
                  </div>
                  {shelfEntryOpen && <form className="dc-shelf-entry" onSubmit={event => { event.preventDefault(); if (bridge && textToHold.trim()) void action('hold-text', async () => { const result = await bridge.addText(textToHold); if (result.ok) { setTextToHold(''); setShelfEntryOpen(false) }; return result }, '已暂存文字。') }}><input ref={shelfEntryRef} aria-label="要暂存的文字或链接" placeholder="放一段文字或链接…" value={textToHold} disabled={!bridge || !!busy} onChange={event => setTextToHold(event.target.value)} /><button className="dc-icon" type="submit" aria-label="暂存文字" title={!bridge ? '桌面版支持暂存文字' : !textToHold.trim() ? '先输入文字或链接' : '暂存文字或链接'} disabled={!bridge || !!busy || !textToHold.trim()}><Icon n="bx-plus" /></button><button className="dc-icon" type="button" aria-label="收起文字输入" title="收起输入，保留未提交的文字" onClick={() => { setShelfEntryOpen(false); shelfAddTrigger.current?.focus() }}><Icon n="bx-x" /></button></form>}
                  <footer className="dc-shelf-footer"><span title="新拖入的文件保留独立副本，不移动原件；旧版引用可重新拖入，创建独立副本">{state.items.some(item => (item.kind === 'file' || item.kind === 'image') && item.storage !== 'copy') ? '含旧版引用' : '独立副本 · 原件保留'}</span></footer>
                </>
              )}
            </div>
            </>
          )}
          {feedback && <p className={'dc-feedback' + (feedbackError ? ' dc-feedback-error' : '')} role={feedbackError ? 'alert' : 'status'}><Icon n={feedbackError ? 'bx-info-circle' : 'bx-check-circle'} /><span>{feedback}</span>{notice?.recovery && !feedbackError && bridge && <button type="button" disabled={!!busy} onClick={() => void action('recovery', () => bridge.revealRemoved())}>找回副本</button>}</p>}
        </div>
        {fileDrag && state.expanded && <div className="dc-drop-intent" role="region" aria-label="选择文件用途">
          <p className="dc-drop-summary">{dragSummary ? `正在拖入 ${dragSummary}` : '正在拖入文件'}</p>
          <div className="dc-drop-destinations">
            <div className="dc-drop-destination" data-drop-destination="note" data-active={dropDestination === 'note'}>
              <span className="dc-drop-destination-icon"><Icon n={dragSummary.endsWith('张图片') ? 'bx-image' : 'bx-paperclip'} /></span>
              <strong>附到笔记</strong>
              <span className="dc-drop-detail">{draft.title.trim() || '正在写的这一篇'}</span>
              <span className="dc-drop-outcome">{dropDestination === 'note' ? '松开，附件落在光标处' : '随笔记一起保存'}</span>
            </div>
            <div className="dc-drop-destination" data-drop-destination="agent" data-active={dropDestination === 'agent'}>
              <span className="dc-drop-destination-icon"><Icon n="bx-message-dots" /></span>
              <strong>交给 Claude</strong>
              <span className="dc-drop-detail">{agentRunning ? 'Claude 正在回答，随下一句发' : '随下一句一起发给它'}</span>
              <span className="dc-drop-outcome">{dropDestination === 'agent' ? '松开，文件进会话的工作目录' : '一起读，一起改'}</span>
            </div>
            <div className="dc-drop-destination" data-drop-destination="shelf" data-active={dropDestination === 'shelf'}>
              <span className="dc-drop-destination-icon"><Icon n="bx-layer-plus" /></span>
              <strong>放入暂存箱</strong>
              <span className="dc-drop-detail">{state.items.length ? `${state.items.length} 件 · 临时放一下` : '临时放一下，随时取走'}</span>
              <span className="dc-drop-outcome">{dropDestination === 'shelf' ? '松开，保留独立副本' : '原文件留在原处'}</span>
            </div>
          </div>
        </div>}
      </div>
      <input ref={noteFilesRef} className="dc-file-input" type="file" multiple aria-label="选择笔记附件" disabled={busy === 'save'} onChange={event => { pickingFiles.current = false; const files = Array.from(event.target.files || []); event.target.value = ''; attachFiles(files) }} />
      {actionMenu && state.expanded && state.panel === 'capture' && <CompanionAIMenu x={actionMenu.x} y={actionMenu.y} scope={actionMenu.scope} characters={Array.from(actionMenu.source.text || '').length} disabledReason={aiState.busy ? '当前 AI 任务正在处理，可在任务条中取消' : actionMenu.disabledReason} onAction={runAIAction} onClose={closeActionMenu} onMaterials={selectAIMaterials} onResume={pendingAI ? selectAIMaterials : undefined} onDecide={decideFromEditor} />}
    </section>
  )
}
