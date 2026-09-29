import { randomUUID } from 'node:crypto'
import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, renameSync, rmSync, statSync, unlinkSync, writeFileSync } from 'node:fs'
import { mkdir, rename, rm } from 'node:fs/promises'
import path from 'node:path'
import type { CompanionItem, CompanionPreview, CompanionWindowCandidate } from './companion-types'
import { copyPlanCurrent, executeCopy, isWithin, MAX_COPY_BYTES, planCopy, type CopyPlan } from './companion-files'

const MAX_ITEMS = 200
const MAX_TEXT = 200_000
const MAX_IMAGE_BYTES = 20 * 1024 * 1024
const imageExtension = /\.(png|jpe?g|webp|gif|bmp|tiff?|heic|avif)$/i
const safeTitle = (value: string) => value.replace(/[\u0000-\u001f]/g, ' ').trim().slice(0, 160) || '未命名'

export function webLink(value: string): string | null {
  try {
    if (/\s/.test(value)) return null
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null
  } catch { return null }
}

function validItem(value: unknown): value is CompanionItem {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<CompanionItem>
  if (typeof item.id !== 'string' || !/^[a-f\d-]{36}$/i.test(item.id)
    || typeof item.title !== 'string' || item.title.length > 160
    || typeof item.createdAt !== 'string' || !Number.isFinite(Date.parse(item.createdAt))) return false
  if (item.thumbnail !== undefined && (typeof item.thumbnail !== 'string' || !item.thumbnail.startsWith('data:image/png;base64,') || item.thumbnail.length > 3_000_000)) return false
  if (item.previewStatus !== undefined && !['loading', 'ready', 'unavailable'].includes(item.previewStatus)) return false
  if (item.previewError !== undefined && (typeof item.previewError !== 'string' || item.previewError.length > 2000)) return false
  if (item.previewText !== undefined && (typeof item.previewText !== 'string' || item.previewText.length > 16 * 1024)) return false
  if (item.previewTextTruncated !== undefined && typeof item.previewTextTruncated !== 'boolean') return false
  if (item.storage !== undefined && !['copy', 'reference'].includes(item.storage)) return false
  if (item.sourcePath !== undefined && (typeof item.sourcePath !== 'string' || !path.isAbsolute(item.sourcePath) || item.sourcePath.includes('\0'))) return false
  if (item.kind === 'file' || item.kind === 'image') return typeof item.path === 'string' && path.isAbsolute(item.path) && !item.path.includes('\0')
  if (item.kind === 'text') return typeof item.text === 'string' && item.text.length <= MAX_TEXT
  if (item.kind === 'link') return typeof item.url === 'string' && webLink(item.url) !== null
  if (item.kind === 'window') return typeof item.windowId === 'string' && /^window:[\w:-]+$/.test(item.windowId)
    && (item.windowTitle === undefined || (typeof item.windowTitle === 'string' && item.windowTitle.length <= 8192 && !item.windowTitle.includes('\0')))
  return false
}

/** New drops are snapshots. Old references remain references; no original is moved or deleted. */
export class CompanionStore {
  private items: CompanionItem[] = []
  private readonly index: string
  private preserveUnreadableIndex = false
  private readonly removing = new Set<string>()
  private readonly exports = new Map<string, { id: string; plan: CopyPlan }>()
  storageError = ''

  constructor(private readonly directory: string) {
    this.index = path.join(directory, 'shelf.json')
    try {
      if (!existsSync(this.index)) return
      const parsed: unknown = JSON.parse(readFileSync(this.index, 'utf8'))
      if (!parsed || typeof parsed !== 'object' || !('version' in parsed) || parsed.version !== 1 || !('items' in parsed)
        || !Array.isArray(parsed.items) || parsed.items.length > MAX_ITEMS || !parsed.items.every(validItem)
        || new Set(parsed.items.map(item => item.id)).size !== parsed.items.length) throw new Error('Invalid shelf data')
      this.items = parsed.items.map(item => {
        if (item.storage === 'copy') this.ownedFolder(item)
        const restored = { ...item }
        // Old file/image thumbnails could be generic type icons, and interrupted jobs are not live after restart.
        const needsTextPreview = restored.kind === 'file' && /\.(txt|md|csv|tsv|log)$/i.test(restored.path || '') && restored.previewText === undefined
        if ((restored.kind === 'file' || restored.kind === 'image') && (!restored.previewStatus || restored.previewStatus === 'loading' || needsTextPreview)) {
          delete restored.thumbnail
          delete restored.previewText
          delete restored.previewTextTruncated
          restored.previewStatus = 'unavailable'
          restored.previewError = '内容预览尚未生成，展开暂存或点击重试继续。'
        }
        return restored
      })
    } catch {
      // Do not replace an unreadable index with an empty shelf on the next click.
      this.preserveUnreadableIndex = true
      this.storageError = '无法读取本机暂存记录，原始文件与暂存副本已保留。恢复索引前无法添加或修改内容。'
    }
  }

  list(): CompanionItem[] {
    return this.items.map(item => {
      let missing = false
      if (item.path) { try { statSync(item.path) } catch { missing = true } }
      return { ...item, ...(item.path ? { missing } : {}) }
    })
  }

  get(id: unknown): CompanionItem {
    if (typeof id !== 'string') throw new Error('请选择已暂存的项目。')
    const item = this.items.find(candidate => candidate.id === id)
    if (!item) throw new Error('这个项目已不在收纳栏中，请重新添加。')
    return { ...item }
  }

  private commit(next: CompanionItem[]) {
    if (next.length > MAX_ITEMS) throw new Error(`收纳栏最多保留 ${MAX_ITEMS} 个项目，请先移除暂时不用的内容。`)
    if (this.preserveUnreadableIndex) throw new Error('本机暂存索引无法读取，尚未保存任何新内容。请先恢复索引。')
    try {
      this.writeJson(this.index, { version: 1, items: next })
      this.items = next
      this.storageError = ''
    } catch {
      this.storageError = '本机暂存记录保存失败，本次操作未完成。原文件与已保存的副本不受影响。'
      throw new Error(this.storageError)
    }
  }

  private writeJson(file: string, value: unknown) {
    mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 })
    const temporary = `${file}.${randomUUID()}.tmp`
    let descriptor: number | undefined
    try {
      descriptor = openSync(temporary, 'wx', 0o600)
      writeFileSync(descriptor, JSON.stringify(value, null, 2))
      fsyncSync(descriptor)
      closeSync(descriptor)
      descriptor = undefined
      renameSync(temporary, file)
    } finally {
      if (descriptor !== undefined) closeSync(descriptor)
      try { unlinkSync(temporary) } catch { /* Successful rename leaves no temporary file. */ }
    }
  }

  private ownedFolder(item: CompanionItem): string {
    const folder = path.join(this.directory, 'vault', item.id)
    if (!item.path || path.dirname(item.path) !== folder || !isWithin(folder, item.path)) throw new Error('暂存副本的路径无效，未操作任何文件。')
    return folder
  }

  async addFiles(values: unknown): Promise<CompanionItem[]> {
    if (!Array.isArray(values) || values.length === 0 || values.length > 50) throw new Error('一次可拖入 1–50 个本机文件或文件夹。')
    if (this.preserveUnreadableIndex) throw new Error('本机暂存索引无法读取，尚未复制任何新内容。')
    const additions: CompanionItem[] = []
    const seen = new Set<string>()
    await mkdir(this.directory, { recursive: true, mode: 0o700 })
    const plans = []
    let totalBytes = 0
    let totalEntries = 0
    for (const value of values) {
      if (typeof value !== 'string' || !path.isAbsolute(value) || value.includes('\0')) throw new Error('无法读取这个文件的本机路径，请从 Finder 或文件管理器拖入。')
      if (seen.has(value)) continue
      seen.add(value)
      let plan
      try { plan = await planCopy(value, this.directory) }
      catch (error) {
        if (error && typeof error === 'object' && 'code' in error) throw new Error(`无法复制「${safeTitle(path.basename(value))}」，请确认文件存在且可读取。`)
        throw error
      }
      totalBytes += plan.bytes
      totalEntries += plan.entries.length
      if (totalBytes > MAX_COPY_BYTES || totalEntries > 2000) throw new Error('一次最多复制 512 MB、2000 个文件或文件夹，请减少所选内容。')
      plans.push(plan)
    }
    if (this.items.length + plans.length > MAX_ITEMS) throw new Error('暂存架已满，请先移除不再需要的内容。')
    const created: string[] = []
    try {
      for (const plan of plans) {
        const id = randomUUID()
        const folder = path.join(this.directory, 'vault', id)
        await mkdir(folder, { recursive: true, mode: 0o700 })
        created.push(folder)
        const file = path.join(folder, path.basename(plan.source))
        await executeCopy(plan, file)
        additions.push({ id, kind: plan.entries[0].metadata.isFile() && imageExtension.test(file) ? 'image' : 'file', title: safeTitle(path.basename(file)), createdAt: new Date().toISOString(), path: file, sourcePath: plan.source, storage: 'copy', previewStatus: 'loading' })
      }
      this.commit([...additions, ...this.items])
      return additions
    } catch (error) {
      // These copies have never been committed or handed to any consumer. Sources are untouched.
      await Promise.all(created.map(folder => rm(folder, { recursive: true, force: true }).catch(() => {})))
      if (error && typeof error === 'object' && 'code' in error) throw new Error('复制未完成，请检查可用磁盘空间与文件权限后重试。原文件未改变。')
      throw error
    }
  }

  addText(value: unknown) {
    if (typeof value !== 'string' || !value.trim()) throw new Error('没有可暂存的文字或链接。')
    if (value.length > MAX_TEXT) throw new Error('文字太长，请先保存为文件后拖入。')
    const text = value.trim()
    const url = webLink(text)
    const item: CompanionItem = { id: randomUUID(), kind: url ? 'link' : 'text', title: safeTitle(text.split('\n')[0]), createdAt: new Date().toISOString(), ...(url ? { url } : { text: value }) }
    this.commit([item, ...this.items])
    return item
  }

  addImage(png: Buffer, thumbnail?: string) {
    if (!png.length || png.length > MAX_IMAGE_BYTES) throw new Error('剪贴板图片为空或超过 20 MB，请另存为文件后拖入。')
    if (this.items.length >= MAX_ITEMS) throw new Error('收纳栏已满，请先移除暂时不用的内容。')
    if (this.preserveUnreadableIndex) throw new Error('本机暂存索引无法读取，尚未保存图片。')
    const id = randomUUID()
    const assets = path.join(this.directory, 'vault', id)
    mkdirSync(assets, { recursive: true, mode: 0o700 })
    const file = path.join(assets, 'clipboard.png')
    const item: CompanionItem = { id, kind: 'image', title: `剪贴板图片 ${new Date().toLocaleString('zh-CN')}`, createdAt: new Date().toISOString(), path: file, storage: 'copy', ...(thumbnail ? { thumbnail, previewStatus: 'ready' as const } : { previewStatus: 'loading' as const }) }
    try {
      const descriptor = openSync(file, 'wx', 0o600)
      try { writeFileSync(descriptor, png); fsyncSync(descriptor) } finally { closeSync(descriptor) }
      this.commit([item, ...this.items])
    } catch (error) {
      try { rmSync(assets, { recursive: true, force: true }) } catch { /* The uncommitted copy remains private if cleanup is unavailable. */ }
      throw error
    }
    return item
  }

  addWindow(candidate: CompanionWindowCandidate) {
    if (!/^window:\d+:[01]$/.test(candidate.id) || !candidate.title.trim() || candidate.title.length > 8192 || candidate.title.includes('\0')) throw new Error('窗口引用无效，请重新列出窗口。')
    const existing = this.items.find(item => item.kind === 'window' && item.windowId === candidate.id && (item.windowTitle ?? item.title) === candidate.title)
    if (existing) {
      this.setPreview(existing.id, candidate.preview
        ? { previewStatus: 'ready', thumbnail: candidate.preview }
        : { previewStatus: 'unavailable', previewError: candidate.previewError || '系统尚未提供这个窗口的截图，请刷新窗口列表。' })
      return this.get(existing.id)
    }
    const item: CompanionItem = { id: randomUUID(), kind: 'window', title: safeTitle(candidate.title), windowTitle: candidate.title, createdAt: new Date().toISOString(), windowId: candidate.id, ...(candidate.preview ? { thumbnail: candidate.preview, previewStatus: 'ready' as const } : { previewStatus: 'unavailable' as const, previewError: candidate.previewError || '系统尚未提供这个窗口的截图，请刷新窗口列表。' }) }
    this.commit([item, ...this.items])
    return item
  }

  setThumbnail(id: string, thumbnail: string) {
    if (!thumbnail.startsWith('data:image/png;base64,') || thumbnail.length > 3_000_000) return
    this.commit(this.items.map(item => item.id === id ? { ...item, thumbnail } : item))
  }

  setPreview(id: string, preview: CompanionPreview): boolean {
    const existing = this.items.find(item => item.id === id)
    if (!existing) return false // Removed items must never be resurrected by a delayed worker.
    if (preview.thumbnail !== undefined && (!preview.thumbnail.startsWith('data:image/png;base64,') || preview.thumbnail.length > 3_000_000)) return false
    if (preview.previewText !== undefined && preview.previewText.length > 16 * 1024) return false
    const next = { ...existing, previewStatus: preview.previewStatus }
    delete next.previewError
    if (preview.previewError) next.previewError = preview.previewError.slice(0, 2000)
    if (preview.previewStatus === 'unavailable') { delete next.thumbnail; delete next.previewText; delete next.previewTextTruncated }
    else if (preview.previewText !== undefined) {
      delete next.thumbnail
      next.previewText = preview.previewText
      next.previewTextTruncated = preview.previewTextTruncated ?? false
    } else if (preview.thumbnail) {
      next.thumbnail = preview.thumbnail
      delete next.previewText
      delete next.previewTextTruncated
    }
    if (next.previewStatus === existing.previewStatus && next.previewError === existing.previewError && next.thumbnail === existing.thumbnail
      && next.previewText === existing.previewText && next.previewTextTruncated === existing.previewTextTruncated) return false
    this.commit(this.items.map(item => item.id === id ? next : item))
    return true
  }

  async prepareExport(id: unknown): Promise<string> {
    const item = this.get(id)
    if (!item.path || (item.kind !== 'file' && item.kind !== 'image') || this.removing.has(item.id)) throw new Error('这个项目当前无法拖出。')
    const exports = path.join(this.directory, 'exports')
    await mkdir(exports, { recursive: true, mode: 0o700 })
    const folder = path.join(exports, randomUUID())
    try {
      const plan = await planCopy(item.path, exports)
      await mkdir(folder, { mode: 0o700 })
      const exported = path.join(folder, path.basename(item.path))
      await executeCopy(plan, exported)
      if (this.removing.has(item.id) || this.get(item.id).path !== item.path) throw new Error('项目已移除，未准备拖出。')
      // Keep the manifest from before copying; sampling a fresh signature afterward
      // could incorrectly pair an old export with newly edited source contents.
      this.exports.set(exported, { id: item.id, plan })
      return exported
    } catch (error) {
      await rm(folder, { recursive: true, force: true }).catch(() => {})
      if (error && typeof error === 'object' && 'code' in error) throw new Error('无法准备拖出副本，请检查文件和可用磁盘空间后重试。')
      throw error
    }
  }

  claimExport(id: unknown, exported: string): boolean {
    const prepared = this.exports.get(exported)
    this.exports.delete(exported)
    if (!prepared || prepared.id !== id || this.removing.has(prepared.id)) return false
    try {
      return this.get(id).path === prepared.plan.source && existsSync(exported) && copyPlanCurrent(prepared.plan)
    } catch { return false }
  }

  async removedDirectory(): Promise<string> {
    const directory = path.join(this.directory, 'removed')
    await mkdir(directory, { recursive: true, mode: 0o700 })
    return directory
  }

  async remove(id: unknown): Promise<{ recoveryPath?: string }> {
    const item = this.get(id)
    if (item.storage !== 'copy') { this.commit(this.items.filter(candidate => candidate.id !== item.id)); return {} }
    if (this.removing.has(item.id)) throw new Error('这个副本正在移除，请稍候。')
    const folder = this.ownedFolder(item)
    this.removing.add(item.id)
    const removed = path.join(this.directory, 'removed', item.id)
    const record = path.join(this.directory, 'removed', `${item.id}.json`)
    let moved = false
    try {
      await this.removedDirectory()
      this.writeJson(record, { version: 1, removedAt: new Date().toISOString(), item, recoveryPath: path.join(removed, path.basename(item.path!)) })
      await rename(folder, removed)
      moved = true
      this.commit(this.items.filter(candidate => candidate.id !== item.id))
      return { recoveryPath: path.join(removed, path.basename(item.path!)) }
    } catch (error) {
      if (moved) {
        try { await rename(removed, folder); moved = false }
        catch { this.storageError = '移除未能完成；副本保留在“已移除文件夹”，可从那里找回。' }
      }
      if (!moved) await rm(record, { force: true }).catch(() => {})
      if (error && typeof error === 'object' && 'code' in error) throw new Error('无法移除这个副本，文件已保留。请检查文件权限后重试。')
      throw error
    } finally { this.removing.delete(item.id) }
  }
}
