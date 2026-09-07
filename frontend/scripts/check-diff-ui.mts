/** 「接受 / 撤回」这套交互的状态层自测。
 *
 *     npx tsx scripts/check-diff-ui.mts
 *
 * 为什么要有：这套 UI 我连着做坏了两版，都是**构建通过、类型通过、按钮不出现**
 * ——第一版靠 CSS 相邻选择器，而 CM6 会在 widget 两侧插 cm-widgetBuffer，选择器
 * 永远匹配不上。这类错 tsc 和 vite build 都拦不住。
 *
 * CM6 的 tooltip 是 EditorState 上的 facet，不需要浏览器就能验：悬停到某一处时
 * facet 里到底有没有出现工具条、位置对不对、接受/撤回之后状态怎么变。
 */
import { EditorState } from '@codemirror/state'
import { showTooltip } from '@codemirror/view'

import {
  acceptAllHunks, acceptHunk, diffParts, dropHunk, roundDiff, roundDiffField,
  setHover, setRoundDiff,
} from '../src/editor/roundDiff.ts'

let bad = 0
const ok = (cond: unknown, msg: string) => {
  console.log(`${cond ? '✓' : '✗'} ${msg}`)
  if (!cond) bad++
}

const BEFORE = '三月上旬启动众筹。排期要往前倒推。'
const AFTER = '四月中旬启动众筹。排期要往前倒推。还要留出测试和修复的时间。'

const mk = (doc: string) => EditorState.create({ doc, extensions: [roundDiff] })
let state = mk(AFTER)
state = state.update({ effects: setRoundDiff.of(diffParts(BEFORE, AFTER)) }).state

const hunks = state.field(roundDiffField).hunks
ok(hunks.length === 2, `切出 2 处改动（实际 ${hunks.length}）`)
ok(state.facet(showTooltip).filter(Boolean).length === 0, '没悬停时不显示工具条')

// —— 悬停：facet 里应该出现工具条，且锚在这一处上 ——
// setHover 没导出（内部用），这里通过 mousemove 之外的唯一入口验证：
// 直接构造一个带 hover 的状态需要拿到 effect，所以从模块里按名字取。
{
  const hovered = state.update({ effects: setHover.of(hunks[0].id) }).state
  const tips = hovered.facet(showTooltip).filter(Boolean)
  ok(tips.length === 1, `悬停第一处时出现 1 个工具条（实际 ${tips.length}）`)
  ok(tips[0] && tips[0].pos === hunks[0].from, '工具条锚在这一处的起点')
  ok(tips[0]?.above === true, '工具条显示在改动上方')

  const accepted = hovered.update({ effects: acceptHunk.of(hunks[0].id) }).state
  ok(accepted.field(roundDiffField).hunks.length === 1, '接受后这一处从列表里消失')
  ok(accepted.facet(showTooltip).filter(Boolean).length === 0, '接受后工具条跟着消失')
  ok(accepted.doc.toString() === AFTER, '接受不改动正文')
}

// —— 撤回：正文要变回改之前 ——
const h0 = hunks[0]
const rejected = state.update({
  changes: { from: h0.from, to: h0.to, insert: h0.del },
  effects: dropHunk.of(h0.id),
}).state
ok(rejected.doc.toString() === '三月上旬启动众筹。排期要往前倒推。还要留出测试和修复的时间。',
  '撤回第一处后，那一段变回原文')
const left = rejected.field(roundDiffField).hunks
ok(left.length === 1, '剩下一处')
// diff 把公共后缀的句号对齐到了末尾，所以这处是从「。」开始的——内容等价
ok(rejected.doc.sliceString(left[0].from, left[0].to) === '。还要留出测试和修复的时间',
  `剩下那处的位置跟着撤回一起映射了（实际 ${JSON.stringify(rejected.doc.sliceString(left[0].from, left[0].to))}）`)

// —— 用户在新增里打字：标记要跟着走，不能消失 ——
const h1 = state.field(roundDiffField).hunks[1]
const typed = state.update({ changes: { from: h1.to, insert: '补一句。' } }).state
const after = typed.field(roundDiffField).hunks
ok(after.length === 2, '用户打字后标记还在（第一版是"文档一变就全丢"）')
ok(typed.doc.sliceString(after[1].from, after[1].to).endsWith('补一句。'),
  '在新增末尾补的字算在这处改动里面')

// —— 全部接受 ——
ok(state.update({ effects: acceptAllHunks.of(null) }).state
  .field(roundDiffField).hunks.length === 0, '全部接受后一处不剩')

// —— 用户把新增整段删掉 = 等于撤回 ——
const wiped = state.update({ changes: { from: h1.from, to: h1.to, insert: '' } }).state
ok(wiped.field(roundDiffField).hunks.length === 1, '新增被用户整段删光后，那一处自动消失')

console.log(bad ? `\n✗ ${bad} 项没通过` : '\n状态层：通过')
if (bad) process.exit(1)
