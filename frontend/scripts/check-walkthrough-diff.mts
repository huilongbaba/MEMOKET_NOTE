/** **跨批逐行 diff 这件事本身的闸**（P87 留的第 ⑥ 条，P89 B）。
 *
 *     ./node_modules/.bin/tsx scripts/check-walkthrough-diff.mts
 *     ./node_modules/.bin/tsx scripts/check-walkthrough-diff.mts --selftest
 *
 * ── 为什么有它 ────────────────────────────────────────────────────────────
 * P87 A 做成了第一次跨批逐行 diff（`p85` ↔ `p87`，78 行、逐行归了四类），
 * 而它自己在末尾写着：
 *
 *     ⑥ **跨批 diff 这件事本身还没有闸**：这一批是人跑 `diff`、人读的。
 *        「两批之间该有几行差异」没法钉（钉了每批都红），
 *        但**「diff 出来的每一行都被归过类」**这件事今天只靠台账。
 *
 * 「只靠台账」是什么意思，P87 自己给了证据：那一份 diff **当场抓到一处台账错**
 * （P85 的走查表把「900px 横向溢出」记成 0，而 P85 自己的日志里写着 1）。
 * 散文写错了没人看得出来。**台账和日志是两把尺**——而这一份把第三把尺摆上：
 * **diff 出来的每一行，在归类表里都得有它自己的一行。**
 *
 * ── 它比的是什么 ──────────────────────────────────────────────────────────
 * 归类表 = `docs/walkthrough-logs/<to>/DIFF-FROM-<from>.tsv`，每行五列（TAB 分）：
 *
 *     类别 <TAB> 文件 <TAB> 方向 <TAB> 那一行逐字 <TAB> 为什么
 *
 * · **方向** `<` = 只在 `<from>` 那一份里、`>` = 只在 `<to>` 那一份里
 *   （跟 `diff` 打出来的前缀逐字一样）；整份文件只在一边时方向是 `-`/`+`。
 * · **那一行逐字**就是 `diff` 打出来那一行去掉前缀之后的原文，**一个字都不许改**。
 * · 类别是**闭集**（见 `CLASSES`）：新冒出来一类得有人想清楚再加进来，
 *   不许随手写一个词把事情盖过去。
 *
 * 两边**多集相等**（同一行出现两次就得归两次）：
 *  · diff 里有、归类表里没有 → **红**（这就是「有差异却没人归类」）
 *  · 归类表里有、diff 里没有 → **红**（上一批的归类留在表里，下一批照抄就绿了）
 *
 * ── **「该有几行差异」一个数都没钉** ──────────────────────────────────────
 * 这是这条闸最要紧的一件事，所以写在这儿而不是脚注里：
 * 这份代码里**没有** `MIN_DIFF_LINES` / `EXPECT_LINES` / `>= N` 这种东西，
 * 0 行是绿的，200 行也是绿的——**只要每一行都被归过类**。
 * 钉那个数等于「每一次正当改动都红一次」，而一条天天误报的闸迟早被人改成不红
 * （P80 B② 判 `db_guard.WATCHED` 不收 `harness_runs` 逐字同一条理由）。
 *
 * ── 它答不了什么 ──────────────────────────────────────────────────────────
 *  · **归得对不对**：一条都答不了。把 78 行全归成「入参素材」它照样绿。
 *    它能做到的是让这件事**在 diff 里是 78 行数据**，而不是一句「都看过了」。
 *    最后一只乌龟仍然是人读 diff——但读的是逐行写着理由的数据行（同 P80 B③）。
 *  · **这两批该不该拿来比**：`from` / `to` 是归类表自己写在文件名里的。
 *  · **日志本身洗干净了没有**：那是 `normalize-log.mjs --selftest` 那一侧的事。
 *    （没洗干净的东西会在这儿变成一堆「归一化漏洞」行——**能归类不等于该留着**。）
 */
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, join, resolve } from 'node:path'

/** 归类的**闭集**。每一类后面那句话是它的边界，不是装饰。 */
const CLASSES = new Map<string, string>([
  ['入参素材', '走查这一趟的入参 / 素材跟上一批不一样（种子标题、截图前缀、开的不是同一篇…）——不是产品变了'],
  ['归一化漏洞', '每批都会变的东西没被洗掉，是归一化那条闸的洞（**这一档该在同一批补上**）'],
  ['走查随机', '走查自己的随机性（候选序号、角标…）——记在案，看下一批还在不在'],
  ['量具改了', '这一批动了量具，日志跟着变'],
  ['产品改了', '这一批动了产品，日志跟着变'],
  ['解释不了', '没查清——**必须同时记进这一批的问题清单**'],
])

/** 归类表里「为什么」那一列的下限：空的、或者短到等于没写，都算没归类。 */
const MIN_WHY = 4

type Item = { file: string; dir: string; line: string }

const key = (i: Item) => `${i.file}\t${i.dir}\t${i.line}`

/** 两个目录逐文件比一遍，把 `diff` 打出来的每一行收成一条。**自己不实现 diff**：
 *  这一条闸要比的就是「人跑 `diff` 会看到什么」，换一个自造的算法就换了口径。 */
export function diffItems(fromDir: string, toDir: string): Item[] {
  const ls = (d: string) => (existsSync(d) ? readdirSync(d).filter((n) => n.endsWith('.txt')).sort() : [])
  const a = ls(fromDir)
  const b = ls(toDir)
  const out: Item[] = []
  for (const f of [...new Set([...a, ...b])].sort()) {
    const inA = a.includes(f)
    const inB = b.includes(f)
    if (!inA || !inB) { out.push({ file: f, dir: inA ? '-' : '+', line: '（整份文件）' }); continue }
    let raw = ''
    try {
      raw = execFileSync('diff', [join(fromDir, f), join(toDir, f)], { encoding: 'utf8' })
    } catch (e) {
      // `diff` 有差异时退 1 —— 那是正常路径，不是出错
      raw = String((e as { stdout?: string }).stdout ?? '')
    }
    for (const l of raw.split('\n')) {
      if (l.startsWith('< ') || l.startsWith('> ')) out.push({ file: f, dir: l[0], line: l.slice(2) })
      else if (l === '<' || l === '>') out.push({ file: f, dir: l[0], line: '' })
    }
  }
  return out
}

export type Row = { cls: string; file: string; dir: string; line: string; why: string; at: number }

export function parseLedger(text: string): { rows: Row[]; bad: string[] } {
  const rows: Row[] = []
  const bad: string[] = []
  text.split('\n').forEach((raw, i) => {
    const n = i + 1
    if (!raw.trim() || raw.startsWith('#')) return
    const c = raw.split('\t')
    if (c.length < 5) { bad.push(`第 ${n} 行只有 ${c.length} 列，要 5 列（类别/文件/方向/那一行/为什么，TAB 分）`); return }
    // 「那一行」自己可能含 TAB：**最后一列是「为什么」，中间全归「那一行」**
    const [cls, file, dir] = c
    const why = c[c.length - 1]
    const line = c.slice(3, c.length - 1).join('\t')
    if (!CLASSES.has(cls)) bad.push(`第 ${n} 行的类别「${cls}」不在闭集里（${[...CLASSES.keys()].join(' / ')}）`)
    if (!'<>-+'.includes(dir) || dir.length !== 1) bad.push(`第 ${n} 行的方向「${dir}」该是 < / > / - / + 之一`)
    if (why.trim().length < MIN_WHY) bad.push(`第 ${n} 行没写为什么（「${why}」）——**归类表不写理由就只是一张打勾表**`)
    rows.push({ cls, file, dir, line, why, at: n })
  })
  return { rows, bad }
}

/** 多集相减。回「diff 里有归类表里没有的」和「归类表里有 diff 里没有的」。 */
export function reconcile(items: Item[], rows: Row[]) {
  const left = new Map<string, number>()
  for (const it of items) left.set(key(it), (left.get(key(it)) ?? 0) + 1)
  const stale: Row[] = []
  for (const r of rows) {
    const k = key(r)
    const n = left.get(k) ?? 0
    if (n > 0) left.set(k, n - 1)
    else stale.push(r)
  }
  const uncovered: Item[] = []
  for (const it of items) {
    const k = key(it)
    const n = left.get(k) ?? 0
    if (n > 0) { left.set(k, n - 1); uncovered.push(it) }
  }
  return { uncovered, stale }
}

// ── 跑 ────────────────────────────────────────────────────────────────────
const LOGS = resolve(import.meta.dirname, '../../docs/walkthrough-logs')
let bad = 0
const fail = (m: string) => { bad++; console.log(`✗ ${m}`) }

function checkOne(toDir: string, ledgerPath: string): { items: number; rows: number } {
  const from = basename(ledgerPath).replace(/^DIFF-FROM-/, '').replace(/\.tsv$/, '')
  const fromDir = join(LOGS, from)
  const rel = `docs/walkthrough-logs/${basename(toDir)}/${basename(ledgerPath)}`
  if (!existsSync(fromDir)) { fail(`${rel} 说要跟 ${from} 比，可 docs/walkthrough-logs/${from} 不在`); return { items: 0, rows: 0 } }
  const items = diffItems(fromDir, toDir)
  const { rows, bad: parseBad } = parseLedger(readFileSync(ledgerPath, 'utf8'))
  for (const b of parseBad) fail(`${rel}：${b}`)
  const { uncovered, stale } = reconcile(items, rows)
  for (const it of uncovered) {
    fail(`${rel} 漏了一行没归类 —— ${it.file} ${it.dir} ${JSON.stringify(it.line)}`)
  }
  for (const r of stale) {
    fail(`${rel} 第 ${r.at} 行归的是一条**今天已经不在 diff 里**的差异 —— `
      + `${r.file} ${r.dir} ${JSON.stringify(r.line)}（上一批的归类照抄下来就是这样）`)
  }
  const byCls = [...CLASSES.keys()].map((c) => `${c} ${rows.filter((r) => r.cls === c).length}`).join(' · ')
  console.log(`  ${basename(toDir)} ← ${from}：diff ${items.length} 行 / 归类 ${rows.length} 行（${byCls}）`)
  return { items: items.length, rows: rows.length }
}

// ── --selftest：**先喂它一个该红的** ──────────────────────────────────────
function selftest() {
  const root = mkdtempSync(join(tmpdir(), 'p89diff-'))
  const A = join(root, 'a')
  const B = join(root, 'b')
  mkdirSync(A); mkdirSync(B)
  writeFileSync(join(A, '01.txt'), '同一行\n开着的是 <ID12>\n字数 105\n')
  writeFileSync(join(B, '01.txt'), '同一行\n开着的是 <ID12>\n字数 205\n')
  writeFileSync(join(A, '02.txt'), '两批逐字节相同\n')
  writeFileSync(join(B, '02.txt'), '两批逐字节相同\n')
  writeFileSync(join(B, '03.txt'), '这一批新加的一份\n')
  const items = diffItems(A, B)
  // 例：三条（`< 字数 105` / `> 字数 205` / `03.txt 整份只在 b`）
  const CASES: [string, number, string][] = [
    ['diff 收到的条数', 3, '一行改动 = 一条 `<` + 一条 `>`，外加只在一边的那份文件'],
  ]
  for (const [why, want, note] of CASES) {
    if (items.length !== want) fail(`${why} 对不上：${items.length}，该是 ${want}（${note}）`)
  }
  const full = [
    '# from: a\t# to: b',
    ['量具改了', '01.txt', '<', '字数 105', '上一批的量具印的是跑之前'].join('\t'),
    ['产品改了', '01.txt', '>', '字数 205', '这一批续写真落地了'].join('\t'),
    ['量具改了', '03.txt', '+', '（整份文件）', '这一批新加的一步'].join('\t'),
  ].join('\n')
  const parsed = parseLedger(full)
  if (parsed.bad.length) fail(`齐全的归类表不该有解析错：${parsed.bad.join(' / ')}`)
  let r = reconcile(items, parsed.rows)
  if (r.uncovered.length || r.stale.length) {
    fail(`**例**：归类表齐全时该绿，却报了 ${r.uncovered.length} 漏 / ${r.stale.length} 陈`)
  }
  // 反例 ①：**少归一行** —— 该红，而且红的得是那一行
  const missing = parseLedger(full.split('\n').filter((l) => !l.includes('字数 205')).join('\n'))
  r = reconcile(items, missing.rows)
  if (r.uncovered.length !== 1 || r.uncovered[0].line !== '字数 205') {
    fail(`**反例①**（少归一行）该红在「字数 205」那一条，实得 ${JSON.stringify(r.uncovered)}`)
  }
  // 反例 ②：**多归一行**（上一批的归类照抄下来）—— 该红
  const extra = parseLedger(full + '\n' + ['走查随机', '01.txt', '>', '字数 999', '抄上一批的'].join('\t'))
  r = reconcile(items, extra.rows)
  if (r.stale.length !== 1 || r.stale[0].line !== '字数 999') {
    fail(`**反例②**（多归一行）该红在「字数 999」那一条，实得 ${JSON.stringify(r.stale)}`)
  }
  // 反例 ③：**归错了文件**（行对、文件不对）—— 该红两头
  const wrongFile = parseLedger(full.replace('产品改了\t01.txt\t>', '产品改了\t02.txt\t>'))
  r = reconcile(items, wrongFile.rows)
  if (r.uncovered.length !== 1 || r.stale.length !== 1) {
    fail(`**反例③**（归到别的文件上）该同时报 1 漏 + 1 陈，实得 ${r.uncovered.length} / ${r.stale.length}`)
  }
  // 反例 ④：**类别不在闭集里** —— 该红
  const badCls = parseLedger(full.replace('量具改了\t01.txt\t<', '大概是环境\t01.txt\t<'))
  if (!badCls.bad.some((b) => b.includes('不在闭集里'))) fail('**反例④**（类别不在闭集里）该红，没红')
  // 反例 ⑤：**理由留空** —— 该红（「打勾表」那一档）
  const noWhy = parseLedger(full.replace('\t上一批的量具印的是跑之前', '\t-'))
  if (!noWhy.bad.some((b) => b.includes('没写为什么'))) fail('**反例⑤**（理由留空）该红，没红')
  // 反例 ⑥：**列数不够** —— 该红
  const short = parseLedger('量具改了\t01.txt\t<\t字数 105')
  if (!short.bad.some((b) => b.includes('要 5 列'))) fail('**反例⑥**（只有 4 列）该红，没红')
  // 例 ②：**两批一个字都不差时，空归类表是绿的**（「该有几行差异」一个数都没钉）
  const same = diffItems(A, A)
  const rSame = reconcile(same, [])
  if (same.length !== 0 || rSame.uncovered.length || rSame.stale.length) {
    fail(`**例②**：跟自己比该 0 行 / 空表绿，实得 ${same.length} 行`)
  }
  return 1 + 6 + 1 + CASES.length   // 例 1 + 反例 6 + 例② 1 + diff 条数那条
}

const cases = selftest()

let pairs = 0
let lines = 0
let rowsAll = 0
if (existsSync(LOGS)) {
  for (const batch of readdirSync(LOGS).sort()) {
    const dir = join(LOGS, batch)
    if (!statSync(dir).isDirectory()) continue
    for (const f of readdirSync(dir).filter((n) => /^DIFF-FROM-.+\.tsv$/.test(n)).sort()) {
      pairs++
      const got = checkOne(dir, join(dir, f))
      lines += got.items
      rowsAll += got.rows
    }
  }
}
// **最新那一批必须有归类表**（不然「这一批忘了做」就是静默绿——一条靠人记得的闸不是闸）。
// 只管最新这一批：比它老的那几批是这条闸之前留下的，**我没跑过它们那一趟，
// 不替它们在归类表上签字**（P87 的分类写在散文里，是summary 级的，不是逐行的）。
const batches = existsSync(LOGS)
  ? readdirSync(LOGS).filter((n) => statSync(join(LOGS, n)).isDirectory() && /^p\d+$/.test(n))
    .sort((x, y) => Number(x.slice(1)) - Number(y.slice(1)))
  : []
const newest = batches[batches.length - 1]
if (!newest) {
  fail('`docs/walkthrough-logs/` 底下一批走查日志都没有')
} else if (batches.length > 1
  && !readdirSync(join(LOGS, newest)).some((n) => /^DIFF-FROM-.+\.tsv$/.test(n))) {
  fail(`最新那一批 ${newest} 没有归类表（\`docs/walkthrough-logs/${newest}/DIFF-FROM-<上一批>.tsv\`）`
    + ' —— **跨批 diff 没有归类表就等于没跑过**')
}

console.log(`\n跨批 diff 那条闸：比了 ${pairs} 对（共 ${lines} 行差异 / ${rowsAll} 行归类，`
  + `**「该有几行」一个数都没钉**）；类别闭集 ${CLASSES.size} 类；例 / 反例 ${cases} 条；对不上 ${bad} 个`)
if (bad) { console.log(`\n${bad} 处失败`); process.exit(1) }
console.log('OK: 每一批的跨批 diff 都有归类表，diff 出来的每一行都在表里有它自己的一行')
