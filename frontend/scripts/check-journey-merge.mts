/** 分段合并：壳里那份（TS）和 P0 脚本那份（Python）必须一致。
 *
 * 这条规则是**在真实使用上量出来的**（第 633 轮，51 分钟）：不合并瞬时切换的话
 * 一天切出 169 段，合并之后 75 段。两份实现漂开的话，P0 量出来的东西就不能用来
 * 说明产品里会发生什么——而这个功能的每一个阈值都是那么定下来的。
 *
 *     npx tsx scripts/check-journey-merge.mts
 */
import { execFileSync } from 'node:child_process'
import { DENY_APPS, DENY_TITLE_WORDS, mergeBlips, type Segment } from '../../desktop/src/capture.ts'
import { GAP_MIN as JOURNEY_GAP_MIN, saySpan } from '../src/components/JourneyPage'

const B = Date.parse('2026-09-14T18:00:00Z')   // 带 Z：两边都按 UTC 算，不然差一个时区
const seg = (app: string, m0: number, m1: number, n = 5): Segment => ({
  app, title: '', n, frames: [],
  start: new Date(B + m0 * 60_000).toISOString(),
  end: new Date(B + m1 * 60_000).toISOString(),
})
const shape = (ss: Segment[]) =>
  ss.map((s) => [s.app, (Date.parse(s.start) - B) / 60_000, (Date.parse(s.end) - B) / 60_000])

const CASES: { why: string; input: Segment[] }[] = [
  { why: '同一个应用的短段被吸收', input: [seg('Code', 0, 5), seg('Code', 5, 5.2), seg('Code', 5.2, 9)] },
  { why: '切走一下又切回来', input: [seg('Code', 0, 5), seg('Safari', 5, 5.5), seg('Code', 5.5, 12)] },
  { why: '真的换了件事就算短也留着', input: [seg('Code', 0, 5), seg('Safari', 5, 5.5), seg('Feishu', 5.5, 12)] },
  { why: '切走很久不算插曲', input: [seg('Code', 0, 5), seg('Safari', 5, 7), seg('Code', 7, 20)] },
  { why: '实拍那一串', input: [seg('Code', 6, 11), seg('Code', 12, 12), seg('Feishu', 12, 15), seg('Code', 15, 16), seg('Electron', 16, 17)] },
  { why: '空的', input: [] },
]

const py = `
import sys, json, datetime as dt
sys.path.insert(0, ${JSON.stringify(new URL('../../backend', import.meta.url).pathname)})
from scripts.journey_probe import merge_blips
out = []
for case in json.load(sys.stdin):
    segs = [{**s, 'start': dt.datetime.fromisoformat(s['start'].replace('Z','+00:00')),
             'end': dt.datetime.fromisoformat(s['end'].replace('Z','+00:00'))} for s in case]
    B = dt.datetime.fromisoformat('2026-09-14T18:00:00+00:00')
    out.append([[s['app'], (s['start']-B).total_seconds()/60, (s['end']-B).total_seconds()/60]
                for s in merge_blips(segs)])
print(json.dumps(out))
`
const venv = new URL('../../backend/.venv/bin/python', import.meta.url).pathname
const got = JSON.parse(execFileSync(venv, ['-c', py], {
  input: JSON.stringify(CASES.map((c) => c.input)), encoding: 'utf8',
})) as unknown[][]

let bad = 0
CASES.forEach((c, i) => {
  const ts = JSON.stringify(shape(mergeBlips(c.input)))
  const pyOut = JSON.stringify(got[i])
  const ok = ts === pyOut
  console.log(`${ok ? '✓' : '✗'} ${c.why}`)
  if (!ok) { bad++; console.log(`    TS  ${ts}\n    PY  ${pyOut}`) }
})
console.log(bad ? `${bad} 处两边对不上` : `${CASES.length} 个用例，壳和 P0 脚本给出同一个分段`)

// ——— 内置黑名单两处必须一模一样 ————————————————————————————————
//
// 拦截发生在壳里（命中时连截图都不拍），而**界面上那份「默认不记的」是后端给的**。
// 两边漂了的后果特别坏：界面上写着「不记」，实际一直在记。
const pyDeny = JSON.parse(execFileSync(venv, ['-c', `
import json, sys
sys.path.insert(0, ${JSON.stringify(new URL('../../backend', import.meta.url).pathname)})
from app.routers.journey import BUILTIN_DENY_APPS, BUILTIN_DENY_WORDS
print(json.dumps({"apps": list(BUILTIN_DENY_APPS), "words": list(BUILTIN_DENY_WORDS)}))
`], { encoding: 'utf8' })) as { apps: string[]; words: string[] }

const same = JSON.stringify(pyDeny.apps) === JSON.stringify(DENY_APPS)
  && JSON.stringify(pyDeny.words) === JSON.stringify(DENY_TITLE_WORDS)
console.log(`${same ? '✓' : '✗'} 内置黑名单：壳和后端同一份`)
if (!same) {
  console.log(`    TS  ${JSON.stringify([DENY_APPS, DENY_TITLE_WORDS])}`)
  console.log(`    PY  ${JSON.stringify([pyDeny.apps, pyDeny.words])}`)
  bad++
}

// ——— 空档阈值和时长写法两边也要一样 ————————————————————————————
//
// 带上那道斜纹空档是前端按 GAP_MIN 画的，日报里「中间有 X 没在记」是后端按
// 同一个数算的；「不到 1 分钟」这种写法两边各写了一遍。漂了的后果很具体：
// **带上画着一道缝，报告里却说没有空档**。
const pyMore = JSON.parse(execFileSync(venv, ['-c', `
import json, sys
sys.path.insert(0, ${JSON.stringify(new URL('../../backend', import.meta.url).pathname)})
from app.journey.stats import GAP_MIN, say_span
print(json.dumps({"gap": GAP_MIN, "spans": [say_span(s) for s in [0, 20, 59, 60, 600, 3600, 4320, 7200]]}))
`], { encoding: 'utf8' })) as { gap: number; spans: string[] }

const tsSpans = [0, 20, 59, 60, 600, 3600, 4320, 7200].map((s) => saySpan(s))
const gapOk = pyMore.gap === JOURNEY_GAP_MIN
const spanOk = JSON.stringify(tsSpans) === JSON.stringify(pyMore.spans)
console.log(`${gapOk ? '✓' : '✗'} 空档阈值：两边都是 ${JOURNEY_GAP_MIN} 分钟${gapOk ? '' : `（后端 ${pyMore.gap}）`}`)
console.log(`${spanOk ? '✓' : '✗'} 时长写成人话：两边一样`)
if (!spanOk) { console.log(`    TS  ${JSON.stringify(tsSpans)}\n    PY  ${JSON.stringify(pyMore.spans)}`) }
if (!gapOk) bad++
if (!spanOk) bad++

process.exit(bad ? 1 : 0)
