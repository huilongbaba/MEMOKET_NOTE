/** 分段合并：壳里那份（TS）和 P0 脚本那份（Python）必须一致。
 *
 * 这条规则是**在真实使用上量出来的**（第 633 轮，51 分钟）：不合并瞬时切换的话
 * 一天切出 169 段，合并之后 75 段。两份实现漂开的话，P0 量出来的东西就不能用来
 * 说明产品里会发生什么——而这个功能的每一个阈值都是那么定下来的。
 *
 *     npx tsx scripts/check-journey-merge.mts
 */
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { DENY_APPS, DENY_TITLE_WORDS, IDLE_SEC, keepBackendFields, mergeBlips, sweepOrphans, trimIdleTail, type Segment } from '../../desktop/src/capture.ts'
import { groupRuns, RUN_GAP_MIN, RUN_SIM, similar } from '../src/util/journeyRuns'
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

// ——— 同一个 segments.json 的两个写的人，各写各的字段 ————————————————
//
// 壳每切一段 `flush()` 一次，后端描述完一段写回去。原来两边都是**整份覆写**，
// 于是谁后写谁赢：第 750 轮实拍到日志里「自动描述了 1 段」刷了 90 次，
// 而那天 71 段一条描述都没有——描述一段要 15–20 秒，这期间壳早把内存里
// 那份没有 `desc` 的盖回去了。用户那边看到的就是「只有计时没有描述」。
//
// 契约：壳只写 start/end/app/title/n，后端只写 desc/skip/session/deleted/frames。
const DISK = [
  // 后端描述完这一段：写了 desc，大图删了（frames 清空），入了库
  { start: 't0', end: 't1', app: 'Code', title: 'a', n: 5, frames: [] as string[],
    desc: '在改 capture.ts 的 flush', session: 'screen-20260917-000' },
  { start: 't2', end: 't3', app: 'Safari', title: 'b', n: 2, frames: [] as string[],
    desc: '', skip: '没有截图' },
]
// 壳内存里那份：没有 desc，大图还在，而且这 20 秒里又采了一段
const FRESH = [
  { start: 't0', end: 't1b', app: 'Code', title: 'a', n: 7, frames: ['/shots/001.png'] },
  { start: 't2', end: 't3', app: 'Safari', title: 'b', n: 2, frames: ['/shots/002.png'] },
  { start: 't4', end: 't5', app: 'Feishu', title: 'c', n: 1, frames: ['/shots/003.png'] },
] as unknown as Segment[]

const kept = keepBackendFields(FRESH, DISK as unknown as Segment[]) as unknown as Record<string, unknown>[]
const shellOk = kept.length === 3
  && kept[0].desc === '在改 capture.ts 的 flush'        // 描述没被壳盖掉
  && JSON.stringify(kept[0].frames) === '[]'           // 后端删过的大图没被复活
  && kept[0].session === 'screen-20260917-000'
  && kept[0].end === 't1b' && kept[0].n === 7          // 壳自己那几个字段照旧生效
  && kept[1].skip === '没有截图'
  && kept[2].app === 'Feishu'                          // 新采的段留着
console.log(`${shellOk ? '✓' : '✗'} 壳落盘：不抹掉后端写的 desc/skip/session/frames`)
if (!shellOk) { bad++; console.log(`    ${JSON.stringify(kept)}`) }

// 反向：后端手里是 20 秒前的旧快照，写回去不能把这期间壳新采的段吞掉
const pyMerge = JSON.parse(execFileSync(venv, ['-c', `
import json, sys
sys.path.insert(0, ${JSON.stringify(new URL('../../backend', import.meta.url).pathname)})
from app.routers.journey import _merge_back
disk = json.loads(sys.stdin.read())
ours = [{"start": "t0", "end": "t1", "app": "Code", "title": "a", "n": 5,
         "frames": [], "desc": "\u5728\u6539 capture.ts", "session": "s0"}]
print(json.dumps(_merge_back(disk, ours)))
`], { input: JSON.stringify(FRESH), encoding: 'utf8' })) as Record<string, unknown>[]

const backOk = pyMerge.length === 3                     // 壳新采的两段没被吞
  && pyMerge[0].desc === '在改 capture.ts'
  && pyMerge[0].end === 't1b' && pyMerge[0].n === 7      // 壳那几个字段以盘上为准
  && pyMerge[2].app === 'Feishu'
console.log(`${backOk ? '✓' : '✗'} 后端写回：不吞掉这期间壳新采的段`)
if (!backOk) { bad++; console.log(`    ${JSON.stringify(pyMerge)}`) }

// ——— 被并掉那一段的截图要有人清 ————————————————————————————————
//
// `mergeBlips` 把短段并进邻居，被并掉那段的 `shots/NNN.png` 就此不在
// `segments.json` 里——后端的过期清理只遍历段，永远扫不到它。
// 第 750 轮在真实数据上量到：71 段配 63 张无主大图。产品自己写着
// 「描述做完就删大图」，对这些图从来没兑现过。
{
  const dir = mkdtempSync(path.join(tmpdir(), 'journey-'))
  mkdirSync(path.join(dir, 'shots')); mkdirSync(path.join(dir, 'thumbs'))
  for (const n of ['001', '002', '003']) {
    writeFileSync(path.join(dir, 'shots', `${n}.png`), 'x')
    writeFileSync(path.join(dir, 'thumbs', `${n}.jpg`), 'x')
  }
  const kept = [{ start: 'a', end: 'b', app: '', title: '', n: 1,
                  frames: [path.join(dir, 'shots', '001.png')],
                  thumb: path.join(dir, 'thumbs', '001.jpg') },
                // 描述做完的段：frames 空了，但缩略图要留着（凭据）
                { start: 'c', end: 'd', app: '', title: '', n: 1,
                  frames: [], thumb: path.join(dir, 'thumbs', '003.jpg') }] as Segment[]
  const later = Date.now() + 3 * 60_000          // 越过两分钟的宽限
  const gone = sweepOrphans(dir, kept, later)
  const left = (d: string) => readdirSync(path.join(dir, d)).sort().join(',')
  const sweepOk = gone === 3 && left('shots') === '001.png' && left('thumbs') === '001.jpg,003.jpg'
  console.log(`${sweepOk ? '✓' : '✗'} 清无主截图：只删没人引用的，留着缩略图当凭据`)
  if (!sweepOk) { bad++; console.log(`    清了 ${gone}；shots=${left('shots')} thumbs=${left('thumbs')}`) }

  // 刚写下去那张还没进 segs，别自己删自己
  writeFileSync(path.join(dir, 'shots', '009.png'), 'x')
  const graceOk = sweepOrphans(dir, kept) === 0 && readdirSync(path.join(dir, 'shots')).includes('009.png')
  console.log(`${graceOk ? '✓' : '✗'} 两分钟宽限：刚拍下来还没入表的不动`)
  if (!graceOk) bad++
  rmSync(dir, { recursive: true, force: true })
}

// ——— 「连着说同一件事」的分块：前端和后端必须是同一份 ————————————————
//
// 前端拿它排时间轴（八行近似重复 → 一块），后端拿它喂日报
// （同一件事喂八遍，模型会当成八件事来权衡）。两边漂了的后果是
// **页面上并成一块的事，日报里却按八件事算权重**。
const RUN_CASES: { why: string; input: { start: string; end: string; app: string; desc: string }[] }[] = (() => {
  const t = (m: number) => new Date(Date.parse('2026-09-17T07:00:00Z') + m * 60_000).toISOString()
  const g = (m0: number, m1: number, app: string, desc: string) =>
    ({ start: t(m0), end: t(m1), app, desc })
  const A = '查看 PRD.md#70-81 的日本 Android 崩溃分析'
  const B = '阅读 PRD.md#70-81 的日本 Android 崩溃分析结论'
  const C = '改需求文档中 [项目名称] 的背景与问题模板'
  return [
    { why: '同一件事并成一块', input: [g(0, 5, 'Code', A), g(5, 11, 'Code', B), g(11, 20, 'Code', A)] },
    { why: '换了件事断开', input: [g(0, 5, 'Code', A), g(5, 9, 'Code', C)] },
    { why: '换了应用断开', input: [g(0, 5, 'Code', A), g(5, 9, 'Safari', A)] },
    { why: '隔太久断开', input: [g(0, 5, 'Code', A), g(120, 125, 'Code', A)] },
    { why: '两条都没描述就并', input: [g(0, 5, 'Code', ''), g(5, 9, 'Code', ''), g(9, 14, 'Code', '')] },
    { why: '一条有一条没有不并', input: [g(0, 5, 'Code', A), g(5, 9, 'Code', '')] },
    { why: '块上取最长那一句', input: [g(0, 5, 'Code', A), g(5, 9, 'Code', A + '，Crashlytics 匹配到 4 条')] },
    // a 像 b、b 像 c，而 a 跟 c 已经是两件事。按「跟上一条比」会把三条并成一块。
    { why: '跟块首比不跟上一条比（会飘）', input: [
      g(0, 5, 'Code', A),
      g(5, 9, 'Code', A + '，打开 Crashlytics 按机型筛选导出 CSV'),
      g(9, 14, 'Code', '打开 Crashlytics 按机型筛选导出 CSV 并写进周报')] },
    { why: '空的', input: [] },
  ]
})()

const pyRuns = JSON.parse(execFileSync(venv, ['-c', `
import json, sys
sys.path.insert(0, ${JSON.stringify(new URL('../../backend', import.meta.url).pathname)})
from app.journey.runs import GAP_MIN, SIM, group_runs, similar
out = {"gap": GAP_MIN, "sim": SIM, "runs": [], "scores": []}
cases = json.load(sys.stdin)
for c in cases:
    out["runs"].append([[r["start"], r["end"], r["app"], r["desc"], len(r["segs"])]
                        for r in group_runs(c)])
for a, b in [("\u67e5\u770b PRD.md", "\u9605\u8bfb PRD.md"), ("abc def", "abc xyz"), ("", "x")]:
    out["scores"].append(round(similar(a, b), 6))
print(json.dumps(out))
`], { input: JSON.stringify(RUN_CASES.map((c) => c.input)), encoding: 'utf8' })) as
  { gap: number; sim: number; runs: unknown[][]; scores: number[] }

RUN_CASES.forEach((c, i) => {
  const ts = JSON.stringify(groupRuns(c.input).map((r) => [r.start, r.end, r.app, r.desc, r.segs.length]))
  const py = JSON.stringify(pyRuns.runs[i])
  const ok = ts === py
  console.log(`${ok ? '✓' : '✗'} 分块：${c.why}`)
  if (!ok) { bad++; console.log(`    TS  ${ts}\n    PY  ${py}`) }
})

const tsScores = [['查看 PRD.md', '阅读 PRD.md'], ['abc def', 'abc xyz'], ['', 'x']]
  .map(([a, b]) => Number(similar(a, b).toFixed(6)))
const simOk = JSON.stringify(tsScores) === JSON.stringify(pyRuns.scores)
const thrOk = pyRuns.gap === RUN_GAP_MIN && Math.abs(pyRuns.sim - RUN_SIM) < 1e-9
console.log(`${simOk ? '✓' : '✗'} 相似度算法两边同一个数`)
console.log(`${thrOk ? '✓' : '✗'} 门槛两边一样（${RUN_SIM} / ${RUN_GAP_MIN} 分钟）`)
if (!simOk) { bad++; console.log(`    TS  ${JSON.stringify(tsScores)}\n    PY  ${JSON.stringify(pyRuns.scores)}`) }
if (!thrOk) bad++

// ——— 人不在的时候那一段不能一路延下去 ————————————————————————————
//
// 读日报读出来的（第 753 轮）：人睡觉去了，屏幕亮着、前台窗口没变，那一段
// 一路延到早上，日报里写着「00:00–10:44 **连续没被打断 10 小时 45 分钟**」。
// 这一页的全部前提是可信，而这句话是假的。
{
  const now = Date.parse('2026-09-17T10:00:00Z')
  const seg = (s: string, e: string): Segment =>
    ({ start: s, end: e, app: 'Code', title: '', n: 1, frames: [] })

  const a = [seg('2026-09-17T00:00:00.000Z', '2026-09-17T09:59:45.000Z')]
  const trimmed = trimIdleTail(a, now, 8 * 3600)      // 八小时没动过
  const tailOk = trimmed && a[0].end === '2026-09-17T02:00:00.000Z'
  console.log(`${tailOk ? '✓' : '✗'} 人不在：段尾收回到最后一次动手那一刻`)
  if (!tailOk) { bad++; console.log(`    ${a[0].end}`) }

  // 只往回收、不往前推：时钟跳变 / 重复调用都不能把一段拉长
  const b = [seg('2026-09-17T09:00:00.000Z', '2026-09-17T09:30:00.000Z')]
  const noGrow = !trimIdleTail(b, now, 60) && b[0].end === '2026-09-17T09:30:00.000Z'
  console.log(`${noGrow ? '✓' : '✗'} 人不在：只往回收，不把段拉长`)
  if (!noGrow) { bad++; console.log(`    ${b[0].end}`) }

  // 收过头就停在 start：宁可留一个零长段，也不要 end 早于 start 的坏数据
  const c = [seg('2026-09-17T09:50:00.000Z', '2026-09-17T09:59:00.000Z')]
  trimIdleTail(c, now, 3600)
  const floorOk = c[0].end === c[0].start
  console.log(`${floorOk ? '✓' : '✗'} 人不在：收过头也不会让 end 早于 start`)
  if (!floorOk) { bad++; console.log(`    ${c[0].start} → ${c[0].end}`) }

  const emptyOk = !trimIdleTail([], now, 3600) && IDLE_SEC === 300
  console.log(`${emptyOk ? '✓' : '✗'} 人不在：空表不炸，门槛 5 分钟`)
  if (!emptyOk) bad++
}

process.exit(bad ? 1 : 0)
