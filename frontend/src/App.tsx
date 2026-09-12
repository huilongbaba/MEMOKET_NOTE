import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { openSearchPanel } from '@codemirror/search'
import { micError } from './util/micError'
import ChangeLayersPanel from './components/ChangeLayersPanel'
import { matchSnippet } from './util/snippet'
import { readingMinutes, wordCount } from './util/wordCount'
import { friendlyError, isLlmUnreachable } from './util/friendlyError'
import { EditorView } from '@codemirror/view'
import * as api from './api'
import type { Note, Revision, TapMeta, TreeRow, VerifyFinding, WritingPlan, WritingSection } from './api'
import AudioRecorder from './components/AudioRecorder'
import CommandPalette from './components/CommandPalette'
import DocumentOutline from './components/DocumentOutline'
import MarkdownEditor from './components/MarkdownEditor'
import SlashPrompt from './components/SlashPrompt'
import { formatMarkdown, fixBoldPunct, stripCommonIndent } from './editor/format'
import type { SlashItem } from './editor/slashMenu'
import {
  appendPreview, endRun, logRun, patchRun, runsField, startRun,
} from './editor/runningBlocks'
import type { StateEffect } from '@codemirror/state'
import MarkdownToolbar from './components/MarkdownToolbar'
import WritingPlanPanel from './components/WritingPlanPanel'
import MemoryPanel from './components/MemoryPanel'
import RelatedMemory from './components/RelatedMemory'
import RevisionPanel, { applyRevision } from './components/RevisionPanel'
import SelectionMenu from './components/SelectionMenu'
import type { SelectionAction } from './components/SelectionMenu'
import AgentActivity, { type AgentRound } from './components/AgentActivity'
import { acceptAllHunks, diffParts, dropHunk, roundDiffField, type DiffPush }
  from './editor/roundDiff'
import ContextMenu, { type MenuAt, type MenuItem } from './components/ContextMenu'
import Gutter from './components/Gutter'
import Logo from './components/Logo'
import PreferencesPanel from './components/PreferencesPanel'
import KbNoteView from './components/KbNoteView'
import { displayTitle, isPlaceholderTitle } from './util/displayTitle'
import { sectionEnd } from './util/sectionEnd'
import { minimalChange } from './editor/minimalChange'
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
import SettingsPanel from './components/SettingsPanel'
import SkillsPanel from './components/SkillsPanel'
import TapProvenance from './components/TapProvenance'
import Toaster from './components/Toaster'
import UserSwitcher from './components/UserSwitcher'
import VerifyPanel from './components/VerifyPanel'
import { toast, toastAction } from './toast'
import { fmtDate } from './util/time'
import { notifyIfHidden } from './util/notify'

// 后台自动生成的节流参数。骨架/编辑都是真实 LLM 调用（本地模型上约 8-15s），
// 不能跟着每次按键触发——用"停止输入 N 秒 + 内容变化够多"两条门槛，既保证
// 不是纯手动，又不会打字过程中疯狂重复调用模型。
const SKELETON_IDLE_MS = 8000
const SKELETON_MIN_CHARS = 30
const SKELETON_MIN_DELTA = 20

/** First non-empty line of a note's content, syntax markers stripped, for
 * the sidebar preview -- strip rather than render so it stays plain text
 * in a one-line ellipsis instead of showing raw "## " or "- " noise. */
function previewLine(content: string, skip = ''): string {
  // 第一行常常就是标题本身（「# 会议纪要 10」）——搜索卡上再印一遍没意义，
  // 跳过跟标题一样的那行，取下一行
  const clean = (l: string) => l.replace(/^#{1,6}\s+/, '').replace(/^[-*>]\s+/, '').trim()
  const lines = content.split('\n').map(clean).filter((l) => l)
  const skipNorm = skip.trim().replace(/\s+/g, '')
  return lines.find((l) => l.replace(/\s+/g, '') !== skipNorm) ?? lines[0] ?? ''
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

/** 不在树上、又没人传标题时标签页显示什么——之前 app:skills 直接把 id 当标题（实拍）。 */
const VIRTUAL_LABELS: Record<string, string> = {
  'app:settings': '设置', 'app:skills': '写作 Skill', 'app:import': '导入',
  kb: '知识库', 'kb:graph': '主题地图', 'kb:digest': '定期回顾', 'kb:timeline': '时间线',
  'kb:topics': '主题', 'kb:entities': '实体', 'kb:recent': '最近摄入',
}

export default function App() {
  const [notes, setNotes] = useState<Note[]>([])
  // 整棵树一次拿全（见 api.getTree 的注释：按层拿会让展开变成一次网络往返）。
  const [tree, setTree] = useState<TreeRow[]>([])
  // 知识库那棵**虚拟**子树（docs/kb-fusion-design.md §3.2）。分类层一次取全，
  // 事实按需展开；展开状态不在服务端（虚拟节点没有 branch），存本机。
  const [kbRows, setKbRows] = useState<TreeRow[]>([])
  const [kbChildren, setKbChildren] = useState<Record<string, TreeRow[]>>({})
  const [kbExpanded, setKbExpanded] = useState<Set<string>>(() => {
    try {
      const raw = localStorage.getItem('memoket-note-kb-expanded:' + api.getUser())
      return new Set(raw ? (JSON.parse(raw) as string[]) : [])
    } catch { return new Set() }
  })
  // 中栏正在看的虚拟节点（一条事实 / 一个分类）。跟 current 互斥：有 current
  // 就是在写笔记，有 virtualId 就是在看知识库。
  const [virtualId, setVirtualId] = useState<string | null>(null)
  // 应用内对话框（替掉 window.prompt——Electron 里那是系统级模态，主题管不到）
  const [picker, setPicker] = useState<PickerRequest | null>(null)
  const [prompt, setPrompt] = useState<PromptRequest | null>(null)
  const [confirmReq, setConfirmReq] = useState<ConfirmRequest | null>(null)
  const [locateTick, setLocateTick] = useState(0)
  const [paneFocus, setPaneFocus] = useState<{ id: string; n: number } | undefined>(undefined)
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
    if (title.trim() || content.trim()) { freshEmpty.current.delete(n.id); return }
    freshEmpty.current.delete(n.id)
    try {
      await api.deleteNote(n.id)
      setTabs((prev) => prev.filter((t) => t.noteId !== n.id))
      void Promise.all([reload(), reloadTree()])
    } catch { /* 删不掉就留着，不值得报错 */ }
  }
  // 分屏：中栏右侧再开一栏看另一篇（Trilium 的 SplitNoteContainer）。
  // **第二栏是只读的**——「对照着另一篇写」要的是看得见，不是两个光标；
  // 编辑器的状态（正文/骨架/修订/harness）是单实例的，做成可编辑要重构一半的
  // App.tsx，收益不成比例。要改它就点「在标签里打开」。
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
  const [quick, setQuick] = useState<Note | null>(null)
  // 保存状态角标（Trilium 的 save-status-badge）：存了就说一声、5s 淡出；
  // 出错变红不淡出。自动保存的产品里留一个「保存」按钮反而暗示「不点就没存」。
  const [saveStatus, setSaveStatus] = useState<{ at: number; error?: string } | null>(null)
  // 关掉的标签留一个栈，⌘⇧T 找回来（reopenLastTab）。关错标签不该无法挽回。
  const closedTabs = useRef<Tab[]>([])
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
  const [loading, setLoading] = useState<'' | 'skeleton' | 'restructure' | 'edit' | 'tap' | 'ingest' | 'note-harness'>('')
  /** agent 每一轮干了什么，喂给 AgentActivity 可视化。按轮聚合：用户关心的是
   * "这一轮查了什么 → 改了什么 → 打了几分 → 于是下一轮怎么调"这条因果链，
   * 事件流水账看不出所以然。 */
  const [agentRounds, setAgentRounds] = useState<AgentRound[]>([])
  useEffect(() => { agentRoundsRef.current = agentRounds.length }, [agentRounds])
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
  // `/` 菜单选中的那一项。needsPrompt 的会先弹输入框，其余的直接执行。
  // 运行状态**不在这里**：跑起来之后状态在光标处的占位块里
  // （editor/runningBlocks.ts）——离产出最近，而且支持同时跑好几个。
  // 这里只留「选中了哪一项、要不要弹提示词输入框」。
  const [slash, setSlash] = useState<
    { item: SlashItem; from: number; to: number; x: number; y: number } | null>(null)
  // **一次运行一个 AbortController**，用 id 索引。原来是单个 ref，
  // 所以同时只能跑一个 `/`——第二个一开始就把第一个的 controller 顶掉了。
  const runAborts = useRef(new Map<string, AbortController>())
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
  const liveContentRef = useRef<string>('')
  // 定向续写的插入光标：null = 追加到文末；每轮开始时复位
  const insertCursorRef = useRef<number | null>(null)
  // 探针里的 setTimeout 回调抓的是那一次 render 的函数——闭包里的 current 是旧的
  // （实拍：harness 跑到了启动时自动打开的那篇上）。永远走最新的那份。
  const actionsRef = useRef({ runNoteHarness: (_m: 'write' | 'polish') => Promise.resolve(), runMagicTap: () => Promise.resolve(), handleSelectionAction: (_a: SelectionAction) => Promise.resolve(), runHarness: (_r: TreeRow) => Promise.resolve(), ingestCurrentNote: () => Promise.resolve(), runBlock: (_i: SlashItem, _f: number, _t: number, _p: string) => Promise.resolve(), dropIfStillEmpty: (_n: Note | null) => Promise.resolve(), collapseAll: () => Promise.resolve(), pushDiff: (_l: string, _b: string, _a: string, _r?: boolean) => {} })
  const [noteHarnessStatus, setNoteHarnessStatus] = useState('')
  // 跑完之后那行结果（几轮、加了多少字、为什么停）留着，直到用户关掉 / 换笔记 /
  // 再跑一次。之前只弹一个 toast，几秒就没了，用户回头看只剩「改了 1 处」的工具条。
  const [harnessDone, setHarnessDone] = useState(false)
  const [showShortcuts, setShowShortcuts] = useState(false)
  // 摄入完成后让「记忆」重新召回一次：正文没变它不会自己再查，而刚入库的事实正是用户想看到的
  const [ingestTick, setIngestTick] = useState(0)
  const harnessDoneRef = useRef(false)
  const agentRoundsRef = useRef(0)
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
  const [writingPlanParent, setWritingPlanParent] = useState<TreeRow | null>(null)
  const [harness, setHarness] = useState<HarnessState | null>(null)
  const [job, setJob] = useState('')

  // harness 跑起来时右栏切到「计划」：计划 + 每轮判了什么，就在眼前（判据 3）
  useEffect(() => {
    if (loading === 'note-harness') setPaneFocus((f) => ({ id: 'plan', n: (f?.n ?? 0) + 1 }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading === 'note-harness'])

  /** 正文里引用了哪些事实。跟后端 `store.cited_fact_ids` 用同一条正则——
   *  两边认的不是同一批，ribbon 的角标和树上的 ◆ 就会对不上。 */
  const citedIds = useMemo(() => {
    const re = /\[([A-Za-z][A-Za-z0-9_-]*-(?:\d+|[0-9a-f]{12})-[0-9A-Fa-f]+)\]/g
    const seen = new Set<string>()
    for (const m of content.matchAll(re)) seen.add(m[1])
    return [...seen]
  }, [content])

  const [healthMsg, setHealthMsg] = useState('')
  const [asrOffline, setAsrOffline] = useState('')
  async function checkHealth() {
    try {
      const h = await api.health()
      // LLM 不通是硬伤，红字常驻；语音是可选服务（没配 ASR 的用户是多数），
      // 只给一个灰色的「语音离线」，悬停看地址——之前一行 ⚠ 长期挂着像出了事故。
      setHealthMsg(!h.llm?.ok ? 'LLM 不可达 (' + h.llm?.base_url + ')' : '')
      setAsrOffline(!h.asr?.ok ? (h.asr?.base_url ?? '') : '')
    } catch { setHealthMsg('后端不可达') }
  }
  const [focusMode, setFocusMode] = useState(false)
  // 左右栏各自可拖宽、可独立折叠，按用户存本机（Trilium 存 leftPaneWidth /
  // rightPaneWidth / leftPaneVisible，我们同一套思路）。focusMode 保留为
  // 「两个都收」的快捷方式。
  const [panes, setPanes] = useState(() => {
    const d = { leftW: 260, rightW: 340, leftOn: true, rightOn: true }
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
  const leftW = Math.min(panes.leftW, Math.floor(winW * 0.3))
  const LAUNCHER_W = 80
  // 分屏也算进去：1000×700 开分屏实拍，中栏被挤到 250px，ribbon 折两行、工具栏只剩 B。
  // 分屏最多占窗口 45%；右栏先收，还不够就连左栏也收（关掉分屏自动回来）。
  const splitW = split ? Math.min(split.w, Math.floor(winW * 0.45)) : 0
  const tooNarrowForRight = panes.leftOn && winW - LAUNCHER_W - leftW - panes.rightW - splitW < 520
  const tooNarrowForLeft = !!split && winW - LAUNCHER_W - leftW - splitW < 520
  const leftShown = !focusMode && panes.leftOn && !tooNarrowForLeft
  const rightShown = !focusMode && panes.rightOn && !tooNarrowForRight
  const [selectionMenu, setSelectionMenu] = useState<{ x: number; y: number; text: string } | null>(null)
  // 光标所在段落：右栏「记忆」按它查跟知识库的关系（冲突 / 延续 / 印证 / 缺依据）
  const [cursorPara, setCursorPara] = useState('')
  const [selectionBusy, setSelectionBusy] = useState<false | SelectionAction>(false)
  const [verifyFindings, setVerifyFindings] = useState<VerifyFinding[] | null>(null)
  /** 「来龙去脉」的结果。落在右栏的标签里而不是弹层——判据 2：看一条旧记录
   *  不该离开这一页，弹层要么盖住正文、要么关掉就没了。 */
  const [trace, setTrace] = useState<
    { answer: string; facts: api.Fact[]; at: string } | null>(null)

  const editorViewRef = useRef<EditorView | null>(null)
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
    const knownVirtual = (id: string) => !!VIRTUAL_LABELS[id] || /^kb:(topic|entity|unit|fact|facts|etype)(:|$)/.test(id) || id.startsWith('app:')
    setTabs((prev) => prev
      .filter((t) => (api.isVirtualId(t.noteId) ? knownVirtual(t.noteId) : ids.has(t.noteId)))
      // 旧版本存下来的标签标题就是裸 id（kb:fact:terrence-…）：补个名字
      .map((t) => (t.title === t.noteId && t.noteId.startsWith('kb:fact:') ? { ...t, title: '事实 ' + t.noteId.slice(8) } : t)))
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
    const t = closedTabs.current.pop()
    if (!t) return
    setTabs((prev) => (prev.find((x) => x.noteId === t.noteId) ? prev : [...prev, t]))
    activateTab(tabs.find((x) => x.noteId === t.noteId) ?? t)
  }
  function closeTabsWhere(pred: (t: Tab, i: number) => boolean) {
    const gone = tabs.filter(pred)
    if (gone.length === 0) return
    closedTabs.current = [...closedTabs.current, ...gone].slice(-20)
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
  function closeTab(id: string) {
    const i = tabs.findIndex((x) => x.id === id)
    if (i < 0) return
    if (current && tabs[i].noteId === current.id && freshEmpty.current.has(current.id) && !title.trim() && !content.trim()) {
      void dropIfStillEmpty(current)
    }
    closedTabs.current = [...closedTabs.current, tabs[i]].slice(-20)
    const next = tabs.filter((x) => x.id !== id)
    setTabs(next)
    if (id !== activeTabId) return
    const fallback = next[i] ?? next[i - 1] ?? null
    if (fallback) activateTab(fallback)
    else {
      setActiveTabId(null); setCurrent(null); setVirtualId(null); setTitle(''); setContent('')
    }
  }

  const reloadTree = useCallback(async () => {
    const t0 = performance.now()
    const rows = await api.getTree()
    const fetched = performance.now() - t0
    setTree(rows)
    // 大库量一眼：几百篇时树的取数和首帧各花多久（探针看 client-log）
    if (rows.length >= 200) requestAnimationFrame(() => void api.clientLog('warn', `tree ${rows.length} rows: fetch ${Math.round(fetched)} ms, paint ${Math.round(performance.now() - t0)} ms`, '', 'perf'))
    // 知识库子树跟着一起刷：摄入完新事实，主题/月份的计数要跟上。
    // 取不到（KITE 还没建库）就当没有，不影响真笔记。
    api.kbTree().then(setKbRows).catch(() => setKbRows([]))
    return rows
  }, [])

  useEffect(() => {
    try {
      localStorage.setItem('memoket-note-kb-expanded:' + api.getUser(),
                           JSON.stringify([...kbExpanded]))
    } catch { /* 存不上就下次全收起，不致命 */ }
  }, [kbExpanded])

  /** 事实是按需取的：展开一个主题/实体/月份/会议时才去拿它名下那一层。 */
  const needsFacts = (id: string) => /^kb:(topic|entity|month|unit):/.test(id)
  const loadKbChildren = useCallback(async (id: string) => {
    if (!needsFacts(id)) return
    try {
      const rows = await api.kbTreeChildren(id)
      setKbChildren((m) => ({ ...m, [id]: rows }))
    } catch { /* 展开了但没内容，树上就是空的，比报错好 */ }
  }, [])

  // 刷新后已经展开着的分类，把事实层补回来。
  useEffect(() => {
    for (const id of kbExpanded) if (needsFacts(id) && !kbChildren[id]) void loadKbChildren(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kbRows])

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
  const allRows = useMemo(() => {
    const virt = [...kbRows, ...Object.values(kbChildren).flat()]
      .map((r) => ({ ...r, is_expanded: kbExpanded.has(r.note_id) }))
    return [...tree, ...virt]
  }, [tree, kbRows, kbChildren, kbExpanded])

  // 截图探针：把知识库子树摆成「根 + 主题 + 第一个主题」展开的样子，
  // 并打开第一个主题（kb-tree）或它名下第一条事实（kb-fact）。
  const kbProbeDone = useRef(false)
  useEffect(() => {
    const probe = new URLSearchParams(location.search).get('probe')
    if (!probe?.startsWith('kb-') || probe === 'kb-tab' || kbProbeDone.current || kbRows.length === 0) return
    const first = kbRows.filter((r) => r.parent_note_id === 'kb:topics')
      .sort((a, b) => b.fact_count - a.fact_count)[0]
    if (!first) return
    kbProbeDone.current = true
    setKbExpanded(new Set(['kb', 'kb:topics', first.note_id]))
    void api.kbTreeChildren(first.note_id).then((rows) => {
      setKbChildren((m) => ({ ...m, [first.note_id]: rows }))
      if (probe === 'kb-fact' && rows[0]) void openVirtual(rows[0].note_id, rows[0].title)
      else void openVirtual(first.note_id, first.title)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kbRows])

  function toggleKbNode(row: TreeRow) {
    const next = !row.is_expanded
    setKbExpanded((prev) => {
      const s = new Set(prev)
      if (next) s.add(row.note_id); else s.delete(row.note_id)
      return s
    })
    if (next && !kbChildren[row.note_id]) void loadKbChildren(row.note_id)
  }

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
    if (id.startsWith('kb:') && !VIRTUAL_LABELS[id] && !/^kb:(topic|entity|unit|fact|facts|etype)(:|$)/.test(id)) id = 'kb'
    if (virtualId === id && !current) return
    await save()
    const leaving = current
    pushHistory(id)
    void dropIfStillEmpty(leaving)
    setCurrent(null); setTitle(''); setContent('')
    setVirtualId(id)

    const label = title ?? allRows.find((r) => r.note_id === id)?.title ?? VIRTUAL_LABELS[id]
      ?? (id.startsWith('kb:facts') ? '事实表' : /^kb:(topic|entity|unit):/.test(id) ? id.split(':').slice(2).join(':')
        : id.startsWith('kb:fact:') ? '事实 ' + id.slice(8) : id.startsWith('kb:unit:') ? '会议记录' : id)
    setTabs((prev) => prev.find((x) => x.noteId === id)
      ? prev
      : [...prev, { id: 't' + Math.random().toString(36).slice(2, 9), noteId: id, title: label }])
  }

  // 右栏那些面板没有 openVirtual 的句柄，用一个窗口事件把「打开某个虚拟节点」
  // 送过来（跟 open-command-palette 同一个模式）。
  useEffect(() => {
    const on = (e: Event) => { const id = (e as CustomEvent<string>).detail; if (id) void openVirtual(id) }
    const onNew = () => void newNote()
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
      save().catch(() => {})
        .then(() => actionsRef.current.dropIfStillEmpty(currentRef.current)).catch(() => {})
        .finally(() => window.memoketDesktop?.flushed?.())
    }
    window.addEventListener('flush-save', onFlush)
    const onOpenNote = (e: Event) => {
      const id = (e as CustomEvent<string>).detail
      const n = notes.find((x) => x.id === id)
      if (n) { void switchTo(n); return }
      // 刚建的（比如「存为笔记」）还不在列表里：拉一次再开，别急着说不存在
      void api.getNote(id).then((fresh) => { void reload(); void reloadTree(); void switchTo(fresh) }).catch(() => toast('链接指向的笔记不存在了', 'error'))
    }
    window.addEventListener('open-note', onOpenNote)
    window.addEventListener('open-virtual', on)
    window.addEventListener('new-note', onNew)
    window.addEventListener('show-shortcuts', onKeys)
    return () => { window.removeEventListener('open-virtual', on); window.removeEventListener('new-note', onNew); window.removeEventListener('show-shortcuts', onKeys); window.removeEventListener('open-note', onOpenNote); window.removeEventListener('nav-history', onNav); window.removeEventListener('tree-locate', onLocate); window.removeEventListener('tree-collapse', onCollapse); window.removeEventListener('export-all', onExport); window.removeEventListener('flush-save', onFlush) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, virtualId, allRows, notes])

  // 树上把当前的虚拟节点露出来：从首页 / 图 / chips 点进一个主题时，左栏的树
  // 也展开到它（Trilium 的树永远跟着当前笔记）。只展开祖先，不展开它自己。
  // 挂在 effect 上而不是 openVirtual 里：kbRows 可能比打开动作晚到。
  useEffect(() => {
    if (!virtualId || kbRows.length === 0) return
    setKbExpanded((prev) => {
      const byNote = new Map<string, TreeRow>()
      for (const r of allRows) if (!byNote.has(r.note_id)) byNote.set(r.note_id, r)
      const next = new Set(prev)
      let cur = byNote.get(virtualId)?.parent_note_id; let guard = 0
      while (cur && cur !== api.ROOT_ID && guard++ < 50) { next.add(cur); cur = byNote.get(cur)?.parent_note_id }
      return next.size === prev.size ? prev : next
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [virtualId, kbRows])

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
  const crumbs = useMemo(() => {
    const id = current?.id ?? virtualId
    if (!id) return [] as TreeRow[]
    const byNote = new Map<string, TreeRow>()
    for (const r of allRows) if (!byNote.has(r.note_id)) byNote.set(r.note_id, r)
    const out: TreeRow[] = []
    let cur = byNote.get(id); let guard = 0
    while (cur && guard++ < 50) { out.unshift(cur); cur = byNote.get(cur.parent_note_id) }
    return out
  }, [current, virtualId, allRows])

  /** 虚拟节点的右键菜单——没有「删除」「移动」这些：它们不是笔记，是知识库
   *  的一个视角。有的是把它带进笔记的动作。 */
  function kbMenuItems(row: TreeRow): MenuItem[] {
    const isFact = api.isFactId(row.note_id)
    const factId = row.note_id.slice('kb:fact:'.length)
    const items: MenuItem[] = [
      { label: '打开', icon: 'bx-link-external', onSelect: () => void openVirtual(row.note_id, row.title) },
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
    } else if (row.child_count > 0) {
      items.push({ kind: 'sep' },
        { label: row.is_expanded ? '收起' : '展开', icon: row.is_expanded ? 'bx-chevron-down' : 'bx-chevron-right',
          onSelect: () => toggleKbNode(row) })
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

  /** 折叠整棵树（只折真笔记的 branch；知识库那边清本机集合）。 */
  async function collapseAll() {
    const open = tree.filter((r) => r.is_expanded)
    setTree((prev) => prev.map((r) => ({ ...r, is_expanded: false })))
    setKbExpanded(new Set())
    await Promise.all(open.map((r) => api.setBranchExpanded(r.note_id, r.parent_note_id, false).catch(() => {})))
  }

  async function newNoteUnder(parentId: string) {
    const n = await api.createNote('', '', parentId)
    freshEmpty.current.add(n.id)
    await Promise.all([reload(), reloadTree()])
    void switchTo(n)
  }

  /** 应用内的输入框，Promise 形式——调用处跟原来用 window.prompt 一样直。 */
  const askText = (title: string, initial: string) =>
    new Promise<string | null>((resolve) => setPrompt({ title, initial, resolve: (v) => { setPrompt(null); resolve(v) } }))
  const askConfirm = (req: Omit<ConfirmRequest, 'resolve'>) =>
    new Promise<boolean>((resolve) => setConfirmReq({ ...req, resolve: (ok) => { setConfirmReq(null); resolve(ok) } }))
  const askNode = (title: string, exclude: Set<string>) =>
    new Promise<string | null>((resolve) => setPicker({ title, exclude, resolve: (v) => { setPicker(null); resolve(v) } }))

  async function renameNode(row: TreeRow) {
    const title = (await askText('改个名字', row.title))?.trim()
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
    const paths = await api.notePaths(row.note_id)
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
  function openWritingPlan() {
    const parents = tree.filter((r) => r.child_count > 0)
    if (parents.length === 0) {
      toast('无限续写对着一棵子树跑——先建一篇笔记，往它下面放几篇')
      return
    }
    const mine = current
      ? tree.find((r) => r.note_id === current.id)?.parent_note_id
      : undefined
    const preferred = parents.find((r) => r.note_id === mine) ?? parents[0]
    setWritingPlanParent(preferred)
    if (parents.length > 1) {
      toast(`已打开「${preferred.title}」的无限续写——想换一棵，在树上右键选`)
    }
  }

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
          reload(); reloadTree()
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
      reload(); reloadTree()
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
        onClick={() => switchTo(n)}
      >
        <div className="t">{displayTitle(n)}</div>
        {n.content.trim() && (
          <div className="muted" style={{ fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {(() => {
              const s = searchResults !== null ? matchSnippet(n.content, noteQuery) : null
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
        <div className="muted" style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {/* 在哪个文件夹下：搜索命中几十条时，这是区分同名笔记的唯一线索 */}
            {(() => { const row = tree.find((r) => r.note_id === n.id); const parent = row && row.parent_note_id !== api.ROOT_ID ? tree.find((r) => r.note_id === row.parent_note_id) : undefined; return parent ? displayTitle(parent) + ' · ' : '' })()}
            {fmtDate(n.updated_at)}
          </span>
          {/* 「移动到文件夹」的下拉没了：树上靠拖拽和右键菜单移动，一个
              只能选一层的下拉表达不了任意深度的树。 */}
          <span
            style={{ flexShrink: 0, opacity: n.pinned ? 1 : 0.35 }}
            title={n.pinned ? '取消置顶' : '置顶'}
            onClick={(e) => { e.stopPropagation(); togglePin(n) }}
          >
            <i className={'bx ' + (n.pinned ? 'bxs-pin' : 'bx-pin')} />
          </span>
          <span
            style={{ flexShrink: 0 }}
            title="删除（5 秒内可在提示里撤销）"
            onClick={(e) => { e.stopPropagation(); remove(n) }}
          >
            <i className="bx bx-x" />
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
    let draft: { title: string; content: string; at: number } | null = null
    try {
      const raw = localStorage.getItem('memoket-note-draft:' + n.id)
      if (raw) draft = JSON.parse(raw) as { title: string; content: string; at: number }
    } catch { draft = null }
    if (draft && draft.content !== n.content && draft.at > Date.parse(n.updated_at)) {
      setTitle(draft.title || n.title)
      setContent(draft.content)
      toast('上次没存上的内容已恢复到这篇里，会在下一次自动保存时存回去')
    } else {
      setTitle(n.title)
      setContent(n.content)
      if (draft) { try { localStorage.removeItem('memoket-note-draft:' + n.id) } catch { /* 无所谓 */ } }
    }
    // 骨架跟着笔记读回来，**不是清空**。清空那版的后果是「一会儿就没了」：
    // 换一篇、刷新页面、甚至无限续写开着「跟随」自动切到下一段，骨架都没了，
    // 而 harness 下一轮还得重新花一次模型调用生成一份。
    setSpine(n.spine ?? '')
    setBeats(n.beats ?? [])
    // 已经有骨架的笔记，打开时不要 8 秒后又生成一遍——之前每开一篇就一次模型
    // 调用，模型连不上时每开一篇弹一个错（实拍）。以打开时的正文为基线，改够
    // 20 字才重算。
    lastSkeletonContent.current = n.spine ? n.content : ''
    setRevisions([])
    setTapMeta(null)
    if (loading !== 'note-harness') { setHarnessDone(false); harnessDoneRef.current = false; if (!pausedRef.current) setNoteHarnessStatus('') }
    setPausedRun(null)
    syncTab(n)
    // 找回跑到一半停下来等处置的那次运行。
    //
    // **SSE 流断了之后它就再也找不回来了**——关标签页、后端重启、网络抖一下，
    // 快照留在库里，而 run_id 只存在于那条已经断掉的流里。用户看到的是「我
    // 明明点了智能续写，现在什么都没有」。这个接口是它唯一的入口。
    void api.listPausedRuns()
      .then((runs) => {
        const mine = runs.find((r) => r.note_id === n.id)
        if (mine) {
          // 接口本来就返回 mode，原来这里写死成 'write'——一次「打磨」跑出来的
          // 暂停，恢复之后所有提示都说成「智能续写」。
          const mode = mine.mode === 'polish' ? 'polish' : 'write'
          setPausedRun({ id: mine.id, noteId: n.id, mode })
          setNoteHarnessStatus(
            `上次${mode === 'polish' ? '打磨' : '智能续写'}写到第 ${mine.round} 轮停下来等你处置`)
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
    const timer = setTimeout(() => runProbe(probe, { notes, tree, switchTo, openVirtual, openInSplit, newNote, removeWithSubtree, remove, syncTab, openWritingPlan, formatNote, setSelectionMenu, setPaneFocus, setContent, setTreeMenu, setTabs, setTabMenu, setShowShortcuts, setReviewEachRound, setQuick, setNoteQuery, setFocusMode, editorViewRef, actionsRef, harnessProbeDone, moveNodeTo }), 800)
    return () => clearTimeout(timer)
    // notes 也要在依赖里：探针体里用到它，只依赖 tree 的话拿到的是笔记还没
    // 加载完时的空数组，判空之后静默跳过——实拍时「开三个标签」的探针
    // 一个都没开出来，查了两轮才发现是这个。探针体里的其它闭包故意不进依赖：
    // 每次它们变都重跑探针会重复开标签 / 重复建笔记。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tree, notes])

  useEffect(() => {
    reload().then((list) => {
      if (!list.length) return
      // 回到上次看的那篇（标签页已经跨启动保住了，正文也该回到同一篇），
      // 没记录才退回最近编辑的。探针要的是确定的起点，一律最近编辑的。
      let last: string | null = null
      try { if (!new URLSearchParams(location.search).get('probe')) last = localStorage.getItem('memoket-note-active:' + api.getUser()) } catch { /* 无所谓 */ }
      open(list.find((n) => n.id === last) ?? list[0])
    })
    reloadTree()
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
    const t = setTimeout(() => {
      api.listNotes(noteQuery).then(setSearchResults).catch(() => {})
    }, 300)
    return () => clearTimeout(t)
  }, [noteQuery])

  // 摄入是后台任务。任务结束时刷一次树——不刷的话「已入库」的 ⇡ 要等下次
  // 打开应用才出现，用户会以为存入没成功、再存一遍。
  // 跑的过程要看得见：实拍点「存入知识库」后 4 秒界面上什么都没有（只有引用页里
  // 有一行），跑完也只有树上多个 ⇡。状态栏挂一个「存入知识库中… 已抽出 N 条」，结束
  // 给一条 toast（错误也说）。
  const [jobInfo, setJobInfo] = useState<{ status: string; facts: number; detail: string } | null>(null)
  useEffect(() => {
    setIngestActive(!!job)
    if (!job) { setJobInfo(null); return }
    const ctrl = new AbortController()
    let last: { status: string; facts: number; detail: string } = { status: 'queued', facts: 0, detail: '' }
    setJobInfo(last)
    api.watchJob(job, (j) => {
      last = { status: String(j.status ?? ''), facts: Number(j.facts ?? 0), detail: String(j.detail ?? '') }
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

  async function newNote() {
    await save()
    const n = await api.createNote('', '')
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
    try {
      const n = await api.saveNote(current.id, title, content)
      setCurrent(n)
      setSaveStatus({ at: Date.now() })
      try { localStorage.removeItem('memoket-note-draft:' + current.id) } catch { /* 无所谓 */ }
      await Promise.all([reload(), reloadTree()])
    } catch (e) {
      setSaveStatus({ at: Date.now(), error: String(e) })
      // **没存上的正文先落到本机**：后端崩了 / 网断了的那几秒里用户还在写，
      // 这时关掉应用就全没了。下次打开这篇如果库里的版本更旧，把草稿放回去。
      try { localStorage.setItem('memoket-note-draft:' + current.id, JSON.stringify({ title, content, at: Date.now() })) } catch { /* 无所谓 */ }
      throw e
    }
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
      else if (key === '/') { e.preventDefault(); setShowShortcuts((v) => !v) }
      // 折叠左/右栏。Trilium 没给默认键，我们给 ⌘\ 和 ⌘⇧\
      else if (key === '\\' && e.shiftKey) { e.preventDefault(); setPanes((p) => ({ ...p, rightOn: !p.rightOn })) }
      else if (key === '\\') { e.preventDefault(); setPanes((p) => ({ ...p, leftOn: !p.leftOn })) }
      // ⌘/Ctrl+⇧+F 一键格式化。加 shift 是为了不跟浏览器/编辑器的「查找」撞
      else if (key === 'f' && e.shiftKey) { e.preventDefault(); formatNote() }
      // ⌘F：焦点不在编辑器里（比如刚点过树）时 CM 的 searchKeymap 收不到，这里兜一下
      else if (key === 'f') { const v = editorViewRef.current; if (v && !v.hasFocus && current) { e.preventDefault(); openSearchPanel(v); v.focus() } }
      // 标签：⌘T 新开、⌘W 关掉当前、⌘1..9 跳到第 n 个。跟浏览器一致，
      // 不需要学。⌘9 是**最后一个**（不是第九个）——同样是浏览器的约定。
      else if (key === 't' && e.shiftKey) { e.preventDefault(); reopenLastTab() }
      else if (key === 't') { e.preventDefault(); newNote() }
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
      } else if (/^[1-9]$/.test(key)) {
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
      if (!view || !sel || sel.empty) return
      setSlash({
        item: { key: 'custom', label: '自定义提示', icon: 'bx-message-dots',
                hint: '对选中的这段做点什么', needsPrompt: true,
                placeholder: '例如：改写成给投资人看的口吻 / 拆成三条要点' },
        from: sel.from, to: sel.to, ...at,
      })
      return
    }
    // Keep the menu open (showing a spinner via selectionBusy) instead of
    // closing it immediately -- otherwise a slow LLM call leaves no
    // indication anything is happening at the spot the user right-clicked.
    setSelectionBusy(action)
    try {
      if (action === 'verify') {
        const r = await api.verifySelection(content, selection)
        setVerifyFindings(r.findings)
      } else if (action === 'trace') {
        // 来龙去脉：这段涉及的事情按时间怎么演进的。**用户不写问题**——
        // 问题由后端拼（判据 1）。结果落在右栏的「来龙去脉」标签里，
        // 不是弹层：判据 2，看一条旧记录不该离开这一页。
        const r = await api.traceMemory(selection)
        setTrace({ answer: r.answer, facts: r.facts, at: new Date().toISOString() })
        // 结果落在右栏「脉络」——要把那个标签切过去，不然用户等了 40 秒只看到角标变了（实拍）
        setPaneFocus({ id: 'trace', n: Date.now() })
      } else if (action === 'expand') {
        const r = await api.expandSelection(content, selection)
        if (r.revisions.length === 0) toast(r.note || '模型认为不需要补充上下文。', r.note ? 'error' : undefined)
        else if (!applyAsDiff(r.revisions, '扩展上下文')) toast('建议对不上正文（锚点找不到），没有改动。')
      } else {
        // 到这里只剩 rewrite / polish：custom 在函数最上面提前返回了，
        // verify / expand 在前面的分支里处理完了。
        // **这个断言是有前提的**——曾经因为 custom 的分支丢了、断言还在，
        // 编译器不报错而线上直接 422（intent 只认 rewrite/polish）。
        const r = await api.rewriteSelection(
          content, selection, action as 'rewrite' | 'polish', spine, beats)
        if (r.revisions.length === 0) toast(r.note || '模型没有给出修改建议。', r.note ? 'error' : undefined)
        else if (!applyAsDiff(r.revisions, action === 'polish' ? '润色' : '重写')) toast('建议对不上正文（锚点找不到），没有改动。')
      }
    } catch (e) {
      toast(`操作失败：${friendlyError(e)}`, 'error')
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
    const leaving = current
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
      if (!undone) api.deleteNote(n.id).then(() => { void reloadTree(); void reload() }).catch(() => { void reloadTree(); void reload() })
    }, 5000)
    toastAction(`已删除「${displayTitle(n)}」${ids.size > 1 ? `和它下面的 ${ids.size - 1} 篇` : ''}`, '撤销', () => {
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
    setLoading('skeleton')
    try {
      const r = await api.genSkeleton(title, content)
      setSpine(r.spine)
      setBeats(r.beats)
      await persistSkeleton(r.spine, r.beats)
    } catch (e) {
      // 后台自动跑的失败不打扰人（用户没点任何东西）；点「生成骨架」失败才提示
      if (background) void api.clientLog('warn', '后台骨架生成失败：' + friendlyError(e), '', 'skeleton')
      else toast('生成骨架失败：' + friendlyError(e), 'error')
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
    // 一个字都没有、标题也空：模型只能编。让用户先给个方向
    if (!content.trim() && !title.trim()) { toast('先写个标题或几句话，AI 才知道往哪写'); return }
    setLoading('tap')
    setTapMeta(null)
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
      const { truncated } = await api.magicTap(
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
        (g) => { if (g.hint) toast(g.hint, 'error') },
        following,
        title,
      )
      // 流完了再统一修一次「**标题：**」这类粗体（后端落盘路径有同样一步，续写是纯客户端拼的）
      const fixed = fixBoldPunct(inserted)
      if (fixed !== inserted) { inserted = fixed; setContent(head + inserted + tail) }
      // 撞 token 上限停在句中（实拍「…写成事项已经完成」没句号）：已写的留着，说一声
      if (truncated) toast('这段撞到长度上限，补了一次尾还没收住——把光标放在末尾再点一次接着写', 'error')
    } catch (e) {
      if ((e as Error).name !== 'AbortError') { if (isLlmUnreachable(e)) toastAction('续写失败：' + friendlyError(e), '打开设置', () => void openVirtual('app:settings', '设置'), 8000); else toast('续写失败：' + friendlyError(e), 'error') }
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
  /** 往某一轮的记录里打补丁。事件是分散到达的（round-start / tool-calls /
   * evaluate / policy 各一条），先到的先建这一轮的空壳，后到的往上补。 */
  function patchRound(round: number, patch: Partial<AgentRound>) {
    setAgentRounds((rs) => {
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
    const h: api.NoteHarnessHandlers = {
      onSkeleton: (s, b) => {
        if (currentRef.current?.id !== noteId) return
        setSpine(s); setBeats(b)
        // 自动生成的一样要存——否则下一轮/下一次打开又得重新生成一份
        void persistSkeleton(s, b, noteId)
        setNoteHarnessStatus('已自动生成骨架，开始第一轮')
      },
      onRoundStart: (d) => {
        if (currentRef.current?.id !== noteId) return
        // skipped_continue：上一轮评分说重复是当前最弱的一项，这一轮
        // 后端直接跳过续写、只再跑一次聚焦修订，不会有 delta 事件
        // 跟着到达（见 TRACELOG [25]）——状态文案要如实说"在清理重复"，
        // 不能说"续写中"，不然用户会以为卡住了；也不能预留续写用的
        // 空行，因为这一轮根本不会有内容来填上这个空行。
        patchRound(d.round, {
          cleanupOnly: !!d.skipped_continue,
          revisions: d.revisions_applied,
    })
        if (d.skipped_continue) {
          setNoteHarnessStatus(`第 ${d.round} 轮：修订 ${d.revisions_applied} 处，正在清理重复内容…`)
          return
    }
        setNoteHarnessStatus(`第 ${d.round} 轮：修订 ${d.revisions_applied} 处，续写中…`)
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
        setContent((c) => {
          const next = applyRevision(c, { id: '', op: r.op as Revision['op'], anchor: r.anchor, anchor_end: r.anchor_end, text: r.text, reason: r.reason, sources: r.sources ?? [] })
          liveContentRef.current = next
          return next
    })
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
          const head = base.slice(0, pos).replace(/\n*$/, '\n\n')
          const tail = base.slice(pos).replace(/^\n*/, '\n\n')
          insertCursorRef.current = head.length
          const next = head + tail
          liveContentRef.current = next
          setContent(next)
        }
        setNoteHarnessStatus((s) => s.replace(/续写中…$/, `写到「${d.section}」这一节…`))
        requestAnimationFrame(() => {
          const view = editorViewRef.current
          if (view && insertCursorRef.current != null) view.dispatch({ effects: EditorView.scrollIntoView(Math.min(insertCursorRef.current, view.state.doc.length), { y: 'center' }) })
        })
      },
      onDelta: (text) => {
        if (currentRef.current?.id !== noteId) return
        {
          // 从 liveContentRef 算，不用 updater：updater 的执行时机跟闭包里的游标
          // 对不上就会漂（magic tap 那边实拍过）
          const c = liveContentRef.current
          const cur = insertCursorRef.current
          let next: string
          if (cur != null && cur <= c.length) {
            next = c.slice(0, cur) + text + c.slice(cur)
            insertCursorRef.current = cur + text.length
          } else next = c + text
          liveContentRef.current = next
          setContent(next)
        }
        // 同时流进 Agent 运行面板。两段式之后编辑器有几十秒完全不动
        // （检索规划是非流式的），面板里能实时看到写出来的字，比一行
        // 干等的状态文案有用得多。
        setAgentRounds((rs) => {
          if (!rs.length) return rs
          const next = [...rs]
          const last = next[next.length - 1]
          next[next.length - 1] = { ...last, streamed: (last.streamed ?? '') + text }
          return next
    })
      },
      onRoundEnd: (_round, serverContent) => {
        if (currentRef.current?.id !== noteId) return
        // 用服务端这一轮结束时的正文对齐。客户端按 anchor 重放修订会跑偏
        // （引用被改烂、分隔符不一致），服务端的才是真的。
        if (typeof serverContent === 'string' && serverContent && serverContent !== liveContentRef.current) {
          // 记一笔：本地重放的正文跟服务端差了多少。差得多说明客户端的重放逻辑
          // 又跑偏了——这是「agent 输出跟编辑器对不对得上」的证据，不是靠感觉。
          void api.clientLog('warn', `round ${_round}: 本地正文 ${liveContentRef.current.length} 字 vs 服务端 ${serverContent.length} 字，已用服务端的`, '', 'harness-sync')
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
        if (currentRef.current?.id !== noteId) return
        const beatScore = d.scores['beat_coverage']
        if (beatScore) setBeatCoverage(beatScore)
        setAgentRounds((rs) => {
          if (!rs.length) return rs
          const next = [...rs]
          next[next.length - 1] = {
            ...next[next.length - 1],
            scores: d.scores, status: d.status, weakest: d.weakest,
          }
          return next
    })
        if (d.status === 'continue' && d.weakest) {
          setNoteHarnessStatus(`这一轮评分：${d.weakest} 还不够，下一轮优先改这个`)
    }
      },
      onPhase: (d) => {
        if (currentRef.current?.id !== noteId) return
        // 用 patchRound 而不是改"最后一张卡片"：修订 pass 跑在
        // round-start **之前**，第 1 轮的 edit 阶段到达时卡片还不存在，
        // 直接改最后一张会把它整段丢掉——而那正是最想看的第一段。
        patchRound(d.round, { phase: d.phase, phaseLabel: d.label })
      },
      onPhaseDelta: (d) => {
        if (currentRef.current?.id !== noteId) return
        setAgentRounds((rs) => {
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
        if (currentRef.current?.id !== noteId) return
        patchRound(d.round, { toolCalls: d.calls, toolTruncated: d.truncated })
        setNoteHarnessStatus(`第 ${d.round} 轮：agent 自己查了知识库 ${d.calls.length} 次，续写中…`)
      },
      onPolicy: (d) => {
        if (currentRef.current?.id !== noteId) return
        // round 0 = 开跑前用历史运行记录定的初始策略，还没有对应的轮次卡片，
        // 挂到第 1 轮上；其余挂在产生它的那一轮
        patchRound(Math.max(1, d.round), { policyReasons: d.reasons, policy: d.policy })
      },
      onDropped: (detail) => {
        // 防线丢掉一条修订不是出错，收在单独的可折叠区里，不占报错的红色。
        if (currentRef.current?.id !== noteId) return
        setAgentRounds((rs) => {
          if (!rs.length) return rs
          const next = [...rs]
          next[next.length - 1] = {
            ...next[next.length - 1],
            dropped: [...next[next.length - 1].dropped, detail],
          }
          return next
    })
      },
      onCheckHit: (d) => {
        // 代码判据当场判不合格，这一轮不会再花模型调用去打分。不标出来的话
        // 用户看到一个 0 分，不知道是谁判的、为什么这轮这么快。
        if (currentRef.current?.id !== noteId) return
        setAgentRounds((rs) => {
          if (!rs.length) return rs
          const next = [...rs]
          next[next.length - 1] = { ...next[next.length - 1], checkHit: d }
          return next
        })
      },
      onWarning: (d) => {
        // 一条 middleware 抛异常了。循环继续跑（能力分包的隔离好处），但这一轮
        // 少了那个能力——后端注释写着「不能是静默的」，可在这之前前端根本没接
        // 这个事件，发出来的警告全被丢掉了。
        if (currentRef.current?.id !== noteId) return
        toast(`「${d.middleware}」这一步出错了，本轮少了这个能力：${d.error}`, 'error')
      },
      onError: (detail) => {
        if (currentRef.current?.id !== noteId) return
        // 后端的 error 事件都是可恢复的降级，流还在继续——记在这一轮上
        // 给用户看，但不打断运行
        setAgentRounds((rs) => {
          if (!rs.length) return rs
          const next = [...rs]
          next[next.length - 1] = {
            ...next[next.length - 1],
            errors: [...next[next.length - 1].errors, detail],
          }
          return next
    })
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
          : reason === 'stalled' ? '连续几轮没有新内容，自动停止'
          : '到达轮数上限，自动停止'
        const delta = liveContentRef.current.length - runBaseRef.current.length
        const summary = `${label} · ${agentRoundsRef.current || 1} 轮 · ${delta === 0 ? '正文没有改动' : `${delta > 0 ? '+' : ''}${delta} 字`}`
        setNoteHarnessStatus(summary)
        harnessDoneRef.current = true
        setHarnessDone(true)
        toast(`智能续写：${label}`, reason === 'blocked' ? 'error' : undefined)
        notifyIfHidden('MEMOKET NOTE · 智能续写', `${notes.find((x) => x.id === noteId)?.title || '笔记'}：${label}`)
      },
    }
    // **统一挡一层**：run 属于 noteId 那篇，用户切走之后它的每个事件都不该碰
    // 现在显示的这篇——之前只有一半 handler 各自写了这条判断，漏掉的那半
    // （onDone 的正文对齐、骨架）把 A 的内容和骨架写进了 B（探针实拍两次）。
    // onDone 自己处理了跨笔记的情况（只提示不动正文），其余一律忽略。
    const guarded: api.NoteHarnessHandlers = {}
    for (const [k, fn] of Object.entries(h) as [keyof api.NoteHarnessHandlers, (...a: unknown[]) => void][]) {
      guarded[k] = ((...args: unknown[]) => {
        if (k !== 'onDone' && currentRef.current?.id !== noteId) return
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
      return
    }
    if (!current) return
    if (!content.trim() && !title.trim()) { toast('先写个标题或几句话，智能续写才有东西可接'); return }
    const noteId = current.id
    // 起跑时记一笔发出去的是什么：哪篇、多少字、骨架开头——探针实拍过一次
    // 「跑在了另一篇上」，没有这条日志只能猜。
    void api.clientLog('warn', `harness start note=${noteId} title=${current.title.slice(0, 20)} content=${content.length} spine=${spine.slice(0, 30)} beats=${beats.length}`, '', 'harness-start')
    setLoading('note-harness')
    setNoteHarnessStatus('启动中…')
    setHarnessDone(false); harnessDoneRef.current = false
    setBeatCoverage(null)
    setAgentRounds([])
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
      )
    } catch (e) {
      if ((e as Error).name !== 'AbortError') toast(
        (mode === 'polish' ? '打磨' : '智能续写') + '失败：' + friendlyError(e), 'error')
    } finally {
      setLoading('')
      // 停在「等你处置」时不能清——那句提示刚在 onDone 里设好，清掉就等于
      // 两个按钮凭空出现、没有任何说明。
      if (!pausedRef.current && !harnessDoneRef.current) setNoteHarnessStatus('')
      abortRef.current = null
      reload()
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
    load()
    window.addEventListener('provider-changed', load)
    return () => window.removeEventListener('provider-changed', load)
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
    if (!content.trim()) return
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
  async function importMarkdown(files: FileList | null, under: string = api.ROOT_ID) {
    const list = Array.from(files ?? []).filter((f) => /\.(md|markdown|txt)$/i.test(f.name))
    if (list.length === 0) return
    await save()
    const strip = (name: string) => name.replace(/\.(md|markdown|txt)$/i, '')
    if (list.length === 1) {
      const n = await api.createNote(strip(list[0].name), await list[0].text(), under)
      await reload(); await reloadTree()
      open(n); return
    }
    const parent = await api.createNote(`导入 ${fmtDate(new Date().toISOString())}`, `从 ${list.length} 个文件导入。`, under)
    let first: Note | null = null
    for (const f of list) {
      const n = await api.createNote(strip(f.name), await f.text(), parent.id)
      first ??= n
    }
    await reload(); await reloadTree()
    toast(`已导入 ${list.length} 篇，放在「${parent.title}」下面`)
    open(first ?? parent)
  }

  /** 全部接受：只是把标记清掉，正文保持现状。 */
  function acceptAllDiff() {
    editorViewRef.current?.dispatch({ effects: acceptAllHunks.of(null) })
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
    setLoading('note-harness')
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
      setLoading('')
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
    if (!before.trim()) return
    // 之前复用 'skeleton'：打开一篇没骨架的笔记自动生成骨架时，「智能排版」也跟着转圈（实拍）
    setLoading('restructure')
    try {
      const r = await api.restructureNote(current.id, title, before)
      if (r.detail) toast(r.detail, 'error')
      if (!r.changed) { toast(r.detail ? '没有改动' : '结构已经很清楚了，没什么可调的'); return }
      const after = formatMarkdown(r.content)
      const v = editorViewRef.current
      if (!v) return
      // 只换变了的那一段：整篇替换会把之前各层提案的位置全映射到一个点上，账本就空了
      const change = minimalChange(before, after)
      if (change) v.dispatch({ changes: change })
      setContent(after)
      pushDiff('智能排版', before, after)
      const skipped = r.skipped.length ? `，跳过 ${r.skipped.length} 处` : ''
      toast(`调整了 ${r.ops} 处结构${skipped}，可以逐处接受或撤回`)
    } catch (e) {
      toast(`排版失败：${friendlyError(e)}`, 'error')
    } finally {
      setLoading('')
    }
  }

  /** `/` 选中一项之后的入口。需要提示词的先弹输入框，其余的当场做完。 */
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
      try {
        const r = await api.transcribeOnly(new Blob(chunks, { type: 'audio/webm' }))
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
        push(patchRun.of({
          id, error: `转写失败：${friendlyError(e)}`, expanded: true,
        }))
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
        const r = await api.tableFromImage(f)
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
      // 音频：先传上去插一个播放器，再转写出文字稿
      push(patchRun.of({ id, phase: '上传中…' }))
      const a = await api.uploadAsset(f)
      push(logRun.of({ id, at: '已上传', text: `${a.name}（${Math.round(a.bytes / 1024)}KB）` }))
      push(patchRun.of({ id, phase: '转写中…' }))
      const t = await api.transcribeOnly(f, f.name)
      const text = (t.text || '').trim()
      const v = editorViewRef.current!
      const before = v.state.doc.toString()
      const player = `\n<audio controls src="${a.url}"></audio>\n\n`
      v.dispatch({
        changes: { from: at(), insert: player + (text ? text + '\n\n' : '') },
        effects: endRun.of(id),
      })
      const after = v.state.doc.toString()
      setContent(after)
      pushDiff('插入音频', before, after)
      if (!text) toast('音频已插入，但转写没有出内容')
    } catch (e) {
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
    const id = Math.random().toString(36).slice(2, 10)
    const ctrl = new AbortController()
    runAborts.current.set(id, ctrl)
    setSlash(null)                                   // 输入框收起，交给占位块

    // custom 是「替换选中的这段」，其余是「在光标这里插一块」。两种都先把
    // [from,to) 清掉，产出落在 from。
    const selection = item.key === 'custom' ? view.state.doc.sliceString(from, to) : ''
    view.dispatch({
      changes: { from, to, insert: '' },
      selection: { anchor: from },
      effects: startRun.of({ id, from, label: item.label }),
    })
    const before = view.state.doc.toString()
    const push = (fx: StateEffect<unknown>) => editorViewRef.current?.dispatch({ effects: fx })

    try {
      const block = await api.composeBlock(
        { note_id: current.id, title, content: before, cursor: from,
          mode: item.key as api.BlockMode, prompt, selection },
        {
          onPhase: (label) => {
            push(patchRun.of({ id, phase: label }))
            push(logRun.of({ id, at: '阶段', text: label }))
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
                : weak.map(([k, v]) => `${k}：${v.note}`).join('；') || status,
            }))
          },
          onError: (d) => push(logRun.of({ id, at: '出错', text: d })),
        },
        ctrl.signal)

      const v = editorViewRef.current
      if (!v) return
      const text = (block || '').trim()
      if (!text) {
        push(patchRun.of({ id, error: '没有产出内容', expanded: true }))
        return                                       // 占位块留着，让用户看到为什么
      }
      const run = v.state.field(runsField, false)?.find((r) => r.id === id)
      const at = Math.max(0, Math.min(run?.from ?? from, v.state.doc.length))
      const b2 = v.state.doc.toString()
      v.dispatch({ changes: { from: at, insert: text + '\n\n' }, effects: endRun.of(id) })
      const after = v.state.doc.toString()
      setContent(after)
      pushDiff(item.label, b2, after)
      // 结果落下来要看得见：跑了 100 秒出的图在折叠线下（实拍），把落点滚到视口上部
      requestAnimationFrame(() => editorViewRef.current?.dispatch({ effects: EditorView.scrollIntoView(at, { y: 'start', yMargin: 80 }) }))
    } catch (e) {
      if (ctrl.signal.aborted) {
        push(endRun.of(id))                          // 用户自己停的，不留残骸
      } else {
        push(patchRun.of({
          id, error: e instanceof Error ? e.message : String(e), expanded: true,
        }))
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

  /** 分屏的第二栏。真笔记只读渲染；虚拟节点走 KbNoteView。
   *  **是函数不是组件**：写成 App 内部的组件的话每次 render 都是新类型，
   *  里面的 MarkdownEditor 会跟着重挂，滚动位置全丢。 */
  function renderSplit(id: string) {
    const note = notes.find((n) => n.id === id)
    const row = allRows.find((r) => r.note_id === id)
    const title = note ? displayTitle(note) : (row?.title ?? id)
    return (
      <>
        <div className="split-head">
          <span className="split-title" title={title}>{title}</span>
          {note && <button className="icon-btn" title="在标签里打开" onClick={() => void switchTo(note)}><i className="bx bx-link-external" /></button>}
          <button className="icon-btn" title="关闭分屏" onClick={() => setSplit(null)}><i className="bx bx-x" /></button>
        </div>
        <div className="split-body">
          {api.isVirtualId(id)
            ? <KbNoteView id={id} rows={allRows} onOpen={(x) => openInSplit(x)}
                          onOpenNote={(nid) => { const n = notes.find((x) => x.id === nid); if (n) void switchTo(n) }}
                          onCite={current ? (fid, text) => insertAtCursor(`${text} [${fid}]`) : null} />
            : note
              ? <MarkdownEditor content={note.content} readOnly />
              : <p className="muted">这篇笔记已经不在了。</p>}
        </div>
      </>
    )
  }

  // ---------------------------------------------------------------- 渲染

  actionsRef.current = { runNoteHarness, runMagicTap, handleSelectionAction, runHarness, ingestCurrentNote, runBlock, dropIfStillEmpty, collapseAll, pushDiff }

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
      {picker && <NotePicker req={picker} rows={tree} />}
      <input ref={importInput} type="file" accept=".md,.markdown,.txt" multiple style={{ display: 'none' }}
             onChange={(e) => { void importMarkdown(e.target.files, importUnder.current); e.target.value = '' }} />
      {quick && <QuickView note={quick} onClose={() => setQuick(null)} onOpen={(n) => void switchTo(n)} />}
      {prompt && <TextPrompt req={prompt} />}
      {confirmReq && <ConfirmDialog req={confirmReq} />}
      <Toaster />
      <CommandPalette onOpenNote={switchTo} onInsertFact={insertAtCursor} />
      {showShortcuts && <ShortcutsPanel onClose={() => setShowShortcuts(false)} />}
      {writingPlanParent && (
        <WritingPlanPanel
          parent={writingPlanParent}
          onClose={() => setWritingPlanParent(null)}
          onNoteChanged={() => { reload(); reloadTree() }}
          harness={harness}
          onRun={() => runHarness(writingPlanParent)}
          onToggleFollow={() => setHarness((h) => (h ? { ...h, follow: !h.follow } : h))}
        />
      )}
      {/* 关掉面板不再停止 harness（见 HarnessState 注释）——这块是面板关着
         的时候唯一能看到"还在跑"的地方，点了直接重新打开对应文件夹的面板。 */}
      {harness?.running && !writingPlanParent && (
        <div
          className="card"
          style={{ position: 'fixed', right: 16, bottom: 16, zIndex: 60, width: 260, cursor: 'pointer' }}
          onClick={() => {
            // 从树里找回那一行——正在跑的 harness 只记了 id 和标题，而面板
            // 要的是完整的 TreeRow。找不到就不开（子树可能已经被删了）。
            const row = tree.find((r) => r.note_id === harness.folderId)
            if (row) setWritingPlanParent(row)
          }}
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

      <input
        ref={filePick}
        type="file"
        style={{ display: 'none' }}
        accept={pickKind.current === 'image' ? 'image/*' : 'audio/*'}
        onChange={(e) => { void onPickFile(e.target.files); e.target.value = '' }}
      />
      {slash?.item.needsPrompt && (
        <SlashPrompt
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
          <button className="icon-btn" disabled={!histState.back} title="后退（⌘[）" onClick={() => goHistory(-1)}><i className="bx bx-left-arrow-alt" /></button>
          <button className="icon-btn" disabled={!histState.fwd} title="前进（⌘]）" onClick={() => goHistory(1)}><i className="bx bx-right-arrow-alt" /></button>
        </span>
        <TabBar
          tabs={tabs}
          activeId={activeTabId}
          onSelect={(id) => activateTab(tabs.find((x) => x.id === id))}
          onClose={closeTab}
          onNew={newNote}
          onContextMenu={(tab, at) => setTabMenu({ tab, at })}
          onReorder={reorderTab}
        />
      </div>
      <div className="shell-main">
      {/* 启动栏 —— 照 Trilium 的 58px 竖排。放的是**跨笔记的入口**：
          知识库、Skill、无限续写、设置、用户。判据见 docs/product-north-star.md：
          记忆是一等公民，不该藏在某个按钮后面的弹层里。 */}
      <div className="launcher-pane">
        <div className="launcher-logo" title="MEMOKET NOTE"><Logo size={30} /></div>
        <button className="launcher-btn" title="新建笔记（⌘N）" onClick={newNote}><i className="bx bx-plus" /></button>
        <button className="launcher-btn" title="全局搜索：笔记 + 知识库（⌘K）"
                onClick={() => window.dispatchEvent(new CustomEvent('open-command-palette'))}><i className="bx bx-search" /></button>
        <button className={'launcher-btn' + (virtualId === 'app:import' ? ' active' : '')}
                title="导入：.md 文件 / Obsidian / Evernote / Notion / Apple Notes / 批量文件"
                onClick={() => void openVirtual('app:import', '导入')}><i className="bx bx-import" /></button>
        <div className="launcher-spacer" />
        {/* 设置和 Skill 是「特殊笔记」：开标签、进中栏，跟别的笔记一样对待
            （照 Trilium：选项是隐藏子树里的笔记，不是弹层）。 */}
        <button className={'launcher-btn' + (virtualId === 'app:skills' ? ' active' : '')} title="写作 Skill"
                onClick={() => void openVirtual('app:skills', '写作 Skill')}><i className="bx bx-extension" /></button>
        <button className="launcher-btn" title="无限续写：对着一棵子树自动一段接一段"
                onClick={openWritingPlan}><i className="bx bx-rocket" /></button>
        <button className={'launcher-btn' + (virtualId === 'app:settings' ? ' active' : '')} title="设置：LLM 供应商"
                onClick={() => void openVirtual('app:settings', '设置')}><i className="bx bx-cog" /></button>
        <button className={'launcher-btn left-pane-toggle' + (panes.leftOn ? '' : ' collapsed')}
                title={panes.leftOn ? '收起左栏（⌘\\）' : '展开左栏（⌘\\）'}
                onClick={() => setPanes((p) => ({ ...p, leftOn: !p.leftOn }))}><i className="bx bx-chevrons-left" /></button>
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
          <i className="bx bx-search" />
          <input
            placeholder="快速搜索"
            title="搜标题和正文；⌘K 是全局搜索（含知识库）"
            value={noteQuery}
            onChange={(e) => setNoteQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setNoteQuery('')
              // 回车开第一条命中（Trilium 的快速搜索也是），不用再伸手去点
              else if (e.key === 'Enter' && visibleNotes.length && noteQuery.trim()) { void switchTo(visibleNotes[0]); setNoteQuery('') }
            }}
          />
          {noteQuery && <button className="icon-btn" title="清空" onClick={() => setNoteQuery('')}><i className="bx bx-x" /></button>}
        </div>
        </div>
        {/* 树的滚动容器——笔记一多，没有它树底部就被裁掉且滚不到 */}
        <div className="left-pane-body">
        {searchResults !== null || noteQuery ? (
          // 搜索时不画树：命中就该直接看到，不用先猜它在树的哪一层。
          visibleNotes.length === 0
            ? <p className="muted">没有匹配的笔记。</p>
            : visibleNotes.map(renderNoteItem)
        ) : (
          <NoteTree
            rows={allRows}
            activeNoteId={current?.id ?? virtualId}
            onOpen={openFromTree}
            onToggle={(row) => (api.isVirtualId(row.note_id) ? toggleKbNode(row) : void toggleTreeNode(row))}
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
          <button className="icon-btn" title="定位到当前笔记" onClick={() => setLocateTick((v) => v + 1)}><i className="bx bx-crosshair" /></button>
          <button className="icon-btn" title="折叠全部" onClick={() => void collapseAll()}><i className="bx bx-collapse-vertical" /></button>
        </div>
        )}
      </div>
      )}

      {leftShown && (
        <Gutter side="left" onResize={(dx) => setPanes((p) => ({ ...p, leftW: Math.max(150, Math.min(600, p.leftW + dx)) }))} />
      )}

      <div className="rest-pane">
        {!rightShown && !focusMode && (
          <button className="right-pane-reopen" title="展开右栏（⌘⇧\\）"
                  onClick={() => setPanes((p) => ({ ...p, rightOn: true }))}><i className="bx bx-chevrons-left" /></button>
        )}
        <div className="center-pane">
        <div className="note-pane">
        {/* 标题行固定在滚动区之上（Trilium 的 title-row 是 ScrollingContainer
            的兄弟，50px）。跟正文一起滚走的标题，滚到下面就不知道在写哪篇。 */}
        {current && (
          <div className="title-row">
            <i className={'bx title-icon ' + ((tree.find((r) => r.note_id === current.id)?.child_count ?? 0) > 0 ? 'bx-folder' : 'bx-note')} />
            {/* 标题是占位词（「未命名」）时输入框显示空、把正文首行放在占位符里——
                跟树和标签用同一个 displayTitle，一篇笔记不再有两个名字 */}
            <input
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
        {/* ribbon —— 这篇笔记的元数据。第一件放进来的是**写作骨架**：
            判据 3 说「自主规划、自主执行、检查结果」，那**计划就得看得见**，
            跟正文一起，而不是右栏某个要切过去才有的面板。把计划藏起来，
            用户能看到的就只剩一个转圈的指示器，那等于什么都没说。 */}
        {current && (
          <Ribbon
            noteKey={current.id}
            defaultOpen={(() => { const pr = new URLSearchParams(location.search).get('probe') ?? ''; return pr === 'kb-tab' || pr.startsWith('notekb:') ? 'cites' : pr === 'history-open' ? 'history' : pr.startsWith('ribbon:') ? pr.slice(7) : undefined })()}
            tabs={[{
              id: 'format', title: '格式', icon: 'bx-text',
              activate: true,
              body: (
                <MarkdownToolbar
                  viewRef={editorViewRef}
                  onFormat={formatNote}
                  onRestructure={restructureNote}
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
                refreshTick={ingestTick}
              />,
            }, {
              id: 'links', title: '链接', icon: 'bx-link-alt',
              badge: (content.match(/\]\(note:\/\/[0-9a-f]{12}\)/g) ?? []).length || undefined,
              body: <NoteLinksPanel noteId={current.id} content={content}
                                    onOpen={(id) => { const n = notes.find((x) => x.id === id); if (n) void switchTo(n) }} />,
            }, {
              id: 'history', title: '历史', icon: 'bx-history',
              body: <RevisionHistoryPanel noteId={current.id} currentChars={content.length} currentContent={content}
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
            }] as RibbonTab[]}
          />
        )}
        <div className={'note-scroll' + (current ? ' has-fb' : '')}>
        <div className="note-body">

        {!current ? (
          virtualId === 'app:import' ? (
            <div className="kb-note" style={{ maxWidth: 760 }}>
              <h2 className="kb-note-title"><i className="bx bx-import" /> 导入</h2>
              <div className="card">
                <b>Markdown 文件</b>
                <p className="muted" style={{ margin: '2px 0 8px', fontSize: 12 }}>一个文件一篇；多个文件成一棵子树。想放到某个节点下面，在树上右键那个节点「导入 .md 到这里…」。</p>
                <input type="file" accept=".md,.markdown,.txt" multiple onChange={(e) => { void importMarkdown(e.target.files); e.target.value = '' }} />
              </div>
              <MemoryPanel pendingJob={job} />
            </div>
          ) : virtualId === 'app:settings' ? (
            <div className="kb-note"><h2 className="kb-note-title"><i className="bx bx-cog" /> 设置</h2><SettingsPanel embedded /><h3 className="kb-section-title">个人偏好</h3><PreferencesPanel /></div>
          ) : virtualId === 'app:skills' ? (
            <div className="kb-note" style={{ maxWidth: 900 }}><h2 className="kb-note-title"><i className="bx bx-extension" /> 写作 Skill</h2><SkillsPanel embedded /></div>
          ) : virtualId ? (
            <KbNoteView
              id={virtualId}
              rows={allRows}
              onOpen={(id) => void openVirtual(id)}
              onOpenNote={(id) => { const n = notes.find((x) => x.id === id); if (n) void switchTo(n) }}
              onCite={null}
            />
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
              <button className={'fb-btn primary' + (loading === 'tap' ? ' running' : '')} onClick={runMagicTap}
                      disabled={loading === 'note-harness'}
                      title="magic tap 续写：先查知识库，据此往下写一段（流式）">
                <i className={'bx ' + (loading === 'tap' ? 'bx-stop' : 'bx-edit-alt')} /><span className="fb-label">{loading === 'tap' ? '停止' : '续写'}</span>
              </button>
              <span className="fb-split">
                <button className={'fb-btn primary' + (loading === 'note-harness' ? ' running' : '')}
                        onClick={() => runNoteHarness('write')} disabled={loading === 'tap'}
                        title="智能续写：自动修订 + 自动续写交替，直到相对骨架已经完整才停">
                  <i className={'bx ' + (loading === 'note-harness' ? 'bx-stop' : 'bx-bot')} /><span className="fb-label">{loading === 'note-harness' ? '停止' : '智能续写'}</span>
                </button>
                <button className="fb-btn primary fb-caret-btn" title="打磨 / 逐轮我来定"
                        onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); setFbMenu({ kind: 'harness', at: { x: r.right - 220, y: r.bottom + 4 } }) }}>
                  <i className="bx bx-chevron-down" />
                </button>
              </span>
              <AudioRecorder onTranscript={insertAtCursor} onIngested={setJob} offline={asrOffline} />
              <button className="fb-btn" title="更多"
                      onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); setFbMenu({ kind: 'more', at: { x: r.right - 220, y: r.bottom + 4 } }) }}>
                <i className="bx bx-dots-horizontal-rounded" />
              </button>
              {loading === 'ingest' && <span className="muted" style={{ fontSize: 12 }}><span className="spinner" /></span>}
              {fbMenu && (
                <ContextMenu at={fbMenu.at} onClose={() => setFbMenu(null)} items={fbMenu.kind === 'harness' ? [
                  { label: '打磨（只修不写）', icon: 'bx-brush', disabled: loading === 'note-harness' || !content.trim(),
                    hint: !content.trim() ? '正文是空的' : undefined, onSelect: () => runNoteHarness('polish') },
                  { kind: 'sep' },
                  { label: reviewEachRound ? '逐轮我来定：开' : '逐轮我来定：关', icon: reviewEachRound ? 'bx-checkbox-checked' : 'bx-checkbox',
                    hint: '每轮停下来等你逐条接受/撤回', disabled: loading === 'note-harness',
                    onSelect: () => setReviewEachRound((v) => !v) },
                ] : [
                  { label: '存入知识库', icon: 'bx-brain', disabled: !content.trim() || loading === 'ingest',
                    hint: !content.trim() ? '正文是空的' : undefined, onSelect: () => void ingestCurrentNote() },
                  { label: '分屏对照另一篇…', icon: 'bx-columns', onSelect: () => { void askNode('在右侧分屏打开哪一篇？', new Set([current.id])).then((id) => { if (id && id !== api.ROOT_ID) openInSplit(id) }) } },
                  { kind: 'sep' },
                  { label: '现在存一版', icon: 'bx-bookmark-plus', hint: '历史版本在 ribbon「历史」里', disabled: !content.trim(),
                    onSelect: () => { void save().then(() => api.snapshotNote(current.id)).then(() => toast('已存一版')).catch((e) => toast('存版失败：' + friendlyError(e), 'error')) } },
                  { label: '导出为 .md', icon: 'bx-export', onSelect: exportMarkdown },
                  { label: '导出全部笔记…', icon: 'bx-package', hint: '整库打成 Markdown zip', onSelect: () => window.dispatchEvent(new CustomEvent('export-all')) },
                  { label: '复制正文', icon: 'bx-copy', onSelect: () => void copyMarkdown() },
                  { kind: 'sep' },
                  { label: focusMode ? '退出专注模式' : '专注模式', icon: 'bx-fullscreen', shortcut: '⌘.', onSelect: () => setFocusMode((v) => !v) },
                  { label: '保存', icon: 'bx-save', shortcut: '⌘S', onSelect: () => void save() },
                ]} />
              )}
            </div>
            {/* 暂停 / 运行 / 结果 一条粘在浮动按钮下面的横条：轮末暂停时用户多半已经
                滚到正文底部看新写的内容，两个按钮和那句话如果留在正文顶部就等于没有
                （实拍：只剩状态栏一个「等你处置」）。 */}
            {(pausedRun || ((loading === 'note-harness' || harnessDone) && noteHarnessStatus)) && (
              <div className="harness-sticky">
                <p className="muted harness-line"><i className="bx bx-bot" /> <span style={{ flex: 1, minWidth: 0 }}>{pausedRun ? '这一轮写完了，逐条看过之后：' : noteHarnessStatus}</span>
                  {loading === 'note-harness' && <span className="muted" style={{ marginInlineStart: 8, fontSize: 11 }}>· 运行中正文由 AI 接管，停下来再改</span>}
                  {pausedRun && (
                    /* 轮末暂停：这一轮写完了，等你在正文里逐条接受/撤回。
                       关掉这个开关的话是原来的行为——一口气跑完再处置，而那意味着
                       你在跑的过程中做的处置会被下一轮盖掉。 */
                    <span className="row" style={{ gap: 6, marginInlineStart: 8 }}>
                      <button className="primary" onClick={() => resumePausedRun()}><i className="bx bx-play" /> 接着写</button>
                      <button onClick={() => resumePausedRun(true)}>到此为止</button>
                    </span>
                  )}
                  {harnessDone && !pausedRun && <button className="icon-btn sm" title="关闭" onClick={() => { setHarnessDone(false); harnessDoneRef.current = false; setNoteHarnessStatus('') }}><i className="bx bx-x" /></button>}
                </p>
              </div>
            )}

            {tapMeta && <TapProvenance meta={tapMeta} onDismiss={() => setTapMeta(null)} />}
            {/* 整篇缩进了 4 格以上（从别处粘来的常见）：markdown 会把它整个当成代码块，
                标题不是标题、一片等宽字。给一键去缩进，别让人自己猜为什么渲染不对。 */}
            {current && content.length > 40 && stripCommonIndent(content) !== content && (
              <p className="muted harness-line" style={{ marginBottom: 8 }}>
                <i className="bx bx-info-circle" /> 这篇整体缩进了，Markdown 会把它当成一整块代码，标题和列表都显示不出来。
                <button className="chip" style={{ marginInlineStart: 8 }} onClick={formatNote}><i className="bx bx-align-left" /> 去掉缩进</button>
              </p>
            )}

            {pendingDiff > 0 && (
              <div
                className="row"
                style={{
                  gap: 8, alignItems: 'center', margin: '2px 2px 6px',
                  fontSize: 12, padding: '5px 8px', borderRadius: 6,
                  border: '1px solid var(--line)', background: 'var(--panel)',
                }}
              >
                <span style={{ color: 'var(--ins)' }}>●</span>
                <span>改了 {pendingDiff} 处</span>
                <span className="muted">鼠标移到改动上可以逐处接受、撤回；<a href="#" onClick={(e) => { e.preventDefault(); setPaneFocus({ id: 'changes', n: Date.now() }) }}>按层处置</a>（保留第一次改的、放弃第三次的）</span>
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
              onChange={setContent}
              // AI 在写的时候锁住编辑器：这时手改的字会被轮末的服务端正文盖掉（同步是
              // 服务端权威）。逐轮暂停、跑完、停止都会解锁。
              readOnly={loading === 'note-harness' || loading === 'tap'}
              revisions={revisions}
              onAcceptInline={acceptRevision}
              roundDiff={roundDiff}
              onPendingDiff={setPendingDiff}
              onSelectionContextMenu={(x, y, text) => setSelectionMenu({ x, y, text })}
              onCursorParagraph={setCursorPara}
              onSlash={onSlash}
              onStopRun={stopRun}
              placeholder="开始写…  支持 Markdown 和 ```mermaid 图表。写到一半点 magic tap，会先查你的知识库再续写。"
              viewRef={editorViewRef}
            />
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
        {verifyFindings && (
          <VerifyPanel findings={verifyFindings} onClose={() => setVerifyFindings(null)} />
        )}
        <RightPane
          onCollapse={() => setPanes((p) => ({ ...p, rightOn: false }))}
          defaultTab="memory"
          focusTab={paneFocus}
          tabs={[
            // 记忆是默认标签：边写边浮现的召回（判据 2）。不再是压在所有标签上面的常驻块。
            { id: 'memory', title: '记忆', icon: 'bx-bulb', alwaysShown: true,
              body: current
                ? <RelatedMemory key={ingestTick} content={content} paragraph={cursorPara} onInsert={insertAtCursor} />
                : <p className="muted" style={{ fontSize: 12 }}>打开一篇笔记后，这里会跟着你写的内容浮现相关记忆。</p> },
            { id: 'outline', title: '目录', icon: 'bx-list-ul', alwaysShown: true,
              body: <DocumentOutline content={content} viewRef={editorViewRef} /> },
            // 改动的分层账本：每次 AI 动作一层，整层接受 / 撤回（痛点 8：AI 改了三轮只想要第一轮）
            { id: 'changes', title: '改动', icon: 'bx-git-compare', badge: pendingDiff || undefined, hasContent: pendingDiff > 0,
              body: <ChangeLayersPanel viewRef={editorViewRef} tick={pendingDiff} /> },
            // 计划 = 写作骨架（计划）+ 每轮做了什么（执行）。判据 3：计划要看得见——
            // 在右栏一直看得见，比把正文顶下去好。harness 跑起来自动切到这里。
            { id: 'plan', title: '计划', icon: 'bx-target-lock', alwaysShown: true,
              badge: agentRounds.length || beats.length || undefined,
              body: (
                <div className="stack">
                  {current && (
                    <SkeletonPanel
                      spine={spine}
                      beats={beats}
                      beatCoverage={beatCoverage}
                      loading={loading === 'skeleton'}
                      onRun={runSkeleton}
                    />
                  )}
                  <AgentActivity
                    rounds={agentRounds}
                    status={loading === 'note-harness' || pausedRun ? noteHarnessStatus : ''}
                    running={loading === 'note-harness'}
                  />
                </div>
              ) },
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
                  <p style={{ margin: 0, lineHeight: 1.6 }}>{trace.answer}</p>
                  {trace.facts.map((f) => (
                    <div key={f.id} className="card" style={{ fontSize: 12 }}>
                      <span className="muted">{f.when}</span>
                      <div>{f.text}</div>
                      <button style={{ fontSize: 11, marginTop: 4 }}
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
          <span style={{ color: 'var(--accent)' }}>🤖 {noteHarnessStatus}</span>
        )}
        {pausedRun && <span style={{ color: 'var(--accent)' }}>⏸ 等你处置</span>}
        {harness?.running && <span style={{ color: 'var(--accent)' }}>🚀 {harness.folderName}</span>}
        <span style={{ marginInlineStart: 'auto', display: 'inline-flex', gap: 12, alignItems: 'center' }}>
          {jobInfo && <span className="muted"><span className="spinner" /> 存入知识库中…{jobInfo.facts > 0 ? ` 已抽出 ${jobInfo.facts} 条` : ''}</span>}
          {healthMsg && <span className="health-bad"><i className="bx bx-error" /> {healthMsg}</span>}
          {asrOffline && <span className="muted" title={'语音服务不可达：' + asrOffline + '。录音转写用不了，其它功能不受影响。'}><i className="bx bx-microphone-off" /> 语音离线</span>}
        </span>
        {current && <span className="muted">{wordCount(content)} 字 · 约 {readingMinutes(wordCount(content))} 分钟</span>}
      </div>
    </div>
  )
}
