/** 前后端「引用 id」「笔记链接」正则一致性。
 *
 *     npx tsx scripts/check-regex-parity.mts
 *
 * 为什么要有：这两条正则前端一处源（util/wordCount.ts），后端却有四处手抄
 * （store._CITE / checks/citations.CITE / prompts/fragments._FACT_ID / harness/tools/tabular）。
 * 两边认的不是同一批 id，ribbon 角标和树上的 ◆ 就会对不上——之前只能靠注释里「N 处同步」提醒。
 * 不比正则字面（Python 和 JS 写法允许有差），比**行为**：同一批样本两边匹配结果要一样。
 */
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

import { CITE_RE_SOURCE, NOTE_LINK_RE, citedFactIds, linkedNoteIds } from '../src/util/wordCount.ts'
import { isSpeakerTag } from '../src/util/kbNoise.ts'

const SAMPLES = [
  '据 [terrence-12-AB] 和 [u-9-F]，又见 [terrence-12-AB]；[t-0123456789ab-1f] 也是。',
  '[链接](note://0123456789ab) [备注] [x-y-] [a-1-] [-1-A] [Ab_c-007-DEADbeef]',
  '见 [甲](note://aaaaaaaaaaaa)、[乙](note://bbbbbbbbbbbb)，再 [甲](note://aaaaaaaaaaaa)；[站](https://x.y) ![图](/api/assets/a.png) [短](note://abc)',
  '[speaker_a-3-0]文本[u-0123456789abc-1](note://0123456789abcd) [标题\n换行](note://0123456789ab)',
]

const backend = resolve(import.meta.dirname, '../../backend')
const py = resolve(backend, '.venv/bin/python')
let bad = 0
const ok = (cond: unknown, msg: string) => { console.log(`${cond ? '✓' : '✗'} ${msg}`); if (!cond) bad++ }

if (!existsSync(py)) {
  console.log('· 后端 venv 不在，跳过（CI 没装后端时允许）')
} else {
  const script = `
import json, sys
sys.path.insert(0, ${JSON.stringify(backend)})
from app.database import store
from app.harness.checks import citations
from app.harness.prompts import fragments
samples = json.loads(sys.stdin.read())
out = []
for s in samples:
    out.append({
        'store_cite': list(dict.fromkeys(store._CITE.findall(s))),
        'checks_cite': list(dict.fromkeys(citations.CITE.findall(s))),
        'store_link': list(dict.fromkeys(store._NOTE_LINK.findall(s))),
        'fragments_head': bool(fragments._FACT_ID.match(s)),
    })
print(json.dumps(out))
`
  const res = JSON.parse(execFileSync(py, ['-c', script], { input: JSON.stringify(SAMPLES), encoding: 'utf8' })) as
    { store_cite: string[]; checks_cite: string[]; store_link: string[]; fragments_head: boolean }[]
  SAMPLES.forEach((s, i) => {
    const fe = citedFactIds(s)
    ok(JSON.stringify(fe) === JSON.stringify(res[i].store_cite), `样本 ${i + 1} 引用 id：前端 ${JSON.stringify(fe)} == store._CITE`)
    ok(JSON.stringify(fe) === JSON.stringify(res[i].checks_cite), `样本 ${i + 1} 引用 id：前端 == checks/citations.CITE`)
    const links = linkedNoteIds(s)
    ok(JSON.stringify(links) === JSON.stringify(res[i].store_link), `样本 ${i + 1} 笔记链接：前端 ${JSON.stringify(links)} == store._NOTE_LINK`)
    const head = new RegExp('^' + CITE_RE_SOURCE).test(s)
    ok(head === res[i].fragments_head, `样本 ${i + 1} 开头是引用 id：前端 ${head} == prompts/fragments._FACT_ID`)
  })
}
// 说话人标签（kbNoise.SPEAKER_TAG vs who._SPEAKER_TAG）：树 / 图 / 召回三处都靠它认「speaker b」不是实体
const SPK = ['speaker a', 'Speaker B', 'speaker_c', 'speaker-d', 'speaker 12', 'speaker3', '说话人 a', '说话人2', '发言人 B', '发言人 10',
  'speakers', 'speaker phone', 'speaker', '说话人', 'speaker abc', 'speaker 123', 'loudspeaker a', 'speaker  a']
if (existsSync(py)) {
  const script2 = `
import json, sys
sys.path.insert(0, ${JSON.stringify(backend)})
from app.database.kb.who import is_speaker_tag
print(json.dumps([bool(is_speaker_tag(x)) for x in json.loads(sys.stdin.read())]))
`
  const res2 = JSON.parse(execFileSync(py, ['-c', script2], { input: JSON.stringify(SPK), encoding: 'utf8' })) as boolean[]
  SPK.forEach((x, i) => ok(isSpeakerTag(x) === res2[i], `说话人标签 ${JSON.stringify(x)}：前端 ${isSpeakerTag(x)} == 后端 ${res2[i]}`))
}
// 前端自己：NOTE_LINK_RE 是 g 正则，lastIndex 不能被谁遗留（matchAll 会克隆，但 .test/.exec 直接用会踩坑）
ok(NOTE_LINK_RE.lastIndex === 0, 'NOTE_LINK_RE.lastIndex 没被污染')
if (bad) { console.error(`${bad} 处不一致`); process.exit(1) }
console.log('OK: 前后端引用 / 链接 / 说话人标签正则行为一致')
