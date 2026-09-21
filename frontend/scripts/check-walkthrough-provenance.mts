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
 * ── P99 A：**第二行**，被 import 的那几份 + `cdp.mjs` 自己 ────────────────
 * P97 那一版的射程只到入口，自己写在这儿：`lib*.mjs` / `clickexact.mjs` 改了看不见，
 * `cdp.mjs` 自己改了也看不见。这一批补上，补法是**第二行**：
 *
 *     依赖: cdp.mjs=<64 位> provenance.mjs=<64 位> steps/lib.mjs=<64 位> …
 *
 * 路径相对 `frontend/scripts/walkthrough/`，按名排序。这条闸核两件事：
 *  · **单子对不对**：拿今天仓库里那份入口 + `cdp.mjs`，**顺着相对 import 重算一遍闭包**，
 *    跟日志上那张单子**逐条比名字**——少了一份（那一趟 import 过、后来被摘了）或者
 *    多了一份，都红。
 *  · **字节对不对**：单子上每一份今天的 sha256 跟日志里记的**逐字相同**。
 *
 * ⚠️ **判据宁可窄**：单子是**顺着 import 走出来的**，不是「把 `walkthrough/` 目录哈希一遍」。
 * 目录里躺着 30 多份别的步骤脚本，整目录哈希 = 隔壁那一步改一行这一批全红 =
 * **一条天天误报的闸**，而天天误报的闸迟早被人改成不红。
 *
 * ⚠️ **代价照实写**（P97 当初就是为这个不做）：跑完走查再动 `cdp.mjs` / `lib*.mjs`，
 * 入库的日志**当场红**。这跟入口那一份本来就是同一条规矩，只是覆盖面从 1 份变成整条链。
 * 顺序因此是「先把量具定死 → 跑走查 → 跑完不动量具」。**这正是这条闸要的那个压力**。
 *
 * ── 它答不了什么（写清楚，别读成「日志从此可信」）────────────────────────
 *  · **老那六批**（`LEGACY`）：一份都不管。P93 那一格是 P97 用 mtime 查出来的，
 *    不是这条闸抓的——它抓的是**下一次**。
 *  · **`p97` 那一批**：只有第一行，**第二行豁免**（`LEGACY_NO_DEPS`，**逐字钉死一批**）。
 *    那一批的 `lib*.mjs` / `cdp.mjs` 改没改，**永远查不回来**——**不硬追认**。
 *  · **日志内容对不对**：一条都答不了。脚本原样、日志是手敲的，它照样绿
 *    （那一档归 `normalize-log.mjs --selftest` 和跨批 diff 那条闸）。
 *  · **动态拼出来的 import**（`import(变量)`）：闭包是**静态**走出来的，够不到。
 *    工具箱里现在一个都没有（`node:fs` 那种不算），有了得有人改 `provenance.mjs`。
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
import { DEPS_RE, HEAD_RE, depsProvenance, importClosure, parseDeps, parseHead, stepProvenance } from './walkthrough/provenance.mjs'

export { DEPS_RE, HEAD_RE, parseDeps, parseHead }

/** 这一行之前就存在、**一份都没有出处**的那几批。逐字钉死，见上面那一段。 */
export const LEGACY = ['p85', 'p87', 'p89', 'p91', 'p93', 'p95']
/** 豁免名单的长度**也钉死**：往里加一批得动这个数，diff 上藏不住。 */
export const LEGACY_COUNT = 6

/** 有第一行、**没有第二行**的那一批（P99 A 立第二行之前跑的）。**一样逐字钉死**。 */
export const LEGACY_NO_DEPS = ['p97']
/** 长度也钉死。**别把这两份名单合成一份**：它们答的不是同一个问题
 *  （`LEGACY` = 连入口都没记；这一份 = 入口记了、被 import 的那几份没记）。 */
export const LEGACY_NO_DEPS_COUNT = 1

export type Head = { step: string; sha: string } | null

export const sha256 = (buf: Buffer | string) => createHash('sha256').update(buf).digest('hex')

export type Bad = { file: string; why: string }

/** 核一批。`steps` = 步骤脚本目录；`logs` = 这一批的日志目录；
 *  `kit` = 工具箱目录（`frontend/scripts/walkthrough/`，第二行那些相对路径的根）。
 *  `deps=false` ⇒ 这一批在第二行立起来之前跑的，**只核第一行**（`LEGACY_NO_DEPS`）。 */
export function checkBatch(
  batch: string, logDir: string, stepsDir: string,
  { kit = resolve(stepsDir, '..'), deps = true }: { kit?: string; deps?: boolean } = {},
): { checked: number; bad: Bad[]; depFiles: number } {
  const bad: Bad[] = []
  let depFiles = 0
  const files = readdirSync(logDir).filter((n) => n.endsWith('.txt')).sort()
  for (const f of files) {
    const rel = `docs/walkthrough-logs/${batch}/${f}`
    const text = readFileSync(join(logDir, f), 'utf8')
    const head = parseHead(text)
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
      continue
    }
    if (!deps) continue

    // ── 第二行（P99 A）：被 import 的那几份 + `cdp.mjs` 自己 ──────────────
    const got = parseDeps(text)
    if (!got) {
      bad.push({ file: rel, why: '第二行不是依赖出处（`依赖: <相对路径>.mjs=<64 位> …`）——'
        + '**入口那一份对得上，不代表它 import 进去的 `lib*.mjs` / 驱动 `cdp.mjs` 也对得上**（P97 留的第 ① 条）' })
      continue
    }
    // **单子由写的那一头自己重算**（`importClosure`）：这儿抄一份「我记得是 lib + clickexact」
    // 会跟驱动飘开，而飘开的症状是一条天天误报（或天天漏报）的闸。
    // 上面第一行已经逐字节对过了 ⇒ **今天这份入口就是那一趟跑的那一份** ⇒ 重算出来的单子可信。
    const want = importClosure([p, join(kit, 'cdp.mjs')], kit).filter((r) => resolve(kit, r) !== resolve(p))
    const missing = want.filter((r) => !(r in got))
    const extra = Object.keys(got).filter((r) => !want.includes(r))
    if (missing.length || extra.length) {
      bad.push({ file: rel, why: `依赖单子跟今天重算的 import 闭包对不上：`
        + `${missing.length ? `日志里少了 \`${missing.join('` `')}\`` : ''}`
        + `${missing.length && extra.length ? '；' : ''}`
        + `${extra.length ? `日志里多出 \`${extra.join('` `')}\`` : ''}`
        + '——**那一趟读进去的那几份跟今天够得到的那几份不是同一套**' })
      continue
    }
    for (const r of want) {
      depFiles++
      const nowDep = sha256(readFileSync(resolve(kit, r)))
      // `got[r] ?? '（日志里没有这一份）'`：上面那条名字对不上就 `continue` 了，正常走不到这儿。
      // **写死 `got[r]` 会在那条判据被人绕过时当场抛 `undefined.slice`**（P99 砍刀 ⑧ 实拍）——
      // 抛出来的堆栈也算「红」，可它**不点名是哪一份**，读起来跟闸自己坏了一样。
      if (nowDep !== (got[r] ?? '')) {
        const rec = got[r] ?? '（日志里根本没有这一份）'
        bad.push({ file: rel, why: `被 import 的那一份**不是同一份** \`${r}\`：`
          + `日志记的是 \`${rec.slice(0, 12)}…\`，今天仓库里是 \`${nowDep.slice(0, 12)}…\``
          + '——**入口一个字节没动，它 import 的那一份被改过**（P97 够不着的正是这一格）' })
      }
    }
  }
  return { checked: files.length, bad, depFiles }
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
  let r = checkBatch('p99', logs, steps, { deps: false })
  if (r.bad.length) fail(`**例①**（出处对得上）该绿，却红了：${r.bad.map((b) => b.why).join(' / ')}`)
  if (r.checked !== 1) fail(`**例①**：该核 1 份，实得 ${r.checked}`)

  // 反例 ①：**跑完之后改了一个字节** ⇒ 红，而且红的得是「不是同一份」
  writeFileSync(join(steps, 'demo.mjs'), src + "console.log('跑完之后加的一行')\n")
  r = checkBatch('p99', logs, steps, { deps: false })
  if (r.bad.length !== 1 || !r.bad[0].why.includes('不是同一份')) {
    fail(`**反例①**（跑完改了脚本）该红在「不是同一份」，实得 ${JSON.stringify(r.bad)}`)
  }
  writeFileSync(join(steps, 'demo.mjs'), src)

  // 反例 ②：**一个字都没改，只是日志里的 sha 抄错一位** ⇒ 也红
  writeFileSync(join(logs, '01.txt'), `步骤脚本: demo.mjs sha256=${sha256(src).replace(/.$/, (c) => (c === 'a' ? 'b' : 'a'))}\n`)
  r = checkBatch('p99', logs, steps, { deps: false })
  if (r.bad.length !== 1 || !r.bad[0].why.includes('不是同一份')) {
    fail(`**反例②**（sha 差一位）该红，实得 ${JSON.stringify(r.bad)}`)
  }
  writeFileSync(join(logs, '01.txt'), `${good}\n跑完了\n`)

  // 反例 ③：**压根没有出处那一行** ⇒ 红（P85…P95 那六批就长这样）
  writeFileSync(join(logs, '02.txt'), '=== ① 虚拟页 ===\n')
  r = checkBatch('p99', logs, steps, { deps: false })
  if (!r.bad.some((b) => b.file.endsWith('02.txt') && b.why.includes('第一行不是出处'))) {
    fail(`**反例③**（没有出处）该红，实得 ${JSON.stringify(r.bad)}`)
  }

  // 反例 ④：**出处不在第一行**（跑完之后贴上去的）⇒ 照样红
  writeFileSync(join(logs, '02.txt'), `=== ① 虚拟页 ===\n${good}\n`)
  r = checkBatch('p99', logs, steps, { deps: false })
  if (!r.bad.some((b) => b.file.endsWith('02.txt') && b.why.includes('第一行不是出处'))) {
    fail(`**反例④**（出处贴在中间）该红，实得 ${JSON.stringify(r.bad)}`)
  }

  // 反例 ⑤：**点名一份不在仓库里的脚本** ⇒ 红
  writeFileSync(join(logs, '02.txt'), `步骤脚本: nosuch.mjs sha256=${sha256(src)}\n`)
  r = checkBatch('p99', logs, steps, { deps: false })
  if (!r.bad.some((b) => b.why.includes('没有这一份'))) {
    fail(`**反例⑤**（点名不存在的脚本）该红，实得 ${JSON.stringify(r.bad)}`)
  }

  // 例 ②：**空目录是绿的**（「该有几份日志」一个数都没钉——钉了每批都红）
  const empty = join(root, 'p98')
  mkdirSync(empty)
  r = checkBatch('p98', empty, steps, { deps: false })
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

  // ── P99 A：第二行（被 import 的那几份 + `cdp.mjs` 自己）─────────────────
  //
  // 另起一份**长得像真工具箱的** kit：`cdp.mjs` 在根上、步骤脚本在 `steps/` 里、
  // 两边各 import 一份共用量具。上面那几条老例子走的是 `deps: false`
  // ——它们答的是第一行那个问题，**两份名单答的不是同一个问题**（见 `LEGACY_NO_DEPS`）。
  const kit = join(root, 'kit')
  const kitSteps = join(kit, 'steps')
  const kitLogs = join(root, 'p99deps')
  mkdirSync(kit); mkdirSync(kitSteps); mkdirSync(kitLogs)
  const W = (p: string, s: string) => writeFileSync(p, s)
  W(join(kit, 'helper.mjs'), "export const h = 1\n")
  W(join(kit, 'cdp.mjs'), "import { h } from './helper.mjs'\nconsole.log(h)\n")
  W(join(kitSteps, 'shared.mjs'), "export const s = 2\n")
  // ⚠️ 这一份的**注释里也写着一句 import**：`relImports()` 要是不剔注释就会多算一份
  //    （**「文件里有这个串」≠「这段代码还在跑」**）。
  W(join(kitSteps, 'demo.mjs'), "// import { nope } from './notreal.mjs'\nimport { s } from './shared.mjs'\nexport default () => s\n")
  const entry = join(kitSteps, 'demo.mjs')
  const head2 = stepProvenance(entry)
  // **「该绿的那一条」还是由写的那一头自己拼**（`depsProvenance`），不是这儿抄一句。
  const deps2 = depsProvenance(entry, join(kit, 'cdp.mjs'), kit)
  const okLog = `${head2}\n${deps2}\n跑完了\n`
  const closure = importClosure([entry, join(kit, 'cdp.mjs')], kit)
  if (JSON.stringify(closure) !== JSON.stringify(['cdp.mjs', 'helper.mjs', 'steps/demo.mjs', 'steps/shared.mjs'])) {
    fail(`**闭包算错了**：该是 cdp / helper / steps/demo / steps/shared 四份，实得 ${JSON.stringify(closure)}`
      + '（注释里那一句 `notreal.mjs` 要是被算进去了，就是没剔注释）')
  }
  if (!parseDeps(`x\n${deps2}`)) fail('**两头对不上**：`depsProvenance()` 拼出来的那一句，`parseDeps()` 自己认不出来')

  // 例 ④：两行都对得上 ⇒ 绿，而且**核到了 3 份依赖**（入口自己不在里头）
  W(join(kitLogs, '01.txt'), okLog)
  let d = checkBatch('p99deps', kitLogs, kitSteps, { kit })
  if (d.bad.length) fail(`**例④**（两行都对得上）该绿，却红了：${d.bad.map((b) => b.why).join(' / ')}`)
  if (d.depFiles !== 3) fail(`**例④**：该核 3 份依赖（cdp / helper / steps/shared），实得 ${d.depFiles}`)

  // 反例 ⑦：**入口一个字节没动，被 import 的 `shared.mjs` 被改过** ⇒ 红且**点名到它**
  //   这正是 P97 够不着、P99 A 补的那一格。
  W(join(kitSteps, 'shared.mjs'), "export const s = 2\nexport const 跑完之后加的 = 3\n")
  d = checkBatch('p99deps', kitLogs, kitSteps, { kit })
  if (d.bad.length !== 1 || !d.bad[0].why.includes('steps/shared.mjs') || !d.bad[0].why.includes('不是同一份')) {
    fail(`**反例⑦**（被 import 的那份改了）该红且点名 \`steps/shared.mjs\`，实得 ${JSON.stringify(d.bad)}`)
  }
  W(join(kitSteps, 'shared.mjs'), "export const s = 2\n")

  // 反例 ⑧：**驱动 `cdp.mjs` 自己被改过** ⇒ 红且点名到它（P97 明写着没钉的另一格）
  W(join(kit, 'cdp.mjs'), "import { h } from './helper.mjs'\nconsole.log(h)\nconsole.log('跑完之后加的')\n")
  d = checkBatch('p99deps', kitLogs, kitSteps, { kit })
  if (d.bad.length !== 1 || !d.bad[0].why.includes('cdp.mjs') || !d.bad[0].why.includes('不是同一份')) {
    fail(`**反例⑧**（驱动改了）该红且点名 \`cdp.mjs\`，实得 ${JSON.stringify(d.bad)}`)
  }
  W(join(kit, 'cdp.mjs'), "import { h } from './helper.mjs'\nconsole.log(h)\n")

  // 反例 ⑨：**压根没有第二行**（p97 那一批就长这样）⇒ 红
  W(join(kitLogs, '01.txt'), `${head2}\n跑完了\n`)
  d = checkBatch('p99deps', kitLogs, kitSteps, { kit })
  if (d.bad.length !== 1 || !d.bad[0].why.includes('第二行不是依赖出处')) {
    fail(`**反例⑨**（没有第二行）该红，实得 ${JSON.stringify(d.bad)}`)
  }
  // 例 ⑤：**同一份日志，`deps: false` 那一档是绿的**——`LEGACY_NO_DEPS` 就靠这个岔路
  d = checkBatch('p97', kitLogs, kitSteps, { kit, deps: false })
  if (d.bad.length || d.depFiles !== 0) fail(`**例⑤**：没有第二行的日志走 \`deps:false\` 该绿 / 核 0 份依赖，实得 ${JSON.stringify(d)}`)

  // 反例 ⑩：**第二行贴在第三行**（跑完之后补上去的）⇒ 红
  W(join(kitLogs, '01.txt'), `${head2}\n=== ① ===\n${deps2}\n`)
  d = checkBatch('p99deps', kitLogs, kitSteps, { kit })
  if (!d.bad.some((b) => b.why.includes('第二行不是依赖出处'))) {
    fail(`**反例⑩**（第二行贴在中间）该红，实得 ${JSON.stringify(d.bad)}`)
  }

  // 反例 ⑪：**单子里少一份**（那一趟 import 过、日志上被摘掉一项）⇒ 红且点名少了谁
  W(join(kitLogs, '01.txt'), `${head2}\n${deps2.split(' ').filter((t) => !t.startsWith('helper.mjs=')).join(' ')}\n`)
  d = checkBatch('p99deps', kitLogs, kitSteps, { kit })
  if (!d.bad.some((b) => b.why.includes('少了') && b.why.includes('helper.mjs'))) {
    fail(`**反例⑪**（单子少一份）该红且点名 \`helper.mjs\`，实得 ${JSON.stringify(d.bad)}`)
  }

  // 反例 ⑫：**单子里多一份**（够不到的东西被塞进来了）⇒ 红且点名多了谁
  W(join(kitLogs, '01.txt'), `${head2}\n${deps2} steps/nosuch.mjs=${'0'.repeat(64)}\n`)
  d = checkBatch('p99deps', kitLogs, kitSteps, { kit })
  if (!d.bad.some((b) => b.why.includes('多出') && b.why.includes('steps/nosuch.mjs'))) {
    fail(`**反例⑫**（单子多一份）该红且点名 \`steps/nosuch.mjs\`，实得 ${JSON.stringify(d.bad)}`)
  }
  W(join(kitLogs, '01.txt'), okLog)

  // 例 ⑥ / 反例 ⑬：**第二行那条正则两头也钉死**，外加 `..` 一个都不许有
  const one = `helper.mjs=${sha256('x')}`
  const SHAPE2: [string, boolean, string][] = [
    [deps2, true, '正经一行认得出'],
    [`依赖: ${one} steps/lib.mjs=${sha256('y')}`, true, '**多份用单空格隔开**认得出'],
    [`依赖: helper.mjs=${sha256('x').slice(0, 63)}`, false, '**63 位不算**'],
    ['依赖: helper.mjs=' + 'g'.repeat(64), false, '**不是十六进制不算**'],
    ['依赖: helper.txt=' + '0'.repeat(64), false, '**不是 .mjs 不算**'],
    [` 依赖: ${one}`, false, '**前面多一个空格不算**（钉死行首）'],
    [`依赖: ${one} 顺手加的`, false, '**行尾多字不算**（钉死行尾）'],
    [`依赖: ${one}  ${one}`, false, '**两个空格不算**'],
    [`依赖: ../outside.mjs=${sha256('x')}`, false, '**`..` 一个都不许有**（射程漏到工具箱外面去）'],
    ['依赖: ', false, '**空单子不算**（驱动自己那几份非有不可）'],
  ]
  for (const [line, want, why] of SHAPE2) {
    if (!!parseDeps(`第一行\n${line}`) !== want) {
      fail(`第二行正则那一格：${why} —— 实得 ${!!parseDeps(`第一行\n${line}`)}，该是 ${want}`)
    }
  }

  // 第一行那一档：例 3 + 反例 6 + 正则 6 + 「两头对得上」2  = 17（P97 立的）
  // 第二行那一档：例 2 + 反例 6 + 正则 10 + 「两头对得上 / 闭包算得对」2 = 20（P99 A 加的）
  return { cases: 3 + 6 + SHAPE.length + 2 + (2 + 6 + SHAPE2.length + 2), bad }
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
  if (!/import \{ depsProvenance, stepProvenance \} from '\.\/provenance\.mjs'/.test(code)) {
    bad.push('`cdp.mjs` 不再从 `provenance.mjs` 里 import `depsProvenance, stepProvenance` —— '
      + '格式串就会重新变成两份，改一头忘另一头那条路又开了')
  }
  for (const [fn, why] of [
    ['stepProvenance', '0 次 = 日志从此没有第一行（而这条闸对着老日志照样全绿）；2 次 = 第一行不止一句'],
    ['depsProvenance', '0 次 = 日志从此没有第二行，被 import 的那几份和驱动又变回没人钉（P97 那一格）；2 次 = 第二行不止一句'],
  ] as const) {
    const calls = (code.match(new RegExp(`\\b${fn}\\(`, 'g')) ?? []).length
    if (calls !== 1) bad.push(`\`cdp.mjs\` 的代码行里调 \`${fn}(\` **${calls} 次**，该是 1 次 —— ${why}`)
  }
  return bad
}

// ── 跑 ────────────────────────────────────────────────────────────────────
const LOGS = resolve(import.meta.dirname, '../../docs/walkthrough-logs')
const KIT = resolve(import.meta.dirname, 'walkthrough')
const STEPS = join(KIT, 'steps')
let bad = 0
const fail = (m: string) => { bad++; console.log(`✗ ${m}`) }

const self = selftest()
const cases = self.cases
bad += self.bad

for (const b of checkWriter(readFileSync(resolve(import.meta.dirname, 'walkthrough/cdp.mjs'), 'utf8'))) fail(b)

if (LEGACY.length !== LEGACY_COUNT) {
  fail(`豁免名单有 ${LEGACY.length} 批，钉死的是 ${LEGACY_COUNT} —— 这两个数得一起动`)
}
if (LEGACY_NO_DEPS.length !== LEGACY_NO_DEPS_COUNT) {
  fail(`第二行的豁免名单有 ${LEGACY_NO_DEPS.length} 批，钉死的是 ${LEGACY_NO_DEPS_COUNT} —— 这两个数得一起动`)
}
for (const b of [...LEGACY, ...LEGACY_NO_DEPS]) {
  if (!existsSync(join(LOGS, b))) {
    fail(`豁免名单上写着 ${b}，可 \`docs/walkthrough-logs/${b}\` 不在 —— **名单陈旧本身是个洞**`)
  }
}
// **两份名单不许有交集**：`LEGACY` 已经整批不核了，再写进第二行那份名单等于
// 「同一批被豁免两次」，看上去像多一道保险，实际是**下一个人读不出到底豁免的是哪一档**。
for (const b of LEGACY_NO_DEPS) {
  if (LEGACY.includes(b)) fail(`\`${b}\` 同时写在两份豁免名单上 —— 它们答的不是同一个问题，别叠着写`)
}

let batches = 0
let checked = 0
let depFiles = 0
if (existsSync(LOGS)) {
  for (const batch of readdirSync(LOGS).sort()) {
    const dir = join(LOGS, batch)
    if (!statSync(dir).isDirectory()) continue
    if (LEGACY.includes(batch)) continue
    batches++
    const deps = !LEGACY_NO_DEPS.includes(batch)
    const got = checkBatch(batch, dir, STEPS, { kit: KIT, deps })
    checked += got.checked
    depFiles += got.depFiles
    for (const b of got.bad) fail(`${b.file}：${b.why}`)
    if (!got.bad.length) {
      console.log(`  ${batch}：${got.checked} 份日志，出处逐份对得上仓库里那份脚本`
        + (deps ? `；被 import 的那几份 + 驱动共核 ${got.depFiles} 次` : '；**第二行豁免**（这一批跑在 P99 A 之前）'))
    }
  }
}

console.log(`\n走查日志的出处：核了 ${batches} 批 / ${checked} 份（整批豁免 ${LEGACY.length} 批：${LEGACY.join(' ')}；`
  + `只豁免第二行 ${LEGACY_NO_DEPS.length} 批：${LEGACY_NO_DEPS.join(' ')}）；`
  + `第二行逐份核依赖 ${depFiles} 次；例 / 反例 ${cases} 条；对不上 ${bad} 个`)
if (bad) { console.log(`\n${bad} 处失败`); process.exit(1) }
console.log('OK: 入库的每一份走查日志，都是入库的那一份步骤脚本 + 那几份量具 + 那一份驱动跑出来的')
console.log('⚠️ 老那六批一份都不管、p97 那批只有第一行；动态 import 够不着 —— 见本文件顶上「它答不了什么」')
