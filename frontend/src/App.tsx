import { useCallback, useEffect, useMemo, useRef, useState, lazy, Suspense } from 'react'
import { clickable } from './util/clickable'
import { DESTINATIONS } from './util/destinations'
import { journalDateOf } from './util/journalDate'
import JourneyRibbonPanel from './components/JourneyRibbonPanel'
import { openSearchPanel } from '@codemirror/search'
import { micError } from './util/micError'
import ChangeLayersPanel from './components/ChangeLayersPanel'
import TrashPanel from './components/TrashPanel'
import { chunked, dotWorthy, MARGIN_BATCH, MARGIN_CACHE_MAX, marginParagraphs, markKey, splitCached, type MarginMark, type MarginVerdict } from './editor/marginMemory'
import { ignoredSet } from './util/relationActions'
import { matchSnippet } from './util/snippet'
import { readingMinutes, stripForRecall, wordCount, citationRanges, noteLinkRanges, citedFactIds, linkedNoteIds } from './util/wordCount'
import { isSpeakerTag } from './util/kbNoise'
import { friendlyError, isBackendDown, isLlmUnreachable } from './util/friendlyError'
import { NOT_CONFIGURED, healthMessage, llmGateMessage, notePrecondition } from './editor/preconditions'
import { EditorView } from '@codemirror/view'
import * as api from './api'
import type { Note, Revision, TapMeta, TreeRow, VerifyResult, WritingPlan, WritingSection } from './api'
import AudioRecorder from './components/AudioRecorder'
import CommandPalette from './components/CommandPalette'
import DocumentOutline from './components/DocumentOutline'
import MarkdownEditor from './components/MarkdownEditor'
import SplitEditor from './components/SplitEditor'
import { insertStreamed, tidyBlankLines, applyScrub, prepareInsert } from './editor/streamJoin'
// 一轮里可以先后命中好几条判据，攒起来别互相盖掉（批 24 / 计划 12.1）
import { withCheckHit } from './editor/agentRound'
import { isStaleShrink, type Served } from './editor/saveGuard'
import IconPicker from './components/IconPicker'
import SlashPrompt from './components/SlashPrompt'
import { formatMarkdown, fixBoldPunct, stripCommonIndent } from './editor/format'
import { blockPrecondition, SLASH_ITEMS, type SlashItem } from './editor/slashMenu'
import { blockShapeProblem, splitBadRevisions, badRevisionNote, unparsedEditNote } from './editor/blockShape'
import type { NoteLinkMenuDetail } from './editor/noteLink'
import { landNotesInTray, noteExcerpt, requestTrayAdd, trayPrecondition } from './util/tray'
import { diffBaseForBlock, textToLand } from './editor/blockLanding'
import { trayByDefault } from './util/trayDefaults'
import {
  appendPreview, endRun, logRun, patchRun, runsField, startRun,
} from './editor/runningBlocks'
import type { StateEffect } from '@codemirror/state'
import MarkdownToolbar from './components/MarkdownToolbar'
import WritingPlanPanel from './components/WritingPlanPanel'
import MemoryPanel from './components/MemoryPanel'
import RelatedMemory from './components/RelatedMemory'
import TrayPanel from './components/TrayPanel'
import RevisionPanel, { applyRevision } from './components/RevisionPanel'
import SelectionMenu from './components/SelectionMenu'
import type { SelectionAction } from './components/SelectionMenu'
import AgentActivity, { type AgentRound } from './components/AgentActivity'
import { acceptAllHunks, diffParts, dropHunk, layersOf, pendingHunks, restoreLayers as restoreLayersEffect, roundDiffField, settledOf, type DiffPush }
  from './editor/roundDiff'
import ContextMenu, { type MenuAt, type MenuItem } from './components/ContextMenu'
import Gutter from './components/Gutter'
import Logo from './components/Logo'
import PreferencesPanel from './components/PreferencesPanel'
// 知识库那一整套页面（含 d3 的图）按需加载：只写笔记的人不该为它多下 300KB（第 519 轮）
const KbNoteView = lazy(() => import('./components/KbNoteView'))
const SlidesPanel = lazy(() => import('./components/SlidesPanel'))
const JourneyPage = lazy(() => import('./components/JourneyPage'))
import { displayTitle, isPlaceholderTitle } from './util/displayTitle'
import ExportNotePanel from './components/ExportNotePanel'
import { setPendingKbQuery } from './util/pendingKbQuery'
import { VIRTUAL_LABELS, isKnownVirtual, factsLabel, previewLine } from './util/virtual'
import { buildCrumbs } from './util/crumbs'
import { layoutPanes, makeRoomForRight } from './util/layoutPanes'
import { readDraft, writeDraft, clearDraft, resolveDraft } from './util/draft'
import { loadSpots, putSpot, saveSpots } from './util/spots'
import { sectionEnd } from './util/sectionEnd'
import { minimalChange } from './editor/minimalChange'
import { undoRound } from './editor/undoRound'
import { groupRuns, type RunRound } from './util/runRounds'
import { changesTabHasContent, reopenedLayersNotice, restoreLayers, sameLayers, serializeLayers, type SavedLayer } from './util/changeLayers'
import { PLAN_EMPTY_HINT, planTabContent } from './util/planTab'
// 轮次卡按 note id 存（P95 A）：为什么不是一条「换篇就清」的 effect，见那份文件的抬头
import { roundsFor, writeRoundsIn, type RoundsByNote } from './util/roundsByNote'
import { guardBlocks } from './util/harnessGuard'
import { mergeRestored, restoredRounds } from './util/roundsRestore'
import { checkLabel, stuckTail } from './editor/dimLabel'   // 收工那句话里的判据名要中文（P13 实拍「done_criteria」原样蹦出来）+ 后面那半句下一步（P40 · B #2）
import { dimLabel } from './editor/dimLabel'
import { runProbe } from './probes'
import { setIngestActive } from './util/ingestActive'
import { ConfirmDialog, NotePicker, TextPrompt, type ConfirmRequest, type PickerRequest, type PromptRequest } from './components/Dialogs'
import { NoteInfoPanel, NotePathsPanel } from './components/NoteInfoPanels'
import NoteLinksPanel from './components/NoteLinksPanel'
import RevisionHistoryPanel from './components/RevisionHistoryPanel'
import QuickView from './components/QuickView'
import WelcomePane from './components/WelcomePane'
import ShortcutsPanel from './components/ShortcutsPanel'
import type { DropWhere } from './components/NoteTree'
import NoteKbPanel from './components/NoteKbPanel'
import NoteTree from './components/NoteTree'
import TabBar, { type Tab } from './components/TabBar'
import Ribbon, { type RibbonTab } from './components/Ribbon'
import RightPane, { type PaneTab } from './components/RightPane'
import SkeletonPanel from './components/SkeletonPanel'
import DocIntentRow from './components/DocIntentRow'
import PlanChecks from './components/PlanChecks'
import { checkDone, doneSummary } from './util/doneChecks'
import MarginCard from './components/MarginCard'
import TraceCard, { type TraceCardState } from './components/TraceCard'
import { intentText, resolveIntent, type DocIntent } from './util/docIntent'
import SettingsPanel, { AboutLine } from './components/SettingsPanel'
import SkillsPanel from './components/SkillsPanel'
import TapProvenance from './components/TapProvenance'
import Toaster from './components/Toaster'
import UserSwitcher from './components/UserSwitcher'
import VerifyPanel, { passageLine, verifyScopeLine } from './components/VerifyPanel'
import { toast, toastAction } from './toast'
import { dupSuffixes } from './util/dupTitles'
import { traceRecallHint } from './util/recallContext'
import { mermaidSvg } from './editor/mermaid'
import { parseMini } from './util/miniMarkdown'
import { slidesToHtml } from './util/slideHtml'
import { isSlides, slidePages } from './util/slidePages'
import { fmtDate, whenLabel } from './util/time'
import { notifyIfHidden } from './util/notify'
import { fmtShortcut } from './util/keys'
import Icon from './components/Icon'

// 后台自动生成的节流参数。骨架/编辑都是真实 LLM 调用（本地模型上约 8-15s），
// 不能跟着每次按键触发——用"停止输入 N 秒 + 内容变化够多"两条门槛，既保证
// 不是纯手动，又不会打字过程中疯狂重复调用模型。
const SKELETON_IDLE_MS = 8000
const SKELETON_MIN_CHARS = 30
const SKELETON_MIN_DELTA = 20

/** 改动层落库的防抖（P39）。**故意比正文自动保存的 1500ms 晚一点**：
 *  存进层里的 `content_tag` 说的是「这几处的坐标是对着哪份正文算的」，
 *  晚一步写，那份正文刚好已经落库，下次打开走的就是「按坐标精确放回」那条路，
 *  不必靠文字重新定位。 */
const CHANGE_LAYER_SAVE_MS = 1600

/** 意图行预填的防抖（P46 #5）：**名字停下来多久才重推一次预填**。
 *
 *  **不是为 CPU**——P43 量过一次 0.03–0.10ms，占一帧的 0.6%。是为**帧数**：
 *  真机上一个字一个字敲 32 个字（160ms 一个），「目标」那一格变了 **19 次**，
 *  中间十几帧是半句话（「周报 9-20：这周把众**：这段时间做了什么…**」）。
 *  标签页跟着变没关系——那是标题；这三格是**用户能改的输入框**，
 *  一个输入框在你打字时自己一格一格换内容，读起来就是坏了。
 *
 *  为什么是 500：一个字的间隔 ~160ms，500ms 落在「真的停下来想了一下」那一侧，
 *  句读之间的停顿（~300ms）还够不着它。实测 19 次 → 1 次。 */
const INTENT_PREFILL_IDLE_MS = 500


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

/** 不在树上、又没人传标题时标签页显示什么——之前 app:skills 直接把 id 当标题（实拍）。 */


/** 菜单里的标签名：硬截 + 省略号（不用 clipTitle——那个按句读截，「产品计划会：APP/硬件…」会只剩前半） */
const ellipsize = (t: string, max: number) => (t.length > max ? t.slice(0, max - 1) + '…' : t)

/** 跑得久的动作在 composer 里显示什么。
 *  **只列真的会让用户等的**：续写和智能续写自己会把主钮变成「停止」，
 *  不需要再来一行字；剩下这几个点完之后界面是静的，才需要一句话交代
 *  （第 733 轮：「做成幻灯片」实测 20 秒，之前一点动静都没有）。 */
const BUSY_LABEL: Record<string, string> = {
  ingest: '存进知识库…',
  slides: '做幻灯片…',
  restructure: '智能排版…',
  skeleton: '生成骨架…',
  // P16 分层历史：「回到这轮之前」/「只撤这一轮」在取那两版快照、改正文
  rounds: '按那一轮的快照改正文…',
}

export default function App() {
  const [notes, setNotes] = useState<Note[]>([])
  // 整棵树一次拿全（见 api.getTree 的注释：按层拿会让展开变成一次网络往返）。
  const [tree, setTree] = useState<TreeRow[]>([])
  // 知识库那棵**虚拟**子树（docs/kb-fusion-design.md §3.2）。分类层一次取全，
  // 事实按需展开；展开状态不在服务端（虚拟节点没有 branch），存本机。
  const [kbRows, setKbRows] = useState<TreeRow[]>([])
  // 中栏正在看的虚拟节点（一条事实 / 一个分类）。跟 current 互斥：有 current
  // 就是在写笔记，有 virtualId 就是在看知识库。
  const [virtualId, setVirtualId] = useState<string | null>(null)
  // 应用内对话框（替掉 window.prompt——Electron 里那是系统级模态，主题管不到）
  const [picker, setPicker] = useState<PickerRequest | null>(null)
  /** 「导回这一篇」的弹层。整库导在导入页，这里只是换个范围——**共用同一个组件**，
   *  不另写一个导出界面（否则又是「同一个动作两个门、各自会漂」）。 */
  const [exportOne, setExportOne] = useState<Note | null>(null)
  /** 侧栏怎么排：`tree` 是用户自己摆的层级，`recent` 是按最近改动平铺。
   *
   * 树只有一种排法（手动顺序 `position`），于是笔记这边**没有「最近」这个概念**
   * ——知识库有「最近摄入」、日记按日期，唯独笔记没有（docs/sidebar-ia-plan.md §3）。
   * 「我昨天写的那篇在哪」在三百篇的库里没法回答。
   * 切到这个模式时时间才显示，因为那是这个模式的重点；树模式下不显示。 */
  const [recentMode, setRecentMode] = useState(() => {
    try { return localStorage.getItem('memoket-note-list-mode:' + api.getUser()) === 'recent' } catch { return false }
  })
  useEffect(() => {
    try { localStorage.setItem('memoket-note-list-mode:' + api.getUser(), recentMode ? 'recent' : 'tree') } catch { /* 存不上就下次回树，不致命 */ }
  }, [recentMode])
  const [prompt, setPrompt] = useState<PromptRequest | null>(null)
  const [confirmReq, setConfirmReq] = useState<ConfirmRequest | null>(null)
  const [iconPicker, setIconPicker] = useState(false)
  const iconBtnRef = useRef<HTMLButtonElement>(null)   // 选择器关掉后焦点回到这个钮（键盘用户不至于掉到 body 上）
  const [locateTick, setLocateTick] = useState(0)
  const [paneFocus, setPaneFocus] = useState<{ id: string; n: number } | undefined>(undefined)
  /** 做幻灯片时的「第几页」。只有它需要比 BUSY_LABEL 更细的进度。 */
  const [slidePhase, setSlidePhase] = useState('')
  const slidesText = useRef('')
  const [fbMenu, setFbMenu] = useState<{ kind: 'harness' | 'more'; at: MenuAt } | null>(null)
  // 树菜单「导入到这里…」用的隐藏文件框；记住要挂到哪个节点下面
  const importInput = useRef<HTMLInputElement>(null)
  const importUnder = useRef<string>(api.ROOT_ID)
  const harnessProbeDone = useRef(false)
  // 这次会话新建、还一个字没写的笔记。离开它时悄悄删掉：每按一次 ＋ 树上就多一个
  // 「未命名」（实拍：截图用户树上堆了九个），Trilium 的做法也是新笔记不写就不留。
  const freshEmpty = useRef(new Set<string>())
  async function dropIfStillEmpty(n: Note | null) {
    if (!n || !freshEmpty.current.has(n.id)) return
    // 写了标题 / 正文、或者挑过图标（挑图标也是「我要这篇」的表态），就不是没动过的空笔记
    if (title.trim() || content.trim() || n.icon) { freshEmpty.current.delete(n.id); return }
    freshEmpty.current.delete(n.id)
    try {
      await api.deleteNote(n.id)
      setTabs((prev) => prev.filter((t) => t.noteId !== n.id))
      void Promise.all([reload(), reloadTree()])
    } catch { /* 删不掉就留着，不值得报错 */ }
  }
  // 分屏：中栏右侧再开一栏看另一篇（Trilium 的 SplitNoteContainer）。
  // 第二栏可编辑（SplitEditor 自己持正文 + 自动保存，第 309 轮起），但 harness / 续写 /
  // 提案层那些只长在主编辑器上；主栏正开着的那篇在分屏里只读。
  const splitFlush = useRef<(() => Promise<void>) | null>(null)
  const [split, setSplit] = useState<{ id: string; w: number } | null>(() => {
    try {
      // 探针截图要的是干净的初始布局，不把上次的分屏带进来
      if (new URLSearchParams(location.search).get('probe')) return null
      const raw = localStorage.getItem('memoket-note-split:' + api.getUser())
      return raw ? (JSON.parse(raw) as { id: string; w: number }) : null
    } catch { return null }
  })
  useEffect(() => {
    try {
      if (split) localStorage.setItem('memoket-note-split:' + api.getUser(), JSON.stringify(split))
      else localStorage.removeItem('memoket-note-split:' + api.getUser())
    } catch { /* 无所谓 */ }
  }, [split])
  const openInSplit = (id: string) => setSplit((s) => ({ id, w: s?.w ?? 420 }))
  const [tabMenu, setTabMenu] = useState<{ tab: Tab; at: MenuAt } | null>(null)
  const [tabListAt, setTabListAt] = useState<MenuAt | null>(null)
  const tabsRef = useRef<Tab[]>([])
  const closeTabRef = useRef<(id: string) => void>(() => {})
  const tabActionRef = useRef<(action: string) => void>(() => {})
  const [quick, setQuick] = useState<Note | null>(null)
  // 保存状态角标（Trilium 的 save-status-badge）：存了就说一声、5s 淡出；
  // 出错变红不淡出。自动保存的产品里留一个「保存」按钮反而暗示「不点就没存」。
  const [saveStatus, setSaveStatus] = useState<{ at: number; error?: string } | null>(null)
  // 关掉的标签留一个栈，⌘⇧T 找回来（reopenLastTab）。关错标签不该无法挽回。
  // 连原来的位置一起记：找回来要放回原位（Chrome 的 ⌘⇧T 就是这样），不是追加到最右边——
  // 关错中间一个再找回，标签顺序就乱了。
  const closedTabs = useRef<{ tab: Tab; at: number }[]>([])
  // 前进/后退：跳去看一篇旧笔记后要能一键回来（判据 2 的痛点 12）。
  // 记的是 note id / 虚拟节点 id；navigating 为真时 open 不再入栈。
  const hist = useRef<{ list: string[]; idx: number; navigating: boolean }>({ list: [], idx: -1, navigating: false })
  const [histState, setHistState] = useState({ back: false, fwd: false })
  const [treeMenu, setTreeMenu] = useState<{ row: TreeRow; at: MenuAt } | null>(null)
  /** 打开着的标签。**存在 localStorage 里，按用户分**——关掉应用再打开时
   *  桌面还在，这是桌面应用的基本预期；不存的话每次启动都要重新找回那几篇
   *  正在写的东西，而「找回来」正是判据 2 要省下的注意力。 */
  const [tabs, setTabs] = useState<Tab[]>(() => {
    try {
      const raw = localStorage.getItem('memoket-note-tabs:' + api.getUser())
      return raw ? (JSON.parse(raw) as Tab[]) : []
    } catch { return [] }
  })
  const [activeTabId, setActiveTabId] = useState<string | null>(null)
  // 展开状态不在这儿了——它跟着 branch 存在服务端（见 toggleTreeNode）。
  const [noteQuery, setNoteQuery] = useState('')
  // null = not searching (show `notes` unfiltered); kept separate from
  // `notes`/`reload()` so typing a search term can never accidentally
  // trigger the mount effect's "open the first result" behavior.
  const [searchResults, setSearchResults] = useState<Note[] | null>(null)
  const [current, setCurrent] = useState<Note | null>(null)
  // 导入 / 录音默认进哪篇的托盘（P15 #3）：最近开着的那篇真笔记——导入页开着时 `current` 是空的，托盘却是按篇的
  const [trayTarget, setTrayTarget] = useState('')
  const trayTargetRef = useRef('')                       // 给闭包里读（探针拿的 ctx 是开跑那一刻的快照）
  useEffect(() => { if (current?.id) { setTrayTarget(current.id); trayTargetRef.current = current.id } }, [current?.id])
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')

  const [spine, setSpine] = useState('')
  const [beats, setBeats] = useState<string[]>([])
  /** 骨架的确定性体检结果（后端 `harness/checks/skeleton.py`，计划 4.3）。
   * 换一篇笔记就清空——它是「这一次生成」的结论，不是笔记的属性，没跟着
   * spine/beats 一起落库。 */
  const [skeletonNotes, setSkeletonNotes] = useState<string[]>([])
  // 智能续写每轮独立核对一次哪些结构节拍还没被正文实质覆盖（TRACELOG
  // [10]）——null 表示"还没跑过/不知道"，这时骨架面板只展示节拍是什么；
  // 有值之后骨架面板据此把已覆盖的节拍标出来，而不是一份看不出进度的
  // 静态清单。
  const [beatCoverage, setBeatCoverage] = useState<{ level: number; note: string } | null>(null)
  const [revisions, setRevisions] = useState<Revision[]>([])
  const [loading, setLoading] = useState<'' | 'skeleton' | 'restructure' | 'edit' | 'tap' | 'ingest' | 'note-harness' | 'slides' | 'rounds'>('')
  // 单篇 harness 正在写哪篇：标签行给那个标签顶上一道 3px 色条（Trilium 工作区色条的位置，第 511 轮）
  const [noteHarnessNoteId, setNoteHarnessNoteId] = useState<string | null>(null)
  // 每篇看到哪儿了：切走时记下光标和滚动位置，切回来放回去（痛点 12：查完一篇旧笔记回来，
  // 想不起来自己刚才在写哪一段）。跨重启保留，见 util/spots。
  const spots = useRef(loadSpots(api.getUser()))
  /** agent 每一轮干了什么，喂给 AgentActivity 可视化。按轮聚合：用户关心的是
   * "这一轮查了什么 → 改了什么 → 打了几分 → 于是下一轮怎么调"这条因果链，
   * 事件流水账看不出所以然。
   *
   * **按 note id 存**（P95 A，收 P93 问题 #1）：原来是一整个 App 一份，
   * 只在 harness 开跑那一刻清一次，于是「A 篇跑完 2 轮 → ⌘K 新建一篇空笔记」
   * 那一屏上，右栏「计划」写着 `计划 2`、底下摆着 A 篇那两轮的执行记录（P93 实拍）。
   * 为什么不照抄 P17 给 `verifyResult` / `roundDiff` 立的那条「换篇就清」——
   * 理由逐条写在 `util/roundsByNote.ts` 的抬头里（一句话：那两个是**消息**，
   * 这个是**这一篇的一段历史**，清掉就再也回不来）。 */
  const [roundsByNote, setRoundsByNote] = useState<RoundsByNote>({})
  /** 收工那句话要数的是**跑的那篇**有几轮，不是**现在显示的那篇**——
   *  用户切走了的话后者是空的。写 ref 是幂等的（跟 `liveContentRef` 同一条理由）。 */
  const roundsByNoteRef = useRef<RoundsByNote>({})
  /** 现在显示的这一篇的轮次卡。虚拟页 / 没开笔记 ⇒ 空。 */
  const agentRounds = roundsFor(roundsByNote, current?.id)
  /** 往**某一篇**的轮次卡上写。**note id 是必给的**——「往当前这篇写」正是那个洞。 */
  const writeRounds = useCallback((noteId: string, fn: (rs: AgentRound[]) => AgentRound[]) => {
    setRoundsByNote((m) => {
      const next = writeRoundsIn(m, noteId, fn)
      roundsByNoteRef.current = next
      return next
    })
  }, [])
  /** 这一轮 harness 改了什么（新增/删除），传给编辑器做只读高亮。
   * 自动应用的改动用户否则完全看不见被动了哪里。 */
  const [roundDiff, setRoundDiff] = useState<DiffPush | null>(null)
  const diffSeq = useRef(0)
  /** 把一次 AI 动作的改动作为一层提案标出来（agent-native-editor §3.2：按层接受 / 撤回）。 */
  function pushDiff(label: string, before: string, after: string, replace = false) {
    if (before === after) return
    setRoundDiff({ label, parts: diffParts(before, after), seq: ++diffSeq.current, replace })
  }
  // 还剩几处 harness 改动没被处置。由编辑器上报——逐处接受/撤回、用户自己
  // 编辑、下一轮写入都会让它变，React 这边只是拿来决定要不要显示那条工具栏。
  const [pendingDiff, setPendingDiff] = useState(0)
  /** 待处置的改动层落库（P39，痛点 8 的最后一块）。
   *
   * **落库时机为什么是这三下**（P37 #5 提醒过：`auto` 快照那一档的 600 秒间隔正是
   * 为了别一敲字就写）：
   *   ① **层一产生就写一次**——跑完一轮智能续写立刻断电，那一层也还在；
   *   ② **处置状态一动就防抖写**（`CHANGE_LAYER_SAVE_MS`，比正文自动保存的 1500ms 稍晚一点，
   *      于是存进去的 `content_tag` 说的正是刚落库的那份正文，重开时能走「按坐标精确放回」那条路）；
   *   ③ **关窗口 / 换篇之前冲一次**（`keepalive`，不然页面一卸载请求就被掐）。
   * 一敲一个字就写是**明确不做**的：位置漂了由 ② 那一下带走，而 `sameLayers` 会把
   * 「其实什么都没变」的那些写请求全挡掉。 */
  const layersSaved = useRef<{ noteId: string; payload: SavedLayer[] }>({ noteId: '', payload: [] })
  const layersTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  /** 层已经放回编辑器的是哪一篇。**换篇到放回来之间这一格是空的**——
   *  这中间的任何一次防抖落库都会把上一篇的层写到新这篇名下。 */
  const layersReady = useRef('')
  const lastSettled = useRef<unknown>(undefined)
  /** 处置过的那本账变了要重渲染面板（「已处置 2 接受 · 1 撤回」那一行） */
  const [layersTick, setLayersTick] = useState(0)
  /** **放不回来的那几层**（P41 #5 ② / P39「留给下一批」②）。原来只弹一句 toast：
   *  用户读完那句话没有任何可按的东西，而那一层的数据其实还在手上。
   *  留在这里，面板给两个出路：「按现在的正文重新算」/「丢掉这一层」。
   *  **落库也带着它**（`flushChangeLayers`）——不带的话下一次冲库就把它悄悄抹了，
   *  那又是一次「静默按接受」。 */
  const [layerStuck, setLayerStuck] = useState<{ id: string; label: string; why: string[]; saved: SavedLayer }[]>([])
  const layerStuckRef = useRef<typeof layerStuck>([])
  useEffect(() => { layerStuckRef.current = layerStuck }, [layerStuck])
  /** 续写写完之后把那一段封成一个撤销单位（P10 C3-2，`editor/undoUnit`）；seq 变了编辑器才动手。 */
  // 撤销分组（P11 #2）：智能续写每一轮开跑加一，编辑器把这一轮落地的所有片段（修订 + 续写）并成一条撤销事件，
  // ⌘Z 一次撤一轮（机制在 `editor/undoUnit.aiSyncSpec` / `MarkdownEditor` 的 content 同步）
  const [undoGroup, setUndoGroup] = useState(0)
  // `/` 菜单选中的那一项。needsPrompt 的会先弹输入框，其余的直接执行。
  // 运行状态**不在这里**：跑起来之后状态在光标处的占位块里
  // （editor/runningBlocks.ts）——离产出最近，而且支持同时跑好几个。
  // 这里只留「选中了哪一项、要不要弹提示词输入框」。
  const [slash, setSlash] = useState<
    { item: SlashItem; from: number; to: number; x: number; y: number } | null>(null)
  // 正文里 `[[` 链接标记右键（P14 §3.4）：「摊到这篇桌上」/ 打开。事件由 editor/noteLink 发，菜单在这里画
  const [noteLinkMenu, setNoteLinkMenu] = useState<NoteLinkMenuDetail | null>(null)
  useEffect(() => {
    const on = (e: Event) => setNoteLinkMenu((e as CustomEvent<NoteLinkMenuDetail>).detail)
    window.addEventListener('note-link-menu', on)
    return () => window.removeEventListener('note-link-menu', on)
  }, [])
  // **一次运行一个 AbortController**，用 id 索引。原来是单个 ref，
  // 所以同时只能跑一个 `/`——第二个一开始就把第一个的 controller 顶掉了。
  const runAborts = useRef(new Map<string, AbortController>())
  // 形状不对被拦下的那次要能原样再跑一遍：记住这一次是哪一项、什么指令（P31 #7）
  const retryArgs = useRef(new Map<string, { item: SlashItem; prompt: string }>())
  const filePick = useRef<HTMLInputElement>(null)
  const pickKind = useRef<'image' | 'audio'>('image')
  // 录音的停止函数按 id 存：停止走 MediaRecorder.stop()（停下来才有音频
  // 可转写），跟网络请求的 abort 不是一回事。
  const voiceStopById = useRef(new Map<string, () => void>())
  // **整次 run 开始时**的正文快照。刻意不按轮记：按轮标的话，第 N 轮的
  // 高亮会被第 N+1 轮的第一条修订清掉（roundDiffField 一见 docChanged 就丢
  // 旧装饰），最后一轮的又会被收尾的 reload() 清掉，用户只来得及看见第一次。
  // 而且你想看的本来就是"这次跑下来它改了什么"，不是"第 3 轮那 20 秒改了什么"。
  const runBaseRef = useRef<string>('')
  // 正文的同步镜像。**不能在 setContent 的 updater 里调 setRoundDiff**——
  // updater 必须是纯函数，在里面触发另一个 setState 是无效用法，React 19
  // StrictMode 还会双调用 updater，实测直接把 Agent 面板整个搞崩了。
  // 所以让 updater 只顺手写一下这个 ref（写 ref 是幂等的，双调用无害），
  // 轮末直接从 ref 读当前正文。
  //
  // **它同时是 `save()` 那条护栏的锚点**（P70 B）：见下面 `servedRef`。
  const liveContentRef = useMemo(() => {
    let v = ''
    return {
      get current() { return v },
      set current(next: string) {
        v = next
        // **写在 setter 里，不是写在 13 个赋值点上**（P68 B 那一课：`d.noteId()`
        // 改的是默认值不是 92 个调用点——漏一个那一处就静默读错）。这里漏一个的
        // 症状更糟：护栏拿着过期的锚点，会去挡一次**该存**的保存。
        servedRef.current = { id: servedRef.current.id, text: next, edits: 0 }
      },
    }
  }, [])
  /** 「服务端 / 流式**最后交给这一篇**的那一份正文」+「自那以后编辑器自己报了几次改动」。
   *
   *  P70 B 的护栏就靠这两样：`edits === 0` 说明**用户一个字都没动**，
   *  这时候 `content` 还比交下来的那一份短，那就只可能是 React 那边的镜像落后了
   *  （P68 实拍：后端交 1103、编辑器剩 807，1.5 秒后自动保存把 807 写回库，
   *  把后端刚落的那一份盖掉）。`id` 由 `open()` 写，正文由 `liveContentRef` 的 setter 写。 */
  const servedRef = useRef<Served>({ id: '', text: '', edits: 0 })
  /** 编辑器报上来的改动（**回声不算**，`editor/syncEcho.ts` 已经把它挡在外面了）：
   *  用户敲的字、悬停工具条的「接受 / 撤回」、`/` 块、粘贴——全走这一条。 */
  const onEditorChange = useCallback((next: string) => {
    servedRef.current.edits++
    setContent(next)
  }, [])
  // 定向续写的插入光标：null = 追加到文末；每轮开始时复位
  const insertCursorRef = useRef<number | null>(null)
  // 探针里的 setTimeout 回调抓的是那一次 render 的函数——闭包里的 current 是旧的
  // （实拍：harness 跑到了启动时自动打开的那篇上）。永远走最新的那份。
  const actionsRef = useRef({ runNoteHarness: (_m: 'write' | 'polish') => Promise.resolve(), runMagicTap: () => Promise.resolve(), handleSelectionAction: (_a: SelectionAction) => Promise.resolve(), runHarness: (_r: TreeRow) => Promise.resolve(), ingestCurrentNote: () => Promise.resolve(), runBlock: (_i: SlashItem, _f: number, _t: number, _p: string) => Promise.resolve(), dropIfStillEmpty: (_n: Note | null) => Promise.resolve(), collapseAll: () => Promise.resolve(), pushDiff: (_l: string, _b: string, _a: string, _r?: boolean) => {}, runSlides: (_s: 'points' | 'talk') => Promise.resolve(), onPickFile: (_f: FileList | null) => Promise.resolve(), restructureNote: () => Promise.resolve(), runSkeleton: (_b?: boolean) => Promise.resolve(), newNoteUnder: (_p: string) => Promise.resolve(), importMarkdown: (_f: FileList | null, _u?: string, _k?: boolean) => Promise.resolve(), runVoice: (_f: number, _t: number) => Promise.resolve(), flushChangeLayers: (_k?: boolean) => {} })
  const [noteHarnessStatus, setNoteHarnessStatus] = useState('')
  // 跑完之后那行结果（几轮、加了多少字、为什么停）留着，直到用户关掉 / 换笔记 /
  // 再跑一次。之前只弹一个 toast，几秒就没了，用户回头看只剩「改了 1 处」的工具条。
  const [harnessDone, setHarnessDone] = useState(false)
  const [showShortcuts, setShowShortcuts] = useState(false)
  // 摄入完成后让「记忆」重新召回一次：正文没变它不会自己再查，而刚入库的事实正是用户想看到的
  const [ingestTick, setIngestTick] = useState(0)
  const harnessDoneRef = useRef(false)
  /** reason=check_stuck 收工时「哪条判据、连响几轮」——后端在 RUN_FINISHED 之前
   *  发一条带 `stopped` 的 check_hit 事件（P6 问题 4），收工那句话从这儿取。 */
  const stuckCheckRef = useRef<{ check: string; rounds: number } | null>(null)
  // 逐轮处置：开着的话每轮写完就停下来，等你在编辑器里逐条接受/撤回，
  // 处置完再点「接着写」。关着是原来的行为——一口气跑完再处置，而那意味着
  // 你在跑的过程中做的处置会被下一轮盖掉。
  const [reviewEachRound, setReviewEachRound] = useState(false)
  const [pausedRun, setPausedRun] = useState<
    { id: string; noteId: string; mode: 'write' | 'polish' } | null>(null)
  // 这一轮是不是停在了「等你处置」。**必须是 ref 不是 state**：读它的地方是
  // runNoteHarness 的 finally，那是个闭包，state 在那里永远是这次运行开始时
  // 的旧值。
  const pausedRef = useRef(false)
  const [tapMeta, setTapMeta] = useState<TapMeta | null>(null)
  /** 刚写的那一段的确定性体检（后端 `harness/checks/tap.py`，计划 8.1）。
   *  **判了不拦**——跟产物一起摆在正文上方那条来源行下面，重不重来由用户定。 */
  const [tapNotes, setTapNotes] = useState<string[]>([])
  const [writingPlanParent, setWritingPlanParent] = useState<TreeRow | null>(null)
  const [harness, setHarness] = useState<HarnessState | null>(null)
  const [mdToKb, setMdToKb] = useState(false)
  const [job, setJob] = useState('')

  // harness 跑起来时右栏切到「计划」：计划 + 每轮判了什么，就在眼前（判据 3）
  useEffect(() => {
    if (loading === 'note-harness') setPaneFocus((f) => ({ id: 'plan', n: (f?.n ?? 0) + 1 }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading === 'note-harness'])

  /** 正文里引用了哪些事实（正则见 util/wordCount）。 */
  const citedIds = useMemo(() => citedFactIds(content), [content])

  const [healthMsg, setHealthMsg] = useState('')
  const [asrOffline, setAsrOffline] = useState('')
  async function checkHealth() {
    try {
      const h = await api.health()
      // LLM 不通是硬伤，红字常驻；语音是可选服务（没配 ASR 的用户是多数），
      // 只给一个灰色的「语音离线」，悬停看地址——之前一行 ⚠ 长期挂着像出了事故。
      // 没配过模型就说「还没配模型」，不报一个用户没有的地址（P19 #1 / P17 #1；`editor/preconditions.healthMessage`）
      setHealthMsg(healthMessage(h.llm ?? {}))
      setAsrOffline(!h.asr?.ok ? (h.asr?.base_url ?? '') : '')
    } catch { setHealthMsg('后端不可达') }
  }
  /** 要模型的动作开跑前先看一眼健康检查（P3「离线」列）：状态栏已经红着说「LLM 不可达」，
   *  再发请求只是转到连接超时才报同一句话。拦下、给「打开设置」、顺手再测一次好让红字自己消掉。 */
  function llmGate(): boolean {
    const why = llmGateMessage(healthMsg)
    if (!why) return true
    toastAction(why, '打开设置', () => void openVirtual('app:settings', '设置'), 8000)
    void checkHealth()
    return false
  }
  const [focusMode, setFocusMode] = useState(false)
  // 左右栏各自可拖宽、可独立折叠，按用户存本机（Trilium 存 leftPaneWidth /
  // rightPaneWidth / leftPaneVisible，我们同一套思路）。focusMode 保留为
  // 「两个都收」的快捷方式。
  const [panes, setPanes] = useState(() => {
    // 左栏默认 280 = 0.5.10 的 `--sidebar-width`（第 716 轮）。原来是 260——
    // 配上 16px 的内边距（也是他们的值）之后，260 会把树标题挤得更早截断。
    const d = { leftW: 280, rightW: 340, leftOn: true, rightOn: true }
    try {
      const raw = localStorage.getItem('memoket-note-panes:' + api.getUser())
      return raw ? { ...d, ...(JSON.parse(raw) as Partial<typeof d>) } : d
    } catch { return d }
  })
  useEffect(() => {
    try { localStorage.setItem('memoket-note-panes:' + api.getUser(), JSON.stringify(panes)) } catch { /* 无所谓 */ }
  }, [panes])
  // 窗口窄的时候正文优先：两侧栏保持用户设的宽度会把编辑器挤到 300px（900×600
  // 实拍：ribbon 折三行、工具栏溢出）。中栏不够 520px 就先收右栏（用户的开关不动，
  // 窗口拉宽自动回来）；左栏最多占窗口 30%。
  const [winW, setWinW] = useState(() => window.innerWidth)
  useEffect(() => {
    const on = () => setWinW(window.innerWidth)
    window.addEventListener('resize', on)
    return () => window.removeEventListener('resize', on)
  }, [])
  const { leftW, splitW, leftShown, rightShown } = layoutPanes({ winW, panes, splitW: split?.w ?? null, focusMode })
  const [selectionMenu, setSelectionMenu] = useState<{ x: number; y: number; text: string } | null>(null)
  // 光标所在段落：右栏「记忆」按它查跟知识库的关系（冲突 / 延续 / 印证 / 缺依据）
  const [cursorPara, setCursorPara] = useState('')
  // 边缘记忆：停止编辑 1.5s 后把含数字的段落批量拿去判关系，段首行右边亮点（零 LLM）
  const [marginMarks, setMarginMarks] = useState<MarginMark[]>([])
  /** 这篇里「缺依据 · 知识库连沾边的记录都没有」那一档有多少段（P25 #4）。**不画点**，
   *  在「记忆」面板上折成一句话——理由在 `editor/marginMemory.dotWorthy`。 */
  const [noRecordDots, setNoRecordDots] = useState(0)
  /** 页边圆点旁边的关系卡（P9，agent-native-editor §3.3）：悬停 / 点圆点、或光标进了亮黄点的段就贴在那一行旁边。 */
  const [marginCard, setMarginCard] = useState<{ m: MarginMark; anchor: DOMRect; reason: 'hover' | 'click' | 'cursor' } | null>(null)
  // ⌥ 悬停 / ⌥↩ 的来龙去脉卡（P16，§3.3 场景 B）：贴在词边、零模型；「查完整来龙去脉」才打模型
  const [traceCard, setTraceCard] = useState<TraceCardState | null>(null)
  // 烧过的跑（P16 改动的分层历史）：这篇历史版本里 reason='round' 的行按 run_id 组回轮次，烧之后还能逐轮撤
  const [runRevs, setRunRevs] = useState<api.NoteRevision[]>([])
  const [runsTick, setRunsTick] = useState(0)
  const runs = useMemo(() => groupRuns(runRevs), [runRevs])
  useEffect(() => {
    const id = current?.id
    if (!id) { setRunRevs([]); return }
    let alive = true
    api.listRevisions(id).then((r) => { if (alive) setRunRevs(r) }).catch(() => { if (alive) setRunRevs([]) })
    return () => { alive = false }
  }, [current?.id, current?.updated_at, harnessDone, runsTick])
  /** 文档意图（P9，§3.1）：这篇要干什么。打开时从库里读，没有就按标题预填（零模型）。 */
  const [intent, setIntent] = useState<DocIntent>(() => resolveIntent(null, ''))
  /** 意图改了（字段、或「完成标准」勾了一条）：本地先更新、落库、树上那份跟着变。用户改字段的路和勾选的路同一条。 */
  const saveIntent = useCallback((next: DocIntent) => {
    setIntent(next)
    const id = current?.id
    if (!id) return
    api.saveIntent(id, next)
      .then((n) => setNotes((prev) => prev.map((x) => (x.id === n.id ? { ...x, intent: n.intent } : x))))
      .catch((e) => toast('意图没存上：' + friendlyError(e), 'error'))
  }, [current?.id])
  /** 「完成标准」逐条核（P12 §3.1，零模型）：标题下的角标和右栏「计划」清单共用这一份。 */
  const doneChecksSum = useMemo(() => doneSummary(checkDone(intent.done, content, intent.checked ?? [])), [intent.done, intent.checked, content])
  // 生成骨架 / 智能排版的「停止」（P3 遗留 ❌×2：模型卡住只能干等 300 秒）
  const skeletonAbortRef = useRef<AbortController | null>(null)
  const restructureAbortRef = useRef<AbortController | null>(null)
  // 标题变了、意图还是预填的 → 跟着标题重推；用户改过一个字的（source=user）永远不覆盖
  // **把现在这份传进去，不要传 `null`**（P31 #1）：这个 effect 也挂在 `current?.id` 上，
  // 每打开一篇都会在上面那句「从库里读」之后再跑一次；传 `null` = 拿一份干净的预填把刚读出来的
  // 盖掉，于是 `checked` 每次开篇都被抹掉——勾过的完成标准关掉重开就退回 `0/n`
  // （库里 `notes.intent.checked` 一直是对的，纯粹丢在这一行）。传 `i` 照样跟着标题重推，
  // 只是把勾带过去；标题改了、判据对不上的那几个勾在 `resolveIntent` 里作废。
  //
  // **认的是界面上那个名字，不是标题框那一格**（P43 #2 / P42 问题 #2）。实拍：新建笔记、
  // 正文第一行打 `# 周报 9-20`，左栏树、标签页、状态栏**全都叫「周报 9-20」**，
  // 唯独 `input.note-title` 的 value 是空的——于是意图行一直空着、没有「预填」角标。
  // 一篇笔记只有一个名字（`displayTitle`，App 里另外五处用的就是它），预填也得认这一个。
  //
  // **重推的代价量过了**（$S/p43/bench2.ts，真函数 + 真库最长的两篇，各 2000 次取均值）：
  //   47k 字 / 2402 行（最长那篇）：`displayTitle` + `resolveIntent` = **0.10 ms**
  //   30k 字 / 533 行（公司汇报）：**0.03 ms**
  //   标题框里有字时 `displayTitle` 压根不碰正文：**0.0001 ms**
  // 一帧是 16.67ms，一个字的间隔 ~160ms——最坏那一档也只占一帧的 0.6%，**不用防抖**。
  // 真正要防的不是 CPU 是**重推的次数**：所以依赖挂的是**算出来的名字**，不是 `content`。
  // 名字没变（正文改的是第三段、或者标题框里本来就有字）这个 effect 一次都不跑，
  // 「会不会覆盖用户勾过的完成标准」那个担心从根上没了；名字真变了才重推，
  // 跟原来在标题框里打字时的行为逐字一样（`source === 'user'` 照旧永不覆盖）。
  const shownTitle = useMemo(() => displayTitle({ title, content }), [title, content])
  // **真机上数出来的**（P46 #5，P43 留的「下一步」：「视觉上会跳，真机上看一眼再定」）。
  // 一个字一个字敲 `# 周报 9-20：这周把众筹页面的文案定稿了，3月12号上线。`（32 个字、160ms 一个）：
  // 「目标」那一格**变了 19 次**，而且中间那十几帧是半句话——
  //   第 3 个字：「围绕「周」写清楚一件事」（**先跳到另一个模板**）
  //   第 4 个字：「周报：这段时间做了什么、进展到哪、卡在哪」（模板又跳回来）
  //   第 11–23 个字：「周报 9-20：这周把众**：这段时间做了什么…**」一个字一个字长出来
  // 标签页跟着变 20 次那是**标题**，看着正常；而这三格是**用户能改的输入框**——
  // 一个输入框在你打字时自己一格一格换内容，读起来就是坏了。**所以加防抖。**
  // 不是为 CPU（P43 量过 0.03–0.10ms / 次，占一帧的 0.6%），是为这 19 帧。
  const [settledTitle, setSettledTitle] = useState(shownTitle)
  useEffect(() => {
    if (settledTitle === shownTitle) return
    const t = setTimeout(() => setSettledTitle(shownTitle), INTENT_PREFILL_IDLE_MS)
    return () => clearTimeout(t)
  }, [shownTitle, settledTitle])
  // **换篇不等**：那一下不是「打字打到一半」，是一篇新的东西开了，
  // 晚半秒才填出来会被读成「这篇没预填」。
  useEffect(() => { setSettledTitle(displayTitle({ title, content })) },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [current?.id])
  useEffect(() => {
    if (!current) return
    setIntent((i) => (i.source === 'user' ? i : resolveIntent(i, settledTitle)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settledTitle, current?.id])
  const [scopeTick, setScopeTick] = useState(0)
  useEffect(() => {
    const on = () => setScopeTick((t) => t + 1)
    window.addEventListener('memory-scope-changed', on)
    // 卡上点了「忽略」：那个点当场灭掉，不等下一轮重算
    const gone = (e: Event) => setMarginMarks((prev) => prev.filter((m) => markKey(m) !== (e as CustomEvent<string>).detail))
    window.addEventListener('relation-ignored', gone)
    return () => { window.removeEventListener('memory-scope-changed', on); window.removeEventListener('relation-ignored', gone) }
  }, [])
  // 段落文本 → 判定 的缓存（P10 C3-5）：知识库变了（摄入 / 换范围）才清
  const marginCache = useRef(new Map<string, MarginVerdict>())
  useEffect(() => { marginCache.current.clear() }, [ingestTick, scopeTick])
  useEffect(() => {
    if (!current) { setMarginMarks([]); setNoRecordDots(0); return }
    // 图片 / 链接地址 / 引用 id 先剥掉：一行 `![x](/api/assets/52dd….png)` 里的数字会让它过门槛去召回。
    // **不封顶**（P1-1d）：原来 `.slice(0, 80)`，30k 字的笔记第 80 个含数字的段落之后一个点都没有，
    // 「有的段有点、有的段没有」；现在按 80 一批分几次发，每批几十毫秒。
    const paras = marginParagraphs(content, stripForRecall)
    if (paras.length === 0) { setMarginMarks([]); setNoRecordDots(0); return }
    let stale = false
    const t = setTimeout(async () => {
      // 文本没变的段直接用缓存；只把没见过的段送去问（P10：30k 字首次 ~15s → 改一段后 1.6s 含防抖）。
      // 几批按序发、**每批回来就先画**（并行没更快：后端是串行的，实拍 2 批并行反而 21.6s）。
      if (marginCache.current.size > MARGIN_CACHE_MAX) marginCache.current.clear()
      const { hits, misses } = splitCached(paras, marginCache.current)
      const marks: MarginMark[] = [...hits]
      const ignored = ignoredSet()                 // 「忽略」过的那一对不再亮点（右栏的卡同一份名单）
      // P25 #4：`no_record` 那一档（知识库里连沾边的记录都没有）不逐段画点——
      // 理由写在 `editor/marginMemory.dotWorthy` 上；这里只负责「不画」和「数出来有多少段」，
      // 面板上那一句由 `noRecordNote` 说。
      const show = () => {
        const keep = [...marks].sort((a, b) => a.line - b.line).filter((m) => !ignored.has(markKey(m)))
        setNoRecordDots(keep.filter((m) => !dotWorthy(m)).length)
        setMarginMarks(keep.filter(dotWorthy))
      }
      if (misses.length === 0 || hits.length) show()
      for (const chunk of chunked(misses, MARGIN_BATCH)) {
        try {
          const r = await api.memoryRelationsBatch(chunk.map((p) => p.text))
          r.marks.forEach((m, i) => {
            const v: MarginVerdict = m ? { relation: m.relation, say: m.say, kinds: m.kinds, fact_ids: m.fact_ids, facts: m.facts, why: m.why } : null
            marginCache.current.set(chunk[i].text, v)   // 先进缓存：就算这一轮作废，下一轮也不用再问这些段
            if (v) marks.push({ ...v, line: chunk[i].line })
          })
          if (stale) return                        // 正文又改了，这一批作废，等下一轮
        } catch { return }
        show()
      }
    }, 1500)
    return () => { stale = true; clearTimeout(t) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, current?.id, ingestTick, scopeTick])
  const [selectionBusy, setSelectionBusy] = useState<false | SelectionAction>(false)
  // 右键菜单那五个动作的「停止」（P3：模型卡住时原来只能干等 300 秒，连 Esc 都关不掉那个转圈）
  const selectionAbortRef = useRef<AbortController | null>(null)
  // 整个回包而不是只留 findings（P37 #2）：空 findings 那句话要按 `checked` / `unparsed` 分三说。
  // 外加 `passage`（P41 #3）：这块卡是**按当时选中的那一段**算的，卡上得写出来是哪一段。
  const [verifyResult, setVerifyResult] = useState<(VerifyResult & { passage: string }) | null>(null)
  // P17 实拍：在 A 篇右键「校验」，切到 B 篇，右栏顶上还挂着 A 的「校验结果」——它是按 A 的选区算的，换篇就清
  useEffect(() => { setVerifyResult(null) }, [current?.id])
  // P17 实拍：右键「自定义提示」→「全部撤回」→ 关掉这篇再打开，正文里冒出一个幻影「硬件」删除标 + 「改动 1」——
  // `roundDiff` 是给编辑器的一条「加一层」消息，层本身活在编辑器的 field 里；消息发过就该作废，
  // 不清的话编辑器一重挂（关掉重开 / 换篇）就按旧坐标再加一遍层，标到别的字上
  useEffect(() => { setRoundDiff(null) }, [current?.id])
  /** 「来龙去脉」的结果。落在右栏的标签里而不是弹层——判据 2：看一条旧记录
   *  不该离开这一页，弹层要么盖住正文、要么关掉就没了。 */
  const [trace, setTrace] = useState<
    { answer: string; facts: api.Fact[]; recalled?: number | null; at: string; passage?: string } | null>(null)

  const editorViewRef = useRef<EditorView | null>(null)
  /** 右栏「计划」里点目录 / 节拍的行号（P12）：光标跳到正文那一行、滚到中间 */
  const jumpToLine = useCallback((line: number) => {
    const v = editorViewRef.current
    if (!v) return
    const l = v.state.doc.line(Math.max(1, Math.min(line, v.state.doc.lines)))
    v.dispatch({ selection: { anchor: l.from }, effects: EditorView.scrollIntoView(l.from, { y: 'center' }) })
    v.focus()
  }, [])
  /** 「说的是你选中的这一段」那两行的点击动作（P46 #4 / P41 留的第 4 条）。
   *  **跳不回去就回 `undefined`**，那时候两块卡都只把那一行当普通字摆着——
   *  一个点了没反应的链接比不能点更糟。判据在 `passageLine`：正文里不多不少一处才给。
   *  跳本身复用 P12 那个 `jumpToLine`，不另写一套滚动。 */
  const jumpToPassage = useCallback((passage?: string) => {
    const line = passageLine(content, passage ?? '')
    return line === null ? undefined : () => jumpToLine(line)
  }, [content, jumpToLine])
  const abortRef = useRef<AbortController | null>(null)

  // setTimeout callbacks close over whatever `loading` was at schedule time,
  // which is stale by the time they fire seconds later -- a ref mirror gives
  // them the live value so a background run doesn't stack on top of another
  // one (manual or auto) that's already in flight.
  const loadingRef = useRef(loading)
  useEffect(() => { loadingRef.current = loading }, [loading])
  const lastSkeletonContent = useRef('')

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
    // 库里已经没有的笔记（别处删的、导入回滚的）标签也收掉——留着点了只会「找不到」
    const ids = new Set(list.map((n) => n.id))
    // 虚拟标签也过一遍：不认识的 kb:* id（旧版本留下的 kb:overview）一起收掉
    const knownVirtual = isKnownVirtual
    setTabs((prev) => prev
      .filter((t) => (api.isVirtualId(t.noteId) ? knownVirtual(t.noteId) : ids.has(t.noteId)))
      // 旧版本存下来的标签标题就是裸 id（kb:fact:terrence-…）：补个名字
      .map((t) => (t.title === t.noteId && t.noteId.startsWith('kb:fact:') ? { ...t, title: '事实 ' + t.noteId.slice(8) }
        : t.noteId.startsWith('kb:unit:') && t.title === t.noteId.slice(8) ? { ...t, title: '会议记录' } : t)))
    return list
  }, [])

  useEffect(() => {
    try {
      localStorage.setItem('memoket-note-tabs:' + api.getUser(), JSON.stringify(tabs))
    } catch { /* 隐私模式下写不了，不值得为它报错 */ }
  }, [tabs])
  useEffect(() => {
    if (!current) return
    try { localStorage.setItem('memoket-note-active:' + api.getUser(), current.id) } catch { /* 同上 */ }
  }, [current])
  // 窗口标题跟着当前笔记走（Mission Control / 窗口切换 / 任务栏里认得出是哪篇）
  useEffect(() => {
    const what = current ? displayTitle({ title, content }) : (virtualId ? (VIRTUAL_LABELS[virtualId] ?? tabs.find((t) => t.noteId === virtualId)?.title ?? '') : '')
    document.title = what ? `${what} · MEMOKET NOTE` : 'MEMOKET NOTE'
  }, [current, title, content, virtualId, tabs])

  /** 打开一篇笔记时同步标签：已经开着就切过去，没开就新开一个。
   *
   *  **不是每打开一篇就无限堆标签**——那样几分钟后标签行就满了。已开的
   *  复用，是浏览器和 Trilium 共同的做法。 */
  const syncTab = useCallback((note: Note) => {
    // **updater 必须是纯函数。** 第一版把 setActiveTabId 写在 setTabs 的
    // updater 里面——这个文件在别处已经为同一件事写过警告（见 liveContentRef
    // 上面那段）：React 19 StrictMode 会双调用 updater。实拍的结果是连开三篇
    // 只出现一个标签。
    //
    // 现在这里只管「有没有这个标签」，**哪个是当前**由下面那个 effect 从
    // current 推导——一个真相，不用两处同步。
    const label = displayTitle(note)
    setTabs((prev) => {
      const found = prev.find((x) => x.noteId === note.id)
      if (found) {
        return found.title === label
          ? prev
          : prev.map((x) => (x.id === found.id ? { ...x, title: label } : x))
      }
      return [...prev, { id: 't' + Math.random().toString(36).slice(2, 9),
                         noteId: note.id, title: label }]
    })
  }, [])

  // 标签名跟着标题/首行走：用户改了标题，标签上还是旧名字会让他以为没改上。
  useEffect(() => {
    if (!current) return
    const label = displayTitle({ title, content })
    setTabs((prev) => {
      const found = prev.find((x) => x.noteId === current.id)
      return found && found.title !== label
        ? prev.map((x) => (x.id === found.id ? { ...x, title: label } : x))
        : prev
    })
  }, [title, content, current])

  // 当前标签从 current 推导。这样「打开笔记」只有一件事要做（syncTab），
  // 高亮哪个是它的结果，不是又一处要记得同步的状态。
  useEffect(() => {
    const key = current?.id ?? virtualId
    if (!key) return
    const tab = tabs.find((x) => x.noteId === key)
    if (tab && tab.id !== activeTabId) setActiveTabId(tab.id)
  }, [current, virtualId, tabs, activeTabId])

  function reopenLastTab() {
    const c = closedTabs.current.pop()
    if (!c) return
    const t = c.tab
    setTabs((prev) => {
      if (prev.find((x) => x.noteId === t.noteId)) return prev
      const at = Math.min(c.at, prev.length)
      return [...prev.slice(0, at), t, ...prev.slice(at)]
    })
    activateTab(tabs.find((x) => x.noteId === t.noteId) ?? t)
  }
  function closeTabsWhere(pred: (t: Tab, i: number) => boolean) {
    const gone = tabs.filter(pred)
    if (gone.length === 0) return
    closedTabs.current = [...closedTabs.current, ...gone.map((tab) => ({ tab, at: tabs.indexOf(tab) }))].slice(-20)
    const next = tabs.filter((t, i) => !pred(t, i))
    setTabs(next)
    if (activeTabId && gone.some((t) => t.id === activeTabId)) {
      if (next[0]) activateTab(next[0])
      else { setActiveTabId(null); setCurrent(null); setVirtualId(null); setTitle(''); setContent('') }
    }
  }
  /** 标签的右键菜单（tab_row.ts:377-416 那 9 项里跟我们相关的）。禁用时带原因。 */
  function tabMenuItems(tab: Tab): MenuItem[] {
    const i = tabs.findIndex((x) => x.id === tab.id)
    const only = tabs.length <= 1
    const last = i === tabs.length - 1
    const none = closedTabs.current.length === 0
    return [
      { label: '在右侧分屏打开', icon: 'bx-columns', onSelect: () => openInSplit(tab.noteId) },
      { kind: 'sep' },
      { label: '关闭', icon: 'bx-x', shortcut: '⌘W', onSelect: () => closeTab(tab.id) },
      { label: '关闭其他', disabled: only, hint: only ? '只有这一个' : undefined,
        onSelect: () => closeTabsWhere((t) => t.id !== tab.id) },
      { label: '关闭右侧', disabled: last, hint: last ? '已经是最右边' : undefined,
        onSelect: () => closeTabsWhere((_t, k) => k > i) },
      { label: '关闭全部', onSelect: () => closeTabsWhere(() => true) },
      { kind: 'sep' },
      { label: '重新打开刚关的', shortcut: '⇧⌘T', disabled: none, hint: none ? '没有刚关的' : undefined,
        onSelect: reopenLastTab },
    ]
  }
  function reorderTab(id: string, index: number) {
    setTabs((prev) => {
      const from = prev.findIndex((t) => t.id === id)
      if (from < 0) return prev
      const next = prev.filter((t) => t.id !== id)
      next.splice(index > from ? index - 1 : index, 0, prev[from])
      return next
    })
  }

  /** 关一个标签。关掉当前这个时切到**右边那个**（没有就左边）——跟浏览器
   *  一致。跳回列表第一篇会让用户失去位置感。 */
  tabsRef.current = tabs
  closeTabRef.current = closeTab
  // 应用菜单「标签」（main.tsx 把 menu 事件转成 window 'tab-action'）：每次渲染刷一份最新闭包
  tabActionRef.current = (action) => {
    const i = tabs.findIndex((t) => t.id === activeTabId)
    if (action === 'close') { if (activeTabId) closeTab(activeTabId) }
    else if (action === 'reopen') reopenLastTab()
    else if (action === 'next' || action === 'prev') { if (tabs.length > 1) activateTab(tabs[(i + (action === 'next' ? 1 : -1) + tabs.length) % tabs.length]) }
    else if (action === 'list') setTabListAt({ x: Math.max(8, window.innerWidth - 420), y: 44 })
    else if (action === 'close-others') closeTabsWhere((t) => t.id !== activeTabId)
  }
  function closeTab(id: string) {
    const i = tabs.findIndex((x) => x.id === id)
    if (i < 0) return
    if (current && tabs[i].noteId === current.id && freshEmpty.current.has(current.id) && !title.trim() && !content.trim()) {
      void dropIfStillEmpty(current)
    }
    closedTabs.current = [...closedTabs.current, { tab: tabs[i], at: i }].slice(-20)
    const next = tabs.filter((x) => x.id !== id)
    setTabs(next)
    if (id !== activeTabId) return
    const fallback = next[i] ?? next[i - 1] ?? null
    if (fallback) activateTab(fallback)
    else {
      setActiveTabId(null); setCurrent(null); setVirtualId(null); setTitle(''); setContent('')
    }
  }

  const reloadTree = useCallback(async (kb = true) => {
    const t0 = performance.now()
    const rows = await api.getTree()
    const fetched = performance.now() - t0
    setTree(rows)
    // 大库量一眼：几百篇时树的取数和首帧各花多久（探针看 client-log）
    if (rows.length >= 200) requestAnimationFrame(() => void api.clientLog('info', `tree ${rows.length} rows: fetch ${Math.round(fetched)} ms, paint ${Math.round(performance.now() - t0)} ms`, '', 'perf'))
    // 知识库子树跟着一起刷：摄入完新事实，主题/月份的计数要跟上。
    // 取不到（KITE 还没建库）就当没有，不影响真笔记。
    // 保存正文不动知识库（引用计数在 notes 树那边）：save() 传 false，别每敲一段就重拉一次知识库树。
    if (kb) api.kbTree().then((rows) => setKbRows(rows.filter(notSpeakerEntity))).catch(() => setKbRows([]))
    return rows
  }, [])

  /** 树上不列录音转写的说话人标签（Speaker A / speaker_c…）：它们是「实体」里事实最多的前五个，
   *  展开「实体」头一屏全是它们（第 203 轮真库实测 2858 / 2296 / 1318…）。索引页默认也藏着，那里有开关能看。 */
  const notSpeakerEntity = (r: TreeRow) => !(r.note_id.startsWith('kb:entity:') && isSpeakerTag(r.title))
  // 虚拟节点的标签可能在 kbRows 到之前就开了（恢复的标签、探针），名字还是
  // 裸 id——数据到了补成真名。
  useEffect(() => {
    if (kbRows.length === 0) return
    setTabs((prev) => {
      let changed = false
      const next = prev.map((t) => {
        if (!api.isVirtualId(t.noteId) || t.title !== t.noteId) return t
        const r = kbRows.find((x) => x.note_id === t.noteId)
        if (!r) return t
        changed = true
        return { ...t, title: r.title }
      })
      return changed ? next : prev
    })
    // tabs 也在依赖里：标签可能在 kbRows 到了**之后**才开（探针、恢复的标签），
    // 只盯 kbRows 就永远等不到下一次。有 changed 守卫，不会循环。
  }, [kbRows, tabs])

  /** 真笔记 + 虚拟子树，一个控件画。虚拟节点的展开状态从本机的集合来。 */
  /** 树上的行 = 用户自己的笔记 + **一行**知识库入口。
   *
   * 知识库原来是整棵子树接在树的最底下（主题 / 实体 / 时间线…一层层展开）。
   * 不合适，理由在 docs/sidebar-ia-plan.md §1，一句话说：**树是「我写的、我摆
   * 的」，知识库是「机器抽的、机器摆的」**，两套层级规则相反——笔记能改名能拖
   * 能删，主题不能；而且体量倒挂，实测这个库真笔记 26 行、知识库子树 180 行，
   * 排在最底下的那个节点装的东西比它上面所有东西加起来多一个数量级。
   *
   * 留这一行是因为它在回答「我的材料在哪」；点进去才回答「里面有什么」——
   * 下钻交给知识库首页，那一页（搜索 + 数字 + 月度图 + 主题 / 实体 / 最近摄入）
   * 本来就比在树里一层层展开好用。而「写作时够到知识」有两条更好的路：右栏的
   * 「记忆」面板和 ⌘K。 */
  const allRows = useMemo(() => {
    const entry = kbRows.find((r) => r.note_id === 'kb')
    return entry ? [...tree, { ...entry, child_count: 0, is_expanded: false }] : tree
  }, [tree, kbRows])

  // 截图探针：打开事实最多的那个主题（kb-tree），或它名下第一条事实（kb-fact）。
  // 以前还要先把树展开到那儿——知识库不在树里之后就没这一步了（第 619 轮）。
  const kbProbeDone = useRef(false)
  useEffect(() => {
    const probe = new URLSearchParams(location.search).get('probe')
    if (!probe?.startsWith('kb-') || probe === 'kb-tab' || kbProbeDone.current || kbRows.length === 0) return
    const first = kbRows.filter((r) => r.parent_note_id === 'kb:topics')
      .sort((a, b) => b.fact_count - a.fact_count)[0]
    if (!first) return
    kbProbeDone.current = true
    if (probe === 'kb-fact') {
      void api.kbTreeChildren(first.note_id).then((rows) => {
        if (rows[0]) void openVirtual(rows[0].note_id, rows[0].title)
        else void openVirtual(first.note_id, first.title)
      })
    } else void openVirtual(first.note_id, first.title)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kbRows])

  /** 打开一个虚拟节点：一条事实 = 一篇只读笔记，占中栏、开标签，跟真笔记
   *  一样的肌肉记忆。离开正在写的那篇之前先落盘——跟 switchTo 同一条纪律。 */
  async function openVirtual(id: string, title?: string) {
    // 传进来的是普通笔记 id（探针 open:<noteId>、旧标签页残留）就走笔记那条路——
    // 实拍：一个笔记 id 会被当成实体名渲染成「别名：<正文前 100 字>」的知识库页。
    if (!api.isVirtualId(id)) {
      const n = notes.find((x) => x.id === id)
      if (n) { await switchTo(n); return }
    }
    // 不认识的 kb:* id（比如早年的 kb:overview）落到总览，别开一页只有裸 id 的空页
    // 事实表带查询串（kb:facts?kind=plan，首页类型 / 说话人 chip 点进来的）也是认识的——第 132 轮实拍点 chip 落回了总览
    if (id.startsWith('kb:') && !isKnownVirtual(id)) id = 'kb'
    if (virtualId === id && !current) return
    rememberSpot()          // 去知识库看一眼再回来，也该回到原处（第 588 轮）
    await save()
    const leaving = current
    pushHistory(id)
    void dropIfStillEmpty(leaving)
    setCurrent(null); setTitle(''); setContent('')
    setVirtualId(id)

    // 带筛选的事实表：标签叫「事实表 · work」而不是树上那行「还有 N 条 · 去事实表看」（那是入口的话，不是页面的名字）
    const label = title ?? factsLabel(id) ?? allRows.find((r) => r.note_id === id)?.title ?? VIRTUAL_LABELS[id]
      ?? (id.startsWith('kb:unit:') ? '会议记录' : /^kb:(topic|entity):/.test(id) ? id.split(':').slice(2).join(':')
        : id.startsWith('kb:fact:') ? '事实 ' + id.slice(8) : id)
    setTabs((prev) => prev.find((x) => x.noteId === id)
      // 已经开着：名字按现在的规则刷一遍（标签落 localStorage，老规则起的名会一直留着——实拍带筛选的事实表标签还叫「事实表」）
      ? prev.map((x) => (x.noteId === id && x.title !== label ? { ...x, title: label } : x))
      : [...prev, { id: 't' + Math.random().toString(36).slice(2, 9), noteId: id, title: label }])
  }

  // 右栏那些面板没有 openVirtual 的句柄，用一个窗口事件把「打开某个虚拟节点」
  // 送过来（跟 open-command-palette 同一个模式）。
  useEffect(() => {
    const on = (e: Event) => { const id = (e as CustomEvent<string>).detail; if (id) void openVirtual(id) }
    const onNew = () => void newNote()
    const onToday = () => void openToday()
    window.addEventListener('open-today', onToday)
    const onKeys = () => setShowShortcuts(true)
    // 编辑器里的 ⌘[ / ⌘] 被 CodeMirror 的缩进吃掉了，编辑器自己把它们转成这个事件
    const onNav = (e: Event) => goHistory((e as CustomEvent<number>).detail < 0 ? -1 : 1)
    window.addEventListener('nav-history', onNav)
    // 树底部那两个钮现在只在鼠标进左栏时现身，⌘K 里给个键盘入口
    const onLocate = () => setLocateTick((v) => v + 1)
    const onCollapse = () => void actionsRef.current.collapseAll()
    window.addEventListener('tree-locate', onLocate)
    window.addEventListener('tree-collapse', onCollapse)
    // 整库导出：导航到接口地址就是下载（Electron 走系统的保存对话框）
    const onExport = () => { void save(); window.location.href = `/api/export/markdown?user=${encodeURIComponent(api.getUser())}` }
    window.addEventListener('export-all', onExport)
    // 桌面壳退出前问一声：存完回 flushed（存失败也回，别卡住退出——草稿已经落本机）
    // 退出时刚建、一个字没写的「未命名」也收掉——切走时会收，退出时之前不收，demo 库里
    // 攒了四篇空「未命名」（实拍）。走 actionsRef 拿最新闭包，这个 effect 的 current 是旧的。
    const onFlush = () => {
      rememberSpot()          // ⌘Q 退出前也记一次位置（第 591 轮：只在切走时记，直接关掉就丢了）
      save().catch(() => {})
        .then(() => actionsRef.current.dropIfStillEmpty(currentRef.current)).catch(() => {})
        .finally(() => window.memoketDesktop?.flushed?.())
    }
    window.addEventListener('flush-save', onFlush)
    // 刷新 / 关窗：desktop 的 ⌘Q 走 flush-save，网页版和 reload 走这里
    const onUnload = () => rememberSpot()
    window.addEventListener('beforeunload', onUnload)
    const onOpenNote = (e: Event) => {
      const id = (e as CustomEvent<string>).detail
      const n = notes.find((x) => x.id === id)
      if (n) { void switchTo(n); return }
      // 刚建的（比如「存为笔记」）还不在列表里：拉一次再开，别急着说不存在
      void api.getNote(id).then((fresh) => { void reload(); void reloadTree(); void switchTo(fresh) }).catch(() => toast('链接指向的笔记不存在了', 'error'))
    }
    // 虚拟页面加载完才知道真名（会议页的标题）：把标签改过来
    const onTitle = (e: Event) => {
      const { id, title } = (e as CustomEvent<{ id: string; title: string }>).detail
      setTabs((prev) => prev.map((t) => (t.noteId === id && t.title !== title ? { ...t, title } : t)))
    }
    window.addEventListener('virtual-title', onTitle)
    // 虚拟页自己说「我指的东西不在了」（事实 404）：收掉它的标签。走 closeTabRef 拿最新闭包
    const onGone = (e: Event) => { const id = (e as CustomEvent<string>).detail; const t = tabsRef.current.find((x) => x.noteId === id); if (t) closeTabRef.current(t.id) }
    window.addEventListener('virtual-gone', onGone)
    const onTabAction = (e: Event) => tabActionRef.current((e as CustomEvent<string>).detail)
    window.addEventListener('tab-action', onTabAction)
    window.addEventListener('open-note', onOpenNote)
    window.addEventListener('open-virtual', on)
    window.addEventListener('new-note', onNew)
    window.addEventListener('show-shortcuts', onKeys)
    // ⌘K「换个图标」/ 树菜单「换个图标…」：只对主栏正开着的那篇；没开笔记就提示
    const onIconPicker = () => { if (current) setIconPicker(true); else toast('先打开一篇笔记再换图标') }
    window.addEventListener('open-icon-picker', onIconPicker)
    return () => { window.removeEventListener('open-icon-picker', onIconPicker); window.removeEventListener('open-today', onToday); window.removeEventListener('virtual-title', onTitle); window.removeEventListener('virtual-gone', onGone); window.removeEventListener('tab-action', onTabAction); window.removeEventListener('open-virtual', on); window.removeEventListener('new-note', onNew); window.removeEventListener('show-shortcuts', onKeys); window.removeEventListener('open-note', onOpenNote); window.removeEventListener('nav-history', onNav); window.removeEventListener('tree-locate', onLocate); window.removeEventListener('tree-collapse', onCollapse); window.removeEventListener('export-all', onExport); window.removeEventListener('flush-save', onFlush); window.removeEventListener('beforeunload', onUnload) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, virtualId, allRows, notes])

  /** 点标签 / ⌘数字 / 关标签后的回退，都走这一条：真笔记就 switchTo，
   *  虚拟节点就 openVirtual。 */
  function activateTab(tab: Tab | undefined) {
    if (!tab) return
    if (api.isVirtualId(tab.noteId)) { void openVirtual(tab.noteId, tab.title); return }
    const note = notes.find((n) => n.id === tab.noteId)
    if (note) void switchTo(note)
    else setActiveTabId(tab.id)
  }

  /** 树上点了一个节点。 */
  function openFromTree(id: string, mods?: { alt: boolean }) {
    if (api.isVirtualId(id)) { void openVirtual(id); return }
    const n = notes.find((x) => x.id === id)
    if (!n) return
    if (mods?.alt) setQuick(n)     // 不离开当前笔记看一眼（PopupEditor）
    else void switchTo(n)
  }

  /** 当前在看的东西在树上的路径（面包屑）。克隆时取第一条。 */
  const noteIdSet = useMemo(() => new Set(notes.map((n) => n.id)), [notes])
  const crumbs = useMemo(
    () => buildCrumbs(current?.id ?? virtualId, allRows, (id) => tabs.find((t) => t.noteId === id)?.title, api.isVirtualId),
    [current, virtualId, allRows, tabs])
  /** 这一篇是不是日记里的某一天（是的话 ribbon 上多一块「屏幕活动」，计划 §8.4）。
   *  memo 住：它要把整棵树摊成一张表，每次渲染重算是白花钱。 */
  const journalDay = useMemo(
    () => (current ? journalDateOf(allRows, current.id) : null), [current, allRows])

  /** 虚拟节点的右键菜单——没有「删除」「移动」这些：它们不是笔记，是知识库
   *  的一个视角。有的是把它带进笔记的动作。 */
  function kbMenuItems(row: TreeRow): MenuItem[] {
    const isFact = api.isFactId(row.note_id)
    const factId = row.note_id.slice('kb:fact:'.length)
    const items: MenuItem[] = [
      { label: '打开', icon: 'bx-link-external', onSelect: () => void openVirtual(row.note_id, factsLabel(row.note_id) ?? row.title) },   // 尾巴行的名字是入口的话，标签用页面名
      { label: '在右侧分屏打开', icon: 'bx-columns', onSelect: () => openInSplit(row.note_id) },
    ]
    if (isFact) {
      items.push(
        { kind: 'sep' },
        { label: '复制引用', icon: 'bx-copy', hint: `[${factId}]`,
          onSelect: () => { void navigator.clipboard.writeText(`[${factId}]`) } },
      )
      if (current) items.push({ label: '引用到当前笔记', icon: 'bx-link', hint: current.title || '未命名',
                                onSelect: () => insertAtCursor(`[${factId}]`) })
    }
    return items
  }

  /** 树上右键。**harness 的动作直接长在节点上**——智能续写/打磨是对某一篇
   *  的，无限续写是对某一棵子树的，而树上本来就有「一篇」和「一棵子树」
   *  这两个层级。做成节点自带的能力，而不是另开一个面板去选目标。
   *
   *  分组照 Trilium 的树菜单：打开 → 插入 → 结构操作 → 剪贴/克隆 → 危险动作。
   */
  function treeMenuItems(row: TreeRow): MenuItem[] {
    const note = notes.find((n) => n.id === row.note_id)
    const isClone = row.branch_count > 1
    return [
      { label: '打开', icon: 'bx-link-external', shortcut: '↩', onSelect: () => { if (note) void switchTo(note) } },
      { label: '在新标签打开', icon: 'bx-window-open', onSelect: () => { if (note) { syncTab(note); void switchTo(note) } } },
      { label: '快速查看', icon: 'bx-show', hint: '⌥点击', onSelect: () => { if (note) setQuick(note) } },
      { label: '在右侧分屏打开', icon: 'bx-columns', hint: '对照着写', onSelect: () => openInSplit(row.note_id) },
      { kind: 'sep' },
      { kind: 'header', label: '新建' },
      { label: '插入子笔记', icon: 'bx-plus', hint: '成为它的下一级',
        onSelect: () => void newNoteUnder(row.note_id) },
      { label: '在后面插入笔记', icon: 'bx-subdirectory-right',
        onSelect: () => void newNoteUnder(row.parent_note_id) },
      { label: '重命名', icon: 'bx-rename', shortcut: 'F2', onSelect: () => void renameNode(row) },
      { label: '换个图标…', icon: 'bx-smile', hint: '树 / 标签 / 标题行同一个',
        onSelect: () => { const n = notes.find((x) => x.id === row.note_id); if (n) void switchTo(n).then(() => setTimeout(() => window.dispatchEvent(new CustomEvent('open-icon-picker')), 50)) } },
      { label: '导入 .md 到这里…', icon: 'bx-import', hint: '多个文件成一棵子树',
        onSelect: () => { importUnder.current = row.note_id; importInput.current?.click() } },
      { kind: 'sep' },
      { kind: 'header', label: 'AI' },
      // ---- 我们自己的：harness 就在这儿，跟结构操作平级
      { label: '智能续写这篇', icon: 'bx-bot', disabled: !note,
        onSelect: () => { if (note) void openAndRun(note, 'write') } },
      { label: '打磨这篇', icon: 'bx-brush', disabled: !note || !(note.content ?? '').trim(),
        onSelect: () => { if (note) void openAndRun(note, 'polish') } },
      { label: '对这棵子树无限续写', icon: 'bx-rocket', disabled: row.child_count === 0,
        hint: row.child_count === 0 ? '它下面还没有笔记' : undefined,
        onSelect: () => setWritingPlanParent(row) },
      { kind: 'sep' },
      { label: '克隆到…', icon: 'bx-duplicate', hint: '同一篇，两处都能看到',
        onSelect: () => void cloneNodeTo(row) },
      { label: '移动到…', icon: 'bx-transfer', onSelect: () => void moveNodeTo(row) },
      { label: '从这个位置移除', icon: 'bx-unlink', disabled: !isClone,
        hint: isClone ? undefined : '它只在这一个位置',
        onSelect: () => void detachNode(row) },
      { label: '复制笔记路径', icon: 'bx-copy-alt', onSelect: () => void copyNotePath(row) },
      { kind: 'sep' },
      { label: row.child_count > 0 ? '删除（连同子树）' : '删除', icon: 'bx-trash', danger: true, shortcut: '⌫',
        hint: row.child_count > 0 ? `会一起删掉 ${row.child_count} 篇` : undefined,
        onSelect: () => { if (note) void removeWithSubtree(note, row) } },
    ]
  }

  /** 删一棵子树之前列出会删掉什么——它会连带删掉看不见的东西，用户在点之前
   *  不知道会删几篇（Trilium 的 delete_notes 对话框）。单篇仍走乐观删除 + 撤销。 */
  async function removeWithSubtree(note: Note, row: TreeRow) {
    const kids = [...subtreeIds(row.note_id)].filter((id) => id !== row.note_id)
    if (kids.length === 0) { remove(note); return }
    const names = kids.slice(0, 8).map((id) => '· ' + displayTitle(tree.find((r) => r.note_id === id) ?? { title: id }))
    const ok = await askConfirm({
      title: `删除「${displayTitle(row)}」和它下面的 ${kids.length} 篇？`,
      detail: names.join('\n') + (kids.length > 8 ? `\n· …还有 ${kids.length - 8} 篇` : ''),
      okLabel: '删除', danger: true,
    })
    if (ok) remove(note, new Set([row.note_id, ...kids]))
  }

  /** 折叠整棵树。知识库现在是一行入口，没有可折的东西了（第 619 轮）。 */
  async function collapseAll() {
    const open = tree.filter((r) => r.is_expanded)
    setTree((prev) => prev.map((r) => ({ ...r, is_expanded: false })))
    await Promise.all(open.map((r) => api.setBranchExpanded(r.note_id, r.parent_note_id, false).catch(() => {})))
  }

  async function newNoteUnder(parentId: string) {
    let n: Note
    try { n = await api.createNote('', '', parentId) } catch (e) { toast('新建笔记失败：' + friendlyError(e), 'error'); return }
    freshEmpty.current.add(n.id)
    await Promise.all([reload(), reloadTree()])
    void switchTo(n)
  }

  /** 应用内的输入框，Promise 形式——调用处跟原来用 window.prompt 一样直。 */
  const composeAsk = (title: string, initial: string) =>
    new Promise<string | null>((resolve) => setPrompt({ title, initial, resolve: (v) => { setPrompt(null); resolve(v) } }))
  const askConfirm = (req: Omit<ConfirmRequest, 'resolve'>) =>
    new Promise<boolean>((resolve) => setConfirmReq({ ...req, resolve: (ok) => { setConfirmReq(null); resolve(ok) } }))
  const askNode = (title: string, exclude: Set<string>, first: string[] = []) =>
    new Promise<string | null>((resolve) => setPicker({ title, exclude, first, resolve: (v) => { setPicker(null); resolve(v) } }))

  async function renameNode(row: TreeRow) {
    const title = (await composeAsk('改个名字', row.title))?.trim()
    if (title === undefined || title === row.title) return
    setTree((prev) => prev.map((r) => (r.note_id === row.note_id ? { ...r, title } : r)))
    try {
      const note = notes.find((n) => n.id === row.note_id)
      await api.saveNote(row.note_id, title, note?.content ?? '')
      await reload()
      if (current?.id === row.note_id) setTitle(title)
    } catch (e) {
      toast('改名失败：' + friendlyError(e), 'error')
      await reloadTree()
    }
  }

  /** 这个节点的子树里有谁（含自己）——移动/克隆时不能选这些，会成环。 */
  function subtreeIds(noteId: string): Set<string> {
    const out = new Set([noteId])
    const stack = [noteId]
    while (stack.length) {
      const p = stack.pop()!
      for (const r of tree) if (r.parent_note_id === p && !out.has(r.note_id)) { out.add(r.note_id); stack.push(r.note_id) }
    }
    return out
  }

  /** 挑一个目标节点：带搜索的选择器（对标 Trilium 的 move_to / clone_to）。 */
  function pickTarget(row: TreeRow, verb: string): Promise<string | null> {
    return askNode(`${verb}「${displayTitle(row)}」到哪儿？`, subtreeIds(row.note_id))
  }

  /** 树上的拖放。before/after 先挪到同一个父节点再整体重排；over 就是挪进去。 */
  async function dropNode(drag: TreeRow, target: TreeRow, where: DropWhere) {
    if (api.isVirtualId(drag.note_id) || api.isVirtualId(target.note_id)) return
    if (subtreeIds(drag.note_id).has(target.note_id)) { toast('不能放进自己的子树里'); return }
    try {
      if (where === 'over') {
        await api.moveBranch(drag.note_id, drag.parent_note_id, target.note_id)
      } else {
        if (drag.parent_note_id !== target.parent_note_id)
          await api.moveBranch(drag.note_id, drag.parent_note_id, target.parent_note_id)
        const sibs = tree.filter((r) => r.parent_note_id === target.parent_note_id && r.note_id !== drag.note_id)
          .sort((x, y) => x.position - y.position).map((r) => r.note_id)
        const k = sibs.indexOf(target.note_id) + (where === 'after' ? 1 : 0)
        sibs.splice(k, 0, drag.note_id)
        await api.reorderBranches(target.parent_note_id, sibs)
      }
      await reloadTree()
    } catch (e) { toast('移不过去：' + e, 'error'); await reloadTree() }
  }

  async function cloneNodeTo(row: TreeRow) {
    const to = await pickTarget(row, '克隆')
    if (!to) return
    try {
      await api.cloneNoteTo(row.note_id, to)
      await reloadTree()
      toast('已克隆——两处是同一篇，改一处处处都变')
    } catch (e) { toast('克隆失败：' + friendlyError(e), 'error') }
  }

  async function moveNodeTo(row: TreeRow) {
    const to = await pickTarget(row, '移动')
    if (!to) return
    try {
      await api.moveBranch(row.note_id, row.parent_note_id, to)
      await reloadTree()
    } catch (e) { toast('移不过去：' + e, 'error') }
  }

  async function detachNode(row: TreeRow) {
    try {
      await api.detachBranch(row.note_id, row.parent_note_id)
      await reloadTree()
    } catch (e) { toast('移除失败：' + friendlyError(e), 'error') }
  }

  async function copyNotePath(row: TreeRow) {
    let paths: string[][]
    // P3 遗留（？）：后端没起来时这里原来直接抛出去没人接——点了什么都没有
    try { paths = await api.notePaths(row.note_id) } catch (e) { toast('复制不了路径：' + friendlyError(e), 'error'); return }
    const byId = new Map(tree.map((r) => [r.note_id, r.title || '未命名']))
    // 克隆之后路径不止一条，全给出来——用户自己知道他要哪条
    const text = paths.map((p) => p.map((id) => byId.get(id) ?? id).join(' / ')).join('\n')
    try {
      await navigator.clipboard.writeText(text)
      toast('路径已复制')
    } catch { toast(text) }
  }

  /** 从树上直接跑 harness：先切到那篇，再跑。**不切就跑的话流式输出会写进
   *  一篇用户看不见的笔记里**，他只看到状态栏在转。 */
  async function openAndRun(note: Note, mode: 'write' | 'polish') {
    await switchTo(note)
    await runNoteHarness(mode)
  }

  /** 展开/收起一个节点。**状态写回服务端**，不是只改本地——刷新一次就全
   *  收起来的树，在几十个节点之后就没法用了。本地先改是为了点下去立刻有
   *  反馈，请求失败再回滚。 */
  async function toggleTreeNode(row: TreeRow) {
    const next = !row.is_expanded
    setTree((prev) => prev.map((r) => (r.id === row.id ? { ...r, is_expanded: next } : r)))
    try {
      await api.setBranchExpanded(row.note_id, row.parent_note_id, next)
    } catch {
      setTree((prev) => prev.map((r) => (r.id === row.id ? { ...r, is_expanded: !next } : r)))
    }
  }

  /** 无限续写现在对着**树上的一棵子树**跑（从前是「文件夹」——树上没有
   * 文件夹这种东西了，有子节点的笔记就是文件夹）。
   *
   * 入口仍然是侧栏一个随时可见的按钮，自己判断该对哪棵子树开：当前笔记
   * 的父节点优先。反馈原文是「我找不到那个按钮了」——那时它藏在文件夹
   * 标题栏的一个图标里，没有文件夹时页面上根本不出现。 */

  /** 跑 harness——挂在 App 级别，不依赖 WritingPlanPanel 是否挂载（见
   * HarnessState 上面的注释）。跟随开着的时候，每次开始写一个新分段就把
   * 主编辑器切到那篇笔记，正文流式追加进 content（跟 magic tap 增量到达
   * 时的处理方式完全一样），是直接回应"不能在实际的笔记里看到流输出吗"。 */
  async function runHarness(parent: TreeRow) {
    if (harness?.running && harness.folderId === parent.note_id) {
      harnessAbortRef.current?.abort()
      return
    }
    // 本地模型同时处理多个生成请求只会互相拖慢，不是真的并行——一次只
    // 允许一个 harness 在跑，跑别的文件夹前先停掉当前这个。
    if (harness?.running) {
      toast(`「${harness.folderName}」的无限续写正在跑，先停掉那边再开始新的`, 'error')
      return
    }
    const got = await api.getWritingPlan(parent.note_id)
    if (!got.plan) { toast('这个文件夹还没有写作计划，先在面板里生成一个'); return }
    setHarness({
      folderId: parent.note_id, folderName: parent.title, plan: got.plan, sections: got.sections,
      running: true, currentSectionTitle: '', currentNoteId: '', preview: '', waitingFirstToken: true, follow: true,
    })
    const ctrl = new AbortController()
    harnessAbortRef.current = ctrl
    try {
      await api.runWritingPlan(parent.note_id, {
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
        onNoteContent: (noteId, serverContent) => {
          // 轮末 / 段末用服务端正文对齐（修订是在服务端应用的，本地只攒了续写增量）
          if (currentRef.current?.id === noteId) { liveContentRef.current = serverContent; setContent(serverContent) }
        },
        onSectionDone: (d) => {
          setHarness((h) => (h ? {
            ...h, waitingFirstToken: true,
            sections: h.sections.map((s) => (s.id === d.section_id ? { ...s, status: 'done', summary: d.summary } : s)),
          } : h))
          if (d.blocked) toast(`这个分段卡住了，需要你看一眼：${d.blocked_reason || '原因未知'}`, 'error')
          void reload(); void reloadTree()
        },
        onPlanExtended: (newSections) => setHarness((h) => (h ? { ...h, sections: [...h.sections, ...newSections] } : h)),
        onPlanDone: (p) => {
          setHarness((h) => (h ? { ...h, plan: p } : h))
          toast(`「${parent.title}」的写作计划已完成`)
          notifyIfHidden('MEMOKET NOTE · 分段写作', `「${parent.title}」的写作计划已完成`)
        },
      }, ctrl.signal)
    } catch (e) {
      if ((e as Error).name !== 'AbortError') toast('写作运行失败：' + friendlyError(e), 'error')
    } finally {
      setHarness((h) => (h ? { ...h, running: false, waitingFirstToken: false } : h))
      harnessAbortRef.current = null
      void reload(); void reloadTree()
    }
  }



  /** Shared between the flat search-results list and the per-folder grouped
   * list -- same note-item markup either way, only what array it's mapped
   * over differs. */
  function renderNoteItem(n: Note) {
    return (
      <div
        key={n.id}
        className={'note-item ' + (current?.id === n.id ? 'active' : '')}
        {...clickable(() => void switchTo(n))}
      >
        <div className="t">{displayTitle(n)}</div>
        {n.content.trim() && (
          <div className="muted" style={{ fontSize: 'var(--t-xs)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {(() => {
              // 标题本身就命中的（三篇「创业一年回顾」搜「创业」），片段再给一遍 H1 是重复的，
              // 换成第一行正文——同名的几篇靠这一行分辨（跟 ⌘K 的 first_body 一个思路）
              const titleHit = noteQuery.trim() && displayTitle(n).toLowerCase().includes(noteQuery.trim().toLowerCase())
              const s = searchResults !== null && !titleHit ? matchSnippet(n.content, noteQuery, 40, 8) : null
              return s ? <>{s.before}<mark>{s.hit}</mark>{s.after}</> : previewLine(n.content, displayTitle(n))
            })()}
          </div>
        )}
        {/* flex 而不是几个 float: right 堆在一起——三个控件（文件夹选择/
           置顶/删除）在 220px 宽的侧栏里跟时间戳挤一行，float 布局在文件夹
           名字长一点或者时间戳格式变化时很容易挤出这一行、换行错位，
           不好预判。timestamp 用 min-width: 0 + ellipsis 当"该缩的先缩"
           那一个（跟更早修的 .col 溢出 bug 是同一个道理），三个控件固定
           大小不被挤压。 */}
        <div className="muted" style={{ fontSize: 'var(--t-xs)', display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {/* 在哪个文件夹下：搜索命中几十条时，这是区分同名笔记的唯一线索 */}
            {(() => { const row = tree.find((r) => r.note_id === n.id); const parent = row && row.parent_note_id !== api.ROOT_ID ? tree.find((r) => r.note_id === row.parent_note_id) : undefined; return parent ? displayTitle(parent) + ' · ' : '' })()}
            {/* 撞名且同一天的两行，这里要精确到分钟才分得开；没撞的照常
                「今天 / 昨天 / MM-DD」（`dupSuffixes` 给的是刚好够分开的粒度，
                带空格的就是分钟级——只有那种才值得顶掉 fmtWhen）。 */}
            {whenLabel(listDups.get(n.id), n.updated_at)}
          </span>
          {/* 「移动到文件夹」的下拉没了：树上靠拖拽和右键菜单移动，一个
              只能选一层的下拉表达不了任意深度的树。 */}
          <span
            className={'row-act' + (n.pinned ? ' pinned' : '')}
            title={n.pinned ? '取消置顶' : '置顶'}
            {...clickable((e) => { e.stopPropagation(); void togglePin(n) })}
          >
            <Icon n={(n.pinned ? 'bxs-pin' : 'bx-pin')} />
          </span>
          <span
            className="row-act danger"
            title="删除（5 秒内可在提示里撤销）"
            {...clickable((e) => { e.stopPropagation(); remove(n) })}
          >
            <Icon n="bx-x" />
          </span>
        </div>
      </div>
    )
  }

  /** 记一步历史。同一个 id 连续两次不记；从中间往回走后再打开新的，
   *  前面那截丢掉——浏览器就是这么做的。 */
  function pushHistory(id: string) {
    const h = hist.current
    if (h.navigating) { h.navigating = false; return }
    if (h.list[h.idx] === id) return
    h.list = [...h.list.slice(0, h.idx + 1), id].slice(-100)
    h.idx = h.list.length - 1
    setHistState({ back: h.idx > 0, fwd: false })
  }
  function goHistory(step: -1 | 1) {
    const h = hist.current
    const k = h.idx + step
    if (k < 0 || k >= h.list.length) return
    h.idx = k; h.navigating = true
    setHistState({ back: k > 0, fwd: k < h.list.length - 1 })
    const id = h.list[k]
    if (api.isVirtualId(id)) void openVirtual(id)
    else { const n = notes.find((x) => x.id === id); if (n) void switchTo(n); else h.navigating = false }
  }

  function open(n: Note) {
    pushHistory(n.id)
    setVirtualId(null)
    setCurrent(n)
    // 上次没存上的草稿（见 save() 的 catch）：比库里的新就放回来，并提示一句
    const d = resolveDraft(n, readDraft(n.id), !!new URLSearchParams(location.search).get('probe'))
    setTitle(d.title)
    setContent(d.content)
    // 护栏的锚点跟着换篇（P70 B）。**按篇分是承重的**：不换的话，在 A 上跑完一轮
    // 再打开一篇更短的 B，护栏会拿着 A 的字数去挡 B 的保存（量具 B5 就是这一格）。
    servedRef.current = { id: n.id, text: d.content, edits: 0 }
    if (d.restored) toast('上次没存上的内容已恢复到这篇里，会在下一次自动保存时存回去')
    if (d.clear) clearDraft(n.id)
    // 骨架跟着笔记读回来，**不是清空**。清空那版的后果是「一会儿就没了」：
    // 换一篇、刷新页面、甚至无限续写开着「跟随」自动切到下一段，骨架都没了，
    // 而 harness 下一轮还得重新花一次模型调用生成一份。
    setSpine(n.spine ?? '')
    setBeats(n.beats ?? [])
    setSkeletonNotes([])
    setIntent(resolveIntent(n.intent, d.title))
    setMarginCard(null)
    setTraceCard(null)
    // 已经有骨架的笔记，打开时不要 8 秒后又生成一遍——之前每开一篇就一次模型
    // 调用，模型连不上时每开一篇弹一个错（实拍）。以打开时的正文为基线，改够
    // 20 字才重算。
    lastSkeletonContent.current = n.spine ? n.content : ''
    setRevisions([])
    setTapMeta(null)
    setTapNotes([])
    if (loading !== 'note-harness') { setHarnessDone(false); harnessDoneRef.current = false; if (!pausedRef.current) setNoteHarnessStatus('') }
    setPausedRun(null)
    syncTab(n)
    // 找回跑到一半停下来等处置的那次运行。
    //
    // **SSE 流断了之后它就再也找不回来了**——关标签页、后端重启、网络抖一下，
    // 快照留在库里，而 run_id 只存在于那条已经断掉的流里。用户看到的是「我
    // 明明点了智能续写，现在什么都没有」。这个接口是它唯一的入口。
    pendingSpot.current = n.id
    void api.listPausedRuns()
      .then((runs) => {
        const mine = runs.find((r) => r.note_id === n.id)
        if (mine) {
          // 接口本来就返回 mode，原来这里写死成 'write'——一次「打磨」跑出来的
          // 暂停，恢复之后所有提示都说成「智能续写」。
          const mode = mine.mode === 'polish' ? 'polish' : 'write'
          setPausedRun({ id: mine.id, noteId: n.id, mode })
          // 带上日期：隔了几天再打开，得知道这份暂停是哪天的（7 天没处置的启动时会清掉）
          setNoteHarnessStatus(
            `${fmtDate(mine.created_at)} ${mode === 'polish' ? '打磨' : '智能续写'}写到第 ${mine.round} 轮停下来等你处置`)
        }
      })
      .catch(() => {})
  }

  // ---------------------------------------------------------------- 探针
  //
  // `?probe=xxx` 把界面驱动到某个状态，供截图核对。
  //
  // **为什么要这个**：右键菜单、弹层、分屏这些东西只有在交互之后才存在，
  // 而截图工具没法替我点——发合成点击要系统的「辅助访问」权限，那是得让
  // 仓库主人去系统设置里授权的东西，不该为了自测要求他改系统权限。
  //
  // 只认 URL 参数，不留任何常驻入口：正常使用时这段代码一次都不会执行。
  useEffect(() => {
    const probe = new URLSearchParams(location.search).get('probe')
    if (!probe) return
    const timer = setTimeout(() => runProbe(probe, { notes, tree, switchTo, openVirtual, openInSplit, newNote, removeWithSubtree, remove, syncTab, formatNote, setSelectionMenu, setPaneFocus, setContent, setTreeMenu, setTabs, setTabMenu, setShowShortcuts, setReviewEachRound, setQuick, setNoteQuery, setFocusMode, editorViewRef, actionsRef, harnessProbeDone, moveNodeTo, setLoading, setNoteHarnessStatus, setSlash, importMarkdown }), 800)
    return () => clearTimeout(timer)
    // notes 也要在依赖里：探针体里用到它，只依赖 tree 的话拿到的是笔记还没
    // 加载完时的空数组，判空之后静默跳过——实拍时「开三个标签」的探针
    // 一个都没开出来，查了两轮才发现是这个。探针体里的其它闭包故意不进依赖：
    // 每次它们变都重跑探针会重复开标签 / 重复建笔记。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tree, notes])

  useEffect(() => {
    void reload().then((list) => {
      if (!list.length) return
      // 回到上次看的那篇（标签页已经跨启动保住了，正文也该回到同一篇），
      // 没记录才退回最近编辑的。探针要的是确定的起点，一律最近编辑的。
      let last: string | null = null
      try { if (!new URLSearchParams(location.search).get('probe')) last = localStorage.getItem('memoket-note-active:' + api.getUser()) } catch { /* 无所谓 */ }
      open(list.find((n) => n.id === last) ?? list[0])
    })
    void reloadTree()
    void checkHealth()
    // 设置里换了供应商 / 服务恢复了，状态栏那行红字要跟着变：之前只在启动时查一次，
    // 改完设置还挂着「LLM 不可达」直到重启。改设置立刻查；有红字时每 30 秒再查。
    const onProvider = () => void checkHealth()
    window.addEventListener('provider-changed', onProvider)
    return () => window.removeEventListener('provider-changed', onProvider)
    // open 只在启动时用一次，进依赖会在每次切笔记时重跑这段启动逻辑
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reload, reloadTree])

  useEffect(() => {
    if (!healthMsg) return
    const t = setInterval(() => void checkHealth(), 30000)
    return () => clearInterval(t)
  }, [healthMsg])

  useEffect(() => {
    if (!noteQuery.trim()) { setSearchResults(null); return }
    // 侧栏搜索在本地过滤：全文列表启动时已经在内存里（notes），每敲一个字再去拉一遍带全文的列表
    // （413 篇 580KB）没有意义。规则跟服务端一样：标题或正文包含、不分大小写；顺序沿用 notes（置顶在前、新的在前）。
    const needle = noteQuery.trim().toLowerCase()
    setSearchResults(notes.filter((n) => (n.title ?? '').toLowerCase().includes(needle) || (n.content ?? '').toLowerCase().includes(needle)))
  }, [noteQuery, notes])

  // 摄入是后台任务。任务结束时刷一次树——不刷的话「已入库」的 ⇡ 要等下次
  // 打开应用才出现，用户会以为存入没成功、再存一遍。
  // 跑的过程要看得见：实拍点「存入知识库」后 4 秒界面上什么都没有（只有引用页里
  // 有一行），跑完也只有树上多个 ⇡。状态栏挂一个「存入知识库中… 已抽出 N 条」，结束
  // 给一条 toast（错误也说）。
  type JobInfo = { status: string; facts: number; detail: string; done: number; total: number; eta: number }
  const [jobInfo, setJobInfo] = useState<JobInfo | null>(null)
  useEffect(() => {
    setIngestActive(!!job)
    if (!job) { setJobInfo(null); return }
    const ctrl = new AbortController()
    let last: JobInfo = { status: 'queued', facts: 0, detail: '', done: 0, total: 0, eta: 0 }
    setJobInfo(last)
    api.watchJob(job, (j) => {
      last = { status: String(j.status ?? ''), facts: Number(j.facts ?? 0), detail: String(j.detail ?? ''),
               done: Number(j.chunks_done ?? 0), total: Number(j.chunks_total ?? 0), eta: Number(j.eta_s ?? 0) }
      setJobInfo(last)
    }, () => {
      void reloadTree(); void reload(); setIngestTick((t) => t + 1); setIngestActive(false); setJobInfo(null); setJob('')
      if (last.status === 'error') toast('存入知识库失败：' + (last.detail || '未知错误'), 'error')
      else if (last.status === 'cancelled') toast('已取消存入知识库')
      else if (last.facts > 0) toastAction(`已存入知识库：抽出 ${last.facts} 条记录`, '看看', () => window.dispatchEvent(new CustomEvent('open-virtual', { detail: 'kb:recent' })), 8000)
      else toast('已存入知识库，但这篇没抽出可记的事实')
      notifyIfHidden('MEMOKET NOTE · 知识库', last.status === 'error' ? '摄入失败' : `摄入完成，${last.facts} 条记录`)
    }, ctrl.signal)
    return () => ctrl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job])

  const visibleNotes = searchResults ?? notes

  /** 平铺的那两个列表（搜索结果 / 最近）里撞名的行，各自补一个刚好够分开的时间。
   *
   *  树上第 619 轮就做了这件事，**平铺列表漏了**——而平铺才是最容易撞的地方：
   *  实拍搜「硬件」11 条结果里，「公司汇报：」出现两次，两行都写着「Notes · 09-07」，
   *  完全分不出是哪一篇（真是两篇不同的笔记，12:50 和 12:58）。 */
  const listDups = useMemo(
    () => dupSuffixes(visibleNotes.map((n) => ({ key: n.id, title: displayTitle(n), at: n.updated_at }))),
    [visibleNotes])

  /** 今天的日记：后端按 日记/年/月/日 找或建，这里刷树再打开。
   *  给了 `day` 就是**那一天**的——屏幕活动那一页的「去这天的日记」走这条（P23 #6）。 */
  async function openToday(day = '') {
    await save()
    try {
      const n = await api.todayNote(day)
      await Promise.all([reload(), reloadTree()])
      await switchTo(n)
    } catch (e) { toast(`打不开${day ? ` ${day} ` : '今天'}的日记：` + friendlyError(e), 'error') }
  }

  async function newNote() {
    await save()
    // P3 实拍：后端没起来时点「新建」什么都不发生（promise 静默拒绝）。建不了就说一句。
    let n: Note
    try { n = await api.createNote('', '') } catch (e) { toast('新建笔记失败：' + friendlyError(e), 'error'); return }
    freshEmpty.current.add(n.id)
    // 树也要刷：不刷的话新笔记不在树上，用户以为「没存」（实拍反馈）
    await Promise.all([reload(), reloadTree()])
    open(n)
  }

  async function save() {
    if (!current) return
    if (title === current.title && content === current.content) return
    // probe 是给截图摆姿势的：往正文塞的假引用不能落库。只拦自动保存不够——
    // switchTo / openVirtual 离开笔记前都会走到这里（实拍：三篇笔记各多了几行
    // 「据 […] 所述」）。
    if (new URLSearchParams(location.search).get('probe')) return
    // **别把更短的正文盖回刚交稿的那一份**（P70 B）。
    //
    // 判据宁可窄，三条同时成立才算数：① 锚点是**这一篇**的；② 自那一份交下来之后
    // 编辑器**一次改动都没报过**（`edits === 0`）；③ 要存的这一份**比它短**。
    // 用户自己删字、悬停工具条上的「撤回」、「全部撤回」、`/` 块——全都会让 ② 不成立，
    // 一次都拦不到（量具 B1 / B2）；服务端自己交了更短的一份（清洗、去重）会把锚点
    // 一起换掉，也拦不到（B6）。剩下能中的只有一种：**用户没动，而它变短了**（B3）。
    //
    // 拦下之后不是「不存」——那样这次连标题都存不上；是**拿服务端交的那一份去存**，
    // 顺手把编辑器也拉回来：P68 实拍那一格里，用户眼前少掉的 296 个字就在这一份里。
    const served = servedRef.current
    let body = content
    if (isStaleShrink(served, current.id, content)) {
      void api.clientLog('warn',
        `挡下一次回退的保存：要存 ${content.length} 字，服务端刚交的是 ${served.text.length} 字，`
        + `而编辑器从那以后一次改动都没报过——用服务端那一份存`, '', 'save-guard')
      body = served.text
      if (content !== served.text) setContent(served.text)
    }
    try {
      const n = await api.saveNote(current.id, title, body)
      setCurrent(n)
      setSaveStatus({ at: Date.now() })
      clearDraft(current.id)
      // 列表接口带全文（terrence 23 篇 250KB、shot-perf 413 篇 580KB）：每次自动保存都重拉一遍整个库
      // 太浪费——保存只改这一篇，用返回的那篇就地替换；增删移动那些路径照旧 reload()
      setNotes((prev) => (prev.some((x) => x.id === n.id) ? prev.map((x) => (x.id === n.id ? n : x)) : [n, ...prev]))
      await reloadTree(false)
    } catch (e) {
      setSaveStatus({ at: Date.now(), error: String(e) })
      // **没存上的正文先落到本机**：后端崩了 / 网断了的那几秒里用户还在写，
      // 这时关掉应用就全没了。下次打开这篇如果库里的版本更旧，把草稿放回去。
      // 落草稿的也是**真要存的那一份**（`body`）：护栏改写过之后还写 `content`，
      // 等于把刚挡掉的那一份短的从草稿这条路又放回去（P70 B）。
      writeDraft(current.id, title, body)
      throw e
    }
  }

  /** 这一篇还挂着哪几层没处置 —— 写进库（P39）。
   *
   * 整批替换：编辑器是这件事的唯一真相，增量同步只会多出一种「两边不一致」。
   * 写之前先问一句「跟上次写下去的一模一样吗」，一样就一个字节都不发——
   * 位置跟着打字漂一下就发一次请求的话，这条路就成了第二个自动保存。 */
  const flushChangeLayers = useCallback((keepalive = false) => {
    if (layersTimer.current) { clearTimeout(layersTimer.current); layersTimer.current = null }
    const view = editorViewRef.current
    const id = currentRef.current?.id
    if (!view || !id || layersReady.current !== id) return
    // **放不回来的那几层原样带着走**（P41 #5 ②）：它们一处都没进编辑器，
    // `serializeLayers` 看不见它们——不补上的话这一次冲库就等于替用户按了「丢掉这一层」，
    // 而这一批的整个主题就是「不许静悄悄替他做决定」。`seq` 重新按数组下标排
    // （后端只拿它排序，P39「留给下一批」③ 已经记过这一格的脆）。
    const payload = [...serializeLayers(view.state), ...layerStuckRef.current.map((s) => s.saved)]
      .map((l, i) => (l.seq === i ? l : { ...l, seq: i }))
    if (layersSaved.current.noteId === id && sameLayers(layersSaved.current.payload, payload)) return
    layersSaved.current = { noteId: id, payload }
    void api.saveChangeLayers(id, payload, keepalive)
      .then((r) => {
        // **淘汰要吵闹**：少存了哪一层、为什么，当场说一句。悄悄少一层，
        // 下次打开就是「我留着的那层不见了」——跟这一批要修的毛病是同一个。
        const gone = [...r.evicted, ...r.rejected]
        if (gone.length) {
          toast(`${gone.length} 层改动没能留到下次打开：${gone[0].label || '这一层'}——${gone[0].why}`
            + (gone.length > 1 ? `（还有 ${gone.length - 1} 层同样没留下）` : ''), 'error')
        }
      })
      .catch(() => { layersSaved.current = { noteId: '', payload: [] } })   // 没存上就别记成存过了
  }, [])

  /** 编辑器报「层动了一下」：防抖之后落库。
   *
   * **所有改层的路都走这一条**（悬停工具条上的「接受 / 撤回」根本不经过 React），
   * 所以这里不去数是哪种处置——只要 `roundDiffField` 的值换了就算。 */
  const onLayersChanged = useCallback(() => {
    const st = editorViewRef.current?.state.field(roundDiffField, false)
    // 「已处置」那本账变了才重渲染面板：位置跟着打字漂不该每敲一个字重画一次右栏
    if (st && st.settled !== lastSettled.current) { lastSettled.current = st.settled; setLayersTick((n) => n + 1) }
    if (layersTimer.current) clearTimeout(layersTimer.current)
    layersTimer.current = setTimeout(() => { layersTimer.current = null; flushChangeLayers() }, CHANGE_LAYER_SAVE_MS)
  }, [flushChangeLayers])

  // 关窗口 / 关标签之前冲一次。`keepalive` 是承重的：不带的话页面一开始卸载，
  // 这个请求就被浏览器掐掉了——「关掉 app 前存一次」等于没存。
  useEffect(() => {
    const on = () => flushChangeLayers(true)
    window.addEventListener('beforeunload', on)
    window.addEventListener('pagehide', on)
    return () => { window.removeEventListener('beforeunload', on); window.removeEventListener('pagehide', on) }
  }, [flushChangeLayers])

  // 打开一篇：把库里挂着的改动层放回编辑器（P39 —— 这一批的正题）。
  useEffect(() => {
    const id = current?.id
    layersReady.current = ''                       // 还没放回来之前，任何一次防抖落库都不许动手
    layersSaved.current = { noteId: '', payload: [] }
    setLayerStuck([]); layerStuckRef.current = []  // 上一篇放不回来的那几层不许跟到这一篇
    lastSettled.current = undefined
    if (layersTimer.current) { clearTimeout(layersTimer.current); layersTimer.current = null }
    if (!id) return
    let alive = true
    void api.listChangeLayers(id)
      .then((saved) => new Promise<SavedLayer[]>((res) => setTimeout(() => res(saved), 320)))
      .then((saved) => {
        // 正文同步进编辑器是子组件的 effect 干的；等一小会儿再放回去，
        // 免得按上一篇的正文算坐标。等完还要再核一次开着的是不是同一篇。
        const view = editorViewRef.current
        if (!alive || !view || currentRef.current?.id !== id) return
        if (saved.length) {
          const r = restoreLayers(saved, view.state.doc.toString())
          view.dispatch({ effects: restoreLayersEffect.of({ layers: r.layers, hunks: r.hunks, settled: r.settled }) })
          setPendingDiff(pendingHunks(view))
          setLayersTick((n) => n + 1)
          if (r.conflicts.length) {
            // **不止一句 toast**（P41 #5 ②）：对不上的那几层留在右栏「改动」里，
            // 每一层给「按现在的正文重新算 / 丢掉这一层」两个出路。
            const byId = new Map(saved.map((l) => [l.id, l]))
            const stuck = r.stuck.filter((s) => byId.has(s.id)).map((s) => ({ ...s, saved: byId.get(s.id)! }))
            // ref 当场也写一份：下面那行基线要把它们算进去，而 setState 是异步的
            layerStuckRef.current = stuck
            setLayerStuck(stuck)
          }
          // **说什么、说不说都在 `reopenedLayersNotice` 那一处判**（P43 #1）：
          // 原来这儿数的是 `hunks ∪ settled`，把**一处活的都不剩**的层也数成
          // 「上次没处置完的 1 层」，而它指的那个「改动」页签当时根本不出现。
          const notice = reopenedLayersNotice(r)
          if (notice) toast(notice.text, notice.kind)
        }
        layersReady.current = id
        const view2 = editorViewRef.current
        if (view2) {
          layersSaved.current = {
            noteId: id,
            payload: [...serializeLayers(view2.state), ...layerStuckRef.current.map((s) => s.saved)]
              .map((l, i) => (l.seq === i ? l : { ...l, seq: i })),
          }
        }
        lastSettled.current = view2?.state.field(roundDiffField, false)?.settled
      })
      .catch(() => { layersReady.current = id })
    return () => { alive = false }
  }, [current?.id])

  // 打开一篇：**把库里那次跑的轮次骨架读回来**（P101 A —— 这一批的正题）。
  //
  // P99 在真壳上实拍：那一篇 **6 次跑 / 12 行轮次**好端端躺在 `harness_rounds` 里，
  // 而**关掉重开之后右栏是 0 张卡**——轮次卡只活在内存里，前端一行都没读。
  // 判下来的是**不新开表、不把卡整个落库**，补的是**读回来这条路**
  // （零迁移 / 零新表 / 零体积增长），而**缺的那几样明细在卡上照实标**
  // （`util/roundsRestore` 的抬头逐条写着）。
  //
  // ⚠️ **活的卡一张都不许被盖住**（`mergeRestored` 那一条）：这一趟跑过、
  //    或者跑着切走又切回的那一份带着明细（P101 B 那一刀之后更全），
  //    读回来的只是骨架——**骨架不许盖住全量**。
  useEffect(() => {
    const id = current?.id
    if (!id) return
    let alive = true
    void api.listNoteRounds(id)
      .then((p) => {
        // 等回来之后**再核一次开着的是不是同一篇**：这几百毫秒里用户可能已经切走了
        // （`listChangeLayers` 那条路同一条理由）。
        if (!alive || currentRef.current?.id !== id) return
        const restored = restoredRounds(p)
        if (!restored.length) return
        // **走 `writeRounds`**（不是自己 `setRoundsByNote`）：直接动那张表的地方
        // 该正好 1 处，多一处就是绕过了「写入必须点名写给哪一篇」——
        // `util/roundsWiring` 第 ⑤ 问钉的就是这个，闸在 `npm test` 里。
        writeRounds(id, (cur) => mergeRestored(cur, restored))
      })
      .catch(() => { /* 读不回来就是没有卡，跟改之前一模一样——不弹话打扰用户 */ })
    return () => { alive = false }
  }, [current?.id, writeRounds])

  /** 放不回来的那一层：**按现在的正文再算一次**（P41 #5 ②）。
   *
   *  正文在这之后可能又变了（用户照着 toast 把那段话改回去了、或者撤销了一步），
   *  所以这不是「再试一次同样的算式」——算的是**现在这一份正文**。
   *  连编辑器里已经挂着的那几层一起重放：`restoreLayers` 那条 effect 是**整份替换**的，
   *  只塞这一层会把别的层全抹掉。已经挂着的那几层 `content_tag` 就是当前正文，
   *  走的是「按坐标精确放回」，一个字都不会漂。 */
  const recomputeStuckLayer = useCallback((key: string) => {
    const view = editorViewRef.current
    const entry = layerStuckRef.current.find((s) => s.id === key)
    if (!view || !entry) return
    const doc = view.state.doc.toString()
    const all = [...serializeLayers(view.state), entry.saved]
    const r = restoreLayers(all, doc)
    view.dispatch({ effects: restoreLayersEffect.of({ layers: r.layers, hunks: r.hunks, settled: r.settled }) })
    setPendingDiff(pendingHunks(view))
    setLayersTick((n) => n + 1)
    const left = r.stuck.find((s) => s.id === key)
    if (left) {
      // **还是对不上就说还是对不上**，不要装作成了——那正是这一批在别处修的那种假话。
      const next = layerStuckRef.current.map((s) => (s.id === key ? { ...s, why: left.why } : s))
      layerStuckRef.current = next
      setLayerStuck(next)
      toast(`「${entry.label}」按现在的正文还是有 ${left.why.length} 处对不上：${left.why.slice(0, 2).join('；')}`, 'error')
    } else {
      const next = layerStuckRef.current.filter((s) => s.id !== key)
      layerStuckRef.current = next
      setLayerStuck(next)
      toast(`「${entry.label}」按现在的正文重新算好了，回到「改动」里了`)
    }
    flushChangeLayers()
  }, [flushChangeLayers])

  /** 放不回来的那一层：**丢掉**（P41 #5 ②）。用户按下去才丢——
   *  库里那一行跟着这一次冲库一起消失，不是悄悄没的。 */
  const dropStuckLayer = useCallback((key: string) => {
    const entry = layerStuckRef.current.find((s) => s.id === key)
    const next = layerStuckRef.current.filter((s) => s.id !== key)
    layerStuckRef.current = next
    setLayerStuck(next)
    setLayersTick((n) => n + 1)
    flushChangeLayers()
    if (entry) toast(`丢掉了「${entry.label}」这一层——正文一个字没动`)
  }, [flushChangeLayers])

  // Cmd/Ctrl+S saves explicitly instead of falling through to the browser's
  // save-page dialog; Cmd/Ctrl+N starts a new note instead of opening a new
  // browser window -- power users expect both, autosave already makes S a
  // no-op when nothing's dirty so this can't double-save anything.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey)) return
      const key = e.key.toLowerCase()
      if (key === 's') { e.preventDefault(); void save() }
      else if (key === 'd' && e.shiftKey) { e.preventDefault(); void openToday() }   // ⌘⇧D 今天的日记（Trilium 也是这个键）
      else if (key === 'n') { e.preventDefault(); void newNote() }
      else if (key === '.') { e.preventDefault(); setFocusMode((v) => !v) }
      // 编辑器里按 ⌘/：CM 的 keymap 已经发了 show-shortcuts（置 true）并 preventDefault，事件接着冒泡到这里
      // 再 toggle 一次就又关上了——实拍 `p10-keys-before`：正文里按 ⌘/ 什么都不出现（P10 C3-1）
      else if (key === '/') { if (e.defaultPrevented) return; e.preventDefault(); setShowShortcuts((v) => !v) }
      // 折叠左/右栏。Trilium 没给默认键，我们给 ⌘\ 和 ⌘⇧\
      else if (key === '\\' && e.shiftKey) { e.preventDefault(); setPanes((p) => (p.rightOn ? { ...p, rightOn: false } : makeRoomForRight(p, winW, split?.w ?? 0))) }
      else if (key === '\\') { e.preventDefault(); setPanes((p) => ({ ...p, leftOn: !p.leftOn })) }
      // ⌘/Ctrl+⇧+F 一键格式化。加 shift 是为了不跟浏览器/编辑器的「查找」撞
      else if (key === 'f' && e.shiftKey) { e.preventDefault(); formatNote() }
      // ⌘F：焦点不在编辑器里（比如刚点过树）时 CM 的 searchKeymap 收不到，这里兜一下
      else if (key === 'f') { const v = editorViewRef.current; if (v && !v.hasFocus && current) { e.preventDefault(); openSearchPanel(v); v.focus() } }
      // 标签：⌘T 新开、⌘W 关掉当前、⌘1..9 跳到第 n 个。跟浏览器一致，
      // 不需要学。⌘9 是**最后一个**（不是第九个）——同样是浏览器的约定。
      else if (key === 't' && e.shiftKey) { e.preventDefault(); reopenLastTab() }
      else if (key === 't') { e.preventDefault(); void newNote() }
      // 前进后退：macOS 上 Trilium 用 ⌘[ / ⌘]（Alt+←/→ 被树的升降级占了）
      else if (key === '[') { e.preventDefault(); goHistory(-1) }
      else if (key === ']') { e.preventDefault(); goHistory(1) }
      // ⌃Tab / ⌃⇧Tab 轮换标签（⌘Tab 是系统的）
      else if (key === 'tab' && e.ctrlKey && tabs.length > 1) {
        e.preventDefault()
        const i = tabs.findIndex((t) => t.id === activeTabId)
        activateTab(tabs[(i + (e.shiftKey ? -1 : 1) + tabs.length) % tabs.length])
      }
      else if (key === 'w') {
        e.preventDefault()
        if (activeTabId) closeTab(activeTabId)
      } else if (/^[1-9]$/.test(key) && !e.altKey) {                  // ⌥⌘1/2/3 是标题（编辑器里），不是切标签
        e.preventDefault()
        const i = key === '9' ? tabs.length - 1 : Number(key) - 1
        activateTab(tabs[i])
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, title, content, tabs, activeTabId, notes])

  /** 把一批建议**直接应用到正文**，然后按 diff 标出来交给「接受 / 撤回」。
   *
   * 原来这几个动作（润色/重写/扩展）产出的 Revision 是挂在正文上的一块彩色
   * 高亮，**点一下就直接接受，没有确认也没有撤回**——想拒绝只能不点它，而它
   * 会一直挂在那儿；改成什么样只有原生 title 提示里能看到；RevisionPanel 这个
   * 组件甚至根本没被渲染过。
   *
   * 现在跟 harness 自动改动走同一套：先应用，正文里绿/红标出来，鼠标移上去
   * 接受或撤回，也可以先改几个字再接受。两套交互合成一套，用户不用记两种。 */
  function applyAsDiff(list: Revision[], label = '修订'): number {
    if (!list.length) return 0
    // 从编辑器的实时文档读，不要读 liveContentRef —— 那个只在 harness 跑的
    // 过程中维护，平时停在上一轮结束时的内容，拿它当基准会把用户之后手打的
    // 东西全当成"这次建议改的"。也不要读 content state：这个函数是 await 之后
    // 才跑的，闭包里的 content 可能已经过时。
    const before = editorViewRef.current?.state.doc.toString() ?? content
    let next = before
    for (const r of list) next = applyRevision(next, r)
    if (next === before) return 0
    setContent(next)
    pushDiff(label, before, next)
    return list.length
  }

  /** 右键动作产出的那批建议**落地前过一道形状闸**（P35 · B）。
   *
   * 这一层原来没有：后端 `compose.rewrite` / `compose.expand` 只管「能不能抽出
   * `text` / `before` / `after` 这几个键」，抽得出就当正品——模型把整个响应又塞进
   * `text` 里答回来时，那串 JSON 原样换进正文，**一句话都不说**
   * （P35 实拍 117 → 163 字，`p35-B-rewrite-jsontext-light`）。
   *
   * 判据在 `editor/blockShape.revisionIsJson`，**只认整串 JSON 这一档**——
   * 块生成那三条（表格行 / 围栏 / 图片）套不到这儿来：右键换的是正文里的一句话，
   * 拿「该是表格」去卡它会把「帮我改成一张表」判死。
   *
   * 三种落法，各说各的话：全被拦下 → 只说被拦；拦了一部分 → 好的照落、坏的说清；
   * 一条都没有 → 还是原来那句（`emptyNote`）。
   *
   * **`unparsed` 那一档不许说 `emptyNote`**（P37 #4 / P35 #5）：「模型认为不需要补充
   * 上下文。」是一句**模型从没说过的话**，而后端现在分得清「模型按格式答了、没话说」
   * 和「模型答的抽不出建议」。抽不出的时候就说抽不出——替模型表态比不说更糟。 */
  function landRevisions(list: Revision[], note: string | undefined,
                         label: string, emptyNote: string, unparsed = false): void {
    if (list.length === 0) {
      toast(note || (unparsed ? unparsedEditNote(label) : emptyNote),
            (note || unparsed) ? 'error' : undefined)
      return
    }
    const { keep, bad } = splitBadRevisions(list)
    if (bad.length) toast(badRevisionNote(label, bad.length), 'error')
    if (keep.length === 0) return
    if (!applyAsDiff(keep, label)) toast('建议对不上正文（锚点找不到），没有改动。')
  }

  async function handleSelectionAction(action: SelectionAction) {
    if (!selectionMenu) return
    const selection = selectionMenu.text
    if (action === 'custom') {
      // 跟 `/` 的「用 AI 写」共用同一个输入框和同一套 harness，差的只是作用域：
      // 那个是「在光标这里插一块」，这个是「把选中的这段换成别的」。
      // **不走 /api/rewrite**——那条路只认 rewrite/polish 两种固定意图。
      const view = editorViewRef.current
      const sel = view?.state.selection.main
      const at = { x: selectionMenu.x, y: selectionMenu.y }
      setSelectionMenu(null)
      if (!view || !sel || sel.empty) { toast('没有选中任何文字——先选一段，再右键「自定义提示」'); return }
      setSlash({
        item: { group: 'AI', key: 'custom', label: '自定义提示', icon: 'bx-message-dots',
                hint: '对选中的这段做点什么', needsPrompt: true,
                placeholder: '例如：改写成给投资人看的口吻 / 拆成三条要点' },
        from: sel.from, to: sel.to, ...at,
      })
      return
    }
    if (!llmGate()) { setSelectionMenu(null); return }
    // Keep the menu open (showing a spinner via selectionBusy) instead of
    // closing it immediately -- otherwise a slow LLM call leaves no
    // indication anything is happening at the spot the user right-clicked.
    setSelectionBusy(action)
    // 「停止」（P3）：模型卡住时这个转圈原来要转满后端 300 秒的超时，Esc 也关不掉
    const ctrl = new AbortController()
    selectionAbortRef.current = ctrl
    const signal = ctrl.signal
    try {
      if (action === 'verify') {
        const r = await api.verifySelection(content, selection, signal, intentText(intent), current?.id ?? '')
        // **把「说的是哪一段」一起存下来**（P41 #3 / P40 问题 #5）：这块卡挂在右栏顶上，
        // 不在页签体系里——换页签、光标移到别的段它都还在，读起来像在说当前这一段。
        setVerifyResult({ ...r, passage: selection })
      } else if (action === 'trace') {
        // 来龙去脉：这段涉及的事情按时间怎么演进的。**用户不写问题**——
        // 问题由后端拼（判据 1）。结果落在右栏的「来龙去脉」标签里，
        // 不是弹层：判据 2，看一条旧记录不该离开这一页。
        await traceFull(selection, signal)
      } else if (action === 'expand') {
        const r = await api.expandSelection(content, selection, signal, intentText(intent), current?.id ?? '')
        landRevisions(r.revisions, r.note, '扩展上下文', '模型认为不需要补充上下文。', r.unparsed)
      } else if (action === 'rewrite' || action === 'polish') {
        const r = await api.rewriteSelection(content, selection, action, spine, beats, signal, intentText(intent))
        landRevisions(r.revisions, r.note, action === 'polish' ? '润色' : '重写', '模型没有给出修改建议。', r.unparsed)
      } else {
        /* **走不到这里，但要让编译器来保证走不到。**
           原来这一支写的是 `action as 'rewrite' | 'polish'`——一个不查的强转，
           注释里还记着它出过事：custom 的分支丢了、断言还在，编译器一声不吭，
           线上直接 422（intent 只认 rewrite/polish）。
           **注释拦不住下一次。** 改成穷尽检查：`SelectionAction` 加了新成员而
           上面没接，`never` 这一行当场编译不过——不用等到线上（第 709 轮）。 */
        const missed: never = action
        toast(`「${String(missed)}」这个动作还没接上`, 'error')
      }
    } catch (e) {
      if ((e as Error).name === 'AbortError') toast('已停止')
      else if (isBackendDown(e)) toast(`操作失败：${friendlyError(e)}`, 'error')
      else if (isLlmUnreachable(e)) toastAction(`操作失败：${friendlyError(e)}`, '打开设置', () => void openVirtual('app:settings', '设置'), 8000)
      else toast(`操作失败：${friendlyError(e)}`, 'error')
    } finally {
      selectionAbortRef.current = null
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
  /** 当前这篇看到哪儿了。harness 自己切笔记时也记：那时候的光标是它写到的位置，
   *  下次回来正好落在上次写到的地方。 */
  function rememberSpot() {
    const v = editorViewRef.current
    const id = currentRef.current?.id
    if (!v || !id) return
    const scroller = document.querySelector('.note-scroll') as HTMLElement | null
    putSpot(spots.current, id, { head: v.state.selection.main.head, top: scroller?.scrollTop ?? 0 })
    saveSpots(api.getUser(), spots.current)
  }

  /** 等这一篇的正文真的进了编辑器，再把光标和滚动放回去。
   *  `open()` 里直接 rAF 太早：那时候 setContent 还没经过 React 渲染、CM 的 doc 还是上一篇的，
   *  dispatch 的 selection 会被随后到达的新内容顶掉（实测光标回到 0）。 */
  const pendingSpot = useRef<string | null>(null)
  useEffect(() => {
    const id = pendingSpot.current
    const v = editorViewRef.current
    if (!id || current?.id !== id || !v || v.state.doc.length !== content.length) return
    pendingSpot.current = null
    const spot = spots.current.get(id)
    if (!spot) return
    v.dispatch({ selection: { anchor: Math.min(spot.head, v.state.doc.length) } })
    const scroller = document.querySelector('.note-scroll') as HTMLElement | null
    if (scroller && spot.top) requestAnimationFrame(() => { scroller.scrollTop = spot.top })
  }, [current?.id, content])

  async function switchTo(n: Note, viaHarness = false) {
    if (current?.id === n.id) return
    await save()
    flushChangeLayers()          // 离开这篇之前把挂着的改动层写下去（P39 ③）
    // 要开的这篇正在分屏里被改：先把分屏没存的冲进库，再拿最新的正文来开。
    // 不然主栏拿着旧正文开出来，1.5 秒后自动保存把分屏那几笔盖掉。
    if (split?.id === n.id && splitFlush.current) {
      await splitFlush.current()
      const fresh = await api.getNote(n.id).catch(() => null)
      if (fresh) n = fresh
    }
    const leaving = current
    rememberSpot()
    // 自动同步：改过还没同步的那篇，切走时马上同步（不等 2 分钟防抖）
    if (leaving && autoSync && dirtySinceIngest.current === leaving.id && !job) {
      dirtySinceIngest.current = ''
      api.syncNoteToKb(leaving.id).then((r) => setJob(r.job_id)).catch(() => {})
    }
    open(n)
    void dropIfStillEmpty(leaving)
    // 手动点了别的笔记 = 明确表示现在想看别的东西，无限续写继续在后台跑，
    // 但不再把编辑器拽回正在写的那篇——harness 自己触发的切换不算"手动"，
    // 不应该关掉跟随（否则每次它自己切笔记都会把 follow 关掉，只能跟一次）。
    if (!viaHarness && harness?.running) setHarness((h) => (h ? { ...h, follow: false } : h))
  }

  // 自动保存：停止输入 1.5 秒后落库
  useEffect(() => {
    if (!current) return
    // probe 是给截图摆姿势的，往正文塞的假引用不能落库——落一次，每次截图
    // 都会在真实笔记里多一行「据 [...] 所述」。
    if (new URLSearchParams(location.search).get('probe')) return
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
      void runSkeleton(true)
    }, SKELETON_IDLE_MS)
    return () => clearTimeout(t)
    // `loading` isn't read in the body, but it's a dep on purpose: if the
    // timer fires while something else is running, it backs off and does
    // nothing -- without `loading` here, nothing would ever re-run this
    // effect to give it another chance once that something else finishes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, current, loading])

  // 「智能编辑」已移除。它原来会在用户停下打字时**自动**跑一次修订建议——
  // 后来给它加了打分诊断，一次自动触发就是两次模型调用，等于在打字间隙
  // 悄悄烧钱。而它的用途已被「✨ 打磨」完全覆盖：同一套修订循环，但有明确
  // 的终止判定（改到已写内容自身达标或改不动为止），而且由用户主动触发。
  // 「人在环内逐条挑」这个入口现在有了，但走的不是 /api/edit——是
  // 「逐轮我来定」：harness 每轮写完停下来，你在编辑器里逐条接受/撤回，
  // 点「接着写」把处置后的正文送回去接着跑。所以那条一次性调用不再需要
  // 前端封装；后端 /api/edit 还在（诊断和针对最弱项的改造也在），要接回来
  // 是三行的事。


  /** Optimistic delete with an undo window instead of a confirm() dialog --
   * deletion used to be instant and permanent past a dialog people click
   * through by habit. The note is only actually deleted from the backend
   * after `ms` unless the toast's "撤销" is clicked first. */
  function remove(n: Note, ids: Set<string> = new Set([n.id])) {
    const wasCurrent = current?.id === n.id
    setNotes((prev) => prev.filter((x) => !ids.has(x.id)))
    setSearchResults((prev) => (prev ? prev.filter((x) => !ids.has(x.id)) : prev))
    // 树上先摘掉（乐观），撤销时 reloadTree 会长回来；不摘的话要等真删之后
    // 再刷树，中间 5 秒树上还站着一篇已经「删了」的笔记。
    setTree((prev) => prev.filter((r) => !ids.has(r.note_id)))
    // 它（和子树）的标签、分屏一起收掉，别留一个点了没反应的标签
    closeTabsWhere((t) => ids.has(t.noteId))
    setSplit((sp) => (sp && ids.has(sp.id) ? null : sp))
    if (wasCurrent) {
      const remaining = notes.filter((x) => !ids.has(x.id))
      if (remaining.length) open(remaining[0])
      else { setCurrent(null); setTitle(''); setContent('') }
    }
    let undone = false
    const timer = setTimeout(() => {
      // P3 遗留（？）：5 秒后真删失败原来只 reload()，笔记长回来没有一句解释
      if (!undone) api.deleteNote(n.id).then(() => { void reloadTree(); void reload() }).catch((e) => { toast(`没删成「${displayTitle(n)}」——它还在库里，列表刷新后会长回来：` + friendlyError(e), 'error'); void reloadTree(); void reload() })
    }, 5000)
    toastAction(`已删除「${displayTitle(n)}」${ids.size > 1 ? `和它下面的 ${ids.size - 1} 篇` : ''}（30 天内可在「最近删除」找回）`, '撤销', () => {
      undone = true
      clearTimeout(timer)
      void reload(); void reloadTree()
      if (wasCurrent) open(n)
    })
  }

  async function togglePin(n: Note) {
    const updated = await api.togglePin(n.id)
    if (current?.id === n.id) setCurrent(updated)
    await reload()
  }

  // ---------------------------------------------------------------- AI 动作

  /** 把骨架存到这篇笔记上。存不上不打断用户——骨架在内存里还是好的，
   * 只是下次打开要重新生成，不值得为它弹个错误。 */
  async function persistSkeleton(s: string, b: string[], noteId?: string) {
    const id = noteId ?? current?.id
    if (!id) return
    try {
      await api.saveSkeleton(id, s, b)
      setNotes((prev) => prev.map((x) => (x.id === id ? { ...x, spine: s, beats: b } : x)))
    } catch { /* 存不上就算了，内存里还在 */ }
  }

  async function runSkeleton(background = false) {
    // **`background === true` 才是后台**：原来 `onClick={onRun}` 把鼠标事件当成了 background，
    // 用户亲手点「生成骨架」失败时一个字都不说（P3 实拍：空正文 / 模型 500 / 后端没起来三种都静默）。
    const quiet = background === true
    const why = notePrecondition('skeleton', content, title)
    if (why) { if (!quiet) toast(why); return }             // 不发请求：后端同一句话
    if (!quiet && !llmGate()) return
    setLoading('skeleton')
    const ctrl = new AbortController()
    skeletonAbortRef.current = ctrl
    try {
      const r = await api.genSkeleton(title, content, intentText(intent), ctrl.signal)
      setSpine(r.spine)
      setBeats(r.beats)
      setSkeletonNotes(r.notes ?? [])
      await persistSkeleton(r.spine, r.beats)
    } catch (e) {
      // 后台自动跑的失败不打扰人（用户没点任何东西）；点「生成骨架」失败才提示
      if ((e as Error).name === 'AbortError') { if (!quiet) toast('已停止生成骨架'); return }
      if (quiet) void api.clientLog('warn', '后台骨架生成失败：' + friendlyError(e), '', 'skeleton')
      else if (isLlmUnreachable(e)) toastAction('生成骨架失败：' + friendlyError(e), '打开设置', () => void openVirtual('app:settings', '设置'), 8000)
      else toast('生成骨架失败：' + friendlyError(e), 'error')
    } finally {
      skeletonAbortRef.current = null
      setLoading('')
    }
  }
  /** 「停止」生成骨架：撤掉请求、按钮复位。后端那次调用照跑到超时，但界面不再被它拖着。 */
  function stopSkeleton() { skeletonAbortRef.current?.abort() }

  /** magic tap：流式续写，边到边写进编辑器。再点一次可中断。 */
  async function runMagicTap() {
    if (loading === 'tap') {
      // 第二下 = 停止（P3 遗留：停下来原来一个字不说，用户分不清是停了还是卡了）
      abortRef.current?.abort()
      toast('已停止续写，写到哪算哪——不要的话用正文上的「撤回」')
      return
    }
    // 一个字都没有、标题也空：模型只能编。让用户先给个方向
    { const why = notePrecondition('tap', content, title); if (why) { toast(why); return } }   // 后端同一句话
    if (!llmGate()) return
    setLoading('tap')
    setTapMeta(null)
    setTapNotes([])
    const ctrl = new AbortController()
    abortRef.current = ctrl
    // **从光标处续写**（Notion / Craft 的「继续写」都在光标处）。光标在文末或
    // 根本没进过编辑器就追加；在中间就把光标后面的内容当「下文」送给模型，
    // 写出来的段插在光标处。光标夹在一段中间时先退到这一段的末尾——在句子
    // 里硬插一段不是任何人想要的。
    const view = editorViewRef.current
    const docLen = view?.state.doc.length ?? content.length
    let at = view?.hasFocus || (view && view.state.selection.main.head > 0) ? view!.state.selection.main.head : docLen
    if (at > 0 && at < docLen) {
      const text = view!.state.doc.toString()
      const nextBreak = text.indexOf('\n\n', at)
      at = nextBreak < 0 ? docLen : nextBreak
    }
    const middle = at > 0 && at < docLen
    const full = view ? view.state.doc.toString() : content
    const before = middle ? full.slice(0, at) : full
    const following = middle ? full.slice(at) : ''
    // **不用 setContent 的 updater 算位置**：流式每片一次 updater，闭包里的
    // 游标跟 state 的先后顺序对不上就会漂（实拍：插进了下一个标题的井号中间）。
    // 头尾定死、中间只增不改，每片直接算出整篇。
    const head = middle ? before.replace(/\n*$/, '\n\n') : (before && !/\n\n$/.test(before) ? before.replace(/\n?$/, '\n\n') : before)
    const tail = middle ? following.replace(/^\n*/, '\n\n') : ''
    let inserted = ''
    try {
      const { truncated, fakeCitations } = await api.magicTap(
        before,
        spine,
        beats,
        setTapMeta,
        (piece) => {
          inserted += piece
          setContent(head + inserted + tail)
          // 跟着写到哪滚到哪（r3 实拍：追加在文末，跑完了屏幕上什么都没变）。
          requestAnimationFrame(() => {
            const v = editorViewRef.current
            if (v) v.dispatch({ effects: EditorView.scrollIntoView(Math.min(head.length + inserted.length, v.state.doc.length)) })
          })
        },
        ctrl.signal,
        // 写完之后的确定性检查：检索到了材料却一条没用上，说明这段写的是
        // 通用内容。magic tap 刻意不套完整闭环（它的定位是点一下几秒出一段），
        // 所以这里不打断也不重写，只提示一句让用户自己决定要不要重来。
        (g) => { if (g.hint) toast(g.hint, 'error'); setTapNotes(g.notes ?? []) },
        following,
        title,
        intentText(intent),
        current?.id ?? '',              // 托盘里的材料先摆（P14）
      )
      // 流完了再统一修一次「**标题：**」这类粗体（后端落盘路径有同样一步，续写是纯客户端拼的）
      let fixed = fixBoldPunct(inserted)
      // 编造的引用（查不到的、或 [terrence-23F3-4F3] 这种格式就不对的）只从刚写的这段里摘——
      // 跟单篇 harness 的 grounding 判据同一个口径（第 139 轮实拍）
      if (fakeCitations.length) {
        for (const fid of fakeCitations) fixed = fixed.replace(new RegExp('\\s*\\[' + fid.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\]', 'g'), '')
        toast(`摘掉了 ${fakeCitations.length} 个知识库里查不到的引用`)
      }
      if (fixed !== inserted) { inserted = fixed; setContent(head + inserted + tail) }
      // ⌘Z 一次撤掉整段：编辑器只读（`loading === 'tap'`）期间流进去的每一片都并进同一条撤销事件
      // （`editor/undoUnit.aiSyncSpec`，跟智能续写同一套；P13 #5）——head 补的空行、上面修粗体标点那一笔都在里面。
      /* **接受 / 撤回。** 续写原来是全应用**唯一**一条不进修订层的插入路径——
         格式化、智能排版、语音输入、图片转表格、插入音频、`/` 菜单的块、
         智能续写全都调了 `pushDiff`，**最常用的这一个反而没有**
         （用户第 739 轮：「续写有截断，且没有 accept 和撤回」）。
         没有它，写出来的东西只能靠 ⌘Z 一把撸掉，逐处挑不了；
         写坏了、撞上限截断了，也没有一键还原的去处。 */
      if (inserted.trim()) pushDiff('续写', full, head + inserted + tail)
      // 撞 token 上限停在句中（实拍「…写成事项已经完成」没句号）：已写的留着，说一声。
      // **现在这句话有了去处**：撤回就在正文里，不用再靠用户自己 ⌘Z。
      if (truncated) toast('这段撞到长度上限，补了一次尾还没收住——不满意就用正文上的「撤回」，或把光标放在末尾再点一次', 'error')
    } catch (e) {
      if ((e as Error).name !== 'AbortError') { if (isLlmUnreachable(e)) toastAction('续写失败：' + friendlyError(e), '打开设置', () => void openVirtual('app:settings', '设置'), 8000); else toast('续写失败：' + friendlyError(e), 'error') }
    } finally {
      setLoading('')
      abortRef.current = null
    }
  }

  /** 这篇 → 一份幻灯片笔记（痛点 6）。
   *
   *  **不套多轮闭环**：幻灯片是一次成型的重构，多轮只会把页越改越碎。跑完直接
   *  把人送到那篇子笔记上——产物是一篇笔记，那就该像打开一篇笔记一样看见它。
   *  判据不合格不拦着落库，用一条提示说出来，要不要重做由用户定。 */
  async function runSlides(style: 'points' | 'talk') {
    if (!current) return
    { const why = notePrecondition('slides', content); if (why) { toast(why); return } }
    if (!llmGate()) return
    setLoading('slides')
    slidesText.current = ''; setSlidePhase('')
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      await save()
      const r = await api.makeSlides(current.id, content, current.title, style,
        /* 流式回来的是正文片段，不是阶段名——**报页数比报字数有意义**：
           用户要的是「做到第几页了」，`---` 的个数就是页数。
           **在累计文本上数，不在每个片段上数**：片段边界随时可能把 `\n---`
           切成两半，逐片段数会漏（第 737 轮，我上一轮刚写的脆弱处）。 */
        (delta) => {
          slidesText.current += delta
          const pages = (slidesText.current.match(/\n---/g) ?? []).length
          setSlidePhase(`做幻灯片…第 ${pages + 1} 页`)
        },
        ctrl.signal)
      window.dispatchEvent(new CustomEvent('notes-changed'))
      await reload(); await reloadTree()
      if (r.note_id) {
        const n = await api.getNote(r.note_id)
        await switchTo(n)
      }
      const bad = r.notes.length
      toast(bad ? `${r.pages} 页 · ${Math.round(r.cite_coverage * 100)}% 的页带着引用 · ${bad} 条可以再改：${r.notes[0]}`
                : `${r.pages} 页 · ${Math.round(r.cite_coverage * 100)}% 的页带着引用`,
            bad ? 'error' : undefined)
    } catch (e) {
      if ((e as Error).name === 'AbortError') toast('已停止做幻灯片')
      else toast('做幻灯片失败：' + friendlyError(e), 'error')
    } finally { setLoading(''); setSlidePhase(''); abortRef.current = null }
  }

  /** 幻灯片 → PDF。HTML 在这边拼（`util/slideHtml`），打印交给主进程——
   *  渲染器这边 `window.print()` 打的是**当前这个窗口**，会把编辑器的 DOM
   *  卷进去；主进程开一个离屏窗口，跟正在编辑的东西完全无关。 */
  async function exportSlidesPdf() {
    if (!current) return
    try {
      // ```mermaid 先渲成 SVG 内联进去：打印那一步在离屏窗口里跑、而且关掉了 JS。
      // 渲不出来的就印源码，不拦着导出——一张图渲不出来不该让整份 PDF 导不成。
      const svgs = new Map<string, string>()
      for (const b of parseMini(content)) {
        if (b.kind !== 'pre' || b.lang !== 'mermaid') continue
        const svg = await mermaidSvg(b.text.trim())
        if (svg) svgs.set(b.text.trim(), svg)
      }
      const where = await window.memoketDesktop?.slidesToPdf?.(
        slidesToHtml(current.title, content, svgs), displayTitle(current))
      if (where) toast('存好了：' + where)
    } catch (e) { toast('导出 PDF 失败：' + friendlyError(e), 'error') }
  }

  /** 智能续写：单篇笔记内的 harness——自动修订（不等人工点接受）+ 自动
   * 续写交替，直到内容相对 spine/beats 已经完整才停。修订直接用跟
   * RevisionPanel 手动接受同一套 applyRevision() 锚点语义应用到本地
   * content，续写增量直接追加，效果上编辑器里能实时看到"自己在改自己"。
   * 用 currentRef 而不是闭包里的 `current` 判断该不该应用——万一运行中
   * 途用户切到了别的笔记，不能把这篇笔记的修订/续写误应用到当前正显示
   * 的另一篇笔记上。 */
  /** 往某一轮的记录里打补丁。事件是分散到达的（round-start / tool-calls /
   * evaluate / policy 各一条），先到的先建这一轮的空壳，后到的往上补。 */
  function patchRound(noteId: string, round: number, patch: Partial<AgentRound>) {
    writeRounds(noteId, (rs) => {
      const i = rs.findIndex((r) => r.round === round)
      if (i < 0) {
        return [...rs, {
          round, cleanupOnly: false, revisions: 0, toolCalls: [], toolTruncated: false,
          scores: {}, status: '', weakest: null, policyReasons: [], policy: null, errors: [], dropped: [],
          ...patch,
        }]
      }
      const next = [...rs]
      next[i] = { ...next[i], ...patch }
      return next
    })
  }

  /** 这一次运行的事件处理。**开跑和「接着写」共用同一份**——两条路径各写
   * 一份的话，恢复之后的运行就会少掉几个 handler，而那是最难发现的一类
   * 差异：界面看起来在跑，只是某个面板不再更新了。 */
  function noteHarnessHandlers(noteId: string, mode: 'write' | 'polish'): api.NoteHarnessHandlers {
    /** 用户已经切走了，这句话**必须点名说的是哪一篇**（P103 B）。
     *
     * 跟 `onDone` 那一支逐字同一个做法（它是这条做法的出处）：不点名的话，
     * 屏幕上开着 B，弹出来一句「这次跑到了上限，就停在这儿了」——用户会读成 B 的事，
     * 而 B 上可能正跑着另一次。**一句没有主语的通知，在多标签页里就是一句错话。**
     * 切走那一支**不用 `error` 那个红档**：那是「你现在这一篇出事了」的语气，
     * 而这句说的是另一篇（`onDone` 切走那一支也是平的）。 */
    const awayToast = (detail: string) =>
      toast(`「${notes.find((x) => x.id === noteId)?.title || '另一篇笔记'}」：${detail}`)
    const h: api.NoteHarnessHandlers = {
      onSkeleton: (s, b, notes) => {
        // **落库这一句排在自己那句 guard 前面**（P103 A，收 P101 B 留的第一处）：
        // `persistSkeleton(s, b, noteId)` 是**按 noteId 落库**的（`api.saveSkeleton(id, …)`
        // 再按 id 改 `notes` 里那一行），碰不到「现在显示的那篇」。
        // 拦住它的后果实拍过（`p103` 走查 `skel103.mjs`，真壳）：
        // **不切走 → 库里 `spine` 第 8 秒变非 0；点完 262 毫秒就切走 → 盯了 60 秒一直是 0，
        // 跑完是 0，关掉重开还是 0。** 而全仓只有这一条路能把跑里现生成的骨架写进笔记
        // （`store.set_skeleton` 唯一调用点在 `PUT /api/notes/<id>/skeleton`），
        // ⇒ 拦住它 = **这一次生成的骨架永久没了**，下次打开还得再打一次模型。
        void persistSkeleton(s, b, noteId)
        // ── 下面全是**现在显示的这篇**的（右栏那三格 + 状态行）──
        // 这半边**照旧拦**：切走之后把 A 的骨架摆进 B 的右栏，正是那一刀本来要拦的东西。
        if (currentRef.current?.id !== noteId) return
        setSpine(s); setBeats(b); setSkeletonNotes(notes ?? [])
        setNoteHarnessStatus('已自动生成骨架，开始第一轮')
      },
      onRoundStart: (d) => {
        // **记账这一句排在 guard 前面**（P101 B）：`patchRound` 按 noteId 写，
        // 切走了照样该建这一轮的卡——拦住它就是 P99 实拍那个 2 → 1 的上游。
        // skipped_continue：上一轮评分说重复是当前最弱的一项，这一轮
        // 后端直接跳过续写、只再跑一次聚焦修订，不会有 delta 事件
        // 跟着到达（见 TRACELOG [25]）——状态文案要如实说"在清理重复"，
        // 不能说"续写中"，不然用户会以为卡住了；也不能预留续写用的
        // 空行，因为这一轮根本不会有内容来填上这个空行。
        patchRound(noteId, d.round, {
          cleanupOnly: !!d.skipped_continue,
          revisions: d.revisions_applied,
          // 「这一轮为什么这么跑」（后端计划 12.1）：上一轮诊断出了什么、
          // 它进没进这一轮的检索计划、这个模式一共几条代码判据、
          // 有几发检索被深度门丢掉。
          steer: d.steer ?? '',
          steerDim: d.steer_dim ?? '',
          steerMaterial: !!d.steer_material,
          // **`undefined` 和 `false` 不是一回事**，所以不许 `?? false`：
          // 前者是「这一轮压根没有检索规划这一步」。
          steerInPlan: d.steer_in_plan,
          checksTotal: d.checks_total,
          depthDropped: d.depth_dropped ?? 0,
          depthDroppedAll: !!d.depth_dropped_all,
          // P8 问题 5：进 prompt 前被相关性筛剔掉的材料（从上千条的主题里抽样、跟这篇零重合）
          factsIrrelevant: d.facts_irrelevant ?? 0,
          irrelevantDropped: !!d.irrelevant_dropped,
          irrelevantSample: d.irrelevant_sample ?? [],
          // 引用覆盖（P30 #1，累计到这一轮）。**不许 `?? 0`**：`undefined`
          // 是「后端这一版还没有这三个键」，`0` 是「算过了、一句可引的都没有」，
          // 面板上是两句完全不同的话（见 `citeCoverLine`）。
          citeLocated: d.cite_located,
          citeMarked: d.cite_marked,
          citeMatched: d.cite_matched,
    })
        // ── 记账到此为止，下面全是**动当前这篇**的（P101 B 那一刀的分界线）──
        if (currentRef.current?.id !== noteId) return
        // 新的一轮 = 新的一条撤销事件（P11 #2）：这一轮落地的修订 + 续写全并进它，⌘Z 一次撤一轮。
        // **在预留空行之前加**——那个空行也是这一轮插的，⌘Z 之后不该剩下它。
        setUndoGroup((g) => g + 1)
        if (d.skipped_continue) {
          setNoteHarnessStatus(`第 ${d.round} 轮：修订 ${d.revisions_applied} 处，正在清理重复内容…`)
          return
    }
        // 知识库是空的（新用户最常见的情形）：**说一次**。原来界面上
        // 「这一轮没查到」和「库压根是空的」长得一模一样，用户看到的只是
        // 「续写中…」，不知道它手上一份材料都没有（第 676 轮实跑）。
        setNoteHarnessStatus(d.round === 1 && d.kb_empty
          ? `第 1 轮：知识库还是空的，这次只能靠你已经写下的内容——导入材料之后续写才会引用你自己的记录。续写中…`
          : `第 ${d.round} 轮：修订 ${d.revisions_applied} 处，续写中…`)
        insertCursorRef.current = null
        // 续写的增量在这之后才开始到达——本地累积的 content 要先补一次
        // 分隔，跟后端 prompts.join_round_text() 是同一个道理
        // （TRACELOG [8]/[10]）：折叠 runHarness 那边已经修过的同一个坑，
        // 这里之前漏了，只修了文件夹 harness 那一侧。
        {
          const c = liveContentRef.current
          const next = c ? c.replace(/\n*$/, '') + '\n\n' : c
          liveContentRef.current = next
          setContent(next)
        }
      },
      onRevision: (r) => {
        if (currentRef.current?.id !== noteId) return
        // 从 liveContentRef 算，不用 updater（跟 onDelta 一样）：updater 要等 React 下一拍才跑，
        // 同一批事件里紧跟着的 delta 已经按旧的 ref 拼过了，updater 再把 ref 盖成「有修订没增量」的版本，
        // 两边各丢一半——第 375 轮真跑第 3 轮那 267 字的错位多半是这么来的
        // 应用完照服务端一样压一遍空行（服务端每条修订后 tidy_blank_lines），不然 delete 留下的三个空行两边不一样
        const next = tidyBlankLines(applyRevision(liveContentRef.current, { id: '', op: r.op as Revision['op'], anchor: r.anchor, anchor_end: r.anchor_end, text: r.text, reason: r.reason, sources: r.sources ?? [] }))
        // 本地重放没改动任何字 = 锚点没定位到：记下来，轮末的「差 N 字」才有下文
        if (next === liveContentRef.current) void api.clientLog('warn', `revision no-op (${r.op}): anchor ${JSON.stringify((r.anchor ?? '').slice(0, 50))}`, '', 'harness-sync')
        liveContentRef.current = next
        setContent(next)
        // 不弹 toast：一轮修订三四处就在右栏叠四张卡片（实拍），计划面板里有
        // 完整记录，状态行说一句就够
        setNoteHarnessStatus(`已自动${r.op === 'delete' ? '删除' : '修订'}一处：${r.reason.slice(0, 50)}`)
      },
      onInsertAt: (d) => {
        if (currentRef.current?.id !== noteId) return
        // 落点按本地正文重算（本地可能刚应用过修订、跟服务端差几个字）；
        // 找不到标题才用后端给的 pos。轮初为追加预留的那个空行要收回来。
        {
          const base = liveContentRef.current.replace(/\n+$/, '\n')
          const pos = sectionEnd(base, d.section) ?? Math.min(d.pos, base.length)
          // 腾位置的规则照服务端 outline.insert_into（editor/streamJoin.prepareInsert，check-stream-parity 对拍）
          const r = prepareInsert(base, pos)
          insertCursorRef.current = r.cursor
          liveContentRef.current = r.next
          setContent(r.next)
        }
        setNoteHarnessStatus((s) => s.replace(/续写中…$/, `写到「${d.section}」这一节…`))
        requestAnimationFrame(() => {
          const view = editorViewRef.current
          if (view && insertCursorRef.current != null) view.dispatch({ effects: EditorView.scrollIntoView(Math.min(insertCursorRef.current, view.state.doc.length), { y: 'center' }) })
        })
      },
      onDelta: (text) => {
        // 同时流进 Agent 运行面板。两段式之后编辑器有几十秒完全不动
        // （检索规划是非流式的），面板里能实时看到写出来的字，比一行
        // 干等的状态文案有用得多。
        //
        // **这一句排在 guard 前面**（P101 B）：它按 noteId 写，跟「现在显示的是哪篇」
        // 无关。P99 实拍丢的就是它——跑着切走 20 秒，卡上「本轮写出的正文」**2 → 1**，
        // 不切走的对照是 2。
        writeRounds(noteId, (rs) => {
          if (!rs.length) return rs
          const next = [...rs]
          const last = next[next.length - 1]
          next[next.length - 1] = { ...last, streamed: (last.streamed ?? '') + text }
          return next
    })
        // ── 记账到此为止，下面是**动正文**（切走了一个字都不许动）──
        if (currentRef.current?.id !== noteId) return
        {
          // 从 liveContentRef 算，不用 updater：updater 的执行时机跟闭包里的游标
          // 对不上就会漂（magic tap 那边实拍过）
          // 接缝处的多余空行在这里压掉（第 375 轮真跑：模型一段结束多吐两个换行，服务端会压、本地不压，
          // 一轮差 2–4 字）——规则在 editor/streamJoin.ts，有单测
          const r = insertStreamed(liveContentRef.current, insertCursorRef.current, text)
          if (insertCursorRef.current != null) insertCursorRef.current = r.cursor
          const next = r.next
          liveContentRef.current = next
          setContent(next)
        }
      },
      onTextEnd: () => {
        if (currentRef.current?.id !== noteId) return
        // 服务端续写收尾会对整篇 fix_bold_punct（**x：** → **x**：），本地同一遍（editor/format.fixBoldPunct，check-scrub-parity 对拍），不然轮末对齐报差字
        const next = fixBoldPunct(liveContentRef.current)
        if (next !== liveContentRef.current) { liveContentRef.current = next; setContent(next) }
      },
      onRoundEnd: (_round, serverContent) => {
        if (currentRef.current?.id !== noteId) return
        // 用服务端这一轮结束时的正文对齐。客户端按 anchor 重放修订会跑偏
        // （引用被改烂、分隔符不一致），服务端的才是真的。
        if (typeof serverContent === 'string' && serverContent && serverContent !== liveContentRef.current) {
          // 记一笔：本地重放的正文跟服务端差了多少。差得多说明客户端的重放逻辑
          // 又跑偏了——这是「agent 输出跟编辑器对不对得上」的证据，不是靠感觉。
          // 带上第一处不同的位置和前后 20 字：光看字数差 4 个字不知道是哪里跑偏的（第 351 轮实拍）
          // 只差文末的换行不算（第 492 轮真跑：每轮都是本地多一个尾部 \n——服务端 insert_into 之后
          // 会 strip，本地 onInsertAt 预留的分隔留着了）——照样用服务端的，但别当跑偏记 warn
          const local = liveContentRef.current
          if (local.replace(/\s+$/, '') !== serverContent.replace(/\s+$/, '')) {
            let at = 0
            while (at < local.length && at < serverContent.length && local[at] === serverContent[at]) at++
            const win = (t: string) => JSON.stringify(t.slice(Math.max(0, at - 20), at + 20))
            void api.clientLog('warn', `round ${_round}: 本地正文 ${local.length} 字 vs 服务端 ${serverContent.length} 字，已用服务端的；第一处不同在 ${at}：本地 ${win(local)} / 服务端 ${win(serverContent)}`, '', 'harness-sync')
          }
          liveContentRef.current = serverContent
          setContent(serverContent)
        }
        // 轮末拿快照跟当前正文做词级 diff，标出这一轮的增删。
        // 修订是自动应用的（不等人工接受），不标出来用户根本不知道
        // 正文被动了哪里。
        // 每轮末都拿**整次 run 的起点**重算一次，高亮是累积的：
        // 装饰会被下一轮的文档改动清掉，但下一轮末又会重新算出来，
        // 且范围只增不减。
        const base = runBaseRef.current
        const cur = liveContentRef.current
        // 只差首尾空白（轮初为续写预留的空行、模型没应答）不算改动——不然模型连不上
        // 也会冒出「这一轮改了 1 处」（实拍）
        if (base && cur && base.replace(/\s+$/, '') !== cur.replace(/\s+$/, '')) pushDiff('智能续写', base, cur, true)
      },
      onEvaluate: (d) => {
        // **记账排在 guard 前面**（P101 B）：按 noteId 写，切走了照样该记这一轮的分。
        writeRounds(noteId, (rs) => {
          if (!rs.length) return rs
          const next = [...rs]
          next[next.length - 1] = {
            ...next[next.length - 1],
            scores: d.scores, status: d.status, weakest: d.weakest,
            // P11 #5：打分器引了正文里没有的原文、被摘掉不计分的那几维
            judgeHallucinated: d.judge_hallucinated ?? [],
          }
          return next
    })
        // ── 记账到此为止，下面是**动当前这篇的右栏 / 状态行** ──
        if (currentRef.current?.id !== noteId) return
        const beatScore = d.scores['beat_coverage']
        if (beatScore) setBeatCoverage(beatScore)
        if (d.status === 'continue' && d.weakest) {
          setNoteHarnessStatus(`这一轮评分：${d.weakest} 还不够，下一轮优先改这个`)
    }
      },
      onPhase: (d) => {
        // **整条都是按 noteId 记账**（P101 B）：那句一刀切的 guard 在这儿纯属误伤，删了。
        // 用 patchRound 而不是改"最后一张卡片"：修订 pass 跑在
        // round-start **之前**，第 1 轮的 edit 阶段到达时卡片还不存在，
        // 直接改最后一张会把它整段丢掉——而那正是最想看的第一段。
        patchRound(noteId, d.round, { phase: d.phase, phaseLabel: d.label })
      },
      onPhaseDelta: (d) => {
        // **整条都是按 noteId 记账**（P101 B）：一刀切的 guard 在这儿是误伤，删了。
        writeRounds(noteId, (rs) => {
          const i = rs.findIndex((r) => r.round === d.round)
          const base = i < 0 ? null : rs[i]
          const pt = { ...(base?.phaseText ?? {}) }
          const cur = pt[d.phase] ?? { thinking: '', output: '' }
          pt[d.phase] = d.kind === 'thinking'
            ? { ...cur, thinking: cur.thinking + d.text }
            : { ...cur, output: cur.output + d.text }
          if (i < 0) {
            return [...rs, {
              round: d.round, cleanupOnly: false, revisions: 0, toolCalls: [],
              toolTruncated: false, scores: {}, status: '', weakest: null,
              policyReasons: [], policy: null, errors: [], dropped: [], phaseText: pt,
            }]
          }
          const next = [...rs]
          next[i] = { ...base!, phaseText: pt }
          return next
    })
      },
      onToolCalls: (d) => {
        // **记账排在 guard 前面**（P101 B）；状态行那句是「现在显示的这篇」的，照旧拦。
        patchRound(noteId, d.round, { toolCalls: d.calls, toolTruncated: d.truncated })
        if (currentRef.current?.id !== noteId) return
        setNoteHarnessStatus(`第 ${d.round} 轮：agent 自己查了知识库 ${d.calls.length} 次，续写中…`)
      },
      onPolicy: (d) => {
        // **整条都是按 noteId 记账**（P101 B）：一刀切的 guard 在这儿是误伤，删了。
        // round 0 = 开跑前用历史运行记录定的初始策略，还没有对应的轮次卡片，
        // 挂到第 1 轮上；其余挂在产生它的那一轮
        patchRound(noteId, Math.max(1, d.round), { policyReasons: d.reasons, policy: d.policy })
      },
      onScrub: ({ sentence }) => {
        // 服务端在轮内把一整句删了（元话语 / 审计腔）：本地同一句也删掉，不然到轮末两边差一整句（第 381 轮真跑）。
        // 找不到就算了——轮末服务端的正文会对齐回来
        if (currentRef.current?.id !== noteId || !sentence) return
        const c = liveContentRef.current
        const at = c.indexOf(sentence)
        // 本地找不到那句：记下来——轮末对齐会报「差 N 字」，但不记这条就不知道是 scrub 没对上还是别的（第 556 轮真跑差 52 字）
        if (at < 0) { void api.clientLog('warn', `scrub miss: ${JSON.stringify(sentence.slice(0, 60))}`, '', 'harness-sync'); return }
        // 规则照抄服务端（同段其它句子也会被 strip），见 editor/streamJoin.applyScrub
        const next = tidyBlankLines(applyScrub(c, sentence))
        if (next === c) void api.clientLog('warn', `scrub no-op: ${JSON.stringify(sentence.slice(0, 60))}`, '', 'harness-sync')
        if (insertCursorRef.current != null && insertCursorRef.current > at) insertCursorRef.current = Math.max(at, insertCursorRef.current - (c.length - next.length))
        liveContentRef.current = next
        setContent(next)
      },
      onDedup: ({ paragraph }) => {
        // 服务端落进正文前剥掉的段 / 行（重复、模型自己写的标题）：本地也删——它们已经流进编辑器了
        if (currentRef.current?.id !== noteId || !paragraph) return
        const c = liveContentRef.current
        const at = c.indexOf(paragraph)
        if (at < 0) { void api.clientLog('warn', `dedup miss: ${JSON.stringify(paragraph.slice(0, 60))}`, '', 'harness-sync'); return }
        const next = tidyBlankLines(c.slice(0, at) + c.slice(at + paragraph.length))
        if (insertCursorRef.current != null && insertCursorRef.current > at) insertCursorRef.current = Math.max(at, insertCursorRef.current - (c.length - next.length))
        liveContentRef.current = next
        setContent(next)
      },
      onDropped: (detail) => {
        // 防线丢掉一条修订不是出错，收在单独的可折叠区里，不占报错的红色。
        // **整条都是按 noteId 记账**（P101 B）：一刀切的 guard 在这儿是误伤，删了。
        writeRounds(noteId, (rs) => {
          if (!rs.length) return rs
          const next = [...rs]
          next[next.length - 1] = {
            ...next[next.length - 1],
            dropped: [...next[next.length - 1].dropped, detail],
          }
          return next
    })
      },
      onSkills: (d) => {
        // 这次跑带了哪几条技能（P1-1b）。第一轮开跑就到，记在那一轮的卡片上；
        // 用户第 768 轮「Skill 有时能加载有时不能」——此前界面上没有任何一处说过这件事。
        // **整条都是按 noteId 记账**（P101 B）：一刀切的 guard 在这儿是误伤，删了。
        patchRound(noteId, d.round, { skills: { scope: d.scope, injected: d.injected, menu: d.menu } })
      },
      onCheckHit: (d) => {
        // 代码判据当场判不合格，这一轮不会再花模型调用去打分。不标出来的话
        // 用户看到一个 0 分，不知道是谁判的、为什么这轮这么快。
        // 带 `stuck_rounds` 的是另一回事：这条连着卡了几轮改不动，后端已经
        // 放行、照常打分了，得说清楚，否则「报了错还给了分」看着像矛盾。
        //
        // **攒成一串，不是留最后一条**（计划 12.1）：一轮里可以先到几条
        // 「卡住了放行」的、最后才到短路的那一条，原来后到的把先到的盖掉
        // ——判据真的命中了，用户看不见。
        //
        // **整条都是这次跑的账**（P101 B）：`writeRounds` 按 noteId 写，
        // `stuckCheckRef` 是 `onDone` 那句「连响几轮」的唯一来源，而 `onDone`
        // 切走了照样跑——拦住这儿等于让收工那句话少半截。一刀切的 guard 删了。
        if (d.stopped) stuckCheckRef.current = { check: d.check || '', rounds: d.stuck_rounds || 0 }
        writeRounds(noteId, (rs) => {
          if (!rs.length) return rs
          const next = [...rs]
          const last = next[next.length - 1]
          next[next.length - 1] = withCheckHit(last, d)
          return next
        })
      },
      onCost: (d) => {
        // 单次跑的成本上限（后端计划 12.3）。**停下来告诉用户，不是静默截断**——
        // 不说一声的话，用户看到的只是「这次怎么只跑了两轮」。
        //
        // **切走之后照样说，但点名**（P103 B ①）。判据：这一句是**停机的理由**，
        // 而紧跟着那条 `onDone(reason='cost_cap')` 在切走那一支里只说「已结束」、
        // **理由那半句丢了**（逐字：「「X」的智能续写已结束，内容已保存在那篇里」）。
        // 花掉的 token 是用户的钱，「为什么只跑了两轮」不该因为他换了个标签页就没人说。
        if (currentRef.current?.id !== noteId) { awayToast(d.detail); return }
        toast(d.detail, 'error')
      },
      onCrossRun: (d) => {
        // 这次跑完比上一次跑差（后端计划 9.3）。**只报不回滚**：上一版正文在
        // 「历史版本」里，回不回去是用户的决定，不是我们的。
        //
        // **切走之后照样说，但点名**（P103 B ②）。判据比 `onCost` 还硬一格：
        // 这一句给了**下一步动作**（「上一次的正文在『历史版本』里，要回去随时可以」），
        // 而「历史版本」是**按篇的右栏**。不点名 = 把人送去翻**错的那一篇**的历史版本。
        // ⇒ 这一条要么点名要么别弹，**原样放行是三条里最坏的一条**。
        if (currentRef.current?.id !== noteId) { awayToast(d.detail); return }
        toast(d.detail, 'error')
      },
      onWarning: (d) => {
        // 一条 middleware 抛异常了。循环继续跑（能力分包的隔离好处），但这一轮
        // 少了那个能力——后端注释写着「不能是静默的」，可在这之前前端根本没接
        // 这个事件，发出来的警告全被丢掉了。
        //
        // **切走之后照旧拦**（P103 B ③，三条里唯一不改的那条）。两条理由，都窄：
        //  · **跑还在继续，用户这一刻做不了任何事**——`onCost` / `onCrossRun` 各自
        //    给了一件事（钱花完了 / 去翻历史版本），这一条给不出。
        //  · **它一轮可以来好几条**：`loop._wrap` 里**每个 middleware 每个钩子**
        //    抛一次就发一条，`hooks/note.py` 光骨架那一处就有两种（生成失败 / 存着的是半句）。
        //    切走之后连弹几条无从下手的红字，是噪声不是通知。
        // ⚠️ 它被拦掉之后**这一轮少了哪个能力这件事在界面上就没有第二个出处了**
        //    （轮次卡上没有这一格）。照实记在 `docs/edge-cases.md`，
        //    要接就得先给轮次卡加一格「这一轮少了什么」——**那是另一刀**。
        if (currentRef.current?.id !== noteId) return
        toast(`「${d.middleware}」这一步出错了，本轮少了这个能力：${d.error}`, 'error')
      },
      onError: (detail) => {
        // **记账排在 guard 前面**（P101 B）：这一轮报了什么错是这一篇的账，
        // 按 noteId 写；切走了这张卡照样该留着那段红字。
        writeRounds(noteId, (rs) => {
          if (!rs.length) return rs
          const next = [...rs]
          next[next.length - 1] = {
            ...next[next.length - 1],
            errors: [...next[next.length - 1].errors, detail],
          }
          return next
    })
        // ── 下面全是**现在显示的这篇**的（状态行 / toast / 「跑完了」那个开关）──
        if (currentRef.current?.id !== noteId) return
        // `loop.run` 只在整个跑挂掉时才发 RUN_ERROR（之后没有 RUN_FINISHED）。P3 实拍：模型 500 时
        // 轮次卡片上挂着一段红字、状态却停在「在写…」，没有 toast、没有「停下了」。这里把话说全。
        setHarnessDone(true); harnessDoneRef.current = true
        setNoteHarnessStatus(`${mode === 'polish' ? '打磨' : '智能续写'}出错停下：${detail}`)
        if (/连不上|拒绝|返回 \d{3}|没应答/.test(detail)) toastAction(`${mode === 'polish' ? '打磨' : '智能续写'}出错停下：${detail}`, '打开设置', () => void openVirtual('app:settings', '设置'), 8000)
        else toast(`${mode === 'polish' ? '打磨' : '智能续写'}出错停下：${detail}`, 'error')
      },
      onDone: (reason, blockedReason, runId, serverContent) => {
        // **用户已经切到别的笔记了**：这一篇的结果绝不能写进现在显示的那篇——
        // 探针实拍：run 在 A 上跑完，把 A 的正文塞进了正显示的 B 的编辑器，
        // 自动保存接着就会把 A 的内容存进 B。只提示一句，正文由服务端保存。
        if (currentRef.current?.id !== noteId) {
          toast(`「${notes.find((x) => x.id === noteId)?.title || '另一篇笔记'}」的${mode === 'polish' ? '打磨' : '智能续写'}已结束，内容已保存在那篇里`)
          return
        }
        // 跑完（或暂停）时也用服务端的正文对齐——见 onRoundEnd
        if (typeof serverContent === 'string' && serverContent && serverContent !== liveContentRef.current) {
          liveContentRef.current = serverContent
          setContent(serverContent)
        }
        // 跑完 / 暂停了，卡片上的「在写…」阶段标签得摘掉，不然停了还显示在写（实拍）
        writeRounds(noteId, (rs) => rs.map((r) => (r.phaseLabel ? { ...r, phase: undefined, phaseLabel: undefined } : r)))
        if (reason === 'awaiting_review' && runId) {
          // 这一轮写完了，等你处置。**正文的最终形态由编辑器说了算**——
          // 逐条接受/撤回都在这儿做，点「接着写」时把当前正文送回去。
          pausedRef.current = true
          setPausedRun({ id: runId, noteId, mode })
          setNoteHarnessStatus('这一轮写完了，逐条看过之后点「接着写」')
          return
    }
        const label = reason === 'no_more_changes' ? '已经改不动了，打磨结束'
          : reason === 'complete' ? (mode === 'polish' ? '已写内容都达标了，打磨完成' : '内容已完整，自动停止')
          : reason === 'blocked' ? `卡住了，需要你看一眼：${blockedReason || '原因未知'}`
          // P8 问题 10：这条规则数的是**修订**没落地（`no_change_rounds`），不是「没有新内容」
          // ——P6 e783 停在 stalled 时那两轮续写各写了 393 / 333 字，文案跟机制要对得上。
          : reason === 'stalled' ? '连续两轮修订都没落地，自动停止（这几轮写的内容留着）'
          : reason === 'regressed' ? '再改反而更差，留下了最好的那轮'
          : reason === 'cost_cap' ? '这次跑到了成本上限，留下了最好的那轮'
          : reason === 'material_used_up' ? '知识库里能用的材料用完了，自动停止'
          // P6 问题 4：同一条判据连响几轮、模型一次都没照做，后端停了交最好的一轮。
          // 「哪条、几轮」来自收工前那条带 stopped 的 check_hit 事件。
          : reason === 'check_stuck' ? (stuckCheckRef.current
              // 后面那半句「下一步做什么」只给**模型答的形状不对**那一档（`stuckTail`，P40 · B #2）：
              // 别的判据连响几轮说的是内容还没写到位，下一步是「你自己看一眼」，不是「换个模型」。
              ? `「${checkLabel(stuckCheckRef.current.check)}」这条判据连响 ${stuckCheckRef.current.rounds} 轮都没解决，停下留了最好的那轮${stuckTail(stuckCheckRef.current.check)}`
              : '同一条判据连响几轮都没解决，停下留了最好的那轮')
          // P55 #4：`best` 连着几轮一格没涨。**不能落到下面那句兜底上**——
          // 「到达轮数上限」会让用户以为再多给几轮就能更好，而这条规则说的恰好相反：
          // 已经量过了，接着跑不会更好（`modes.BEST_STALL_ROUNDS`）。
          : reason === 'best_stalled' ? '接连几轮都没写得更好，停下留了最好的那轮'
          : '到达轮数上限，自动停止'
        stuckCheckRef.current = null
        const delta = liveContentRef.current.length - runBaseRef.current.length
        const summary = `${label} · ${(roundsByNoteRef.current[noteId]?.length ?? 0) || 1} 轮 · ${delta === 0 ? '正文没有改动' : `${delta > 0 ? '+' : ''}${delta} 字`}`
        setNoteHarnessStatus(summary)
        harnessDoneRef.current = true
        setHarnessDone(true)
        toast(`智能续写：${label}`, reason === 'blocked' ? 'error' : undefined)
        notifyIfHidden('MEMOKET NOTE · 智能续写', `${notes.find((x) => x.id === noteId)?.title || '笔记'}：${label}`)
      },
    }
    // **统一挡一层**：run 属于 noteId 那篇，用户切走之后**动正文 / 动编辑器**那几条
    // 都不该碰现在显示的这篇——之前只有一半 handler 各自写了这条判断，漏掉的那半
    // （onDone 的正文对齐、骨架）把 A 的内容和骨架写进了 B（探针实拍两次）。
    //
    // **P101 B：这一层原来是「一刀切」，那是误伤。** `writeRounds` / `patchRound`
    // 本来就**按 noteId 写**（P95 A 那一刀），碰不到「现在显示的那篇」；拦住它们的后果
    // 是 P99 在真壳上实拍到的 **2 → 1**（跑着切走 20 秒，卡上「本轮写出的正文」少一整块，
    // 不切走的对照是 2）。所以现在**按 `util/harnessGuard` 那张表逐条问**：
    // 有按 noteId 记账那一份的放行（它们自己把记账那几句排在自己那句 guard 前面），
    // 一点账都不记的照旧拦。**表里没有的键一律拦**（保守那一侧），
    // 而「新加一条忘了归档」有闸当场红（`scripts/check-harness-guard.mts`：集合相等）。
    //
    // **P103 B：那句 `k !== 'onDone'` 拿掉了。** 它本来就是多余的
    // （`guardBlocks('onDone')` 因为归在 `self` 档本来就回 false），
    // 而这一批 `self` 档从 1 条变成 3 条（`onDone` / `onCost` / `onCrossRun`：
    // 三条都**自己判跨篇**，切走了就说一句**点了名**的话），
    // 留着那个写死的键名会读成「只有 onDone 是例外」——**跟表里写的不是一回事**。
    const guarded: api.NoteHarnessHandlers = {}
    for (const [k, fn] of Object.entries(h) as [keyof api.NoteHarnessHandlers, (...a: unknown[]) => void][]) {
      guarded[k] = ((...args: unknown[]) => {
        if (guardBlocks(k) && currentRef.current?.id !== noteId) return
        fn(...args)
      }) as never
    }
    return guarded
  }
  async function runNoteHarness(mode: 'write' | 'polish' = 'write') {
    if (loading === 'note-harness') {
      // 点"停止"时**同时强制复位状态**，不要只 abort 就指望 fetch 的
      // finally 去复位——真实踩过：后端重启切断 SSE 连接后，前端
      // reader.read() 卡住不返回，finally 永远不执行，loading 一直停在
      // 'note-harness'。于是死锁：再点按钮它以为还在运行、走到这里
      // abort 一个已经死掉的请求、直接 return，什么都不发生，用户只能
      // 刷新页面才能继续用。
      abortRef.current?.abort()
      abortRef.current = null
      setLoading('')
      setNoteHarnessStatus('')
      toast('已停止智能续写，写到哪算哪——改动在右栏「改动」里可以整层撤回')   // P3 遗留：第二下 = 停止但原来一个字不说
      return
    }
    if (!current) return
    { const why = notePrecondition(mode === 'polish' ? 'polish' : 'harness', content, title); if (why) { toast(why); return } }
    if (!llmGate()) return
    const noteId = current.id
    // 起跑时记一笔发出去的是什么：哪篇、多少字、骨架开头——探针实拍过一次
    // 「跑在了另一篇上」，没有这条日志只能猜。
    void api.clientLog('info', `harness start note=${noteId} title=${current.title.slice(0, 20)} content=${content.length} spine=${spine.slice(0, 30)} beats=${beats.length}`, '', 'harness-start')
    setLoading('note-harness'); setNoteHarnessNoteId(noteId)
    setNoteHarnessStatus('启动中…')
    setHarnessDone(false); harnessDoneRef.current = false
    setBeatCoverage(null)
    writeRounds(noteId, () => [])
    setRoundDiff(null)
    setPausedRun(null)
    pausedRef.current = false
    liveContentRef.current = content
    runBaseRef.current = content
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      await api.runNoteHarness(
        noteId, content, spine, beats,
        noteHarnessHandlers(noteId, mode),
        ctrl.signal,
        mode,
        reviewEachRound,
        intentText(intent),          // 文档意图进 harness 的 system 第一段（P11）
      )
    } catch (e) {
      if ((e as Error).name !== 'AbortError') toast(
        (mode === 'polish' ? '打磨' : '智能续写') + '失败：' + friendlyError(e), 'error')
    } finally {
      setLoading(''); setNoteHarnessNoteId(null)
      // 停在「等你处置」时不能清——那句提示刚在 onDone 里设好，清掉就等于
      // 两个按钮凭空出现、没有任何说明。
      if (!pausedRef.current && !harnessDoneRef.current) setNoteHarnessStatus('')
      abortRef.current = null
      void reload()
      // reload() 会用服务端正文替换文档，docChanged 会把装饰清掉——跑完
      // 之后必须再补一次，不然用户最终什么都看不到（这正是"只有第一次
      // 有绿色"的第二个原因）。
      const base = runBaseRef.current
      const cur = liveContentRef.current
      if (base && cur && base !== cur) pushDiff('智能续写', base, cur, true)
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
  /** 同步：服务端读这篇最新正文，删旧 session 重抽。跟摄入一样是后台 job，状态栏 / toast 同一套。 */
  async function syncNoteToKb(noteId: string) {
    if (job) return                                    // 一次只跑一个
    try {
      await save()
      const r = await api.syncNoteToKb(noteId)
      setJob(r.job_id)
    } catch (e) {
      toast('同步失败：' + friendlyError(e), 'error')
    }
  }

  // 自动同步：设置里开了的话，摄入过的笔记改完 2 分钟没再动就同步一次；切走时马上同步。
  // 每次同步是一次抽取调用，所以默认关、要防抖。
  const [autoSync, setAutoSync] = useState(false)
  useEffect(() => {
    const load = () => api.getProviderConfig().then((c) => setAutoSync(!!c.auto_sync_notes)).catch(() => {})
    void load()
    const onProv = () => { void load() }
    window.addEventListener('provider-changed', onProv)
    return () => window.removeEventListener('provider-changed', onProv)
  }, [])
  const autoSyncTimer = useRef<number | null>(null)
  const dirtySinceIngest = useRef<string>('')          // 哪篇改过还没同步
  useEffect(() => {
    if (!autoSync || !current?.ingested_at) return
    if (content === current.content) return           // 没改
    dirtySinceIngest.current = current.id
    if (autoSyncTimer.current) window.clearTimeout(autoSyncTimer.current)
    const id = current.id
    autoSyncTimer.current = window.setTimeout(() => {
      if (dirtySinceIngest.current === id && currentRef.current?.id === id && !new URLSearchParams(location.search).get('probe')) {
        dirtySinceIngest.current = ''
        void syncNoteToKb(id)
      }
    }, 120_000)
    return () => { if (autoSyncTimer.current) window.clearTimeout(autoSyncTimer.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, autoSync, current?.id])

  async function ingestCurrentNote() {
    { const why = notePrecondition('ingest', content); if (why) { toast(why); return } }
    // P3 实拍：「⋯ → 存入知识库」连点两下发了两个 job，同一篇抽两遍事实。ribbon「引用」那个钮本来就按 job 禁用，这里补齐
    if (job || loading === 'ingest') { toast('这篇正在存入知识库，等它跑完再点'); return }
    setLoading('ingest')
    try {
      const r = await api.ingestText(content, title || '未命名', 'note', current?.id ?? '')
      setJob(r.job_id)
    } catch (e) {
      toast('存入知识库失败：' + friendlyError(e), 'error')
    } finally {
      setLoading('')
    }
  }

  /** 把找不到的引用从正文里删掉：走 CM 的 changes（可撤销、跟敲键一条路），没有编辑器时直接改 content */
  function stripCitationIds(ids: string[]) {
    if (!ids.length) return
    const view = editorViewRef.current
    if (view) {
      const ranges = citationRanges(view.state.doc.toString(), ids)
      if (ranges.length) view.dispatch({ changes: ranges.map((r) => ({ from: r.from, to: r.to, insert: '' })) })
      toast(`已清掉 ${ranges.length} 处引用`)
      return
    }
    setContent((c) => {
      const ranges = citationRanges(c, ids)
      let out = c
      for (const r of [...ranges].reverse()) out = out.slice(0, r.from) + out.slice(r.to)
      return out
    })
  }

  /** 链到已删笔记的 `[标题](note://id)` 改成纯文本：跟 stripCitationIds 一条路 */
  function unlinkNotes(ids: string[]) {
    if (!ids.length) return
    const view = editorViewRef.current
    if (view) {
      const ranges = noteLinkRanges(view.state.doc.toString(), ids)
      if (ranges.length) view.dispatch({ changes: ranges })
      toast(`已把 ${ranges.length} 条链接改成纯文本`)
      return
    }
    setContent((c) => {
      let out = c
      for (const r of [...noteLinkRanges(c, ids)].reverse()) out = out.slice(0, r.from) + r.insert + out.slice(r.to)
      return out
    })
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
  /** 导入 .md：一个文件就是一篇；**多个文件生成一棵子树**——一个「导入 日期」
   *  的父节点，每个文件是它的子节点。几十篇散在树根上没法收拾。 */
  async function importMarkdown(files: FileList | null, under: string = api.ROOT_ID, toKb = false) {
    const list = Array.from(files ?? []).filter((f) => /\.(md|markdown|txt)$/i.test(f.name))
    if (list.length === 0) { if (files?.length) toast('只认 .md / .markdown / .txt——选的文件里没有这几种'); return }
    await save()
    // P3 实拍：后端没起来时选完文件什么都不发生。整段兜住，建到一半失败也说清建了几篇。
    try { await importMarkdownFiles(list, under, toKb) }
    catch (e) { toast('导入失败：' + friendlyError(e), 'error'); void reload(); void reloadTree() }
  }

  async function importMarkdownFiles(list: File[], under: string, toKb: boolean) {
    const strip = (name: string) => name.replace(/\.(md|markdown|txt)$/i, '')
    // 顺带抽进知识库。**这一条是补一个路由上的坑**（第 678 轮）：知识库空态页
    // 上那个主按钮「导入」把人送到这一页，而这一页最上面、最显眼的就是这张
    // Markdown 卡——它是页面上**唯一一条到不了知识库的路**，而用户恰恰是为了
    // 填知识库才点进来的。走的是跟「存入知识库」同一条 `ingest/text`。
    const ingest = async (notes: { id: string; title: string; content: string }[]) => {
      if (!toKb) return
      for (const n of notes) {
        try { await api.ingestText(n.content, n.title || '未命名', 'note', n.id) } catch { /* 单篇失败不挡其余 */ }
      }
      toast(`${notes.length} 篇已排进知识库抽取，抽完会在「最近摄入」里`)
    }
    // 导入默认进托盘（P15 #3）：落成的几篇先摊到最近那篇的桌上；开关在托盘格里，关了就只建笔记
    const toTray = async (notes: { id: string; title: string; content: string }[]) => {
      const target = trayTargetRef.current
      if (!trayByDefault() || !target) return
      try {
        const k = await landNotesInTray(target, notes)
        if (k) toast(`导入的 ${k} 篇已进托盘——写那篇时优先用；不想要就在托盘里移除`)
      } catch (e) { toast('进托盘没成：' + friendlyError(e), 'error') }
    }
    if (list.length === 1) {
      const text = await list[0].text()
      const n = await api.createNote(strip(list[0].name), text, under)
      await reload(); await reloadTree()
      await ingest([{ id: n.id, title: n.title, content: text }])
      await toTray([{ id: n.id, title: n.title, content: text }])
      open(n); return
    }
    const parent = await api.createNote(`导入 ${fmtDate(new Date().toISOString())}`, `从 ${list.length} 个文件导入。`, under)
    void api.setNoteIcon(parent.id, 'bx-import').catch(() => {})     // 导入进来的那一批挂在一个带「导入」图标的节点下
    let first: Note | null = null
    const made: { id: string; title: string; content: string }[] = []
    for (const f of list) {
      const text = await f.text()
      const n = await api.createNote(strip(f.name), text, parent.id)
      made.push({ id: n.id, title: n.title, content: text })
      first ??= n
    }
    await reload(); await reloadTree()
    toast(`已导入 ${list.length} 篇，放在「${parent.title}」下面`)
    await ingest(made)
    await toTray(made)
    open(first ?? parent)
  }

  /** 完整来龙去脉（模型、20 秒左右）：右键菜单和 ⌥ 悬停卡上的「查完整来龙去脉」都走这条；结果在右栏「脉络」。
   *  **用户不写问题**——问题由后端拼（判据 1）；结果不是弹层（判据 2）。 */
  async function traceFull(text: string, signal?: AbortSignal) {
    const r = await api.traceMemory(text, 10, signal)
    // **说的是哪一段也要带着走**（P43 #5）：跑完这一趟，右栏上面会同时挂着「校验结果」
    // 和「脉络」两块，而它们常常说的是**不同的两段**（P42 问题 #6 实拍）。
    // 「校验」那块 P41 已经写清了自己在说哪一段，这块没写——两块并排、一块报户口一块不报，
    // 用户还是分不清。用的是同一个 `verifyScopeLine`，一份判据，两处不会各说各的。
    setTrace({ answer: r.answer, facts: r.facts, recalled: r.recalled ?? null, at: new Date().toISOString(), passage: text })
    // 结果落在右栏「脉络」——要把那个标签切过去，不然用户等了 40 秒只看到角标变了（实拍）
    setPaneFocus({ id: 'trace', n: Date.now() })
  }
  async function traceFromCard(phrase: string) {
    if (!llmGate()) return
    toast(`正在查「${phrase}」的完整来龙去脉，20 秒左右，结果在右栏「脉络」`)
    try { await traceFull(phrase) } catch (e) { toast('来龙去脉查不了：' + friendlyError(e), 'error') }
  }

  /** 「回到这轮之前」（P16 分层历史）：恢复第 N 轮开始前那一版——后端恢复前会再存一版（before_restore），永远可逆。 */
  async function restoreBeforeRound(r: RunRound) {
    if (!current) return
    setLoading('rounds')
    try {
      const n = await api.restoreRevision(current.id, r.before.id)
      setCurrent(n); setTitle(n.title); setContent(n.content); liveContentRef.current = n.content
      void reload()
      setRunsTick((t) => t + 1)
      toast(`已回到第 ${r.round_no} 轮之前（回来之前的正文也留了一版）`)
    } catch (e) { toast('回不去：' + friendlyError(e), 'error') }
    finally { setLoading('') }
  }
  /** 「只撤这一轮」（P16 分层历史）：拿这一轮前后两版做 diff、反向应用到现在的正文（`editor/undoRound`）；
   *  结果作为一层提案标出来（「撤掉第 N 轮」），不对就在「改动」里撤回这一层。对不上的地方说清楚，不猜。 */
  async function undoRoundOnly(r: RunRound) {
    if (!current || !r.after) return
    setLoading('rounds')
    try {
      // 后几轮的快照也一起取：这一轮的改动要沿它们映射过去（P18 #3——后一轮改过这轮的句子不再只报冲突）
      const [before, after, ...later] = await Promise.all([r.before, r.after, ...r.later].map((x) => api.getRevision(current.id, x.id)))
      // 从编辑器的实时文档读（同 applyAsDiff）：await 之后闭包里的 content 可能已经过时
      const cur = editorViewRef.current?.state.doc.toString() ?? content
      const res = undoRound(before.content, after.content, cur, later.map((x) => x.content))
      if (res.undone === 0) {
        toast(`第 ${r.round_no} 轮改的 ${res.total} 处在现在的正文里都对不上，没有改动。${res.conflicts[0] ?? ''}`, 'error')
        return
      }
      setContent(res.text)
      pushDiff(`撤掉第 ${r.round_no} 轮`, cur, res.text)
      if (res.conflicts.length) toast(`撤掉了第 ${r.round_no} 轮的 ${res.undone} 处；${res.conflicts.length} 处对不上没动：${res.conflicts.join('；')}`, 'error')
      else toast(`撤掉了第 ${r.round_no} 轮的 ${res.undone} 处，别的轮留着；不对就在「改动」里撤回这一层`)
    } catch (e) { toast('撤不了：' + friendlyError(e), 'error') }
    finally { setLoading('') }
  }

  /** 全部接受：只是把标记清掉，正文保持现状。
   *
   *  **顺手把库里那几层当场烧掉**（P41 #6）：光靠编辑器清空 + 下一次防抖冲库不够——
   *  烧完立刻关掉 app，那一次冲库没发出去，下次打开会按旧坐标把高亮标到
   *  已经烧进正文的字上。`keepalive` 是同一条理由（`saveChangeLayers` 那边写过）。
   *  放不回来的那几层（`layerStuck`）一起了结：「全部接受」说的是全部。 */
  function acceptAllDiff() {
    editorViewRef.current?.dispatch({ effects: acceptAllHunks.of(null) })
    layerStuckRef.current = []
    setLayerStuck([])
    const id = currentRef.current?.id
    if (!id) return
    layersSaved.current = { noteId: id, payload: [] }     // 库里已经空了，别再发一次空表
    void api.burnChangeLayers(id, true).catch(() => { layersSaved.current = { noteId: '', payload: [] } })
  }

  /** 全部撤回：把这一轮改的全部还原。
   *
   * **从后往前撤**——每撤一处都会改变文档长度，从前往后的话后面那些 hunk 的
   * 位置就全错位了。逐处撤回不用管这个（每次 dispatch 之后剩下的 hunk 会跟着
   * 映射），批量在同一批里做就必须自己保证顺序。 */
  function rejectAllDiff() {
    const view = editorViewRef.current
    if (!view) return
    const hunks = [...(view.state.field(roundDiffField, false)?.hunks ?? [])]
      .sort((a, b) => b.from - a.from)
    if (!hunks.length) return
    for (const h of hunks) {
      if (h.off) { view.dispatch({ effects: dropHunk.of(h.id) }); continue }   // 关着的层：正文已是原文
      view.dispatch({ changes: { from: h.from, to: h.to, insert: h.del },
                      effects: dropHunk.of(h.id) })
    }
  }

  /** 处置完接着跑，或者到此为止。
   *
   * 送回去的是**编辑器当前的正文**：逐条接受/撤回都发生在编辑器里，让后端
   * 拿一串 hunk id 再合并一遍等于同一个合并写两份实现，而用户真正看到的是
   * 浏览器里那一份。
   */
  async function resumePausedRun(stop = false) {
    const run = pausedRun
    const view = editorViewRef.current
    if (!run || !view) return
    const kept = view.state.doc.toString()
    setPausedRun(null)
    if (stop) {
      try {
        await api.stopHarness(run.id, kept)
        // 用 toast 不用状态行：这一刻 pausedRun 已经清空、loading 也是 ''，
        // 状态行的两个渲染条件都不成立，写进去没人看得见。
        setNoteHarnessStatus('')
        toast('已按你处置后的正文收尾')
      } catch (e) {
        toast('收尾失败：' + friendlyError(e), 'error')
      }
      setLoading('')
      return
    }
    setLoading('note-harness'); setNoteHarnessNoteId(run.noteId)
    setNoteHarnessStatus('接着写…')
    runBaseRef.current = kept
    liveContentRef.current = kept
    setRoundDiff(null)
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      await api.resumeHarness(
        run.id, kept, noteHarnessHandlers(run.noteId, run.mode), ctrl.signal)
    } catch (e) {
      if ((e as Error).name !== 'AbortError') toast('接着写失败：' + friendlyError(e), 'error')
    } finally {
      abortRef.current = null
      setLoading(''); setNoteHarnessNoteId(null)
    }
  }

  /** 一键格式化整篇。
   *
   * **纯规则、不走模型**（见 editor/format.ts）：格式是有明确规则的东西，
   * 交给模型只会每次结果不一样、还可能顺手改内容。
   *
   * 结果按 diff 交给「接受 / 撤回」——整篇重排是个大改动，用户得能逐处看、
   * 也能一键全撤。 */
  function formatNote() {
    const view = editorViewRef.current
    if (!view) return
    const before = view.state.doc.toString()
    const after = formatMarkdown(before)
    if (after === before) { toast('已经是规范格式了，没有需要改的'); return }
    // 只换真正变了的那一段：整篇替换会把光标和视口拽到文末（跟外部更新走同一条路）
    const change = minimalChange(before, after)
    if (change) view.dispatch({ changes: change })
    setContent(after)
    pushDiff('格式化', before, after)
    toast(`格式化：改动 ${Math.abs(after.length - before.length)} 字（空行 / 空格 / 表格对齐）`)
  }

  /** 智能排版。跟一键格式化是**互补**的两件事：
   *
   * · 格式化（纯规则）只能把**已经标好**的结构规范化——补空格、对齐表格、
   *   块之间补空行。它判断不了「这一行应该是标题」。
   * · 智能排版做的正是那个语义判断，但**模型只输出「第几行改成什么结构」**，
   *   原文由后端按行搬运，所以改不到内容。
   *
   * 排完再跑一次格式化，输出仍然是规范的；结果按 diff 交给「接受 / 撤回」。 */
  async function restructureNote() {
    const view = editorViewRef.current
    if (!view || !current) return
    const before = view.state.doc.toString()
    // P3 实拍：空白笔记上点「智能排版」什么都不发生——不发请求，但要说一句（后端同一句话）
    { const why = notePrecondition('restructure', before); if (why) { toast(why); return } }
    if (!llmGate()) return
    // 之前复用 'skeleton'：打开一篇没骨架的笔记自动生成骨架时，「智能排版」也跟着转圈（实拍）
    setLoading('restructure')
    const ctrl = new AbortController()
    restructureAbortRef.current = ctrl
    try {
      const r = await api.restructureNote(current.id, title, before, intentText(intent), ctrl.signal)
      if (r.detail) toast(r.detail, 'error')
      if (!r.changed) { toast(r.detail ? '没有改动' : '结构已经很清楚了，没什么可调的'); return }
      const after = formatMarkdown(r.content)
      const v = editorViewRef.current
      if (!v) return
      // 等模型的这几秒里用户还能打字（排版不像 harness 那样锁编辑器）。minimalChange 算出来的
      // 位置是按请求前那份正文的，文档变过就会错位——宁可丢掉这次结果也不要弄坏正文（第 585 轮）
      if (v.state.doc.toString() !== before) {
        toast('排版期间正文改过了，这次结果没有应用——改完再点一次「智能排版」', 'error')
        return
      }
      // 只换变了的那一段：整篇替换会把之前各层提案的位置全映射到一个点上，账本就空了
      const change = minimalChange(before, after)
      if (change) v.dispatch({ changes: change })
      setContent(after)
      pushDiff('智能排版', before, after)
      const skipped = r.skipped.length ? `，跳过 ${r.skipped.length} 处` : ''
      toast(`调整了 ${r.ops} 处结构${skipped}，可以逐处接受或撤回`)
    } catch (e) {
      if ((e as Error).name === 'AbortError') toast('已停止智能排版，正文没动')
      else toast(`排版失败：${friendlyError(e)}`, 'error')
    } finally {
      restructureAbortRef.current = null
      setLoading('')
    }
  }
  function stopRestructure() { restructureAbortRef.current?.abort() }

  /** `/` 选中一项之后的入口。需要提示词的先弹输入框，其余的当场做完。 */
  /** 右栏托盘上的「从托盘写」：跟 `/` 菜单那一项同一件事——在光标处打开同一个输入框（可留空） */
  function writeFromTray() {
    const view = editorViewRef.current
    const item = SLASH_ITEMS.find((i) => i.key === 'tray')
    if (!view || !current || !item) return
    const at = view.state.selection.main.head
    const coords = view.coordsAtPos(at)
    view.focus()
    setSlash({ item, from: at, to: at, x: coords?.left ?? 200, y: (coords?.bottom ?? 200) + 6 })
  }

  function onSlash(item: SlashItem, from: number, to: number) {
    const view = editorViewRef.current
    const coords = view?.coordsAtPos(from)
    const at = { x: coords?.left ?? 200, y: (coords?.bottom ?? 200) + 6 }
    if (item.needsPrompt) { setSlash({ item, from, to, ...at }); return }
    if (item.key === 'table-image' || item.key === 'audio') {
      pickKind.current = item.key === 'audio' ? 'audio' : 'image'
      setSlash({ item, from, to, ...at })
      filePick.current?.click()
      return
    }
    if (item.key === 'voice') {
      setSlash(null)
      // 语音服务离线时别让用户录完一段才发现转不了：录音前就说
      if (asrOffline) { toast(`语音服务不可达（${asrOffline}），转写用不了；其它功能不受影响`, 'error'); return }
      void runVoice(from, to); return
    }
    // 其余（chart / eda）不需要提示词，直接跑
    setSlash({ item, from, to, ...at })
    void runBlock(item, from, to, '')
  }

  /** 语音输入：录一段、转写、把文字插到 `/` 的位置。
   *
   * 用一个独立的 MediaRecorder 而不是复用右侧那个 AudioRecorder 组件——那个的
   * 产出去向是"插到编辑器"或"存进知识库"，是面板上的常驻功能；这里是「在光标
   * 这个位置插一段」，位置信息只有这里有。状态走占位块，跟其他 AI 动作一致。 */
  async function runVoice(from: number, to: number) {
    const view = editorViewRef.current
    if (!view) return
    // **一次只录一段**（P23 #8，临界条件表 A 组「语音输入 × 重复点击」那个 ？）：
    // 原来录着的时候再 `/` → 语音输入，会起**第二个 MediaRecorder**——两个占位块、
    // 两条麦克风轨、两段各自转写各自往正文里插，而「停止」只停得了它自己那一个。
    // 判据守的是**有没有正在录的**（`voiceStopById`），不是某个按钮的禁用态：
    // 这一条路右键、`/`、探针都走得到，守在入口才守得住（P21「闸要守来源」）。
    if (voiceStopById.current.size > 0) {
      toast('已经在录一段了——先把正文里那个「录音中」停掉，再录下一段', 'error')
      return
    }
    const id = Math.random().toString(36).slice(2, 10)
    const push = (fx: StateEffect<unknown>) => editorViewRef.current?.dispatch({ effects: fx })
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (e) {
      toast(micError(e), 'error')
      return
    }
    const chunks: Blob[] = []
    const mr = new MediaRecorder(stream)
    mr.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data) }
    voiceStopById.current.set(id, () => { if (mr.state !== 'inactive') mr.stop() })
    view.dispatch({
      changes: { from, to, insert: '' },
      effects: startRun.of({ id, from, label: '语音输入' }),
    })
    push(patchRun.of({ id, phase: '录音中，点停止结束' }))
    mr.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop())
      voiceStopById.current.delete(id)
      push(patchRun.of({ id, phase: '转写中…' }))
      // P3 遗留（？）：录完之后「停止」原来只撤块，转写请求照跑、回来还往正文里插——挂上 AbortController
      const ctrl = new AbortController()
      runAborts.current.set(id, ctrl)
      try {
        const r = await api.transcribeOnly(new Blob(chunks, { type: 'audio/webm' }), 'recording.webm', ctrl.signal)
        if (ctrl.signal.aborted) return
        const text = (r.text || '').trim()
        if (!text) {
          push(patchRun.of({ id, error: '没听清，什么都没转出来', expanded: true }))
          return
        }
        const v = editorViewRef.current
        if (!v) return
        const run = v.state.field(runsField, false)?.find((x) => x.id === id)
        const at = Math.max(0, Math.min(run?.from ?? from, v.state.doc.length))
        const before = v.state.doc.toString()
        v.dispatch({ changes: { from: at, insert: text }, effects: endRun.of(id) })
        const after = v.state.doc.toString()
        setContent(after)
        pushDiff('语音输入', before, after)
      } catch (e) {
        if ((e as Error).name === 'AbortError') { toast('已停止，这段录音没有转写'); return }
        push(patchRun.of({
          id, error: `转写失败：${friendlyError(e)}`, expanded: true,
        }))
      } finally {
        runAborts.current.delete(id)
      }
    }
    mr.start()
  }

  /** 选完文件之后：图片走「识别里面的表格」，音频走「插入 + 自动转写」。
   *
   * 两个都不是"只插入"——`/` 菜单只放 AI 功能，纯插入的在顶部工具栏。
   * 状态同样走光标处的占位块，跟其他 AI 动作一致。 */
  async function onPickFile(files: FileList | null) {
    const f = files?.[0]
    const ctx = slash
    setSlash(null)
    const view = editorViewRef.current
    if (!f || !ctx || !view) return
    const id = Math.random().toString(36).slice(2, 10)
    const push = (fx: StateEffect<unknown>) => editorViewRef.current?.dispatch({ effects: fx })
    view.dispatch({
      changes: { from: ctx.from, to: ctx.to, insert: '' },
      effects: startRun.of({ id, from: ctx.from, label: ctx.item.label }),
    })
    const at = () => {
      const v = editorViewRef.current!
      const r = v.state.field(runsField, false)?.find((x) => x.id === id)
      return Math.max(0, Math.min(r?.from ?? ctx.from, v.state.doc.length))
    }
    try {
      if (ctx.item.key === 'table-image') {
        push(patchRun.of({ id, phase: '在看这张图里有没有表格…' }))
        // P3 遗留（？）：占位块「停止」原来只撤块，看图请求照跑、跑完仍插进正文——挂上 AbortController
        const ctrl = new AbortController()
        runAborts.current.set(id, ctrl)
        let r: Awaited<ReturnType<typeof api.tableFromImage>>
        try { r = await api.tableFromImage(f, ctrl.signal) } finally { runAborts.current.delete(id) }
        if (ctrl.signal.aborted) return
        if (!r.detected) {
          // 如实说没检测到，**不要硬塞一张空表进用户笔记**
          push(patchRun.of({
            id, expanded: true,
            error: '没有检测到表格' + (r.raw ? `（模型说：${r.raw.slice(0, 40)}）` : ''),
          }))
          return
        }
        const v = editorViewRef.current!
        const before = v.state.doc.toString()
        v.dispatch({ changes: { from: at(), insert: `\n${r.table}\n\n` }, effects: endRun.of(id) })
        const after = v.state.doc.toString()
        setContent(after)
        pushDiff('图片转表格', before, after)       // 识别结果一样可以接受/撤回
        return
      }
      // 音频：先传上去、**先把播放器插进正文**，再转写出文字稿。
      // P3 实拍：语音服务没开时，原来传完就去转写、转写失败整段跳到 catch——用户选的音频
      // 传上去了却没插进笔记，报错还指去「LLM 供应商」。播放器不需要语音服务，先落下来；
      // 转写是附赠的，失败只说转写没成。语音服务明知不可达时连转写请求都不发。
      push(patchRun.of({ id, phase: '上传中…' }))
      const a = await api.uploadAsset(f)
      push(logRun.of({ id, at: '已上传', text: `${a.name}（${Math.round(a.bytes / 1024)}KB）` }))
      const v = editorViewRef.current!
      const before = v.state.doc.toString()
      const player = `\n<audio controls src="${a.url}"></audio>\n\n`
      v.dispatch({ changes: { from: at(), insert: player } })
      setContent(v.state.doc.toString())
      if (asrOffline) {
        push(patchRun.of({ id, expanded: true, error: `音频已插入；语音服务不可达（${asrOffline}），这次没转写——在设置里检查语音服务地址` }))
        pushDiff('插入音频', before, v.state.doc.toString())
        return
      }
      push(patchRun.of({ id, phase: '转写中…' }))
      let text = ''
      // 转写这一步也挂 AbortController（P9，同语音输入）：占位块「停止」撤掉转写，播放器留着
      const tctrl = new AbortController()
      runAborts.current.set(id, tctrl)
      try {
        text = ((await api.transcribeOnly(f, f.name, tctrl.signal)).text || '').trim()
      } catch (e) {
        if ((e as Error).name === 'AbortError') { pushDiff('插入音频', before, editorViewRef.current!.state.doc.toString()); toast('已停止转写，音频留在正文里'); return }
        push(patchRun.of({ id, expanded: true, error: `音频已插入，转写没成：${friendlyError(e)}` }))
        pushDiff('插入音频', before, editorViewRef.current!.state.doc.toString())
        return
      } finally {
        runAborts.current.delete(id)
      }
      const v2 = editorViewRef.current!
      v2.dispatch({ changes: { from: at(), insert: text ? text + '\n\n' : '' }, effects: endRun.of(id) })
      const after = v2.state.doc.toString()
      setContent(after)
      pushDiff('插入音频', before, after)
      if (!text) toast('音频已插入，但转写没有出内容')
    } catch (e) {
      if ((e as Error).name === 'AbortError') { toast('已停止，什么都没插进正文'); return }
      push(patchRun.of({
        id, expanded: true,
        error: `处理失败：${friendlyError(e)}`,
      }))
    }
  }

  /** 跑一次块生成。
   *
   * **产出不往正文里流**：生成过程只在光标处那个占位块里预览，跑完才一次性
   * 落进正文。直接往文档里流的话，同时跑几个任务就会把文字交错插在一起；
   * 而且中途打分可能重写好几轮，流进去的是被推翻的版本。
   *
   * 落进正文之后同时算出 diff 交给「接受 / 撤回」，跟 harness 改动、右键润色
   * 走同一套处置方式。 */
  async function runBlock(item: SlashItem, from: number, to: number, prompt: string) {
    const view = editorViewRef.current
    if (!view || !current) return
    // custom 是「替换选中的这段」，其余是「在光标这里插一块」。两种都先把
    // [from,to) 清掉，产出落在 from。
    const selection = item.key === 'custom' ? view.state.doc.sliceString(from, to) : ''
    // 临界条件（P1-2-B1 / 2-B2）：空指令、空选区、超长、空白笔记——**不发请求、不清空选区**，说一句。
    // 输入框自己已经拦过空指令；这里是第二道（`/` 直接跑的那几项没有输入框）。
    // 正文要**去掉 `/查询词` 那几个字**再判空：空白笔记上打了一个 `/`，正文就不是空串了（实拍第一版漏过）
    const docWithoutSlash = item.key === 'custom' ? view.state.doc.toString()
      : view.state.doc.sliceString(0, from) + view.state.doc.sliceString(to)
    // 「从托盘写」（P14）：托盘空着开跑前就拦——跟别的临界条件同一条路，不发请求、不清空选区
    const why = blockPrecondition(item, prompt, selection, docWithoutSlash) || (item.key === 'tray' ? trayPrecondition(current.id) : '')
    if (why) {
      // `/查询词` 那几个字照样收掉（插入类），选区（custom）留着
      if (item.key !== 'custom' && to > from) view.dispatch({ changes: { from, to, insert: '' }, selection: { anchor: from } })
      setSlash(null)
      toast(why, 'error')
      return
    }
    if (!llmGate()) { if (item.key !== 'custom' && to > from) view.dispatch({ changes: { from, to, insert: '' }, selection: { anchor: from } }); setSlash(null); return }
    const id = Math.random().toString(36).slice(2, 10)
    const ctrl = new AbortController()
    runAborts.current.set(id, ctrl)
    retryArgs.current.set(id, { item, prompt })
    setSlash(null)                                   // 输入框收起，交给占位块

    view.dispatch({
      changes: { from, to, insert: '' },
      selection: { anchor: from },
      effects: startRun.of({ id, from, label: item.label }),
    })
    const before = view.state.doc.toString()
    const push = (fx: StateEffect<unknown>) => editorViewRef.current?.dispatch({ effects: fx })

    let lastError = ''
    try {
      const block = await api.composeBlock(
        { note_id: current.id, title, content: before, cursor: from,
          // 「从托盘写」走的是 prompt 模式 + from_tray（不是新的 block mode）；留空的指令后端按托盘材料写一段
          mode: (item.key === 'tray' ? 'prompt' : item.key) as api.BlockMode,
          prompt: item.key === 'tray' && !prompt.trim() ? '按托盘里摊开的材料写一段，每句话带材料的出处' : prompt,
          selection, from_tray: item.key === 'tray' },
        {
          onPhase: (label) => {
            push(patchRun.of({ id, phase: label }))
            push(logRun.of({ id, at: '阶段', text: label }))
          },
          onSkills: (d) => {
            push(logRun.of({ id, at: '技能', text: d.injected.length ? `带上 ${d.injected.join('、')}` : '这个范围没配技能' + (d.menu.length ? `，${d.menu.length} 条留给模型按需加载` : '') }))
          },
          onTools: (calls) => {
            for (const c of calls) {
              const args = Object.entries(c.args)
                .filter(([k]) => k !== 'limit')
                .map(([, v]) => String(v)).join(' / ')
              push(logRun.of({ id, at: '查', text: `${c.tool}${args ? '（' + args + '）' : ''}` }))
            }
          },
          onDelta: (t) => push(appendPreview.of({ id, text: t })),
          onEvaluate: (status, scores) => {
            const weak = Object.entries(scores ?? {}).filter(([, v]) => v.level < 2)
            push(logRun.of({
              id, at: '打分',
              text: status === 'complete' ? '都达标了'
                : weak.map(([k, v]) => `${dimLabel(k)}：${v.note}`).join('；') || status,
            }))
          },
          onError: (d) => { lastError = d; push(logRun.of({ id, at: '出错', text: d })) },
        },
        ctrl.signal)

      const v = editorViewRef.current
      if (!v) return
      const text = (block || '').trim()
      if (!text) {
        // 门槛拦下的（光标附近没数据）把原因写在占位块上，别只说「没有产出内容」
        push(patchRun.of({ id, error: lastError || '没有产出内容', expanded: true }))
        return                                       // 占位块留着，让用户看到为什么
      }
      // **形状不对就不落正文**（P31 #7）：实拍过 `/` 智能插图把整串
      // `{"text":…,"reason":…}` 写进正文、还进了目录和骨架。这一路上原来没有任何一层校形状，
      // 而「模型答得不对」跟「模型报错」是两回事——后者早就有人接，前者一直没有。
      // 判据宁可窄（见 `editor/blockShape`），拦下来的给一句人话 + 一个「重试」，产出留在预览里。
      const badShape = blockShapeProblem(item.key, text)
      if (badShape) {
        push(patchRun.of({ id, error: badShape, expanded: true, retry: true }))
        return
      }
      const run = v.state.field(runsField, false)?.find((r) => r.id === id)
      const at = Math.max(0, Math.min(run?.from ?? from, v.state.doc.length))
      // P17：替换类（custom）开跑时选区已经清掉了——diff 的基准要把它补回原位，不然「全部撤回」
      // 只撤掉新写的、原来选中的字就没了；行内替换也不补空行（`editor/blockLanding`，纯函数有测试）
      const b2 = diffBaseForBlock(v.state.doc.toString(), at, item.key, selection)
      v.dispatch({ changes: { from: at, insert: textToLand(item.key, text) }, effects: endRun.of(id) })
      const after = v.state.doc.toString()
      setContent(after)
      pushDiff(item.label, b2, after)
      // 结果落下来要看得见：跑了 100 秒出的图在折叠线下（实拍），把落点滚到视口上部
      requestAnimationFrame(() => editorViewRef.current?.dispatch({ effects: EditorView.scrollIntoView(at, { y: 'start', yMargin: 80 }) }))
    } catch (e) {
      if (ctrl.signal.aborted) {
        push(endRun.of(id))                          // 用户自己停的，不留残骸
      } else {
        // P3 实拍：占位块上原样写着 `Failed to fetch`——翻成人话（后端没起来 / 模型连不上各说各的）
        push(patchRun.of({ id, error: friendlyError(e), expanded: true }))
      }
    } finally {
      runAborts.current.delete(id)
    }
  }

  /** 占位块上的「停止」。 */
  function stopRun(id: string) {
    const rec = voiceStopById.current.get(id)
    if (rec) { rec(); return }        // 录音：停下来还要转写，不能直接撤掉占位块
    runAborts.current.get(id)?.abort()
    editorViewRef.current?.dispatch({ effects: endRun.of(id) })
  }

  /** 占位块上的「重试」：形状不对被拦下的那一次，原样再跑一遍（P31 #7）。
   *  落点用**现在**那个占位块的位置（文档可能已经被编辑过，`runsField` 一直在映射它）。 */
  function retryRun(id: string) {
    const again = retryArgs.current.get(id)
    const v = editorViewRef.current
    if (!again || !v) return
    const at = v.state.field(runsField, false)?.find((r) => r.id === id)?.from ?? 0
    retryArgs.current.delete(id)
    v.dispatch({ effects: endRun.of(id) })
    void runBlock(again.item, at, at, again.prompt)
  }

  /** 分屏的第二栏。真笔记可编辑（SplitEditor，自己自动保存）；主栏正开着的那篇只读；虚拟节点走 KbNoteView。
   *  **是函数不是组件**：写成 App 内部的组件的话每次 render 都是新类型，
   *  里面的 MarkdownEditor 会跟着重挂，滚动位置全丢。 */
  function renderSplit(id: string) {
    const note = notes.find((n) => n.id === id)
    const row = allRows.find((r) => r.note_id === id)
    const title = note ? displayTitle(note) : (factsLabel(id) ?? row?.title ?? id)
    return (
      <>
        <div className="split-head">
          <span className="split-title" title={title}>{title}</span>
          {note && <button className="icon-btn" title="在标签里打开" onClick={() => void switchTo(note)}><Icon n="bx-link-external" /></button>}
          <button className="icon-btn" title="关闭分屏" onClick={() => setSplit(null)}><Icon n="bx-x" /></button>
          {/* 右栏收起时那个「展开右栏」小钮是绝对定位在中栏右上角的，分屏一开正好压在「关闭分屏」上（第 198 轮实拍）——分屏时挪进这一行 */}
          {!rightShown && !focusMode && (
            <button className="icon-btn" title={`展开右栏（${fmtShortcut('⇧⌘\\')}）`} onClick={() => setPanes((p) => makeRoomForRight(p, winW, split?.w ?? 0))}><Icon n="bx-chevrons-left" /></button>
          )}
        </div>
        <div className="split-body">
          {api.isVirtualId(id)
            ? <Suspense fallback={<p className="muted" style={{ padding: 16 }}>…</p>}><KbNoteView id={id} rows={allRows} onOpen={(x) => openInSplit(x)}
                          onOpenNote={(nid) => { const n = notes.find((x) => x.id === nid); if (n) void switchTo(n) }}
                          onCite={current ? (fid, text) => insertAtCursor(`${text} [${fid}]`) : null} /></Suspense>
            : note
              ? (current?.id === note.id
                  // 同一篇在主栏也开着：这里只读，不然两边各存各的互相盖
                  ? <>
                      <p className="muted split-hint">这篇在主栏正开着，这里只看不改。</p>
                      {note.content.trim() ? <MarkdownEditor content={content} readOnly /> : <p className="muted">这篇还是空的。</p>}
                    </>
                  : <SplitEditor key={note.id} note={note} flushRef={splitFlush} onSaved={(n) => {
                      setNotes((prev) => prev.map((x) => (x.id === n.id ? n : x)))
                      void reloadTree(false)
                    }} />)
              : <p className="muted">这篇笔记已经不在了。</p>}
        </div>
      </>
    )
  }

  // ---------------------------------------------------------------- 渲染

  actionsRef.current = { runNoteHarness, runMagicTap, handleSelectionAction, runHarness, ingestCurrentNote, runBlock, dropIfStillEmpty, collapseAll, pushDiff, runSlides, onPickFile, restructureNote, runSkeleton, newNoteUnder, importMarkdown, runVoice, flushChangeLayers }

  return (
    <div className={'shell' + (focusMode ? ' focus-mode' : '')}>
      {treeMenu && (
        <ContextMenu
          at={treeMenu.at}
          items={api.isVirtualId(treeMenu.row.note_id) ? kbMenuItems(treeMenu.row) : treeMenuItems(treeMenu.row)}
          onClose={() => setTreeMenu(null)}
        />
      )}
      {tabMenu && (
        <ContextMenu at={tabMenu.at} items={tabMenuItems(tabMenu.tab)} onClose={() => setTabMenu(null)} />
      )}
      {noteLinkMenu && (
        <ContextMenu at={{ x: noteLinkMenu.x, y: noteLinkMenu.y }} onClose={() => setNoteLinkMenu(null)} items={[
          { kind: 'header', label: noteLinkMenu.title || '未命名' },
          { label: '摊到这篇桌上', icon: 'bx-layer-plus', hint: '放进托盘，写这篇时优先用它',
            onSelect: () => {
              const id = noteLinkMenu.id
              // 摘要要那篇的开头几百字：拉一次（`[[` 链接标记只带标题）
              void api.getNote(id)
                .then((n) => requestTrayAdd({ kind: 'note', ref_id: id, title: n.title || noteLinkMenu.title, excerpt: noteExcerpt(n.content) }))
                .catch(() => requestTrayAdd({ kind: 'note', ref_id: id, title: noteLinkMenu.title, excerpt: '' }))
            } },
          { label: '打开这篇', icon: 'bx-note', onSelect: () => window.dispatchEvent(new CustomEvent('open-note', { detail: noteLinkMenu.id })) },
        ]} />
      )}
      {tabListAt && (
        <ContextMenu at={tabListAt} onClose={() => setTabListAt(null)} items={[
          { kind: 'header', label: `打开的标签 · ${tabs.length}` },
          ...tabs.map((t): MenuItem => {
            const n = notes.find((x) => x.id === t.noteId)
            // 同名标签（三个「创业一年回顾」）光看名字分不开：给一截正文首行，跟 ⌘K 一样
            const dup = tabs.some((o) => o !== t && o.title === t.title)
            const snip = dup && n ? previewLine(n.content ?? '', t.title) : ''
            return {
              label: ellipsize(t.title || '未命名', 36) + (snip ? ' · ' + ellipsize(snip, 24) : ''), icon: n?.icon || (api.isVirtualId(t.noteId) ? 'bx-hash' : 'bx-note'),
              hint: t.id === activeTabId ? '当前' : undefined, onSelect: () => activateTab(t),
            }
          }),
          { kind: 'sep' },
          { label: '关闭其他', icon: 'bx-x', disabled: tabs.length <= 1, onSelect: () => closeTabsWhere((t) => t.id !== activeTabId) },
        ]} />
      )}
      {picker && <NotePicker req={picker} rows={tree} />}
      <input ref={importInput} type="file" accept=".md,.markdown,.txt" multiple style={{ display: 'none' }}
             onChange={(e) => { void importMarkdown(e.target.files, importUnder.current); e.target.value = '' }} />
      {quick && <QuickView note={quick} onClose={() => setQuick(null)} onOpen={(n) => void switchTo(n)} />}
      {prompt && <TextPrompt req={prompt} />}
      <Toaster />
      <CommandPalette onOpenNote={(id) => { const n = notes.find((x) => x.id === id); if (n) void switchTo(n); else void api.getNote(id).then((fresh) => switchTo(fresh)).catch(() => toast('这篇笔记不在了', 'error')) }} onInsertFact={insertAtCursor}
                      tabs={tabs.map((t) => ({ noteId: t.noteId, title: t.title, snip: previewLine(notes.find((n) => n.id === t.noteId)?.content ?? '', t.title) }))}
                      onOpenTab={(id) => activateTab(tabs.find((t) => t.noteId === id))} />
      {showShortcuts && <ShortcutsPanel onClose={() => setShowShortcuts(false)} />}
      {writingPlanParent && (
        <WritingPlanPanel
          parent={writingPlanParent}
          onClose={() => setWritingPlanParent(null)}
          onNoteChanged={() => { void reload(); void reloadTree() }}
          harness={harness}
          onRun={() => runHarness(writingPlanParent)}
          onToggleFollow={() => setHarness((h) => (h ? { ...h, follow: !h.follow } : h))}
          confirm={askConfirm}
        />
      )}
      {exportOne && (
        <div className="palette-backdrop" onMouseDown={() => setExportOne(null)}>
          <div className="palette export-one" role="dialog" aria-label="导回这一篇"
               onMouseDown={(e) => e.stopPropagation()}>
            <ExportNotePanel noteId={exportOne.id} title={displayTitle(exportOne)}
                             onClose={() => setExportOne(null)} />
          </div>
        </div>
      )}
      {/* 确认框必须排在写作计划面板之后：两者的遮罩同一层（z-index 200），谁在 DOM 里靠后谁在上面。
         排前面的话，面板上点「换个目标」弹出的确认框会被面板自己盖住（第 306 轮实拍）。 */}
      {confirmReq && <ConfirmDialog req={confirmReq} />}
      {/* 关掉面板不再停止 harness（见 HarnessState 注释）——这块是面板关着
         的时候唯一能看到"还在跑"的地方，点了直接重新打开对应文件夹的面板。 */}
      {harness?.running && !writingPlanParent && (
        <div
          className="card"
          style={{ position: 'fixed', right: 16, bottom: 16, zIndex: 60, width: 260, cursor: 'pointer' }}
          {...clickable(() => {
            // 从树里找回那一行——正在跑的 harness 只记了 id 和标题，而面板
            // 要的是完整的 TreeRow。找不到就不开（子树可能已经被删了）。
            const row = tree.find((r) => r.note_id === harness.folderId)
            if (row) setWritingPlanParent(row)
          })}
          title="点击打开写作计划面板"
        >
          <div className="row" style={{ gap: 6 }}>
            <span className="spinner" />
            <strong style={{ fontSize: 'var(--t-md)' }}><Icon n="bx-folder-open" /> {harness.folderName}</strong>
          </div>
          <p className="muted" style={{ fontSize: 'var(--t-sm)', margin: '4px 0 0' }}>
            {harness.currentSectionTitle ? `正在写：${harness.currentSectionTitle}` : '正在启动…'}
          </p>
        </div>
      )}

      <input
        ref={filePick}
        type="file"
        style={{ display: 'none' }}
        accept={pickKind.current === 'image' ? 'image/*' : 'audio/*'}
        onChange={(e) => { void onPickFile(e.target.files); e.target.value = '' }}
      />
      {slash?.item.needsPrompt && (
        <SlashPrompt
          key={`${slash.item.key}:${slash.from}:${slash.to}`}
          item={slash.item}
          x={slash.x}
          y={slash.y}
          busy={false}
          phase=""
          onRun={(p) => { void runBlock(slash.item, slash.from, slash.to, p) }}
          onCancel={() => setSlash(null)}
        />
      )}
      {selectionMenu && (
        <SelectionMenu
          x={selectionMenu.x}
          y={selectionMenu.y}
          busy={selectionBusy}
          onAction={handleSelectionAction}
          onStop={() => selectionAbortRef.current?.abort()}
          onClose={() => { if (!selectionBusy) setSelectionMenu(null) }}
        />
      )}
      {/* 标签行在最顶上、整行宽。macOS 的红绿灯落在左端 spacer 里，右端 filler
          是窗口拖动区（照 Trilium desktop_layout.tsx:71-95：窗口控件在左侧时
          标签行只占 rest-pane 就给不出位置，红绿灯会画到启动栏上）。 */}
      <div className="tab-bar">
        <div className="tab-row-left-spacer" />
        {/* 前进后退（TabHistoryNavigationButtons）。跳去看一篇再回来。 */}
        <span className="history-nav">
          <button className="icon-btn" disabled={!histState.back} title={`后退（${fmtShortcut('⌘[')}）`} onClick={() => goHistory(-1)}><Icon n="bx-left-arrow-alt" /></button>
          <button className="icon-btn" disabled={!histState.fwd} title={`前进（${fmtShortcut('⌘]')}）`} onClick={() => goHistory(1)}><Icon n="bx-right-arrow-alt" /></button>
        </span>
        <TabBar
          tabs={tabs}
          activeId={activeTabId}
          onSelect={(id) => activateTab(tabs.find((x) => x.id === id))}
          onClose={closeTab}
          onNew={newNote}
          onContextMenu={(tab, at) => setTabMenu({ tab, at })}
          iconOf={(noteId) => notes.find((x) => x.id === noteId)?.icon || undefined}
          onReorder={reorderTab}
          onListTabs={setTabListAt}
          menuTabId={tabMenu?.tab.id ?? null}
          busyIds={new Set([loading === 'note-harness' ? noteHarnessNoteId : null, harness?.running ? harness.currentNoteId : null].filter((x): x is string => !!x))}
        />
      </div>
      <div className="shell-main">
      {/* 启动栏 —— 照 Trilium 的 58px 竖排。放的是**跨笔记的入口**：
          知识库、Skill、无限续写、设置、用户。判据见 docs/product-north-star.md：
          记忆是一等公民，不该藏在某个按钮后面的弹层里。 */}
      <div className="launcher-pane">
        <div className="launcher-logo" title="MEMOKET NOTE"><Logo size={30} /></div>
        <button className="launcher-btn" title={`新建笔记（${fmtShortcut('⌘N')}）`} onClick={newNote}><Icon n="bx-plus" /></button>
        <button className="launcher-btn" title={`今天的日记（${fmtShortcut('⇧⌘D')}）：日记 / 年 / 月 / 日，没有就建`} onClick={() => void openToday()}><Icon n="bx-calendar-event" /></button>
        <button className="launcher-btn" title={`全局搜索：笔记 + 知识库（${fmtShortcut('⌘K')}）`}
                onClick={() => window.dispatchEvent(new CustomEvent('open-command-palette'))}><Icon n="bx-search" /></button>
        {/* 去处（导入 / 屏幕活动 / Skill / 设置）**从 `util/destinations` 生成**：
            这一份同时喂给 ⌘K（第 779 轮 / P21）。原来两处各写各的，于是屏幕活动
            和写作 Skill 在左栏有、在 ⌘K 里没有——而计划 §8.4 明写要有。
            加一个新去处只改那一个文件，两处同时出现。 */}
        {DESTINATIONS.filter((d) => d.where === 'top').map((d) => (
          <button key={d.id} className={'launcher-btn' + (virtualId === d.id ? ' active' : '')}
                  title={d.hint} onClick={() => void openVirtual(d.id, d.name)}><Icon n={d.icon} /></button>
        ))}
        <div className="launcher-spacer" />
        {/* 设置和 Skill 是「特殊笔记」：开标签、进中栏，跟别的笔记一样对待
            （照 Trilium：选项是隐藏子树里的笔记，不是弹层）。 */}
        {DESTINATIONS.filter((d) => d.where === 'foot').map((d) => (
          <button key={d.id} className={'launcher-btn' + (virtualId === d.id ? ' active' : '')}
                  title={d.hint} onClick={() => void openVirtual(d.id, d.name)}><Icon n={d.icon} /></button>
        ))}
        <button className={'launcher-btn left-pane-toggle' + (panes.leftOn ? '' : ' collapsed')}
                title={panes.leftOn ? '收起左栏（⌘\\）' : '展开左栏（⌘\\）'}
                onClick={() => setPanes((p) => ({ ...p, leftOn: !p.leftOn }))}><Icon n="bx-chevrons-left" /></button>
        {/* 用户头像放在最底下——对标 Trilium 启动栏底部的 GlobalMenu。 */}
        <UserSwitcher />
      </div>

      {/* 专注模式把左栏收起来——但启动栏留着：那是跨笔记的入口，收掉之后
          专注模式就等于「什么都点不到」。 */}
      {leftShown && (
      <div className="left-pane" style={{ width: leftW }}>
        {/* 左栏只放「找笔记」这一件事：快速搜索 + 树。
            标题、用户切换、新建、导入都挪进了启动栏——照 Trilium：左栏是
            导航，跨笔记的入口在启动栏。 */}
        {/* 快速搜索在树的上面——照 Trilium 的位置。 */}
        <div className="left-pane-search">
        <div className="quick-search">
          <Icon n="bx-search" />
          <input
            placeholder="快速搜索"
            title={`搜标题和正文；${fmtShortcut('⌘K')} 是全局搜索（含知识库）`}
            value={noteQuery}
            onChange={(e) => setNoteQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setNoteQuery('')
              // 回车开第一条命中（Trilium 的快速搜索也是），不用再伸手去点
              else if (e.key === 'Enter' && visibleNotes.length && noteQuery.trim()) { void switchTo(visibleNotes[0]); setNoteQuery('') }
            }}
          />
          {noteQuery && <button className="icon-btn" title="清空" onClick={() => setNoteQuery('')}><Icon n="bx-x" /></button>}
        </div>
        </div>
        {/* 列表自己的头一行：**你现在看的是什么、有多少**。
            视角开关第一版塞在搜索框里（第 622 轮），不对——`×` 属于输入框（它清的是
            你打的字），而视角开关作用的是**下面的列表**。当时还给它写了「有搜索词就
            隐藏」，那本身就是个信号：**需要躲开输入框，说明它不该在输入框里**
            （用户原话：「你这个切换视角的按钮放在搜索框里合适？」）。
            这一行顺带回答了应用一直没回答的一个问题：现在这一列是什么、多少条。 */}
        {/* 一篇笔记都没有时这一行整条收起来：**空列表没有「视角」可切**，
            而「0 篇」是新用户第一眼就看到的一句废话（第 643 轮全新用户实拍）。 */}
        {(notes.length > 0 || searchResults !== null || noteQuery) && (
        <div className="list-head">
          {searchResults !== null || noteQuery ? (
            <span className="muted">{visibleNotes.length} 条结果</span>
          ) : (
            <>
              <span className="seg">
                <button className={recentMode ? '' : 'on'} onClick={() => setRecentMode(false)}
                        aria-pressed={!recentMode} title="按你自己摆的层级">层级</button>
                <button className={recentMode ? 'on' : ''} onClick={() => setRecentMode(true)}
                        aria-pressed={recentMode} title="按最近改动，平铺">最近</button>
              </span>
              <span className="muted">{notes.length} 篇</span>
            </>
          )}
        </div>
        )}
        {/* 树的滚动容器——笔记一多，没有它树底部就被裁掉且滚不到 */}
        <div className="left-pane-body">
        {recentMode && searchResults === null && !noteQuery ? (
          /* 平铺、按最近改动。不画层级——跟搜索时同一条规矩（App 里那句
             「命中就该直接看到，不用先猜它在树的哪一层」）：这个模式回答的是
             「我最近动过哪几篇」，层级在这个问题里帮不上忙。
             `renderNoteItem` 每行本来就带「父文件夹 · 时间」，正好是这个模式要的。 */
          [...notes].sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? '')).map(renderNoteItem)
        ) : searchResults !== null || noteQuery ? (
          // 搜索时不画树：命中就该直接看到，不用先猜它在树的哪一层。
          visibleNotes.length === 0
            ? (
              /* 死路变去处：搜不到笔记不等于这个词在这儿没有东西——知识库里可能有一堆。
                 之前只在搜索框的 title 里提了一句「⌘K 是全局搜索（含知识库）」，
                 而用户读 tooltip 的时机恰好不是搜不到的这一刻（第 616 轮实拍：
                 搜「严亚」没有笔记，可知识库里关于严亚总的事实一大把）。 */
              <div className="muted" style={{ padding: '4px 2px', lineHeight: 1.7 }}>
                没有匹配的笔记。
                <br />
                <a href="#" onClick={(e) => {
                  e.preventDefault()
                  const q = noteQuery.trim()
                  setPendingKbQuery(q)                 // 还没挂载：它挂载时自取
                  window.dispatchEvent(new CustomEvent('kb-search', { detail: q }))  // 已经开着：直接收
                  void openVirtual('kb', '知识库')
                }}>到知识库里搜「{noteQuery.trim().slice(0, 12)}」 →</a>
              </div>
            )
            : visibleNotes.map(renderNoteItem)
        ) : (
          <NoteTree
            rows={allRows}
            menuRowId={treeMenu?.row.id ?? null}
            activeNoteId={current?.id ?? virtualId}
            onOpen={openFromTree}
            /* 树上只剩真笔记可以展开：知识库现在是一行入口，下钻在它自己那一页里 */
            onToggle={(row) => { if (!api.isVirtualId(row.note_id)) void toggleTreeNode(row) }}
            onDelete={(row) => { const n = notes.find((x) => x.id === row.note_id); if (n) void removeWithSubtree(n, row) }}
            locateTick={locateTick}
            onRename={(row) => void renameNode(row)}
            onNewChild={(row) => void newNoteUnder(row.note_id)}
            onDrop={(d, t, w) => void dropNode(d, t, w)}
            onFilesDrop={(files, t) => void importMarkdown(files, t?.note_id ?? api.ROOT_ID)}
            onContextMenu={(row, at) => setTreeMenu({ row, at })}
          />
        )}
        </div>
        {/* 底部浮动工具条（note_tree.ts:113-121）：定位到当前笔记 / 折叠全树。
            「定位」我们尤其需要——克隆意味着同一篇在树上有多处。 */}
        {searchResults === null && !noteQuery && (
        <div className="tree-actions">
          <button className="icon-btn" title="定位到当前笔记" onClick={() => setLocateTick((v) => v + 1)}><Icon n="bx-crosshair" /></button>
          <button className="icon-btn" title="折叠全部" onClick={() => void collapseAll()}><Icon n="bx-collapse-vertical" /></button>
        </div>
        )}
      </div>
      )}

      {leftShown && (
        <Gutter side="left" onResize={(dx) => setPanes((p) => ({ ...p, leftW: Math.max(150, Math.min(600, p.leftW + dx)) }))} />
      )}

      <div className="rest-pane">
        {/* 这一支在 `!split` 里，所以腾地方时分屏宽度按 0 算 */}
        {!rightShown && !focusMode && !split && (
          <button className="right-pane-reopen" title={`展开右栏（${fmtShortcut('⇧⌘\\')}）`}
                  onClick={() => setPanes((p) => makeRoomForRight(p, winW, 0))}><Icon n="bx-chevrons-left" /></button>
        )}
        <div className="center-pane">
        <div className={'note-pane' + (focusMode ? ' focus' : '')}>
        {/* 标题行固定在滚动区之上（Trilium 的 title-row 是 ScrollingContainer
            的兄弟，50px）。跟正文一起滚走的标题，滚到下面就不知道在写哪篇。 */}
        {current && (
          <div className="title-row">
            {/* 图标可点：挑一个当这篇的标识（Trilium 的 NoteIcon）。树、标签、标题行三处同一个 */}
            <button type="button" className="title-icon-btn" title="换个图标" aria-label="换个图标" aria-haspopup="dialog" aria-expanded={iconPicker} ref={iconBtnRef} onClick={() => setIconPicker((v) => !v)}>
              <Icon className="title-icon" n={current.icon || ((tree.find((r) => r.note_id === current.id)?.child_count ?? 0) > 0 ? 'bx-folder' : 'bx-note')} />
            </button>
            {iconPicker && (
              <IconPicker current={current.icon ?? ''} onClose={() => { setIconPicker(false); iconBtnRef.current?.focus() }}
                          onPick={(ic) => { setIconPicker(false); iconBtnRef.current?.focus(); void api.setNoteIcon(current.id, ic).then((n) => {
                            setCurrent((c) => (c && c.id === n.id ? { ...c, icon: n.icon } : c))
                            setNotes((prev) => prev.map((x) => (x.id === n.id ? { ...x, icon: n.icon } : x)))
                            void reloadTree(false)
                          }).catch((e) => toast('换图标失败：' + friendlyError(e), 'error')) }} />
            )}
            {/* 标题是占位词（「未命名」）时输入框显示空、把正文首行放在占位符里——
                跟树和标签用同一个 displayTitle，一篇笔记不再有两个名字 */}
            <input aria-label="笔记标题"
              className="note-title"
              value={isPlaceholderTitle(title) ? '' : title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={displayTitle({ title: '', content }) === '未命名' ? '标题' : displayTitle({ title: '', content })}
            />
            {saveStatus && (
              <span key={saveStatus.at} className={'save-status' + (saveStatus.error ? ' error' : '')}
                    title={saveStatus.error ?? undefined}>
                {saveStatus.error ? '⚠ 没存上' : '已保存'}
              </span>
            )}
          </div>
        )}
        {/* 这篇要干什么（P9，agent-native-editor §3.1）：标题下面常驻一行，所有 AI 动作的前提。
            专注模式收起——那会儿只剩正文。 */}
        {current && !focusMode && (
          <DocIntentRow intent={intent} onChange={saveIntent}
            checks={doneChecksSum}
            onOpenChecks={() => setPaneFocus({ id: 'plan', n: Date.now() })} />
        )}
        {/* ribbon —— 这篇笔记的元数据。第一件放进来的是**写作骨架**：
            判据 3 说「自主规划、自主执行、检查结果」，那**计划就得看得见**，
            跟正文一起，而不是右栏某个要切过去才有的面板。把计划藏起来，
            用户能看到的就只剩一个转圈的指示器，那等于什么都没说。 */}
        {current && (
          <Ribbon
            noteKey={current.id}
            defaultOpen={(() => { const pr = (new URLSearchParams(location.search).get('probe') ?? '').split(';;')[0]; return pr === 'kb-tab' || pr.startsWith('notekb:') ? 'cites' : pr === 'history-open' ? 'history' : pr.startsWith('ribbon:') ? pr.slice(7) : pr.startsWith('blank:ribbon:') ? pr.slice(13) : (/^note:[^:]+:ribbon:([^:]+)/.exec(pr)?.[1]) })()}
            tabs={[{
              /* **不给 activate**：它是全应用唯一一个，等于每开一篇笔记都把
                 13 个钮的工具条强行摊开——而 Ribbon 自己的注释写的是
                 「收起是默认：正文才是主角」。标题和正文之间原来叠着三条控件带
                 （页签 / 工具条 / 浮动按钮），这是最容易去掉的一条。
                 排版入口没少：`/` 斜杠菜单、选中弹出的菜单、⌘B 这些键都在，
                 想要常驻工具条的人点一次「格式」，**换笔记也记着**（第 704 轮）。 */
              id: 'format', title: '格式', icon: 'bx-text',
              body: (
                <MarkdownToolbar
                  viewRef={editorViewRef}
                  onFormat={formatNote}
                  onRestructure={restructureNote}
                  onStopRestructure={stopRestructure}
                  restructuring={loading === 'restructure'}
                />
              ),
            }, {
              id: 'cites', title: '引用', icon: 'bx-link',
              badge: citedIds.length || undefined,
              body: <NoteKbPanel
                citedIds={citedIds}
                row={tree.find((r) => r.note_id === current.id)}
                noteId={current.id}
                onOpenNote={(id) => { const n = notes.find((x) => x.id === id); if (n) void switchTo(n) }}
                onIngest={ingestCurrentNote}
                onSync={() => void syncNoteToKb(current.id)}
                ingesting={loading === 'ingest' || !!job}
                empty={!content.trim()}
                onStripMissing={stripCitationIds}
                refreshTick={ingestTick}
              />,
            }, {
              id: 'links', title: '链接', icon: 'bx-link-alt',
              badge: linkedNoteIds(content).length || undefined,
              body: <NoteLinksPanel noteId={current.id} content={content}
                                    onOpen={(id) => { const n = notes.find((x) => x.id === id); if (n) void switchTo(n) }}  onUnlink={unlinkNotes} knownIds={noteIdSet} knownNotes={notes} updatedAt={current.updated_at} />,
            }, {
              id: 'history', title: '历史', icon: 'bx-history',
              body: <RevisionHistoryPanel noteId={current.id} currentChars={wordCount(content)} currentContent={content} updatedAt={current.updated_at}
                                          onRestored={(n) => { setCurrent(n); setTitle(n.title); setContent(n.content); liveContentRef.current = n.content; void reload() }} />,
            }, {
              id: 'paths', title: '路径', icon: 'bx-git-branch',
              badge: (tree.find((r) => r.note_id === current.id)?.branch_count ?? 1) > 1
                ? tree.filter((r) => r.note_id === current.id).length : undefined,
              body: <NotePathsPanel noteId={current.id} rows={tree}
                                    onOpen={(id) => { const n = notes.find((x) => x.id === id); if (n) void switchTo(n) }}
                                    onClone={() => { const row = tree.find((r) => r.note_id === current.id); if (row) void cloneNodeTo(row) }} />,
            }, {
              id: 'info', title: '信息', icon: 'bx-info-circle',
              body: <NoteInfoPanel note={current} content={content} row={tree.find((r) => r.note_id === current.id)} />,
            },
            /* **日记那一篇多一块「屏幕活动」**（计划 §8.4，第 779 轮 / P21 补上）：
               摘要 + 一条进去的链接，**不把机器写的内容塞进用户的正文**。
               只在日记树上「某一天」那一层出现——别的笔记没有「这一天」可言。
               `journalDateOf` 的年份从树上读，不拿今天的年份凑：翻到去年那篇
               日记时查一个不存在的日子，页面会写「这一天没有记录」，
               那比不显示更糟（它看起来像个事实）。 */
            ...(journalDay
              ? [{ id: 'journey', title: '屏幕活动', icon: 'bx-desktop',
                   body: <JourneyRibbonPanel date={journalDay} /> }]
              : [])] as RibbonTab[]}
          />
        )}
        <div className={'note-scroll' + (current ? ' has-composer' : '')}>
        <div className="note-body">

        {!current ? (
          virtualId === 'app:import' ? (
            <div className="kb-note" style={{ maxWidth: 760 }}>
              <h2 className="kb-note-title"><Icon n="bx-import" /> 导入</h2>
              <div className="card">
                <b>Markdown 文件</b>
                <p className="muted" style={{ margin: '2px 0 8px', fontSize: 'var(--t-sm)' }}>一个文件一篇；多个文件成一棵子树。想放到某个节点下面，在树上右键那个节点「导入 .md 到这里…」。</p>
                {/* **这张卡原来是整页唯一一条到不了知识库的路**，而知识库空态页上
                    那个主按钮「导入」正是把人送到这一页最上面（第 678 轮）。默认
                    仍然只建笔记（迁移笔记的人不该被动花模型钱），但得说出来，
                    而且要在原地给得到。 */}
                {/* `.row` 会 flex-wrap——说明长了勾选框就被甩到上一行、文字掉到下面
                    （第 685 轮实拍）。勾选框不参与换行，文字自己在旁边折行。 */}
                <label className="checkbox-row" style={{ fontSize: 'var(--t-sm)', margin: '0 0 8px' }}>
                  <input type="checkbox" checked={mdToKb} onChange={(e) => setMdToKb(e.target.checked)} />
                  <span>同时存入知识库（逐篇抽事实，要跑模型；不勾就只建笔记，之后也能对单篇「存入知识库」）</span>
                </label>
                <input aria-label="选择 Markdown 文件" type="file" accept=".md,.markdown,.txt" multiple onChange={(e) => { void importMarkdown(e.target.files, api.ROOT_ID, mdToKb); e.target.value = '' }} />
              </div>
              <MemoryPanel pendingJob={job} trayNoteId={trayTarget} />
            </div>
          ) : virtualId === 'app:settings' ? (
            <div className="kb-note"><h2 className="kb-note-title"><Icon n="bx-cog" /> 设置</h2><SettingsPanel embedded /><h3 className="kb-section-title">个人偏好</h3><PreferencesPanel /><AboutLine /></div>
          ) : virtualId === 'app:skills' ? (
            <div className="kb-note" style={{ maxWidth: 900 }}><h2 className="kb-note-title"><Icon n="bx-extension" /> 写作 Skill</h2><SkillsPanel embedded /></div>
          ) : virtualId === 'app:journey' ? (
            <Suspense fallback={<p className="muted" style={{ padding: 16 }}>…</p>}>
              <JourneyPage onLater={() => { if (activeTabId) closeTab(activeTabId) }}
                           onOpenNote={(id) => { void reload().then(() => api.getNote(id).then((n) => switchTo(n)).catch(() => {})) }}
                           onOpenJournal={(d) => void openToday(d)} />
            </Suspense>
          ) : virtualId === 'app:trash' ? (
            <div className="kb-note" style={{ maxWidth: 760 }}><h2 className="kb-note-title"><Icon n="bx-trash" /> 最近删除</h2>
              <TrashPanel onRestored={(id) => { void reload(); void reloadTree(); void api.getNote(id).then((n) => switchTo(n)).catch(() => {}) }} /></div>
          ) : virtualId ? (
            <Suspense fallback={<p className="muted" style={{ padding: 16 }}>…</p>}><KbNoteView
              id={virtualId}
              rows={allRows}
              onOpen={(id) => void openVirtual(id)}
              onOpenNote={(id) => { const n = notes.find((x) => x.id === id); if (n) void switchTo(n) }}
              onCite={null}
            /></Suspense>
          ) : (
            <WelcomePane
              notes={notes}
              factCount={kbRows.find((r) => r.note_id === 'kb')?.fact_count ?? 0}
              onNew={() => void newNote()}
              onImport={() => void openVirtual('app:import', '导入')}
              onOpen={(id) => void openVirtual(id)}
              onOpenNote={(n) => void switchTo(n)}
              onShortcuts={() => setShowShortcuts(true)}
            />
          )
        ) : (
          <>
            {/* 浮动按钮（Trilium FloatingButtons）：AI 能力跟正文在一起、不占正文的行。
                判据 1「一个能力一个按钮」：续写、智能续写各一个；打磨和「逐轮我来定」是
                智能续写的参数，收在它的 ▾ 里；录音一个麦克风两个去处；⋯ 是杂项。 */}
            <div className="floating-buttons">
              {/* 跑的过程中的状态，放在「续写」左边（用户第 767 轮指定的位置）。
                  这一排是 `height: 0` 的浮层，所以它不占正文的行——这正是它从
                  `.harness-sticky` 搬过来的理由。原来那句「正文由 AI 接管，停下来再改」
                  收进 `title`：它是解释，不是每秒都要读的东西。 */}
              {loading === 'note-harness' && !pausedRun && noteHarnessStatus && (
                <span className="fb-status muted" title={noteHarnessStatus + '\n运行中正文由 AI 接管，停下来再改'}>
                  <span className="spinner" /><span className="fb-status-text">{noteHarnessStatus}</span>
                </span>
              )}
              <button className={'fb-btn primary' + (loading === 'tap' ? ' running' : '')} onClick={runMagicTap}
                      disabled={loading === 'note-harness'}
                      title="续写：先查知识库，据此往下写一段（流式）">
                <Icon n={(loading === 'tap' ? 'bx-stop' : 'bx-edit-alt')} /><span className="fb-label">{loading === 'tap' ? '停止' : '续写'}</span>
              </button>
              <span className="fb-split">
                <button className={'fb-btn secondary' + (loading === 'note-harness' ? ' running' : '')}
                        onClick={() => runNoteHarness('write')} disabled={loading === 'tap' || isSlides(content)}
                        title={isSlides(content) ? '这一篇是幻灯片——接散文会把分页和引用弄乱；要改内容回原笔记改完再重做一份'
                          : '智能续写：自动修订 + 自动续写交替，直到相对骨架已经完整才停'}>
                  <Icon n={(loading === 'note-harness' ? 'bx-stop' : 'bx-bot')} /><span className="fb-label">{loading === 'note-harness' ? '停止' : '智能续写'}</span>
                </button>
                <button className="fb-btn secondary fb-caret-btn" title="打磨 / 逐轮我来定"
                        onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); setFbMenu({ kind: 'harness', at: { x: r.right - 220, y: r.bottom + 4 } }) }}>
                  <Icon n="bx-chevron-down" />
                </button>
              </span>
              <AudioRecorder onTranscript={insertAtCursor} onIngested={setJob} offline={asrOffline} noteId={current?.id} />
              <button className="fb-btn" title="更多"
                      onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); setFbMenu({ kind: 'more', at: { x: r.right - 220, y: r.bottom + 4 } }) }}>
                <Icon n="bx-dots-horizontal-rounded" />
              </button>
              {/* 跑得久的动作要有反馈（第 733 轮）。`BUSY_LABEL` 只列真会让用户等的；
                  续写 / 智能续写自己会把按钮变成「停止」，不在这里重复一遍。 */}
              {BUSY_LABEL[loading] && (
                <span className="fb-busy muted"><span className="spinner" /><span>{slidePhase || BUSY_LABEL[loading]}</span>
                  {/* 做幻灯片有 abortRef 却一直没有停止钮（P3：模型卡住时要等满 600 秒） */}
                  {loading === 'slides' && <button className="linklike link" style={{ marginInlineStart: 6 }} onClick={() => abortRef.current?.abort()}>停止</button>}
                </span>
              )}
              {fbMenu && (
                <ContextMenu at={fbMenu.at} onClose={() => setFbMenu(null)} items={fbMenu.kind === 'harness' ? [
                  { label: '打磨（只修不写）', icon: 'bx-brush', disabled: loading === 'note-harness' || !content.trim(),
                    hint: !content.trim() ? '正文是空的' : undefined, onSelect: () => { void runNoteHarness('polish') } },
                  { kind: 'sep' },
                  { label: reviewEachRound ? '逐轮我来定：开' : '逐轮我来定：关', icon: reviewEachRound ? 'bx-checkbox-checked' : 'bx-checkbox',
                    hint: '每轮停下来等你逐条接受/撤回', disabled: loading === 'note-harness',
                    onSelect: () => setReviewEachRound((v) => !v) },
                ] : [
                  { label: '存入知识库', icon: 'bx-brain', disabled: !content.trim() || loading === 'ingest' || !!job,
                    hint: !content.trim() ? '正文是空的' : job ? '正在存入知识库中' : undefined, onSelect: () => void ingestCurrentNote() },
                  /* 无限续写：**不在标题行上常驻**（用户第 625 轮：「无限续写的按钮不要显示了行吗？」）。
                     收进这里而不是只留树上右键——右键是「知道了才会去用」的地方，不承担发现；
                     这个菜单至少是看得见的一个入口。作用域仍然是当前这篇：分段会建成它的子笔记。 */
                  /* 幻灯片上不给：它是**原笔记的一种形态**，往里塞散文分段既破坏
                     `---` 分页、也回不到原笔记（方案里「不做反向同步」那条）。
                     实拍撞到过——探针在幻灯片那篇上打开了写作计划弹层。 */
                  { label: '无限续写…', icon: 'bx-rocket', disabled: isSlides(content),
                    hint: isSlides(content) ? '这一篇是幻灯片——要改内容回原笔记改完再重做一份'
                      : '给一个目标，拆成若干分段，每段建成这篇的子笔记',
                    onSelect: () => { const row = tree.find((r) => r.note_id === current.id); if (row) setWritingPlanParent(row) } },
                  /* 痛点 6：「想做成 PPT，又要上传给另一个 agent 工具，两个工具之间没有链接」。
                     **产物是一篇笔记不是一个文件**——落成这篇的子笔记，于是能 ⌘K 找到、
                     能挂引用、能被续写继续改、能导出。导出成 PDF 是第二步。 */
                  { label: '做成幻灯片…', icon: 'bx-slideshow', disabled: !content.trim() || loading === 'slides',
                    hint: !content.trim() ? '正文是空的' : '落成这篇的子笔记，每页带着它的引用编号',
                    onSelect: () => { void runSlides('points') } },
                  /* 只有这篇真是幻灯片时才给这一项——普通笔记上「导出幻灯片」是句空话。
                     零新依赖：主进程在离屏窗口里 printToPDF（方案 §落点「导出」那一行）。 */
                  ...(isSlides(content) && window.memoketDesktop?.slidesToPdf ? [{
                    label: '导出这份幻灯片 → PDF', icon: 'bx-file-blank',
                    hint: `${slidePages(content).length} 页，16:9`,
                    onSelect: () => { void exportSlidesPdf() },
                  }] : []),
                  { label: '分屏对照另一篇…', icon: 'bx-columns', onSelect: () => { void askNode('在右侧分屏打开哪一篇？', new Set([current.id])).then((id) => { if (id && id !== api.ROOT_ID) openInSplit(id) }) } },
                  { kind: 'sep' },
                  { label: '现在存一版', icon: 'bx-bookmark-plus', hint: '历史版本在 ribbon「历史」里', disabled: !content.trim(),
                    onSelect: () => { void save().then(() => api.snapshotNote(current.id)).then(() => toast('已存一版')).catch((e) => toast('存版失败：' + friendlyError(e), 'error')) } },
                  { label: '导出为 .md', icon: 'bx-export', onSelect: exportMarkdown },
                  /* 单篇导回。后端和 api 层本来就收 note_ids，一直缺的只是这个入口
                     （用户第 628 轮：「每一个 note，导出到 Notion/Obsidian/Feishu 的按钮没有」）。 */
                  { label: '导回到 Obsidian / Notion / 飞书…', icon: 'bx-share',
                    /* **这句话原来是不准的**：只有 Obsidian 是按文件里的 memoket_id 认，
                       Notion / 飞书认的是这台机器上记着的那一篇（`note_remotes.remote_id`）。
                       差别是实的：换台机器导，Notion / 飞书会新建一份而不是覆盖。 */
                    hint: '覆盖对方那边的同一篇（Obsidian 按文件里的 id 认，Notion / 飞书按这台机器记着的认）',
                    onSelect: () => setExportOne(current) },
                  { label: '导出全部笔记…', icon: 'bx-package', hint: '整库打成 Markdown zip', onSelect: () => window.dispatchEvent(new CustomEvent('export-all')) },
                  { label: '复制正文', icon: 'bx-copy', onSelect: () => void copyMarkdown() },
                  { kind: 'sep' },
                  { label: '正文怎么写', icon: 'bx-help-circle',
                    hint: 'Markdown 语法、```mermaid 画图、[[ 链笔记、@ 引事实',
                    onSelect: () => setShowShortcuts(true) },
                  { label: focusMode ? '退出专注模式' : '专注模式', icon: 'bx-fullscreen', shortcut: '⌘.', onSelect: () => setFocusMode((v) => !v) },
                  { label: '保存', icon: 'bx-save', shortcut: '⌘S', onSelect: () => void save() },
                ]} />
              )}
            </div>
            {/* **底部 composer**（第 714 轮，用户：「你续写智能续写音频入口那一行真的很奇怪」）。
                原来这一排浮在正文右上角，压着要写字的第一行，五个控件三种形状。
                搬到正文底部做成一条胶囊——构造照 0.5.10 的 `.home-ask-dock` +
                `.home-composer`（docs/MEMOKET_DESKTOP_0.5.10.md）。
                顺带补上了一个本来只藏在 `/` 菜单里的入口：**直接说要写什么**。
                动作一个没丢，只是重新排了：输入框空着时主钮是「续写」，
                写了字就变成「发送」（走跟 `/` 的「用 AI 写」同一条路）。 */}
            {/* 暂停 / 运行 / 结果 一条粘在浮动按钮下面的横条：轮末暂停时用户多半已经
                滚到正文底部看新写的内容，两个按钮和那句话如果留在正文顶部就等于没有
                （实拍：只剩状态栏一个「等你处置」）。 */}
            {/* 文件夹 harness 写到当前这篇时也给一条——不然编辑器忽然打不了字，没有任何解释 */}
            {!pausedRun && loading !== 'note-harness' && harness?.running && harness.currentNoteId === current?.id && (
              <div className="harness-sticky">
                <p className="muted harness-line"><Icon n="bx-bot" /> <span style={{ flex: 1, minWidth: 0 }}>
                  「{harness.folderName}」的写作计划正在写这一篇{harness.currentSectionTitle ? `（${harness.currentSectionTitle}）` : ''}
                </span>
                  <span className="muted" style={{ marginInlineStart: 8, fontSize: 'var(--t-xs)' }}>· 正文由 AI 接管，停下来再改</span>
                </p>
              </div>
            )}
            {/* **跑的过程中这条横条不再出现**（用户第 767 轮：「你这样搞挡着编辑板了」）。
                它 `position: sticky` 粘在浮动按钮带下面，于是整轮几十秒里一直压着正文的
                第一行——而同一句话另外两个地方也在显示（右栏「Agent 运行」、底部状态栏），
                这里是第三份。跑的过程改到 `.fb-status` 那个胶囊里，跟「停止」并排、
                `height: 0` 不占正文的行。
                **留下来的两种都是「等你动手」**：轮末暂停（两个按钮）和跑完（一句话 + 关闭），
                那两种本来就该停在你眼前。 */}
            {(pausedRun || (harnessDone && noteHarnessStatus)) && (
              <div className="harness-sticky">
                <p className="muted harness-line"><Icon n="bx-bot" /> <span style={{ flex: 1, minWidth: 0 }}>{pausedRun ? '这一轮写完了，逐条看过之后：' : noteHarnessStatus}</span>
                  {pausedRun && (
                    /* 轮末暂停：这一轮写完了，等你在正文里逐条接受/撤回。
                       关掉这个开关的话是原来的行为——一口气跑完再处置，而那意味着
                       你在跑的过程中做的处置会被下一轮盖掉。 */
                    <span className="row" style={{ gap: 6, marginInlineStart: 8 }}>
                      <button className="primary" onClick={() => resumePausedRun()}><Icon n="bx-play" /> 接着写</button>
                      <button onClick={() => resumePausedRun(true)}>到此为止</button>
                    </span>
                  )}
                  {harnessDone && !pausedRun && <button className="icon-btn sm" title="关闭" onClick={() => { setHarnessDone(false); harnessDoneRef.current = false; setNoteHarnessStatus('') }}><Icon n="bx-x" /></button>}
                </p>
              </div>
            )}

            {tapMeta && <TapProvenance meta={tapMeta} notes={tapNotes}
                                       onDismiss={() => { setTapMeta(null); setTapNotes([]) }} />}
            {/* 整篇缩进了 4 格以上（从别处粘来的常见）：markdown 会把它整个当成代码块，
                标题不是标题、一片等宽字。给一键去缩进，别让人自己猜为什么渲染不对。 */}
            {current && content.length > 40 && stripCommonIndent(content) !== content && (
              <p className="muted harness-line" style={{ marginBottom: 8 }}>
                <Icon n="bx-info-circle" /> 这篇整体缩进了，Markdown 会把它当成一整块代码，标题和列表都显示不出来。
                <button className="chip" style={{ marginInlineStart: 8 }} onClick={formatNote}><Icon n="bx-align-left" /> 去掉缩进</button>
              </p>
            )}

            {/* **上边距别写在 style 里**（P31 #2）：内联样式压得过 styles.css 里
                `.note-body > .floating-buttons + :not(.md-editor)` 那条让位规则，于是这一条
                只让了 2px，而浮动按钮 28px 高、sticky 不占高度——实拍按钮盖住这条的第一行
                右半截（「按层处置（保留第一次改的、放弃第三次的）」整句看不见）。
                P17 #4 量的是出处条（`tap-prov`，没有内联 margin），这条一直没修到；
                而 `/` 块、右键动作跑完出的正是这一条，是最常见的那个。 */}
            {pendingDiff > 0 && (
              <div
                className="row pending-diff-bar"
                style={{
                  gap: 8, alignItems: 'center',
                  fontSize: 'var(--t-sm)', padding: '5px 8px', borderRadius: 'var(--r-sm)',
                  border: '1px solid var(--line)', background: 'var(--panel)',
                }}
              >
                <span style={{ color: 'var(--ins)' }}>●</span>
                <span>改了 {pendingDiff} 处</span>
                {/* **关掉就定稿了，得先说一句**（P37 #5 / P35 #9）：这一层活在编辑器状态里，
                    一行都不落库（P37 量过 `note_revisions` / `harness_runs`，见台账）。
                    用户关掉 app 再打开，高亮没了、正文留着——**等于替他按了「全部接受」**，
                    而界面上还摆着「全部接受 / 全部撤回」两个钮，读起来像「有个决定等你做」。
                    落库是下一批的事；在那之前，至少不许它是静悄悄的。 */}
                <span className="muted">鼠标移到改动上可以逐处接受、撤回；<a href="#" onClick={(e) => { e.preventDefault(); setPaneFocus({ id: 'changes', n: Date.now() }) }}>按层处置</a>（保留第一次改的、放弃第三次的）。<strong>关掉这个 app 再打开，这些改动还挂在这儿</strong>——你逐处按下去的接受 / 撤回也留着。</span>
                <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                  <button onClick={acceptAllDiff}>全部接受</button>
                  <button onClick={rejectAllDiff} title="把这一轮改的全部还原成改之前的样子">
                    全部撤回
                  </button>
                </span>
              </div>
            )}
            <MarkdownEditor
              content={content}
              // **不是裸 `setContent`**（P70 B）：编辑器报上来的每一次改动都要在
              // `servedRef` 上记一笔「用户动过」，护栏靠它区分「用户自己删的」和
              // 「React 那边的镜像落后了」。回声不走这条（`editor/syncEcho.ts` 挡住了）。
              onChange={onEditorChange}
              // AI 在写的时候锁住编辑器：这时手改的字会被轮末的服务端正文盖掉（同步是
              // 服务端权威）。逐轮暂停、跑完、停止都会解锁。
              // 文件夹 harness 正在写的那篇也只读：它跟单篇那条一样在逐块往正文里写，
              // 用户这时候打的字会跟 AI 的写入互相打断，轮末服务端正文一对齐就没了（第 584 轮）
              readOnly={loading === 'note-harness' || loading === 'tap'
                || (!!harness?.running && harness.currentNoteId === current?.id)}
              scrollPad
              revisions={revisions}
              onAcceptInline={acceptRevision}
              roundDiff={roundDiff}
              undoGroup={undoGroup}
              onPendingDiff={setPendingDiff}
              onLayersChanged={onLayersChanged}
              onSelectionContextMenu={(x, y, text) => setSelectionMenu({ x, y, text })}
              onCursorParagraph={setCursorPara}
              marginMarks={marginMarks}
              onMarginClick={(m, anchor, reason) => { if (!m || !anchor) { setMarginCard(null); return } setMarginCard({ m, anchor, reason }) }}
              onAltHover={(phrase, anchor, reason, range) => { if (!anchor) return; setTraceCard((c) => (c && c.phrase === phrase && c.reason === reason ? c : { phrase, anchor, reason, range })) }}
              onSlash={onSlash}
              onStopRun={stopRun}
              onRetryRun={retryRun}
              /* 空文档那一刻是**唯一一个用户愿意读提示的时刻**，别拿去讲 Markdown。
                 原文是「开始写… 支持 Markdown 和 ```mermaid 图表。写到一半点右上角
                 「续写」…」——三个毛病：讲的是实现细节不是邀请；```mermaid 这种写法
                 是给程序员看的；而最值钱的东西（`/` 后面挂着八个能力）一个字没提。
                 还指着「续写」那个标签，而那个标签在默认布局下是藏起来的（第 618 轮）。
                 Markdown / mermaid 的说明挪进了「更多」菜单——那是「想起来了去查」的
                 东西，不是「第一次打开」的。 */
              /* **两个占位符别说同一句话。** 底下那条 composer 是「说一句话让 AI 写」，
                 这里是「自己动手写」——原来两句都以「写…什么」开头，一屏里
                 两个输入框看起来在问同一件事（第 737 轮实拍新笔记那一屏）。
                 顺带把 `/` 的内容补全：第 705 轮给它加了排版组，这句话还停在之前。 */
              placeholder="在这里写。　打一个 / 唤出菜单：AI 写作、插图、表格、排版"
              viewRef={editorViewRef}
            />
            {/* 边缘记忆的关系卡：贴在圆点旁边，不用转头去右栏（P9，§3.3） */}
            {marginCard && current && (
              <MarginCard card={marginCard} content={content} onClose={() => setMarginCard(null)} onInsert={insertAtCursor}
                          onSeeAll={() => { setMarginCard(null); setPaneFocus({ id: 'memory', n: Date.now() }) }} />
            )}
            {/* ⌥ 悬停 / ⌥↩ 的来龙去脉卡：贴在词边、零模型（P16，§3.3 场景 B） */}
            {traceCard && current && (
              <TraceCard card={traceCard} content={content} onClose={() => setTraceCard(null)} onInsert={insertAtCursor}
                         onTrace={(p) => void traceFromCard(p)} />
            )}
          </>
        )}
        </div>{/* note-body */}
        </div>{/* note-scroll */}
        </div>{/* note-pane */}
        {split && (
          <>
            <Gutter side="right" onResize={(dx) => setSplit((s) => s && ({ ...s, w: Math.max(260, Math.min(900, s.w + dx)) }))} />
            <div className="split-pane" style={{ width: splitW }}>
              {renderSplit(split.id)}
            </div>
          </>
        )}

      {rightShown && (
        <Gutter side="right" onResize={(dx) => setPanes((p) => ({ ...p, rightW: Math.max(180, Math.min(700, p.rightW + dx)) }))} />
      )}
      {rightShown && (
      <div className="right-pane" style={{ width: panes.rightW }}>
        {verifyResult && (
          <VerifyPanel findings={verifyResult.findings}
                       checked={verifyResult.checked ?? 0}
                       unparsed={verifyResult.unparsed ?? false}
                       passage={verifyResult.passage}
                       gone={!!verifyResult.passage && !content.includes(verifyResult.passage)}
                       onJump={jumpToPassage(verifyResult.passage)}
                       onClose={() => setVerifyResult(null)} />
        )}
        <RightPane
          onCollapse={() => setPanes((p) => ({ ...p, rightOn: false }))}
          defaultTab="memory"
          focusTab={paneFocus}
          tabs={[
            // 记忆是默认标签：边写边浮现的召回（判据 2）。不再是压在所有标签上面的常驻块。
            { id: 'memory', title: '记忆', icon: 'bx-bulb', alwaysShown: true,
              body: current
                ? <div className="stack">
                    {/* 材料托盘（P14 §3.4）：「记忆」的第一格，不开新页签（P12 定的：右栏页签只能减不能加） */}
                    <TrayPanel key={'tray:' + current.id} noteId={current.id} onWrite={writeFromTray} />
                    <RelatedMemory key={ingestTick} content={content} paragraph={cursorPara} onInsert={insertAtCursor}
                                   noRecordDots={noRecordDots}
                                   kbEmpty={kbRows.length > 0 && (kbRows.find((r) => r.note_id === 'kb')?.fact_count ?? 0) === 0} />
                  </div>
                : <p className="muted" style={{ fontSize: 'var(--t-sm)' }}>打开一篇笔记后，这里会跟着你写的内容浮现相关记忆。</p> },
            /* 「目录」不再是单独的页签：目录 = 计划（P12，agent-native-editor §3.5）——每一节带状态的目录就是这篇的计划，
               跟完成标准、骨架、执行记录放在同一个「计划」页签里。 */
            /* 幻灯片预览：**只在这篇真是幻灯片时才出现**（front-matter 里有 slides: true）。
               普通笔记上多一个永远空着的标签，比没有这个标签更糟。 */
            ...(isSlides(content) ? [{
              id: 'slides', title: '幻灯片', icon: 'bx-slideshow', alwaysShown: true,
              badge: slidePages(content).length || undefined,
              body: <SlidesPanel content={content} viewRef={editorViewRef} />,
            }] : []),
            // 改动的分层账本：每次 AI 动作一层，整层接受 / 撤回（痛点 8：AI 改了三轮只想要第一轮）
            // P16：烧进正文之后这次跑的每一轮还在（后端每轮开始前存一版）——有烧过的跑时这个标签也留着，逐轮「回到之前 / 只撤这一轮」
            // 放不回来的那几层也算「有内容」：出路摆在这个页签里，页签自己不出现就等于没出路（P41 #5 ②）
            // P43 #1：页签出不出现**跟面板这一次会画出什么算同一份判据**（`changesTabHasContent`）。
            // 原来这一格只看 `pendingDiff`（不算只差空白的那几处），面板却按 `layersOf` /
            // `settledOf` 画——一层逐处处置完之后面板还有「已处置 N 接受 / M 撤回」那行灰字
            // 可画，页签已经没了，于是重开时那句 toast 指着一个不存在的地方（P42 问题 #1）。
            // 这两个数**当场从编辑器读**——跟下面 `ChangeLayersPanel` 同一个渲染回合、同一个
            // view，所以两边不可能对不上；重渲染照旧由 `pendingDiff` / `layersTick` 触发。
            { id: 'changes', title: '改动', icon: 'bx-git-compare', badge: pendingDiff || undefined,
              hasContent: changesTabHasContent({
                layers: editorViewRef.current ? layersOf(editorViewRef.current).length : 0,
                settled: editorViewRef.current ? settledOf(editorViewRef.current).length : 0,
                runs: runs.length,
                stuck: layerStuck.length,
              }),
              body: <ChangeLayersPanel viewRef={editorViewRef} tick={pendingDiff + layersTick} runs={runs} busy={loading === 'rounds'}
                                       stuck={layerStuck} onRecomputeStuck={recomputeStuckLayer} onDropStuck={dropStuckLayer}
                                       onRestoreBefore={(r) => void restoreBeforeRound(r)} onUndoRound={(r) => void undoRoundOnly(r)} /> },
            // 计划 = 完成标准（判据）+ 目录（每节状态）+ 写作骨架 + 每轮做了什么（执行）。判据 3：计划要看得见——
            // 在右栏一直看得见，比把正文顶下去好。harness 跑起来自动切到这里。
            // P12（§3.1 / §3.5）：「完成标准」逐条核、目录每一节带「空 / 草稿 / 有依据」——目录就是计划，不再单开一个页签。
            // P91 A：**角标、出不出内容、空了说哪句话，三样同一份判据**（`planTabContent`，
            // 跟「改动」那一格 P43 #1 同一条理由）。原来这一格是两把尺：角标拿上一篇留下的
            // `agentRounds` 数出「计划 2」，而正文那四块在虚拟页上一块都画不出来，
            // 于是 `alwaysShown` 的页签底下是**一片纯空白**（P89 实拍 `p89-b4-old-wipe-light.png`），
            // 而 `RightPane` 自己的注释写着「别留白」——那条 `emptyHint` 的路当时一条都走不到。
            // 虚拟页（知识库 / 设置…）上 current 是 null，但 beats 还是上一篇的：角标别拿旧骨架充数（第 524 轮实拍事实表页顶着「计划 5」）
            // P95 A：`agentRounds` 这一半从**源头**治了——它按 note id 取，换篇 / 虚拟页上本来就取不到上一篇的
            // （P93 实拍：A 篇跑完 2 轮，⌘K 新建一篇空笔记，这儿写着「计划 2」、底下摆着 A 篇那两轮的执行记录）
            { id: 'plan', title: '计划', icon: 'bx-target-lock', alwaysShown: true,
              badge: planTabContent({ hasNote: !!current, running: loading === 'note-harness' || !!harness?.running,
                                      rounds: agentRounds.length, beats: beats.length }).badge || undefined,
              hasContent: planTabContent({ hasNote: !!current, running: loading === 'note-harness' || !!harness?.running,
                                           rounds: agentRounds.length, beats: beats.length }).has,
              emptyHint: PLAN_EMPTY_HINT,
              // 跑起来之后轮次卡排在最前：骨架是一屏高的静态文本，跑动中用户要看的是
              // 「这一轮在干什么、判了什么」，原来得滚过整份骨架才看得到（第 579 轮实拍）。
              // 不跑的时候判据 → 目录 → 骨架 → 执行——那会儿规划才是主角。
              body: (() => {
                const busy = loading === 'note-harness' || !!harness?.running || !!pausedRun
                const checks = current && (
                  <PlanChecks key="checks" done={intent.done} content={content} checked={intent.checked ?? []}
                    onToggle={(text, on) => {
                      const was = intent.checked ?? []
                      const next = on ? Array.from(new Set([...was, text])) : was.filter((t) => t !== text)
                      saveIntent({ ...intent, source: intent.source || 'user', checked: next })
                    }}
                    onEdit={() => document.querySelector<HTMLInputElement>('.doc-intent-input[aria-label="完成标准"]')?.focus()} />
                )
                const outline = current && (
                  <div key="outline">
                    <h2>目录</h2>
                    <DocumentOutline content={content} viewRef={editorViewRef} withStatus />
                  </div>
                )
                const skeleton = current && (
                  <SkeletonPanel
                    key="skeleton"
                    spine={spine}
                    beats={beats}
                    beatCoverage={beatCoverage}
                    notes={skeletonNotes}
                    loading={loading === 'skeleton'}
                    onRun={runSkeleton}
                    onStop={stopSkeleton}
                    onJumpLine={jumpToLine}
                  />
                )
                const activity = (current || loading === 'note-harness' || harness?.running) && <AgentActivity
                  key="activity"
                  rounds={agentRounds}
                  status={loading === 'note-harness' || pausedRun ? noteHarnessStatus : ''}
                  running={loading === 'note-harness'}
                />
                return <div className="stack">{busy ? [activity, outline, checks, skeleton] : [checks, outline, skeleton, activity]}</div>
              })() },
            { id: 'revisions', title: '修订', icon: 'bx-edit', badge: revisions.length || undefined,
              hasContent: revisions.length > 0, emptyHint: '这篇还没有待处置的修订。',
              body: (
                <RevisionPanel
                  revisions={revisions}
                  content={content}
                  loading={loading === 'edit'}
                  onAccept={acceptRevision}
                  onReject={(r) => setRevisions((rs) => rs.filter((x) => x.id !== r.id))}
                  onRun={() => {}}
                />
              ) },
            { id: 'trace', title: '脉络', icon: 'bx-git-commit', hasContent: !!trace,
              badge: trace?.facts.length || undefined,
              body: trace ? (
                <div className="stack">
                  {/* P43 #5：跟「校验结果」那块**用同一个 `verifyScopeLine`**报户口——
                      两块卡并排挂在右栏上面时，一块写清说的是哪一段、另一块不写，
                      等于只解决了一半（P42 问题 #6）。「还在不在正文里」照旧按现在的正文判。 */}
                  {!!verifyScopeLine(trace.passage ?? '', !!trace.passage && !content.includes(trace.passage)) && (
                    <p className="muted verify-scope" style={{ margin: 0, fontSize: 'var(--t-sm)' }}>
                      {/* P46 #4：跟「校验结果」那块**用同一个 `jumpToPassage`**——
                          一块能跳回去、另一块不能，用户还是得自己找。跳不回去时两块都只是普通字。 */}
                      {jumpToPassage(trace.passage)
                        ? <span className="scope-jump" title="跳回正文这一段" {...clickable(jumpToPassage(trace.passage)!)}>
                            {verifyScopeLine(trace.passage ?? '', !!trace.passage && !content.includes(trace.passage))}
                          </span>
                        : verifyScopeLine(trace.passage ?? '', !!trace.passage && !content.includes(trace.passage))}
                    </p>
                  )}
                  <p style={{ margin: 0, lineHeight: 1.6 }}>{trace.answer}</p>
                  {/* P41 #1：KITE 一条都没串出来、而词法召回真的有数时，说清那几条在哪儿看得到。
                      后端那句话已经不说假的了（`AskOut.recalled` 三档），这里补的是出路那半句。 */}
                  {!!traceRecallHint(trace.facts.length, trace.recalled) && (
                    <p className="muted" style={{ margin: 0, fontSize: 'var(--t-sm)' }}>
                      {traceRecallHint(trace.facts.length, trace.recalled)}
                    </p>
                  )}
                  {trace.facts.map((f) => (
                    <div key={f.id} className="card" style={{ fontSize: 'var(--t-sm)' }}>
                      <span className="muted">{f.when}</span>
                      <div>{f.text}</div>
                      <button style={{ fontSize: 'var(--t-xs)', marginTop: 4 }}
                              onClick={() => insertAtCursor(`${f.text} [${f.id}]\n`)}>
                        插入到正文
                      </button>
                    </div>
                  ))}
                </div>
              ) : null },
          ] as PaneTab[]}
        />
      </div>
      )}
        </div>{/* center-pane */}
      </div>{/* rest-pane */}
      </div>{/* shell-main */}

      {/* 状态栏。放**当前在发生什么**——harness 跑到第几轮、后端连没连上。
          判据 3（高度自动化）要求自动化的过程是看得见的；一个只会转圈的
          指示器等于什么都没说。 */}
      <div className="status-bar">
        {/* 面包屑：当前笔记在树的哪个位置。克隆之后同一篇在多处，这是唯一能
            说清「你现在看的是哪一份」的东西（Trilium StatusBar 的 Breadcrumb）。 */}
        <span className="breadcrumb status-crumbs">
          {crumbs.length === 0
            ? <span>{notes.length} 篇笔记</span>
            : crumbs.map((r, i) => (
              <span key={r.id}>
                {i > 0 && <span className="muted"> / </span>}
                {i === crumbs.length - 1
                  ? <b>{displayTitle(r)}</b>
                  : <a href="#" onClick={(e) => { e.preventDefault(); openFromTree(r.note_id) }}>{displayTitle(r)}</a>}
              </span>
            ))}
        </span>
        {loading === 'note-harness' && noteHarnessStatus && (
          <span style={{ color: 'var(--accent)' }}><Icon n="bx-bot" /> {noteHarnessStatus}</span>
        )}
        {pausedRun && <span style={{ color: 'var(--accent)' }}><Icon n="bx-pause-circle" /> 等你处置</span>}
        {harness?.running && <span style={{ color: 'var(--accent)' }}><Icon n="bx-folder-open" /> {harness.folderName}</span>}
        <span style={{ marginInlineStart: 'auto', display: 'inline-flex', gap: 12, alignItems: 'center' }}>
          {jobInfo && <span className="muted"><span className="spinner" /> 存入知识库中…{jobInfo.total > 0 ? ` 第 ${Math.min(jobInfo.done + 1, jobInfo.total)}/${jobInfo.total} 块` : ''}{jobInfo.eta > 0 ? ` · 还要约 ${jobInfo.eta < 90 ? `${jobInfo.eta} 秒` : `${Math.round(jobInfo.eta / 60)} 分钟`}` : ''}{jobInfo.facts > 0 ? ` · 已抽出 ${jobInfo.facts} 条` : ''}
            {/* P3 遗留（？）：后台 job 原来没有取消——模型卡住时这一行要转到 job 自己超时。后端本来就有 cancel，接上 */}
            {jobInfo.status === 'cancelling'
              ? <>{' '}· 取消中（等这一块的模型调用结束）</>
              : <>{' '}<button className="linklike" title="取消这次存入知识库（已抽出的留着）" onClick={() => { void api.cancelJob(job).catch((e) => toast('取消不了：' + friendlyError(e), 'error')) }}>取消</button></>}
          </span>}
          {/* 红字可点：装好的包第一次开、或换了台机器没填模型，红字只说「不可达」用户不知道去哪修 */}
          {healthMsg && (
            <button className="health-bad linklike"
                    title={healthMsg === NOT_CONFIGURED
                      ? '还没配过模型：打开设置，选「本地模型」填地址和模型名，或选「OpenAI 兼容」填 key'
                      : '点开设置页填模型地址 / 密钥'}
                    onClick={() => void openVirtual('app:settings', '设置')}>
              <Icon n="bx-error" /> {healthMsg} · 去设置
            </button>
          )}
          {asrOffline && <span className="muted" title={'语音服务不可达：' + asrOffline + '。录音转写用不了，其它功能不受影响。'}><Icon n="bx-microphone-off" /> 语音离线</span>}
        </span>
        {current && <span className="muted">{wordCount(content)} 字{wordCount(content) > 0 && <> · 约 {readingMinutes(wordCount(content))} 分钟</>}</span>}
      </div>
    </div>
  )
}
