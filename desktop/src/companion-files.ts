import { constants, lstatSync, type Stats } from 'node:fs'
import { chmod, copyFile, lstat, mkdir, open, readdir, realpath, utimes } from 'node:fs/promises'
import path from 'node:path'

export const MAX_COPY_BYTES = 512 * 1024 * 1024
const MAX_COPY_ENTRIES = 2000
const MAX_COPY_DEPTH = 16
type Entry = { relative: string; metadata: Stats }
export type CopyPlan = { source: string; entries: Entry[]; bytes: number }
const unchanged = (a: Stats, b: Stats) => a.dev === b.dev && a.ino === b.ino && a.size === b.size && a.mtimeMs === b.mtimeMs && a.ctimeMs === b.ctimeMs
export const isWithin = (parent: string, child: string) => { const relative = path.relative(parent, child); return relative === '' || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative)) }

/** Bounded, asynchronous preflight; never follow a symlink or modify a source. */
export async function planCopy(source: string, privateDirectory: string): Promise<CopyPlan> {
  const sourceStat = await lstat(source)
  if (sourceStat.isSymbolicLink()) throw new Error('暂不支持符号链接，请拖入文件或文件夹本身。')
  const canonical = await realpath(source)
  const privatePath = await realpath(privateDirectory)
  if (isWithin(privatePath, canonical) || (sourceStat.isDirectory() && isWithin(canonical, privatePath))) throw new Error('不能把暂存空间自身或包含它的文件夹再次复制到暂存。')
  const entries: Entry[] = []
  let bytes = 0
  async function scan(relative: string, depth: number) {
    if (depth > MAX_COPY_DEPTH || entries.length >= MAX_COPY_ENTRIES) throw new Error('文件夹过大：每次最多复制 2000 个文件或文件夹，层级不超过 16 层。')
    const absolute = path.join(source, relative)
    const metadata = await lstat(absolute)
    if (metadata.isSymbolicLink()) throw new Error('文件夹包含符号链接，尚未复制。请移除链接或单独选择实际文件。')
    if (!metadata.isFile() && !metadata.isDirectory()) throw new Error('暂存仅支持普通文件和文件夹。')
    if (metadata.isFile()) bytes += metadata.size
    if (bytes > MAX_COPY_BYTES) throw new Error('一次最多复制 512 MB，请减少文件或选择更小的文件夹。')
    entries.push({ relative, metadata })
    if (metadata.isDirectory()) for (const name of await readdir(absolute)) await scan(path.join(relative, name), depth + 1)
  }
  await scan('', 0)
  return { source, entries, bytes }
}

/** Copies only the preflight manifest, using async I/O and exclusive destination files. */
export async function executeCopy(plan: CopyPlan, destination: string) {
  for (const entry of plan.entries) {
    const source = path.join(plan.source, entry.relative)
    const target = path.join(destination, entry.relative)
    const before = await lstat(source)
    if (before.isSymbolicLink() || !unchanged(entry.metadata, before)) throw new Error('复制期间源文件发生变化，尚未暂存。请等待文件写入完成后重试。')
    if (before.isDirectory()) await mkdir(target, { mode: 0o700 })
    else {
      await copyFile(source, target, constants.COPYFILE_EXCL | constants.COPYFILE_FICLONE)
      const after = await lstat(source)
      const copied = await lstat(target)
      if (after.isSymbolicLink() || !unchanged(before, after) || copied.size !== before.size) throw new Error('复制期间源文件发生变化，尚未暂存。请重试。')
      const handle = await open(target, 'r')
      try { await handle.sync() } finally { await handle.close() }
      await chmod(target, before.mode & 0o777)
      await utimes(target, before.atime, before.mtime)
    }
  }
  // Catch additions/removals and source replacements that happened after a child copied.
  for (const entry of plan.entries) {
    const current = await lstat(path.join(plan.source, entry.relative))
    if (current.isSymbolicLink() || !unchanged(entry.metadata, current)) throw new Error('复制期间源文件或文件夹发生变化，尚未暂存。请重试。')
  }
}

/** Small metadata-only check during the drag gesture; no copying or file-byte reads. */
export function copyPlanCurrent(plan: CopyPlan): boolean {
  try {
    return plan.entries.every(entry => {
      const current = lstatSync(path.join(plan.source, entry.relative))
      return !current.isSymbolicLink() && unchanged(entry.metadata, current)
    })
  } catch { return false }
}
