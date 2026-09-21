/** 切走之后那一刀**拦谁、放谁**——那张表跟 `App.tsx` 的原文对得上吗（P101 B）。
 *
 *     ./node_modules/.bin/tsx scripts/check-harness-guard.mts
 *
 * ── 为什么要它 ──────────────────────────────────────────────────────────
 * P99 判④写着：`writeRounds` / `patchRound` 被 `currentRef` 一刀切拦住**是误伤**，
 * 该拦的是**动正文 / 动编辑器**那几条。这一批照着做了——而「照着做了」这句话
 * 要是只活在注释里，下一次有人加一条 handler、忘了归档，
 * 洞就会以另一个写法长回来（P92/P93 合并那一课逐字写着）。
 *
 * ── 它判五件事，**每一件都拿 `App.tsx` 的原文说话** ────────────────────────
 *  ① **集合相等**：`util/harnessGuard.HARNESS_GUARD` 的键 == `App.tsx` 里
 *     `const h: api.NoteHarnessHandlers = { … }` 真定义出来的那些。
 *     多一个少一个都红——**「表里有的都在」是不够的**，那是
 *     **「测试数据比判据窄」**的那张脸（新加一条忘了归档就静默绿）。
 *  ② `rounds` 那一档：那条 handler 的函数体里**真的有** `writeRounds(noteId`
 *     或 `patchRound(noteId`（或者是 `onCheckHit` 那种记 `stuckCheckRef` 的跑账）。
 *     归错档 = 把一条动正文的 handler 放行 = P95 A0 那个洞长回来。
 *  ③ `blocked` 那一档：函数体里**一句 `writeRounds(noteId` / `patchRound(noteId` 都没有**。
 *     有的话就是「明明记着账却被拦着」，正是这一批要治的那种误伤。
 *  ④ `rounds` 那一档里**还动正文**的那几条（`onRoundStart` / `onDelta` / `onEvaluate` /
 *     `onToolCalls` / `onError`），**记账那几句必须排在自己那句
 *     `if (currentRef.current?.id !== noteId) return` 前面**——排在后面等于没改。
 *     判法：函数体里第一处 `writeRounds(noteId` / `patchRound(noteId` 的下标
 *     **小于**第一处那句 guard 的下标。
 *  ⑤ **那个包装真的在问这张表**：`App.tsx` 里那一行是 `guardBlocks(k)` 而不是
 *     原来那句一刀切；`self` 那一档**正好是 `onDone` 一条**；每条的 `why` 不短于 8 个字。
 *
 * ── 它**答不了**什么（别读成「切走之后什么都不丢了」）─────────────────────
 *  · **那一刀放行之后真的留住了没有**：一条都答不了。它读的是源码的形状。
 *    那一半只有真壳上跑一趟才答得了（P101 走查里的 `rounds99 --mode away`：
 *    **切走 20 秒再切回，卡上「本轮写出的正文」2 → 2**，P99 那一趟是 2 → 1）。
 *  · **`blocked` 那一摞该不该也放行**：不判。`onCost` / `onCrossRun` / `onWarning` /
 *    `onSkeleton` 是另一条判据（见 `harnessGuard.ts` 抬头和 `docs/edge-cases.md`）。
 *  · **`App.tsx` 之外**：看不见。
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

import { HARNESS_GUARD, guardBlocks, guardedKeys } from '../src/util/harnessGuard.ts'
import { stripComments } from '../src/util/roundsWiring.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
const APP = resolve(HERE, '../src/App.tsx')

let bad = 0
let ran = 0
const ok = (c: unknown, m: string) => { ran++; console.log(`${c ? '✓' : '✗'} ${m}`); if (!c) bad++ }

/** `noteHarnessHandlers` 里那个 `const h: api.NoteHarnessHandlers = { … }` 的函数体逐条。
 *
 *  **先摘注释**（`roundsWiring.stripComments`，同一份）：注释里就写着
 *  `writeRounds(noteId` / `currentRef.current?.id !== noteId` 这些串，
 *  不摘的话判的是注释不是代码——**「文件里有这个串」≠「这段代码还在跑」**。 */
function handlerBodies(src: string): Record<string, string> {
  const s = stripComments(src)
  const start = s.indexOf('const h: api.NoteHarnessHandlers = {')
  if (start < 0) throw new Error('`App.tsx` 里解不出 `const h: api.NoteHarnessHandlers = {` —— handler 那一摞换写法了，先去读 App.tsx，别改这份闸')
  const end = s.indexOf('const guarded: api.NoteHarnessHandlers = {}', start)
  if (end < 0) throw new Error('`App.tsx` 里解不出那个 `guarded` 包装 —— 那一刀换写法了，先去读 App.tsx')
  const region = s.slice(start, end)
  // 每一条 handler 都以行首 6 个空格 + `onXxx: (` 起头（那一摞的缩进是稳的）。
  const heads = [...region.matchAll(/^ {6}(on[A-Za-z]+): \(/gm)]
  if (!heads.length) throw new Error('那一摞里一条 `onXxx: (` 都解不出来 —— 缩进或写法变了')
  const out: Record<string, string> = {}
  heads.forEach((m, i) => {
    const from = m.index!
    const to = i + 1 < heads.length ? heads[i + 1].index! : region.length
    out[m[1]] = region.slice(from, to)
  })
  return out
}

const src = readFileSync(APP, 'utf8')
const bodies = handlerBodies(src)

// ── ① 集合相等 ────────────────────────────────────────────────────────────
const inApp = Object.keys(bodies).sort()
const inTable = Object.keys(HARNESS_GUARD).sort()
ok(inApp.length === 22, `\`App.tsx\` 里解出 22 条 handler（实得 ${inApp.length}）`)
ok(JSON.stringify(inApp) === JSON.stringify(inTable),
  '那张表的键跟 `App.tsx` 里真定义的那些**逐条相等**'
  + (JSON.stringify(inApp) === JSON.stringify(inTable) ? ''
    : `：表里多了 ${inTable.filter((k) => !inApp.includes(k))}，少了 ${inApp.filter((k) => !inTable.includes(k))}`))

// ── ② / ③ 归档对不对：拿函数体的原文说话 ──────────────────────────────────
const KEEPS_BOOKS = /\b(writeRounds|patchRound)\(noteId\b/
const GUARD_LINE = 'if (currentRef.current?.id !== noteId) return'

for (const k of inApp) {
  const body = bodies[k]
  const e = HARNESS_GUARD[k]
  if (!e) continue
  if (e.verdict === 'rounds') {
    const books = KEEPS_BOOKS.test(body) || /stuckCheckRef\.current =/.test(body)
    ok(books, `\`${k}\` 归 rounds，函数体里真的有按 noteId 记的那一句`)
  } else if (e.verdict === 'blocked') {
    ok(!KEEPS_BOOKS.test(body),
      `\`${k}\` 归 blocked，函数体里一句 \`writeRounds(noteId\` / \`patchRound(noteId\` 都没有`)
  }
  ok((e.why ?? '').length >= 8, `\`${k}\` 的「为什么」不短于 8 个字`)
}

// ── ④ 记账那几句排在自己那句 guard 前面 ──────────────────────────────────
//
// ⚠️ **这一条第一版有个洞，是设计砍刀的时候现形的**（刀 ⑦）：原来写的是
// 「解不出 guard 那一行就跳过」——于是把 `onDelta` 里那句 guard **整行删掉**
// 这条闸一声不吭，而那正是最危险的一刀（放行之后它会动现在显示的那篇的正文）。
// **「解不出来」和「不适用」不是一回事**——判据比产品窄的又一张脸。
//
// 现在分两档，**哪一档由函数体自己说了算**：
//  · 函数体里有**只属于「现在显示的这篇」**的动作（下面那张名单）⇒
//    那句 guard **必须在**，而且记账排在它前面；
//  · 整条都是按 noteId 记账（名单里一条都不碰）⇒ 那句 guard 本来就该删干净。
//
// **名单是逐条点名的，不是一句「动 UI 的」**：`setContent` / `liveContentRef` /
// `pushDiff` / `view.dispatch` 是动正文和编辑器；`toast` / `setNoteHarnessStatus` /
// `setBeatCoverage` / `setUndoGroup` / `setHarnessDone` / `insertCursorRef` 是
// 动**这一刻屏幕上那一篇**的东西——切走之后它们说的都是另一篇的事。
const TOUCHES_CURRENT = new RegExp([
  'setContent\\(', 'liveContentRef\\.current =', 'pushDiff\\(', 'view\\.dispatch',
  'toast\\(', 'toastAction\\(', 'setNoteHarnessStatus\\(', 'setBeatCoverage\\(',
  'setUndoGroup\\(', 'setHarnessDone\\(', 'insertCursorRef\\.current =',
].join('|'))
for (const k of guardedKeys('rounds')) {
  const body = bodies[k]
  const g = body.indexOf(GUARD_LINE)
  const b = body.search(KEEPS_BOOKS)
  if (TOUCHES_CURRENT.test(body)) {
    ok(g >= 0, `\`${k}\` 归 rounds，但函数体里还动着「现在显示的这篇」—— 那句 guard **必须在**`)
    ok(g >= 0 && b >= 0 && b < g,
      `\`${k}\` 记账那一句排在自己那句 guard **前面**（记账 @${b} < guard @${g}）——排在后面等于没改`)
  } else {
    ok(g < 0, `\`${k}\` 整条都是按 noteId 记账，那句一刀切的 guard 该删干净（实得 @${g}）`)
  }
}

// ── ⑤ 包装真的在问这张表 + 两条形状 ──────────────────────────────────────
const stripped = stripComments(src)
ok(/if \(k !== 'onDone' && guardBlocks\(k\) && currentRef\.current\?\.id !== noteId\) return/.test(stripped),
  '那个包装那一行真的在问 `guardBlocks(k)`（不是原来那句一刀切）')
ok(!/if \(k !== 'onDone' && currentRef\.current\?\.id !== noteId\) return/.test(stripped),
  '原来那句一刀切**不在了**（留着的话两条同时在，后一条照样拦光）')
ok(JSON.stringify(guardedKeys('self')) === JSON.stringify(['onDone']),
  '`self` 那一档正好是 `onDone` 一条')
ok(guardBlocks('onDelta') === false && guardBlocks('onRevision') === true,
  '`guardBlocks` 自己：onDelta 放行 / onRevision 照拦')
ok(guardBlocks('onNeverHeardOf') === true,
  '表里没有的键 ⇒ **拦**（保守那一侧，不是静默放行）')

// ── 这一批放行了几条、还拦着几条：**把数打出来**，台账抄的就是这三个数 ───────
console.log(`\n放行 ${guardedKeys('rounds').length} 条：${guardedKeys('rounds').join(' ')}`)
console.log(`照拦 ${guardedKeys('blocked').length} 条：${guardedKeys('blocked').join(' ')}`)
console.log(`自理 ${guardedKeys('self').length} 条：${guardedKeys('self').join(' ')}`)
console.log(`\n共核 ${ran} 条，${bad} 条对不上`)
if (bad) process.exit(1)
