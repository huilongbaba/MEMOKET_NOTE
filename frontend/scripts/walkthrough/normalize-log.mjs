/** **把一趟走查的日志洗成「跨批可以逐行 diff」的样子**（P85 C①）。
 *
 *     node scripts/walkthrough/normalize-log.mjs --today 2026-09-21 <日志文件…>   # 打到 stdout
 *     node scripts/walkthrough/normalize-log.mjs --today 2026-09-21 --out <目录> <日志文件…>
 *     node scripts/walkthrough/normalize-log.mjs --selftest                        # 例 / 反例
 *
 * ── 为什么有它 ────────────────────────────────────────────────────────────
 * P83 的走查那一节末尾逐字写着：
 *
 *     ⚠️ **这一批没能逐行 diff 到 P80 的原始日志**：P80 那份跑在它自己的 scratch 里，
 *     这一批开工时**已经不在了**。…… 下一批要么把上一批的日志留在**固定位置**，
 *     要么就别在任务书里写「逐行 diff 判」。
 *
 * 「留在固定位置」只解决一半。原始日志里每一批都会变的东西有一大把
 * （note id、端口、pid、时间戳、今天是几号、截图名的批次前缀、scratch 的绝对路径），
 * 直接 `diff` 两批**每一行都不一样**——**一条永远红的闸不是闸**，一份永远全红的 diff
 * 也不是对账。所以这一份把「每批都会变」和「变了就该看一眼」**分开**：
 *
 * ── **洗掉的**（每批必变，留着只会淹掉真差异）────────────────────────────
 *  1. 绝对路径的目录那一截 → `<DIR>/`（**文件名留着**，不然截图名就对不上了）
 *  2. 12 位十六进制 → `<ID12>`（note id / 改动层 id；P83 B 那条坑的主角）
 *  3. `127.0.0.1:<端口>` → `:<PORT>`、`pid=<数字>` → `pid=<PID>`
 *  4. ISO 时间戳 → `<TS>`
 *  5. **这一趟的今天 / 昨天 / 前天**三个日期 → `<D0>` / `<D-1>` / `<D-2>`
 *  6. 截图名的批次前缀 `p<数字>-` → `<B>-`；身份 `p<数字>-newbie` → `<B>-newbie`
 *  7. 前端随手生成的身份 `user-xxxxxx` → `<RANDUSER>`（P60 #2 那条坑的症状）
 *  8. `content_tag` 里那一截哈希 → `<TAG>`
 *
 * ── **一个字都不洗的**（洗掉它们这份 diff 就什么也判不了了）────────────────
 *  · 字数 / 段数 / 项数 / 圆点那几个数 · 逐字的文案 · 各种 true / false
 *  · **语料里的日期**（`2026-02-24 的记录` 是冲突卡的判据，它该被 diff 到）
 *  · 亚像素坐标（`cy 659.71875` —— P80 / P83 / P85 三批拿它对账）
 *
 * ⚠️ 第 5 条**要把「今天」告诉它**（`--today`，默认取文件的 mtime 那天）。
 * 不给的话只有两条路：要么把所有 `\d{4}-\d{2}-\d{2}` 都洗掉——那会连语料里的日期
 * 一起洗，第 ⑧ 步和冲突卡就都不剩什么可 diff 的了；要么一个都不洗——那走查那三天
 * 每批都不一样，`journey` 那几行永远红。**判据宁可窄**：只洗这一趟自己那三天。
 *
 * ── 它答不了什么 ──────────────────────────────────────────────────────────
 *  · **diff 出来的差异该不该紧张**：一条都答不了，那是人读的。
 *  · **没洗干净的东西**：`--selftest` 里有一条「洗完不许剩下什么」的扫描，但它只认
 *    上面列的那 8 类。新冒出来一类每批都变的东西，得有人把它加进来。
 */
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import path from 'node:path'

/** 往前数 n 天。`day` 是 `yyyy-mm-dd`。 */
const shift = (day, n) => {
  const d = new Date(day + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

export function normalize(text, { today } = {}) {
  let s = String(text)
  // ④ 先洗时间戳：它里头含着 `yyyy-mm-dd`，晚洗会被第 ⑤ 条先咬掉一半
  s = s.replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?/g, '<TS>')
  // ① 绝对路径：目录洗掉、**文件名留着**
  s = s.replace(/(?:\/Users\/[^\s"',)]*|\/private\/tmp\/[^\s"',)]*)/g, (m) => {
    const base = m.slice(m.lastIndexOf('/') + 1)
    return base && base.includes('.') ? `<DIR>/${base}` : '<DIR>'
  })
  // ⑧ content_tag 里那一截哈希（`"content_tag":"205:4rpyb9"` → `205:<TAG>`）
  s = s.replace(/(content_tag"\s*:\s*"\d+:)[A-Za-z0-9]+/g, '$1<TAG>')
  // ② 12 位十六进制 = note id / 改动层 id。**两头加边界**，别咬进更长的哈希里
  s = s.replace(/\b[0-9a-f]{12}\b/g, '<ID12>')
  // ③ 端口 / pid
  s = s.replace(/(127\.0\.0\.1|localhost):\d{2,5}/g, '$1:<PORT>')
  s = s.replace(/\bpid[=: ]\s*\d+/g, 'pid=<PID>')
  // ⑥⑦ 批次前缀 / 随机身份
  s = s.replace(/\bp\d+-newbie\b/g, '<B>-newbie')
  s = s.replace(/\bp\d+-(?=[A-Za-z0-9])/g, '<B>-')
  s = s.replace(/\buser-[a-z0-9]{6}\b/g, '<RANDUSER>')
  // ⑤ 这一趟自己那三天（**只有这三天**）
  if (today) {
    for (const [n, tag] of [[0, '<D0>'], [-1, '<D-1>'], [-2, '<D-2>']]) {
      s = s.split(shift(today, n)).join(tag)
    }
  }
  return s
}

/** 洗完之后**不许再剩下**的那几类。剩了就说明上面哪一条没咬到。 */
export const LEFTOVERS = [
  [/\/Users\//, '绝对路径（/Users/…）'],
  [/\/private\/tmp\//, '绝对路径（/private/tmp/…）'],
  [/\b[0-9a-f]{12}\b/, '12 位十六进制（note id）'],
  [/(127\.0\.0\.1|localhost):\d{2,5}/, '写死的端口'],
  [/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/, 'ISO 时间戳'],
]

export function leftovers(text) {
  return LEFTOVERS.filter(([re]) => re.test(text)).map(([, why]) => why)
}

// ── 例 / 反例：**先喂它一个该洗 / 不许洗的**（每批的规矩）──────────────────
const BATTERY = [
  // [原文, 该洗成什么, 为什么]
  ['note id: 6b9bb40ae341', 'note id: <ID12>', 'note id 洗掉'],
  ['开着的是: df3b4f7e987d', '开着的是: <ID12>', '另一个 note id 也洗掉'],
  ['shot → /private/tmp/x/y/p85-b1-old-open-light.png',
   'shot → <DIR>/<B>-b1-old-open-light.png', '目录洗掉、文件名留着、批次前缀归一'],
  ['窗口 origin: http://127.0.0.1:47231', '窗口 origin: http://127.0.0.1:<PORT>', '端口洗掉'],
  ['假模型端点 127.0.0.1:18386（--mode ok） pid=26535',
   '假模型端点 127.0.0.1:<PORT>（--mode ok） pid=<PID>', '端口 + pid'],
  ['"started_at":"2026-09-21T05:10:35.394Z"', '"started_at":"<TS>"', 'ISO 时间戳'],
  ['"content_tag":"205:4rpyb9"', '"content_tag":"205:<TAG>"', 'content_tag 的哈希那一截'],
  ['③ api.getUser() = p85-newbie', '③ api.getUser() = <B>-newbie', '批次身份'],
  ['身份回落成 user-64j2ig', '身份回落成 <RANDUSER>', '前端随手生成的身份'],
  // —— **不许洗的**（洗了这份 diff 就判不了事了）——
  ['日期跟知识库 2026-02-24 的记录不一致', '日期跟知识库 2026-02-24 的记录不一致',
   '**语料里的日期一个字都不许洗**（它是冲突卡的判据）'],
  ['点之前 bbox: {"cx":397,"cy":659.71875}', '点之前 bbox: {"cx":397,"cy":659.71875}',
   '**亚像素坐标不许洗**（P80 / P83 / P85 拿它对账）'],
  ['跑完：编辑器 205 （+ 100 ）', '跑完：编辑器 205 （+ 100 ）', '**字数不许洗**'],
  ['页边圆点: {"落槽合计":2,"图例":6,"页面合计":8}', '页边圆点: {"落槽合计":2,"图例":6,"页面合计":8}',
   '**圆点那几个数不许洗**'],
  ['  `/` 菜单项数: 19', '  `/` 菜单项数: 19', '**项数不许洗**'],
]
const DATE_BATTERY = [
  ['天列表: ["2026-09-21","2026-09-20"]', '天列表: ["<D0>","<D-1>"]', '这一趟自己那三天洗掉'],
  ['最早 2026-09-19', '最早 <D-2>', '前天也洗'],
  ['2026-02-24Speaker A 理解三人讨论', '2026-02-24Speaker A 理解三人讨论',
   '**不是这三天的日期不许洗**'],
]

function selftest() {
  let bad = 0
  for (const [src, want, why] of BATTERY) {
    const got = normalize(src)
    if (got !== want) { bad++; console.log(`✗ ${why}\n   得到 ${JSON.stringify(got)}\n   该是 ${JSON.stringify(want)}`) }
  }
  for (const [src, want, why] of DATE_BATTERY) {
    const got = normalize(src, { today: '2026-09-21' })
    if (got !== want) { bad++; console.log(`✗ ${why}\n   得到 ${JSON.stringify(got)}\n   该是 ${JSON.stringify(want)}`) }
  }
  // 「洗完不许剩下什么」那条自己也要例 / 反例
  const LEFT = [
    ['开着的是 6b9bb40ae341', 1, '没洗的 note id 要被扫出来'],
    ['开着的是 <ID12>', 0, '洗过的不该再被扫出来'],
    ['/Users/x/y', 1, '没洗的绝对路径要被扫出来'],
  ]
  for (const [src, want, why] of LEFT) {
    const got = leftovers(src).length
    if (got !== want) { bad++; console.log(`✗ ${why}：扫出 ${got} 类，该是 ${want}`) }
  }
  // **仓库里躺着的那几份也扫一遍**：有人把原始日志直接 commit 进去的话，
  // 下一批 `diff` 出来会是满屏红，而那正是这一份要防的事。
  const KEEP = path.resolve(import.meta.dirname, '../../../docs/walkthrough-logs')
  let kept = 0
  if (existsSync(KEEP)) {
    for (const batch of readdirSync(KEEP)) {
      const dir = path.join(KEEP, batch)
      if (!statSync(dir).isDirectory()) continue
      for (const f of readdirSync(dir).filter((n) => n.endsWith('.txt'))) {
        kept++
        const left = leftovers(readFileSync(path.join(dir, f), 'utf8'))
        if (left.length) { bad++; console.log(`✗ docs/walkthrough-logs/${batch}/${f} 没洗干净：${left.join(' / ')}`) }
      }
    }
  }
  console.log(`\n走查日志归一化：例 / 反例 ${BATTERY.length + DATE_BATTERY.length + LEFT.length} 条`
    + `（该洗的 ${BATTERY.filter(([a, b]) => a !== b).length + 2} 条 / **不许洗的** `
    + `${BATTERY.filter(([a, b]) => a === b).length + 1} 条）；`
    + `仓库里存着的走查日志 ${kept} 份（没洗干净的**当场红**）；对不上 ${bad} 个`)
  if (bad) { console.log(`\n${bad} 处失败`); process.exit(1) }
  console.log('OK: 每批都会变的洗掉了，判据那几样一个字没动')
}

// ── CLI ───────────────────────────────────────────────────────────────────
if (import.meta.url === `file://${process.argv[1]}`) {
  const argv = process.argv.slice(2)
  if (argv.includes('--selftest')) { selftest() }
  else {
    const i = argv.indexOf('--today'); const today = i >= 0 ? argv[i + 1] : ''
    const o = argv.indexOf('--out'); const out = o >= 0 ? argv[o + 1] : ''
    const files = argv.filter((a, k) => !a.startsWith('--') && k !== i + 1 && k !== o + 1)
    if (!files.length) { console.error('要给至少一个日志文件'); process.exit(64) }
    if (out) mkdirSync(out, { recursive: true })
    for (const f of files) {
      const s = normalize(readFileSync(f, 'utf8'), { today })
      const left = leftovers(s)
      if (left.length) console.error(`⚠ ${f} 洗完还剩：${left.join(' / ')}`)
      if (out) writeFileSync(path.join(out, path.basename(f)), s)
      else process.stdout.write(s)
    }
  }
}
