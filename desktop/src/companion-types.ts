/** Data shared by the local desktop surface. New drops are independent local copies. */
export type CompanionSurface = 'top' | 'shelf'
/** `decide` 不是标签：全局热键把岛直接展开成「拿主意」的台面，四个标签都不亮。 */
export type CompanionPanel = 'capture' | 'agent' | 'tasks' | 'clipboard' | 'windows' | 'decide'
export type CompanionPreview = {
  previewStatus: 'loading' | 'ready' | 'unavailable'
  previewError?: string
  thumbnail?: string
  previewText?: string
  previewTextTruncated?: boolean
}
export type CompanionItem = {
  id: string
  kind: 'file' | 'image' | 'text' | 'link' | 'window'
  title: string
  createdAt: string
  path?: string
  storage?: 'copy' | 'reference'
  sourcePath?: string
  text?: string
  url?: string
  thumbnail?: string
  previewText?: string
  previewTextTruncated?: boolean
  previewStatus?: CompanionPreview['previewStatus']
  previewError?: string
  missing?: boolean
  windowId?: string
  windowTitle?: string
}
export type CompanionState = {
  surface: 'top'
  expanded: boolean
  panel: CompanionPanel
  items: CompanionItem[]
  storageError: string
}
export type CompanionActionResult = { ok: boolean; error?: string }
export type CompanionMutationResult = CompanionActionResult & { state: CompanionState; recoveryPath?: string }
export type CompanionWindowCandidate = { id: string; title: string; preview?: string; previewStatus?: CompanionPreview['previewStatus']; previewError?: string }
export interface CompanionBridge {
  getState(): Promise<CompanionState>
  /** Read-only native pointer check for external drags whose DOM exit is missing. */
  isPointerInside?(): Promise<boolean>
  onState(callback: (state: CompanionState) => void): () => void
  setExpanded(expanded: boolean, panel?: CompanionPanel, focus?: boolean): Promise<CompanionState>
  /** Called only when the renderer's current closing spring has settled. */
  /** 收起的弹簧停了：报一下停在多宽（240 平时 / 320 拿主意在想），主进程据此收窄或保留窗口。 */
  settleCollapsed(width?: number): Promise<void>
  show(surface: CompanionSurface, panel?: CompanionPanel): Promise<void>
  openWorkspace(destination?: string): Promise<void>
  addFiles(files: File[]): Promise<CompanionMutationResult>
  addText(text: string): Promise<CompanionMutationResult>
  /** A transient, bounded candidate; available only while the capture panel is expanded. */
  peekClipboard(): Promise<{ text: string; truncated: boolean }>
  pasteClipboard(): Promise<CompanionMutationResult>
  refreshPreview(id: string): Promise<CompanionActionResult>
  remove(id: string): Promise<CompanionMutationResult>
  revealRemoved(): Promise<CompanionActionResult>
  open(id: string): Promise<CompanionActionResult>
  reveal(id: string): Promise<CompanionActionResult>
  startDrag(id: string): Promise<CompanionActionResult>
  copy(id: string): Promise<CompanionActionResult>
  listWindows(): Promise<CompanionActionResult & { candidates?: CompanionWindowCandidate[] }>
  addWindow(candidateId: string): Promise<CompanionMutationResult>
  recallWindow(itemId: string): Promise<CompanionActionResult>
}

// ── 岛上的智能体会话 ────────────────────────────────────────────────────────
// Claude Code 在主进程里以无头方式（`claude -p --output-format stream-json`）跑；渲染层只看
// 这里归一化过的事件，不碰 CLI 的原始 JSON。一次只有一轮在进行；每轮一个子进程，`--resume`
// 接上同一个会话。会话与消息记在 userData/agent/ 下，属于岛自己（暂存箱不收自己私有目录里的文件，所以不放在 companion/ 下）。

/** `id` 就是传给 `--model` 的值；空串 = 跟随 Claude Code 自己的默认模型。 */
export type AgentModel = { id: string; label: string }
export type AgentStatus = {
  /** 找到了可执行文件且 `--version` 答得上来。 */
  available: boolean
  /** null = 还没跑过一轮、不知道；false = 上一轮被 CLI 拒绝为「未登录」。 */
  loggedIn: boolean | null
  version: string
  /** 不可用 / 未登录时给用户看的一句话。 */
  reason: string
  /** 会话的工作目录：岛自己的一个文件夹，智能体只能在这里读写。 */
  cwd: string
  models: AgentModel[]
  /** 正在进行的那一轮；没有就是 null。 */
  runningTurnId: string | null
}
export type AgentSession = { id: string; title: string; model: string; createdAt: string; updatedAt: string; turns: number }
/** 智能体写出的（write / edit）或用户拖进来带上的（attach）文件；都在工作目录里。 */
export type AgentArtifact = { path: string; name: string; action: 'write' | 'edit' | 'attach'; shelved?: boolean }
export type AgentMessage = {
  id: string
  role: 'user' | 'assistant'
  text: string
  at: string
  artifacts?: AgentArtifact[]
  costUsd?: number
  /** 这一轮以错误收尾（模型报错、进程退出）：正文里是能拿到的部分，这里是原因。 */
  error?: string
}
export type AgentTurnEvent =
  | { type: 'turn-start'; turnId: string; sessionId: string | null; model: string }
  /** CLI 的 init 事件到了：真正的会话 id 与模型名。 */
  | { type: 'session'; turnId: string; sessionId: string; model: string }
  | { type: 'delta'; turnId: string; text: string }
  /** 正在用某个工具（读、写、搜）：面板上的一行活动提示。 */
  | { type: 'activity'; turnId: string; tool: string; path?: string; label: string }
  | { type: 'artifact'; turnId: string; artifact: AgentArtifact }
  | { type: 'turn-end'; turnId: string; sessionId: string; message: AgentMessage }
  | { type: 'turn-error'; turnId: string; sessionId: string | null; message: string; notLoggedIn?: boolean }
/** attachments：先用 attach() 复制进工作目录的文件；主进程把它们的路径附在提示词后面，Claude 可以直接读。 */
export type AgentSendInput = { sessionId: string | null; text: string; model: string; attachments?: string[] }
export interface AgentBridge {
  status(): Promise<AgentStatus>
  sessions(): Promise<AgentSession[]>
  transcript(sessionId: string): Promise<AgentMessage[]>
  /** 开始一轮；上一轮还在跑时返回 ok: false。sessionId 为 null 表示开一个新会话。 */
  send(input: AgentSendInput): Promise<CompanionActionResult & { turnId?: string; sessionId?: string | null }>
  interrupt(): Promise<CompanionActionResult>
  /** 拖进来的文件复制进工作目录的「附件」里，随下一句一起发；返回复制后的路径。 */
  attach(files: File[]): Promise<CompanionActionResult & { attachments?: AgentArtifact[] }>
  /** 把智能体写出的文件放进暂存箱：走和拖入文件同一条路（复制进库）。 */
  shelve(paths: string[]): Promise<CompanionMutationResult>
  onEvent(callback: (event: AgentTurnEvent) => void): () => void
}

// ── 拿主意：全局热键 + 别的应用里的选区 ───────────────────────────────────
// 主进程注册一个全局热键；按下时模拟 ⌘C 读走当前应用的选区（读完把剪贴板原样放回），
// 连同前台应用名一起广播给岛，岛展开成「拿主意」台面并去问后端 /api/desktop/decide。

export type DecideStatus = {
  accelerator: string
  registered: boolean
  /** 没注册上 / 没有辅助功能权限时给用户看的一句话。 */
  reason: string
  /** null = 还没查过；false = 系统设置里没给辅助功能权限，读不到选区。 */
  accessibility: boolean | null
  /** 双击 ⌃ 截图那条入口起来了没（原生辅助进程 modtap）。 */
  tap: boolean
}
export type DecideSelection = {
  text: string
  /** 前台应用名，如 Safari；读不到就是空串。 */
  source: string
  at: string
  /** selection：⌘C 读到的选区；clipboard：什么都没选，用的是剪贴板里已有的东西（文字或图片）；screenshot：双击 ⌃ 框的一块屏幕。 */
  origin?: 'selection' | 'clipboard' | 'screenshot'
  /** 剪贴板里是图片时：PNG 的 data URL（主进程已缩到 1600px 以内、6 MB 以内）；text 为空。 */
  image?: string
  /** accessibility：没权限读不到选区；empty：按了热键，既没选中，剪贴板里也没有文字或图片。 */
  error?: 'accessibility' | 'empty'
}
/** 热键刚按下、还在读：药丸先亮起来「正在拿主意」，不等读选区那几百毫秒。
 *  phase = screenshot：十字线出来了，药丸说「框一块屏幕」；cancelled：Esc 了，药丸复原。 */
export type DecidePending = { at: string; phase?: 'screenshot' | 'cancelled' }
export interface DecideBridge {
  status(): Promise<DecideStatus>
  onSelection(callback: (selection: DecideSelection) => void): () => void
  onPending(callback: (event: DecidePending) => void): () => void
}
