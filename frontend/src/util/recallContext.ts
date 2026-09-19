/** 右栏「记忆」列表按什么召回、哪些召回来的是用户刚写的（P7，P4 #7 / #8）。
 *
 *  P4 人读 5 篇：记忆列表只看正文末 500 字、跟光标无关——用户在 N1 顶部写华为芯片，右栏是恒瑞翻译的
 *  记忆；N4 5 条全是正文已经逐字引过的原话，零信息量。这里两条纯函数：
 *    · `recallQuery`：光标所在段 + 前一段当查询；光标不在正文里（空行 / 标题 / 太短）才退回末 500 字；
 *    · `factInBody`：一条事实是不是已经在正文里（跟任一段的双字重合 ≥ 0.8，或整句子串）。 */
import { stripForRecall } from './wordCount'

export const RECALL_TAIL_CHARS = 500
export const RECALL_MIN_CHARS = 8
/** 光标段前面带多少字的上下文（只取前一段，不跨空行再往前） */
export const RECALL_CONTEXT_BEFORE = 200

export type RecallQuery = { query: string; mode: 'cursor' | 'tail' }

export function recallQuery(content: string, paragraph: string, tailChars = RECALL_TAIL_CHARS): RecallQuery {
  const para = (paragraph || '').trim()
  const p = stripForRecall(para).trim()
  if (p.length >= RECALL_MIN_CHARS && !/^#{1,6}\s/.test(p)) {
    const idx = content.indexOf(para)
    let before = (idx > 0 ? content.slice(Math.max(0, idx - RECALL_CONTEXT_BEFORE), idx) : '').replace(/\s+$/, '')
    const cut = before.lastIndexOf('\n\n')
    if (cut >= 0) before = before.slice(cut + 2)
    before = before.trim()
    if (/^#{1,6}\s/.test(before)) before = ''
    const q = stripForRecall((before ? before + '\n' : '') + para).trim()
    return { query: q, mode: 'cursor' }
  }
  return { query: stripForRecall(content.slice(-tailChars)).trim(), mode: 'tail' }
}

const norm = (s: string) => (s || '').toLowerCase().replace(/[\s\p{P}\p{S}]+/gu, '')
const grams = (s: string) => { const g = new Set<string>(); for (let i = 0; i < s.length - 1; i++) g.add(s.slice(i, i + 2)); return g }

export const IN_BODY_MIN_OVERLAP = 0.8
const IN_BODY_MIN_GRAMS = 8

/** 这条事实是不是用户已经写在正文里的原话。整句子串直接算；否则跟正文**任一段**的双字重合 ≥ 0.8。
 *  按段比、不按全文比：26k 字的长文里几乎任何双字都能在某处找到，全文比会把所有事实都判成「已在正文」。 */
export function factInBody(fact: string, content: string): boolean {
  const f = norm(fact)
  if (f.length < 6) return false
  const c = norm(content)
  if (c.includes(f)) return true
  const fg = grams(f)
  if (fg.size < IN_BODY_MIN_GRAMS) return false
  for (const para of content.split(/\n\s*\n/)) {
    const pg = grams(norm(para))
    if (pg.size === 0) continue
    let hit = 0
    for (const g of fg) if (pg.has(g)) hit++
    if (hit / fg.size >= IN_BODY_MIN_OVERLAP) return true
  }
  return false
}

/** 「为什么给我看这条」里的那半句：**这个词凭什么算证据**（计划 §2 A5）。
 *
 *  P31 实拍：面板写着「命中：再决定」——**它说对了自己在干什么，干的这件事本身是错的**。
 *  光报命中了哪个词不够，得说清那个词为什么算数。三种理由来自后端 `kb/search.evidence`：
 *    · `vocab` —— 它是你知识库里的一个词条（实体 / 主题）；
 *    · `span`  —— 这么长的一整段原话逐字对上（≥4 个汉字 / ≥3 个字母，不可能是滑窗撞的）；
 *    · `pair`  —— 它自己不够硬，是跟别的词**一起**命中才算数的。
 *  `units` 是这个词在库里出现在几条记录里，给「为什么」一个量。 */
export function evidenceWhy(e: { why: string; units: number }): string {
  const why = e.why === 'vocab' ? '知识库里的词条'
    : e.why === 'span' ? '整段原话对上'
      : '跟别的词一起才算'
  return e.units > 0 ? `${why} · 库里 ${e.units} 条提到` : why
}

/** 右栏那一行：按什么找的、命中了什么、每个命中凭什么算证据。
 *  后端没给 `evidence`（老版本 / 出错兜底）就退回原来那句「命中：X、Y」。 */
export function evidenceLine(
  mode: 'cursor' | 'tail',
  evidence: { term: string; why: string; units: number }[],
  terms: string[],
): string {
  const head = '按' + (mode === 'cursor' ? '光标这段' : '正文末尾') + '找的'
  if (evidence.length) {
    return head + '，命中：' + evidence.slice(0, 3).map((e) => `${e.term}（${evidenceWhy(e)}）`).join('、')
  }
  return head + (terms.length ? '，命中：' + terms.slice(0, 6).join('、') : '')
}
