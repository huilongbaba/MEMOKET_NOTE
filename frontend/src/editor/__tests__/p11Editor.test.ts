// @vitest-environment jsdom
/** P11：智能续写的撤销封装（`docs/TRACELOG-product.md` P11 #2）。
 *
 *   一轮智能续写 = 修订（多处 replace / delete）+ 续写（插一段）。跑的时候编辑器只读，content 同步进来的
 *   每一片都带 `aiSyncSpec(fresh)`：一轮的第一片 `isolateHistory('before')` 另起一条撤销事件，之后每一片
 *   `input.type.compose` 并进它（CM 对 compose 事件无视 500ms 分组和相邻与否）。于是一轮 = 一条：
 *   ⌘Z 一次撤一轮、两轮就两次、第三次才轮到用户自己的字；⇧⌘Z 逐轮回来。
 */
import { describe, expect, it } from 'vitest'
import { EditorState, Transaction } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { history, undo, redo } from '@codemirror/commands'

import { aiSyncSpec } from '../undoUnit'
import editorSrc from '../../components/MarkdownEditor.tsx?raw'
import appSrc from '../../App.tsx?raw'

function mkView(doc: string): EditorView {
  const parent = document.createElement('div')
  document.body.appendChild(parent)
  return new EditorView({ state: EditorState.create({ doc, extensions: [history()] }), parent })
}
/** 像 `MarkdownEditor` 只读时那样往编辑器里落一处改动（`fresh` = 这一轮的第一片） */
function land(v: EditorView, from: number, to: number, insert: string, t: number, fresh = false) {
  const spec = aiSyncSpec(fresh)
  v.dispatch({ changes: { from, to, insert }, userEvent: spec.userEvent, annotations: [...(spec.annotations as never[] ?? []), Transaction.time.of(t)] })
}

const USER = '用户写的第一段。\n\n用户写的第二段，里面有一句要被修订的话。\n'

describe('P11 #2 一轮智能续写（修订 + 续写，多处）= 一个撤销单位', () => {
  it('两轮各一条：⌘Z 第一次撤第 2 轮、第二次撤第 1 轮、第三次才吃用户的字；⇧⌘Z 逐轮回来', () => {
    const v = mkView('')
    // 用户自己打的字（记历史），跟 AI 的第一片只隔 100ms——不许被并进去
    v.dispatch({ changes: { from: 0, insert: USER }, userEvent: 'input.type', annotations: Transaction.time.of(1000) })
    expect(v.state.doc.toString()).toBe(USER)

    // ---- 第 1 轮：轮初预留空行（第一片，另起一条）+ 四片续写（各隔 900ms）
    let t = 1100
    land(v, v.state.doc.length, v.state.doc.length, '\n', t, true)
    for (const piece of ['第一轮', '写的', '第一片', '第二片。']) { t += 900; land(v, v.state.doc.length, v.state.doc.length, piece, t) }
    const after1 = v.state.doc.toString()
    expect(after1).toBe(USER + '\n第一轮写的第一片第二片。')

    // ---- 第 2 轮：一处修订（改用户段落里的一句）+ 一处删除（第 1 轮的半句）+ 续写一段
    t += 30_000
    const at = v.state.doc.toString().indexOf('要被修订的话')
    land(v, at, at + '要被修订的话'.length, '修订过的话', t, true)
    const cut = v.state.doc.toString().indexOf('第二片。')
    land(v, cut, cut + '第二片。'.length, '', t + 900)
    for (const piece of ['\n\n第二轮', '续写的一段。']) { t += 900; land(v, v.state.doc.length, v.state.doc.length, piece, t) }
    const after2 = v.state.doc.toString()
    expect(after2).toBe('用户写的第一段。\n\n用户写的第二段，里面有一句修订过的话。\n\n第一轮写的第一片\n\n第二轮续写的一段。')

    // ⌘Z ×1：第 2 轮整轮回去（修订、删除、续写三处一起）
    undo(v); expect(v.state.doc.toString()).toBe(after1)
    // ⌘Z ×2：第 1 轮整轮回去（含预留的那个空行）
    undo(v); expect(v.state.doc.toString()).toBe(USER)
    // ⌘Z ×3：才轮到用户自己的字
    undo(v); expect(v.state.doc.toString()).toBe('')
    // ⇧⌘Z 逐轮回来
    redo(v); expect(v.state.doc.toString()).toBe(USER)
    redo(v); expect(v.state.doc.toString()).toBe(after1)
    redo(v); expect(v.state.doc.toString()).toBe(after2)
    v.destroy()
  })

  it('修前的形状：片段按默认记历史，⌘Z 是片段级——钉住为什么要 compose 并组', () => {
    const v = mkView(USER)
    let t = 1000
    for (const piece of ['\n', '第一片', '第二片', '第三片']) { t += 900; v.dispatch({ changes: { from: v.state.doc.length, insert: piece }, annotations: Transaction.time.of(t) }) }
    undo(v)
    expect(v.state.doc.toString()).toBe(USER + '\n第一片第二片')     // 只撤掉最后一片
    v.destroy()
  })

  it('aiSyncSpec：第一片另起一条（isolateHistory before + input.ai），后面的是 input.type.compose', () => {
    expect(aiSyncSpec(true).userEvent).toBe('input.ai')
    expect(aiSyncSpec(true).annotations).toHaveLength(1)
    expect(aiSyncSpec(false)).toEqual({ userEvent: 'input.type.compose' })
  })

  it('MarkdownEditor：只读（AI 在写）时 content 同步带 aiSyncSpec；App 每一轮开跑 undoGroup 加一（在预留空行之前）', () => {
    expect(editorSrc).toMatch(/const fresh = freshRef\.current \|\| undoGroup !== lastGroup\.current/)
    expect(editorSrc).toMatch(/\.\.\.\(ai \? aiSyncSpec\(fresh\) : \{\}\)/)   // P13 #5 起 `ai = readOnly || aiRef.current`
    expect(editorSrc).toMatch(/if \(readOnly\) freshRef\.current = true/)
    const bump = appSrc.indexOf('setUndoGroup((g) => g + 1)')
    const spare = appSrc.indexOf("c.replace(/\\n*$/, '') + '\\n\\n'", bump)
    expect(bump).toBeGreaterThan(0)
    expect(spare).toBeGreaterThan(bump)
    expect(appSrc).toMatch(/undoGroup=\{undoGroup\}/)
    // 意图随智能续写的请求带过去（P11 #1）
    expect(appSrc).toMatch(/reviewEachRound,\s*\n\s*intentText\(intent\)/)
  })
})
