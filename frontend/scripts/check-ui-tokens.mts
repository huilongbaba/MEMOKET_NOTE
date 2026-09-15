/** 颜色只能写在令牌文件里。规范见 docs/UI_SPEC.md §3.1 / §5.2。
 *
 *     npx tsx scripts/check-ui-tokens.mts
 *
 * **规范不上闸门就是许愿。** 第 675 轮那条「输入框要有名字」是靠 check-a11y 才
 * 守得住的；这条同理——换肤只做一次，而散在各处的字面颜色会让下一次换肤重新
 * 变成考古。扫 src 下的 .css / .ts / .tsx：除令牌文件外出现字面颜色就失败。
 *
 * 白名单里每一条都要写清楚理由；理由站不住就该改代码，不是加名单。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const root = resolve(import.meta.dirname, '../src')
const walk = (d: string, out: string[] = []) => {
  for (const f of readdirSync(d)) {
    const p = join(d, f)
    if (statSync(p).isDirectory()) { if (!p.includes('__tests__')) walk(p, out) } else out.push(p)
  }
  return out
}

/** 允许写字面颜色的文件，以及为什么。 */
const ALLOW: Record<string, string> = {
  'design-tokens.css': '令牌本身就住在这儿——这是唯一的源',
  'shell.css': '分类色 --jn-1..8 是一套过了色盲校验的调色板，换成品牌色系会毁掉可分辨性（UI_SPEC §1.2）',
  'util/slideHtml.ts': '生成的是**独立的**导出 HTML / PDF，脱离这个应用跑，拿不到 :root 上的令牌',
  'probes.ts': '截图探针里画一张测试用的 canvas 图，不是界面',
}

/** 就地允许的几处，以及为什么。 */
const INLINE_OK: RegExp[] = [
  /#fff\b|#ffffff\b/i,          // 品牌底上的白字：跟着 --brand 走，不是一个独立的颜色决策
  /transparent|currentColor|inherit|none/i,
]

const HEX = /#[0-9a-fA-F]{3,8}\b/g
const FUNC = /\b(?:rgba?|hsla?)\s*\(/g
/* **UI 不止是颜色**（用户第 680 轮原话）。字号、字重、圆角同样是视觉身份的一部分，
   同样会随手写死、随手漂移。量过：圆角原来写死 6px(27 处) / 8px(17) / 10px(13)，
   字号写死 12px(41) / 13px(34) / 11px(29) 外加 226 处内联 fontSize，字重几乎全是
   默认 400（源仓库 600 用了 123 处）。所以这三样一起上闸门。 */
/* border-radius 要连**多值**一起查。第一版只匹配 `border-radius: 9px`，于是
   `border-radius: var(--r-sm) 6px 0 0` 里的那个 6px 一直活着（第 683 轮在
   `.pane-tab` 上抓到）——**只查一半的闸门给的是假安全感**。 */
const SHAPE = /(?:border-radius:[^;}]*?\b[0-9.]+px|font-size: *[0-9.]+px|font-weight: *[0-9]{3}\b|fontSize: *[0-9]+\b|borderRadius: *[0-9]+\b|fontWeight: *[0-9]{3}\b|gap: *[0-9]+px|z-index: *[0-9]+|letter-spacing: *[-0-9.]+em)/g

let bad = 0
for (const f of walk(root)) {
  if (!/\.(css|tsx?)$/.test(f)) continue
  const rel = f.replace(root + '/', '')
  if (ALLOW[rel]) continue
  // 注释要**按行等长地抹掉**，不能直接删：删了行号就偏，报出来的位置是错的
  // （第一版就是这样，指到了一条注释的中间）。
  const blank = (m: string) => m.replace(/[^\n]/g, ' ')
  const src = readFileSync(f, 'utf8')
    .replace(/\/\*[^]*?\*\//g, blank)
    .replace(/(^|[^:])\/\/.*$/gm, (m, p1) => p1 + blank(m.slice(p1.length)))
  const lines = src.split('\n')
  lines.forEach((line, i) => {
    // 颜色以外的 # 用法（锚点、id 选择器、模板串）不算：只看形如 #abc / #aabbcc 的
    for (const m of [...line.matchAll(HEX), ...line.matchAll(FUNC)]) {
      const hit = m[0]
      if (INLINE_OK.some((re) => re.test(hit))) continue
      bad++
      console.log(`✗ ${rel}:${i + 1} 写了字面颜色 ${hit.trim()} —— 用令牌（docs/UI_SPEC.md §1）：${line.trim().slice(0, 90)}`)
    }
    for (const m of line.matchAll(SHAPE)) {
      bad++
      console.log(`✗ ${rel}:${i + 1} 写死了尺度值（字号/字重/圆角/间距/层级）：${m[0].trim()} —— 用尺度令牌（docs/UI_SPEC.md §1.5）：${line.trim().slice(0, 80)}`)
    }
  })
}
const stale = Object.keys(ALLOW).filter((f) => { try { statSync(join(root, f)); return false } catch { return true } })
for (const f of stale) { bad++; console.log(`✗ 白名单里的 ${f} 已经不存在了，从名单去掉`) }
if (bad) { console.error(`${bad} 处`); process.exit(1) }
console.log('OK: 颜色 / 字号 / 字重 / 圆角 / 间距 / 层级都走令牌')

/* 死令牌跟死样式一样要清。第 683 轮把快速搜索框改成跟输入框同一套之后，
   `--quick-search-bg` / `--quick-search-hover-bg` / `--right-pane-heading`
   三个立刻没人用了——**定义了没人用的令牌会让下一个人以为它是活的**。 */
{
  const cssAll = walk(root).filter((f) => f.endsWith('.css'))
    .map((f) => readFileSync(f, 'utf8')).join('\n')
  const defined = [...cssAll.matchAll(/^\s*(--[a-z0-9-]+):/gm)].map((m) => m[1])
  const allSrc = walk(root).filter((f) => /\.(css|tsx?)$/.test(f))
    .map((f) => readFileSync(f, 'utf8')).join('\n')
  // 运行时由 JS 写进 style 的（TabBar 的 --tab-w）用 setProperty 出现，一样算用了
  /* 代码里拼出来的令牌名：`var(--jn-${i + 1})`（屏幕活动的八个分类色）。
     按前缀放过——跟 check-css-classes 的 DYNAMIC_PREFIX 一个道理。
     名单里每条要写清楚是谁拼的，前缀失效了这条也要跟着删。 */
  const DYNAMIC = [
    { prefix: '--jn-', why: 'JourneyPage.tsx:29 `var(--jn-${i + 1})` 拼出 8 个分类色' },
  ]
  const dead = [...new Set(defined)].filter((v) => {
    if (DYNAMIC.some((d) => v.startsWith(d.prefix) && allSrc.includes('var(' + d.prefix + '$'))) return false
    const uses = allSrc.split(`var(${v}`).length - 1 + allSrc.split(`'${v}'`).length - 1
    return uses === 0
  })
  for (const d of DYNAMIC) {
    if (!allSrc.includes('var(' + d.prefix + '$')) {
      bad++; console.log(`✗ 动态名单里的 ${d.prefix} 已经没人拼了（${d.why}），从名单去掉`)
    }
  }
  for (const v of dead) { bad++; console.log(`✗ 令牌 ${v} 定义了没人用 —— 删掉，或者说明为什么留着`) }
}
if (bad) { console.error(`${bad} 处`); process.exit(1) }
console.log('OK: 没有死令牌')
