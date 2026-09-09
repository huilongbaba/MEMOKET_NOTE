/** 前端的 applyRevision() 必须跟后端算出同一个结果。
 *
 *     npx tsx scripts/check-revision-parity.mts
 *
 * 判据是 `shared/revision-cases.json`——后端 `tests/test_revision_parity.py`
 * 读的是同一张表。两份实现同一套锚点语义是有意的（后端要在没人审核时自动
 * 应用，不能指望一份只跑在浏览器里的代码），代价是它们会漂。
 *
 * 实测漂过一次，而且很严重：同一条去重修订，后端删掉重复的那一节，前端把
 * 整篇笔记删光（只剩一个换行）。用户点一下「接受」就没了，界面上不报错。
 */
import { readFileSync } from 'node:fs'

import { applyRevision } from '../src/components/RevisionPanel.tsx'

type Case = {
  name: string; content: string; op: string; anchor: string
  anchor_end?: string; text?: string; expected: string
}

const { cases } = JSON.parse(
  readFileSync(new URL('../../shared/revision-cases.json', import.meta.url), 'utf8'),
) as { cases: Case[] }

if (cases.length < 8) {
  console.error(`✗ 用例只剩 ${cases.length} 条——两边的判据就是这张表`)
  process.exit(1)
}

let bad = 0
for (const c of cases) {
  const got = applyRevision(c.content, {
    id: '', op: c.op as never, anchor: c.anchor, anchor_end: c.anchor_end ?? '',
    text: c.text ?? '', reason: '', sources: [],
  } as never)
  if (got === c.expected) {
    console.log(`✓ ${c.name}`)
  } else {
    bad++
    console.log(`✗ ${c.name}`)
    console.log(`   实际: ${JSON.stringify(got)}`)
    console.log(`   期望: ${JSON.stringify(c.expected)}`)
  }
}
console.log(bad ? `\n✗ ${bad} 条跟后端不一致` : `\n修订语义一致：${cases.length} 条全过`)
if (bad) process.exit(1)
