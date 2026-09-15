/** `/` 菜单的 mode 前后端对拍。
 *
 *     npx tsx scripts/check-block-modes.mts
 *
 * **为什么要有**：`App.onSlash` 最后一句是
 * `mode: item.key as api.BlockMode` —— 一个**不查的强转**。菜单里加一项、
 * key 少写一个字母，tsc / eslint / vitest 全绿，请求照发，后端在
 * `modes.BLOCK[mode]` 上抛 KeyError，用户看到的是「点了没反应」。
 * 前端的 `BLOCK_MODES` 和后端的 `harness/modes.BLOCK` 必须逐字一致
 * （第 708 轮）。
 */
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

import { BLOCK_MODES } from '../src/api.ts'

const backend = resolve(import.meta.dirname, '../../backend')
const py = resolve(backend, '.venv/bin/python')
let bad = 0
if (!existsSync(py)) console.log('· 后端 venv 不在，跳过')
else {
  const script = `
import json, sys
sys.path.insert(0, ${JSON.stringify(backend)})
from app.harness import modes
print(json.dumps(sorted(modes.BLOCK.keys())))
`
  const out = execFileSync(py, ['-c', script], { encoding: 'utf8' }).trim().split('\n').pop() ?? '[]'
  const back: string[] = JSON.parse(out)
  const front = [...BLOCK_MODES].sort()
  if (back.length < 4) { console.error('闸门失效：后端只读到 ' + back.length + ' 个 block mode'); process.exit(1) }
  for (const k of front) if (!back.includes(k)) { bad++; console.log(`✗ 前端有 ${k}，后端 modes.BLOCK 里没有 —— 点下去会 KeyError`) }
  for (const k of back) if (!front.includes(k)) { bad++; console.log(`✗ 后端有 ${k}，前端 BLOCK_MODES 里没有 —— 这个能力前端到不了`) }
  if (!bad) console.log(`✓ block mode 前后端一致（${front.join(' / ')}）`)
}
if (bad) { console.error(`${bad} 处`); process.exit(1) }
console.log('OK: / 菜单的 mode 前后端一致')
