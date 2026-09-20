/** toast 那一摞的两条源码闸（P62）。
 *
 *     npx tsx scripts/check-toast-single.mts
 *
 * P58 / P60 两批的走查日志里，两条 toast 各出现两遍（`已切换到本地模型…` ×2、
 * `没删成 2026-09-19…` ×2），两批都记成「同一条 toast 连出两遍，下一批去修」。
 * **根因在量具**：那两批读的是 `[class*="toast"]`，而外层容器叫 `toaster`——
 * 这个串里含 `toast`，通配把容器和里面那一条**一起**选中了，容器的 `textContent`
 * 又正好等于里面那一条，于是一条读成两条。实拍截图 `p60-b7-2-ro-toast-light.png`
 * 上**只有一个 toast 框**。**「选不到 ≠ 没有」的镜像：「选到两个 ≠ 真有两个」。**
 *
 * 行为那一侧的闸在 `src/editor/__tests__/p62Toast.test.tsx`。这一份钉源码里的两条：
 *
 *  ① **`<Toaster/>` 全仓只许挂一处。** 挂两处就真的会出两遍——这条路排除掉，
 *     下一次再看见「两遍」才能一口咬定是读法问题。
 *  ② **toast 存储里不许按 message 去重。** 「同一条消息短时间内只留一条」听着像修，
 *     实际会**吞掉用户真的连点两次的反馈**（删两次失败两次，用户只看见一条）。
 *     根因既然不在产品，就一个字都别改产品。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const src = resolve(import.meta.dirname, '..', 'src')
let bad = 0
const fail = (msg: string) => { bad++; console.log('✗ ' + msg) }

function walk(dir: string, out: string[] = []): string[] {
  for (const n of readdirSync(dir)) {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.tsx?$/.test(n)) out.push(p)
  }
  return out
}

/** **注释里写的不算挂载。** `toast.ts` 的抬头里就有一句
 *  「`<Toaster/>` 是唯一会因为 toast 变化而重渲染的东西」——不去掉注释，
 *  这条闸会把那句说明数成第二处挂载。**这跟它要防的是同一类毛病：
 *  匹配到了文字，不等于匹配到了那件事。** */
const strip = (s: string) => s
  .replace(/\/\*[\s\S]*?\*\//g, ' ')
  .replace(/^[ \t]*\/\/.*$/gm, ' ')
  .replace(/([^:])\/\/.*$/gm, '$1')

// ① <Toaster/> 挂了几处（测试文件不算——它们自己造容器）
const mounts: string[] = []
for (const f of walk(src)) {
  if (/__tests__/.test(f)) continue
  const hits = (strip(readFileSync(f, 'utf8')).match(/<Toaster\s*\/>/g) ?? []).length
  for (let i = 0; i < hits; i++) mounts.push(f.replace(src + '/', ''))
}
if (mounts.length !== 1) {
  fail(`<Toaster/> 挂了 ${mounts.length} 处（${mounts.join(', ')}）——只许一处。`
    + '挂两处的话每条 toast 真的会出两遍，而那正是 P58 / P60 两批误判的那个样子。')
}

// ② toast 存储里不许按 message 去重
const store = strip(readFileSync(join(src, "toast.ts"), "utf8"))
// **别用 `[^)]*`**：`toasts.some((t) => t.message === message)` 里第一个 `)` 是
// 箭头函数自己的形参括号，`[^)]*` 在那儿就停了，于是这条闸对着真正的去重写法
// **一声不响地放行**。突变刀 ⑤ 当场抓到的——*一条永远绿的闸不是闸*。
// 现在按「`.some(` / `.find(` / `.filter(` 之后 60 个字符内出现 `message`」认。
const dedupe = [
  /\.some\s*\((?:.|\n){0,60}?message/,
  /\.find\s*\((?:.|\n){0,60}?message/,
  /\.filter\s*\((?:.|\n){0,60}?message\s*===/,
]
for (const re of dedupe) {
  if (re.test(store)) {
    fail(`toast.ts 里出现了按 message 查重的写法（${re}）——`
      + '「同一条消息短时间内只留一条」会吞掉用户真的连点两次的反馈。'
      + '那两遍是量具选择器多选的，不是派发了两次，产品这一侧一个字都不该改。')
  }
}
// 容器那一行确实还叫 `toaster`（改名了这条闸和量具的注释都得跟着改）
if (!/className="toaster"/.test(readFileSync(join(src, 'components/Toaster.tsx'), 'utf8'))) {
  fail('Toaster.tsx 里找不到 `className="toaster"`——容器改名了，'
    + '量具 `d.toasts()` 的 `.toaster > .toast` 和这条闸都得跟着改')
}

if (bad) { console.error(`check-toast-single：${bad} 处`); process.exit(1) }
console.log(`check-toast-single ✓ <Toaster/> 只挂 1 处（${mounts[0]}）· toast.ts 没有按 message 的去重`)
