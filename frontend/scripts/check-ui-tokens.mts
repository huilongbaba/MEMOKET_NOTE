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
  })
}
const stale = Object.keys(ALLOW).filter((f) => { try { statSync(join(root, f)); return false } catch { return true } })
for (const f of stale) { bad++; console.log(`✗ 白名单里的 ${f} 已经不存在了，从名单去掉`) }
if (bad) { console.error(`${bad} 处`); process.exit(1) }
console.log('OK: 颜色只写在令牌文件里')
