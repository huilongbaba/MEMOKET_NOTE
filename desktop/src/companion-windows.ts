/** User-invoked window references. Previews are snapshots, never embedded or live OS windows. */
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import type { DesktopCapturerSource, SourcesOptions } from 'electron'

export type WindowCandidate = { id: string; title: string; preview?: string; previewError?: string }
export type WindowActionResult = { ok: true } | { ok: false; error: string }
export type WindowCandidatesResult = { ok: true; candidates: WindowCandidate[] } | { ok: false; error: string }

type WindowSource = Pick<DesktopCapturerSource, 'id' | 'name' | 'thumbnail'>
export type WindowAdapterDependencies = {
  platform: string
  screenAccess: () => Promise<string>
  accessibilityAccess: () => Promise<boolean>
  getSources: (options: SourcesOptions) => Promise<WindowSource[]>
  run: (command: ReturnType<typeof windowRecallCommand>) => Promise<string>
}

const UNSUPPORTED = '当前系统尚不支持窗口暂存与唤回。你仍可暂存文字、链接和文件。'
const SCREEN_PERMISSION = '读取窗口列表需要屏幕录制权限。请在系统设置 → 隐私与安全性 → 屏幕与系统音频录制中允许 MEMOKET NOTE，再重试；应用不会主动弹出授权请求。'
const ACCESSIBILITY_PERMISSION = '唤回窗口需要辅助功能权限。请在系统设置 → 隐私与安全性 → 辅助功能中允许 MEMOKET NOTE，再重试。'
const WINDOW_GONE = '这个窗口已关闭或标题已变化，请重新选择窗口。暂存的预览仍是原来的快照。'
const PREVIEW_SIZE = { width: 720, height: 450 }
const MAX_PREVIEW_LENGTH = 3_000_000
const PREVIEW_MISSING = '此窗口没有提供截图，当前仅保存窗口引用。请保持窗口可见后刷新列表重试。'
const PREVIEW_EMPTY = '此窗口截图为空，当前仅保存窗口引用。可尝试取消最小化并刷新列表。'
const PREVIEW_UNREADABLE = '此窗口截图暂时无法读取，当前仅保存窗口引用。请刷新列表重试。'
const PREVIEW_TOO_LARGE = '此窗口截图超过预览大小限制，当前仅保存窗口引用。请刷新列表重试。'
const validTitle = (title: unknown): title is string => typeof title === 'string' && title.trim().length > 0 && title.length <= 8192 && !title.includes('\0')
const validWindowId = (id: unknown): id is string => typeof id === 'string' && /^window:\d+:[01]$/.test(id)

/** Keep a real bounded snapshot, or an explicit failure. Never manufacture a window preview. */
function windowSnapshot(thumbnail: WindowSource['thumbnail'] | undefined): Pick<WindowCandidate, 'preview' | 'previewError'> {
  if (!thumbnail) return { previewError: PREVIEW_MISSING }
  try {
    if (thumbnail.isEmpty()) return { previewError: PREVIEW_EMPTY }
    const size = thumbnail.getSize(1)
    if (!Number.isFinite(size.width) || !Number.isFinite(size.height) || size.width <= 0 || size.height <= 0) return { previewError: PREVIEW_EMPTY }
    // Electron does not guarantee the returned thumbnail matches thumbnailSize.
    const scale = Math.min(1, PREVIEW_SIZE.width / size.width, PREVIEW_SIZE.height / size.height)
    const image = scale < 1 ? thumbnail.resize({ width: Math.max(1, Math.floor(size.width * scale)), height: Math.max(1, Math.floor(size.height * scale)), quality: 'best' }) : thumbnail
    const bounded = image.getSize(1)
    if (image.isEmpty() || bounded.width <= 0 || bounded.height <= 0) return { previewError: PREVIEW_EMPTY }
    if (!Number.isFinite(bounded.width) || !Number.isFinite(bounded.height) || bounded.width > PREVIEW_SIZE.width || bounded.height > PREVIEW_SIZE.height) return { previewError: PREVIEW_TOO_LARGE }
    const preview = image.toDataURL({ scaleFactor: 1 })
    if (preview.length > MAX_PREVIEW_LENGTH) return { previewError: PREVIEW_TOO_LARGE }
    if (!/^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/.test(preview)) return { previewError: PREVIEW_UNREADABLE }
    return { preview }
  } catch { return { previewError: PREVIEW_UNREADABLE } }
}

// No title is interpolated into source. Only the exact title is supplied as argv.
// Scan before changing focus, and refuse ambiguous matches instead of choosing an arbitrary app.
const RECALL_SCRIPT = `on run argv
  if (count of argv) is not 1 then return "invalid"
  set targetTitle to item 1 of argv
  set matchedWindows to {}
  set matchedProcesses to {}
  tell application "System Events"
    repeat with candidateProcess in application processes
      try
        set processWindows to windows of candidateProcess
      on error
        set processWindows to {}
      end try
      repeat with candidateWindow in processWindows
        try
          set candidateTitle to name of candidateWindow as text
          considering case, diacriticals, hyphens, punctuation and white space
            set matchesTitle to candidateTitle is targetTitle
          end considering
          if matchesTitle then
            set end of matchedWindows to contents of candidateWindow
            set end of matchedProcesses to contents of candidateProcess
          end if
        end try
      end repeat
    end repeat
    if (count of matchedWindows) is 0 then return "not-found"
    if (count of matchedWindows) is not 1 then return "ambiguous"
    set targetWindow to item 1 of matchedWindows
    set targetProcess to item 1 of matchedProcesses
    try
      considering case, diacriticals, hyphens, punctuation and white space
        if (name of targetWindow as text) is not targetTitle then return "not-found"
      end considering
      if exists attribute "AXMinimized" of targetWindow then
        if value of attribute "AXMinimized" of targetWindow then set value of attribute "AXMinimized" of targetWindow to false
      end if
      set frontmost of targetProcess to true
      perform action "AXRaise" of targetWindow
      return "raised"
    on error
      return "failed"
    end try
  end tell
end run`

/** Pure command construction: shell metacharacters, quotes and newlines stay in a single argument. */
export function windowRecallCommand(title: string) {
  if (!validTitle(title)) throw new Error('窗口标题无效，请重新选择窗口。')
  return {
    file: '/usr/bin/osascript',
    args: ['-e', RECALL_SCRIPT, '--', title],
    options: { encoding: 'utf8' as const, timeout: 8000, maxBuffer: 16 * 1024, shell: false as const },
  }
}

export function parseWindowRecallResult(stdout: string): WindowActionResult {
  switch (stdout.trim()) {
    case 'raised': return { ok: true }
    case 'not-found': return { ok: false, error: WINDOW_GONE }
    case 'ambiguous': return { ok: false, error: '发现多个同名窗口，无法安全确定原窗口。请区分窗口标题后重新选择。' }
    default: return { ok: false, error: '系统未能唤回这个窗口。请检查辅助功能权限，或重新选择仍打开的窗口。' }
  }
}

/** Dependency injection keeps regression checks entirely off the user's real desktop. */
export function createCompanionWindowAdapter(deps: WindowAdapterDependencies) {
  const candidates = new Map<string, string>()
  let listVersion = 0

  async function listWindowCandidates(): Promise<WindowCandidatesResult> {
    const version = ++listVersion
    candidates.clear()
    if (deps.platform !== 'darwin') return { ok: false, error: UNSUPPORTED }
    try {
      if (await deps.screenAccess() !== 'granted') return { ok: false, error: SCREEN_PERMISSION }
      const sources = await deps.getSources({ types: ['window'], thumbnailSize: { ...PREVIEW_SIZE }, fetchWindowIcons: false })
      // A settings change during the asynchronous capture must not expose a stale result.
      if (await deps.screenAccess() !== 'granted') return { ok: false, error: SCREEN_PERMISSION }
      if (version !== listVersion) return { ok: false, error: '窗口列表已更新，请使用最新列表重新选择。' }
      const result: WindowCandidate[] = []
      for (const source of sources) {
        if (!validWindowId(source.id) || !validTitle(source.name) || candidates.has(source.id)) continue
        const candidate: WindowCandidate = { id: source.id, title: source.name, ...windowSnapshot(source.thumbnail) }
        candidates.set(source.id, source.name)
        result.push(candidate)
      }
      return { ok: true, candidates: result }
    } catch {
      return { ok: false, error: '无法读取窗口列表。请检查屏幕录制权限后重试。' }
    }
  }

  /** expectedTitle must come from the main process's saved item, never a renderer-supplied title. */
  async function recallWindow(id: string, expectedTitle?: string): Promise<WindowActionResult> {
    if (deps.platform !== 'darwin') return { ok: false, error: UNSUPPORTED }
    const title = expectedTitle ?? candidates.get(id)
    if (!validWindowId(id) || !validTitle(title)) return { ok: false, error: '这个窗口引用不可用，请重新选择窗口。' }
    try {
      if (await deps.screenAccess() !== 'granted') return { ok: false, error: SCREEN_PERMISSION }
      if (!await deps.accessibilityAccess()) return { ok: false, error: ACCESSIBILITY_PERMISSION }
      // An explicit recall is allowed to revalidate a persisted reference after restart.
      // Zero-sized thumbnails avoid taking another snapshot just to check identity.
      const sources = await deps.getSources({ types: ['window'], thumbnailSize: { width: 0, height: 0 }, fetchWindowIcons: false })
      const source = sources.find(item => item.id === id)
      if (!source || source.name !== title) return { ok: false, error: WINDOW_GONE }
      if (sources.filter(item => item.name === title).length !== 1) {
        return parseWindowRecallResult('ambiguous')
      }
      return parseWindowRecallResult(await deps.run(windowRecallCommand(title)))
    } catch (error) {
      const detail = error instanceof Error ? error.message : ''
      if (/-1743|-25211/.test(detail)) {
        return { ok: false, error: 'macOS 拒绝了窗口操作。请检查隐私与安全性中的辅助功能与自动化权限，再重试。' }
      }
      return { ok: false, error: '无法唤回窗口。请确认它仍打开、权限可用后重试。' }
    }
  }

  return { listWindowCandidates, recallWindow }
}

const run = promisify(execFile)
const adapter = createCompanionWindowAdapter({
  platform: process.platform,
  screenAccess: async () => (await import('electron')).systemPreferences.getMediaAccessStatus('screen'),
  accessibilityAccess: async () => (await import('electron')).systemPreferences.isTrustedAccessibilityClient(false),
  getSources: async options => (await import('electron')).desktopCapturer.getSources(options),
  run: async command => (await run(command.file, command.args, command.options)).stdout,
})

export const listWindowCandidates = adapter.listWindowCandidates
export const recallWindow = adapter.recallWindow
