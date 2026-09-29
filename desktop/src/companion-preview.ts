import { execFile } from 'node:child_process'
import { createHash } from 'node:crypto'
import { chmod, copyFile, lstat, mkdir, mkdtemp, open, readFile, readdir, rm, stat } from 'node:fs/promises'
import path from 'node:path'
import { previewDimensions } from './companion-image'
import type { CompanionItem, CompanionPreview } from './companion-types'

const MAX_PNG_BYTES = 2 * 1024 * 1024
const MAX_PENDING = 200
const MAX_TEXT_BYTES = 16 * 1024
const TEXT_EXTENSIONS = /\.(txt|md|csv|tsv|log)$/i
const PREVIEW_EXTENSIONS = /\.(pdf|key|pages|numbers|docx?|pptx?|xlsx?|odt|ods|odp|rtf|txt|md|csv|tsv|log|png|jpe?g|webp|gif|bmp|tiff?|heic|avif)$/i
const DOCUMENT_BUNDLE = /\.(key|pages|numbers)$/i
type RunOptions = { timeout: number; maxBuffer: number; signal: AbortSignal }
type Run = (executable: string, args: string[], options: RunOptions) => Promise<void>
type Request = { item: CompanionItem & { path: string }; force: boolean; done: () => void }
type Options = {
  directory: string
  encodePng: (bytes: Buffer) => string
  update: (id: string, preview: CompanionPreview) => void
  platform?: string
  run?: Run
}

const runQuickLook: Run = (executable, args, options) => new Promise((resolve, reject) => {
  // Argument arrays preserve spaces, quotes and shell metacharacters; no shell ever sees a filename.
  execFile(executable, args, { ...options, encoding: 'utf8', killSignal: 'SIGKILL', windowsHide: true }, error => error ? reject(error) : resolve())
})

function unavailable(previewError: string): CompanionPreview { return { previewStatus: 'unavailable', previewError } }

/** Local document-content thumbnails. Never calls getFileIcon or Quick Look's icon mode. */
export class CompanionPreviewQueue {
  private queue: Request[] = []
  private pending = new Map<string, Promise<void>>()
  private active = new Set<AbortController>()
  private disposed = false
  private readonly platform: string
  private readonly run: Run

  constructor(private readonly options: Options) {
    this.platform = options.platform ?? process.platform
    this.run = options.run ?? runQuickLook
  }

  request(item: CompanionItem, force = false): Promise<void> {
    if (this.disposed || !item.path || (item.kind !== 'file' && item.kind !== 'image')) return Promise.resolve()
    const previous = this.pending.get(item.id)
    if (previous) return previous
    if (this.pending.size >= MAX_PENDING) {
      this.options.update(item.id, unavailable('预览队列已满，请稍后重试。'))
      return Promise.resolve()
    }
    let done!: () => void
    const pending = new Promise<void>(resolve => { done = resolve })
    this.pending.set(item.id, pending)
    this.queue.push({ item: { ...item, path: item.path }, force, done })
    if ((!item.thumbnail && item.previewText === undefined) || force) this.options.update(item.id, { previewStatus: 'loading' })
    this.pump()
    return pending
  }

  private pump() {
    while (!this.disposed && this.active.size < 2 && this.queue.length) {
      const request = this.queue.shift()!
      const controller = new AbortController()
      this.active.add(controller)
      void this.generate(request, controller.signal).then(preview => {
        if (!this.disposed) this.options.update(request.item.id, preview)
      }).catch(() => {
        if (!this.disposed) this.options.update(request.item.id, unavailable('预览暂时无法生成，请重试。原文件仍可打开和拖出。'))
      }).finally(() => {
        this.active.delete(controller)
        this.pending.delete(request.item.id)
        request.done()
        this.pump()
      })
    }
  }

  private async png(file: string): Promise<Buffer> {
    const metadata = await lstat(file)
    if (!metadata.isFile() || metadata.size === 0 || metadata.size > MAX_PNG_BYTES) throw new Error('invalid-thumbnail')
    const bytes = await readFile(file)
    if (bytes.length > MAX_PNG_BYTES) throw new Error('invalid-thumbnail')
    const dimensions = previewDimensions(bytes)
    if (!bytes.subarray(0, 8).equals(Buffer.from('89504e470d0a1a0a', 'hex')) || !dimensions
      || dimensions.width > 2048 || dimensions.height > 2048) throw new Error('invalid-thumbnail')
    return bytes
  }

  private async fingerprint(file: string) {
    const metadata = await stat(file)
    if (!metadata.isFile() && !(metadata.isDirectory() && DOCUMENT_BUNDLE.test(file))) throw new Error('folder')
    let bundle = ''
    if (metadata.isDirectory()) {
      // Bundle document editors update inner members without necessarily changing the root mtime.
      for (const name of ['Index.zip', 'Metadata/Properties.plist', 'QuickLook/Thumbnail.jpg', 'QuickLook/Preview.pdf', 'preview.jpg', 'preview-micro.jpg']) {
        try { const child = await stat(path.join(file, name)); bundle += `${name}:${child.size}:${child.mtimeMs};` } catch { /* Optional bundle member. */ }
      }
    }
    return createHash('sha256').update(`content-v1\0${file}\0${metadata.size}\0${metadata.mtimeMs}\0${metadata.ctimeMs}\0${bundle}`).digest('hex')
  }

  private async generate(request: Request, signal: AbortSignal): Promise<CompanionPreview> {
    const file = request.item.path
    if (!path.isAbsolute(file) || file.includes('\0')) return unavailable('文件路径无效，请重新暂存。')
    const plainText = TEXT_EXTENSIONS.test(file)
    if (!plainText && this.platform !== 'darwin') return unavailable('此系统暂未接入文档内容预览；原文件仍可打开和拖出。')
    if (!PREVIEW_EXTENSIONS.test(file)) return unavailable('这个文件格式暂不支持内容预览；可以打开原文件查看。')
    let key: string
    try { key = await this.fingerprint(file) }
    catch (error) { return unavailable(error instanceof Error && error.message === 'folder' ? '文件夹没有文档页面预览；可以打开文件夹查看。' : '原文件已移动、删除或无法读取，请重新暂存。') }
    if (signal.aborted) return unavailable('预览已取消。')
    // Plain-text Quick Look thumbnails can be dark-on-dark and too small to read. Preserve bounded actual text instead.
    if (plainText) return this.textPreview(file, key, signal)
    await mkdir(this.options.directory, { recursive: true, mode: 0o700 })
    if (signal.aborted) return unavailable('预览已取消。')
    const cached = path.join(this.options.directory, `${key}.png`)
    if (!request.force) {
      try { return this.ready(await this.png(cached)) } catch { /* Cache misses and invalid entries are regenerated. */ }
    }
    if (!signal.aborted) this.options.update(request.item.id, { previewStatus: 'loading' })
    const working = await mkdtemp(path.join(this.options.directory, 'working-'))
    try {
      try {
        await this.run('/usr/bin/qlmanage', ['-t', '-s', '512', '-o', working, file], { timeout: 12_000, maxBuffer: 64 * 1024, signal })
      } catch (error) {
        const timedOut = !!error && typeof error === 'object' && 'killed' in error && error.killed
        return unavailable(timedOut ? '内容预览生成超时，请重试或打开原文件。' : '系统未能生成内容预览，请重试或打开原文件。')
      }
      if (signal.aborted) return unavailable('预览已取消。')
      const outputs = (await readdir(working)).filter(name => name.toLowerCase().endsWith('.png'))
      if (outputs.length !== 1) return unavailable('系统没有提供这个文件的内容缩略图；可以打开原文件查看。')
      const output = path.join(working, outputs[0])
      let bytes: Buffer
      try { bytes = await this.png(output) }
      catch { return unavailable('系统生成的预览无效或过大；可以打开原文件查看。') }
      // Do not cache or display a snapshot of a file that changed while Quick Look was reading it.
      try { if (await this.fingerprint(file) !== key) return unavailable('生成期间文件已更新，请重新生成预览。') }
      catch { return unavailable('原文件已移动或删除，请重新暂存。') }
      const result = this.ready(bytes)
      if (result.previewStatus === 'ready') {
        await copyFile(output, cached)
        await chmod(cached, 0o600)
        await this.prune()
      }
      return result
    } finally { await rm(working, { recursive: true, force: true }) }
  }

  private async textPreview(file: string, expectedFingerprint: string, signal: AbortSignal): Promise<CompanionPreview> {
    try {
      const handle = await open(file, 'r')
      let bytes: Buffer
      let previewTextTruncated: boolean
      try {
        const metadata = await handle.stat()
        if (!metadata.isFile()) return unavailable('这不是可读取的普通文本文件。')
        const buffer = Buffer.alloc(Math.min(metadata.size, MAX_TEXT_BYTES))
        let length = 0
        while (length < buffer.length) {
          if (signal.aborted) return unavailable('预览已取消。')
          const result = await handle.read(buffer, length, buffer.length - length, length)
          if (result.bytesRead === 0) break
          length += result.bytesRead
        }
        bytes = buffer.subarray(0, length)
        previewTextTruncated = metadata.size > length
      } finally { await handle.close() }
      if (signal.aborted) return unavailable('预览已取消。')
      if (await this.fingerprint(file) !== expectedFingerprint) return unavailable('读取期间文件已更新，请重新生成预览。')
      const encoding = bytes[0] === 0xff && bytes[1] === 0xfe ? 'utf-16le'
        : bytes[0] === 0xfe && bytes[1] === 0xff ? 'utf-16be' : 'utf-8'
      let previewText: string
      try {
        // Streaming mode holds an incomplete final code point at the byte limit instead of inventing a replacement glyph.
        previewText = new TextDecoder(encoding, { fatal: true }).decode(bytes, { stream: previewTextTruncated })
      } catch { return unavailable('暂不支持这个文本编码，请以 UTF-8 保存后重试。') }
      if (previewText.includes('\0')) return unavailable('文件含二进制内容，无法作为纯文本预览。')
      return { previewStatus: 'ready', previewText, previewTextTruncated }
    } catch (error) {
      const denied = !!error && typeof error === 'object' && 'code' in error && (error.code === 'EACCES' || error.code === 'EPERM')
      return unavailable(denied ? '没有读取这个文本文件的权限，请检查原文件权限。' : '原文件已移动、删除或无法读取，请重新暂存。')
    }
  }

  private ready(bytes: Buffer): CompanionPreview {
    try {
      const thumbnail = this.options.encodePng(bytes)
      if (!thumbnail.startsWith('data:image/png;base64,') || thumbnail.length > 3_000_000) throw new Error('invalid-thumbnail')
      return { previewStatus: 'ready', thumbnail }
    } catch { return unavailable('无法显示系统生成的内容预览，请重试或打开原文件。') }
  }

  private async prune() {
    const names = (await readdir(this.options.directory)).filter(name => /^[a-f0-9]{64}\.png$/.test(name))
    const files = await Promise.all(names.map(async name => {
      const file = path.join(this.options.directory, name)
      try { const metadata = await stat(file); return { file, size: metadata.size, modified: metadata.mtimeMs } } catch { return null }
    }))
    const present = files.filter((file): file is NonNullable<typeof file> => file !== null).sort((a, b) => b.modified - a.modified)
    let bytes = 0
    for (const [index, file] of present.entries()) {
      bytes += file.size
      if (index >= 128 || bytes > 64 * 1024 * 1024) await rm(file.file, { force: true })
    }
  }

  dispose() {
    this.disposed = true
    for (const controller of this.active) controller.abort()
    for (const request of this.queue.splice(0)) { this.pending.delete(request.item.id); request.done() }
  }
}
