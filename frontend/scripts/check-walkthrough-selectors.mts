/** 走查量具的**静态自检**：量具里选的每一个类名，在前端源码里真的存在吗？
 *
 *     npx tsx scripts/check-walkthrough-selectors.mts [额外扫描目录...]
 *
 * **为什么要有这个**（P62 立、P64 实测抓到、P66 搬进仓库接进 `npm test`）：
 * `d.count()` / `d.texts()` 选不到时回 `0` / `[]`，跟「产品里真的没有」读起来一模一样。
 * P60 问题 #6 那两格（`.cm-margin-dot` / `.context-menu`）就这样在 P58 / P60 两批的
 * 台账上躺了两批 —— 报的圆点 0、右键菜单 `[]` **全是假的**，真类是 `.mm-dot` / `.palette-item`。
 * 运行期那一半由 `walkthrough/cdp.mjs` 的 `d.must()` 管（选不到就抛）；
 * 这一份管**跑之前**：把量具里所有类名对着 `frontend/src` 点一遍名。
 *
 * **它是有牙的，不是摆设**：P64 收工那一趟它当场点名了那一批**新写的**
 * `.journey-day-opt` —— 前端里根本没有这个类，`option` 那一半退回去把「留多久」
 * 两个下拉的选项读了回来，打出来「1 周（7 天）/ 3 个月（90 天）…」**看起来像天列表**。
 * **「选到东西 ≠ 选到那个东西」。**
 *
 * **扫什么**：默认只扫仓库里的 `scripts/walkthrough/`（公共驱动）。
 * 步骤脚本（`steps/*.mjs`）还在 scratch 里（要真打出来的 `.app`，见
 * `walkthrough/README.md`），跑走查之前**显式点名**那些目录：
 *
 *     npx tsx scripts/check-walkthrough-selectors.mts <scratch>/p66/steps
 *
 * **两遍抽取，因为一遍会漏**：
 *  ① 前缀表（P62 原版）：`.mm-* / .cm-* / .palette-* …` 这些已知前缀，整份源码里抓。
 *  ② 选择器字面量（P66 加）：只看**真的被当选择器传进去**的那些字符串
 *     （`querySelectorAll('…')` / `d.must('…')` / `d.texts('…')` …），
 *     从里头抠类名 —— **前缀表外的类名第 ① 遍一个都看不见**，而
 *     「新写的选择器用了个没见过的前缀」正是最容易漏的那一类。
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { corpus } from './_corpus.mts'

const here = path.dirname(fileURLToPath(import.meta.url))
const FE = path.join(here, '..')
const EXTRA = process.argv.slice(2)

/** 前端源码整棵树拼成一个大串（`src/**` 的 .ts/.tsx/.css）。 */
function slurp(dir: string, out: string[] = []): string[] {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n)
    if (statSync(p).isDirectory()) { if (n !== 'node_modules') slurp(p, out) }
    else if (/\.(ts|tsx|css)$/.test(n)) out.push(p)
  }
  return out
}
const srcFiles = corpus(slurp(path.join(FE, 'src')), 70, '前端源文件')
const HAY = srcFiles.map((f) => readFileSync(f, 'utf8')).join('\n')

/** ① 已知前缀。 */
const CLASS_RE = /\.((?:cm|mm|kb|mem|note|pane|palette|toast|toaster|margin|context|journey|round|agent|chip|ribbon|slide|tab)[a-zA-Z0-9_-]*)/g
/** ② 真的被当选择器用的那些字符串。函数名列窄一点，宁可漏也别把散文当选择器。 */
const SEL_CALL_RE = /(?:querySelectorAll|querySelector|closest|matches|count|texts|text|exists|must|mustTexts|rect|click|rclick|clickText|findText|readCard|menuItems|expandDetails)\(\s*(['"`])((?:[^'"`\\]|\\.)*)\1/g
const CLASS_IN_SEL_RE = /\.([A-Za-z_][\w-]*)/g
const WILD_RE = /\[class\s*\*=\s*["'][^"']+["']\]/g
/** 这个串**看起来像个选择器**吗？不像就整串扔掉，别从里头抠「类名」。
 *
 * 实测反例（P66 拿 `p64/steps` 跑出来的）：`querySelector('button[title=${JSON.stringify(t)}]')`
 * —— 里面那个 `.stringify` 会被当成一个类名报出来。**闸门不该把不是选择器的东西当选择器**
 * （`check-css-classes.mts` 顶上记的注释 / `url()` 两次是同一个形状）。
 * 判据宁可窄：带 `${}` 的模板（拼出来的选择器，静态核不了）和
 * 出了 CSS 选择器字符集的串，一律不抠。 */
const LOOKS_LIKE_SELECTOR = /^[\w\s.#>+~*[\]="'^$|:(),-]*$/

/** 注释里写的类名不算「在选」—— 这一份自己的说明里就写着 `.cm-margin-dot` 这种反例。
 *  方法调用也不算（`d.cmText()` 的 `.cmText` 不是选择器）。 */
function strip(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, ' ')      // 块注释
    .replace(/^[ \t]*\/\/.*$/gm, ' ')        // 整行行注释
    .replace(/([^:])\/\/.*$/gm, '$1')        // 行尾注释（别误伤 http://）
}

function mjsIn(dir: string): string[] {
  try { return readdirSync(dir).filter((n) => n.endsWith('.mjs')).map((n) => path.join(dir, n)) }
  catch { return [] }
}

const files = [...mjsIn(path.join(here, 'walkthrough'))]
for (const d of EXTRA) {
  const got = mjsIn(d)
  if (!got.length) { console.error(`✗ 点名的目录 ${d} 里一个 .mjs 都没有 —— 扫不到东西的闸门会一直是绿的`); process.exit(1) }
  files.push(...got)
}
// **扫不到东西的闸门会一直是绿的**：公共驱动至少得在。
corpus(files, 1, '量具文件')

let wilds = 0
const seen = new Map<string, { files: Set<string>, how: Set<string> }>()
const note = (cls: string, f: string, how: string) => {
  if (!seen.has(cls)) seen.set(cls, { files: new Set(), how: new Set() })
  seen.get(cls)!.files.add(f)
  seen.get(cls)!.how.add(how)
}
for (const f of files) {
  const raw = readFileSync(f, 'utf8')
  const src = strip(raw)
  const show = f.replace(FE + '/', '')
  for (const m of src.matchAll(WILD_RE)) { wilds++; console.log(`  通配  ${show}  ${m[0]}`) }
  for (const m of src.matchAll(CLASS_RE)) {
    // `d.cmText()` 是方法、`window.memoketDesktop?.x` 是属性——都不是选择器
    if (src[m.index! + m[0].length] === '(' || src[m.index! + m[0].length] === '?') continue
    note(m[1], show, '前缀')
  }
  for (const m of src.matchAll(SEL_CALL_RE)) {
    const sel = m[2]
    if (sel.includes('${') || !LOOKS_LIKE_SELECTOR.test(sel)) continue
    for (const c of sel.matchAll(CLASS_IN_SEL_RE)) note(c[1], show, '选择器字面量')
  }
}

let bad = 0
for (const [cls, info] of [...seen].sort()) {
  // 前端源码里出现过这个类名就算数（className / styles.css 规则 / 探针里都算）
  if (HAY.includes(cls)) continue
  bad++
  console.log(`✗ 「.${cls}」在 frontend/src 里一个字都搜不到 —— 选不到 ≠ 没有（${[...info.how].join(' / ')}）：`)
  for (const f of info.files) console.log(`    ${f}`)
}

// **量具里一个类名都没抠出来 = 这条闸什么都没核**（正则写坏 / 文件挪位都是这个症状）。
// 8 是当前值（只扫公共驱动那一份 = 14 个）的六成左右：留够增删余量，挡得住「几乎什么都没抠到」。
const MIN_CLASSES = 8
if (seen.size < MIN_CLASSES) {
  console.error(`✗ 只抠出 ${seen.size} 个类名（至少该有 ${MIN_CLASSES} 个）——`
    + '抽取正则或扫描目录坏了，这条闸会一直绿。别把这个数字改小')
  process.exit(1)
}

console.log(`\n扫了 ${files.length} 个量具文件 / ${seen.size} 个类名 / ${wilds} 处通配；对不上 ${bad} 个`)
if (bad) process.exit(1)
console.log('OK: 量具里选的每一个类名在 frontend/src 里都真的有')
