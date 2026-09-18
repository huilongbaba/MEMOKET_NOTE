// @vitest-environment jsdom
/**
 * P13（`docs/TRACELOG-product.md` P13 节）：完成标准清单进 harness + P11 / P12 编辑器侧遗留。
 *
 *   1. 完成标准判定跟后端是同一份：`shared/done-cases.json` 一张表两边各跑一遍（这里跑前端那份；`DONE_RULES` 的字面
 *      由后端 `tests/test_p13.py` 逐条核对）；`DONE_RULES.cite` 就是 `CITE_RE_SOURCE`
 *   2. 「每条」的单位：紧跟在列表项后面的段落算给那一条（周会「要点列表 + 展开段」原来 7/7 没出处）
 *   3. 目录：滚到底 / 刚点过的那一节，高亮不再是上一节（`activeHeadingPos`）
 *   4. ⌘E 行内代码 / ⇧⌘X 删除线，进快捷键表
 *   5. 「续写」和「智能续写」的撤销是一套机制（`aiSyncSpec`）、两个入口——两个入口都是 1 轮 = 1 次 ⌘Z；
 *      `sealAsOneUndo` / `undoSeal` 从代码里删干净
 */


import { describe, expect, it } from 'vitest'
import { EditorSelection, EditorState, Transaction } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { history, undo, redo } from '@codemirror/commands'

import { DONE_RULES, checkDoneItem, splitDone, units } from '../../util/doneChecks'
import { CITE_RE_SOURCE } from '../../util/wordCount'
import { activeHeadingPos } from '../../components/DocumentOutline'
import { inlineCodeCmd, markdownKeymap, strikeCmd } from '../markdownCommands'
import { SHORTCUT_GROUPS } from '../../shortcuts'
import { aiSyncSpec } from '../undoUnit'
import editorSrc from '../../components/MarkdownEditor.tsx?raw'
import appSrc from '../../App.tsx?raw'
import undoSrc from '../undoUnit.ts?raw'
import casesJson from '../../../../shared/done-cases.json'

type Case = { name: string; item: string; content: string; expect: { status: string; why: string } | null }
const table = casesJson as unknown as {
  contents: Record<string, string>; cases: Case[]; units: { name: string; content: string; kind: string; texts: string[] }[]; split: { done: string; items: string[] }[]
}

describe('P13 #1 完成标准判定：前端按共享用例表（后端跑同一张表）', () => {
  it.each(table.cases.map((c) => [c.name, c] as const))('%s', (_n, c) => {
    const r = checkDoneItem(c.item, table.contents[c.content])
    expect(r ? { status: r.status, why: r.why } : null).toEqual(c.expect)
  })
  it.each(table.split.map((s) => [s.done, s] as const))('拆条 %j', (_d, s) => { expect(splitDone(s.done)).toEqual(s.items) })
  it('引用正则就是 wordCount 那一份源（不另抄一份漂掉）', () => { expect(DONE_RULES.cite).toBe(CITE_RE_SOURCE) })
})

describe('P13 #2 「每条」的单位：紧跟列表项的段落算给那一条', () => {
  it.each(table.units.map((u) => [u.name, u] as const))('%s', (_n, u) => {
    expect(units(table.contents[u.content])).toEqual({ kind: u.kind, texts: u.texts })
  })
  it('周会：修前 7 条里 7 条没出处 → 修后 5 条（展开段的两处出处算给了它们前面那一条）', () => {
    expect(checkDoneItem('每条进展有出处', table.contents['周会'])).toEqual({ status: 'fail', why: '7 条里 5 条没有出处' })
    // 修前的形状：只看列表项那一行
    const bare = table.contents['周会'].split('\n').filter((l) => /^\s*-\s/.test(l)).join('\n')
    expect(checkDoneItem('每条进展有出处', bare)).toEqual({ status: 'fail', why: '7 条里 7 条没有出处' })
  })
})

describe('P13 #3 目录：点最后一节高亮的是上一节', () => {
  const H = [{ pos: 0 }, { pos: 100 }, { pos: 200 }, { pos: 300 }]
  it('老规则：顶上那一行属于哪一节', () => {
    expect(activeHeadingPos(H, 150, 250, false)).toBe(100)
    expect(activeHeadingPos(H, 0, 50, false)).toBe(0)
    expect(activeHeadingPos([], 10, 20, false)).toBe(-1)
  })
  it('滚到底了：亮视口里最后一个标题（文末那一节短到撑不满一屏，顶上那一行永远属于上一节）', () => {
    expect(activeHeadingPos(H, 250, 340, false)).toBe(200)    // 修前
    expect(activeHeadingPos(H, 250, 340, true)).toBe(300)     // 修后
  })
  it('刚点过的那一节：标题还在视口里就亮它；滚走了才交回老规则', () => {
    expect(activeHeadingPos(H, 250, 340, false, 300)).toBe(300)
    expect(activeHeadingPos(H, 150, 250, false, 200)).toBe(200)
    expect(activeHeadingPos(H, 0, 90, false, 300)).toBe(0)     // 300 不在视口里
    expect(activeHeadingPos(H, 150, 250, false, 999)).toBe(100) // 不是目录里的标题
  })
})

function mkView(doc: string): EditorView {
  const parent = document.createElement('div')
  document.body.appendChild(parent)
  return new EditorView({ state: EditorState.create({ doc, extensions: [history()] }), parent })
}

describe('P13 #4 ⌘E 行内代码 / ⇧⌘X 删除线', () => {
  it('选中再按是包上，已经包着的再按一次是去掉', () => {
    const v = mkView('abc')
    v.dispatch({ selection: EditorSelection.range(0, 3) })
    strikeCmd(v); expect(v.state.doc.toString()).toBe('~~abc~~')
    strikeCmd(v); expect(v.state.doc.toString()).toBe('abc')
    inlineCodeCmd(v); expect(v.state.doc.toString()).toBe('`abc`')
    inlineCodeCmd(v); expect(v.state.doc.toString()).toBe('abc')
    v.destroy()
  })
  it('键绑在 markdownKeymap 上（Mod-e / Mod-Shift-x），且快捷键表里查得到', () => {
    const v = mkView('abc')
    v.dispatch({ selection: EditorSelection.range(0, 3) })
    const e = markdownKeymap.find((k) => k.key === 'Mod-e')!
    const x = markdownKeymap.find((k) => k.key === 'Mod-Shift-x')!
    expect(e.run(v)).toBe(true); expect(v.state.doc.toString()).toBe('`abc`')
    e.run(v); expect(v.state.doc.toString()).toBe('abc')
    expect(x.run(v)).toBe(true); expect(v.state.doc.toString()).toBe('~~abc~~')
    v.destroy()
    const keys = SHORTCUT_GROUPS.flatMap((g) => g.items.map((i) => i.keys))
    expect(keys.some((k) => /⌘E/.test(k))).toBe(true)
    expect(keys.some((k) => /⇧⌘X/.test(k))).toBe(true)
  })
})

/** 像 `MarkdownEditor` 只读时那样往编辑器里落一处改动（`fresh` = 这一轮的第一片） */
function land(v: EditorView, from: number, to: number, insert: string, t: number, fresh = false) {
  const spec = aiSyncSpec(fresh)
  v.dispatch({ changes: { from, to, insert }, userEvent: spec.userEvent, annotations: [...(spec.annotations as never[] ?? []), Transaction.time.of(t)] })
}
const USER = '用户写的第一段。\n\n用户写的第二段。\n'

describe('P13 #5 一套机制、两个入口：「续写」和「智能续写」的撤销都是 1 轮 = 1 次', () => {
  it('入口一「续写」：四片各隔 900ms + 3 秒后修粗体标点的收尾一笔 → ⌘Z 一次回到开跑前，第二次才吃用户的字', () => {
    const v = mkView('')
    v.dispatch({ changes: { from: 0, insert: USER }, userEvent: 'input.type', annotations: Transaction.time.of(1000) })
    let t = 1100
    land(v, v.state.doc.length, v.state.doc.length, '\n\n第一片', t, true)       // head 补的空行也在这一片里
    for (const piece of ['第二片', '**标题：**第三片', '第四片。']) { t += 900; land(v, v.state.doc.length, v.state.doc.length, piece, t) }
    // 流完 3 秒后 fixBoldPunct 把「**标题：**」修成「**标题**：」——只读刚结束那一帧的同步，仍按 AI 的字并进去
    t += 3000
    const at = v.state.doc.toString().indexOf('**标题：**')
    land(v, at, at + '**标题：**'.length, '**标题**：', t)
    const after = v.state.doc.toString()
    expect(after).toBe(USER + '\n\n第一片第二片**标题**：第三片第四片。')
    undo(v); expect(v.state.doc.toString()).toBe(USER)
    undo(v); expect(v.state.doc.toString()).toBe('')
    redo(v); redo(v); expect(v.state.doc.toString()).toBe(after)
    v.destroy()
  })
  it('入口二「智能续写」：两轮（每轮修订 + 续写多处）→ ⌘Z 两次回到开跑前，第三次才吃用户的字', () => {
    const v = mkView(USER)
    let t = 1100
    land(v, v.state.doc.length, v.state.doc.length, '\n', t, true)
    for (const piece of ['第一轮', '写的。']) { t += 900; land(v, v.state.doc.length, v.state.doc.length, piece, t) }
    const after1 = v.state.doc.toString()
    t += 30_000
    const at = v.state.doc.toString().indexOf('第二段')
    land(v, at, at + 3, '第二段（修订）', t, true)
    for (const piece of ['\n\n第二轮', '写的。']) { t += 900; land(v, v.state.doc.length, v.state.doc.length, piece, t) }
    undo(v); expect(v.state.doc.toString()).toBe(after1)
    undo(v); expect(v.state.doc.toString()).toBe(USER)
    v.destroy()
  })
  it('接线：只读刚结束那一帧仍按 AI 的字并组（aiRef）；sealAsOneUndo / undoSeal 从代码里删干净', () => {
    expect(editorSrc).toMatch(/const ai = readOnly \|\| aiRef\.current/)
    expect(editorSrc).toMatch(/\.\.\.\(ai \? aiSyncSpec\(fresh\) : \{\}\)/)
    expect(editorSrc).toMatch(/aiRef\.current = readOnly/)
    expect(editorSrc).not.toMatch(/undoSeal|sealAsOneUndo/)
    expect(appSrc).not.toMatch(/undoSeal|sealAsOneUndo/)
    // 收工那句「「X」这条判据连响 N 轮」里的判据名走 checkLabel（实拍「done_criteria」原样蹦出来）
    expect(appSrc).toMatch(/checkLabel\(stuckCheckRef\.current\.check\)/)
    expect(undoSrc).not.toMatch(/export function sealAsOneUndo/)
    // 「续写」跑的时候编辑器只读（这就是它跟智能续写走同一套的前提）
    expect(appSrc).toMatch(/readOnly=\{loading === 'note-harness' \|\| loading === 'tap'/)
  })
})
