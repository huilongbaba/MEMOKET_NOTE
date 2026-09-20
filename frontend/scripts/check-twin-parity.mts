/** 剩下那三处「两边各写一遍、谁都没盯着」的对拍（P40 · A）。
 *
 *     npx tsx scripts/check-twin-parity.mts
 *
 * 判据只留一份：`shared/twin-cases.json`，后端那份由 `backend/tests/test_twin_parity.py` 跑。
 *
 *   ① 记忆范围的标签（`api.SCOPE_LABEL` ↔ `kb/scope.SCOPE_LABEL`）——
 *      「全部」不含屏幕活动这件事是**写在标签里**的承诺，两边漂了就有一边在说假话。
 *   ② 占位标题那一组（`util/displayTitle.PLACEHOLDER` ↔ `harness/tray.PLACEHOLDER_TITLES`）——
 *      托盘里的笔记项标题是它时退回正文首行，两边认的不是同一批就两处显示不一样。
 *   ③ 空行分段（`editor/marginMemory.paragraphsWithLines` ↔ `checks/skeleton._paragraphs`）——
 *      **段落文本拿去查关系、行号回来画页边圆点**，两边切得不一样，点就画在别的段上。
 */
import { readFileSync } from 'node:fs'

import { SCOPE_LABEL } from '../src/api.ts'
import { PLACEHOLDER } from '../src/util/displayTitle.ts'
import { paragraphsWithLines } from '../src/editor/marginMemory.ts'

type Para = { name: string; content: string; expect: { line: number; text: string }[] }
const t = JSON.parse(
  readFileSync(new URL('../../shared/twin-cases.json', import.meta.url), 'utf8'),
) as {
  scope_label: Record<string, string>; placeholder_titles: string[]
  paragraphs: Para[]; paragraphs_min_cases: number
}

let bad = 0
const ok = (cond: unknown, msg: string) => { console.log(`${cond ? '✓' : '✗'} ${msg}`); if (!cond) bad++ }

if (t.paragraphs.length < t.paragraphs_min_cases) {
  console.error('✗ 用例表被删了？两边的判据就是这张表')
  process.exit(1)
}

ok(JSON.stringify(SCOPE_LABEL) === JSON.stringify(t.scope_label), '记忆范围的五个标签逐字跟表一致')
ok(JSON.stringify([...PLACEHOLDER].sort()) === JSON.stringify([...t.placeholder_titles].sort()),
  '占位标题那一组跟表一致')

for (const c of t.paragraphs) {
  const got = paragraphsWithLines(c.content).map((p) => ({ line: p.line, text: p.text }))
  ok(JSON.stringify(got) === JSON.stringify(c.expect), `分段·${c.name}：${JSON.stringify(got)}`)
}

if (bad) { console.error(`\n${bad} 处跟共享用例表不一致`); process.exit(1) }
console.log(`\nOK: 范围标签 / 占位标题 / 空行分段前端跟共享用例表一致（分段 ${t.paragraphs.length} 条）`)
