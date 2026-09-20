// @vitest-environment jsdom
/**
 * P68 A：**同步进编辑器的那一份不再回声回去**（`editor/syncEcho.ts`）。
 *
 * 实拍（打包壳 · 真 CM · 假模型 `--mode adv` 三轮 · 482 篇老用户库）：后端交出去并且
 * 已经 commit 进库的是 1103 字，编辑器里只剩 807，1.5 秒后自动保存**把 807 写回了库**，
 * 把后端刚落的那一份盖掉。同一屏上收工那行写着「+1060 字」——那个数是对的，
 * 丢字的是正文（P64 问题 #1 / P66 问题 #1 三批都把方向记反了）。
 *
 * 三条闸，各测一件事：
 *   ① 回声：我们同步过去的那一份原样回来 → **不报给 React**（这一条是修复本身）
 *   ② 没被吃掉：CM 在同一条事务上又改了一道（结果跟我们发过去的不一样）→ **照报**
 *   ③ 用户自己打的字 → **照报**（回声那条判据不许把它一起吞了）
 * 外加一条**接线洞**断言：`MarkdownEditor` 真的两头都接上了
 *   （只加标注不判、或只判不加标注，上面三条都还是绿的）。
 */
import { describe, expect, it } from 'vitest'
import { EditorState, Transaction } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import editorSrc from '../../components/MarkdownEditor.tsx?raw'
import { syncedFromApp, isAppEcho } from '../syncEcho'

/** 建一个真 CM，把每次 docChanged 时 `isAppEcho` 的答案记下来。 */
function harness(doc: string) {
  const seen: { text: string; echo: boolean }[] = []
  const view = new EditorView({
    state: EditorState.create({
      doc,
      extensions: [EditorView.updateListener.of((u) => {
        if (!u.docChanged) return
        const text = u.state.doc.toString()
        seen.push({ text, echo: isAppEcho(u, text) })
      })],
    }),
  })
  return { view, seen }
}

describe('P68 A：content → 编辑器 的同步不再回声', () => {
  it('① 同步过去的那一份原样落地 → 认成回声（不报给 React）', () => {
    const { view, seen } = harness('起点')
    const next = '起点，又写了一段'
    view.dispatch({ changes: { from: 2, insert: '，又写了一段' }, annotations: [syncedFromApp.of(next)] })
    expect(seen).toHaveLength(1)
    expect(seen[0].text).toBe(next)
    expect(seen[0].echo).toBe(true)
  })

  it('② CM 又改了一道、结果跟发过去的不一样 → 不算回声，照报', () => {
    const { view, seen } = harness('起点')
    // 我们以为会变成这一份，实际落地的是另一份（别的扩展在同一条事务上追加了改动）
    view.dispatch({
      changes: [{ from: 2, insert: '，又写了一段' }, { from: 0, insert: '# ' }],
      annotations: [syncedFromApp.of('起点，又写了一段')],
    })
    expect(seen).toHaveLength(1)
    expect(seen[0].text).toBe('# 起点，又写了一段')
    expect(seen[0].echo).toBe(false)
  })

  it('③ 用户自己打的字 → 不算回声，照报', () => {
    const { view, seen } = harness('起点')
    view.dispatch({ changes: { from: 2, insert: '啊' }, userEvent: 'input.type' })
    expect(seen).toHaveLength(1)
    expect(seen[0].echo).toBe(false)
  })

  it('④ 一条真实的流式序列：回声不再把「刚到的那一片」盖回上一片', () => {
    // P68 实拍的形状：同步 A → 回声 A（被扔掉）→ 同步 B（更长）→ 回声 B（被扔掉）。
    // 报上去的次数 = 0，于是 React 那边的 content 完全由 App 自己说了算，
    // 没有任何一次「上一片的回声」排在「下一片」后面。
    const { view, seen } = harness('')
    let now = ''
    for (const piece of ['第一片', '第二片', '第三片']) {
      now += piece
      view.dispatch({ changes: { from: view.state.doc.length, insert: piece },
                      annotations: [syncedFromApp.of(now)] })
    }
    expect(view.state.doc.toString()).toBe('第一片第二片第三片')
    expect(seen.map((s) => s.echo)).toEqual([true, true, true])
  })

  it('⑤ 接线洞：`MarkdownEditor` 两头都真的接上了（只接一头三条闸照样全绿）', () => {
    const src = editorSrc
    expect(src).toMatch(/syncedFromApp\.of\(content\)/)          // 同步那一下带上标注
    expect(src).toMatch(/if \(!isAppEcho\(update, text\)\) liveRef\.current\.onChange/)  // 回声那一头判它
  })

  it('⑥ 标注带的是「同步过去的那一份」，不是一个布尔（换成布尔，② 就分不出来了）', () => {
    const st = EditorState.create({ doc: 'x' })
    const tr = st.update({ changes: { from: 1, insert: 'y' }, annotations: [syncedFromApp.of('xy')] })
    expect(tr.annotation(syncedFromApp)).toBe('xy')
    expect(tr.annotation(Transaction.userEvent)).toBeUndefined()
  })
})
