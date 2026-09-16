/** 每一个「跑得久的动作」都必须有可见反馈。
 *
 *     npx tsx scripts/check-busy.mts
 *
 * **为什么要有**：第 733 轮查出「做成幻灯片」实测跑 **20 秒**，而 `loading==='slides'`
 * 只被用来**禁菜单项**——点完之后界面是静的，用户不知道它在跑还是压根没接上。
 * 那次是靠人工把 `setLoading(...)` 列一遍才发现的；下一个新动作没人会再列一遍。
 *
 * 判据：`App.tsx` 里每一个 `setLoading('x')` 的 `x`，要么在 `BUSY_LABEL` 里
 * （composer 的忙碌条会显示一句话），要么在下面的**自带反馈**名单里。
 * 名单里每一条要写清楚它的反馈是什么——**写不出来就说明它没有**。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const src = readFileSync(resolve(import.meta.dirname, '../src/App.tsx'), 'utf8')

/** 自带反馈、不需要忙碌条的。**每条都要说清楚反馈长什么样。** */
const OWN_FEEDBACK: Record<string, string> = {
  'tap': '主钮当场变成红色的「停止」（.fb-btn.primary.running）',
  'note-harness': '同上，外加正文顶上一条 .harness-sticky 状态条报轮次',
  '': '空串 = 结束，不是一个状态',
}

const states = [...src.matchAll(/setLoading\('([a-z-]*)'\)/g)].map((m) => m[1])
if (states.length < 5) { console.error('没读到 setLoading(...)，闸门失效'); process.exit(1) }

const labelBlock = src.slice(src.indexOf('const BUSY_LABEL'), src.indexOf('}', src.indexOf('const BUSY_LABEL')))
const labelled = new Set([...labelBlock.matchAll(/^\s*([a-z-]+):/gm)].map((m) => m[1]))
if (labelled.size < 2) { console.error('没读到 BUSY_LABEL，闸门失效'); process.exit(1) }

let bad = 0
for (const st of [...new Set(states)]) {
  if (labelled.has(st) || st in OWN_FEEDBACK) continue
  bad++
  console.log(`✗ setLoading('${st}') 没有可见反馈 —— 加进 BUSY_LABEL（composer 会显示那句话），`
    + '或者加进 check-busy.mts 的 OWN_FEEDBACK 并写清楚它自己的反馈长什么样')
}
// 反向：BUSY_LABEL 里列了、却没人再 setLoading 的（动作删了、标签留着）
for (const l of labelled) {
  if (states.includes(l)) continue
  bad++
  console.log(`✗ BUSY_LABEL 里的 '${l}' 已经没有对应的 setLoading —— 删掉`)
}
if (bad) { console.error(`${bad} 处`); process.exit(1) }
console.log(`OK: ${new Set(states).size} 个 loading 状态都有可见反馈`)
