/**
 * 材料托盘（P14，docs/agent-native-editor.md §3.4）：这篇笔记显式「摊在桌上」的材料。
 *
 * 用户把别的笔记 / 一条事实 / 导入的一段 / 摘的一段放进托盘，之后续写、智能续写、`/` 块、右键动作
 * 取材料时托盘里的排最前、不被筛、不滚出窗口（后端 `harness/tray.py`）。方案 §1 第 5 行原话：
 * 「写周报时我要的是把这八篇笔记摊在桌上，而不是逐条搜事实」。
 *
 * 这里只有纯函数和一个进程内缓存：托盘住在右栏「记忆」顶上的 `TrayPanel`，别处（记忆卡的「放进托盘」、
 * `[[` 链接的「摊到这篇桌上」）不认识面板，只往 window 上发 `tray-add`；面板收到就落库、再广播 `tray-changed`。
 * `runBlock` 的「从托盘写」开跑前要判托盘空不空，读的是这份缓存（面板每次落库都更新）。
 */
import type { TrayItem, TrayItemIn, TrayKind } from '../api'

export const TRAY_KIND_LABEL: Record<TrayKind, string> = { note: '笔记', fact: '事实', import: '导入', selection: '摘录' }
export const TRAY_KIND_ICON: Record<TrayKind, string> = { note: 'bx-note', fact: 'bx-link', import: 'bx-import', selection: 'bx-text' }
/** 托盘里一条的摘要给多长：跟后端 `store.TRAY_EXCERPT_MAX` 同一个数 */
export const TRAY_EXCERPT_MAX = 600
/** 面板里一条折起来时显示几个字 */
export const TRAY_PREVIEW_CHARS = 120

/** `tray-add` 事件的 detail：谁想往当前这篇的托盘里放一条 */
export type TrayAddDetail = TrayItemIn & { noteId?: string }

/** 从别处往托盘里放一条。面板（`TrayPanel`）在监听；没开笔记时它会说「先打开一篇」。 */
export function requestTrayAdd(item: TrayAddDetail): void {
  window.dispatchEvent(new CustomEvent<TrayAddDetail>('tray-add', { detail: item }))
}

/** 一篇笔记的开头几百字 → 托盘摘要：去掉标题井号、内链折回标题、空行折成单换行 */
export function noteExcerpt(content: string, max = TRAY_EXCERPT_MAX): string {
  const plain = (content || '')
    .replace(/\[([^\]\n]+)\]\(note:\/\/[0-9a-f]{12}\)/g, '$1')
    .replace(/^#+\s*/gm, '')
    .replace(/\n{2,}/g, '\n')
    .trim()
  return plain.length > max ? plain.slice(0, max) + '…' : plain
}

/** 同一条放两次只算一次：note / fact 按 ref_id，import / selection 按内容 */
export function trayKey(i: Pick<TrayItemIn, 'kind' | 'ref_id' | 'excerpt'>): string {
  return i.kind === 'note' || i.kind === 'fact' ? `${i.kind}:${i.ref_id ?? ''}` : `${i.kind}:${(i.excerpt ?? '').trim()}`
}

export function alreadyInTray(items: Pick<TrayItemIn, 'kind' | 'ref_id' | 'excerpt'>[], item: TrayItemIn): boolean {
  const k = trayKey(item)
  return items.some((i) => trayKey(i) === k)
}

/** 把一条加到末尾（已在托盘里就原样返回）——纯函数，PUT 整份的那份数组就是它的返回值 */
export function withItem(items: TrayItem[], item: TrayItemIn): TrayItemIn[] {
  const base: TrayItemIn[] = items.map(({ id, kind, ref_id, title, excerpt }) => ({ id, kind, ref_id, title, excerpt }))
  if (alreadyInTray(base, item)) return base
  return [...base, { ...item, excerpt: (item.excerpt ?? '').slice(0, TRAY_EXCERPT_MAX) }]
}

/** 拖序 / 上移下移：把 from 挪到 to（纯函数） */
export function moveItem<T>(items: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= items.length || to >= items.length) return items
  const next = items.slice()
  const [it] = next.splice(from, 1)
  next.splice(to, 0, it)
  return next
}

// ---- 进程内缓存：`runBlock`「从托盘写」开跑前判空用；面板每次落库都写它
const cache = new Map<string, TrayItem[]>()
export function setTrayCache(noteId: string, items: TrayItem[]): void {
  cache.set(noteId, items)
  window.dispatchEvent(new CustomEvent('tray-changed', { detail: { noteId, count: items.length } }))
}
export function trayCount(noteId: string): number { return cache.get(noteId)?.length ?? 0 }

/** 「从托盘写」开跑前的门槛：托盘空着就说一句、不发请求（后端也拦，`compose_block` 400）。空串 = 放行 */
export function trayPrecondition(noteId: string): string {
  return trayCount(noteId) === 0 ? '托盘是空的——先把要用的笔记 / 事实放进右栏「记忆」顶上的托盘，再「从托盘写」。' : ''
}
