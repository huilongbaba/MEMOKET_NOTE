/**
 * 待处置的改动层怎么落库、怎么放回来（P39，痛点 8 的最后一块）。
 *
 * **为什么要这一层**：层活在 CodeMirror 的 `roundDiffField` 里，关掉 app 就没了，
 * 等于替用户按了「全部接受」（P35 #9 / P37 #5）。P37 在真库上量过：九种改动层里
 * 八种在库里什么都不留，`auto` 快照那一档被 600 秒间隔掐掉、存的还是「改之前」那一版，
 * `harness_runs` 连 `note_id` 都没有——**重建不出来**。所以这一批给层单开了一张表
 * （`note_change_layers`），这个文件是它两头的纯函数：编辑器状态 → 行，行 → 编辑器状态。
 *
 * 这里全是纯函数，没有一次 fetch、没有一处 dispatch——**能用代码判准的不交给模型**，
 * 也不交给一个要起 app 才能跑的测试。
 */
import type { EditorState } from '@codemirror/state'
import { roundDiffField, type Hunk, type Settled } from '../editor/roundDiff'
import { SLASH_ITEMS } from '../editor/slashMenu'

/** 一处改动存下来长什么样。`state` 的四个取值跟后端 `store.HUNK_STATES` 逐字一致。 */
export type SavedHunk = {
  k: number
  from: number
  to: number
  del: string
  ins: string
  state: 'pending' | 'off' | 'accepted' | 'reverted'
  soft?: boolean
  /** 存这一版时这一处**前面 / 后面**的一小截正文。正文被别处改过之后靠它重新定位。 */
  before?: string
  after?: string
}

/** 一层存下来长什么样。跟后端 `note_change_layers` 的列一一对应。 */
export type SavedLayer = {
  id: string
  label: string
  source: string
  run_id?: string
  round_no?: number
  seq: number
  state: 'on' | 'off'
  at: string
  content_tag: string
  hunks: SavedHunk[]
}

/** 前后文取多少字。跟 `editor/undoRound` 那边同一个数（24 / 12 / 6 / 0 逐级缩短）——
 *  两处解决的是同一个问题：**只有文字能跨一次重启定位，坐标不能**。 */
const CONTEXT = 24
const FALLBACKS = [24, 12, 6, 0]

/** 正文的指纹：长度 + FNV-1a。
 *
 * **不是密码学哈希**，也不需要是：它唯一的用途是回答「正文还是不是存这一版时那份」。
 * 用 `crypto.subtle` 的话这一步就成了 async，而它被夹在一次同步的 dispatch 中间。
 * 长度一起带上：FNV 撞一次的代价是「按旧坐标把高亮标到别的字上」，加个长度基本堵死。 */
export function contentTag(s: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return `${s.length}:${h.toString(36)}`
}

/** 层的来源机器码。取值表在后端 `store.CHANGE_LAYER_SOURCES`，两边逐字一致
 *  （`scripts/check-change-layers.mts` 盯着）。
 *
 *  **认不出来给 `other`，不是丢掉**——丢掉就又是一次静默按「接受」。 */
export function layerSource(label: string): string {
  const s = (label ?? '').trim()
  if (s.startsWith('撤掉第')) return 'undo_round'
  if (s === '智能续写' || s === '打磨') return 'round'
  if (s === '续写') return 'continue'
  if (s === '重写') return 'rewrite'
  if (s === '润色') return 'polish'
  if (s === '扩展上下文' || s === '扩展') return 'expand'
  if (s === '格式化') return 'format'
  if (s === '智能排版') return 'restructure'
  if (s === '语音输入' || s === '插入音频') return 'voice'
  if (s === '图片转表格') return 'table'
  if (BLOCK_LABELS.has(s)) return 'block'
  return 'other'
}

/** `/` 菜单里会产出一层的那几项。**从 `SLASH_ITEMS` 直接算**，不另抄一份名单：
 *  抄一份的话菜单里长出新项、这边忘了加，新项就静静落进 `other`——
 *  一份过期的名单比没有名单更糟（`check-api-wired` 开头那句话）。 */
export const BLOCK_LABELS = new Set(
  SLASH_ITEMS.filter((i) => i.group === 'AI').map((i) => i.label))

function ctxBefore(doc: string, pos: number): string {
  return doc.slice(Math.max(0, pos - CONTEXT), pos)
}
function ctxAfter(doc: string, pos: number): string {
  return doc.slice(pos, pos + CONTEXT)
}

/** 编辑器现在挂着的层 → 存得进库的行。
 *
 * 三件事一起带走：**还活着的每一处**（`pending` / `off`）、**用户已经处置过的每一处**
 * （`accepted` / `reverted`，从 `roundDiffField` 的 `settled` 那本账来）、以及层序和 `at`。
 * 少带最后那本账，「逐处按下去的那几下」就永远写不进库——那正是这一批要修的毛病。 */
export function serializeLayers(state: EditorState): SavedLayer[] {
  const st = state.field(roundDiffField, false)
  if (!st) return []
  const doc = state.doc.toString()
  const tag = contentTag(doc)
  const out: SavedLayer[] = []
  st.layers.forEach((l, i) => {
    const live: Hunk[] = st.hunks.filter((h) => h.layer === l.id)
    const done: Settled[] = st.settled.filter((s) => s.layer === l.id)
    if (!live.length && !done.length) return
    const hunks: SavedHunk[] = []
    live.forEach((h, k) => {
      const ins = h.off ? (h.ins ?? '') : doc.slice(h.from, h.to)
      hunks.push({
        k, from: h.from, to: h.to, del: h.del, ins,
        state: h.off ? 'off' : 'pending',
        soft: h.soft,
        before: ctxBefore(doc, h.from),
        after: ctxAfter(doc, h.to),
      })
    })
    done.forEach((s, k) => {
      hunks.push({ k: live.length + k, from: 0, to: 0, del: s.del, ins: s.ins, state: s.state, soft: s.soft })
    })
    out.push({
      // `key` 是层生出来那一刻定的、跨重启不变；退回 `l${id}` 只是防漏（模块级计数器
      // 当主键的话每存一次就多一行），今天三条造层的路都会填 `key`。
      id: l.key ?? `l${l.id}`,
      label: l.label,
      source: layerSource(l.label),
      seq: i,
      // 整层开 / 关：每一处都关着才算整层关着，跟 `layersOf` 那条口径逐字一致
      state: live.length > 0 && live.every((h) => h.off) ? 'off' : 'on',
      at: new Date(l.at).toISOString(),
      content_tag: tag,
      hunks,
    })
  })
  return out
}

/** 一处在正文里找不回来时说的话。**不猜**——猜错等于把高亮标到别的字上。 */
export type Relocation =
  | { ok: true; from: number; to: number }
  | { ok: false; why: string }

/** 靠文字重新定位一处（正文被别的地方改过之后）。
 *
 * 跟 `editor/undoRound` 同一套：拿「前文 + 这处现在该长的样子 + 后文」在正文里找，
 * **唯一命中才算**；找不到就把前后文缩短一级再找（24 → 12 → 6 → 0），
 * 多处命中 / 一处都没有都算冲突。纯删除那种（这处现在是空串）**不许用 0 上下文**，
 * 空串在任何正文里都有无数个位置。 */
export function relocate(doc: string, h: SavedHunk): Relocation {
  const want = h.state === 'off' ? h.del : h.ins
  const before = h.before ?? ''
  const after = h.after ?? ''
  for (const n of FALLBACKS) {
    if (n === 0 && !want) break
    const lead = n ? before.slice(-n) : ''
    const tail = n ? after.slice(0, n) : ''
    const needle = lead + want + tail
    if (!needle) continue
    let first = -1
    let count = 0
    let at = doc.indexOf(needle)
    while (at >= 0) {
      count++
      if (first < 0) first = at
      if (count > 1) break
      at = doc.indexOf(needle, at + 1)
    }
    if (count === 1) return { ok: true, from: first + lead.length, to: first + lead.length + want.length }
  }
  const shown = (want || h.del).replace(/\s+/g, ' ').trim().slice(0, 18)
  return { ok: false, why: shown ? `「${shown}」` : '一处空改动' }
}

export type Restored = {
  layers: { key: string; label: string; at: number }[]
  hunks: { key: string; from: number; to: number; del: string; ins?: string; off?: boolean; soft?: boolean }[]
  settled: { key: string; state: 'accepted' | 'reverted'; del: string; ins: string; soft?: boolean }[]
  /** 对不上、没放回去的那几处。**要说出来**，不是悄悄少几处。 */
  conflicts: string[]
}

/** 库里的行 → 能塞进编辑器的东西。
 *
 * 正文还是存这一版时那份（`content_tag` 对得上）就按坐标直接放回去——那是**精确**的；
 * 对不上（这篇在别处被改过、或者上次没来得及存最后一版）才逐处按文字重新定位。
 * 两条路都走不通的那一处**不放**，并且在 `conflicts` 里说清是哪一处。 */
export function restoreLayers(saved: SavedLayer[], doc: string): Restored {
  const tag = contentTag(doc)
  const out: Restored = { layers: [], hunks: [], settled: [], conflicts: [] }
  for (const l of saved ?? []) {
    const at = Date.parse(l.at)
    out.layers.push({ key: l.id, label: l.label, at: Number.isFinite(at) ? at : Date.now() })
    for (const h of l.hunks ?? []) {
      if (h.state === 'accepted' || h.state === 'reverted') {
        out.settled.push({ key: l.id, state: h.state, del: h.del, ins: h.ins, soft: h.soft })
        continue
      }
      const want = h.state === 'off' ? h.del : h.ins
      const exact = l.content_tag === tag && doc.slice(h.from, h.from + want.length) === want
      const at2: Relocation = exact
        ? { ok: true, from: h.from, to: h.from + want.length }
        : relocate(doc, h)
      if (!at2.ok) {
        out.conflicts.push(`${l.label}：${at2.why}`)
        continue
      }
      out.hunks.push({
        key: l.id, from: at2.from, to: at2.to, del: h.del,
        ins: h.state === 'off' ? h.ins : undefined,
        off: h.state === 'off' ? true : undefined,
        soft: h.soft,
      })
    }
  }
  return out
}

/** 两份存下来的层一不一样。**写之前先问这一句**：位置没漂、状态没动就一个字节都不发。 */
export function sameLayers(a: SavedLayer[], b: SavedLayer[]): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}
