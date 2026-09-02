import { useCallback, useEffect, useRef, useState } from 'react'
import type { EditorView } from '@codemirror/view'
import * as api from './api'
import type { Folder, Note, Revision, TapMeta, VerifyFinding, WritingPlan, WritingSection } from './api'
import AudioRecorder from './components/AudioRecorder'
import CommandPalette from './components/CommandPalette'
import DocumentOutline from './components/DocumentOutline'
import MarkdownEditor from './components/MarkdownEditor'
import MarkdownToolbar from './components/MarkdownToolbar'
import WritingPlanPanel from './components/WritingPlanPanel'
import MemoryPanel from './components/MemoryPanel'
import RelatedMemory from './components/RelatedMemory'
import RevisionPanel, { applyRevision } from './components/RevisionPanel'
import SelectionMenu from './components/SelectionMenu'
import type { SelectionAction } from './components/SelectionMenu'
import SkeletonPanel from './components/SkeletonPanel'
import SettingsPanel from './components/SettingsPanel'
import SkillsPanel from './components/SkillsPanel'
import TapProvenance from './components/TapProvenance'
import Toaster from './components/Toaster'
import UserSwitcher from './components/UserSwitcher'
import VerifyPanel from './components/VerifyPanel'
import { toast, toastAction } from './toast'

// 后台自动生成的节流参数。骨架/编辑都是真实 LLM 调用（本地模型上约 8-15s），
// 不能跟着每次按键触发——用"停止输入 N 秒 + 内容变化够多"两条门槛，既保证
// 不是纯手动，又不会打字过程中疯狂重复调用模型。
const SKELETON_IDLE_MS = 8000
const SKELETON_MIN_CHARS = 30
const SKELETON_MIN_DELTA = 20
const EDIT_IDLE_MS = 15000
const EDIT_MIN_CHARS = 30
const EDIT_MIN_DELTA = 20

/** First non-empty line of a note's content, syntax markers stripped, for
 * the sidebar preview -- strip rather than render so it stays plain text
 * in a one-line ellipsis instead of showing raw "## " or "- " noise. */
function previewLine(content: string): string {
  const line = content.split('\n').find((l) => l.trim())
  if (!line) return ''
  return line.replace(/^#{1,6}\s+/, '').replace(/^[-*>]\s+/, '').trim()
}

/** 无限续写 harness 的运行状态——挂在 App 这一级而不是 WritingPlanPanel
 * 里，是直接回应"必须要写作计划那一页吗？？不能在后台吗？"：状态生命周期
 * 之前跟着弹窗组件的挂载/卸载走，关掉弹窗（或者干脆没打开过）就等于停止。
 * 提到 App 级别之后，运行本身不依赖弹窗是否打开——面板只是"看这个状态、
 * 控制这个状态"的一个视图，不是状态本身的持有者。导出给 WritingPlanPanel
 * 当 prop 类型用（type-only import，编译期擦除，不构成真正的运行时循环
 * 依赖）。 */
export type HarnessState = {
  folderId: string
  folderName: string
  plan: WritingPlan
  sections: WritingSection[]
  running: boolean
  currentSectionTitle: string
  currentNoteId: string
  preview: string
  waitingFirstToken: boolean
  follow: boolean
}

export default function App() {
  const [notes, setNotes] = useState<Note[]>([])
  const [folders, setFolders] = useState<Folder[]>([])
  // absence from this set = expanded (the default) -- tracking collapsed
  // folders instead of expanded ones means a newly created folder starts
  // open without needing to seed its id into any state first.
  const [collapsedFolders, setCollapsedFolders] = useState<Set<string>>(new Set())
  const [creatingFolder, setCreatingFolder] = useState(false)
  const [newFolderName, setNewFolderName] = useState('')
  const [noteQuery, setNoteQuery] = useState('')
  // null = not searching (show `notes` unfiltered); kept separate from
  // `notes`/`reload()` so typing a search term can never accidentally
  // trigger the mount effect's "open the first result" behavior.
  const [searchResults, setSearchResults] = useState<Note[] | null>(null)
  const [current, setCurrent] = useState<Note | null>(null)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')

  const [spine, setSpine] = useState('')
  const [beats, setBeats] = useState<string[]>([])
  // 智能续写每轮独立核对一次哪些结构节拍还没被正文实质覆盖（TRACELOG
  // [10]）——null 表示"还没跑过/不知道"，这时骨架面板只展示节拍是什么；
  // 有值之后骨架面板据此把已覆盖的节拍标出来，而不是一份看不出进度的
  // 静态清单。
  const [beatCoverage, setBeatCoverage] = useState<{ level: number; note: string } | null>(null)
  const [revisions, setRevisions] = useState<Revision[]>([])
  const [loading, setLoading] = useState<'' | 'skeleton' | 'edit' | 'tap' | 'ingest' | 'note-harness'>('')
  const [noteHarnessStatus, setNoteHarnessStatus] = useState('')
  const [tapMeta, setTapMeta] = useState<TapMeta | null>(null)
  const [writingPlanFolder, setWritingPlanFolder] = useState<Folder | null>(null)
  const [harness, setHarness] = useState<HarnessState | null>(null)
  const [skillsPanelOpen, setSkillsPanelOpen] = useState(false)
  const [settingsPanelOpen, setSettingsPanelOpen] = useState(false)
  const [job, setJob] = useState('')
  const [healthMsg, setHealthMsg] = useState('')
  const [focusMode, setFocusMode] = useState(false)
  const [selectionMenu, setSelectionMenu] = useState<{ x: number; y: number; text: string } | null>(null)
  const [selectionBusy, setSelectionBusy] = useState(false)
  const [verifyFindings, setVerifyFindings] = useState<VerifyFinding[] | null>(null)
  const [rightTab, setRightTab] = useState<'write' | 'memory' | 'kb'>('write')

  const editorViewRef = useRef<EditorView | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  // setTimeout callbacks close over whatever `loading` was at schedule time,
  // which is stale by the time they fire seconds later -- a ref mirror gives
  // them the live value so a background run doesn't stack on top of another
  // one (manual or auto) that's already in flight.
  const loadingRef = useRef(loading)
  useEffect(() => { loadingRef.current = loading }, [loading])
  const lastSkeletonContent = useRef('')
  const lastEditContent = useRef('')

  // 无限续写 harness 用的 ref 镜像——同样的"闭包过时"问题：
  // api.runWritingPlan() 的 handlers 对象在 runHarness() 调用那一刻创建
  // 一次，之后每个 SSE 事件都复用同一个闭包；如果 onDelta 里直接读
  // `current`/`harness.follow`，读到的永远是"点继续写那一刻"的值，用户
  // 之后手动切换笔记也不会让它知道。
  const harnessAbortRef = useRef<AbortController | null>(null)
  const currentRef = useRef<Note | null>(current)
  useEffect(() => { currentRef.current = current }, [current])
  const harnessFollowRef = useRef(true)
  useEffect(() => { harnessFollowRef.current = harness?.follow ?? true }, [harness?.follow])

  // ---------------------------------------------------------------- 加载

  const reload = useCallback(async () => {
    const list = await api.listNotes()
    setNotes(list)
    return list
  }, [])

  const reloadFolders = useCallback(async () => {
    const list = await api.listFolders()
    setFolders(list)
    return list
  }, [])

  function toggleFolderExpanded(id: string) {
    setCollapsedFolders((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  /** 无限续写按文件夹组织，之前唯一的入口是文件夹标题栏里那个不起眼的
   * 🚀 图标——没有文件夹的话那个图标根本不会出现在页面上任何地方，等于
   * 完全没有入口（反馈原文："我找不到那个按钮了"）。这是一个随时可见的
   * 侧栏按钮，自己判断该打开哪个文件夹的面板，而不是要求用户先知道"这个
   * 功能是按文件夹来的"这件事。 */
  function openWritingPlan() {
    if (folders.length === 0) {
      toast('无限续写按文件夹组织，先建一个文件夹')
      setCreatingFolder(true)
      return
    }
    if (folders.length === 1) {
      setWritingPlanFolder(folders[0])
      return
    }
    // 当前笔记所在的文件夹优先，没有的话退回第一个——都不是完美的选择，
    // 但比强迫用户先去研究"要点哪个文件夹的哪个图标"要好。
    const preferred = folders.find((f) => f.id === current?.folder_id) ?? folders[0]
    setWritingPlanFolder(preferred)
    if (folders.length > 1) toast(`已打开「${preferred.name}」的无限续写——想用别的文件夹，点文件夹标题栏自己的 🚀`)
  }

  /** 跑 harness——挂在 App 级别，不依赖 WritingPlanPanel 是否挂载（见
   * HarnessState 上面的注释）。跟随开着的时候，每次开始写一个新分段就把
   * 主编辑器切到那篇笔记，正文流式追加进 content（跟 magic tap 增量到达
   * 时的处理方式完全一样），是直接回应"不能在实际的笔记里看到流输出吗"。 */
  async function runHarness(folder: Folder) {
    if (harness?.running && harness.folderId === folder.id) {
      harnessAbortRef.current?.abort()
      return
    }
    // 本地模型同时处理多个生成请求只会互相拖慢，不是真的并行——一次只
    // 允许一个 harness 在跑，跑别的文件夹前先停掉当前这个。
    if (harness?.running) {
      toast(`「${harness.folderName}」的无限续写正在跑，先停掉那边再开始新的`, 'error')
      return
    }
    const got = await api.getWritingPlan(folder.id)
    if (!got.plan) { toast('这个文件夹还没有写作计划，先在面板里生成一个'); return }
    setHarness({
      folderId: folder.id, folderName: folder.name, plan: got.plan, sections: got.sections,
      running: true, currentSectionTitle: '', currentNoteId: '', preview: '', waitingFirstToken: true, follow: true,
    })
    const ctrl = new AbortController()
    harnessAbortRef.current = ctrl
    try {
      await api.runWritingPlan(folder.id, {
        onPlanLoaded: (p, s) => setHarness((h) => (h ? { ...h, plan: p, sections: s } : h)),
        onSectionStart: async (d) => {
          setHarness((h) => (h ? {
            ...h, waitingFirstToken: false, currentSectionTitle: d.title, currentNoteId: d.note_id, preview: '',
            sections: h.sections.map((s) => (s.id === d.section_id ? { ...s, status: 'in_progress', note_id: d.note_id } : s)),
          } : h))
          const alreadyViewing = currentRef.current?.id === d.note_id
          if (harnessFollowRef.current && !alreadyViewing) {
            try {
              const note = await api.getNote(d.note_id)
              await switchTo(note, true)
            } catch { /* 笔记刚建，偶尔还没来得及可读，跳过这次跟随，下一段还会再试 */ }
          } else if (alreadyViewing) {
            // 同一篇笔记的下一轮（section 没换，只是继续写）——本地累积的
            // content 在这轮新增量到达前要保证有空行分隔，原理和后端的
            // prompts.join_round_text() 一样：上一轮可能刚好停在一个
            // mermaid 代码块的收尾```上，直接拼接会跟下一轮内容粘在同一
            // 行，把代码块解析弄坏（TRACELOG [8]）。两边都要做，不然前端
            // 本地攒的内容会跟后端持久化的版本对不上。
            setContent((c) => (c ? c.replace(/\n*$/, '') + '\n\n' : c))
          }
        },
        onDelta: (noteId, text) => {
          setHarness((h) => (h ? { ...h, waitingFirstToken: false, preview: h.preview + text } : h))
          if (currentRef.current?.id === noteId) setContent((c) => c + text)
        },
        onSectionDone: (d) => {
          setHarness((h) => (h ? {
            ...h, waitingFirstToken: true,
            sections: h.sections.map((s) => (s.id === d.section_id ? { ...s, status: 'done', summary: d.summary } : s)),
          } : h))
          if (d.blocked) toast(`这个分段卡住了，需要你看一眼：${d.blocked_reason || '原因未知'}`, 'error')
          reload(); reloadFolders()
        },
        onPlanExtended: (newSections) => setHarness((h) => (h ? { ...h, sections: [...h.sections, ...newSections] } : h)),
        onPlanDone: (p) => {
          setHarness((h) => (h ? { ...h, plan: p } : h))
          toast(`「${folder.name}」的写作计划已完成`)
        },
      }, ctrl.signal)
    } catch (e) {
      if ((e as Error).name !== 'AbortError') toast('写作运行失败：' + e, 'error')
    } finally {
      setHarness((h) => (h ? { ...h, running: false, waitingFirstToken: false } : h))
      harnessAbortRef.current = null
      reload(); reloadFolders()
    }
  }

  async function confirmCreateFolder() {
    const name = newFolderName.trim()
    if (!name) { setCreatingFolder(false); return }
    await api.createFolder(name)
    setNewFolderName('')
    setCreatingFolder(false)
    await reloadFolders()
  }

  /** Same optimistic-delete-with-undo pattern as note deletion (see remove()
   * below) instead of a confirm() dialog -- lower stakes here too, since
   * the folder's notes survive (they just fall back to uncategorized). */
  function removeFolder(f: Folder) {
    setFolders((prev) => prev.filter((x) => x.id !== f.id))
    setNotes((prev) => prev.map((n) => (n.folder_id === f.id ? { ...n, folder_id: null } : n)))
    let undone = false
    const timer = setTimeout(() => {
      if (!undone) api.deleteFolder(f.id).catch(() => {})
    }, 5000)
    toastAction(`已删除文件夹「${f.name}」（笔记已移至未分类）`, '撤销', () => {
      undone = true
      clearTimeout(timer)
      reloadFolders()
      reload()
    })
  }

  async function moveNote(n: Note, folderId: string | null) {
    const updated = await api.moveNoteToFolder(n.id, folderId)
    setNotes((prev) => prev.map((x) => (x.id === n.id ? updated : x)))
    if (current?.id === n.id) setCurrent(updated)
  }

  /** Shared between the flat search-results list and the per-folder grouped
   * list -- same note-item markup either way, only what array it's mapped
   * over differs. */
  function renderNoteItem(n: Note) {
    return (
      <div
        key={n.id}
        className={'note-item ' + (current?.id === n.id ? 'active' : '')}
        onClick={() => switchTo(n)}
      >
        <div className="t">{n.title || '未命名'}</div>
        {n.content.trim() && (
          <div className="muted" style={{ fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {previewLine(n.content)}
          </div>
        )}
        {/* flex 而不是几个 float: right 堆在一起——三个控件（文件夹选择/
           置顶/删除）在 220px 宽的侧栏里跟时间戳挤一行，float 布局在文件夹
           名字长一点或者时间戳格式变化时很容易挤出这一行、换行错位，
           不好预判。timestamp 用 min-width: 0 + ellipsis 当"该缩的先缩"
           那一个（跟更早修的 .col 溢出 bug 是同一个道理），三个控件固定
           大小不被挤压。 */}
        <div className="muted" style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {n.updated_at.slice(0, 16).replace('T', ' ')}
          </span>
          {folders.length > 0 && (
            <select
              value={n.folder_id ?? ''}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => moveNote(n, e.target.value || null)}
              title="移动到文件夹"
              style={{ fontSize: 10, maxWidth: 60, padding: '0 1px', flexShrink: 0 }}
            >
              <option value="">未分类</option>
              {folders.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
          )}
          <span
            style={{ flexShrink: 0, opacity: n.pinned ? 1 : 0.35 }}
            title={n.pinned ? '取消置顶' : '置顶'}
            onClick={(e) => { e.stopPropagation(); togglePin(n) }}
          >
            📌
          </span>
          <span
            style={{ flexShrink: 0 }}
            title="删除（5 秒内可在提示里撤销）"
            onClick={(e) => { e.stopPropagation(); remove(n) }}
          >
            ✕
          </span>
        </div>
      </div>
    )
  }

  function open(n: Note) {
    setCurrent(n)
    setTitle(n.title)
    setContent(n.content)
    setSpine('')
    setBeats([])
    setRevisions([])
    setTapMeta(null)
  }

  useEffect(() => {
    reload().then((list) => {
      if (list.length) open(list[0])
    })
    reloadFolders()
    api.health().then((h) => {
      const bad: string[] = []
      if (!h.llm?.ok) bad.push('LLM 不可达 (' + h.llm?.base_url + ')')
      if (!h.asr?.ok) bad.push('语音服务不可达 (' + h.asr?.base_url + ')')
      setHealthMsg(bad.join(' · '))
    }).catch(() => setHealthMsg('后端不可达'))
  }, [reload, reloadFolders])

  useEffect(() => {
    if (!noteQuery.trim()) { setSearchResults(null); return }
    const t = setTimeout(() => {
      api.listNotes(noteQuery).then(setSearchResults).catch(() => {})
    }, 300)
    return () => clearTimeout(t)
  }, [noteQuery])

  const visibleNotes = searchResults ?? notes

  async function newNote() {
    await save()
    const n = await api.createNote('未命名', '')
    await reload()
    open(n)
  }

  async function save() {
    if (!current) return
    if (title === current.title && content === current.content) return
    const n = await api.saveNote(current.id, title, content)
    setCurrent(n)
    await reload()
  }

  // Cmd/Ctrl+S saves explicitly instead of falling through to the browser's
  // save-page dialog; Cmd/Ctrl+N starts a new note instead of opening a new
  // browser window -- power users expect both, autosave already makes S a
  // no-op when nothing's dirty so this can't double-save anything.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey)) return
      const key = e.key.toLowerCase()
      if (key === 's') { e.preventDefault(); save() }
      else if (key === 'n') { e.preventDefault(); newNote() }
      else if (key === '.') { e.preventDefault(); setFocusMode((v) => !v) }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, title, content])

  // Right-click with a live selection opens the AI selection menu instead of
  // the browser's native context menu; right-click with no selection (or
  // outside the editor) falls through to the browser default as normal.
  // The listener attaches to the CM6 view's own DOM node rather than a React
  // onContextMenu prop on MarkdownEditor -- editorViewRef is stable across
  // note switches (MarkdownEditor mounts its EditorView once, see its own
  // effect), so this only needs to (re)attach once the ref is populated,
  // which `current` transitioning from null captures.
  useEffect(() => {
    const view = editorViewRef.current
    if (!view) return
    function onContextMenu(e: MouseEvent) {
      const sel = view!.state.selection.main
      if (sel.empty) return
      e.preventDefault()
      const text = view!.state.sliceDoc(sel.from, sel.to)
      setSelectionMenu({ x: e.clientX, y: e.clientY, text })
    }
    view.dom.addEventListener('contextmenu', onContextMenu)
    return () => view.dom.removeEventListener('contextmenu', onContextMenu)
  }, [current])

  async function handleSelectionAction(action: SelectionAction) {
    if (!selectionMenu) return
    const selection = selectionMenu.text
    // Keep the menu open (showing a spinner via selectionBusy) instead of
    // closing it immediately -- otherwise a slow LLM call leaves no
    // indication anything is happening at the spot the user right-clicked.
    setSelectionBusy(true)
    try {
      if (action === 'verify') {
        const r = await api.verifySelection(content, selection)
        setVerifyFindings(r.findings)
      } else if (action === 'expand') {
        const r = await api.expandSelection(content, selection)
        if (r.revisions.length === 0) toast('模型认为不需要补充上下文。')
        setRevisions((rs) => [...rs, ...r.revisions])
      } else {
        // 'rewrite' | 'polish'
        const r = await api.rewriteSelection(content, selection, action, spine, beats)
        if (r.revisions.length === 0) toast('模型没有给出修改建议。')
        setRevisions((rs) => [...rs, ...r.revisions])
      }
    } catch (e) {
      toast(`操作失败：${e}`, 'error')
    } finally {
      setSelectionBusy(false)
      setSelectionMenu(null)
    }
  }

  /** Plain-text .md download -- markdown source is already the storage
   * format (see MarkdownEditor), so this is a straight file save, not an
   * export/conversion step. Deliberately no backend round-trip: portability
   * shouldn't depend on the server being reachable. */
  function exportMarkdown() {
    if (!current) return
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${title || '未命名'}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  async function copyMarkdown() {
    if (!current) return
    try {
      await navigator.clipboard.writeText(content)
    } catch {
      toast('复制失败，浏览器可能没给剪贴板权限', 'error')
    }
  }

  /** Leaving the current note (switching to another, creating a new one)
   * used to just call open()/createNote() directly -- if you did that within
   * the 1.5s autosave window, the debounce effect's cleanup cancelled the
   * pending save on its way out, and open() immediately overwrote
   * title/content with the new note's values. The edits were never sent to
   * the backend and never came back: silent data loss, no error, nothing to
   * undo. Every path that leaves the current note must flush first. */
  async function switchTo(n: Note, viaHarness = false) {
    if (current?.id === n.id) return
    await save()
    open(n)
    // 手动点了别的笔记 = 明确表示现在想看别的东西，无限续写继续在后台跑，
    // 但不再把编辑器拽回正在写的那篇——harness 自己触发的切换不算"手动"，
    // 不应该关掉跟随（否则每次它自己切笔记都会把 follow 关掉，只能跟一次）。
    if (!viaHarness && harness?.running) setHarness((h) => (h ? { ...h, follow: false } : h))
  }

  // 自动保存：停止输入 1.5 秒后落库
  useEffect(() => {
    if (!current) return
    if (title === current.title && content === current.content) return
    const t = setTimeout(save, 1500)
    return () => clearTimeout(t)
  }, [title, content])  // eslint-disable-line react-hooks/exhaustive-deps

  // 后台自动生成骨架：停顿 8 秒、且内容比上次生成时至少多变了 20 字才重新
  // 生成——骨架本身要求"补上显然还没写但该写的部分"（见 prompts.py），跑在
  // 后台就是一份持续预测下一步该写什么的活骨架，不用手动点。
  useEffect(() => {
    if (!current) return
    if (content.trim().length < SKELETON_MIN_CHARS) return
    if (content === lastSkeletonContent.current) return
    if (lastSkeletonContent.current
        && Math.abs(content.length - lastSkeletonContent.current.length) < SKELETON_MIN_DELTA) return
    const t = setTimeout(() => {
      if (loadingRef.current) return
      lastSkeletonContent.current = content
      runSkeleton()
    }, SKELETON_IDLE_MS)
    return () => clearTimeout(t)
    // `loading` isn't read in the body, but it's a dep on purpose: if the
    // timer fires while something else is running, it backs off and does
    // nothing -- without `loading` here, nothing would ever re-run this
    // effect to give it another chance once that something else finishes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, current, loading])

  // 后台自动生成修订建议：门槛比骨架更保守（停顿更久），避免骨架和修订两个
  // 后台任务在同一次停顿窗口里抢着跑。
  useEffect(() => {
    if (!current) return
    if (content.trim().length < EDIT_MIN_CHARS) return
    if (content === lastEditContent.current) return
    if (lastEditContent.current
        && Math.abs(content.length - lastEditContent.current.length) < EDIT_MIN_DELTA) return
    const t = setTimeout(() => {
      if (loadingRef.current) return
      lastEditContent.current = content
      runEdit()
    }, EDIT_IDLE_MS)
    return () => clearTimeout(t)
    // same reasoning as the skeleton effect above: `loading` as a dep gives
    // this a chance to retry once whatever was blocking it (e.g. the
    // skeleton auto-run) finishes, instead of silently never firing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, current, loading])

  /** Optimistic delete with an undo window instead of a confirm() dialog --
   * deletion used to be instant and permanent past a dialog people click
   * through by habit. The note is only actually deleted from the backend
   * after `ms` unless the toast's "撤销" is clicked first. */
  function remove(n: Note) {
    const wasCurrent = current?.id === n.id
    setNotes((prev) => prev.filter((x) => x.id !== n.id))
    setSearchResults((prev) => (prev ? prev.filter((x) => x.id !== n.id) : prev))
    if (wasCurrent) {
      const remaining = notes.filter((x) => x.id !== n.id)
      if (remaining.length) open(remaining[0])
      else { setCurrent(null); setTitle(''); setContent('') }
    }
    let undone = false
    const timer = setTimeout(() => {
      if (!undone) api.deleteNote(n.id).catch(() => {})
    }, 5000)
    toastAction(`已删除「${n.title || '未命名'}」`, '撤销', () => {
      undone = true
      clearTimeout(timer)
      reload()
      if (wasCurrent) open(n)
    })
  }

  async function togglePin(n: Note) {
    const updated = await api.togglePin(n.id)
    if (current?.id === n.id) setCurrent(updated)
    await reload()
  }

  // ---------------------------------------------------------------- AI 动作

  async function runSkeleton() {
    setLoading('skeleton')
    try {
      const r = await api.genSkeleton(title, content)
      setSpine(r.spine)
      setBeats(r.beats)
    } catch (e) {
      toast('生成骨架失败：' + e, 'error')
    } finally {
      setLoading('')
    }
  }

  async function runEdit() {
    setLoading('edit')
    try {
      const r = await api.genRevisions(content, spine, beats)
      setRevisions(r.revisions)
      if (r.revisions.length === 0) toast('模型认为当前正文没有需要修订的地方。')
    } catch (e) {
      toast('生成修订失败：' + e, 'error')
    } finally {
      setLoading('')
    }
  }

  /** magic tap：流式续写，边到边写进编辑器。再点一次可中断。 */
  async function runMagicTap() {
    if (loading === 'tap') {
      abortRef.current?.abort()
      return
    }
    setLoading('tap')
    setTapMeta(null)
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      await api.magicTap(
        content,
        spine,
        beats,
        setTapMeta,
        (piece) => setContent((c) => c + piece),
        ctrl.signal,
      )
    } catch (e) {
      if ((e as Error).name !== 'AbortError') toast('续写失败：' + e, 'error')
    } finally {
      setLoading('')
      abortRef.current = null
    }
  }

  /** 智能续写：单篇笔记内的 harness——自动修订（不等人工点接受）+ 自动
   * 续写交替，直到内容相对 spine/beats 已经完整才停。修订直接用跟
   * RevisionPanel 手动接受同一套 applyRevision() 锚点语义应用到本地
   * content，续写增量直接追加，效果上编辑器里能实时看到"自己在改自己"。
   * 用 currentRef 而不是闭包里的 `current` 判断该不该应用——万一运行中
   * 途用户切到了别的笔记，不能把这篇笔记的修订/续写误应用到当前正显示
   * 的另一篇笔记上。 */
  async function runNoteHarness() {
    if (loading === 'note-harness') {
      abortRef.current?.abort()
      return
    }
    if (!current) return
    const noteId = current.id
    setLoading('note-harness')
    setNoteHarnessStatus('启动中…')
    setBeatCoverage(null)
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      await api.runNoteHarness(
        noteId, content, spine, beats,
        {
          onSkeleton: (s, b) => {
            if (currentRef.current?.id !== noteId) return
            setSpine(s); setBeats(b)
            setNoteHarnessStatus('已自动生成骨架，开始第一轮')
          },
          onRoundStart: (d) => {
            if (currentRef.current?.id !== noteId) return
            // skipped_continue：上一轮评分说重复是当前最弱的一项，这一轮
            // 后端直接跳过续写、只再跑一次聚焦修订，不会有 delta 事件
            // 跟着到达（见 TRACELOG [25]）——状态文案要如实说"在清理重复"，
            // 不能说"续写中"，不然用户会以为卡住了；也不能预留续写用的
            // 空行，因为这一轮根本不会有内容来填上这个空行。
            if (d.skipped_continue) {
              setNoteHarnessStatus(`第 ${d.round} 轮：修订 ${d.revisions_applied} 处，正在清理重复内容…`)
              return
            }
            setNoteHarnessStatus(`第 ${d.round} 轮：修订 ${d.revisions_applied} 处，续写中…`)
            // 续写的增量在这之后才开始到达——本地累积的 content 要先补一次
            // 分隔，跟后端 prompts.join_round_text() 是同一个道理
            // （TRACELOG [8]/[10]）：折叠 runHarness 那边已经修过的同一个坑，
            // 这里之前漏了，只修了文件夹 harness 那一侧。
            setContent((c) => (c ? c.replace(/\n*$/, '') + '\n\n' : c))
          },
          onRevision: (r) => {
            if (currentRef.current?.id !== noteId) return
            setContent((c) => applyRevision(c, { id: '', op: r.op as Revision['op'], anchor: r.anchor, text: r.text, reason: r.reason, sources: r.sources ?? [] }))
            const sourceNote = r.sources?.length ? `（依据：${r.sources[0].slice(0, 40)}${r.sources.length > 1 ? ' 等' : ''}）` : ''
            toast(`已自动${r.op === 'delete' ? '删除' : '修订'}一处：${r.reason.slice(0, 60)}${sourceNote}`)
          },
          onDelta: (text) => {
            if (currentRef.current?.id !== noteId) return
            setContent((c) => c + text)
          },
          onEvaluate: (d) => {
            if (currentRef.current?.id !== noteId) return
            const beatScore = d.scores['beat_coverage']
            if (beatScore) setBeatCoverage(beatScore)
            if (d.status === 'continue' && d.weakest) {
              setNoteHarnessStatus(`这一轮评分：${d.weakest} 还不够，下一轮优先改这个`)
            }
          },
          onDone: (reason, blockedReason) => {
            const label = reason === 'complete' ? '内容已完整，自动停止'
              : reason === 'blocked' ? `卡住了，需要你看一眼：${blockedReason || '原因未知'}`
              : reason === 'stalled' ? '连续几轮没有新内容，自动停止'
              : '到达轮数上限，自动停止'
            setNoteHarnessStatus(label)
            toast(`智能续写：${label}`, reason === 'blocked' ? 'error' : undefined)
          },
        },
        ctrl.signal,
      )
    } catch (e) {
      if ((e as Error).name !== 'AbortError') toast('智能续写失败：' + e, 'error')
    } finally {
      setLoading('')
      setNoteHarnessStatus('')
      abortRef.current = null
      reload()
    }
  }

  function acceptRevision(r: Revision) {
    setContent((c) => applyRevision(c, r))
    setRevisions((rs) => rs.filter((x) => x.id !== r.id))
  }

  /** Manually push the current note into the knowledge base. Not wired to
   * autosave: autosave fires every 1.5s of idle typing, so tying ingestion
   * to it would re-ingest the whole note repeatedly while the user is still
   * writing -- wasting LLM calls and producing a pile of near-duplicate
   * facts. */
  async function ingestCurrentNote() {
    if (!content.trim()) return
    setLoading('ingest')
    try {
      const r = await api.ingestText(content, title || '未命名', 'note')
      setJob(r.job_id)
    } catch (e) {
      toast('存入知识库失败：' + e, 'error')
    } finally {
      setLoading('')
    }
  }

  function insertAtCursor(text: string) {
    if (!text) return
    const view = editorViewRef.current
    if (!view) {
      setContent((c) => c + text)
      return
    }
    const { from, to } = view.state.selection.main
    // dispatch's own updateListener already calls onChange -> setContent,
    // same path a keystroke takes -- no need to also setContent here.
    view.dispatch({ changes: { from, to, insert: text }, selection: { anchor: from + text.length } })
  }

  /** Symmetric with exportMarkdown(): bring a .md file in as a real editable
   * note (not knowledge-base extraction -- that's the separate "存入知识库"
   * / 批量导入 path). Migrating content in from Obsidian/Notion exports etc.
   * shouldn't require re-typing it. */
  async function importMarkdown(files: FileList | null) {
    const file = files?.[0]
    if (!file) return
    const text = await file.text()
    await save()
    const title = file.name.replace(/\.(md|markdown|txt)$/i, '')
    const n = await api.createNote(title, text)
    await reload()
    open(n)
  }

  // ---------------------------------------------------------------- 渲染

  return (
    <div className={'app' + (focusMode ? ' focus-mode' : '')}>
      <Toaster />
      <CommandPalette onOpenNote={switchTo} onInsertFact={insertAtCursor} />
      {writingPlanFolder && (
        <WritingPlanPanel
          folder={writingPlanFolder}
          onClose={() => setWritingPlanFolder(null)}
          onNoteChanged={() => { reload(); reloadFolders() }}
          harness={harness}
          onRun={() => runHarness(writingPlanFolder)}
          onToggleFollow={() => setHarness((h) => (h ? { ...h, follow: !h.follow } : h))}
        />
      )}
      {/* 关掉面板不再停止 harness（见 HarnessState 注释）——这块是面板关着
         的时候唯一能看到"还在跑"的地方，点了直接重新打开对应文件夹的面板。 */}
      {harness?.running && !writingPlanFolder && (
        <div
          className="card"
          style={{ position: 'fixed', right: 16, bottom: 16, zIndex: 60, width: 260, cursor: 'pointer' }}
          onClick={() => setWritingPlanFolder({ id: harness.folderId, name: harness.folderName, user_id: '', created_at: '' })}
          title="点击打开写作计划面板"
        >
          <div className="row" style={{ gap: 6 }}>
            <span className="spinner" />
            <strong style={{ fontSize: 13 }}>🚀 {harness.folderName}</strong>
          </div>
          <p className="muted" style={{ fontSize: 12, margin: '4px 0 0' }}>
            {harness.currentSectionTitle ? `正在写：${harness.currentSectionTitle}` : '正在启动…'}
          </p>
        </div>
      )}
      {skillsPanelOpen && <SkillsPanel onClose={() => setSkillsPanelOpen(false)} />}
      {settingsPanelOpen && <SettingsPanel onClose={() => setSettingsPanelOpen(false)} />}
      {selectionMenu && (
        <SelectionMenu
          x={selectionMenu.x}
          y={selectionMenu.y}
          busy={selectionBusy}
          onAction={handleSelectionAction}
          onClose={() => { if (!selectionBusy) setSelectionMenu(null) }}
        />
      )}
      {!focusMode && (
      <div className="col sidebar">
        <h1>
          memoket-NOTE{' '}
          <span
            className="muted"
            style={{ fontSize: 12, cursor: 'help' }}
            title={'⌘K 全局搜索（笔记+知识库）\n⌘N 新建笔记\n⌘S 保存\n⌘. 专注模式\nEsc 关闭弹层'}
          >
            ⌘?
          </span>
        </h1>
        <UserSwitcher />
        {/* 最高频操作放最前面、最显眼——"写作 Skill"/"无限续写"这两个工具类
           入口挪到侧栏底部的 sidebar-footer 里了（见下面），不再跟这两个
           抢第一屏。 */}
        <div className="row" style={{ marginBottom: 8 }}>
          <button className="primary" style={{ flex: 1 }} onClick={newNote}>
            + 新建笔记
          </button>
          <label className="muted" style={{ fontSize: 18, cursor: 'pointer', padding: '0 4px' }} title="导入 .md 文件为笔记">
            ⬆
            <input
              type="file"
              accept=".md,.markdown,.txt"
              style={{ display: 'none' }}
              onChange={(e) => importMarkdown(e.target.files)}
            />
          </label>
        </div>

        <h2>笔记</h2>
        <input
          placeholder="搜索笔记标题或正文…（⌘K 全局搜索）"
          value={noteQuery}
          onChange={(e) => setNoteQuery(e.target.value)}
          style={{ marginBottom: 8 }}
        />
        {visibleNotes.length === 0 && (
          <p className="muted">{noteQuery ? '没有匹配的笔记。' : '还没有笔记。'}</p>
        )}
        {searchResults !== null ? (
          // 搜索结果不按文件夹分组——命中就该直接看到，不用先猜它在哪个文件夹里
          visibleNotes.map(renderNoteItem)
        ) : (
          <>
            {folders.map((f) => {
              const inFolder = notes.filter((n) => n.folder_id === f.id)
              const collapsed = collapsedFolders.has(f.id)
              return (
                <div key={f.id} style={{ marginBottom: 4 }}>
                  <div
                    className="muted"
                    style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                            fontSize: 12, padding: '4px 2px', cursor: 'pointer' }}
                    onClick={() => toggleFolderExpanded(f.id)}
                  >
                    <span>{collapsed ? '▸' : '▾'} 📁 {f.name} <span style={{ opacity: 0.6 }}>({inFolder.length})</span></span>
                    <span>
                      <span
                        title="无限续写：给个目标，自动拆分段一段接一段写"
                        onClick={(e) => { e.stopPropagation(); setWritingPlanFolder(f) }}
                        style={{ marginRight: 8 }}
                      >
                        🚀
                      </span>
                      <span
                        title="删除文件夹（笔记会变为未分类，不会被删除）"
                        onClick={(e) => { e.stopPropagation(); removeFolder(f) }}
                      >
                        ✕
                      </span>
                    </span>
                  </div>
                  {!collapsed && inFolder.map(renderNoteItem)}
                </div>
              )
            })}

            {creatingFolder ? (
              <div className="row" style={{ marginBottom: 8 }}>
                <input
                  autoFocus
                  value={newFolderName}
                  onChange={(e) => setNewFolderName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') confirmCreateFolder()
                    if (e.key === 'Escape') { setCreatingFolder(false); setNewFolderName('') }
                  }}
                  placeholder="文件夹名称"
                  style={{ flex: 1 }}
                />
                <button onClick={confirmCreateFolder}>确定</button>
              </div>
            ) : (
              <button style={{ width: '100%', marginBottom: 8 }} onClick={() => setCreatingFolder(true)}>
                + 新建文件夹
              </button>
            )}

            {notes.filter((n) => !n.folder_id).map(renderNoteItem)}
          </>
        )}

        <div className="sidebar-footer">
          <button onClick={() => setSkillsPanelOpen(true)}>🧩 Skill</button>
          <button onClick={openWritingPlan} title="按文件夹自动一段接一段续写">🚀 无限续写</button>
          <button onClick={() => setSettingsPanelOpen(true)} title="LLM 供应商：本地模型 / GPT">⚙️ 设置</button>
        </div>
      </div>
      )}

      <div className="col">
        {healthMsg && <p className="card" style={{ color: 'var(--del)' }}>{healthMsg}</p>}

        {!current ? (
          <p className="muted">
            左侧新建一篇笔记开始。<br />
            找导入过的知识库内容？那是分开存的，看右侧「知识库」面板，不在笔记列表里。
          </p>
        ) : (
          <>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="标题"
              style={{ fontSize: 20, fontWeight: 600, border: 'none', padding: '4px 0' }}
            />

            {/* Two tiers, not one flat row of 7 -- content-generation actions
               (what you came here to do) stay big and prominent; file/view
               utilities are real but secondary, so they're visually quieter
               and grouped separately instead of competing for the same
               attention as "continue writing". */}
            <div className="row" style={{ margin: '10px 0 6px' }}>
              <button className="primary" onClick={runMagicTap} disabled={loading === 'note-harness'}>
                {loading === 'tap' ? '■ 停止' : '✨ magic tap 续写'}
              </button>
              <button
                className="primary"
                onClick={runNoteHarness}
                disabled={loading === 'tap'}
                title="自动修订（不用手动接受）+ 自动续写交替进行，直到内容相对结构节拍已经完整才停"
              >
                {loading === 'note-harness' ? '■ 停止' : '🤖 智能续写'}
              </button>
              <AudioRecorder onTranscript={insertAtCursor} onIngested={setJob} />
              <button onClick={ingestCurrentNote} disabled={!content.trim() || loading === 'ingest'}>
                {loading === 'ingest' ? <span className="spinner" /> : '📥 存入知识库'}
              </button>
            </div>
            {loading === 'note-harness' && noteHarnessStatus && (
              <p className="muted" style={{ fontSize: 12, margin: '0 0 8px' }}>🤖 {noteHarnessStatus}</p>
            )}
            <div className="row toolbar-secondary" style={{ marginBottom: 10 }}>
              <button onClick={save}>保存</button>
              <button onClick={exportMarkdown} title="导出为 .md 文件">⬇ 导出</button>
              <button onClick={copyMarkdown} title="复制正文到剪贴板">⧉ 复制</button>
              <button onClick={() => setFocusMode((v) => !v)} title="专注模式（⌘.）">
                {focusMode ? '⤢ 退出专注' : '⛶ 专注模式'}
              </button>
            </div>

            {tapMeta && <TapProvenance meta={tapMeta} />}

            <MarkdownToolbar viewRef={editorViewRef} />
            <MarkdownEditor
              content={content}
              onChange={setContent}
              revisions={revisions}
              onAcceptInline={acceptRevision}
              placeholder="开始写…  支持 Markdown 和 ```mermaid 图表。写到一半点 magic tap，会先查你的知识库再续写。"
              viewRef={editorViewRef}
            />
            <p className="muted" style={{ fontSize: 11, margin: '4px 2px' }}>
              {content.length} 字 · 约 {Math.max(1, Math.round(content.length / 400))} 分钟阅读
            </p>
          </>
        )}
      </div>

      {!focusMode && (
      <div className="col">
        {verifyFindings && (
          <VerifyPanel findings={verifyFindings} onClose={() => setVerifyFindings(null)} />
        )}
        {/* Tabbed instead of five-plus panels stacked in one endless scroll --
           "写作"/"记忆"/"知识库" are three different modes of attention
           (structuring THIS note / ambient recall while writing / browsing
           the whole knowledge base), not things you look at simultaneously. */}
        <div className="row" style={{ marginBottom: 10 }}>
          {([
            ['write', '写作' + (revisions.length > 0 ? ` (${revisions.length})` : '')],
            ['memory', '相关记忆'],
            ['kb', '知识库'],
          ] as const).map(([key, label]) => (
            <button
              key={key}
              className={rightTab === key ? 'primary' : ''}
              onClick={() => setRightTab(key)}
            >
              {label}
            </button>
          ))}
        </div>

        {rightTab === 'write' && (
          <>
            <DocumentOutline content={content} viewRef={editorViewRef} />
            <SkeletonPanel
              spine={spine}
              beats={beats}
              beatCoverage={beatCoverage}
              loading={loading === 'skeleton'}
              onRun={runSkeleton}
            />
            <RevisionPanel
              revisions={revisions}
              content={content}
              loading={loading === 'edit'}
              onAccept={acceptRevision}
              onReject={(r) => setRevisions((rs) => rs.filter((x) => x.id !== r.id))}
              onRun={runEdit}
            />
          </>
        )}
        {rightTab === 'memory' && <RelatedMemory content={content} onInsert={insertAtCursor} />}
        {rightTab === 'kb' && <MemoryPanel pendingJob={job} />}
      </div>
      )}
    </div>
  )
}
