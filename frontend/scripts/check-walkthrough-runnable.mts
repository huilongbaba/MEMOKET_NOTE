/** 走查工具箱的**「按 README 跑得起来」**闸（P72；P66 / P67 / P68 / P70 各欠了一批的那条）。
 *
 *     npx tsx scripts/check-walkthrough-runnable.mts
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ## 这条闸**判的是什么**
 *
 * 四件事，每一件都对着磁盘上真的东西问，不对着 README 的**命令文本**问：
 *
 *  1. **README 点名的每个文件都在。** 把 README 里所有反引号包着的仓库路径抠出来
 *     （`frontend/… `、`backend/…`、`steps/….mjs` …），逐个 `existsSync`。
 *  2. **每个入口都 import 得动。** `steps/*.mjs` 逐个 `await import()`。
 *     这一步真的把模块装进 node：相对 import 写错、语法坏了、导出名拼错，当场炸。
 *  3. **每个入口符合 `cdp.mjs` 的契约。** 驱动收尾那一行是 `await mod.default(d, args)`
 *     ——所以「一步」的默认导出必须是个函数。共用量具（`lib*.mjs`）没有 default，
 *     **这条豁免是显式名单**，不是「没有就算了」。
 *  4. **README 里 `export` 的每个环境变量，脚本里真有人读。** `export X=…` → 工具箱里
 *     必须有 `process.env.X`。（`unset X` 那一行豁免：`ELECTRON_RUN_AS_NODE` 是给
 *     Electron 自己看的，工具箱不读它——**豁免写在名单里，不是靠正则恰好漏掉**。）
 *
 * 另外**第二件事**（同一个工具箱的另一把尺，见文件下半段）：
 * **状态栏字数那条正则的例 / 反例表**（P70 问题 #2）。
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ## 怎么证明它**会红**
 *
 * 光跑绿不算数（`check-walkthrough-selectors.mts` 顶上那条「红不了不等于闸没了」）。
 * P72 逐刀验过（唯一锚点 + 整文件写回 + `filecmp` 逐字节核回原样 + 清缓存），
 * **跟这条闸有关的 8 刀**（另有 10 刀在别处，见 `docs/TRACELOG-product.md` P72 节）：
 *
 *  | 刀 | 动哪儿 | 预期 | 实测 |
 *  |---|---|---|---|
 *  | ① | README 里把 `steps/b1old.mjs` 改成 `steps/b1old-改名了.mjs` | 第 ① 条红 | **第一趟没红 → 抓出这条闸自己的洞，见下** |
 *  | ② | `steps/b1b.mjs` 里 `./lib.mjs` → `./libb.mjs` | 第 ② 条红 | 红，点名 `b1b.mjs` + `Cannot find module` |
 *  | ③ | `steps/whoami52.mjs` 的 `export default` 去掉 | 第 ③ 条红 | 红，点名 `whoami52.mjs` |
 *  | ④ | `cdp.mjs` 里 `process.env.WALKTHROUGH_SHOT_DIR` 改名 | 第 ④ 条红 | 红，点名 `WALKTHROUGH_SHOT_DIR` |
 *  | ⑤ | `lib.mjs` 的 `STATUS_WORDS_RE` 换回 P70 那条老正则 | 第 ⑤ 条红 | 红 **2 条样本**（第 1 条和第 3 条，都含 `1072 字 · 约 4 分钟`） |
 *  | ⑰ | ① 修完重砍一刀（`steps/b2old-纯ASCII之外.mjs`） | 第 ① 条红 | 红，点名那个中文名 |
 *  | ⑥ | **对照刀**：改 `steps/b1old.mjs` 里一句 `console.log` 的中文 | **不红** | 没红 |
 *  | ⑦ | **对照刀**：README 里改一句散文 | **不红** | 没红 |
 *  | ⑱ | **对照刀**：README 里那条花括号展开的假路径 `{main,preload,…}.js` 改一个字 | **不红**（它本来就不该当路径） | 没红 |
 *
 * ⑥⑦⑱ 是分母：**绿有个数，才分得清「放过了」和「没看见」**。
 *
 * **第 ① 刀第一趟没红，那是这条闸自己的洞，不是刀钝了。** 根因写在 `PATHY` 上面
 * ——一句话：判路径的正则用了 `\w`，中文文件名整条被静默跳过。
 * **判据比产品窄的第六张脸，跟它要治的 P70 问题 #2 是同一个形状。**
 * 修完补了第 ⑰ 刀重砍一次，这回红了。
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ## 它**够不着**什么（这一段不许含糊过去）
 *
 * **它没起过壳，一步走查都没跑过。** 具体地说，下面这些它一个都碰不到：
 *
 *  · **`npm run dist` 打不打得出来**（`vite build` + `pyinstaller` + `electron-builder`
 *    + adhoc 重签，十几分钟、几百 MB，产物不进 git）。
 *  · **CDP 端口连不连得上**、窗口起没起来、`ELECTRON_RUN_AS_NODE` 有没有真的被 unset。
 *  · **每一步跑起来对不对**：`d.must()` 选不到、判据读回 `null`、`until()` 等得够不够、
 *    截图存没存下来——**全在运行期**，这条闸只证明「装得进 node」。
 *  · **shell 命令本身**（`cd` / `npx` / `node` 那几行）。**故意不核**：
 *    「README 里那几行命令 grep 得到」是一条永远绿的闸，那正是这一批要避开的东西。
 *  · **`backend/scripts/walkthrough_udd.py` 跑不跑得动**（那半边由 `pytest` /
 *    `backend/tests/test_p66.py` 管，这边只核它在不在）。
 *  · **真库那一份拷贝、换 key、三个 base_url 指本机**——那是安全纪律，不是这条闸的射程。
 *
 * 换句话说：**它把「搬进仓库之后还是没人跑」这件事挡掉了三分之一**（在不在 / 装不装得进 /
 * 合不合契约），剩下三分之二仍然只有真起一次壳才能答。**别把它读成「走查过了」。**
 */
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { corpus } from './_corpus.mts'

const here = path.dirname(fileURLToPath(import.meta.url))
const FE = path.join(here, '..')
const REPO = path.join(FE, '..')
const KIT = path.join(here, 'walkthrough')
const STEPS = path.join(KIT, 'steps')
const README = path.join(KIT, 'README.md')

let bad = 0
const fail = (msg: string) => { bad++; console.log('✗ ' + msg) }

// ── 0. 先立分母：README 在、步骤脚本在 ───────────────────────────────────────
if (!existsSync(README)) { console.error(`✗ 没有 ${README}`); process.exit(1) }
const readme = readFileSync(README, 'utf8')
const stepFiles = corpus(
  readdirSync(STEPS).filter((n) => n.endsWith('.mjs')).sort().map((n) => path.join(STEPS, n)),
  18, '步骤脚本')

/** 反引号里的东西（README 是拿它标路径 / 变量 / 类名的）。 */
const ticks = [...readme.matchAll(/`([^`\n]+)`/g)].map((m) => m[1])

// ── 1. README 点名的每个文件都在 ─────────────────────────────────────────────
//
// **只认长得像一条具体路径的**（判据宁可窄）：带 `/`、带已知扩展名、不带空白 / 通配 / 花括号。
// 排掉的那几类都有实例：`app.asar/dist/{main,preload,capture,backend}.js`（花括号展开，
// 不是一条真路径）、`desktop/src`（没扩展名）、`d.must`（方法名，没有 `/`）。
//
// ⚠️ **这一条自己栽过一次**（P72 突变验第 ① 刀）：第一版写的是 `^[\w][\w./-]*\.(…)$`，
// 而 JS 的 `\w` 只有 `[A-Za-z0-9_]` —— README 里但凡有个**带中文的文件名**，
// 它整条串都不当路径，**静默跳过**。第 ① 刀把 `steps/b1old.mjs` 改成
// `steps/b1old-改名了.mjs`，闸**没红**。判据比产品窄的第六张脸，跟 P70 问题 #2
// 是同一个形状——**而且这一刀正是为了抓它才砍的**。
const PATHY = /^[^\s`*{},<>]+\.(mjs|mts|ts|tsx|py|json|md|xml|js)$/
const named = [...new Set(ticks.filter((t) => t.includes('/') && PATHY.test(t)))].sort()
// 相对 `steps/…` 的那些是相对**工具箱目录**写的，其余相对仓库根。
const resolveNamed = (t: string) => (t.startsWith('steps/') ? path.join(KIT, t) : path.join(REPO, t))
console.log(`① README 点名的文件：${named.length} 条`)
if (named.length < 8) fail(`README 里只抠出 ${named.length} 条路径 —— 抽取正则坏了，这条闸会一直绿`)
for (const t of named) {
  if (!existsSync(resolveNamed(t))) fail(`README 点名了 \`${t}\`，磁盘上没有：${resolveNamed(t)}`)
}

// ── 2 + 3. 每个入口都 import 得动 / 符合 `cdp.mjs` 的契约 ────────────────────
//
// 契约的出处：`cdp.mjs` 收尾那一行 `await mod.default(d, args)`。**从驱动里读回来核一遍**
// ——手写一份「我记得是 default」会跟驱动飘开，而飘开的症状是一条天天误报（或天天漏报）的闸。
const driver = readFileSync(path.join(KIT, 'cdp.mjs'), 'utf8')
if (!/await\s+mod\.default\(/.test(driver)) {
  fail('`cdp.mjs` 里找不到 `await mod.default(…)` —— 入口契约变了，下面这条断言先别信，人去看一眼')
}
/** 共用量具：不是「一步」，没有 default 是对的。**显式名单**，不是「没有就算了」。 */
const LIBS = new Set(['lib.mjs', 'lib52.mjs'])
console.log(`②③ 步骤脚本：${stepFiles.length} 份（其中共用量具 ${LIBS.size} 份）`)
let entries = 0
for (const f of stepFiles) {
  const base = path.basename(f)
  let mod: Record<string, unknown>
  try {
    mod = await import(f) as Record<string, unknown>
  } catch (e) {
    fail(`\`steps/${base}\` import 不动：${(e as Error).message.split('\n')[0]}`)
    continue
  }
  if (LIBS.has(base)) {
    if (typeof mod.default === 'function') {
      fail(`\`steps/${base}\` 在共用量具名单里，却导出了 default —— 名单跟事实飘了，改之前先看一眼`)
    }
    continue
  }
  entries++
  if (typeof mod.default !== 'function') {
    fail(`\`steps/${base}\` 的默认导出不是函数（是 ${typeof mod.default}）`
      + ' —— `cdp.mjs` 收尾会 `await mod.default(d, args)`，这一步跑起来当场 TypeError')
  }
}
// **入口一个都没有 = 这条闸什么都没核**（上面那个 try 全军覆没也是这个症状）。
if (entries < 15) fail(`只认出 ${entries} 个入口（至少该有 15 个）—— 名单或扫描目录坏了`)

// ── 4. README 里 export 的环境变量，脚本里真有人读 ──────────────────────────
//
// `unset X` 那一行豁免：`ELECTRON_RUN_AS_NODE` 是给 Electron 自己看的，工具箱不读它。
// **豁免写成名单**，不是靠正则恰好漏掉——漏掉的那种，下一个变量加进来时会静默放行。
const UNREAD_BY_DESIGN = new Set(['ELECTRON_RUN_AS_NODE'])
const exported = [...new Set([...readme.matchAll(/^\s*export\s+([A-Z][A-Z0-9_]*)=/gm)].map((m) => m[1]))]
const kitSrc = [path.join(KIT, 'cdp.mjs'), ...stepFiles].map((f) => readFileSync(f, 'utf8')).join('\n')
console.log(`④ README export 的环境变量：${exported.join(', ') || '(一个都没有)'}`)
if (!exported.length) fail('README 里一个 `export X=` 都没抠到 —— 抽取正则坏了，第 ④ 条会一直绿')
for (const v of exported) {
  if (UNREAD_BY_DESIGN.has(v)) continue
  if (!kitSrc.includes(`process.env.${v}`)) {
    fail(`README 让人 \`export ${v}\`，但工具箱里没有任何一处 \`process.env.${v}\` —— `
      + '这一步设了等于没设，跑的时候是静默走默认值')
  }
}
for (const v of UNREAD_BY_DESIGN) {
  // **豁免也要证明自己还在豁免**：哪天工具箱真读了它，这条豁免就该撤掉。
  if (kitSrc.includes(`process.env.${v}`)) {
    fail(`\`${v}\` 在「工具箱不读它」的豁免名单里，可现在工具箱真读了 —— 把它从名单里拿掉`)
  }
}

// ── 第二件事：状态栏字数那条正则的例 / 反例（P70 问题 #2）────────────────────
//
// P70 那一趟截图上白纸黑字写着「1072 字」，脚本读回 `null`，差点记成产品缺陷。
// 根因是 `lib.mjs` 的正则要求那个叶子**整串只有「N 字」**，而真界面是
// `1072 字 · 约 4 分钟`。**老正则原样留在这儿当反例**：它要是也能过第一条样本，
// 就说明样本表已经不是当年那个形状了，这条闸也就没在核任何东西。
const { STATUS_WORDS_RE, STATUS_WORDS_CASES } = await import(path.join(STEPS, 'lib.mjs')) as {
  STATUS_WORDS_RE: RegExp, STATUS_WORDS_CASES: [string, string | null][]
}
/** P70 那条（老的、太窄的）。**判的是叶子整串**，所以这里连锚点一起原样抄。 */
const OLD_RE = /^\s*\d+\s*字\s*$/
console.log(`⑤ 状态栏字数正则：${STATUS_WORDS_CASES.length} 条样本`)
if (STATUS_WORDS_CASES.length < 6) fail('样本表少于 6 条 —— 例 / 反例两侧至少各要有几条')
for (const [raw, want] of STATUS_WORDS_CASES) {
  const m = STATUS_WORDS_RE.exec(raw)
  const got = m ? m[0].replace(/\s+/g, ' ').trim() : null
  if (got !== want) fail(`状态栏样本 ${JSON.stringify(raw)}：读回 ${JSON.stringify(got)}，该是 ${JSON.stringify(want)}`)
}
{
  const [raw, want] = STATUS_WORDS_CASES[0]
  if (want === null) {
    fail('样本表第 1 条该是 P70 那张截图上的原话（一条**该读出数来**的），现在它的期望是 null')
  } else if (OLD_RE.test(raw)) {
    fail(`老正则在第 1 条样本 ${JSON.stringify(raw)} 上**也能过** —— 那条样本已经不是 P70 栽的那个形状了，`
      + '这条闸没在核任何东西，换回真界面上的原话')
  }
}

// ── 第三件事：截图名的**批次前缀从参数来**（P74 问题 #6 / P76 C①）──────────
//
// 那笔旧账：30 份步骤脚本里的截图名写死成 `p70-*`，**每批跑完手工改名**（P74 那批 36 张）。
// 改名本身不危险，**漏改**才危险——台账写着 `p74-b1-old-dark.png`，盘上那张其实是
// P70 拍的，而截图是走查唯一的物证。
//
// P76 的修法**不是把 30 份里的 `p70-` 改成 `p76-`**（那只是把同一个洞挪了一批，
// 还得把「步骤脚本一个字节不改」那条规矩作废）。所有截图只有一条出口——
// `cdp.mjs` 的 `d.shot()`——前缀在那儿从 `WALKTHROUGH_SHOT_PREFIX` 来。
//
// 这一段核三样，**例 / 反例跑在断言之前**：
//  ⑥ 那个改名函数本身对不对（6 条例 / 反例，含三条「不许动」的）；
//  ⑦ `cdp.mjs` 的 `shot()` **真的调了它**（摘掉整行注释再判——注释里提一嘴不算）；
//  ⑧ 步骤脚本里**还有多少张写死的批次前缀**：这个数**只准往下走**。
//     它不是 0 也没关系（这一批就不是 0），要紧的是**它们现在都会被前缀改掉**。
const { withBatchPrefix } = await import(path.join(KIT, 'shotname.mjs')) as {
  withBatchPrefix: (n: string, p: string | undefined) => string
}
const SHOT_CASES: [string, string | undefined, string][] = [
  // 例：写死的批次前缀被换掉
  ['p70-bnew-1-open-light.png', 'p76', 'p76-bnew-1-open-light.png'],
  ['p70-b8-flipday-1-light.png', 'p76', 'p76-b8-flipday-1-light.png'],   // 后面的数字一个不许碰
  ['p47-5-old-ctx-light.png', 'p76-', 'p76-5-old-ctx-light.png'],        // 末尾多给一个 `-` 也认
  // 反例：**不许动**的三种
  ['p70-bnew-1-open-light.png', undefined, 'p70-bnew-1-open-light.png'], // 没设环境变量 → 原样
  ['debug.png', 'p76', 'debug.png'],                                     // 名字里没有批次前缀 → 不许硬加
  ['/tmp/p70-x/p60-a.png', 'p76', '/tmp/p70-x/p76-a.png'],               // 只动最后一段，目录名不许动
]
console.log(`⑥ 截图批次前缀：${SHOT_CASES.length} 条样本`)
if (SHOT_CASES.length < 6) fail('截图前缀样本少于 6 条 —— 例 / 反例两侧至少各要有几条')
for (const [name, prefix, want] of SHOT_CASES) {
  const got = withBatchPrefix(name, prefix)
  if (got !== want) {
    fail(`截图前缀样本 ${JSON.stringify([name, prefix])}：读回 ${JSON.stringify(got)}，该是 ${JSON.stringify(want)}`)
  }
}
{
  // **接线洞单独一条断言**：`shot()` 真的调了它。**摘掉整行注释再判**——
  // 「文件里有这个串」≠「这段代码还在跑」（P68 第 ⑤ 刀 / P76 第 ⑪ 刀都栽在这上面）。
  const cdpCode = readFileSync(path.join(KIT, 'cdp.mjs'), 'utf8')
    .split('\n').map((l) => (/^\s*(\/\/|\*|\/\*)/.test(l) ? '' : l)).join('\n')
  if (!/name = withBatchPrefix\(name, process\.env\.WALKTHROUGH_SHOT_PREFIX\)/.test(cdpCode)) {
    fail('`cdp.mjs` 的 `shot()` 没在用 `withBatchPrefix(…, WALKTHROUGH_SHOT_PREFIX)` —— '
      + '截图名的批次前缀又回到「每批手工改 36 张」了（P74 问题 #6）')
  }
}
{
  // 步骤脚本里写死的批次前缀还剩几张。**只准往下走**：这个数涨了，说明又有人
  // 往步骤脚本里写死了新的一批号；而它现在不用是 0 —— 它们都会被前缀改掉。
  // **量出来的是 37，不是 P74 台账上那个 36**：那个 36 是**那一趟真拍下来**、
  // 事后手工改名的张数，源码里写死的是 37 张（有一张那一趟没跑到）。
  // **「台账上的数」和「源码里的数」是两把尺**，这儿钉的是后者。
  const MAX_HARDCODED = 37
  let hard = 0
  for (const f of stepFiles) {
    const src = readFileSync(f, 'utf8')
    hard += [...src.matchAll(/'(p\d+-[\w.-]*\.png)'/g)].length
      + [...src.matchAll(/`(p\d+-[^`$]*\.png)`/g)].length
  }
  console.log(`⑦ 步骤脚本里写死的批次前缀截图名：${hard} 张（上限 ${MAX_HARDCODED}，只准往下走）`)
  if (hard > MAX_HARDCODED) {
    fail(`步骤脚本里写死的批次前缀截图名涨到 ${hard} 张（上限 ${MAX_HARDCODED}）—— `
      + '别再往步骤脚本里写批次号了，前缀从 `WALKTHROUGH_SHOT_PREFIX` 来')
  }
  if (hard === 0) fail('一张写死的批次前缀都没扒到 —— 抽取正则坏了，第 ⑦ 条会一直绿')
}

// ── 第四件事：**「翻页成功」只许有一个判法**（P74 问题 #1 / P76 C②）─────────
//
// P58 问题 #8 → P74 问题 #1，**同一个坑在同一格里重演了两批**：
// `b3old.mjs` 的「翻到别的一天 → 确认框该作废」连点**同一个方向**的箭头，
// 站在最老那天上第二下什么都没发生（`next: false`），于是「确认框还在」
// 被读成产品缺陷。**「点过了 ≠ 翻过了」。**
//
// `flipday60.mjs` 是为这件事写的那一份，判法只有一个：**日期真的变了**。
// P76 把 `b3old.mjs` 那一格换成了它（`flip()` 导出出来共用）。这一条钉住那件事——
// **不然下一批换个人重写那一格，坑会第三次重演**。
{
  const flipSrc = readFileSync(path.join(STEPS, 'flipday60.mjs'), 'utf8')
  if (!/export async function flip\(/.test(flipSrc)) {
    fail('`flipday60.mjs` 不再导出 `flip()` —— 那是「日期真的变了」这个判法的唯一一份')
  }
  const b3 = readFileSync(path.join(STEPS, 'b3old.mjs'), 'utf8')
  const b3code = b3.split('\n').map((l) => (/^\s*(\/\/|\*|\/\*)/.test(l) ? '' : l)).join('\n')
  if (!/import \{ flip \} from '\.\/flipday60\.mjs'/.test(b3code)) {
    fail('`b3old.mjs` 不再用 `flipday60.mjs` 的 `flip()` 翻天 —— '
      + '「点过了 ≠ 翻过了」那个坑会第三次重演（P58 #8 / P74 #1）')
  }
  if (!/真翻了吗/.test(b3code)) {
    fail('`b3old.mjs` 的翻天那一格不再打印「真翻了吗」—— '
      + '没有这一行，「确认框还在」跟「压根没翻页」在日志上分不开')
  }
}

console.log(`\n扫了 README 1 份 / 点名文件 ${named.length} 条 / 步骤脚本 ${stepFiles.length} 份`
  + `（入口 ${entries}）/ 环境变量 ${exported.length} 个 / 状态栏样本 ${STATUS_WORDS_CASES.length} 条；`
  + `对不上 ${bad} 个`)
if (bad) process.exit(1)
console.log('OK: README 点名的都在、每个入口都 import 得动且符合 cdp.mjs 的契约、'
  + 'export 的环境变量真有人读、状态栏那条正则例反例全对')
console.log('⚠️ 够不着的那三分之二（打壳 / 起壳 / 真跑每一步）见本文件顶上那段 —— 别读成「走查过了」')
