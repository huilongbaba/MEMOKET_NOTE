/** roundDiff 的核心不变量：**任意组合撤回，都要精确还原成改动前的原文**。
 *
 *     npx tsx scripts/check-hunks.mts
 *
 * 为什么单独写个脚本而不是塞进单测：前端这边没有测试框架，而这条不变量又
 * 是「接受/撤回」整套交互的地基——撤回还原不出原文，用户点一下就丢内容。
 * 固定用例覆盖已知形态，后面的随机 fuzz 覆盖边界（相邻改动、只差一个字、
 * 换行处的改动），那才是真正会坏的地方。
 */
import { diffParts, toHunks } from '../src/editor/roundDiff.ts'

function restore(after: string, hunks: ReturnType<typeof toHunks>): string {
  // 必须**从后往前**：每撤一处都会改变长度，从前往后的话后面全部错位。
  let s = after
  for (const h of [...hunks].sort((a, b) => b.from - a.from)) {
    s = s.slice(0, h.from) + h.del + s.slice(h.to)
  }
  return s
}

let bad = 0
const check = (name: string, before: string, after: string, quiet = false) => {
  const hs = toHunks(diffParts(before, after))
  const got = restore(after, hs)
  if (got !== before) {
    bad++
    console.log(`✗ ${name}\n   期望 ${JSON.stringify(before)}\n   得到 ${JSON.stringify(got)}`)
  } else if (!quiet) {
    console.log(`✓ ${name}: ${hs.length} 处`)
  }
  return hs
}

const CASES: [string, string, string][] = [
  ['纯新增', '三月上旬启动。', '三月上旬启动。排期要倒推。'],
  ['纯删除', '三月上旬启动。排期要倒推。', '三月上旬启动。'],
  ['近处替换（应并成一处）', '三月上旬启动众筹。', '四月中旬启动众筹。'],
  ['远处两改（应保持两处）', '甲乙丙丁戊己庚辛壬癸子丑寅卯。', '甲XX丁戊己庚辛壬癸子丑寅YY。'],
  ['整段重写', '原来的一整段话在这里。', '完全不同的另一段内容写在这里面。'],
  ['多段落新增', '## 标题\n\n第一段。', '## 标题\n\n第一段。\n\n新增的第二段在这里。'],
  ['开头改', 'abc 后面不动。', 'xyz 后面不动。'],
  ['结尾改', '前面不动 abc', '前面不动 xyz'],
  ['清空', '有内容。', ''],
  ['从空写起', '', '新写的内容。'],
  ['完全没变', '一模一样。', '一模一样。'],
]
for (const [n, b, a] of CASES) check(n, b, a)

// ---- 随机 fuzz：真正会坏的是边界，固定用例覆盖不到 ----
const ALPHA = '甲乙丙丁戊abc \n。'
const rnd = (n: number) => Math.floor(Math.random() * n)
const gen = (len: number) => Array.from({ length: len }, () => ALPHA[rnd(ALPHA.length)]).join('')
let fuzzBad = 0
for (let i = 0; i < 2000; i++) {
  const before = gen(rnd(40))
  // 在 before 上随机做几次编辑得到 after，比纯随机两串更接近真实改动形态
  let after = before
  for (let k = 0, ops = 1 + rnd(3); k < ops; k++) {
    const at = rnd(after.length + 1)
    after = rnd(2)
      ? after.slice(0, at) + gen(1 + rnd(5)) + after.slice(at)
      : after.slice(0, at) + after.slice(at + rnd(5))
  }
  const hs = toHunks(diffParts(before, after))
  if (restore(after, hs) !== before) {
    fuzzBad++
    if (fuzzBad <= 3) {
      console.log(`✗ fuzz #${i}\n   before ${JSON.stringify(before)}\n   after  ${JSON.stringify(after)}`
        + `\n   还原   ${JSON.stringify(restore(after, hs))}`)
    }
  }
}
console.log(fuzzBad ? `✗ 随机 2000 例中 ${fuzzBad} 例还原失败` : '✓ 随机 2000 例全部精确还原')

if (bad || fuzzBad) process.exit(1)
console.log('\n撤回可逆性：通过')
