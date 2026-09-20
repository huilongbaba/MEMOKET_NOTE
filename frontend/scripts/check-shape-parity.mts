/** 「这一段整个是不是一串 JSON」前后端对拍（P40 · A，P37「留给下一批」②）。
 *
 *     npx tsx scripts/check-shape-parity.mts
 *
 * 判据只留一份：`shared/shape-cases.json`，这里跑前端 `editor/blockShape.looksLikeJson`，
 * 后端那份由 `backend/tests/test_shape_parity.py` 跑同一张表。谁漂了谁红。
 *
 * **为什么非要一张表。** 两边的注释都写着「逐字同一条」（`blockShape.ts` 头上那段、
 * `checks/shape.py` §「判据宁可窄」），而 P40 拿这张表一对，**六个样本上两边答得不一样**：
 * 围栏第一行带额外的字（```json extra）前端剥得掉、后端剥不掉；`{"a": NaN}` 后端认
 * （Python 的 `json.loads` 默认收 NaN / Infinity）、前端不认。**注释不是闸。**
 *
 * 用户那一侧的后果：同一串产出，`/` 插一块时被拦下（「模型这次答的是一串 JSON…」），
 * 智能续写那条路上却原样落进正文——**同一个毛病，一半的入口拦得住**。
 *
 * **反例是这张表的一半**（`min_counterexamples`）：正常产出不许被拦。
 * 误伤一次（用户眼睁睁看着跑完几十秒然后被拦下）比漏掉一次贵得多。
 */
import { readFileSync } from 'node:fs'

import { looksLikeJson, revisionIsJson } from '../src/editor/blockShape.ts'

type Case = { name: string; text: string; json: boolean; why?: string }
const table = JSON.parse(
  readFileSync(new URL('../../shared/shape-cases.json', import.meta.url), 'utf8'),
) as { cases: Case[]; min_cases: number; min_counterexamples: number }

const { cases } = table
if (cases.length < table.min_cases) {
  console.error(`✗ 用例只剩 ${cases.length} 条（下限 ${table.min_cases}）——两边的判据就是这张表`)
  process.exit(1)
}
const negatives = cases.filter((c) => !c.json).length
if (negatives < table.min_counterexamples) {
  console.error(`✗ 反例只剩 ${negatives} 条（下限 ${table.min_counterexamples}）——`
    + '「正常产出不许被拦」那一侧塌了，这张表就只剩半边')
  process.exit(1)
}

let bad = 0
for (const c of cases) {
  const got = looksLikeJson(c.text)
  if (got === c.json) { console.log(`✓ ${c.name}`); continue }
  bad++
  console.log(`✗ ${c.name}：前端 ${got}，表里是 ${c.json}`)
  console.log(`   样本: ${JSON.stringify(c.text)}`)
}

// 右键那三条（重写 / 润色 / 扩展上下文）换进正文的判据**跟它逐字同一条**（P35 · B）：
// 只有 JSON 这一档，块生成那三条（表格行 / 围栏 / 图片）一条都不搬。这里钉着别让它自己长出第二条。
for (const c of cases) {
  if (revisionIsJson(c.text) !== c.json) {
    bad++
    console.log(`✗ revisionIsJson 跟 looksLikeJson 漂了：${c.name}`)
  }
}

if (bad) { console.error(`\n${bad} 处跟共享用例表不一致`); process.exit(1) }
console.log(`\nOK: JSON 形状判据前端跟共享用例表一致（${cases.length} 条，其中反例 ${negatives} 条）`)
