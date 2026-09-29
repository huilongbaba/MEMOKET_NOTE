/**
 * 渲染进程唯一能碰到主进程的口子。只暴露一件事：换主题——界面的暗色
 * 全靠 `prefers-color-scheme`，而 Electron 里那个值由 nativeTheme.themeSource
 * 决定，所以「设置里选深色」必须绕到主进程去改它，CSS 一行不用动。
 */
import { contextBridge, ipcRenderer, webUtils } from 'electron'
import type { AgentBridge, AgentTurnEvent, CompanionBridge, CompanionState, DecideBridge, DecidePending, DecideSelection } from './companion-types'

const companion: CompanionBridge = {
  getState: () => ipcRenderer.invoke('companion:state'),
  isPointerInside: () => ipcRenderer.invoke('companion:pointer-inside'),
  onState(callback) {
    const listener = (_event: Electron.IpcRendererEvent, state: CompanionState) => callback(state)
    ipcRenderer.on('companion:changed', listener)
    return () => ipcRenderer.removeListener('companion:changed', listener)
  },
  setExpanded: (expanded, panel, focus) => ipcRenderer.invoke('companion:expand', expanded, panel, focus),
  // 不带宽度就不传参：这个端点保持「无参也合法」，主进程按 240 处理。
  settleCollapsed: (width?: number) => (width === undefined ? ipcRenderer.invoke('companion:settle-collapsed') : ipcRenderer.invoke('companion:settle-collapsed', width)),
  show: (surface, panel) => ipcRenderer.invoke('companion:show', surface, panel),
  openWorkspace: (destination) => ipcRenderer.invoke('companion:workspace', destination),
  async addFiles(files) {
    const paths = Array.from(files).map(file => webUtils.getPathForFile(file))
    if (paths.some(filePath => !filePath)) throw new Error('部分拖入内容没有本机文件路径，此次尚未暂存。请从 Finder 或文件管理器拖入；剪贴板图片可使用“粘贴”添加。')
    return ipcRenderer.invoke('companion:add-files', paths)
  },
  addText: (text) => ipcRenderer.invoke('companion:add-text', text),
  peekClipboard: () => ipcRenderer.invoke('companion:peek-clipboard'),
  pasteClipboard: () => ipcRenderer.invoke('companion:paste'),
  refreshPreview: (id) => ipcRenderer.invoke('companion:refresh-preview', id),
  remove: (id) => ipcRenderer.invoke('companion:remove', id),
  revealRemoved: () => ipcRenderer.invoke('companion:reveal-removed'),
  open: (id) => ipcRenderer.invoke('companion:open', id),
  reveal: (id) => ipcRenderer.invoke('companion:reveal', id),
  startDrag: (id) => ipcRenderer.invoke('companion:drag', id),
  copy: (id) => ipcRenderer.invoke('companion:copy', id),
  listWindows: () => ipcRenderer.invoke('companion:list-windows'),
  addWindow: (id) => ipcRenderer.invoke('companion:add-window', id),
  recallWindow: (id) => ipcRenderer.invoke('companion:recall-window', id),
}

/** 岛上的智能体会话（Claude Code 无头运行在主进程里）。频道 `agent:*`，事件 `agent:event`。 */
const agent: AgentBridge = {
  status: () => ipcRenderer.invoke('agent:status'),
  sessions: () => ipcRenderer.invoke('agent:sessions'),
  transcript: (sessionId) => ipcRenderer.invoke('agent:transcript', sessionId),
  send: (input) => ipcRenderer.invoke('agent:send', input),
  interrupt: () => ipcRenderer.invoke('agent:interrupt'),
  async attach(files) {
    const paths = Array.from(files).map(file => webUtils.getPathForFile(file))
    if (paths.some(filePath => !filePath)) throw new Error('部分拖入内容没有本机文件路径，这次没有带上。请从 Finder 或文件管理器拖入。')
    return ipcRenderer.invoke('agent:attach', paths)
  },
  shelve: (paths) => ipcRenderer.invoke('agent:shelve', paths),
  onEvent(callback) {
    const listener = (_event: Electron.IpcRendererEvent, turnEvent: AgentTurnEvent) => callback(turnEvent)
    ipcRenderer.on('agent:event', listener)
    return () => ipcRenderer.removeListener('agent:event', listener)
  },
}

/** 拿主意：热键读到的选区从主进程送过来。频道 `decide:status`，事件 `decide:selection`。 */
const decide: DecideBridge = {
  status: () => ipcRenderer.invoke('decide:status'),
  onSelection(callback) {
    const listener = (_event: Electron.IpcRendererEvent, selection: DecideSelection) => callback(selection)
    ipcRenderer.on('decide:selection', listener)
    return () => ipcRenderer.removeListener('decide:selection', listener)
  },
  onPending(callback) {
    const listener = (_event: Electron.IpcRendererEvent, event: DecidePending) => callback(event)
    ipcRenderer.on('decide:pending', listener)
    return () => ipcRenderer.removeListener('decide:pending', listener)
  },
}

contextBridge.exposeInMainWorld('memoketDesktop', {
  companion,
  agent,
  decide,
  setTheme(theme: 'system' | 'light' | 'dark') { ipcRenderer.send('set-theme', theme) },
  /** 应用菜单里点了「帮助 › 快捷键」这类要界面响应的项 */
  onMenu(cb: (name: string) => void) {
    const listener = (_e: Electron.IpcRendererEvent, name: string) => cb(name)
    ipcRenderer.on('menu', listener)
    return () => ipcRenderer.removeListener('menu', listener)
  },
  quickCapture: {
    /** Called after the renderer has attached its open-quick-capture listener. */
    ready() { ipcRenderer.send('quick-capture:ready') },
    status(): Promise<{ accelerator: string; registered: boolean; reason: string }> {
      return ipcRenderer.invoke('quick-capture:status')
    },
    /** Invoked only by the quick-capture dialog's explicit paste button. */
    readClipboard(): Promise<string> { return ipcRenderer.invoke('quick-capture:clipboard') },
  },
  /** 退出前主进程问一句「还有没存的吗」；界面存完回 flushed() */
  onFlush(cb: () => void) { ipcRenderer.on('flush', () => cb()) },
  flushed() { ipcRenderer.send('flushed') },
  /** 界面定下了当前身份：主进程记进 identity.json，localStorage 丢了也认得回来 */
  rememberUser(user: string) { ipcRenderer.send('remember-user', user) },
  /** **我这个窗口该连的是哪个后端**（P45 #2）：壳起的那个子进程的 pid / 端口 / 数据目录。
   *  界面拿它跟 `/api/health` 里后端自报的那一份对一次——对不上说明这一屏摆的是
   *  另一份实例的库（P44 问题 #2 实拍）。还没起来回 null。 */
  backendInfo(): Promise<{ port: number; pid: number; dataDir: string } | null> {
    return ipcRenderer.invoke('backend:info')
  },
  /** 弹系统的选文件夹对话框（导回 Obsidian 选 vault）；取消返回空串 */
  pickDirectory(title: string): Promise<string> { return ipcRenderer.invoke('pick-directory', title) },
  /** 导回 Notion / 飞书的凭证：记在主进程的 export-credentials.json（identity.json 旁边），网页版没有这个口子 */
  exportCreds: {
    load(): Promise<Record<string, string>> { return ipcRenderer.invoke('export-creds:load') },
    save(patch: Record<string, string>): Promise<void> { return ipcRenderer.invoke('export-creds:save', patch) },
  },

  /** 屏幕活动（Daily Journey）。**采集在主进程里**——它要常驻、要在窗口关掉之后
   *  继续、要响应锁屏，这些渲染层都做不到。界面只是这个状态的一个视图：
   *  菜单栏那个图标是另一个（docs/daily-journey-plan.md §8.3）。 */
  /** 幻灯片 → PDF：主进程在离屏窗口里 printToPDF（零新依赖）。
   *  返回存到哪；用户取消返回空串。 */
  slidesToPdf(html: string, name: string): Promise<string> {
    return ipcRenderer.invoke('slides:pdf', html, name)
  },
  journey: {
    state(): Promise<{ state: 'off' | 'running' | 'paused' | 'no-permission'; today: number }> {
      return ipcRenderer.invoke('journey:state')
    },
    start(): Promise<void> { return ipcRenderer.invoke('journey:start') },
    pause(minutes?: number): Promise<void> { return ipcRenderer.invoke('journey:pause', minutes) },
    resume(): Promise<void> { return ipcRenderer.invoke('journey:resume') },
    stop(): Promise<void> { return ipcRenderer.invoke('journey:stop') },
  },
})
