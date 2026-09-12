import { describe, expect, it } from 'vitest'
import { EditorState } from '@codemirror/state'
import { marginField, paragraphsWithLines, setMarginMarks } from '../marginMemory'

describe('边缘记忆', () => {
  it('段落切分给出段首行号', () => {
    expect(paragraphsWithLines('# 标题\n\n第一段\n第二行\n\n\n第二段\n')).toEqual([
      { text: '# 标题', line: 1 }, { text: '第一段\n第二行', line: 3 }, { text: '第二段', line: 7 },
    ])
  })
  it('行号跟着文档改动映射', () => {
    let s = EditorState.create({ doc: 'a\n\nb 420mAh\n', extensions: [marginField] })
    s = s.update({ effects: setMarginMarks.of([{ line: 3, relation: 'conflict', say: 'x' }]) }).state
    s = s.update({ changes: { from: 0, insert: '新的一行\n\n' } }).state
    expect(s.field(marginField)[0].line).toBe(5)
  })
})
