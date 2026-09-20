/** 「假壳那条路还接着吗」——**静态**那一半（P74 A）。
 *
 *     npx tsx scripts/check-walkthrough-fakeshell.mts
 *
 * ── 它跟 `run-walkthrough-fakeshell.mjs` 的分工 ──────────────────────────
 * 那一份是**真跑**：起 Electron + 后端 + 假模型，把真的步骤脚本跑一遍。
 * 它要一个真 Chromium、一个 `backend/.venv`、一份 `frontend/dist`，**CI 上一样都没有**，
 * 所以它**不在 `npm test` 里**（缺前置当场红着退，不是静默跳过——见那份文件的注释）。
 *
 * 这一份在 `npm test` 里，管的是**那条路有没有断**。它核得动的：
 * 文件还在不在、`PLAN` 指着的步骤脚本是不是真的、判据条数够不够、
 * 假壳的 preload 有没有暴露产品没有的东西、身份契约有没有跟产品 `main.ts` 飘开、
 * 搬进来的那几份 shell 脚本里有没有**写死的绝对路径**。
 *
 * ── **够不着什么**（照 P72 的写法，写在闸自己身上）─────────────────────
 *  · 跑得绿不绿：一条都答不了。这一份**不起任何进程**。
 *  · 每一步的判据对不对（`must` 的正则会不会命中）：那要真跑。
 *  · 打包壳那一圈（`npm run dist` / 签名 / `extraResources`）：`backend/tests/test_packaging.py` 管。
 *  · **它是「这条路还接着吗」，不是「这条路走得通吗」。** 绿了只说明没人把它拆了。
 */
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const here = path.dirname(fileURLToPath(import.meta.url))
const FE = path.join(here, '..')
const ROOT = path.join(FE, '..')
const WALK = path.join(here, 'walkthrough')
const RUNNER = path.join(here, 'run-walkthrough-fakeshell.mjs')

let bad = 0
const fail = (msg: string) => { bad++; console.log('✗ ' + msg) }

// ── ① 那条路上的每一份东西都还在 ─────────────────────────────────────────
const PARTS: [string, string][] = [
  [RUNNER, '假壳那条闸（真跑的那一半）'],
  [path.join(WALK, 'fakeshell/main.cjs'), '假壳的主进程'],
  [path.join(WALK, 'fakeshell/preload.cjs'), '假壳的 preload'],
  [path.join(WALK, 'cdp.mjs'), 'CDP 驱动'],
  [path.join(WALK, 'haspage.mjs'), '窗口起来了没有的探针'],
  [path.join(WALK, 'go.sh'), '真壳那一趟的跑法'],
  [path.join(WALK, 'launch.sh'), '起真壳'],
  [path.join(WALK, 'step.sh'), '跑一个步骤'],
  [path.join(ROOT, 'backend/scripts/walkthrough_fakellm.py'), '假模型端点'],
  [path.join(ROOT, 'backend/scripts/walkthrough_udd.py'), 'userData 造法'],
]
for (const [p, why] of PARTS) {
  if (!existsSync(p)) fail(`${path.relative(ROOT, p)} 不在了（${why}）—— 假壳那条路断了`)
}
if (bad) { console.error('✗ 路上缺了东西，后面的数一个都不算'); process.exit(1) }

// ── ② `PLAN` 指着的步骤脚本是真的，判据条数够 ────────────────────────────
// **拿 AST 不拿正则**：`PLAN` 里有一堆带中文和转义的正则字面量，正则去扒它自己就是
// 又一把会漏的尺子（`check-walkthrough-selectors.mts` 第 ③ 遍同一条理由）。
const runnerSrc = readFileSync(RUNNER, 'utf8')
// **判「这段代码还在吗」之前先把整行注释摘掉**（P68 第 ⑤ 刀立的规矩）。
// ⚠️ P76 第 ⑪ 刀实拍：把 `await stopShell()` 那一行**注释掉**，
// 下面 ②′ 那条锚在它身上的断言**没红**——串还在文件里，只是在注释里了。
// **「文件里有这个串」≠「这段代码还在跑」**，跟 ③ 那条「匹配上了 ≠ 匹配的是那一处」
// 是同一个形状。结构上的断言一律对着 `runnerCode` 问；
// 要核注释里写没写清楚的（⑦「够不着什么」那一段）才对着 `runnerSrc` 问。
const runnerCode = runnerSrc.split('\n')
  .map((l) => (/^\s*(\/\/|\*|\/\*)/.test(l) ? '' : l)).join('\n')
const sf = ts.createSourceFile(RUNNER, runnerSrc, ts.ScriptTarget.Latest, true)
type Plan = { name: string, step: string, must: number, refute: number,
              hasBefore: boolean, beforeCount: number, afterCount: number, restart: boolean }
const plan: Plan[] = []
const visit = (n: ts.Node) => {
  if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.name.text === 'PLAN'
      && n.initializer && ts.isArrayLiteralExpression(n.initializer)) {
    for (const el of n.initializer.elements) {
      if (!ts.isObjectLiteralExpression(el)) continue
      const get = (k: string) => el.properties.find(
        (p) => ts.isPropertyAssignment(p) && ts.isIdentifier(p.name) && p.name.text === k) as ts.PropertyAssignment | undefined
      const str = (k: string) => { const p = get(k); return p && ts.isStringLiteral(p.initializer) ? p.initializer.text : '' }
      const len = (k: string) => { const p = get(k); return p && ts.isArrayLiteralExpression(p.initializer) ? p.initializer.elements.length : -1 }
      // **P76 加的三样**（`before` / `after` / `restart`）也得扒出来：它们报的问题跟
      // `must` / `refute` 一样算数，**而静态这条闸看不见它们的话，把它们删掉照样绿**。
      const num = (k: string) => {
        const p = get(k)
        if (!p || !ts.isNumericLiteral(p.initializer)) return 0
        return Number(p.initializer.text)
      }
      const afterCount = (() => {
        const p = get('after')
        if (!p || !ts.isObjectLiteralExpression(p.initializer)) return 0
        const c = p.initializer.properties.find(
          (x) => ts.isPropertyAssignment(x) && ts.isIdentifier(x.name) && x.name.text === 'count') as ts.PropertyAssignment | undefined
        return c && ts.isNumericLiteral(c.initializer) ? Number(c.initializer.text) : -1
      })()
      const restart = (() => {
        const p = get('restart')
        return !!p && p.initializer.kind === ts.SyntaxKind.TrueKeyword
      })()
      plan.push({ name: str('name'), step: str('step'), must: len('must'), refute: len('refute'),
        hasBefore: !!get('before'), beforeCount: num('beforeCount'), afterCount, restart })
    }
  }
  ts.forEachChild(n, visit)
}
visit(sf)

// **扫不到东西的闸门会一直是绿的**：`PLAN` 空了 / AST 没扒着，这一整段就白跑了。
// **只准往上调**（同 `check-walkthrough-selectors.mts` 的 `MIN_CLASSES`）：
// P74 是 3 步，P76 把走查第 ④⑤⑥⑩ 加进来之后是 7 步。
const MIN_STEPS = 7
if (plan.length < MIN_STEPS) {
  console.error(`✗ 从 run-walkthrough-fakeshell.mjs 里只扒出 ${plan.length} 步（至少该有 ${MIN_STEPS} 步）`
    + '—— 要么 PLAN 被砍了，要么这段 AST 扒法坏了。别把这个数字改小')
  process.exit(1)
}
const stepFiles = new Set(readdirSync(path.join(WALK, 'steps')).filter((n) => n.endsWith('.mjs')))
let musts = 0, refutes = 0, extra = 0
for (const s of plan) {
  if (!stepFiles.has(s.step)) fail(`PLAN 里的「${s.name}」指着 steps/${s.step}，而那个文件不在`)
  // **判据和反例都得有**。只有 `must` 的闸：步骤脚本整个不跑、只打一句话，也可能全过；
  // 只有 `refute` 的闸：什么都不打印也全过。
  if (s.must < 3) fail(`「${s.name}」只有 ${s.must} 条判据 —— 一步至少 3 条，不然「跑过了」跟「跑了一半」分不开`)
  if (s.refute < 1) fail(`「${s.name}」一条反例都没有 —— 只有 must 的闸，步骤脚本只打一句话也可能全过`)
  musts += Math.max(s.must, 0); refutes += Math.max(s.refute, 0)
  // **声明了 `before` 却没给 `beforeCount`** = 那几条跑了但不进总数：
  // 「核了 N 条」那个数会少报，而一个报不准条数的闸，下一批没法拿它对账。
  // `after` 同理（它的条数写在 `after.count` 上）。
  if (s.hasBefore && s.beforeCount < 1) {
    fail(`「${s.name}」有 before 却没给 beforeCount —— 那几条跑了但不进「核了 N 条」`)
  }
  if (s.afterCount < 0) fail(`「${s.name}」的 after 没给 count —— 同上`)
  extra += Math.max(s.beforeCount, 0) + Math.max(s.afterCount, 0)
}

// ── ②′ **关掉重开那一段的接线洞**（P76 加的第 ⑩ 步）────────────────────────
// `reopen64.mjs` 头上逐字写着「**换了一篇 ≠ 重开过一次**」。那一步要是没真把壳关掉，
// 它那六条判据**照样全过**——突变验第 ⑥ 刀量到的正是这件事（把 `if (s.restart)`
// 短路掉，红的只有「壳从头到尾只起过 1 次」那一条，外加一条页签上的角标差异）。
// 所以这儿三样一起核：**有人声明了 restart / 那个分支真的在收摊重起 / 那条 pid 判据还在**。
if (!plan.some((p) => p.restart)) {
  fail('PLAN 里没有一步声明 `restart: true` —— 走查第 ⑩ 步「关掉重开」没在跑')
}
for (const [re, why] of [
  [/if \(s\.restart\) \{[\s\S]{0,400}?await stopShell\(\)/, '`restart` 那一支里没有 `stopShell()`——壳没关掉'],
  [/if \(s\.restart\) \{[\s\S]{0,400}?ctx\.shellPids\.push\(await startShell\(\)\)/, '`restart` 那一支里没有重起一个壳'],
  [/function shellReallyRestarted/, '「壳真换了一个进程吗」那条判据没了——「点过了 ≠ 翻过了」'],
] as [RegExp, string][]) {
  if (!re.test(runnerCode)) fail(why)
}

// ── ③ **接线洞单独一条断言**（P72 那一课）────────────────────────────────
// 这条闸最容易悄悄失效的方式不是「被删掉」，是「它改成跑自己抄的一份驱动 / 自己写的一份步骤」
// ——那时候它照样绿，绿的却是**没在跑产品那一份**的绿。
// ⚠️ **锚在真调用点上，不是「文件里提过这个名字」**：第一版写的是
// `/path\.join\(WALK, 'cdp\.mjs'\)/`，而那个串在 runner 里出现**两次**
// ——一次在 `preflight()` 的「这些文件得在」清单里，一次才是真的 `spawn`。
// 突变验第 ⑧ 刀把 `spawn` 那一处改成 `cdp-抄了一份.mjs`，**闸没红**：
// 它匹配上的是 preflight 里那一处。**这正是它自己要治的那个接线洞**
// （P72 #3：「手动才跑的闸等于没接进链」的同族——**匹配上了 ≠ 匹配的是那一处**）。
if (!/spawn\(process\.execPath, \[path\.join\(WALK, 'cdp\.mjs'\)/.test(runnerCode)) {
  fail('那条闸不再是拿 `walkthrough/cdp.mjs` **跑**步骤了（preflight 里提一嘴不算）'
    + ' —— 抄一份驱动出来，跑绿了也不算')
}
if (!/path\.join\(STEPS, stepFile\)/.test(runnerCode)) {
  fail('那条闸不再是从 `walkthrough/steps/` 里取步骤脚本了')
}
// 步骤脚本**一个字节都不许为了这条闸改**：PLAN 里点的必须是走查本来就在用的那些。
// 判法是「它点的每一步，README 的十一步对照表或专题探针清单里也点过」。
const readme = readFileSync(path.join(WALK, 'README.md'), 'utf8')
for (const s of plan) {
  if (!readme.includes(`steps/${s.step}`)) {
    fail(`PLAN 点的 steps/${s.step} 在 README 的对照表里找不到 —— `
      + '这条闸跑的得是**走查本来就在跑的那几步**，不是为它自己现写的步骤')
  }
}

// ── ④ 假壳的 preload 不许暴露产品 preload 没有的东西 ─────────────────────
// 多挂一个桩 = 假壳上「有这个功能」而真壳上没有，走查就会在假壳上量出一条
// 真壳没有的结论。**判据宁可窄**：只核「假壳 ⊆ 产品」，不核反向（产品多得多，那是故意的）。
// **别用 `\w` 去认标识符名**（P72 那条 README 路径正则、P74 那条选择器引号正则，
// 这是第三次）：JS 的 `\w` 只有 `[A-Za-z0-9_]`，中文标识符一个都认不出来。
// 突变验第 ⑨ 刀给假壳 preload 加了一件 `产品没有的这一件()`，**闸没红**——
// 不是它放过了，是它**压根没看见**。改成「不是空白 / 括号 / 冒号 / 花括号」的一串。
const names = (src: string, re: RegExp) => {
  const m = src.match(re)
  if (!m) return null
  return new Set([...m[1].matchAll(/^\s{2}(?:([^\s(:{,]+)\s*\(|([^\s(:{,]+)\s*:)/gm)]
    .map((x) => x[1] ?? x[2]))
}
const fakePre = readFileSync(path.join(WALK, 'fakeshell/preload.cjs'), 'utf8')
const realPre = readFileSync(path.join(ROOT, 'desktop/src/preload.ts'), 'utf8')
const fakeNames = names(fakePre, /exposeInMainWorld\('memoketDesktop',\s*\{([\s\S]*?)\n\}\)/)
const realNames = names(realPre, /exposeInMainWorld\('memoketDesktop',\s*\{([\s\S]*?)\n\}\)/)
if (!fakeNames || !fakeNames.size) fail('扒不出假壳 preload 暴露了什么 —— 这一段就白跑了')
else if (!realNames || !realNames.size) fail('扒不出产品 preload 暴露了什么 —— 这一段就白跑了')
else {
  for (const n of fakeNames) {
    if (!realNames.has(n)) fail(`假壳 preload 暴露了 \`${n}\`，而 desktop/src/preload.ts 里没有这一件 —— `
      + '假壳上会量出一条真壳没有的结论')
  }
  console.log(`  preload：假壳 ${[...fakeNames].sort().join(' / ')}（产品 ${realNames.size} 件）`)
}

// ── ⑤ 身份契约不许跟产品 `main.ts` 飘开 ──────────────────────────────────
// 飘开的症状是**静默变差**：窗口身份回落成前端随机生成的 `user-xxxxxx`，
// 482 篇一篇看不见，而 app 一声不吭（P60 #2，`walkthrough_udd.py` 整篇都在说这件事）。
const fakeMain = readFileSync(path.join(WALK, 'fakeshell/main.cjs'), 'utf8')
const realMain = readFileSync(path.join(ROOT, 'desktop/src/main.ts'), 'utf8')
for (const [needle, why] of [
  [`'identity.json'`, '身份文件名'],
  [String.raw`/^[\w.-]{1,64}$/`, '身份那条正则'],
  [`q.set('user', user)`, '挂到 URL 上的那个查询串键'],
] as [string, string][]) {
  const inFake = fakeMain.includes(needle), inReal = realMain.includes(needle)
  if (!inReal) fail(`产品 main.ts 里找不到「${needle}」（${why}）—— 产品改了，假壳这条对照就过期了，先看一眼`)
  else if (!inFake) fail(`假壳 main.cjs 里找不到「${needle}」（${why}）—— 身份会静默回落（P60 #2）`)
}

// ── ⑥ 搬进来的那几份里不许有写死的绝对路径 ───────────────────────────────
// scratch 里那几份原样全是 `/Users/huilong/...worktrees/agent-xxxx/...`。
// **一份进 git 的文件里写死某一次会话的路径，换一台机器就是静默写错地方**
// （`cdp.mjs` 的 `WALKTHROUGH_SHOT_DIR` 是同一条理由）。
const MOVED = [
  path.join(WALK, 'go.sh'), path.join(WALK, 'launch.sh'), path.join(WALK, 'step.sh'),
  path.join(WALK, 'haspage.mjs'), path.join(WALK, 'fakeshell/main.cjs'),
  path.join(WALK, 'fakeshell/preload.cjs'), RUNNER,
  path.join(ROOT, 'backend/scripts/walkthrough_fakellm.py'),
]
const ABS = /(?:^|[^\w/])(\/Users\/[\w.-]+|\/private\/tmp\/|\/tmp\/claude)/
for (const p of MOVED) {
  const lines = readFileSync(p, 'utf8').split('\n')
  lines.forEach((l, i) => {
    // 注释里举例说「原来写死的是这种」是允许的——判之前先摘整行注释（P68 第 ⑤ 刀那一课）
    if (/^\s*(#|\/\/|\*|\/\*)/.test(l)) return
    if (ABS.test(l)) fail(`${path.relative(ROOT, p)}:${i + 1} 写死了一个绝对路径：${l.trim().slice(0, 80)}`)
  })
}

// ── ⑦ 「够不着什么」那张单子还在（P72 的规矩：不许含糊过去）──────────────
for (const needle of ['够不着什么', 'npm run dist', 'CI 跑不了', '怎么证明它会红']) {
  if (!runnerSrc.includes(needle)) {
    fail(`run-walkthrough-fakeshell.mjs 的说明里找不到「${needle}」—— `
      + '一条闸得自己说清楚它够不着什么，不然下一批会拿它当「走查跑过了」')
  }
}
// README 得指着这条路，否则两边会飘（P66 起每批都栽在「搬了但没人知道」上）
if (!readme.includes('run-walkthrough-fakeshell.mjs')) {
  fail('walkthrough/README.md 里没提假壳那条路 —— 搬进来了但 README 还写着「搬进来也跑不了」')
}

console.log(`\n假壳那条路：${PARTS.length} 份东西都在；${plan.length} 步（`
  + plan.map((p) => `${p.name}=${p.must}+${p.refute}`).join(' / ')
  + `）共 ${musts} 条判据 / ${refutes} 条反例 / ${extra} 条闸自己跑的（before + after）`
  + `；写死的绝对路径 0；对不上 ${bad} 个`)
if (bad) process.exit(1)
console.log('OK: 假壳那条路还接着（跑得绿不绿这条闸答不了，见文件头「够不着什么」）')
