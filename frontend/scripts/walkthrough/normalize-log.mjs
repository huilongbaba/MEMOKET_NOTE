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
  // ④b **被日志自己截断的那半截时间戳**（P87 留的第 ③ 条，P89 B 判了：**洗**）。
  //
  // 日志把 `/api/health` 的回包 `slice` 掉了尾巴，于是上面那条完整 ISO 咬不到它，
  // 行尾剩下一个 `"started_at":"2026-09`。P87 判「宁可窄」留着，理由是
  // **放宽到「年-月」会咬语料里的日期**。那个理由对的是「放宽 ISO 那条通则」，
  // 而这一处根本不需要通则：它有自己的键。所以这一条**两头都钉死**——
  // 左边必须紧挨着 `"started_at":"`、右边必须是**行尾**（截断才会这样）。
  // 语料里的日期两个条件一个都够不着。
  //
  // **为什么非洗不可**：这半截里带着「年-月」。它不是每批都变，是**每个月变一次**——
  // 一条平时安静、跨月那一批突然红一行的噪声，恰恰是最难读的那种：
  // 那一批的人会拿它当真差异查半天。**安静不等于洗干净了。**
  //
  // ⚠️ **断在哪一位是随机的**（P89 当场栽过一次）：第一版写的是 `\d{4}-\d{2}(-\d{2})?(T…)?`，
  // 按 P87 日志里那一处（`…"started_at":"2026-09`）抄的。而这一趟实得
  // `…"started_at":"20` —— 截断的位置跟着 `data_dir` **那条绝对路径的长度**走，
  // 这一批的 scratch 路径比 P87 长几个字符，`slice` 就在更靠前的地方切。
  // **「我见过的那个样子」不是「它的样子」**。所以右边只要「数字开头、一路到行尾」。
  s = s.replace(/("started_at"\s*:\s*")\d[\d:.T-]*$/gm, '$1<TS')
  // ⑧ content_tag 里那一截哈希（`"content_tag":"205:4rpyb9"` → `205:<TAG>`）
  s = s.replace(/(content_tag"\s*:\s*"\d+:)[A-Za-z0-9]+/g, '$1<TAG>')
  // ② 12 位十六进制 = note id / 改动层 id。**两头加边界**，别咬进更长的哈希里
  s = s.replace(/\b[0-9a-f]{12}\b/g, '<ID12>')
  // ③ 端口 / pid
  s = s.replace(/(127\.0\.0\.1|localhost):\d{2,5}/g, '$1:<PORT>')
  // ⚠️ **JSON 里那一格单独一条**（P87 A 逐行 diff 实拍出来的洞）：
  // 下面那条要求 `pid` 后面**紧挨着** `=` / `:` / 空格，而 `/api/health` 回的是
  // `{"status":"ok","backend":{"pid":26273,…}}` —— `pid` 和 `:` 中间隔着一个引号，
  // 于是 `05-old-whoami52.txt` 里那个 pid **一批都没洗掉**，p85 ↔ p87 的 diff 上
  // 它是唯一一条纯噪声。**「有一条规则在管这类东西」不等于「这一处被管到了」。**
  s = s.replace(/"pid"\s*:\s*\d+/g, '"pid":<PID>')
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
  // P87 A：**扫描这一侧原来也没有 pid 这一条**——洗的规则漏了一处，
  // 而「洗完不许剩下什么」也没看着它，于是两头一起瞎了一整批。
  [/\bpid"?\s*[=: ]\s*\d+/, '没洗的 pid'],
  [/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/, 'ISO 时间戳'],
  // P89 B：**扫描这一侧也得有它**（P87 A 那一课：洗的一侧漏了、扫的一侧也没有，两头一起瞎）。
  // 只认「`started_at` 的值还是个数字开头、而且行到这儿就断了」这一格。
  [/"started_at"\s*:\s*"\d/m, '没洗的半截时间戳（`"started_at":"2026-09`）'],
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
  // —— P87 A 那个洞的正反例（**引号隔在中间的那一格**）——
  ['  /api/health: {"status":"ok","backend":{"pid":26273,"data_dir":"<DIR>"',
   '  /api/health: {"status":"ok","backend":{"pid":<PID>,"data_dir":"<DIR>"',
   '**JSON 里的 pid**（`pid` 和 `:` 中间隔着引号）—— P87 逐行 diff 抓出来的洞'],
  ['{"pid": 26273}', '{"pid":<PID>}', 'JSON 里冒号后有空格的也洗'],
  ['壳关掉了（pid 59267，SIGTERM 自己退的）', '壳关掉了（pid=<PID>，SIGTERM 自己退的）',
   '中文括号里那种写法照旧洗得掉（老规则没被新规则挤掉）'],
  // —— **不许洗的**：名字里带 pid 的别的东西 ——
  ['  rapid 3 次', '  rapid 3 次', '**`rapid` 不是 `pid`**（`\\b` 边界守着）'],
  ['"started_at":"2026-09-21T05:10:35.394Z"', '"started_at":"<TS>"', 'ISO 时间戳'],
  // —— P89 B：**被日志截断的那半截时间戳**（P87 留的第 ③ 条）——
  ['  /api/health: {"status":"ok","backend":{"pid":<PID>,"started_at":"2026-09',
   '  /api/health: {"status":"ok","backend":{"pid":<PID>,"started_at":"<TS',
   '**行尾那半截时间戳**（P87 判「宁可窄」留着的那一处，P89 判「洗」）'],
  ['{"started_at":"2026-09-21T05:10', '{"started_at":"<TS',
   '截在别处的半截（`T` 之后断掉）照样洗'],
  ['  /api/health: {"data_dir":"<DIR>","started_at":"20',
   '  /api/health: {"data_dir":"<DIR>","started_at":"<TS',
   '**断在第 2 位那一格**（P89 实拍：截断点跟着 `data_dir` 那条路径的长度走，不是固定在「年-月」）'],
  ['{"started_at":"2', '{"started_at":"<TS', '只剩一位数字也洗'],
  // —— **不许洗的**：这条规则两头都钉死，语料里的日期一个都够不着 ——
  ['日期跟知识库 2026-02-24 的记录不一致，2026-09 那条也对不上',
   '日期跟知识库 2026-02-24 的记录不一致，2026-09 那条也对不上',
   '**没有 `started_at` 这个键就一个字不洗**（左边那头钉着）'],
  ['"started_at":"2026-09-21","tail":1', '"started_at":"2026-09-21","tail":1',
   '**后面还有字就不是被截断的**，不洗（右边那头钉着行尾）；'
   + '真出现这一格由「洗完不许剩下什么」那一侧喊出来，**不是悄悄放过**'],
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
    ['{"pid":26273}', 1, '**JSON 里没洗的 pid 也要被扫出来**（P87 A 那个洞的另一半）'],
    ['{"pid":<PID>}', 0, '洗过的 pid 不该再被扫出来'],
    ['rapid 3 次', 0, '**`rapid` 不算**——扫描这一侧也不许把它当 pid'],
    ['{"started_at":"2026-09', 1, '**没洗的半截时间戳要被扫出来**（P89 B）'],
    ['{"started_at":"<TS', 0, '洗过的半截不该再被扫出来'],
    ['{"started_at":"2026-09-21","tail":1', 1,
     '**洗不到的那一格也要被扫出来**——「规则够不着」和「这儿没问题」不是一回事'],
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
