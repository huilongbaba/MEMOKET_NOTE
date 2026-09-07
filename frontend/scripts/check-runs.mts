/** 「正在跑」占位块的状态层自测。
 *
 *     npx tsx scripts/check-runs.mts
 *
 * 重点在两件原来做不到的事：**同时跑好几个**、以及**位置跟着文档编辑映射**。
 * 原来是一个全局 slashBusy + 一个 AbortController ref，第二个 `/` 一开始就把
 * 第一个顶掉了。
 */
import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'

import {
  appendPreview, endRun, logRun, patchRun, runningBlocks, runsField, startRun, toggleRun,
} from '../src/editor/runningBlocks.ts'

let bad = 0
const ok = (c: unknown, m: string) => { console.log(`${c ? '✓' : '✗'} ${m}`); if (!c) bad++ }

const mk = (doc: string) => EditorState.create({ doc, extensions: [runningBlocks(() => {})] })
const runs = (s: EditorState) => s.field(runsField)

// —— 并发 ——
let st = mk('第一段。\n\n第二段。\n')
st = st.update({ effects: startRun.of({ id: 'a', from: 0, label: '智能插图' }) }).state
st = st.update({ effects: startRun.of({ id: 'b', from: 10, label: '智能 EDA' }) }).state
ok(runs(st).length === 2, '两个可以同时跑')
ok(runs(st).map((r) => r.label).join(',') === '智能插图,智能 EDA', '各自带着自己的标签')

// —— 位置映射：在第一个占位块前面插字，两个的落点都要跟着动 ——
const before = runs(st).map((r) => r.from)
st = st.update({ changes: { from: 0, insert: '插在最前面。' } }).state
const after = runs(st).map((r) => r.from)
ok(after[0] === before[0] + 6 && after[1] === before[1] + 6,
  `位置跟着文档改动映射（${before} → ${after}）`)

// —— 状态更新只影响对应的那个 ——
st = st.update({ effects: patchRun.of({ id: 'a', phase: '在查知识库…' }) }).state
ok(runs(st).find((r) => r.id === 'a')?.phase === '在查知识库…', 'phase 更新到位')
ok(runs(st).find((r) => r.id === 'b')?.phase === '', '不影响另一个')

st = st.update({ effects: appendPreview.of({ id: 'a', text: '前半段' }) }).state
st = st.update({ effects: appendPreview.of({ id: 'a', text: '后半段' }) }).state
ok(runs(st).find((r) => r.id === 'a')?.preview === '前半段后半段', '预览是累加的')

st = st.update({ effects: logRun.of({ id: 'a', at: '查', text: 'list_tables' }) }).state
ok(runs(st).find((r) => r.id === 'a')?.log.length === 1, '日志记下来了')

// —— 展开/收起 ——
ok(runs(st).find((r) => r.id === 'a')?.expanded === false, '默认收起')
st = st.update({ effects: toggleRun.of('a') }).state
ok(runs(st).find((r) => r.id === 'a')?.expanded === true, '点一下展开')

// —— 结束只清掉自己 ——
st = st.update({ effects: endRun.of('a') }).state
ok(runs(st).length === 1 && runs(st)[0].id === 'b', '结束一个不影响另一个')

// —— 装饰真的产生了，widget 的 DOM 也对 ——
//
// 不 new EditorView：jsdom 里没有 MutationObserver，CM6 的视图层起不来。
// 直接从 decorations facet 取装饰、调 widget 的 toDOM——要验的是"有没有渲染
// 出东西"，那部分不依赖视图。这套 UI 做坏过两版（构建通过但东西不出现）。
const { JSDOM } = await import('jsdom')
const dom = new JSDOM('<!doctype html><html><body></body></html>')
;(globalThis as any).document = dom.window.document

let s2 = mk('正文。\n')
s2 = s2.update({ effects: startRun.of({ id: 'x', from: 0, label: '智能表格' }) }).state
s2 = s2.update({ effects: patchRun.of({ id: 'x', phase: '在写…' }) }).state
const sets = s2.facet(EditorView.decorations)
  .map((v) => (typeof v === 'function' ? v({ state: s2 } as never) : v))
let widgetHtml = ''
for (const set of sets) {
  set.between(0, s2.doc.length, (_f, _t, d) => {
    const w = (d.spec as { widget?: { toDOM(v: unknown): HTMLElement } }).widget
    if (w && 'run' in (w as object)) widgetHtml = w.toDOM({ dispatch() {} }).outerHTML
  })
}
ok(widgetHtml.includes('cm-run-block'), '占位块渲染出 DOM')
ok(widgetHtml.includes('智能表格') && widgetHtml.includes('在写…'), '标签和阶段都显示出来了')
ok(widgetHtml.includes('cm-run-stop'), '有停止按钮')

let s3 = s2.update({ effects: toggleRun.of('x') }).state
s3 = s3.update({ effects: logRun.of({ id: 'x', at: '查', text: 'list_tables' }) }).state
let expanded = ''
for (const v of s3.facet(EditorView.decorations)) {
  const set = typeof v === 'function' ? v({ state: s3 } as never) : v
  set.between(0, s3.doc.length, (_f, _t, d) => {
    const w = (d.spec as { widget?: { toDOM(v: unknown): HTMLElement } }).widget
    if (w && 'run' in (w as object)) expanded = w.toDOM({ dispatch() {} }).outerHTML
  })
}
ok(expanded.includes('cm-run-body'), '展开后有详情区')
ok(expanded.includes('list_tables'), '详情里能看到调了哪些工具')

console.log(bad ? `\n✗ ${bad} 项没通过` : '\n占位块：通过')
if (bad) process.exit(1)
