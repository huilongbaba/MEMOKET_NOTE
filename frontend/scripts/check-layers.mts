/** 提案层的开关不变量（agent-native-editor §3.2「关掉再打开」）：
 *  关掉 = 正文精确回到这层之前；再打开 = 正文精确回到这层之后；两层交错开关也成立；
 *  关着时用户改了原文，那处重放不了要报 lost 而不是写错位置。
 *
 *     npx tsx scripts/check-layers.mts
 */
import { EditorState, type TransactionSpec } from '@codemirror/state'
import { addLayer, diffParts, dropLayer, layersOf, roundDiff, turnLayerOff, turnLayerOn } from '../src/editor/roundDiff.ts'
import { minimalChange } from '../src/editor/minimalChange.ts'

class Host {
  state: EditorState
  constructor(doc: string) { this.state = EditorState.create({ doc, extensions: [roundDiff] }) }
  dispatch(spec: TransactionSpec) { this.state = this.state.update(spec).state }
  get doc() { return this.state.doc.toString() }
  /** 像 App.pushDiff 一样：正文按最小改动换成 after（MarkdownEditor 就是这么应用外部内容的），再按 diff 加一层 */
  push(label: string, after: string) {
    const before = this.doc
    const change = minimalChange(before, after)
    if (change) this.state = this.state.update({ changes: change }).state
    this.dispatch({ effects: addLayer.of({ label, parts: diffParts(before, after) }) })
  }
}

let bad = 0
const eq = (name: string, got: string, want: string) => {
  if (got !== want) { bad++; console.log(`✗ ${name}\n   期望 ${JSON.stringify(want)}\n   得到 ${JSON.stringify(got)}`) }
  else console.log(`✓ ${name}`)
}

// 1. 一层：关掉回到之前，打开回到之后，反复三次
{
  const v0 = '三月上旬启动众筹。排期要倒推。'
  const v1 = '四月中旬启动众筹。排期要倒推，而且要留缓冲。'
  const h = new Host(v0)
  h.push('润色', v1)
  const [L] = layersOf(h)
  for (let i = 0; i < 3; i++) {
    turnLayerOff(h, L.id); eq(`关掉 #${i}`, h.doc, v0)
    eq(`关掉后 off=true #${i}`, String(layersOf(h)[0].off), 'true')
    const r = turnLayerOn(h, L.id); eq(`打开 #${i}`, h.doc, v1)
    eq(`打开全部重放 #${i}`, `${r.replayed}/${r.lost}`, `${r.replayed}/0`)
  }
}

// 2. 两层：关 A 保留 B，再关 B，再开 A，再开 B
{
  const v0 = '甲乙丙丁戊己庚辛壬癸子丑寅卯。'
  const v1 = '甲XX丁戊己庚辛壬癸子丑寅卯。'          // A：开头改
  const v2 = '甲XX丁戊己庚辛壬癸子丑寅YY。'          // B：结尾改
  const h = new Host(v0)
  h.push('A', v1); h.push('B', v2)
  const [A, B] = layersOf(h)
  turnLayerOff(h, A.id); eq('关 A 只剩 B 的改动', h.doc, '甲乙丙丁戊己庚辛壬癸子丑寅YY。')
  turnLayerOff(h, B.id); eq('再关 B 回到原文', h.doc, v0)
  turnLayerOn(h, A.id); eq('开 A', h.doc, v1)
  turnLayerOn(h, B.id); eq('开 B', h.doc, v2)
  dropLayer(h, A.id); eq('撤回 A（B 还在）', h.doc, '甲乙丙丁戊己庚辛壬癸子丑寅YY。')
  eq('A 撤回后只剩一层', String(layersOf(h).length), '1')
}

// 3. 关着时用户改了那处原文 → 打开时 lost，另一处照常重放，且不写错位置
{
  const v0 = '第一句原文。中间隔着很多没有变化的文字在这里。第二句原文。'
  const v1 = '第一句改过。中间隔着很多没有变化的文字在这里。第二句改过。'
  const h = new Host(v0)
  h.push('改', v1)
  const [L] = layersOf(h)
  turnLayerOff(h, L.id); eq('关掉', h.doc, v0)
  h.dispatch({ changes: { from: 3, to: 5, insert: '原稿' } })       // 用户改了第一处的原文（那处是「原文」两个字）
  const r = turnLayerOn(h, L.id)
  eq('一处丢、一处重放', `${r.replayed}/${r.lost}`, '1/1')
  eq('重放不写错位置', h.doc, '第一句原稿。中间隔着很多没有变化的文字在这里。第二句改过。')
}

// 4. 关着时用户在别处打字：位置跟着映射，打开仍精确
{
  const v0 = '开头。中间原文。结尾。'
  const v1 = '开头。中间改过了。结尾。'
  const h = new Host(v0)
  h.push('改', v1)
  const [L] = layersOf(h)
  turnLayerOff(h, L.id)
  h.dispatch({ changes: { from: 0, insert: '新加的开头，' } })
  const r = turnLayerOn(h, L.id)
  eq('别处打字后打开', h.doc, '新加的开头，开头。中间改过了。结尾。')
  eq('无丢失', `${r.lost}`, '0')
}

// 5. 随机 fuzz：关掉 / 打开各 200 次要精确
{
  const ALPHA = '甲乙丙丁戊abc \n。'
  const rnd = (n: number) => Math.floor(Math.random() * n)
  const gen = (len: number) => Array.from({ length: len }, () => ALPHA[rnd(ALPHA.length)]).join('')
  let fuzzBad = 0
  for (let i = 0; i < 200; i++) {
    const v0 = gen(rnd(40))
    let v1 = v0
    for (let k = 0, ops = 1 + rnd(3); k < ops; k++) {
      const at = rnd(v1.length + 1)
      v1 = rnd(2) ? v1.slice(0, at) + gen(1 + rnd(5)) + v1.slice(at) : v1.slice(0, at) + v1.slice(at + rnd(4))
    }
    const h = new Host(v0)
    h.push('f', v1)
    const L = layersOf(h)[0]
    if (!L) { if (v0 !== v1 && h.doc !== v1) fuzzBad++; continue }
    turnLayerOff(h, L.id); if (h.doc !== v0) { fuzzBad++; console.log('关掉不对', JSON.stringify([v0, v1, h.doc])); continue }
    turnLayerOn(h, L.id); if (h.doc !== v1) { fuzzBad++; console.log('打开不对', JSON.stringify([v0, v1, h.doc])) }
  }
  eq('fuzz 200 例', String(fuzzBad), '0')
}

if (bad) { console.log(`\n${bad} 处失败`); process.exit(1) }
console.log('\ncheck-layers OK')

// 6. 探针场景：A 层改了中间，用户 / 探针在末尾追加一段并作为 B 层，关掉 A 之后 B 还在
{
  const v0 = '开头。\n\n中间原文。\n\n结尾。'
  const v1 = '开头。\n\n中间改过了。\n\n结尾。'
  const h = new Host(v0)
  h.push('A', v1)
  h.dispatch({ changes: { from: h.state.doc.length, insert: '\n\n探针塞进来的一段。\n' } })
  const v2 = h.doc
  h.dispatch({ effects: addLayer.of({ label: 'B', parts: diffParts(v1, v2) }) })
  eq('两层都在', String(layersOf(h).length), '2')
  const [A] = layersOf(h)
  turnLayerOff(h, A.id)
  eq('关 A 后 B 还在', layersOf(h).map((l) => `${l.label}:${l.off ? 'off' : 'on'}`).join(','), 'A:off,B:on')
  eq('关 A 后正文', h.doc, v0 + '\n\n探针塞进来的一段。\n')
}
if (bad) process.exit(1)
