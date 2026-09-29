import { app, BrowserWindow, clipboard, ClipboardItem, ipcMain, nativeImage, screen, shell } from 'electron'
import type { IpcMainInvokeEvent, WebContents } from 'electron'
import { statSync } from 'node:fs'
import path from 'node:path'
import { trustedCompanionFrame, validWorkspaceDestination } from './companion-boundary'
import { CompanionStore, webLink } from './companion-store'
import { CompanionPreviewQueue } from './companion-preview'
import { listWindowCandidates, recallWindow } from './companion-windows'
import type { CompanionActionResult, CompanionItem, CompanionMutationResult, CompanionPanel, CompanionState, CompanionSurface, CompanionWindowCandidate } from './companion-types'

type Options = { getUrl: () => string; openWorkspace: (destination?: string) => void; log: (message: string) => void }
type SurfaceWindow = { surface: 'top'; window: BrowserWindow; expanded: boolean; physicalExpanded: boolean; live: boolean; panel: CompanionPanel; displayId: number; url: string }
const COLLAPSE_FALLBACK_MS = 1000
/** 收起的窗口和药丸一样宽（240）：透明的边会吃掉底下应用的点击。拿主意时药丸要在弹簧上长到 320 装下那句摘录，
 *  那段时间窗口放宽到 320（live），弹簧缩回 240 并 settle 之后再收回来。 */
const COLLAPSED_WIDTH = 240
const LIVE_WIDTH = 320
const MAX_CLIPBOARD_CANDIDATE_LENGTH = 12_000
const isSurface = (value: unknown): value is CompanionSurface => value === 'top' || value === 'shelf'
const isPanel = (value: unknown): value is CompanionPanel => value === 'capture' || value === 'agent' || value === 'tasks' || value === 'clipboard' || value === 'windows' || value === 'decide'
const failure = (error: unknown): CompanionActionResult => ({ ok: false, error: error instanceof Error ? error.message : '操作未完成，请重试。' })

/** One passive island below the notch/menu bar; the full workspace opens only by explicit action. */
export function createDesktopCompanion(options: Options) {
  const store = new CompanionStore(path.join(app.getPath('userData'), 'companion'))
  const windows = new Map<'top', SurfaceWindow>()
  const handlers: string[] = []
  const windowCandidates = new Map<string, CompanionWindowCandidate>()
  let windowListVersion = 0
  let collapseTimer: ReturnType<typeof setTimeout> | null = null
  let disposed = false
  const previewAttempts = new Set<string>()
  const exportReady = new Map<string, string>()
  const exportPending = new Set<string>()
  const exportErrors = new Map<string, string>()
  const exportQueue: string[] = []
  let activeExports = 0
  const previews = new CompanionPreviewQueue({
    directory: path.join(app.getPath('userData'), 'companion', 'previews'),
    encodePng(bytes) {
      const image = nativeImage.createFromBuffer(bytes)
      if (image.isEmpty()) throw new Error('无法读取内容预览。')
      return image.toDataURL()
    },
    update(id, preview) {
      if (disposed) return
      try { if (store.setPreview(id, preview)) broadcast() }
      catch { broadcast() } // Strict index failures stay visible without crashing the preview worker.
    },
  })

  function prepareExport(id: string) {
    if (disposed || exportReady.has(id) || exportPending.has(id)) return
    exportPending.add(id)
    exportQueue.push(id)
    drainExports()
  }

  function drainExports() {
    if (disposed) return
    while (activeExports < 2 && exportQueue.length) {
      const id = exportQueue.shift()!
      activeExports++
      void store.prepareExport(id).then(file => {
        if (disposed) return
        store.get(id) // A removal that completed during preparation must not resurrect an export.
        exportReady.set(id, file)
        exportErrors.delete(id)
      }).catch(error => {
        if (!disposed) exportErrors.set(id, error instanceof Error ? error.message : '无法准备拖出副本，请重试。')
      }).finally(() => {
        activeExports--
        exportPending.delete(id)
        broadcast()
        drainExports()
      })
    }
  }

  function backfillPreviews() {
    // Prioritize uncached older references without flooding startup with hundreds of native jobs.
    const files = store.list().filter(item => item.path && (item.kind === 'file' || item.kind === 'image'))
    files.sort((a, b) => Number(previewAttempts.has(a.id)) - Number(previewAttempts.has(b.id))
      || Number(a.previewStatus === 'ready') - Number(b.previewStatus === 'ready'))
    for (const item of files.slice(0, 24)) { previewAttempts.add(item.id); void previews.request(item) }
  }

  function surfaceUrl() {
    const url = new URL(options.getUrl())
    url.searchParams.set('surface', 'top')
    return url.href
  }

  function getState(surface: SurfaceWindow): CompanionState {
    return { surface: surface.surface, expanded: surface.expanded, panel: surface.panel, items: store.list(), storageError: store.storageError }
  }

  function broadcast() {
    if (disposed) return
    for (const surface of windows.values()) {
      if (!surface.window.isDestroyed() && !surface.window.webContents.isDestroyed()) surface.window.webContents.send('companion:changed', getState(surface))
    }
  }

  function layout(surface: SurfaceWindow) {
    if (surface.window.isDestroyed()) return
    const display = screen.getAllDisplays().find(candidate => candidate.id === surface.displayId) ?? screen.getPrimaryDisplay()
    surface.displayId = display.id
    const work = display.workArea
    const width = Math.min(surface.physicalExpanded ? 640 : surface.live ? LIVE_WIDTH : COLLAPSED_WIDTH, Math.max(52, work.width - 24))
    const height = Math.min(surface.physicalExpanded ? 460 : 44, Math.max(44, work.height - 24))
    const x = work.x + Math.round((work.width - width) / 2)
    const y = work.y
    surface.window.setBounds({ x, y, width, height }, false)
  }

  function cancelCollapse() {
    if (collapseTimer !== null) clearTimeout(collapseTimer)
    collapseTimer = null
  }

  /** `live`：弹簧停在了 320（岛收着、拿主意还在想）就保留宽窗口；停回 240 才收窄。 */
  function settleCollapsed(surface: SurfaceWindow, live = false) {
    // A delayed completion from an interrupted closing spring must never shrink an open island.
    if (disposed || surface.expanded || surface.window.isDestroyed()) return
    cancelCollapse()
    if (!surface.physicalExpanded && surface.live === live) return
    surface.physicalExpanded = false
    surface.live = live
    layout(surface)
  }

  function setExpanded(surface: SurfaceWindow, expanded: boolean, panel?: CompanionPanel, focus = true) {
    surface.expanded = expanded
    // `search` is the knowledge base panel; it is a real panel of the island, no longer an alias of capture.
    if (panel) surface.panel = panel
    if (expanded) {
      cancelCollapse()
      // The renderer needs the full canvas before its enter transition starts.
      surface.physicalExpanded = true
      layout(surface)
      if (focus) { surface.window.show(); surface.window.focus() }
      else surface.window.showInactive()
      broadcast()
      if (surface.panel === 'clipboard') {
        backfillPreviews()
        // Prepare only the first visible copies after reopening; legacy references
        // remain untouched until the user explicitly drags them.
        for (const item of store.list().filter(item => item.storage === 'copy' && item.path && (item.kind === 'file' || item.kind === 'image')).slice(0, 8)) prepareExport(item.id)
      }
    } else {
      // Keep the full canvas until the renderer acknowledges that its closing spring settled.
      broadcast()
      // Leave the compact island visible without keeping keyboard focus after Escape.
      if (surface.window.isFocused()) surface.window.blur()
      if (surface.physicalExpanded && collapseTimer === null) {
        collapseTimer = setTimeout(() => {
          collapseTimer = null
          settleCollapsed(surface)
        }, COLLAPSE_FALLBACK_MS)
      } else if (!surface.physicalExpanded) layout(surface)
    }
    return getState(surface)
  }

  function show(surface?: CompanionSurface, panel?: CompanionPanel) {
    if (disposed) return
    const target = windows.get('top')
    if (!target || target.window.isDestroyed()) return
    // Compatibility for existing tray/menu callers; no side window is ever created.
    const targetPanel = panel ?? (surface === 'shelf' ? 'clipboard' : undefined)
    // A generic show command must not unmount an active panel or interrupt its pending save.
    if (!targetPanel && target.expanded) { target.window.showInactive(); return }
    target.displayId = screen.getDisplayNearestPoint(screen.getCursorScreenPoint()).id
    setExpanded(target, !!targetPanel, targetPanel, !!targetPanel)
    if (!targetPanel) target.window.showInactive()
  }

  function load(surface: SurfaceWindow) {
    try {
      surface.url = surfaceUrl()
      void surface.window.loadURL(surface.url).catch(error => options.log(`[companion] 页面加载失败：${error instanceof Error ? error.message : String(error)}`))
    } catch (error) { options.log(`[companion] 页面暂不可用：${error instanceof Error ? error.message : String(error)}`) }
  }

  function create() {
    const window = new BrowserWindow({
      title: 'MEMOKET · 灵动岛',
      width: COLLAPSED_WIDTH, height: 44,
      frame: false, transparent: true, backgroundColor: '#00000000', hasShadow: false,
      alwaysOnTop: true, skipTaskbar: true, resizable: false, movable: false,
      fullscreenable: false, maximizable: false, minimizable: false, show: false,
      webPreferences: {
        preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true,
        // The passive island stays visible while another app has focus; its clock and springs must keep rendering.
        backgroundThrottling: false,
      },
    })
    const entry: SurfaceWindow = { surface: 'top', window, expanded: false, physicalExpanded: false, live: false, panel: 'capture', displayId: screen.getPrimaryDisplay().id, url: surfaceUrl() }
    windows.set('top', entry)
    window.setAlwaysOnTop(true, 'floating')
    if (process.platform === 'darwin') window.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
    layout(entry)
    window.once('ready-to-show', () => { if (!disposed) { window.showInactive(); broadcast() } })
    window.on('focus', broadcast)
    window.on('close', event => { if (!disposed) { event.preventDefault(); window.hide() } })
    window.webContents.setWindowOpenHandler(({ url }) => {
      // Deliberate attachment links use the system browser for viewing/download.
      // Keep the island itself fixed to its renderer, and reject every other popup.
      try {
        const target = new URL(url)
        const origin = new URL(entry.url).origin
        if (!disposed && target.origin === origin && !target.username && !target.password
            && !target.search && !target.hash && /^\/api\/assets\/[a-f0-9]{24}\.[a-z0-9]{1,12}$/.test(target.pathname)
            && url === `${origin}${target.pathname}`) {
          void shell.openExternal(target.href).catch(error => options.log(`[companion] 附件打开失败：${error instanceof Error ? error.message : String(error)}`))
        }
      } catch { /* Invalid or non-asset destinations remain denied. */ }
      return { action: 'deny' }
    })
    window.webContents.on('will-navigate', (event, url) => { if (url !== entry.url) event.preventDefault() })
    window.webContents.on('did-finish-load', broadcast)
    load(entry)
  }

  function authorize(event: IpcMainInvokeEvent) {
    const surface = [...windows.values()].find(candidate => !candidate.window.isDestroyed() && candidate.window.webContents === event.sender)
    if (!surface || !trustedCompanionFrame(event, {
      contents: surface.window.webContents, mainFrame: surface.window.webContents.mainFrame,
      // Keep local shelf IPC usable while the backend restarts. reload() updates this exact URL.
      frameUrl: event.senderFrame?.url ?? '', baseUrl: surface.url, surface: surface.surface,
    })) throw new Error('不允许从这个窗口调用桌面工具。')
    return surface
  }

  function handle(channel: string, run: (surface: SurfaceWindow, event: IpcMainInvokeEvent, args: unknown[]) => unknown) {
    const name = `companion:${channel}`
    ipcMain.handle(name, (event, ...args: unknown[]) => run(authorize(event), event, args))
    handlers.push(name)
  }

  function mutate(surface: SurfaceWindow, run: () => void): CompanionMutationResult {
    try { run(); broadcast(); return { ok: true, state: getState(surface) } }
    catch (error) { broadcast(); return { ...failure(error), state: getState(surface) } }
  }

  async function mutateAsync(surface: SurfaceWindow, run: () => Promise<{ recoveryPath?: string } | void>): Promise<CompanionMutationResult> {
    try { const extra = await run(); broadcast(); return { ok: true, state: getState(surface), ...extra } }
    catch (error) { broadcast(); return { ...failure(error), state: getState(surface) } }
  }

  async function action(run: () => void | Promise<void>): Promise<CompanionActionResult> {
    try { await run(); broadcast(); return { ok: true } }
    catch (error) { broadcast(); return failure(error) }
  }

  function existingFile(id: unknown) {
    const item = store.get(id)
    if (!item.path || (item.kind !== 'file' && item.kind !== 'image')) throw new Error('这个项目不是本机文件。')
    try { statSync(item.path) } catch { throw new Error('文件已移动、删除或暂时无法读取。请从原位置重新拖入。') }
    return item as CompanionItem & { path: string }
  }

  function dragIcon(item: CompanionItem) {
    if (item.thumbnail) {
      const image = nativeImage.createFromDataURL(item.thumbnail)
      if (!image.isEmpty()) return image.resize({ width: 64, height: 64 })
    }
    // startDrag requires a non-empty icon, even while an OS file icon is still loading.
    const pixels = Buffer.alloc(48 * 48 * 4)
    for (let y = 5; y < 43; y++) for (let x = 9; x < 39; x++) {
      const offset = (y * 48 + x) * 4
      pixels[offset] = 73; pixels[offset + 1] = 91; pixels[offset + 2] = 36; pixels[offset + 3] = 255
    }
    return nativeImage.createFromBitmap(pixels, { width: 48, height: 48 })
  }

  handle('state', surface => getState(surface))
  handle('pointer-inside', surface => {
    if (disposed || !surface.expanded || surface.window.isDestroyed() || !surface.window.isVisible()) return false
    const cursor = screen.getCursorScreenPoint()
    const bounds = surface.window.getBounds()
    return cursor.x >= bounds.x && cursor.x < bounds.x + bounds.width
      && cursor.y >= bounds.y && cursor.y < bounds.y + bounds.height
  })
  handle('expand', (surface, _event, [expanded, panel, focus = true]) => {
    if (typeof expanded !== 'boolean' || (panel !== undefined && !isPanel(panel)) || typeof focus !== 'boolean') throw new Error('无效的工具面板。')
    return setExpanded(surface, expanded, panel, focus)
  })
  handle('settle-collapsed', (surface, _event, [width]) => settleCollapsed(surface, typeof width === 'number' && width > COLLAPSED_WIDTH))
  handle('show', (_surface, _event, [surface, panel]) => {
    if (!isSurface(surface) || (panel !== undefined && !isPanel(panel))) throw new Error('无效的工具面板。')
    show(surface, panel)
  })
  handle('workspace', (_surface, _event, [destination]) => {
    if (!validWorkspaceDestination(destination)) throw new Error('无效的工作区入口。')
    options.openWorkspace(destination)
  })
  /** 拖入与「放入暂存箱」共用：复制进库，然后排预览和拖出副本。 */
  function addFiles(surface: SurfaceWindow, paths: unknown) {
    return mutateAsync(surface, async () => {
      const additions = await store.addFiles(paths)
      for (const item of additions) { previewAttempts.add(item.id); void previews.request(item); prepareExport(item.id) }
    })
  }
  handle('add-files', (surface, _event, [paths]) => addFiles(surface, paths))
  handle('refresh-preview', (_surface, _event, [id]) => action(() => { void previews.request(existingFile(id), true) }))
  handle('add-text', (surface, _event, [text]) => mutate(surface, () => { store.addText(text) }))
  handle('peek-clipboard', async (surface, event) => {
    const requireCapture = () => {
      // Passive hover may not own keyboard focus. A hidden or unrelated panel may never peek.
      if (disposed || !surface.expanded || surface.panel !== 'capture' || !surface.window.isVisible()) throw new Error('仅在展开的随手记面板中提供剪贴板候选。')
    }
    requireCapture()
    const value = await clipboard.readText()
    // A read can complete after the panel closed, changed or navigated. Do not deliver that text.
    authorize(event)
    requireCapture()
    let text = value.slice(0, MAX_CLIPBOARD_CANDIDATE_LENGTH)
    if (text.length < value.length && /[\uD800-\uDBFF]$/.test(text)) text = text.slice(0, -1)
    return { text, truncated: text.length < value.length }
  })
  handle('paste', async surface => {
    try {
      const entries = await clipboard.read()
      for (const entry of entries) {
        const type = entry.types.find(type => type === 'image/png' || type === 'image/jpeg')
        if (!type) continue
        const blob = await entry.getType(type)
        if (!('arrayBuffer' in blob) || blob.size > 20 * 1024 * 1024) throw new Error('剪贴板图片超过 20 MB，请另存为文件后拖入。')
        const image = nativeImage.createFromBuffer(Buffer.from(await blob.arrayBuffer()))
        if (image.isEmpty()) throw new Error('无法读取剪贴板图片，请另存为文件后拖入。')
        const size = image.getSize()
        const scale = Math.min(1, 240 / Math.max(size.width, size.height))
        const preview = image.resize({ width: Math.max(1, Math.round(size.width * scale)), height: Math.max(1, Math.round(size.height * scale)) }).toDataURL()
        return mutate(surface, () => { const item = store.addImage(image.toPNG(), preview); prepareExport(item.id) })
      }
      const text = await clipboard.readText()
      return mutate(surface, () => { store.addText(text) })
    } catch (error) { return { ...failure(error), state: getState(surface) } }
  })
  handle('remove', (surface, _event, [id]) => mutateAsync(surface, async () => {
    const result = await store.remove(id)
    previewAttempts.delete(id as string)
    exportReady.delete(id as string)
    exportErrors.delete(id as string)
    return result
  }))
  async function revealRemoved() {
    return action(async () => {
      const error = await shell.openPath(await store.removedDirectory())
      if (error) throw new Error(`无法打开已移除文件夹：${error}`)
    })
  }
  handle('reveal-removed', () => revealRemoved())
  handle('open', (_surface, _event, [id]) => action(async () => {
    const item = store.get(id)
    if (item.kind === 'link' && item.url && webLink(item.url)) await shell.openExternal(item.url)
    else if (item.kind === 'file' || item.kind === 'image') {
      const file = existingFile(id)
      const error = await shell.openPath(file.path)
      if (error) throw new Error(`无法打开这个文件：${error}`)
    } else throw new Error(item.kind === 'window' ? '请使用唤回窗口操作。' : '这是一段文字，可以复制到剪贴板。')
  }))
  handle('reveal', (_surface, _event, [id]) => action(() => { shell.showItemInFolder(existingFile(id).path) }))
  handle('drag', (_surface, event, [id]) => action(() => {
    const item = existingFile(id)
    const prepared = exportReady.get(item.id)
    const ready = prepared && store.claimExport(item.id, prepared) ? prepared : undefined
    exportReady.delete(item.id)
    if (!ready) {
      const error = exportErrors.get(item.id)
      exportErrors.delete(item.id)
      prepareExport(item.id)
      throw new Error(error || '正在准备独立的拖出副本，请稍后再拖一次。')
    }
    // Never start a drag after an awaited copy: that gesture may already have ended.
    // A handed-off export is never reused, even if the destination merely copied it.
    event.sender.startDrag({ file: ready, icon: dragIcon(item) })
    prepareExport(item.id)
  }))
  handle('copy', (_surface, _event, [id]) => action(async () => {
    const item = store.get(id)
    if (item.kind === 'text' && item.text !== undefined) await clipboard.writeText(item.text)
    else if (item.kind === 'link' && item.url) await clipboard.writeText(item.url)
    else if (item.kind === 'image') {
      const image = nativeImage.createFromPath(existingFile(id).path)
      if (image.isEmpty()) throw new Error('无法读取这张图片，请使用拖出文件。')
      await clipboard.write([new ClipboardItem({ 'image/png': new Blob([Uint8Array.from(image.toPNG())], { type: 'image/png' }) })])
    } else throw new Error('这个项目可通过拖出或唤回使用。')
  }))
  handle('list-windows', async () => {
    const version = ++windowListVersion
    windowCandidates.clear()
    const result = await listWindowCandidates()
    if (version !== windowListVersion) return { ok: false, error: '窗口列表已更新，请使用最新列表重新选择。' }
    if (result.ok) for (const candidate of result.candidates) windowCandidates.set(candidate.id, candidate)
    return result
  })
  handle('add-window', (surface, _event, [id]) => mutate(surface, () => {
    const candidate = typeof id === 'string' ? windowCandidates.get(id) : undefined
    if (!candidate) throw new Error('请先点击列出窗口，再选择需要暂存的窗口。')
    store.addWindow(candidate)
  }))
  handle('recall-window', (_surface, _event, [id]) => action(async () => {
    const item = store.get(id)
    if (item.kind !== 'window' || !item.windowId) throw new Error('这个项目不是已暂存的窗口。')
    const result = await recallWindow(item.windowId, item.windowTitle ?? item.title)
    if (!result.ok) throw new Error(result.error)
  }))

  create()
  backfillPreviews()
  const relayout = () => { for (const surface of windows.values()) layout(surface) }
  screen.on('display-metrics-changed', relayout)
  screen.on('display-removed', relayout)

  return {
    show,
    /** 拿主意期间收起的窗口放宽到 320（药丸要长开）；展开着就等收起时按 settle 报的宽度处理。 */
    setLive(live: boolean) {
      const target = windows.get('top')
      if (disposed || !target || target.window.isDestroyed()) return
      target.live = live
      if (!target.physicalExpanded) layout(target)
    },
    revealRemoved,
    hide() {
      cancelCollapse()
      for (const surface of windows.values()) {
        surface.expanded = false
        surface.physicalExpanded = false
        surface.live = false
        layout(surface)
        surface.window.hide()
      }
      broadcast()
    },
    owns(contents: WebContents) { return !disposed && [...windows.values()].some(surface => !surface.window.isDestroyed() && surface.window.webContents === contents) },
    /** 别的模块（会话）的 IPC 也过同一道门：必须是岛的窗口、主框架、本地后端的地址。 */
    assertIsland(event: IpcMainInvokeEvent) { authorize(event) },
    /** 主进程里别的模块（会话）往顶部浮条的暂存箱里放文件：和拖入走同一条路。 */
    async addFiles(paths: string[]): Promise<CompanionMutationResult> {
      const surface = windows.get('top')
      if (disposed || !surface || surface.window.isDestroyed()) throw new Error('桌面浮条尚未就绪。')
      return addFiles(surface, paths)
    },
    /** 还活着的浮条窗口，给别的模块广播用。 */
    contents(): WebContents[] {
      return [...windows.values()].filter(surface => !surface.window.isDestroyed() && !surface.window.webContents.isDestroyed()).map(surface => surface.window.webContents)
    },
    reload() { if (!disposed) for (const surface of windows.values()) load(surface) },
    dispose() {
      if (disposed) return
      disposed = true
      exportQueue.length = 0
      exportReady.clear()
      previews.dispose()
      cancelCollapse()
      for (const channel of handlers) ipcMain.removeHandler(channel)
      screen.removeListener('display-metrics-changed', relayout)
      screen.removeListener('display-removed', relayout)
      for (const surface of windows.values()) surface.window.destroy()
      windows.clear()
    },
  }
}
