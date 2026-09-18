/**
 * 关系卡上的动作（引用这条 / 新的取代旧的 / 补进来 / 合成一条 / 忽略）——右栏「记忆」的卡
 * 和页边圆点旁边的卡（P9 `MarginCard`）**同一份**，不然两处会漂（同一个动作两个门）。
 *
 * 「忽略」记在本机（localStorage）：同一对事实下次不再提。key = 关系 + 事实 id 列表。
 */
import { mergeFacts, supersedeFact, type Fact, type MemoryRelationKind } from '../api'
import { toast } from '../toast'
import { friendlyError } from './friendlyError'

export type RelationLike = { relation: MemoryRelationKind; fact_ids: string[]; facts: Fact[] }

const IGNORED_KEY = 'memoket-note-ignored-relations'

export function relationKey(r: RelationLike): string { return r.relation + ':' + r.fact_ids.join(',') }

export function ignoredSet(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(IGNORED_KEY) || '[]')) } catch { return new Set() }
}

export function ignoreRelation(key: string): Set<string> {
  const next = ignoredSet(); next.add(key)
  try { localStorage.setItem(IGNORED_KEY, JSON.stringify([...next].slice(-200))) } catch { /* 无所谓 */ }
  window.dispatchEvent(new CustomEvent('relation-ignored', { detail: key }))
  return next
}

/** 「新的取代旧的」：库里有两条时把早的标成被晚的取代。正文这句还不是记录时说清楚去哪补。 */
export async function supersedeRelation(rel: RelationLike): Promise<boolean> {
  const old = rel.facts[0]
  const latest = rel.facts[rel.facts.length - 1]
  if (!old || !latest || old.id === latest.id) { toast('正文这句还不是知识库里的记录——先在「引用」页「补一条」，再来标取代'); return false }
  try { await supersedeFact(old.id, latest.id); toast('已标记：旧记录被新的取代'); ignoreRelation(relationKey(rel)); return true }
  // P3 遗留（？）：原来 `String(e)`，后端没起来时是英文 `TypeError: Failed to fetch`
  catch (e) { toast('标不上：' + friendlyError(e), 'error'); return false }
}

/** 「合成一条」：留晚的那条，早的标成被它取代（merged）；结果记住，下次不再提这一对 */
export async function mergeRelation(rel: RelationLike): Promise<boolean> {
  const [a, b] = rel.facts
  if (!a || !b) return false
  try { await mergeFacts(b.id, a.id); toast('已合成一条：留下了 ' + (b.when || '晚的那条')); ignoreRelation(relationKey(rel)); return true }
  catch (e) { toast('合不了：' + friendlyError(e), 'error'); return false }
}

/** 「补进来」：把知识库里那几个条件带引用插进正文 */
export function fillInText(rel: RelationLike): string {
  return rel.facts.map((f) => `${f.text} [${f.id}]`).join('\n')
}

/** 「引用这条」：最新的那条带出处 */
export function citeText(rel: RelationLike): string {
  const f = rel.facts[rel.facts.length - 1]
  return f ? `${f.text} [${f.id}]` : ''
}

/** 正文里已经引了最新那条 */
export function alreadyCited(rel: RelationLike, content: string): boolean {
  const f = rel.facts[rel.facts.length - 1]
  return !!f && content.includes(`[${f.id}]`)
}
