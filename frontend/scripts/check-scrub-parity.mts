/** 轮内 scrub（删元话语句子）前后端行为对拍。
 *
 *     npx tsx scripts/check-scrub-parity.mts
 *
 * 服务端 grounding_rules.scrub_meta_sentences_v 返回 (清理后正文, 删掉的句子列表)；客户端拿到一条条
 * `scrub` 事件后用 editor/streamJoin.applyScrub 逐句删。两边结果得一样，不然轮末对齐时每轮都差几个字
 * （第 492 轮真跑：「。 [id]」的空格）。
 */
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

import { applyScrub } from '../src/editor/streamJoin.ts'
import { fixBoldPunct } from '../src/editor/format.ts'

const SAMPLES = [
  '前言。\n\nDVT 节点从 6 月调到 8 月。 [terrence-1833-10F1] 这一步不能据此判断已经完成。 后面继续。\n\n尾巴。\n',
  '知识库里没有这条。整段都是元话语，不能据此断言。\n\n正常段落。\n\n| 表 | 不能据此 |\n|---|---|\n',
  '```\n代码里 不能据此 不动\n```\n\n一句。 两句！仍需与记录核对。 三句？\n\n\n\n多空行。',
  '没有元话语的正文。 空格 保留。\n',
  '缺少对应的版本记录，因此不能算完成。KB 里查过。剩下的。',
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
from app.harness.checks.grounding_rules import scrub_meta_sentences_v
out = []
for s in json.loads(sys.stdin.read()):
    content, removed = scrub_meta_sentences_v(s)
    out.append({'content': content, 'removed': removed})
print(json.dumps(out))
`
  const res = JSON.parse(execFileSync(py, ['-c', script], { input: JSON.stringify(SAMPLES), encoding: 'utf8' })) as { content: string; removed: string[] }[]
  SAMPLES.forEach((s, i) => {
    let local = s
    for (const sentence of res[i].removed) local = applyScrub(local, sentence)
    ok(local === res[i].content, `样本 ${i + 1}：删 ${res[i].removed.length} 句后两边一致${local === res[i].content ? '' : `\n    本地 ${JSON.stringify(local)}\n    服务端 ${JSON.stringify(res[i].content)}`}`)
  })
}
// 加粗尾标点归一（grounding_rules.fix_bold_punct vs streamJoin.fixBoldPunct）
const BOLD = ['**依赖链：**后面', '**要点。** 下一句', '正常 **粗体** 不动', '```\n**代码里：**不动\n```\n**外面：**改', '**a，**b **c）**d', '**没有尾标点**']
if (existsSync(py)) {
  const script2 = `
import json, sys
sys.path.insert(0, ${JSON.stringify(backend)})
from app.harness.checks.grounding_rules import fix_bold_punct
print(json.dumps([fix_bold_punct(s) for s in json.loads(sys.stdin.read())]))
`
  const res2 = JSON.parse(execFileSync(py, ['-c', script2], { input: JSON.stringify(BOLD), encoding: 'utf8' })) as string[]
  BOLD.forEach((s, i) => ok(fixBoldPunct(s) === res2[i], `fixBoldPunct 样本 ${i + 1}${fixBoldPunct(s) === res2[i] ? '' : `\n    本地 ${JSON.stringify(fixBoldPunct(s))}\n    服务端 ${JSON.stringify(res2[i])}`}`))
}
if (bad) { console.error(`${bad} 处不一致`); process.exit(1) }
console.log('OK: scrub / fixBoldPunct 前后端一致')
