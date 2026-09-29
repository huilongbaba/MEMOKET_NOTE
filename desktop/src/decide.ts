/**
 * 「拿主意」的全局热键——主进程这一侧。
 *
 * 用户在**任意应用**里选中一段字、按下热键：这里先问一声前台是哪个应用，再模拟一次 ⌘C
 * 把选区读进剪贴板，读完**把剪贴板原样放回**，然后让岛展开成「拿主意」的台面，把选区
 * 连同应用名一起广播过去（`decide:selection`）。之后的事（问后端、摆选项、↑↓ 选）都在渲染层。
 *
 * 双击 ⌃（modtap.ts）是另一条入口：弹出 macOS 原生的框选十字线，框一块屏幕直接送进去（`origin: 'screenshot'`），
 * 走和剪贴板图片同一条读图的路；Esc 取消就什么都不发生。
 *
 * 什么都没选时，用的是**剪贴板里现成的那一份**——用户最后一次复制的东西，不是什么历史：
 * 文字走同一条路，图片编成 PNG data URL 交给岛（`origin: 'clipboard'`）；文件这一期还不接。
 * 既没选中、剪贴板里也没有能用的，才是 `error: 'empty'`。
 *
 * 剪贴板走的是 Electron 44 的 W3C 那一套：`read()` 给一组 ClipboardItem（`types` + `getType` → Blob），
 * `write()` 收一组 ClipboardItem。快照就是把每一种类型的 Blob 都留着，放回去时原样拼回一个 ClipboardItem。
 *
 * 读选区靠 System Events 发按键，这要辅助功能权限：没有权限时 osascript 会失败，广播里
 * 带 `error: 'accessibility'`，岛上能说清楚去哪开。
 *
 * 选区文本和图片数据**不进日志**：那是用户在别的应用里的内容。
 * electron 的 clipboard / globalShortcut / systemPreferences 都能由调用方注入，测试里不碰真的。
 */
import { randomUUID } from 'node:crypto'
import { ClipboardItem, clipboard as electronClipboard, globalShortcut as electronGlobalShortcut, ipcMain, nativeImage, screen, systemPreferences } from 'electron'
import type { IpcMainInvokeEvent, WebContents } from 'electron'
import { execFile } from 'node:child_process'
import { existsSync } from 'node:fs'
import { readFile as readFileAsync, unlink } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { promisify } from 'node:util'
import type { DecidePending, DecideSelection, DecideStatus } from './companion-types'
import type { Cue, CuePoint } from './cue'

const run = promisify(execFile)

/** 剪贴板里的图片：Electron 的 NativeImage 这几个都有；假的至少要有 isEmpty。缩放和编码只在剪贴板兜底时用。 */
export type ClipboardImage = {
  isEmpty(): boolean
  getSize?(): { width: number; height: number }
  resize?(options: { width: number }): unknown
  toPNG?(): Buffer
}
/** `clipboard.read()` 给的一格：有哪些 MIME 类型，每一种取出来是个 Blob（书签那种是个对象）。 */
export type ClipboardEntry = { types: string[]; getType(type: string): Promise<unknown> }
type ClipboardBlob = { arrayBuffer(): Promise<ArrayBuffer> }

export type DecideHotkeyOptions = {
  /** 默认 ⌥D；被占就顺着 ACCELERATOR_LADDER 往下退。 */
  accelerator?: string
  companion: {
    contents(): WebContents[]
    assertIsland(event: IpcMainInvokeEvent): void
    /** 收起的窗口要不要留 320 宽：按下就说要（药丸马上要长），什么都没读到就说不要。 */
    setLive?(live: boolean): void
  }
  /** 按下的一瞬间在光标处荡开一圈光环（cue.ts）；不给就不画。 */
  cue?: Pick<Cue, 'pulse'>
  /** 按下热键时光标在哪：光环的位置。默认问 electron.screen。 */
  cursor?: () => CuePoint
  /** 框一块屏幕存成 PNG 文件；回 false 就是取消了。默认 screencapture -i。 */
  capture?: (file: string) => Promise<boolean>
  /** 读截图文件；测试里换成假的。 */
  readFile?: (file: string) => Promise<Buffer>
  /** 双击截图现在可不可用（modtap 起来了没）：status 里告诉岛。 */
  tapActive?: () => boolean
  log(line: string): void
  /** 跑 osascript；测试里换成脚本化的假的。 */
  exec?: (file: string, args: string[], timeoutMs: number) => Promise<{ stdout: string }>
  /** Electron 44 的 clipboard（W3C 那一套，Promise 的）；同步的假的也收。只给 readText/writeText 的最小假的也能跑。 */
  clipboard?: {
    readText(): string | Promise<string>; writeText(text: string): void | Promise<void>
    read?(): ClipboardEntry[] | Promise<ClipboardEntry[]>
    write?(items: unknown[]): void | Promise<void>
    has?(type: string): boolean | Promise<boolean>
    clear?(): void
  }
  /** 把快照里的各种类型拼回一格；默认就是 Electron 的 ClipboardItem。 */
  createItem?: (parts: Record<string, unknown>) => unknown
  /** 图片字节解成能缩放、能编 PNG 的图；默认 nativeImage.createFromBuffer。 */
  decodeImage?: (bytes: Buffer) => ClipboardImage
  globalShortcut?: { register(accelerator: string, callback: () => void): boolean; unregister(accelerator: string): void; isRegistered?(accelerator: string): boolean }
  /** 辅助功能权限给没给；默认问系统（不弹框）。 */
  isTrustedAccessibility?: () => boolean
  now?: () => Date
  /** 模拟 ⌘C 之后最多等剪贴板更新多久；一变就不等了。测试里调小。 */
  copyDelayMs?: number
}
export type DecideHotkey = { status(): DecideStatus; trigger(): Promise<void>; screenshot(): Promise<void>; dispose(): void }

/** ⌥D（D = 拿主意 / Decide）：两个键，macOS 自己没占它，平时只在英文布局下打出 ∂。
 *  被别的应用占了就顺着这张表退：⌥J，再到 ⌃⇧Space。可用 MEMOKET_DECIDE_SHORTCUT 指定。 */
export const DEFAULT_ACCELERATOR = 'Alt+D'
export const ACCELERATOR_LADDER = ['Alt+D', 'Alt+J', 'Control+Shift+Space']
/** 选区最多带多少字过去：够一封邮件、一段聊天；再长后端也读不出「要选什么」。 */
export const MAX_SELECTION_CHARS = 6000
/** 剪贴板图片最多多宽：够 Gemini 读清一张截图；再宽只是费流量。 */
export const MAX_IMAGE_WIDTH = 1600
/** 编成 data URL 后最多多长（6 MB）；超了就往下缩，缩到最窄一档还超就当没有图片。 */
export const MAX_IMAGE_DATA_URL_CHARS = 6_000_000
const IMAGE_RETRY_WIDTHS = [1200, 900]
const IMAGE_TYPES = ['image/png', 'image/jpeg']
/** 放回去时唯一不带的：图片的派生格式。一张截图会带 TIFF、HEIC、AVIF、PSD 好几份（十几 MB，逐个读要几百毫秒），
 *  留一张 PNG（没有就 JPEG）任何应用都能贴。别的类型（各应用的原生格式、文件、书签）都原样留着——不然 Numbers 的公式、Keynote 的幻灯片贴回去就没了。 */
const IMAGE_DERIVATIVE = /^image\/|format="(public\.(tiff|heic|heif|avif)|com\.adobe\.photoshop-image)"/i
/** Finder 里复制的文件在剪贴板上的样子：W3C 那边是 uri-list，macOS 原生格式是 public.file-url。 */
const FILE_FORMAT = 'electron application/osclipboard;format="public.file-url"'
const isFileType = (type: string) => /file-url|uri-list/i.test(type)
const COPY_TIMEOUT_MS = 3000
const FRONT_TIMEOUT_MS = 3000
/** 框选十字线可以停很久：人在想框哪儿。 */
const CAPTURE_TIMEOUT_MS = 180_000
const FRONT_SCRIPT = 'tell application "System Events" to get name of first application process whose frontmost is true'
/** ⌘C 之后每 30 ms 看一眼剪贴板，最多等 450 ms：选中了通常一百毫秒内就变；没选中就等满这一段再用剪贴板里现成的。 */
const COPY_DEADLINE_MS = 450
const COPY_POLL_MS = 30
const REGISTER_FAILED = '快捷键已被其他应用占用，或系统不允许注册。'
const NO_ACCESSIBILITY = '还没有辅助功能权限：系统设置 › 隐私与安全性 › 辅助功能 里允许 MEMOKET NOTE，才能读到别的应用里的选区。'
/** 一次 osascript 做两件事：问前台是谁，再模拟 ⌘C。前台问不到也照样按（名字给空串）。
 *  一个进程：两个进程同时去拉起 System Events 会互相撞掉，两件事都失败。 */
const FRONT_AND_COPY_SCRIPT = [
  'set frontName to ""',
  'tell application "System Events"',
  '  try',
  '    set frontName to name of first application process whose frontmost is true',
  '  end try',
  '  keystroke "c" using command down',
  'end tell',
  'return frontName',
].join('\n')
const STATUS_CHANNEL = 'decide:status'
const SELECTION_CHANNEL = 'decide:selection'
const PENDING_CHANNEL = 'decide:pending'

type Exec = NonNullable<DecideHotkeyOptions['exec']>

const message = (error: unknown) => (error instanceof Error ? error.message : String(error))
const sleep = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms))
const systemExec: Exec = async (file, args, timeoutMs) => {
  const { stdout } = await run(file, args, { timeout: timeoutMs, encoding: 'utf8' })
  return { stdout: String(stdout) }
}
/** macOS 原生的框选：十字线、空格切窗口、Esc 取消（取消时不生成文件，退出码非 0）。要屏幕录制权限，没给时系统会问。 */
const systemCapture = async (file: string): Promise<boolean> => {
  try { await run('screencapture', ['-i', '-x', '-t', 'png', file], { timeout: CAPTURE_TIMEOUT_MS }) } catch { /* 取消或超时：看文件在不在。 */ }
  return existsSync(file)
}
/** `isTrustedAccessibilityClient` 只有 macOS 有；别的平台没有这道门。 */
const systemTrusted = () => (process.platform === 'darwin' ? systemPreferences.isTrustedAccessibilityClient(false) : true)
const isBlob = (value: unknown): value is ClipboardBlob => !!value && typeof (value as ClipboardBlob).arrayBuffer === 'function'

export function createDecideHotkey(options: DecideHotkeyOptions): DecideHotkey {
  // 指定了就只试那一个；没指定就顺着梯子找第一个能注册上的。
  const candidates = options.accelerator ? [options.accelerator] : ACCELERATOR_LADDER
  let accelerator = candidates[0]
  const exec: Exec = options.exec ?? systemExec
  // Electron 的 clipboard 本来就有这些方法；这里统一成选项里那份可选的形状，假的和真的走同一条路。
  const clipboard = (options.clipboard ?? electronClipboard) as NonNullable<DecideHotkeyOptions['clipboard']>
  const createItem = options.createItem ?? ((parts: Record<string, unknown>) => new ClipboardItem(parts as ConstructorParameters<typeof ClipboardItem>[0]))
  const decodeImage = options.decodeImage ?? ((bytes: Buffer) => nativeImage.createFromBuffer(bytes))
  const globalShortcut = options.globalShortcut ?? electronGlobalShortcut
  const isTrusted = options.isTrustedAccessibility ?? systemTrusted
  const cursor = options.cursor ?? (() => screen.getCursorScreenPoint())
  const cue = options.cue ?? null
  const capture = options.capture ?? systemCapture
  const readImageFile = options.readFile ?? readFileAsync
  const now = options.now ?? (() => new Date())
  const copyDeadlineMs = options.copyDelayMs ?? COPY_DEADLINE_MS
  const log = (line: string) => { try { options.log(`${line}\n`) } catch { /* 日志本身出错不影响热键。 */ } }
  let registered = false
  let registerReason = ''
  let inFlight = false
  let disposed = false

  /** 每次都重新问：用户可能在应用开着的时候刚去系统设置里给了权限。 */
  function accessibility(): boolean | null {
    try { return isTrusted() } catch { return null }
  }

  function status(): DecideStatus {
    const trusted = accessibility()
    return {
      accelerator,
      registered,
      tap: options.tapActive?.() ?? false,
      reason: (registered ? '' : registerReason) + (trusted === false ? NO_ACCESSIBILITY : ''),
      accessibility: trusted,
    }
  }

  async function readClipboard(): Promise<string> {
    try { return await clipboard.readText() } catch { return '' }
  }

  const DENIED_PATTERN = /-1743|not authorized to send apple events|不允许发送 apple 事件|不允许.*apple.*事件/i
  /** 整份剪贴板：纯文字、每种类型的 Blob（放回去用）、解出来的图片、是不是 Finder 里复制的文件。 */
  type Snapshot = { text: string; parts: Record<string, unknown>; image: ClipboardImage | null; files: boolean }
  type Grabbed = Pick<DecideSelection, 'text' | 'origin' | 'image' | 'error'>
  type GrabbedFrom = Grabbed & { source: string }

  /** 剪贴板上现在是不是 Finder 复制的文件（问 macOS 原生格式；问不到就当没有）。 */
  async function hasFiles(): Promise<boolean> {
    if (!clipboard.has) return false
    try { return Boolean(await clipboard.has(FILE_FORMAT)) } catch { return false }
  }

  /** 快照：把 read() 给的每一格、每一种类型都取出来留着；顺手把第一张 PNG/JPEG 解成图。读不出来的类型跳过，不影响别的。 */
  async function snapshot(): Promise<Snapshot> {
    const text = await readClipboard()
    let entries: ClipboardEntry[] = []
    try { entries = (await clipboard.read?.()) ?? [] } catch (error) { log(`[decide] 剪贴板读不出来：${message(error)}`) }
    const parts: Record<string, unknown> = {}
    let image: ClipboardImage | null = null
    let files = false
    for (const entry of entries) {
      const types = entry.types ?? []
      // 一张图留一份：有 PNG 就不读 JPEG；其余 image/* 和原生 TIFF/HEIC/AVIF/PSD 派生格式跳过，别的类型全留。
      const primaryImage = IMAGE_TYPES.find(type => types.includes(type)) ?? null
      const wanted = types.filter(type => type === primaryImage || !IMAGE_DERIVATIVE.test(type))
      for (const type of wanted) {
        if (isFileType(type)) files = true
        let payload: unknown
        try { payload = await entry.getType(type) } catch { continue }
        if (payload === undefined || payload === null) continue
        parts[type] = payload
        if (!image && IMAGE_TYPES.includes(type) && isBlob(payload)) {
          try {
            const decoded = decodeImage(Buffer.from(await payload.arrayBuffer()))
            if (!decoded.isEmpty()) image = decoded
          } catch (error) { log(`[decide] 剪贴板图片解不出来：${message(error)}`) }
        }
      }
    }
    if (!files) files = await hasFiles()
    if (text && !('text/plain' in parts)) parts['text/plain'] = text
    return { text, parts, image, files }
  }

  /** 整份放回去：有什么类型就拼回什么类型，一次 write 原子提交。整份放不回去，至少把文字放回去——哨兵绝不能留在剪贴板上。 */
  async function restore(before: Snapshot) {
    try {
      if (!Object.keys(before.parts).length) { if (clipboard.clear) clipboard.clear(); else await clipboard.writeText(''); return }
      if (clipboard.write) { await clipboard.write([createItem(before.parts)]); return }
      await clipboard.writeText(before.text)
    } catch (error) {
      log(`[decide] 剪贴板没能整份放回去：${message(error)}`)
      try { await clipboard.writeText(before.text) } catch (again) { log(`[decide] 剪贴板文字也没放回去：${message(again)}`) }
    }
  }

  /** 剪贴板里的图片编成 PNG data URL：比 1600px 宽先缩到 1600；编出来超过 6 MB 就再缩到 1200、900——只缩到比原图窄的档位，
   *  原图本来就更小的档位缩出来还是同一张。最窄一档还超、编不出来、中途抛错，都当没有图片。图片数据不进日志。 */
  function encodeImage(image: ClipboardImage): string | null {
    try {
      const width = image.getSize?.().width ?? 0
      const plan: Array<number | null> = [width > MAX_IMAGE_WIDTH ? MAX_IMAGE_WIDTH : null, ...IMAGE_RETRY_WIDTHS.filter(target => width > target)]
      for (const target of plan) {
        const candidate = target === null || !image.resize ? image : (image.resize({ width: target }) as ClipboardImage)
        const png = candidate.toPNG?.()
        if (!png) return null
        const url = `data:image/png;base64,${png.toString('base64')}`
        if (url.length <= MAX_IMAGE_DATA_URL_CHARS) return url
      }
      const narrowest = plan[plan.length - 1] ?? width
      log(`[decide] 剪贴板图片太大：原图 ${width}px 宽，最窄试到 ${narrowest}px 仍超过 6 MB，当作没有图片`)
      return null
    } catch (error) {
      log(`[decide] 剪贴板图片编不出来：${message(error)}`)
      return null
    }
  }

  /** 没选中时用剪贴板里现成的：文字走同一条路，图片编成 data URL；文件这一期还不接（Finder 复制的文件在纯文字里只是个文件名，
   *  拿它当内容会误导）；都没有才是 empty。 */
  function fromClipboard(before: Snapshot): Grabbed {
    if (before.files) { log('[decide] 剪贴板里是文件，这一期还不接，当作没有内容'); return { text: '', error: 'empty' } }
    const text = before.text.trim().slice(0, MAX_SELECTION_CHARS)
    if (text) return { text, origin: 'clipboard' }
    const image = before.image ? encodeImage(before.image) : null
    if (image) return { text: '', image, origin: 'clipboard' }
    return { text: '', error: 'empty' }
  }

  function cursorPoint(): CuePoint | null {
    try { return cursor() } catch { return null }
  }

  /** ⌘C 发出去之后盯着剪贴板：一变就拿走；到点还是哨兵，那就是什么都没选。 */
  async function awaitCopy(sentinel: string): Promise<string> {
    const deadline = Date.now() + copyDeadlineMs
    let copied = await readClipboard()
    while (copied === sentinel && Date.now() < deadline) {
      await sleep(Math.min(COPY_POLL_MS, copyDeadlineMs))
      copied = await readClipboard()
    }
    return copied
  }

  /** 读选区：先把一个哨兵写进剪贴板，再模拟 ⌘C。⌘C 后剪贴板还是哨兵 = 什么都没选，这时改用哨兵之前那份剪贴板；
   *  变了 = 那就是选区。不管哪种，最后都把之前的整份剪贴板放回去。用哨兵而不是比对旧内容，是因为「刚复制过的同一段」和
   *  「什么都没选」在旧内容上分不开。 */
  async function grab(): Promise<GrabbedFrom> {
    const before = await snapshot()
    const sentinel = `​ memoket-decide ${randomUUID()}`
    try { await clipboard.writeText(sentinel) }
    catch (error) { log(`[decide] 剪贴板写不进去：${message(error)}`); return { text: '', error: 'empty', source: '' } }
    let copied: string
    let source = ''
    let copiedFiles = false
    try {
      const { stdout } = await exec('osascript', ['-e', FRONT_AND_COPY_SCRIPT], COPY_TIMEOUT_MS)
      source = (stdout.split('\n')[0] ?? '').trim()
      copied = await awaitCopy(sentinel)
      // ⌘C 复制的是 Finder 里的文件：纯文字只是个文件名。要在放回剪贴板之前问，放回去之后看到的就是旧的那份了。
      copiedFiles = copied !== sentinel && await hasFiles()
    } catch (error) {
      const reason = message(error)
      log(`[decide] 模拟 ⌘C 失败：${reason}`)
      // 超时也可能已经按下去了：不管剪贴板现在是什么，都放回原样。
      await restore(before)
      const denied = DENIED_PATTERN.test(reason)
      return { text: '', error: denied || accessibility() === false ? 'accessibility' : 'empty', source: '' }
    }
    await restore(before)
    if (copied === sentinel) return { ...fromClipboard(before), source }
    if (copiedFiles) { log('[decide] 剪贴板里是文件，这一期还不接，当作没有内容'); return { text: '', error: 'empty', source } }
    const text = copied.trim().slice(0, MAX_SELECTION_CHARS)
    return text ? { text, origin: 'selection', source } : { text: '', error: 'empty', source }
  }

  /** 日志里只说读到了什么、多少字；内容本身不进。 */
  function describe(selection: DecideSelection): string {
    if (selection.error === 'accessibility') return '没读到选区（accessibility）'
    if (selection.error) return '没读到内容（empty）'
    if (selection.origin === 'clipboard') return selection.image ? '剪贴板图片' : `剪贴板文字 ${selection.text.length} 字`
    return `读到选区 ${selection.text.length} 字`
  }

  function send(channel: string, payload: DecideSelection | DecidePending) {
    for (const contents of options.companion.contents()) {
      try { if (!contents.isDestroyed()) contents.send(channel, payload) }
      catch (error) { log(`[decide] 广播失败：${message(error)}`) }
    }
  }
  const broadcast = (selection: DecideSelection) => send(SELECTION_CHANNEL, selection)
  const pending = () => send(PENDING_CHANNEL, { at: now().toISOString() })

  async function trigger(): Promise<void> {
    // 连按两下：第一下还在读选区，第二下不排队也不打断——不然会多发一次 ⌘C。
    if (disposed || inFlight) return
    inFlight = true
    try {
      // 按下的一瞬间：岛上先亮「在读」，光标处荡开一圈光环——都不等读选区那几百毫秒。岛不在这里展开：答案出来时渲染层自己展开。
      const started = Date.now()
      const at = cursorPoint()
      // 窗口先放宽到 320，渲染层的弹簧才有地方把药丸长开；透明的那 40px 只在拿主意期间存在。
      options.companion.setLive?.(true)
      pending()
      if (at && cue) cue.pulse(at).catch(error => log(`[decide] 光环没画出来：${message(error)}`))
      const grabbed = await grab()
      const source = grabbed.source
      if (disposed) return
      const selection: DecideSelection = { text: grabbed.text, source, at: now().toISOString() }
      if (grabbed.origin) selection.origin = grabbed.origin
      if (grabbed.image) selection.image = grabbed.image
      if (grabbed.error) selection.error = grabbed.error
      if (selection.error) options.companion.setLive?.(false)
      broadcast(selection)
      log(`[decide] 热键：${source || '（未知应用）'}，${describe(selection)}，读了 ${Date.now() - started} ms`)
    } catch (error) {
      log(`[decide] 热键处理失败：${message(error)}`)
    } finally {
      inFlight = false
    }
  }

  async function frontApp(): Promise<string> {
    try {
      const { stdout } = await exec('osascript', ['-e', FRONT_SCRIPT], FRONT_TIMEOUT_MS)
      return (stdout.split('\n')[0] ?? '').trim()
    } catch { return '' }
  }

  /** 双击 ⌃：框一块屏幕，直接送进拿主意。药丸先说「框一块屏幕」，取消就静静复原；框到了就和剪贴板图片走同一条路。 */
  async function screenshot(): Promise<void> {
    if (disposed || inFlight) return
    inFlight = true
    const started = Date.now()
    const file = path.join(tmpdir(), `memoket-decide-${randomUUID()}.png`)
    try {
      options.companion.setLive?.(true)
      send(PENDING_CHANNEL, { at: now().toISOString(), phase: 'screenshot' })
      const source = await frontApp()
      const captured = await capture(file)
      if (disposed) return
      if (!captured) {
        options.companion.setLive?.(false)
        send(PENDING_CHANNEL, { at: now().toISOString(), phase: 'cancelled' })
        log('[decide] 截图取消了')
        return
      }
      const image = decodeImage(await readImageFile(file))
      const url = image.isEmpty() ? null : encodeImage(image)
      const selection: DecideSelection = { text: '', source, at: now().toISOString() }
      if (url) { selection.origin = 'screenshot'; selection.image = url }
      else { selection.error = 'empty'; options.companion.setLive?.(false) }
      broadcast(selection)
      log(`[decide] 截图：${source || '（未知应用）'}，${url ? '读到一张' : '没读出来'}，用了 ${Date.now() - started} ms`)
    } catch (error) {
      options.companion.setLive?.(false)
      send(PENDING_CHANNEL, { at: now().toISOString(), phase: 'cancelled' })
      log(`[decide] 截图失败：${message(error)}`)
    } finally {
      inFlight = false
      unlink(file).catch(() => { /* 取消时本来就没有文件。 */ })
    }
  }

  for (const candidate of candidates) {
    try {
      if (globalShortcut.register(candidate, () => { void trigger() })) { registered = true; accelerator = candidate; break }
      log(`[decide] 热键 ${candidate} 被占，换下一个`)
    } catch (error) {
      log(`[decide] 注册热键 ${candidate} 出错：${message(error)}`)
    }
  }
  if (!registered) { accelerator = candidates[0]; registerReason = REGISTER_FAILED }
  log(`[decide] 拿主意热键 ${accelerator} ${registered ? '已注册' : `不可用：${registerReason}`}`)
  // 先验身份再答：不是岛的窗口连一个 Promise 都拿不到。
  ipcMain.handle(STATUS_CHANNEL, event => { options.companion.assertIsland(event); return status() })

  return {
    status,
    trigger,
    screenshot,
    dispose() {
      if (disposed) return
      disposed = true
      if (registered) { try { globalShortcut.unregister(accelerator) } catch { /* 已经注销了。 */ } }
      registered = false
      ipcMain.removeHandler(STATUS_CHANNEL)
    },
  }
}
