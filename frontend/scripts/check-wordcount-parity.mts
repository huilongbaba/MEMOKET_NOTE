/** 字数前后端对拍：状态栏 / 信息面板用前端 wordCount，历史版本 / 最近删除的「N 字」用后端 util/wordcount.word_count，
 *  同一篇得是同一个数（第 547 轮之前后端是 len(content)，8330 vs 9613）。
 *
 *     npx tsx scripts/check-wordcount-parity.mts
 */
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

import { wordCount } from '../src/util/wordCount.ts'

const SAMPLES = [
  '# 标题\n\n正文 **重点** 句 [terrence-12-AB]。\n- 一条',
  'hello world',
  '| a | b |\n|---|:---:|\n| 1 | 2 |',
  '![一张很长的 alt 文字](/api/assets/x.png)\n\n[链接文字](https://x.y/z) 之后',
  '1. 一\n2. 二二\n> 引用\n\n`code` _斜_ ~删~ |竖|',
  '   缩进的 ## 标题  \n\n\n多空行',
  '',
  'v2 改过',
]
const backend = resolve(import.meta.dirname, '../../backend')
const py = resolve(backend, '.venv/bin/python')
let bad = 0
const ok = (cond: unknown, msg: string) => { console.log(`${cond ? '✓' : '✗'} ${msg}`); if (!cond) bad++ }
if (!existsSync(py)) console.log('· 后端 venv 不在，跳过')
else {
  const script = `
import json, sys
sys.path.insert(0, ${JSON.stringify(backend)})
from app.database.wordcount import word_count
print(json.dumps([word_count(s) for s in json.loads(sys.stdin.read())]))
`
  const res = JSON.parse(execFileSync(py, ['-c', script], { input: JSON.stringify(SAMPLES), encoding: 'utf8' })) as number[]
  SAMPLES.forEach((s, i) => { const n = wordCount(s); ok(n === res[i], `样本 ${i + 1}：前端 ${n} == 后端 ${res[i]}`) })
}
if (bad) { console.error(`${bad} 处不一致`); process.exit(1) }
console.log('OK: 字数前后端一致')
