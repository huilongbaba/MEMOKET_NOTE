/** **`components/` 底下那条测试路还在不在**（P85 A）。
 *
 *     ./node_modules/.bin/tsx scripts/check-components-gate.mts
 *
 * ── 为什么有它 ────────────────────────────────────────────────────────────
 * P81 ⑤ / P82 ④ 连着两批留着同一句话：「`components/kb/` 今天跑不起来前端测试」。
 * P85 量下来**那句话的形状记错了**：vitest 这个仓没有 `test.include` 覆盖，
 * `src/components/__tests__/` 底下放一个探针**当场就被收走**（96 → 97 文件）。
 * 真正缺的是**东西不是路**——`kb/` 那 11 个文件里只有 2 个被任何测试 import 过，
 * 而被点名了三批的 `KbDashboard.tsx` **一条测试都没有**。
 *
 * P85 在 `src/components/__tests__/p85.test.tsx` 摆了第一条。这份闸看着**两件事**：
 *
 *  ① **那条路不许被悄悄关掉。** 「加一条 `test.include: ['src/editor/**']`」
 *     不会让任何测试变红——它只会让 `components/` 底下的测试**从此不跑**，
 *     而「不跑」和「跑绿了」在终端里长得一模一样（`check-greppable` 那一课的同款）。
 *     所以这条判据**不读 glob、不读配置**，直接问 vitest 自己：
 *     `vitest list --filesOnly` 列出来的**就是它真要跑的那些文件**。
 *  ② **那一行的两个标签不许只剩一个。** `KbDashboard.tsx` 上
 *     `' · 命中词：'` / `' · 找过：'` 是 P81 ③ 落的那一刀（0 条结果时不许说「命中」）。
 *     判据是**双向**的：源码里各在（摘掉注释之后），**而且**各被一个
 *     「真的 `createRoot` 挂了 `KbDashboard`」的测试文件断言到。
 *     只核源码 = 「文件里有这个串」≠「这段代码还在跑」；
 *     只核测试 = 测试可以对着一个已经删掉的串断言（它会自己红，但红得晚）。
 *
 * ── 它答不了什么 ──────────────────────────────────────────────────────────
 *  - **那条测试写得对不对**：一条都答不了。它只管「路开着 / 靶子还在」。
 *  - **`components/` 覆盖得够不够**：`MIN_COMPONENT_TESTS` 是个**下限**，不是覆盖率。
 *    今天 1 个文件 / 70 个源文件，离「够」远得很——这个数只准往上走。
 *  - **别的组件**：判据宁可窄，②只盯 `KbDashboard` 那一行。
 */
import { execFileSync } from 'node:child_process'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

// ── 闸门常数（`backend/scripts/floor_ruler.py` 登记着这三个）───────────────
/** `src/components/` 底下 vitest **真要跑**的测试文件数下限。只准往上。 */
const MIN_COMPONENT_TESTS = 1
/** 那两个标签在 `KbDashboard.tsx` 代码行里各出现几次。钉死 1：出现两次说明那一行被抄了一份。 */
const EXPECT_LABEL_HITS = 1
/** `hits.terms.slice(0, N)` 里的那个 N。`backend/scripts/kb_search_ruler.py` 的 `SHOW` 抄的就是它。 */
const SHOW = 6

const FE = resolve(import.meta.dirname, '..')
const SRC = join(FE, 'src')
const DASH = join(SRC, 'components/kb/KbDashboard.tsx')
const LABELS = [' · 命中词：', ' · 找过：'] as const

let bad = 0
const fail = (msg: string) => { bad++; console.log('✗ ' + msg) }

/** 摘掉块注释和行注释。**判之前先摘整行注释**——这份闸自己的抬头里就写着那两个标签。 */
export const strip = (s: string): string => s
  .replace(/\/\*[\s\S]*?\*\//g, ' ')
  .replace(/^[ \t]*\/\/.*$/gm, ' ')
  .replace(/([^:])\/\/.*$/gm, '$1')

function walk(dir: string, out: string[] = []): string[] {
  for (const n of readdirSync(dir)) {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.tsx?$/.test(n)) out.push(p)
  }
  return out
}

/** 这份测试**真的把 `KbDashboard` 挂起来了**吗：import 到它 + 用 `createRoot` 挂。
 *  只看 import 不够——`import type` 和一句注释里的路径都能骗过它。 */
export const mountsKbDashboard = (src: string): boolean => {
  const s = strip(src)
  return /import[\s\S]{0,120}?['"][^'"]*kb\/KbDashboard['"]/.test(s) && /createRoot\s*\(/.test(s)
}

/** 第 ① 条的判断本身**单拎出来**，为的是让它自己也有例 / 反例。
 *
 * ⚠️ **这一条是突变验第 ⑦ 刀逼出来的**：第一版把这个判断内联在下面那个 `if` 里，
 * 于是把 `listed.length &&` 换成 `false &&`（= 把这条闸整个关掉）之后
 * **跑什么都不红**——闸自己那一半没有任何东西看着。
 * 现在它是个纯函数，刀砍在它身上会当场落进底下那张例 / 反例表里。
 *
 * `listed` 空着不算不足：那说明 `vitest list` 根本没跑起来，上面另有一条 `fail` 管它，
 * 在这儿再红一次只会把「跑不动」说成「测试没了」。 */
export const componentsShortfall = (listed: string[], min: number): boolean =>
  listed.length > 0 && listed.filter((p) => p.startsWith('src/components/')).length < min

// ── ① vitest 自己列出来的清单里，`src/components/` 底下有几个 ───────────────
let listed: string[] = []
try {
  const out = execFileSync(join(FE, 'node_modules/.bin/vitest'), ['list', '--filesOnly'],
                           { cwd: FE, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
  listed = out.split('\n').map((l) => l.trim()).filter(Boolean)
} catch (e) {
  // **缺了就当场红，不许静默跳过**（「没装就算了」的闸是一条永远绿的闸）
  fail(`跑不动 \`vitest list --filesOnly\`（${(e as Error).message.split('\n')[0]}）——`
    + '这条闸靠它拿「vitest 真要跑哪些文件」的地面真相，跑不动就等于没核')
}
const inComponents = listed.filter((p) => p.startsWith('src/components/'))
if (componentsShortfall(listed, MIN_COMPONENT_TESTS)) {
  fail(`vitest 会跑的文件里，\`src/components/\` 底下只有 ${inComponents.length} 个`
    + `（下限 ${MIN_COMPONENT_TESTS}）。`
    + '要么测试被删了，要么有人给 vitest 加了 `test.include` 把这条路关掉了——'
    + '**关掉不会让任何测试变红**，这正是这条判据在看的那件事')
}
// 磁盘上有、vitest 却不跑的：那就是「被悄悄关掉」的实锤
const onDisk = walk(join(SRC, 'components'))
  .filter((p) => /\.(test|spec)\.[cm]?[jt]sx?$/.test(p))
  .map((p) => relative(FE, p))
const missed = onDisk.filter((p) => !listed.includes(p))
if (listed.length && missed.length) {
  fail(`这 ${missed.length} 份测试在磁盘上，vitest 却不跑它们：${missed.join(', ')}`)
}

// ── ② 那一行的两个标签：源码里在，且被一份真挂了 KbDashboard 的测试断言到 ──
const dashCode = strip(readFileSync(DASH, 'utf8'))
for (const label of LABELS) {
  const n = dashCode.split(label).length - 1
  if (n !== EXPECT_LABEL_HITS) {
    fail(`\`KbDashboard.tsx\` 的代码行里 ${JSON.stringify(label)} 出现 ${n} 次（钉死 ${EXPECT_LABEL_HITS}）。`
      + '这两个标签是 P81 ③ 落的那一刀：0 条结果时那几个词是「找过的」不是「命中的」')
  }
}
if (!new RegExp(`terms\\.slice\\(\\s*0\\s*,\\s*${SHOW}\\s*\\)`).test(dashCode)) {
  fail(`\`KbDashboard.tsx\` 里找不到 \`terms.slice(0, ${SHOW})\`——`
    + '摆几串这个数变了。`backend/scripts/kb_search_ruler.py` 的 `SHOW` 抄的就是它，'
    + 'P79 第 ⑤ 刀实拍过「把它 6 → 3，那把尺自己量不到」')
}
const mounters = walk(SRC).filter((f) => /\.(test|spec)\.[cm]?[jt]sx?$/.test(f))
  .filter((f) => mountsKbDashboard(readFileSync(f, 'utf8')))
if (mounters.length === 0) {
  fail('没有任何一份测试真的挂起 `KbDashboard`（import 到它 + `createRoot`）——'
    + '那一行就又回到「只能靠后端源码对拍钉」的状态了（P81 ⑤）')
}
for (const label of LABELS) {
  const who = mounters.filter((f) => strip(readFileSync(f, 'utf8')).includes(label.trim().replace(/^· /, '')))
  if (who.length === 0) {
    fail(`${JSON.stringify(label)} 在产品里有，却没有一份「真挂了 KbDashboard」的测试断言它。`
      + '源码里有这个串 ≠ 这段代码还在跑')
  }
}

// ── ③ 例 / 反例：**先喂它一个该红 / 该绿的**（每批的规矩）──────────────────
const BATTERY: [string, boolean, string][] = [
  ['import KbDashboard from "../kb/KbDashboard"\ncreateRoot(el)', true, '真 import + 真挂'],
  ['const { default: D } = await import("../kb/KbDashboard")\ncreateRoot(el)', true, '动态 import 也算'],
  ['import KbDashboard from "../kb/KbDashboard"', false, '只 import 没挂 → 不算'],
  ['createRoot(el)', false, '只挂没 import 它 → 不算'],
  ['// import KbDashboard from "../kb/KbDashboard"\ncreateRoot(el)', false, '注释掉的 import 不算'],
  ['/* import x from "../kb/KbDashboard" */\ncreateRoot(el)', false, '块注释里的 import 不算'],
  ['import KbDashboard from "../kb/KbDashboardX"\ncreateRoot(el)', false, '同前缀的别的文件不算'],
]
for (const [src, want, why] of BATTERY) {
  const got = mountsKbDashboard(src)
  if (got !== want) fail(`例 / 反例对不上（${why}）：${JSON.stringify(src)} → ${got}，该是 ${want}`)
}
/** 第 ① 条自己的例 / 反例（突变验第 ⑦ 刀逼出来的，见 `componentsShortfall` 的注释）。 */
const SHORTFALL_BATTERY: [string[], number, boolean, string][] = [
  [['src/editor/__tests__/a.test.ts'], 1, true,
   '**路被悄悄关掉的那个形状**：vitest 只列 editor 底下的 → 不足'],
  [['src/components/__tests__/p85.test.tsx', 'src/editor/__tests__/a.test.ts'], 1, false,
   'components 底下有一份 → 够'],
  [['src/components/a.test.ts'], 2, true, '下限抬到 2 而只有 1 份 → 不足'],
  [[], 1, false, '一份都没列出来 = `vitest list` 没跑起来，上面另有一条 fail 管它，这儿不许再红一次'],
]
for (const [listed, min, want, why] of SHORTFALL_BATTERY) {
  const got = componentsShortfall(listed, min)
  if (got !== want) fail(`第 ① 条的例 / 反例对不上（${why}）：${JSON.stringify(listed)} / ${min} → ${got}，该是 ${want}`)
}

const STRIP_BATTERY: [string, string, string][] = [
  ["const a = ' · 找过：'", " · 找过：", '代码行里的串留着'],
  ["// 说明里提到 ' · 找过：'", "", '行注释里的不算'],
  ["/** 抬头里提到 ' · 找过：' */", "", '块注释里的不算'],
]
for (const [src, want, why] of STRIP_BATTERY) {
  const got = strip(src).includes(' · 找过：') ? ' · 找过：' : ''
  if (got !== want) fail(`摘注释的例 / 反例对不上（${why}）：${JSON.stringify(src)} → ${JSON.stringify(got)}`)
}

console.log(`\ncomponents 那条测试路：vitest 会跑 ${listed.length} 份，其中 \`src/components/\` 底下 `
  + `${inComponents.length} 份（下限 ${MIN_COMPONENT_TESTS}）；磁盘上有它却不跑的 ${missed.length} 份；`
  + `那一行两个标签各 ${EXPECT_LABEL_HITS} 次 / \`slice(0, ${SHOW})\` 在；`
  + `真挂了 KbDashboard 的测试 ${mounters.length} 份；`
  + `例 / 反例 ${BATTERY.length + STRIP_BATTERY.length + SHORTFALL_BATTERY.length} 条；`
  + `对不上 ${bad} 个`)
if (bad) { console.log(`\n${bad} 处失败`); process.exit(1) }
console.log('OK: `components/` 底下那条测试路开着，那一行的两个标签两头都对得上')
