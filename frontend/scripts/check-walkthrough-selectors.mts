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
 * **三遍抽取，因为前两遍的并集还是会漏**：
 *  ① 前缀表（P62 原版）：`.mm-* / .cm-* / .palette-* …` 这些已知前缀，整份源码里抓。
 *  ② 选择器字面量（P66 加）：只看**真的被当选择器传进去**的那些字符串
 *     （`querySelectorAll('…')` / `d.must('…')` / `d.texts('…')` …），
 *     从里头抠类名 —— **前缀表外的类名第 ① 遍一个都看不见**，而
 *     「新写的选择器用了个没见过的前缀」正是最容易漏的那一类。
 *  ③ **拼出来的选择器**（P67 加，P66 留的第 ④ 条）：`d.count('.' + kind)` 这种
 *     **前两遍都抓不到**。第 ① 遍看见的是注释和方法名那一类字面 `.xxx`；
 *     第 ② 遍抓的是「紧跟在 `(` 后面的那个字符串」，而 `'.' + kind` 里
 *     **那个字符串就是一个孤零零的 `.`**，`CLASS_IN_SEL_RE` 从里头抠不出任何类名，
 *     于是它**静悄悄地过**。
 *
 * ### 第 ③ 遍的判据，为什么是这一条（而不是「把 `'.' + kind` 也静态算出来」）
 *
 * 算不出来 —— `kind` 是运行时的值，静态核**本来就不该假装知道**它是什么。
 * 所以这一遍换了个问法：**拼出来的选择器选空了，谁会吵？**
 *  · 走 `must()` / `mustTexts()` / `click()` / `clickText()` / `rclick()` / `readCard()`
 *    —— 这几个**选不到当场抛**（`must` 的那句「选不到 ≠ 没有」）。静态核不了没关系，
 *    运行期有人管。**只计数，不报错。**
 *  · 走 `count()` / `texts()` / `text()` / `exists()` / `menuItems()` / `rect()` /
 *    `findText()` / `querySelectorAll()` —— 这几个选不到回 `0` / `[]` / `null`，
 *    **跟「产品里真的没有」读起来一模一样**。静态核不了 + 运行期不吭声 =
 *    **两头都没人管**，正是 P60 问题 #6 那两格躺两批的形状。**点名报错。**
 *
 * **`this.xxx(…)` 不算**（判据宁可窄）：量具库自己内部把 `sel` 参数传来传去
 * （`must` 里的 `this.count(sel)`、`click` 里的 `this.rect(sel)`）不是「拼选择器」。
 * 先量后加的这一条：不排除 `this` 时，光仓库里那一份公共驱动就误报 **6 处**。
 *
 * **这一遍今天在仓库里扫不到调用点**（公共驱动只有定义、没有调用方；步骤脚本还在
 * scratch，P66 留给下一批第 3 条）。所以它的证据不是「跑绿了」，是突变验：
 * 现造一个量具目录，`d.count('.' + kind)` 一刀下去它**红且点名**，
 * `d.must('.' + kind)` 一刀下去它**绿、但第 ③ 遍的计数从 0 变 1**
 * —— **红不了不等于闸没了**（P66 第 ⑪ 刀那一课）。
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
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

/** ③ 选不到会**当场抛**的读法：静态核不了没关系，运行期有人管。 */
const THROWS = new Set(['must', 'mustTexts', 'click', 'clickText', 'rclick', 'readCard'])
/** ③ 选不到**一声不响**回 `0` / `[]` / `null` 的读法：静态核不了就没人管了。 */
const SILENT = new Set(['querySelectorAll', 'querySelector', 'count', 'texts', 'text',
  'exists', 'menuItems', 'rect', 'findText', 'expandDetails'])

/** 这个实参是不是一个**写死的**选择器串（那第 ② 遍已经管着了）。 */
function isPlainSelector(a: ts.Node): boolean {
  return ts.isStringLiteral(a) || ts.isNoSubstitutionTemplateLiteral(a)
}

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
/** 第 ③ 遍的分母 / 战果。`builtSafe` 是「拼出来的，但走会抛的读法」——**它不是错**，
 *  打出来是为了让「绿」有个数：0 → 1 说明这一遍真的看见了那一刀（P66 第 ⑪ 刀那一课）。 */
let seenCalls = 0, builtSafe = 0
const builtBlind: string[] = []
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
  // ③ 拼出来的选择器。**拿 AST 不拿正则**：这一遍问的是「第一个实参是不是一个写死的串」，
  // 而 `'.' + kind` / `` `.${kind}` `` / `SEL[kind]` 各长一个样，正则挨个描一遍
  // 就是又一把会漏的尺子 —— 而这一条闸存在的全部理由就是「前两遍会漏」。
  const sf = ts.createSourceFile(f, raw, ts.ScriptTarget.Latest, true)
  const walk = (n: ts.Node) => {
    if (ts.isCallExpression(n) && n.arguments.length && ts.isPropertyAccessExpression(n.expression)) {
      const name = n.expression.name.text
      // **`this.xxx(…)` 不算**：量具库自己把 `sel` 参数传来传去不是「拼选择器」。
      const onThis = n.expression.expression.kind === ts.SyntaxKind.ThisKeyword
      if (!onThis && (THROWS.has(name) || SILENT.has(name))) {
        seenCalls++
        const a = n.arguments[0]
        if (!isPlainSelector(a)) {
          const { line } = sf.getLineAndCharacterOfPosition(a.getStart(sf))
          const where = `${show}:${line + 1}  ${name}(${a.getText(sf).slice(0, 60)})`
          if (THROWS.has(name)) { builtSafe++; console.log(`  拼出来（运行期会抛，不算洞）  ${where}`) }
          else builtBlind.push(where)
        }
      }
    }
    ts.forEachChild(n, walk)
  }
  walk(sf)
}

let bad = 0
for (const where of builtBlind) {
  bad++
  console.log('✗ 拼出来的选择器走了**静默读法**，静态核不了、运行期也不吭声 —— '
    + '选不到会回 0 / [] / null，跟「产品里真的没有」读起来一模一样。'
    + '改走 `must()` / `mustTexts()`（选不到当场抛），或者把选择器写死：')
  console.log(`    ${where}`)
}
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

console.log(`\n扫了 ${files.length} 个量具文件 / ${seen.size} 个类名 / ${wilds} 处通配；`
  + `第 ③ 遍 ${seenCalls} 个调用点（拼出来的：会抛 ${builtSafe} / 静默 ${builtBlind.length}）；`
  + `对不上 ${bad} 个`)
if (bad) process.exit(1)
console.log('OK: 量具里选的每一个类名在 frontend/src 里都真的有')
