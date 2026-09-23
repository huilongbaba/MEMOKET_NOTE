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

/** `before` = **这一趟真的拼进查询的那一截前一段**（已 strip 过；`tail` 档恒为 `''`）。
 *
 *  P80 A：面板上那一行写着「按**光标这段**找的」，而查询是「前一段 + 这一段」——
 *  前一段词多的时候，摆出来的命中词**一个都可以不在光标这段里**（实拍见
 *  `editor/__tests__/p80.test.ts`）。要把那句话说老实，就得让面板知道
 *  「哪一截是前一段带进来的」。**这儿只是把它交出去，判在 `termFromBefore`。** */
export type RecallQuery = { query: string; mode: 'cursor' | 'tail'; before: string }

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
    return { query: q, mode: 'cursor', before: stripForRecall(before).trim() }
  }
  return { query: stripForRecall(content.slice(-tailChars)).trim(), mode: 'tail', before: '' }
}

/** 这个命中词是**前一段带进来的**吗（P80 A）。
 *
 *  **两条都成立才算**，宁可少说一句：
 *    ① 它**不在光标这段里**，而且 ② 它**确实在前一段那一截里**。
 *
 *  只判前半条会冤枉人：命中词是后端在**拼好的查询**上切出来的，切法跟这里的子串判法
 *  不是同一把尺（**判据比产品窄**那张脸），落差会变成屏幕上一句假话——
 *  比原来那句含糊话更糟。两条都要，落差只会让它**少说**一句。 */
export function termFromBefore(term: string, paragraph: string, before: string): boolean {
  if (!term || !before) return false
  const inPara = stripForRecall(paragraph || '').includes(term)
  return !inPara && before.includes(term)
}

/** 那半句本身。单独拎出来是为了**量具和判据引的是同一个串**（P67 ② 那条「一屏一把尺」）。 */
export const FROM_BEFORE_NOTE = '前一段带进来的'

/** 这一趟拿哪几个词去判「前一段带进来的」（P83 A）。
 *
 *  **三档跟 `evidenceLine` 逐字同一条**（P46 #1）——同一屏上两把尺就是 P40 那次
 *  「校验说有 6 条、脉络说没有」的形状：
 *    · 有证据 —— 用证据里的词（后端**判过**的那一份）；
 *    · `[]`   —— **判过了、一条都摆不出来**：那就一个词都别拿去判卡。退回 `terms`
 *               等于把后端刚判掉的那几串捡回来当依据（P44 问题 #3 那条路），
 *               而这一次捡回来是要往卡上盖戳，比印在那一行上更难撤；
 *    · 没这一格（老后端 / 判据自己抛了）—— 没人判过，退回 `terms` 是对的，
 *               跟那一行**同进同退**。 */
export function evidencePool(
  evidence: { term: string; why: string; units: number }[] | null | undefined,
  terms: string[],
): string[] {
  if (evidence && evidence.length) return evidence.map((e) => e.term)
  if (evidence) return []
  return terms
}

/** 底下那张记忆卡是**前一段带回来的**吗（P83 A）。
 *
 *  P80 只把那**一行**的说法改老实了（「命中：X（前一段带进来的）」），
 *  底下那 5 张卡还是混着的：哪几张是因为「光标这一段」捞回来的、哪几张是因为
 *  「前一段」捞回来的，用户一点提示都没有。真库实测 964 张卡里 **133 张**
 *  是前一段带回来的，其中 **29 条查询是混着的**、**33 条整屏 5 张全是前一段的**。
 *
 *  **两条都成立才标**（照抄 P80 立的形状，宁可少说一句）：
 *    ① 这张卡里**一个「光标这段里的命中词」都没有**；
 *    ② 这张卡里**至少有一个「前一段带进来的命中词」**（`termFromBefore` 那两条）。
 *
 *  ⚠️ **第 ① 条是「一票否决」不是「多数决」**：只要卡里沾着一个光标这段的词，
 *  它就至少有一半是因为这一段被捞回来的，那时候盖一个「前一段带进来的」是句假话。
 *  ⚠️ 命中词是后端在**拼好的查询**上切出来的，卡里一个词都不含是常有的事
 *  （召回不是靠子串）——那时候两条都不成立，**不标**。落差只会让它少说。
 *
 *  ⚠️ **`paragraph` / `before` 必须是「发那一问时」的那两段**，不是渲染这一刻的
 *  ——跟 `evidenceLine` 的 `ctx` 同一条口径（P80 A）。 */
export function cardFromBefore(factText: string, pool: string[], paragraph: string, before: string): boolean {
  const body = stripForRecall(factText || '').toLowerCase()
  if (!body || !before) return false
  const inPara = stripForRecall(paragraph || '')
  let fromBefore = false
  for (const t of pool) {
    if (!t || !body.includes(t)) continue
    if (termFromBefore(t, paragraph, before)) fromBefore = true
    else if (inPara.includes(t)) return false     // ① 一票否决
  }
  return fromBefore
}

/** 这张卡是否有**可逐字核对**的当前段命中词。
 *
 * `!cardFromBefore` 不能反推“来自当前段”：它还包括“分词/语义召回到了，但前端无法用子串
 * 说明原因”的卡。只有命中词同时出现在当前段和事实文本里，才盖“当前段”标记。 */
export function cardFromCurrent(factText: string, pool: string[], paragraph: string): boolean {
  const body = stripForRecall(factText || '').toLowerCase()
  const para = stripForRecall(paragraph || '').toLowerCase()
  if (!body || !para) return false
  return pool.some((term) => {
    const t = (term || '').toLowerCase()
    return !!t && para.includes(t) && body.includes(t)
  })
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

/** 「脉络」空手而归时，右栏在那句话下面多说的**出路**那一行（P41 #1 / P40 问题 #1）。
 *
 *  P40 实拍：同一屏上「校验」说「知识库里有 6 条相关记录」，「来龙去脉」说
 *  「知识库里没有跟这段沾边的记录。」——**两块面板互相打架**。后端那句话这一批已经
 *  照 `VerifyOut` 的思路分成三档（`AskOut.recalled`），这里补的是它答不了的那半句：
 *  **那几条在哪儿能看到**。
 *
 *  判据**窄**：只有「KITE 一条都没串出来（`facts` 空）**而且**词法召回真的有数」
 *  这一档才说。串出东西了不说（下面就列着）；`recalled` 是 0 / `null`（老后端没这一格）
 *  也不说——那时候多说一句就是又一次替空气背书。 */
export function traceRecallHint(factCount: number, recalled?: number | null): string {
  if (factCount > 0) return ''
  const n = recalled ?? 0
  if (n <= 0) return ''
  return `那 ${n} 条在右栏「记忆」里按同一段话就能直接看到——「脉络」要的是先后顺序，这一步没串起来。`
}

/** 证据一条都摆不出来时那一句（P46 #1）。
 *
 *  **P44 实拍的毛病**：后端那两条显示过滤让 9 / 765 条查询的证据列表空掉，
 *  这里原来退回 `display_terms`，摆出来的是「矿山行业最重要、**希望通过智能化能**、
 *  矿区工作环境恶劣」——**比被砍掉的那个碎片还长、还碎**（`display_terms` 会往后
 *  接到汉字串的尽头）。后端刚判完「这些串都不合格」，前端转手拿一份**没判过**的去顶，
 *  等于把后端那一刀原地撤销，还撤成了更难看的样子。
 *
 *  **判过了就如实说一句。** 召回那几条一条不少（`qualifies` 没动），
 *  说不出来的只是「为什么是这几条」。 */
export const NO_EVIDENCE_LINE = '这一段没有可摆出来的证据'

/** 右栏那一行：按什么找的、命中了什么、每个命中凭什么算证据。
 *
 *  **`[]` 和 `null` / `undefined` 不是一回事**（P46 #1，后端 `RecallOut.evidence` 同一条口径）：
 *    · 有东西 —— 摆前 3 个，每个带上它凭什么算证据；
 *    · `[]`   —— **判过了，一条都摆不出来**：如实说一句，**不许**退回 `terms`
 *               那串没判过的（那正是 P44 问题 #3 摆出「希望通过智能化能」的那条路）；
 *    · 没这一格（老后端 / 判据自己抛了）—— 没人判过，退回原来那句「命中：X、Y」是对的。
 *
 *  **P80 A 加的第四件事**：`ctx` 给了的话，摆出来的每个词再问一句
 *  「它是不是**前一段带进来的**」，是就当场点出来。`ctx` 不给逐字不变
 *  （老调用、老快照一个字都不动）。**`ctx` 里那两段必须是「发那一问时」的，
 *  不是渲染这一刻的**——拿新光标段去标旧结果又是一次张冠李戴。 */
export function evidenceLine(
  mode: 'cursor' | 'tail',
  evidence: { term: string; why: string; units: number }[] | null | undefined,
  terms: string[],
  ctx?: { paragraph: string; before: string } | null,
): string {
  const head = '按' + (mode === 'cursor' ? '光标这段' : '正文末尾') + '找的'
  const why = (e: { term: string; why: string; units: number }) => {
    const base = evidenceWhy(e)
    return ctx && termFromBefore(e.term, ctx.paragraph, ctx.before) ? `${FROM_BEFORE_NOTE} · ${base}` : base
  }
  if (evidence && evidence.length) {
    return head + '，命中：' + evidence.slice(0, 3).map((e) => `${e.term}（${why(e)}）`).join('、')
  }
  if (evidence) return head + '，' + NO_EVIDENCE_LINE
  if (!terms.length) return head
  const shown = terms.slice(0, 6).map((t) =>
    ctx && termFromBefore(t, ctx.paragraph, ctx.before) ? `${t}（${FROM_BEFORE_NOTE}）` : t)
  return head + '，命中：' + shown.join('、')
}
