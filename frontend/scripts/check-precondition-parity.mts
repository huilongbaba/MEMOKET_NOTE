/** 「开跑前规则就能判死」的前置判断前后端对拍（P40 · A；P1 块生成 / P3 整篇动作）。
 *
 *     npx tsx scripts/check-precondition-parity.mts
 *
 * 判据只留一份：`shared/precondition-cases.json`，这里跑前端两个纯函数
 * （`editor/preconditions.notePrecondition`、`editor/slashMenu.blockPrecondition`），
 * 后端那份由 `backend/tests/test_precondition_parity.py` 跑同一张表。谁漂了谁红。
 *
 * **原来有什么、缺什么。** `backend/tests/test_p3_edge_cases.py` 早就有一条闸，
 * 但它是拿正则去这边的 `.ts` **源码里 grep 那七句话**——核的是字面，不是行为：
 * 「有标题算不算数」（`BODY_ONLY`）这条规则两边各判各的，谁改了另一边不会红。
 * 块生成那一组（`blockPrecondition`）连字面都没人核，而两边的注释都写着「同一套规则」。
 *
 * P40 拿这张表一对，当场对出两处：
 *   · 空指令那句话前端带句号、后端不带（**同一件事两句话**，看你被哪一层拦下）；
 *   · 「还没配过模型」那一段两边不是同一句（后端说「还没配**置**模型」、且没有那个
 *     能直接抄的 Ollama 地址）。
 *
 * **有意不一样的那一组单独列**（`block_diverges`）：前端多一条「笔记还是空的」，
 * 因为后端那个函数的签名根本拿不到正文。**清单之外不许再有第二处不一样。**
 */
import { readFileSync } from 'node:fs'

import { NOT_CONFIGURED, NOT_CONFIGURED_HINT, EMPTY_NOTE, notePrecondition, type NoteAction } from '../src/editor/preconditions.ts'
import { blockPrecondition, MAX_PROMPT_CHARS, SLASH_ITEMS, type SlashItem } from '../src/editor/slashMenu.ts'

type NoteCase = { name: string; action: string; content: string; title: string; expect: string }
type BlockCase = { name: string; mode: string; prompt: string; selection: string; doc: string; expect: string }
type Diverge = { name: string; mode: string; prompt: string; selection: string; doc: string; fe: string; be: string }
type Flags = { needsPrompt: boolean; promptOptional: boolean }

const t = JSON.parse(
  readFileSync(new URL('../../shared/precondition-cases.json', import.meta.url), 'utf8'),
) as {
  empty_note: Record<string, string>; body_only: string[]
  note: NoteCase[]; note_min_cases: number
  block: BlockCase[]; block_min_cases: number; block_diverges: Diverge[]
  block_modes: string[]; block_flags: Record<string, Flags>; prompt_required: string[]
  max_prompt_chars: number
  not_configured: { short: string; hint: string }
}

let bad = 0
const ok = (cond: unknown, msg: string) => { console.log(`${cond ? '✓' : '✗'} ${msg}`); if (!cond) bad++ }

if (t.note.length < t.note_min_cases || t.block.length < t.block_min_cases) {
  console.error('✗ 用例表被删了？两边的判据就是这张表')
  process.exit(1)
}

// ---------------------------------------------------------------- 整篇动作（P3）
ok(JSON.stringify(EMPTY_NOTE) === JSON.stringify(t.empty_note), '七句话逐字跟表一致')
for (const c of t.note) {
  const got = notePrecondition(c.action as NoteAction, c.content, c.title)
  ok(got === c.expect, `整篇·${c.name}：${JSON.stringify(got)}`)
}

// ---------------------------------------------------------------- 块生成（P1）
ok(MAX_PROMPT_CHARS === t.max_prompt_chars, `指令上限 ${MAX_PROMPT_CHARS}`)

/** 表里 `字xN` = N 个「字」（两千字塞进 json 里没法看）。 */
const expand = (s: string) => {
  const m = /^字x(\d+)$/.exec(s)
  return m ? '字'.repeat(Number(m[1])) : s
}
/** 表里的 mode → 前端那个 item。`custom` 不在 `/` 菜单里（它在右键菜单），
 *  照 `App.tsx` 里构造的那份写——那一份漂了这里也得红。 */
const CUSTOM: SlashItem = { group: 'AI', key: 'custom', label: '自定义提示', icon: 'bx-message-dots',
                            hint: '对选中的这段做点什么', needsPrompt: true }
const itemOf = (mode: string): SlashItem => {
  if (mode === 'custom') return CUSTOM
  const it = SLASH_ITEMS.find((i) => i.key === mode)
  if (!it) throw new Error(`/ 菜单里没有 ${mode}——表和菜单漂了`)
  return it
}

// 「要不要一条指令」两边各存各的：前端在 SLASH_ITEMS 的两个布尔上，后端在 PROMPT_REQUIRED 那个元组里。
for (const mode of t.block_modes) {
  const it = itemOf(mode)
  const f = t.block_flags[mode]
  ok(!!it.needsPrompt === f.needsPrompt && !!it.promptOptional === f.promptOptional,
    `模式 ${mode} 的两个旗标跟表一致`)
  const required = !!it.needsPrompt && !it.promptOptional
  ok(required === t.prompt_required.includes(mode),
    `模式 ${mode} 非要一条指令不可 = ${required}（后端 PROMPT_REQUIRED 那份也得这么说）`)
}

for (const c of t.block) {
  const got = blockPrecondition(itemOf(c.mode), expand(c.prompt), c.selection, c.doc)
  ok(got === expand(c.expect), `块·${c.name}：${JSON.stringify(got)}`)
}
// 有意不一样的那一组：前端必须给 `fe` 那句（后端那边钉 `be`）。
for (const c of t.block_diverges) {
  const got = blockPrecondition(itemOf(c.mode), expand(c.prompt), c.selection, c.doc)
  ok(got === c.fe, `块·有意不一样·${c.name}：前端 ${JSON.stringify(got)}`)
  ok(c.fe !== c.be, `块·有意不一样·${c.name}：清单里这一条确实两边不一样`)
}

// ---------------------------------------------------------------- 「还没配过模型」那一段
ok(NOT_CONFIGURED === t.not_configured.short, '状态栏那一行跟表一致')
ok(NOT_CONFIGURED_HINT === t.not_configured.hint, '点下去那一段跟表一致（后端 util/llm.NOT_CONFIGURED 是同一句）')

if (bad) { console.error(`\n${bad} 处跟共享用例表不一致`); process.exit(1) }
console.log(`\nOK: 前置判断前端跟共享用例表一致（整篇 ${t.note.length} 条 + 块 ${t.block.length} 条 + 有意不一样 ${t.block_diverges.length} 条）`)
