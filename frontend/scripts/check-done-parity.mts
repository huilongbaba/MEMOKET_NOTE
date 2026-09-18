/** 「完成标准」判定前后端对拍（P13 #1）：右栏「计划」第一格用前端 util/doneChecks，智能续写每轮用后端
 *  harness/checks/done.py——同一条完成标准对着同一篇正文，两边必须给同一个 status 和同一句 why。
 *  判据只留一份：`shared/done-cases.json`，这里跑前端那份；后端那份由 `backend/tests/test_p13.py` 跑。谁漂了谁红。
 *
 *     npx tsx scripts/check-done-parity.mts
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { checkDoneItem, splitDone, units } from '../src/util/doneChecks.ts'

type Case = { name: string; item: string; content: string; expect: { status: string; why: string } | null }
type Units = { name: string; content: string; kind: string; texts: string[] }
const table = JSON.parse(readFileSync(resolve(import.meta.dirname, '../../shared/done-cases.json'), 'utf8')) as {
  contents: Record<string, string>; cases: Case[]; units: Units[]; split: { done: string; items: string[] }[]
}
let bad = 0
const ok = (cond: unknown, msg: string) => { console.log(`${cond ? '✓' : '✗'} ${msg}`); if (!cond) bad++ }
if (table.cases.length < 20) { console.error('用例表被删了？两边的判据就是这张表'); process.exit(1) }
for (const c of table.cases) {
  const r = checkDoneItem(c.item, table.contents[c.content])
  const got = r ? { status: r.status, why: r.why } : null
  ok(JSON.stringify(got) === JSON.stringify(c.expect), `${c.name}：${JSON.stringify(got)}`)
}
for (const u of table.units) {
  const got = units(table.contents[u.content])
  ok(got.kind === u.kind && JSON.stringify(got.texts) === JSON.stringify(u.texts), `单位：${u.name}`)
}
for (const s of table.split) ok(JSON.stringify(splitDone(s.done)) === JSON.stringify(s.items), `拆条：${JSON.stringify(s.done)}`)
if (bad) { console.error(`${bad} 处跟共享用例表不一致`); process.exit(1) }
console.log('OK: 完成标准判定前端跟共享用例表一致')
