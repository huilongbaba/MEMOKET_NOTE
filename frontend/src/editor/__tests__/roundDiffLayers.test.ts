import { describe, expect, it } from 'vitest'
import { EditorState } from '@codemirror/state'
import { acceptLayer, addLayer, diffParts, dropHunk, roundDiffField } from '../roundDiff'

function mk(doc: string) { return EditorState.create({ doc, extensions: [roundDiffField] }) }
import { minimalChange } from '../minimalChange'
function push(state: EditorState, label: string, before: string, after: string) {
  // 只换真正变了的那一段（上层走 minimalChange）：整篇替换会把旧层的位置全映射到一个点上，旧层就没了
  const change = minimalChange(before, after)
  return state.update({ changes: change ?? [], effects: addLayer.of({ label, parts: diffParts(before, after) }) }).state
}

describe('提案分层', () => {
  it('两次动作是两层，各自记着自己的 hunk', () => {
    let s = mk('甲乙丙丁')
    s = push(s, '润色', '甲乙丙丁', '甲乙X丙丁')
    s = push(s, '重写', '甲乙X丙丁', '甲乙X丙丁Y')
    const st = s.field(roundDiffField)
    expect(st.layers.map((l) => l.label)).toEqual(['润色', '重写'])
    expect(st.hunks.length).toBe(2)
    expect(new Set(st.hunks.map((h) => h.layer)).size).toBe(2)
  })
  it('接受一层只摘那层；撤回另一层把文档还原', () => {
    let s = mk('甲乙丙丁')
    s = push(s, '润色', '甲乙丙丁', '甲乙X丙丁')
    s = push(s, '重写', '甲乙X丙丁', '甲乙X丙丁Y')
    const [l1, l2] = s.field(roundDiffField).layers
    s = s.update({ effects: acceptLayer.of(l1.id) }).state
    expect(s.field(roundDiffField).layers.map((l) => l.id)).toEqual([l2.id])
    // 撤回 l2：把它的 hunk 还原
    const h = s.field(roundDiffField).hunks.find((x) => x.layer === l2.id)!
    s = s.update({ changes: { from: h.from, to: h.to, insert: h.del }, effects: dropHunk.of(h.id) }).state
    expect(s.doc.toString()).toBe('甲乙X丙丁')
    expect(s.field(roundDiffField).layers).toEqual([])
  })
  it('replace 会清掉已有的层（智能续写的累积 diff）', () => {
    let s = mk('甲乙丙丁')
    s = push(s, '润色', '甲乙丙丁', '甲乙X丙丁')
    s = s.update({ effects: addLayer.of({ label: '智能续写', parts: diffParts('甲乙X丙丁', '甲乙X丙丁'), replace: true }) }).state
    expect(s.field(roundDiffField).layers).toEqual([])
  })
})
