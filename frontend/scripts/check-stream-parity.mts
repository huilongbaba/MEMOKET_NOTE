/** 轮内正文镜像的另外两条规则前后端对拍：空行归一（tidy_blank_lines）和定向插入（outline.insert_into）。
 *
 *     npx tsx scripts/check-stream-parity.mts
 *
 * 客户端在 `insert_at` 事件时用 prepareInsert 腾位置、之后 delta 一块块 insertStreamed 进去；
 * 服务端是拿整段文字一次 insert_into。两边最后得一样（尾部空白除外——服务端 scrub 之后会 strip）。
 */
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

import { insertStreamed, prepareInsert, tidyBlankLines } from '../src/editor/streamJoin.ts'
import { sectionEnd } from '../src/util/sectionEnd.ts'

const TIDY = [
  'a\n\n\n\nb\n  \n\nc  \n', '```\n\n\n\n代码里\n```\n\n\n后面', '  \n\n# 标题  \n\n\n\n- 项', '',
]
const INSERT: { base: string; pos: number; text: string; chunks: number }[] = [
  { base: '## A\n正文。\n\n## B\n乙\n', pos: 9, text: '\n\n新写的一段。\n\n', chunks: 3 },
  { base: '## A\n正文。\n\n## B\n乙\n\n\n', pos: 9, text: '一句。\n再一句。\n', chunks: 5 },
  { base: '甲。，后半句', pos: 2, text: '插入', chunks: 1 },
  { base: '只有一段。\n', pos: 6, text: '追加到末尾。\n\n\n', chunks: 2 },
  { base: '# 题\n\n段一。\n\n段二。', pos: 8, text: '\n\n\n中间多空行\n\n\n', chunks: 4 },
]
const split = (t: string, n: number) => { const out: string[] = []; const step = Math.max(1, Math.ceil(t.length / n)); for (let i = 0; i < t.length; i += step) out.push(t.slice(i, i + step)); return out }
const trimEnd = (t: string) => t.replace(/\s+$/, '')

// 定向续写的落点：客户端拿自己的正文重算（onInsertAt），服务端给的 pos 只是兜底——两边必须是同一条规则
const SECTIONS: [string, string][] = [
  ['# 一\n正文\n\n## 二\n正文二\n\n## 三\n正文三', '二'],
  ['# 一\n正文\n\n## 二\n正文二\n\n### 二点一\n更深的\n\n## 三\n三', '二'],
  ['# 一\n只有一节', '一'],
  ['# 一\n正文', '不存在的标题'],
  ['## 市场\n正文\n\n```\n# 这是代码注释不是标题\n```\n\n## 硬件\n正文', '市场'],
  ['# 标题  \n带尾随空格的标题', '标题'],
  ['正文没有任何标题', '一'],
  ['```\n# 未闭合围栏里的\n## 也是\n', '未闭合围栏里的'],
  ['# 一\n\n#不是标题（没空格）\n\n## 二\n二', '一'],
]
const backend = resolve(import.meta.dirname, '../../backend')
const py = resolve(backend, '.venv/bin/python')
let bad = 0
const ok = (cond: unknown, msg: string) => { console.log(`${cond ? '✓' : '✗'} ${msg}`); if (!cond) bad++ }
if (!existsSync(py)) {
  console.log('· 后端 venv 不在，跳过')
} else {
  const script = `
import json, sys
sys.path.insert(0, ${JSON.stringify(backend)})
from app.harness.revision import tidy_blank_lines
from app.editor.outline import insert_into
inp = json.loads(sys.stdin.read())
print(json.dumps({'tidy': [tidy_blank_lines(s) for s in inp['tidy']],
                  'insert': [insert_into(c['base'], c['pos'], c['text']) for c in inp['insert']]}))
`
  const res = JSON.parse(execFileSync(py, ['-c', script], { input: JSON.stringify({ tidy: TIDY, insert: INSERT }), encoding: 'utf8' })) as { tidy: string[]; insert: string[] }
  TIDY.forEach((s, i) => ok(tidyBlankLines(s) === res.tidy[i], `tidy 样本 ${i + 1}${tidyBlankLines(s) === res.tidy[i] ? '' : `\n    本地 ${JSON.stringify(tidyBlankLines(s))}\n    服务端 ${JSON.stringify(res.tidy[i])}`}`))
  const script3 = `
import json, sys
sys.path.insert(0, ${JSON.stringify(backend)})
from app.editor.outline import section_end
print(json.dumps([section_end(c, t) for c, t in json.loads(sys.stdin.read())]))
`
  const res3 = JSON.parse(execFileSync(py, ['-c', script3], { input: JSON.stringify(SECTIONS), encoding: 'utf8' })) as (number | null)[]
  SECTIONS.forEach(([c, t], i) => { const n = sectionEnd(c, t); ok(n === res3[i], `section_end 样本 ${i + 1}（${JSON.stringify(t)}）：前端 ${n} == 后端 ${res3[i]}`) })
  INSERT.forEach((c, i) => {
    const r = prepareInsert(c.base, c.pos)
    let content = r.next; let cursor: number | null = r.cursor
    for (const piece of split(c.text, c.chunks)) { const x = insertStreamed(content, cursor, piece); content = x.next; cursor = x.cursor }
    const local = tidyBlankLines(content)
    const server = res.insert[i]
    const same = trimEnd(local) === trimEnd(server)
    ok(same, `insert 样本 ${i + 1}（${c.chunks} 块）${same ? '' : `\n    本地 ${JSON.stringify(local)}\n    服务端 ${JSON.stringify(server)}`}`)
  })
}
if (bad) { console.error(`${bad} 处不一致`); process.exit(1) }
console.log('OK: tidy / insert / section_end 前后端一致')
