/** `/` 插入菜单的状态层自测。
 *
 *     npx tsx scripts/check-slash.mts
 *
 * 为什么要有：这套 UI 我做坏过两版，都是**构建通过、类型通过、东西不出现**
 * （靠 CSS 相邻选择器那版，被 CM6 插在 widget 两侧的 cm-widgetBuffer 破坏）。
 * tsc 和 vite build 拦不住这类错。CM6 的 tooltip 是 EditorState 上的 facet，
 * 不需要浏览器就能验：什么时候该弹、过滤对不对、上下键走到哪、什么时候该关。
 */
import { EditorState } from '@codemirror/state'
import { showTooltip } from '@codemirror/view'

import { SLASH_ITEMS, filtered, moveSlash, slashField, slashMenu } from '../src/editor/slashMenu.ts'

let bad = 0
const ok = (cond: unknown, msg: string) => {
  console.log(`${cond ? '✓' : '✗'} ${msg}`)
  if (!cond) bad++
}

const ext = slashMenu(() => {})
const mk = (doc: string) => EditorState.create({ doc, extensions: [ext] })
const menuShown = (st: EditorState) => st.facet(showTooltip).filter(Boolean).length === 1

/** 模拟"在 pos 处打一个字符" */
const type = (st: EditorState, ch: string) => {
  const at = st.selection.main.head
  return st.update({ changes: { from: at, insert: ch },
                     selection: { anchor: at + ch.length } }).state
}

// —— 该弹的时候 ——
let st = mk('').update({ selection: { anchor: 0 } }).state
st = type(st, '/')
ok(st.field(slashField) !== null, '行首打 / 唤起菜单')
ok(menuShown(st), '菜单出现在 tooltip 里')

st = mk('前面有字 ')
st = st.update({ selection: { anchor: st.doc.length } }).state
st = type(st, '/')
ok(st.field(slashField) !== null, '空格之后打 / 唤起菜单')

// —— 不该弹的时候 ——
let st2 = mk('A/B')
st2 = st2.update({ selection: { anchor: 1 } }).state
st2 = type(st2, '/')
ok(st2.field(slashField) === null, '「A/B 测试」这种不弹（前面不是空白）')

// —— 过滤 ——
ok(filtered('').length === SLASH_ITEMS.length, '没输入时列出全部功能')
ok(filtered('表格').every((i) => i.label.includes('表格') || i.hint.includes('表格')),
  '中文能过滤')
ok(filtered('eda').length >= 1 && filtered('eda')[0].key === 'eda', '英文 key 也能过滤')
ok(filtered('这个功能不存在').length === 0, '匹配不到时给空列表')

// 边打字边过滤
let st3 = mk('')
st3 = st3.update({ selection: { anchor: 0 } }).state
st3 = type(st3, '/')
for (const ch of '表格') st3 = type(st3, ch)
const s3 = st3.field(slashField)
ok(s3?.query === '表格', `过滤词跟着输入走（实际 ${JSON.stringify(s3?.query)}）`)
ok(filtered(s3!.query).length > 0 && menuShown(st3), '过滤后菜单还在')

// —— 上下键 ——
let st4 = mk('')
st4 = st4.update({ selection: { anchor: 0 } }).state
st4 = type(st4, '/')
st4 = st4.update({ effects: moveSlash.of(1) }).state
ok(st4.field(slashField)?.active === 1, '↓ 移到第二项')
st4 = st4.update({ effects: moveSlash.of(-1) }).state
ok(st4.field(slashField)?.active === 0, '↑ 回到第一项')
st4 = st4.update({ effects: moveSlash.of(-1) }).state
ok(st4.field(slashField)?.active === SLASH_ITEMS.length - 1, '在第一项按 ↑ 绕到最后一项')

// —— 该关的时候 ——
let st5 = mk('')
st5 = st5.update({ selection: { anchor: 0 } }).state
st5 = type(st5, '/')
st5 = st5.update({ selection: { anchor: 0 } }).state          // 光标退到 / 前面
ok(st5.field(slashField) === null, '光标退到 / 前面就关掉')

let st6 = mk('')
st6 = st6.update({ selection: { anchor: 0 } }).state
st6 = type(st6, '/')
for (const ch of ' 随便写的一句话') st6 = type(st6, ch)
ok(st6.field(slashField) === null, '打了空格又匹配不上任何功能就关掉（普通斜杠）')

// —— 每一项都得有必要字段 ——
for (const it of SLASH_ITEMS) {
  ok(!!(it.key && it.label && it.hint && it.icon), `「${it.label}」字段完整`)
}
const modes = new Set(['prompt', 'chart', 'table', 'eda', 'analysis'])
const aiItems = SLASH_ITEMS.filter((i) => modes.has(i.key))
ok(aiItems.length === 5, `五个 AI 功能都在菜单里（实际 ${aiItems.length}）`)

console.log(bad ? `\n✗ ${bad} 项没通过` : '\n状态层：通过')
if (bad) process.exit(1)
