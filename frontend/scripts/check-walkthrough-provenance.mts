/** **入库的走查日志，是不是入库的那份步骤脚本跑出来的**（P97 A）。
 *
 *     ./node_modules/.bin/tsx scripts/check-walkthrough-provenance.mts
 *     ./node_modules/.bin/tsx scripts/check-walkthrough-provenance.mts --selftest
 *
 * ── 为什么有它：P95 那一行「解释不了」，P97 查实了 ────────────────────────
 * P95 的跨批 diff 里有一行判了「解释不了」，原话：
 *
 *     `17-new-panes93.txt` 少一行 `=== ③ 没给 note id，这一档跳过 ===`——
 *     P93 自己 scratch 里的原始日志也没有，而 HEAD 上那个 `else` 分支在。
 *     最像的解释是「它跑的那份跟入库的那份差着一行」，**证不实**。
 *
 * P97 证实了，证据三条，都不是推的：
 *  ① P93 那趟的 `go-new.log` 里，`step.sh` **自己**打着
 *     `EXIT=0 → …/17-new-panes93.txt (17 行)` —— **跑完那一刻就是 17 行**，
 *     不是事后被截断（`step.sh` 是 `> "$log"` 直写文件，中间一节管道都没有）；
 *     而 `EXIT=0` 说明那个 `export default` 是**正常走完**的：
 *     清单里那一行没给 note id，`else` 在的话这一行非印不可。
 *  ② P93 那份 worktree 还在。里头 `panes93.mjs` 的 mtime = **19:10:57**，
 *     而那份日志落盘在 **19:10:21** —— **跑完之后 36 秒它被写过一次**。
 *  ③ 同目录另外 32 份步骤脚本 + `go.sh` / `step.sh` / `cdp.mjs` 的 mtime
 *     **全是 18:47:28**（签出那一刻），只有它一个是 19:10:57；
 *     而那一批的 commit 在 **19:49:54**。
 *     ⇒ 入库的那一份，跟跑出那份日志的那一份，**不是同一份**。
 *
 * 这不是 P93 一个人的手滑，是**走查日志这件事本身的洞**：跨批逐行 diff
 * （`check-walkthrough-diff.mts`）读的就是这些日志，而「这份日志是哪一份代码跑出来的」
 * 原来**一个字都没记**。下一批照样会在「跑完 → 顺手改一句 → commit」之间踩进去，
 * 而症状是**下下批**的 diff 上一行查不清的噪声。
 *
 * ── 它怎么判 ──────────────────────────────────────────────────────────────
 * `cdp.mjs` 每跑一个步骤脚本，**第一行**打它这一刻真读进来的那份文件的字节 sha256：
 *
 *     步骤脚本: panes93.mjs sha256=<64 位十六进制>
 *
 * 这条闸对着 `docs/walkthrough-logs/<批次>/*.txt` 逐份核：
 *  · 第一行**必须**是这个形状（没有 ⇒ 红）
 *  · 点名那份脚本**必须**在 `frontend/scripts/walkthrough/steps/` 里（不在 ⇒ 红）
 *  · 它今天的字节 sha256 **必须**跟日志里记的那一个**逐字相同**（对不上 ⇒ 红）
 *
 * 第三条就是 P93 那一格：跑完改了一句再 commit，这条闸当场红，**点名到那一份**。
 *
 * ── 豁免名单：**逐字钉死，不是「老的都算」** ──────────────────────────────
 * p85…p95 六批一份都没有这一行（那时候还没有这条规矩）。名单写死在 `LEGACY` 里，
 * **数也钉死**：加一批进去得有人动这份代码、在 diff 上留个名。
 * 写成「小于 p97 的都豁免」就等于给以后的人留了一条静默绕过的路——
 * 那正是「**一条天天误报的闸迟早被人改成不红**」的镜像：**一条太好绕的闸等于没有**。
 * 名单上写着、仓库里却没有那个目录 ⇒ 也红（**名单陈旧本身是个洞**）。
 *
 * ── 它答不了什么（写清楚，别读成「日志从此可信」）────────────────────────
 *  · **老那六批**：一份都不管。P93 那一格是**这一批用 mtime 查出来的**，
 *    不是这条闸抓的——它抓的是**下一次**。
 *  · **日志内容对不对**：一条都答不了。脚本原样、日志是手敲的，它照样绿
 *    （那一档归 `normalize-log.mjs --selftest` 和跨批 diff 那条闸）。
 *  · **`lib.mjs` / `lib52.mjs` / `clickexact.mjs` 那几份被 import 进去的**：
 *    没记。sha 只钉**入口那一份**——入口改了必红，被 import 的那几份改了这条闸看不见。
 *    （要连着钉就得把 import 图整棵算进去，那是下一批的活，**照实写在这儿**。）
 *  · **`go.sh` 自己打的那几行**（`=== <清单行> ===` / `EXIT=…`）不经 `cdp.mjs`，
 *    入库的日志里也没有它们。
 */
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

// **写的那一头和认的那一头是同一份文件**（`walkthrough/provenance.mjs`）：
// 两头各写一份格式串的话，改一头忘另一头 = 闸从此全红或全绿，而且看不出来是哪一种。
// 这条闸下面那几行**真去调它**（不是抄一份正则再比对），所以「措辞改了闸没跟上」这条路不存在。
import { HEAD_RE, parseHead, stepProvenance } from './walkthrough/provenance.mjs'

export { HEAD_RE, parseHead }

/** 这一行之前就存在、**一份都没有出处**的那几批。逐字钉死，见上面那一段。 */
export const LEGACY = ['p85', 'p87', 'p89', 'p91', 'p93', 'p95']
/** 豁免名单的长度**也钉死**：往里加一批得动这个数，diff 上藏不住。 */
export const LEGACY_COUNT = 6

export type Head = { step: string; sha: string } | null

export const sha256 = (buf: Buffer | string) => createHash('sha256').update(buf).digest('hex')

export type Bad = { file: string; why: string }

/** 核一批。`steps` = 步骤脚本目录；`logs` = 这一批的日志目录。 */
export function checkBatch(batch: string, logDir: string, stepsDir: string): { checked: number; bad: Bad[] } {
  const bad: Bad[] = []
  const files = readdirSync(logDir).filter((n) => n.endsWith('.txt')).sort()
  for (const f of files) {
    const rel = `docs/walkthrough-logs/${batch}/${f}`
    const head = parseHead(readFileSync(join(logDir, f), 'utf8'))
    if (!head) {
      bad.push({ file: rel, why: '第一行不是出处（`步骤脚本: <名>.mjs sha256=<64 位>`）——'
        + '**没有出处的日志，下一批 diff 到它时查不清是谁跑的**（P95 那一行「解释不了」）' })
      continue
    }
    const p = join(stepsDir, head.step)
    if (!existsSync(p)) {
      bad.push({ file: rel, why: `出处点名 \`${head.step}\`，可 \`frontend/scripts/walkthrough/steps/\` 里没有这一份` })
      continue
    }
    const now = sha256(readFileSync(p))
    if (now !== head.sha) {
      bad.push({ file: rel, why: `跑的那份跟入库的那份**不是同一份** \`${head.step}\`：`
        + `日志记的是 \`${head.sha.slice(0, 12)}…\`，今天仓库里是 \`${now.slice(0, 12)}…\``
        + '——**跑完之后那份脚本被改过**（P93 实拍：跑完 36 秒改了一句，39 分钟后 commit）' })
    }
  }
  return { checked: files.length, bad }
}

// ── --selftest：**先喂它该红 / 该绿的** ───────────────────────────────────
/** ⚠️ **它自己的失败数要回给外头**（P97 砍刀实拍当场抓到的）：
 *  第一版这儿是 `let bad = 0`，**把外层那个同名的遮住了**——砍刀 ④⑤⑥⑦
 *  （正则两头的锚点 / sha 不比 / 出处不钉第一行）**逐条打了 `✗`，闸却 `EXIT=0` 还印「OK」**。
 *  **「闸跑绿不等于闸有用」**的最短一张脸：例 / 反例全红了，闸自己不认。 */
function selftest(): { cases: number; bad: number } {
  let bad = 0
  const fail = (m: string) => { bad++; console.log(`✗ ${m}`) }
  const root = mkdtempSync(join(tmpdir(), 'p97prov-'))
  const steps = join(root, 'steps')
  const logs = join(root, 'p99')
  mkdirSync(steps); mkdirSync(logs)
  const src = "console.log('hi')\n"
  writeFileSync(join(steps, 'demo.mjs'), src)
  // **「该绿的那一条」由写的那一头自己拼出来**（`stepProvenance`），不是这儿抄一句。
  // 这样「跑的时候打的」和「入库之后认的」在这一行上真接上了：
  // 措辞一改，下面那条断言当场红——**「文件里有这个串」≠「这两头对得上」**。
  const good = stepProvenance(join(steps, 'demo.mjs'))
  if (good !== `步骤脚本: demo.mjs sha256=${sha256(src)}`) {
    fail(`**两头对不上**：\`stepProvenance()\` 拼的是 ${JSON.stringify(good)}，`
      + `而这条闸按 \`步骤脚本: <名> sha256=<64 位>\` 认 —— 改了一头没改另一头`)
  }
  if (!parseHead(good)) fail('**两头对不上**：`stepProvenance()` 拼出来的那一句，`parseHead()` 自己认不出来')

  // 例 ①：出处对得上 ⇒ 绿
  writeFileSync(join(logs, '01.txt'), `${good}\n跑完了\n`)
  let r = checkBatch('p99', logs, steps)
  if (r.bad.length) fail(`**例①**（出处对得上）该绿，却红了：${r.bad.map((b) => b.why).join(' / ')}`)
  if (r.checked !== 1) fail(`**例①**：该核 1 份，实得 ${r.checked}`)

  // 反例 ①：**跑完之后改了一个字节** ⇒ 红，而且红的得是「不是同一份」
  writeFileSync(join(steps, 'demo.mjs'), src + "console.log('跑完之后加的一行')\n")
  r = checkBatch('p99', logs, steps)
  if (r.bad.length !== 1 || !r.bad[0].why.includes('不是同一份')) {
    fail(`**反例①**（跑完改了脚本）该红在「不是同一份」，实得 ${JSON.stringify(r.bad)}`)
  }
  writeFileSync(join(steps, 'demo.mjs'), src)

  // 反例 ②：**一个字都没改，只是日志里的 sha 抄错一位** ⇒ 也红
  writeFileSync(join(logs, '01.txt'), `步骤脚本: demo.mjs sha256=${sha256(src).replace(/.$/, (c) => (c === 'a' ? 'b' : 'a'))}\n`)
  r = checkBatch('p99', logs, steps)
  if (r.bad.length !== 1 || !r.bad[0].why.includes('不是同一份')) {
    fail(`**反例②**（sha 差一位）该红，实得 ${JSON.stringify(r.bad)}`)
  }
  writeFileSync(join(logs, '01.txt'), `${good}\n跑完了\n`)

  // 反例 ③：**压根没有出处那一行** ⇒ 红（P85…P95 那六批就长这样）
  writeFileSync(join(logs, '02.txt'), '=== ① 虚拟页 ===\n')
  r = checkBatch('p99', logs, steps)
  if (!r.bad.some((b) => b.file.endsWith('02.txt') && b.why.includes('第一行不是出处'))) {
    fail(`**反例③**（没有出处）该红，实得 ${JSON.stringify(r.bad)}`)
  }

  // 反例 ④：**出处不在第一行**（跑完之后贴上去的）⇒ 照样红
  writeFileSync(join(logs, '02.txt'), `=== ① 虚拟页 ===\n${good}\n`)
  r = checkBatch('p99', logs, steps)
  if (!r.bad.some((b) => b.file.endsWith('02.txt') && b.why.includes('第一行不是出处'))) {
    fail(`**反例④**（出处贴在中间）该红，实得 ${JSON.stringify(r.bad)}`)
  }

  // 反例 ⑤：**点名一份不在仓库里的脚本** ⇒ 红
  writeFileSync(join(logs, '02.txt'), `步骤脚本: nosuch.mjs sha256=${sha256(src)}\n`)
  r = checkBatch('p99', logs, steps)
  if (!r.bad.some((b) => b.why.includes('没有这一份'))) {
    fail(`**反例⑤**（点名不存在的脚本）该红，实得 ${JSON.stringify(r.bad)}`)
  }

  // 例 ②：**空目录是绿的**（「该有几份日志」一个数都没钉——钉了每批都红）
  const empty = join(root, 'p98')
  mkdirSync(empty)
  r = checkBatch('p98', empty, steps)
  if (r.bad.length || r.checked !== 0) fail(`**例②**：空目录该绿 / 核 0 份，实得 ${JSON.stringify(r)}`)

  // 例 ③ / 反例 ⑥：**正则两头都钉死**
  const SHAPE: [string, boolean, string][] = [
    [good, true, '正经一行认得出'],
    [`步骤脚本: demo.mjs sha256=${sha256(src).slice(0, 63)}`, false, '**63 位不算**（少一位就不是 sha256）'],
    ['步骤脚本: demo.mjs sha256=' + 'g'.repeat(64), false, '**不是十六进制不算**'],
    ['步骤脚本: demo.txt sha256=' + '0'.repeat(64), false, '**不是 .mjs 不算**'],
    [` 步骤脚本: demo.mjs sha256=${sha256(src)}`, false, '**前面多一个空格不算**（钉死行首）'],
    [`步骤脚本: demo.mjs sha256=${sha256(src)} 顺手加的`, false, '**行尾多字不算**（钉死行尾）'],
  ]
  for (const [line, want, why] of SHAPE) {
    if (!!parseHead(line) !== want) fail(`正则那一格：${why} —— 实得 ${!!parseHead(line)}，该是 ${want}`)
  }
  return { cases: 3 + 6 + SHAPE.length + 2, bad }   // 例 3 + 反例 6 + 正则 6 + 「两头对得上」2
}

/** **写的那一头还在不在**（`cdp.mjs` 真的会打那一行吗）。
 *
 * 这条闸核的是**入库的日志**，而日志里那一行是上一趟跑出来的。
 * 把 `cdp.mjs` 里那一句删掉，**已经入库的日志一个字不变** ⇒ 这条闸照样全绿，
 * 要等**下一批**跑完才红。**「闸跑绿不等于闸有用」**——所以这儿静态钉一次：
 * `cdp.mjs` 得从 `provenance.mjs` 里 import `stepProvenance`，而且**在代码行里**调它。
 * （**「文件里有这个串」≠「这段代码还在跑」**：所以下面把注释行剔掉再数，
 *  而「它在 `main()` 里、而且在连 CDP 之前」这一层静态判不了——那一层由
 *  **下一批的日志**来判：没有第一行就红。照实写在这儿。） */
function checkWriter(cdp: string): string[] {
  const bad: string[] = []
  const code = cdp.split('\n').map((l) => (/^\s*(\/\/|\*|\/\*)/.test(l) ? '' : l)).join('\n')
  if (!/import \{ stepProvenance \} from '\.\/provenance\.mjs'/.test(code)) {
    bad.push('`cdp.mjs` 不再从 `provenance.mjs` 里 import `stepProvenance` —— '
      + '格式串就会重新变成两份，改一头忘另一头那条路又开了')
  }
  const calls = (code.match(/\bstepProvenance\(/g) ?? []).length
  if (calls !== 1) {
    bad.push(`\`cdp.mjs\` 的代码行里调 \`stepProvenance(\` **${calls} 次**，该是 1 次 —— `
      + '0 次 = 日志从此没有出处（而这条闸对着老日志照样全绿）；2 次 = 第一行不止一句')
  }
  return bad
}

// ── 跑 ────────────────────────────────────────────────────────────────────
const LOGS = resolve(import.meta.dirname, '../../docs/walkthrough-logs')
const STEPS = resolve(import.meta.dirname, 'walkthrough/steps')
let bad = 0
const fail = (m: string) => { bad++; console.log(`✗ ${m}`) }

const self = selftest()
const cases = self.cases
bad += self.bad

for (const b of checkWriter(readFileSync(resolve(import.meta.dirname, 'walkthrough/cdp.mjs'), 'utf8'))) fail(b)

if (LEGACY.length !== LEGACY_COUNT) {
  fail(`豁免名单有 ${LEGACY.length} 批，钉死的是 ${LEGACY_COUNT} —— 这两个数得一起动`)
}
for (const b of LEGACY) {
  if (!existsSync(join(LOGS, b))) {
    fail(`豁免名单上写着 ${b}，可 \`docs/walkthrough-logs/${b}\` 不在 —— **名单陈旧本身是个洞**`)
  }
}

let batches = 0
let checked = 0
if (existsSync(LOGS)) {
  for (const batch of readdirSync(LOGS).sort()) {
    const dir = join(LOGS, batch)
    if (!statSync(dir).isDirectory()) continue
    if (LEGACY.includes(batch)) continue
    batches++
    const got = checkBatch(batch, dir, STEPS)
    checked += got.checked
    for (const b of got.bad) fail(`${b.file}：${b.why}`)
    if (!got.bad.length) console.log(`  ${batch}：${got.checked} 份日志，出处逐份对得上仓库里那份脚本`)
  }
}

console.log(`\n走查日志的出处：核了 ${batches} 批 / ${checked} 份（豁免 ${LEGACY.length} 批：${LEGACY.join(' ')}）；`
  + `例 / 反例 ${cases} 条；对不上 ${bad} 个`)
if (bad) { console.log(`\n${bad} 处失败`); process.exit(1) }
console.log('OK: 入库的每一份走查日志，都是入库的那一份步骤脚本跑出来的')
console.log('⚠️ 老那六批一份都不管；被 import 的 `lib*.mjs` 也没钉 —— 见本文件顶上「它答不了什么」')
