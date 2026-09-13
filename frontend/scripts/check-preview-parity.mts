/** 同名笔记消歧用的「正文首行」前后端对拍：服务端 store._first_body_line（⌘K 笔记组 / [[ 补全）
 *  和客户端 util/virtual.previewLine（侧栏预览 / ⌘K 标签组 / ▾ 标签列表）要给同一截。
 *
 *     npx tsx scripts/check-preview-parity.mts
 */
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

import { previewLine } from '../src/util/virtual.ts'
import { displayTitle } from '../src/util/displayTitle.ts'

const SAMPLES: [string, string][] = [
  ['# 会议纪要 10\n- 第一条\n- 第二条', '会议纪要 10'],
  ['    ## 时间线\n正文在这', ''],
  ['# 题\n![图](/api/assets/a.png)\n```\ncode\n```\n## 小标题\n**重点**句子', '题'],
  ['# 题\n## 只有小标题\n### 再一个', '题'],
  ['创业一年回顾\n\n就目前可核验的记录，创业第一年尚不能证明 APP…', '未命名'],
  ['创业一年回顾\n\n时间线与里程碑', '创业一年回顾'],
  ['1. 一\n2. 二二', ''],
  ['> 引用一句\n\n_斜体_ 与 `code`', '标题'],
  ['', ''],
  ['x\ny\n只有这行够长', 'x'],
]
// 显示名（标题是占位符时拿正文首行截句读）：exporters.display_title / clip_title vs util/displayTitle
const TITLES: [string, string][] = [
  ['未命名', '今天跟供应商确认了 PCBA 样品的交期，4 月 10 日拿到手板之后再定下一步的测试安排。'],
  ['', '    # 时间线与里程碑\n正文'],
  ['note', 'APP定义：先锚定范围，再谈功能。'],
  ['Untitled', '好的，那就这么定了。'],
  ['真标题', '# 会被忽略的首行'],
  ['未命名', ''],
  ['未命名', '一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十一二三'],
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
from app.database.store import _first_body_line
print(json.dumps([_first_body_line(c, t) for c, t in json.loads(sys.stdin.read())]))
`
  const res = JSON.parse(execFileSync(py, ['-c', script], { input: JSON.stringify(SAMPLES), encoding: 'utf8' })) as string[]
  SAMPLES.forEach(([c, t], i) => { const l = previewLine(c, t); ok(l === res[i], `样本 ${i + 1}${l === res[i] ? '' : `\n    本地 ${JSON.stringify(l)}\n    服务端 ${JSON.stringify(res[i])}`}`) })
  const script2 = `
import json, sys
sys.path.insert(0, ${JSON.stringify(backend)})
from app.database.exporters import display_title
print(json.dumps([display_title(t, c) for t, c in json.loads(sys.stdin.read())]))
`
  const res2 = JSON.parse(execFileSync(py, ['-c', script2], { input: JSON.stringify(TITLES), encoding: 'utf8' })) as string[]
  TITLES.forEach(([t, c], i) => { const l = displayTitle({ title: t, content: c }); ok(l === res2[i], `显示名 ${i + 1}${l === res2[i] ? '' : `\n    本地 ${JSON.stringify(l)}\n    服务端 ${JSON.stringify(res2[i])}`}`) })
}
if (bad) { console.error(`${bad} 处不一致`); process.exit(1) }
console.log('OK: 正文首行 / 显示名前后端一致')
